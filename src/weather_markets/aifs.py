"""ECMWF-AIFS ensemble/deterministic forecast ingestion.

AIFS is ECMWF's data-driven (machine-learning) forecast, distributed on the SAME
ECMWF Open Data channel we already use for the physics-based IFS. It is the
research doc's #2 recommended addition: a *decorrelated* AI core whose errors
should be more independent of the GEFS/IFS physics ensemble than another physics
model would be.

Two products, both 0.25° global, both written to the shared `forecasts` table:

  AIFS-Single  (Herbie model='aifs', product='oper')  -> forecasts.model='aifs'
      One deterministic field. Stored as member_id=0.

  AIFS-ENS     (Herbie model='aifs', product='enfo')  -> forecasts.model='aifs_ens'
      50 perturbed members (`pf`), stored as member_id 1..50. (Herbie has no
      separate 'aifs_ens' model; the ENS stream is product='enfo' under model
      'aifs'. The single control `cf` file is NOT fetched — matching ecmwf.py's
      IFS-enfo treatment, which also scores on the 50 perturbed members.)

COARSE DAILY-MAX (flagged): AIFS publishes only INSTANTANEOUS 2 m temperature
(`2t`) on a 6-hourly grid (00/06/12/18/24h ...) and has NO native windowed-max
variable (unlike IFS's mx2t3). We therefore approximate the daily high as the
MAX over the 6-hourly samples that fall inside local day D — the same way
aggregation.compute_daily_highs takes MAX(tmax_f) over local-day valid times.
With only the 18Z and 24Z (= next-day 00Z) samples landing in the afternoon
window, the true sub-grid peak (often ~20-22Z) is under-sampled, so AIFS daily
highs run biased LOW vs IFS's mx2t3. The rolling-45-day EMOS fit absorbs that
systematic bias; the residual day-to-day sampling noise is the unavoidable cost
of 6-hourly instantaneous data and is the reason AIFS-Single is reported as a
COARSE source.

REGIME NOTE: AIFS-Single switched experimental -> operational on 2025-02-25
(inside our backfill window). ECMWF serves both eras from the same `oper` path,
so ingestion is uniform, but model behavior (and bias) may shift across that
date — a possible discontinuity the rolling EMOS window re-absorbs within ~45
days. Recorded here so it is not mistaken for a data bug.

Instantaneous 2t is written to BOTH temperature_f and tmax_f (mirrors hrrr.py):
tmax_f drives the daily-high MAX; temperature_f keeps the sample available to the
day-ahead-low path.

Read/ingest only; additive `forecasts` rows. No trading or EMOS code is touched.
"""
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from herbie import Herbie

from .db import get_connection
from .stations import get as get_station

# 6-hourly instantaneous-2t steps whose valid time lands in local day D's
# afternoon for every station from Eastern to Pacific (18Z and next-day 00Z).
# AIFS has no sub-6-hourly step, so these are the only afternoon samples
# available; MAX over them approximates the daily high (see module docstring).
DEFAULT_FORECAST_HOURS = [18, 24]

# AIFS-ENS publishes 50 perturbed members on the enfo stream. Fewer than this
# means a partial/stale GRIB — warn loudly (same guard as ecmwf.py).
EXPECTED_ENS_MEMBERS = 50

K_TO_F_OFFSET = 273.15


def kelvin_to_fahrenheit(k: float) -> float:
    return (k - K_TO_F_OFFSET) * 9 / 5 + 32


def lon_for_grid(grid_lon_min: float, grid_lon_max: float, station_lon: float) -> float:
    """Return the longitude to pass to .sel for this grid's convention.

    AIFS is -180..180, so a station's conventional negative longitude is used
    as-is. If the grid is instead 0..360 (min >= 0 and extends past 180), wrap
    the western longitude into 0..360 so .sel(method='nearest') doesn't snap to
    the wrong hemisphere. Pure helper so the convention is unit-tested.
    """
    if grid_lon_min >= 0 and grid_lon_max > 180:
        return station_lon % 360
    return station_lon


def build_rows(
    run_time: datetime,
    valid_time: datetime,
    station_id: str,
    model: str,
    member_temps_k,
) -> list[dict]:
    """Build `forecasts` row dicts from per-member Kelvin temps.

    member_temps_k: iterable of (member_id:int, temp_k:float). Each instantaneous
    2t sample is stored in BOTH temperature_f and tmax_f (see module docstring).
    Pure (no I/O) so the K->F conversion, model string and member ids are tested.
    """
    rows = []
    for member_id, temp_k in member_temps_k:
        temp_f = kelvin_to_fahrenheit(float(temp_k))
        rows.append({
            "init_time": run_time,
            "valid_time": valid_time,
            "station_id": station_id,
            "model": model,
            "member_id": int(member_id),
            "temperature_f": temp_f,
            "tmax_f": temp_f,
        })
    return rows


def _valid_time_utc(ds) -> datetime:
    return pd.Timestamp(ds.valid_time.values).to_pydatetime().replace(tzinfo=timezone.utc)


def _extract_member_temps_k(ds, key: str, lat: float, lon: float):
    """Return list of (member_id, temp_k) at the nearest grid point.

    Deterministic (oper) fields have no `number` dim -> single member 0.
    Ensemble (enfo) fields carry a `number` dim of perturbed members.
    """
    point = ds[key].sel(latitude=lat, longitude=lon, method="nearest")
    if "number" in ds.dims or "number" in getattr(ds, "coords", {}):
        # Read all members in ONE vectorized decode (point.values), aligned with
        # point's own `number` coord — far cheaper than 50 per-member .item()
        # calls (which dominated the ENS backfill at ~78s/day).
        nums = np.asarray(point["number"].values).ravel()
        vals = np.asarray(point.values).ravel()
        return [(int(n), float(v)) for n, v in zip(nums, vals)]
    return [(0, float(np.asarray(point.values).ravel()[0]))]


def ingest_aifs_run(
    run_time: datetime,
    station_id: str = "KORD",
    ensemble: bool = False,
    forecast_hours: list[int] | None = None,
) -> dict:
    """Ingest one AIFS run (one init, one station) into `forecasts`.

    ensemble=False -> AIFS-Single (product='oper', model='aifs', member 0).
    ensemble=True  -> AIFS-ENS    (product='enfo', model='aifs_ens', 50 members).
    """
    if forecast_hours is None:
        forecast_hours = DEFAULT_FORECAST_HOURS

    product = "enfo" if ensemble else "oper"
    db_model = "aifs_ens" if ensemble else "aifs"
    run_time_naive = run_time.replace(tzinfo=None) if run_time.tzinfo else run_time
    station = get_station(station_id)

    rows: list[dict] = []
    for fxx in forecast_hours:
        try:
            H = Herbie(run_time_naive, model="aifs", product=product, fxx=fxx)
            ds = H.xarray(":2t:sfc:")
            if isinstance(ds, list):
                ds = ds[0]
            key = "t2m" if "t2m" in ds.data_vars else list(ds.data_vars)[0]

            lon = lon_for_grid(
                float(ds.longitude.values.min()),
                float(ds.longitude.values.max()),
                station.longitude,
            )
            member_temps_k = _extract_member_temps_k(ds, key, station.latitude, lon)
            valid_time = _valid_time_utc(ds)
            rows.extend(build_rows(run_time, valid_time, station_id, db_model, member_temps_k))

            n = len(member_temps_k)
            tag = ""
            if ensemble and n < EXPECTED_ENS_MEMBERS:
                tag = f"WARNING incomplete: "
            print(f"  fxx={fxx:3d}h: {tag}{n} member(s) extracted "
                  f"[{db_model}] @ {valid_time.isoformat()}", flush=True)
        except Exception as e:
            print(f"  fxx={fxx:3d}h: SKIPPED ({type(e).__name__}: {e})", flush=True)
        time.sleep(0.3)  # rate limit (object store)

    if not rows:
        return {"model": db_model, "rows_inserted": 0, "members_processed": 0}

    sql = """
        INSERT INTO forecasts (init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f)
        VALUES (%(init_time)s, %(valid_time)s, %(station_id)s, %(model)s, %(member_id)s, %(temperature_f)s, %(tmax_f)s)
        ON CONFLICT (init_time, valid_time, station_id, model, member_id) DO NOTHING
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)

    n_members = len({r["member_id"] for r in rows})
    return {
        "model": db_model,
        "rows_inserted": len(rows),
        "members_processed": n_members,
        "forecast_hours": forecast_hours,
    }
