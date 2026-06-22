#!/usr/bin/env python
"""
P0 follow-up (READ-ONLY, scratch): capture exact daily-Tmax / 2 m-temp variable
strings via Herbie inventory (.idx/.index only -- tiny), and diagnose the GEM-GDPS
msc path (HEAD the constructed URL for today's run).

Run:
  cd /home/tdunn/weather-project && \
  uv run python /home/tdunn/wt-p0-probe/scripts/analysis/probe_vars.py
"""
import os
import socket
import shutil
import warnings

warnings.filterwarnings("ignore")
socket.setdefaulttimeout(30)

from herbie import Herbie  # noqa: E402

SAVE_DIR = os.path.expanduser("~/data/_p0_probe")
DATE = "2026-06-13"


def show(label, kwargs, source, patterns):
    print(f"\n### {label}  via {source}  kwargs={kwargs}")
    try:
        H = Herbie(DATE, priority=[source], save_dir=SAVE_DIR, verbose=False, **kwargs)
        inv = H.inventory()
        cols = list(inv.columns)
        txt = inv.astype(str)
        mask = txt.apply(
            lambda r: any(p in " ".join(map(str, r.values)).lower() for p in patterns),
            axis=1,
        )
        hits = inv[mask]
        print(f"  rows={len(inv)}  temp-rows={len(hits)}")
        # print the search_this column (the wgrib2/eccodes selector) + key fields
        for _, r in hits.head(40).iterrows():
            st = str(r.get("search_this", ""))
            var = str(r.get("variable", r.get("param", "")))
            lvl = str(r.get("level", r.get("levtype", "")))
            num = str(r.get("number", ""))
            print(f"    {var:>10} | lvl={lvl:>18} | num={num:>4} | {st}")
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED: {type(e).__name__}: {str(e)[:200]}")


def gdps_diag():
    import requests
    print("\n### GEM-GDPS path diagnostic (HEAD today's constructed msc URL)")
    for date in ("2026-06-20", "2026-06-19"):
        for fxx in (24,):
            try:
                H = Herbie(date, model="gdps", product="15km/grib2/lat_lon",
                           fxx=fxx, variable="TMP", level="TGL_2",
                           priority=["msc"], save_dir=SAVE_DIR, verbose=False)
                url = H.SOURCES["msc"]
                try:
                    code = requests.head(url, timeout=20, allow_redirects=True).status_code
                except Exception as e:  # noqa: BLE001
                    code = f"HEAD-err {type(e).__name__}"
                print(f"  {date} f{fxx:03d}: HTTP={code}")
                print(f"    URL={url}")
            except Exception as e:  # noqa: BLE001
                print(f"  {date} f{fxx:03d}: construct FAILED {type(e).__name__}: {str(e)[:120]}")
    # also probe the parent datamart dir for current GDPS layout
    for base in (
        "https://dd.weather.gc.ca/model_gem_global/15km/grib2/lat_lon/00/024/",
        "https://dd.weather.gc.ca/model_gem_global/15km/grib2/lat_lon/",
        "https://dd.weather.gc.ca/20260620/WXO-DD/model_gem_global/15km/grib2/lat_lon/00/024/",
    ):
        try:
            code = requests.head(base, timeout=20, allow_redirects=True).status_code
        except Exception as e:  # noqa: BLE001
            code = f"err {type(e).__name__}"
        print(f"  DIR HTTP={code}  {base}")


def main():
    # NBM core: instantaneous 2m temp + daily-max temp variable
    show("NBM-core", dict(model="nbm", product="co", fxx=24), "aws",
         ("tmp", "tmax", "2 m", "maxt", "apparent"))
    # NBM qmd: percentile temperature fields
    show("NBM-qmd", dict(model="nbmqmd", product="co", fxx=24), "aws",
         ("tmp", "tmax", "2 m", "maxt", "%"))
    # AIFS single: 2t at sfc
    show("AIFS-Single", dict(model="aifs", product="oper", fxx=24), "google",
         ("2t", "tmax", "2 m", "temperature"))
    # AIFS ens: 2t at sfc, member 'number'
    show("AIFS-ENS", dict(model="aifs", product="enfo", fxx=24), "google",
         ("2t", "tmax", "2 m", "temperature"))
    gdps_diag()
    if os.path.isdir(SAVE_DIR):
        shutil.rmtree(SAVE_DIR, ignore_errors=True)
        print(f"\npurged {SAVE_DIR}: exists={os.path.isdir(SAVE_DIR)}")
    print("vars-probe done.")


if __name__ == "__main__":
    main()
