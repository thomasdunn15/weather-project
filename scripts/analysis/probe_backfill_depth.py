#!/usr/bin/env python
"""
P0 backfill-depth probe  ---  READ-ONLY, scratch (do not commit to production).

Goal: decide, empirically via Herbie, whether each candidate forecast model can be
backfilled deep enough to validate on our ~26-month window (VALIDATE-NOW) or is
forward-collect-only (FORWARD-COLLECT).

It does NOT touch the DB or any production/trading code.

Resource discipline (constrained box: 7.6 GB RAM, no swap):
  * Stage A = existence-only.  Constructing Herbie(...) runs a *source find* (cheap
    HEAD/range request per source) and sets H.grib if the file exists.  NO full GRIB
    download.  We probe each source separately to measure per-mirror archive depth.
  * Stage B = inventory-only (.idx/.index is tiny) on the most-recent hit per model
    to read the exact 2 m-temperature / daily-Tmax variable naming, PLUS one real
    subset download + xarray + station extract for NBM only (the recommended model)
    to prove end-to-end fetch.
  * Everything is written under an isolated save_dir which is purged at the end.

Run (use the already-synced main venv; run the worktree copy of this file):
  cd /home/tdunn/weather-project && \
  uv run python /home/tdunn/wt-p0-probe/scripts/analysis/probe_backfill_depth.py
"""

import os
import socket
import shutil
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
socket.setdefaulttimeout(30)  # don't hang on a dead mirror

from herbie import Herbie  # noqa: E402

SAVE_DIR = os.path.expanduser("~/data/_p0_probe")  # isolated; purged at end

# 6 historical init dates (00Z) spanning our window + a tail near "now".
PROBE_DATES = [
    "2026-06-13", "2026-05-20", "2026-03-20",
    "2025-12-20", "2025-06-20", "2024-06-20",
]
# Extra recent date used ONLY to prove the live (24 h-retention) templates work at all.
RECENT_DATE = "2026-06-20"

# label -> (Herbie kwargs, ordered candidate sources to test individually, extra dates)
MODELS = [
    ("NBM-core",    dict(model="nbm",    product="co",                 fxx=24),
     ["aws", "nomads"], []),
    ("NBM-qmd",     dict(model="nbmqmd", product="co",                 fxx=24),
     ["aws", "nomads"], []),
    ("AIFS-Single", dict(model="aifs",   product="oper",               fxx=24),
     ["google", "aws", "azure", "ecmwf"], []),
    ("AIFS-ENS",    dict(model="aifs",   product="enfo",               fxx=24),
     ["google", "aws", "azure", "ecmwf"], []),
    ("GEM-GDPS",    dict(model="gdps",   product="15km/grib2/lat_lon", fxx=24,
                        variable="TMP", level="TGL_2"),
     ["msc"], [RECENT_DATE]),  # add today to show template works while archive doesn't
]

# KORD for the NBM end-to-end station-extract proof (lat, lon).
KORD = (41.99, -87.93)


def probe_source(date, kwargs, source):
    """Return (found: bool, grib_url_or_None, note)."""
    try:
        H = Herbie(date, priority=[source], save_dir=SAVE_DIR, verbose=False, **kwargs)
        grib = getattr(H, "grib", None)
        return (grib is not None), grib, ""
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {str(e)[:120]}"


def stage_a():
    print("=" * 78)
    print("STAGE A  --  existence-only depth probe (no GRIB download)")
    print("=" * 78)
    # most-recent hit per model -> (label) : (date, source, kwargs)
    best_hit = {}
    for label, kwargs, sources, extra in MODELS:
        dates = list(extra) + list(PROBE_DATES)  # recent first
        print(f"\n### {label}  kwargs={kwargs}")
        for date in dates:
            row = []
            hit_src = None
            for src in sources:
                found, url, note = probe_source(date, kwargs, src)
                row.append(f"{src}={'OK' if found else '--'}")
                if found and hit_src is None:
                    hit_src = src
                if note:
                    row.append(f"({src} err {note})")
            tag = "FOUND" if hit_src else "miss "
            print(f"  RESULT|{label}|{date}|{tag}|{'  '.join(row)}")
            if hit_src and label not in best_hit and date in PROBE_DATES:
                best_hit[label] = (date, hit_src, kwargs)
        # also remember a hit even if only the RECENT/extra date worked
        if label not in best_hit:
            for date in dates:
                for src in sources:
                    found, _, _ = probe_source(date, kwargs, src)
                    if found:
                        best_hit[label] = (date, src, kwargs)
                        break
                if label in best_hit:
                    break
    return best_hit


def stage_b(best_hit):
    print("\n" + "=" * 78)
    print("STAGE B  --  inventory-only variable discovery (+ NBM end-to-end)")
    print("=" * 78)
    temp_pat = ("tmp", "tmax", "2 m", "2m", "2t", "maxt", "temperature", "tgl_2")
    for label, kwargs, sources, extra in MODELS:
        if label not in best_hit:
            print(f"\n### {label}: no hit anywhere -> skip inventory")
            continue
        date, src, _ = best_hit[label]
        print(f"\n### {label}: inventory @ {date} via {src}")
        try:
            H = Herbie(date, priority=[src], save_dir=SAVE_DIR, verbose=False, **kwargs)
            inv = H.inventory()
            cols = [c for c in inv.columns]
            print(f"  inventory rows={len(inv)} cols={cols}")
            txt = inv.astype(str)
            mask = txt.apply(lambda r: any(p in " ".join(r.values).lower() for p in temp_pat), axis=1)
            hits = inv[mask]
            print(f"  temp-related rows={len(hits)} (showing up to 18):")
            for _, r in hits.head(18).iterrows():
                print("    VAR| " + " | ".join(str(r[c]) for c in cols))
        except Exception as e:  # noqa: BLE001
            print(f"  inventory FAILED: {type(e).__name__}: {str(e)[:160]}")

    # NBM end-to-end: real subset download + xarray + KORD nearest-neighbor extract.
    if "NBM-core" in best_hit:
        date, src, kwargs = best_hit["NBM-core"]
        print(f"\n### NBM-core end-to-end @ {date} via {src} (real subset fetch)")
        try:
            H = Herbie(date, priority=[src], save_dir=SAVE_DIR, verbose=False, **kwargs)
            ds = H.xarray(":TMP:2 m above ground:", remove_grib=False)
            if isinstance(ds, list):
                ds = ds[0]
            import numpy as np
            lat = np.asarray(ds["latitude"].values)
            lon = np.asarray(ds["longitude"].values)
            lon180 = np.where(lon > 180, lon - 360, lon)
            d2 = (lat - KORD[0]) ** 2 + (lon180 - KORD[1]) ** 2
            iy, ix = np.unravel_index(int(np.argmin(d2)), d2.shape)
            tvar = [v for v in ds.data_vars if v.lower() in ("t2m", "tmp", "2t")]
            tvar = tvar[0] if tvar else list(ds.data_vars)[0]
            val = float(np.asarray(ds[tvar].values)[iy, ix])
            units = ds[tvar].attrs.get("units", "?")
            print(f"  data_vars={list(ds.data_vars)}  grid_shape={lat.shape}")
            print(f"  KORD nearest cell -> {tvar}={val:.2f} {units} "
                  f"(grid lat={float(lat[iy, ix]):.3f} lon={float(lon180[iy, ix]):.3f})")
            print("  -> end-to-end station extraction WORKS for NBM.")
        except Exception as e:  # noqa: BLE001
            print(f"  end-to-end FAILED: {type(e).__name__}: {str(e)[:200]}")


def main():
    print(f"probe start (utc={datetime.utcnow().isoformat()})  save_dir={SAVE_DIR}")
    best_hit = stage_a()
    stage_b(best_hit)
    # cleanup
    if os.path.isdir(SAVE_DIR):
        shutil.rmtree(SAVE_DIR, ignore_errors=True)
        print(f"\npurged {SAVE_DIR}: exists={os.path.isdir(SAVE_DIR)}")
    print("probe done.")


if __name__ == "__main__":
    main()
