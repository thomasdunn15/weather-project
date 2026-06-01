"""ECMWF IFS ensemble forecast ingestion.

mx2t3 (3-hour max 2m temperature) was added to the ECMWF Open Data enfo stream
on 2024-11-13. For older dates only instantaneous 2t is available, so we fall
back to it. The fallback samples temperature at the requested forecast hours
rather than computing a true 3-hour windowed max — daily-high estimates for
pre-cutover dates are therefore biased low by ~1-2°F. The rolling EMOS fit
absorbs this bias over its 45-day window after the cutover.
"""
import time
from datetime import datetime, timezone
from herbie import Herbie
import numpy as np
from .db import get_connection
import pandas as pd

# 3-hour windowed max temperature, peak heating hours for NYC
DEFAULT_FORECAST_HOURS = [3, 6, 9, 12]

# ECMWF enfo publishes 50 perturbed members per run. Fewer than this on an
# extracted dataset means a partial GRIB download (often a stale cache from
# an interrupted prior run) — warn loudly so it doesn't go unnoticed.
EXPECTED_ENFO_MEMBERS = 50

KNYC_LAT = 40.78
KNYC_LON = -73.97


def _extract_temps(H: Herbie):
    """Extract (xarray dataset, variable key, source_label) for a single Herbie handle.

    Tries mx2t3 first (current archive); falls back to instantaneous 2t for
    pre-2024-11-13 dates. cfgrib renames '2t' to 't2m' in the dataset.
    """
    try:
        ds = H.xarray(':mx2t3:sfc:')
        if isinstance(ds, list):
            ds = ds[0]
        if 'mx2t3' in ds.data_vars:
            return ds, 'mx2t3', 'mx2t3'
        # Unexpected: search succeeded but variable name missing — treat as failure.
        raise KeyError("mx2t3 not in dataset")
    except (FileNotFoundError, KeyError, ValueError, IndexError):
        ds = H.xarray(':2t:sfc:')
        if isinstance(ds, list):
            ds = ds[0]
        # cfgrib renames 2t → t2m
        key = 't2m' if 't2m' in ds.data_vars else list(ds.data_vars)[0]
        return ds, key, '2t-fallback'


def _extract_2t_only(H: Herbie):
    """Extract instantaneous 2t directly. Used for forecasts of daily lows where
    mx2t3 (3-hour max) is the wrong variable. Returns (ds, var_key)."""
    ds = H.xarray(':2t:sfc:')
    if isinstance(ds, list):
        ds = ds[0]
    key = 't2m' if 't2m' in ds.data_vars else list(ds.data_vars)[0]
    return ds, key


def ingest_ecmwf_run(
    run_time: datetime,
    station_id: str = "KNYC",
    forecast_hours: list[int] | None = None,
    use_instantaneous: bool = False,
) -> dict:
    """
    Ingest one ECMWF ENS run for one station.

    use_instantaneous=False (default): extract mx2t3 (3-hour max), fall back to
    2t for pre-2024-11-13 dates. Stored in tmax_f. Use for daily-high forecasts.

    use_instantaneous=True: extract 2t directly at every requested forecast hour
    and store in temperature_f. Used for daily-low forecasts where we want the
    point-in-time temperature at the early-morning low window, not a windowed
    max. This path always uses the 2t archive (which goes back further than
    mx2t3 anyway), so no fallback distinction needed.

    Returns dict with ingestion summary.
    """
    if forecast_hours is None:
        forecast_hours = DEFAULT_FORECAST_HOURS

    run_time_naive = run_time.replace(tzinfo=None) if run_time.tzinfo else run_time

    rows = []

    for fxx in forecast_hours:
        try:
            H = Herbie(
                run_time_naive,
                model='ifs',
                product='enfo',
                fxx=fxx,
            )

            if use_instantaneous:
                ds, var_key = _extract_2t_only(H)
                source = '2t-instant'
            else:
                ds, var_key, source = _extract_temps(H)

            # Extract KNYC point for all 50 members
            station_temps_k = ds[var_key].sel(
                latitude=KNYC_LAT,
                longitude=KNYC_LON,
                method='nearest',
            )

            # Convert to Fahrenheit
            temps_f = (station_temps_k - 273.15) * 9 / 5 + 32

            # valid_time is init + fxx
            valid_time = pd.Timestamp(ds.valid_time.values).to_pydatetime().replace(tzinfo=timezone.utc)

            # Build rows. For instantaneous mode, store in temperature_f.
            # For mx2t3 / fallback mode (default), store in tmax_f.
            for member_num in ds.number.values:
                temp_f = float(temps_f.sel(number=member_num).item())
                if use_instantaneous:
                    row = {
                        "init_time": run_time, "valid_time": valid_time,
                        "station_id": station_id, "model": "ifs",
                        "member_id": int(member_num),
                        "temperature_f": temp_f, "tmax_f": None,
                    }
                else:
                    row = {
                        "init_time": run_time, "valid_time": valid_time,
                        "station_id": station_id, "model": "ifs",
                        "member_id": int(member_num),
                        "temperature_f": None, "tmax_f": temp_f,
                    }
                rows.append(row)

            n_members = len(ds.number.values)
            tag = "WARNING incomplete: " if n_members < EXPECTED_ENFO_MEMBERS else ""
            suffix = f" [{source}]" if source != 'mx2t3' else ""
            print(f"  fxx={fxx:3d}h: {tag}{n_members}/{EXPECTED_ENFO_MEMBERS} members extracted{suffix}")

        except Exception as e:
            print(f"  fxx={fxx:3d}h: SKIPPED ({type(e).__name__}: {e})")

        time.sleep(0.5)  # rate limit
    
    # Insert into database
    if not rows:
        return {"members_processed": 0, "rows_inserted": 0}
    
    sql = """
        INSERT INTO forecasts (init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f)
        VALUES (%(init_time)s, %(valid_time)s, %(station_id)s, %(model)s, %(member_id)s, %(temperature_f)s, %(tmax_f)s)
        ON CONFLICT (init_time, valid_time, station_id, model, member_id) DO NOTHING
    """
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    
    return {
        "model": "ifs",
        "rows_inserted": len(rows),
        "members_processed": 50,
        "forecast_hours": forecast_hours,
    }