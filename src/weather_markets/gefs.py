import numpy as np
import pandas as pd
from datetime import datetime
from herbie import Herbie
from pathlib import Path
import xarray as xr
import math
from weather_markets.db import get_connection
import time

# GEFS forecast hours: 3-hourly out to 240h, 6-hourly to 384h
DEFAULT_FORECAST_HOURS = list(range(0, 241, 3))  # 3-hourly out to 240h (10 days)
GEFS_VARIABLES_SEARCH = ":(?:TMP|TMAX):2 m above ground:"

def kelvin_to_fahrenheit(kelvin: float) -> float:
    return (kelvin - 273.15) * 9 / 5 + 32

def conventional_to_gefs_longitude(longitude: float) -> float:
    return longitude % 360

def numpy_to_utc_datetime(t) -> datetime:
    return pd.Timestamp(t).tz_localize('UTC').to_pydatetime()

def download_member(run_time: datetime, member_id: int, fxx: int) -> Path:

    # Validation
    if run_time.tzinfo is None:
        raise ValueError("run_time must be timezone-aware")
    if run_time.hour not in (0, 6, 12, 18):
        raise ValueError(f"run_time hour must be 0/6/12/18 UTC, got {run_time.hour}")
    if not 0 <= member_id <= 30:
        raise ValueError(f"member_id must be in 0-30, got {member_id}")

    run_time = run_time.strftime("%Y-%m-%d %H:%M")
    
    H = Herbie(run_time, model="gefs", product="atmos.25", member=member_id, fxx=fxx)
    path = H.download(search=GEFS_VARIABLES_SEARCH)

    return path 

def extract_temperatures(path: Path, latitude: float, longitude: float) -> list[tuple]:

    converted_lon = conventional_to_gefs_longitude(longitude)

    ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys={"typeOfLevel": "heightAboveGround", "level": 2})
    point = ds.sel(latitude=latitude, longitude=converted_lon, method="nearest")

    t2m_k = float(point.t2m.values)
    tmax_k = float(point.tmax.values)
    vt_np = point.valid_time.values

    t_f = kelvin_to_fahrenheit(t2m_k)
    tmax_f = None if math.isnan(tmax_k) else kelvin_to_fahrenheit(tmax_k)
    vt = numpy_to_utc_datetime(vt_np)

    result = [(vt, t_f, tmax_f)]

    return result

def insert_forecasts(rows: list[tuple], conn) -> int:
    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO forecasts 
                (init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

    return len(rows)
    
def ingest_gefs_run(run_time: datetime, station_id: str = "KNYC", members: range = range(31), forecast_hours: list[int] | None = None) -> dict:
    
    # Validation
    if run_time.tzinfo is None:
        raise ValueError("run_time must be timezone-aware")
    if run_time.hour not in (0, 6, 12, 18):
        raise ValueError(f"run_time hour must be 0/6/12/18 UTC, got {run_time.hour}")

    if forecast_hours is None:
        forecast_hours = DEFAULT_FORECAST_HOURS

    from .stations import get as get_station
    station = get_station(station_id)
    latitude = station.latitude
    longitude = station.longitude

    # Accumulate all rows
    all_rows = []

    with get_connection() as conn:
        
        for member in members:
            print(f"Processing member {member}...")
            for fxx in forecast_hours:
                try:
                    path = download_member(run_time, member, fxx)
                    rows = extract_temperatures(path, latitude, longitude)
                    for vt, t_f, tmax_f in rows:
                        all_rows.append((
                            run_time, vt, station_id, "gefs", member, t_f, tmax_f
                        ))
                except Exception as e:
                    print(f"  Skipping member={member} fxx={fxx}: {type(e).__name__}: {e}")
                    continue
            time.sleep(1)

        count = insert_forecasts(all_rows, conn)

    return {
        "members_processed": len(list(members)),
        "rows_inserted": count,
        "run_time": run_time,
    }
