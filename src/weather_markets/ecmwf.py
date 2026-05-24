"""ECMWF IFS ensemble forecast ingestion."""
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


def ingest_ecmwf_run(
    run_time: datetime,
    station_id: str = "KNYC",
    forecast_hours: list[int] | None = None,
) -> dict:
    """
    Ingest one ECMWF ENS run for one station.
    
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
            
            ds = H.xarray(':mx2t3:sfc:')
            if isinstance(ds, list):
                ds = ds[0]
            
            # Extract KNYC point for all 50 members
            station_temps_k = ds['mx2t3'].sel(
                latitude=KNYC_LAT,
                longitude=KNYC_LON,
                method='nearest',
            )
            
            # Convert to Fahrenheit
            temps_f = (station_temps_k - 273.15) * 9 / 5 + 32
            
            # valid_time is init + fxx
            valid_time = pd.Timestamp(ds.valid_time.values).to_pydatetime().replace(tzinfo=timezone.utc)
            
            # Build rows
            for member_num in ds.number.values:
                temp_f = float(temps_f.sel(number=member_num).item())
                rows.append({
                    "init_time": run_time,
                    "valid_time": valid_time,
                    "station_id": station_id,
                    "model": "ifs",
                    "member_id": int(member_num),
                    "temperature_f": None,  # only have tmax for ENS
                    "tmax_f": temp_f,
                })

            n_members = len(ds.number.values)
            tag = "WARNING incomplete: " if n_members < EXPECTED_ENFO_MEMBERS else ""
            print(f"  fxx={fxx:3d}h: {tag}{n_members}/{EXPECTED_ENFO_MEMBERS} members extracted")
        
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