"""HRRR (High-Resolution Rapid Refresh) deterministic forecast ingestion.

HRRR is NOAA NCEP's 3km regional model — single deterministic forecast, hourly
updates, CONUS-only. Stored in the `forecasts` table with model='hrrr' and
member_id=0 (deterministic, no ensemble).

Treated as one extra "member" when combined with GEFS+IFS ensemble.
"""
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from herbie import Herbie

from .db import get_connection


DEFAULT_FORECAST_HOURS = [15, 18, 21, 24]   # matches ECMWF 00Z afternoon peak window

# NOTE: HRRR uses a 2D Lambert grid; nearest-cell lookup is done per station_id
# at first call inside ingest_hrrr_run, then cached across forecast hours.


def _nearest_yx(lat2d: np.ndarray, lon2d: np.ndarray, target_lat: float, target_lon: float) -> tuple[int, int]:
    """Find the (y, x) grid index nearest to (target_lat, target_lon).

    HRRR uses a 2D rotated Lambert grid; xarray .sel() doesn't work directly.
    Squared-degree distance is fine for sub-station-scale accuracy at 3km grid res."""
    if lon2d.max() > 180:  # normalize 0-360 → -180-180
        lon2d = np.where(lon2d > 180, lon2d - 360, lon2d)
    dist_sq = (lat2d - target_lat) ** 2 + (lon2d - target_lon) ** 2
    yi, xi = np.unravel_index(int(np.argmin(dist_sq)), dist_sq.shape)
    return int(yi), int(xi)


def ingest_hrrr_run(
    run_time: datetime,
    station_id: str = "KNYC",
    forecast_hours: list[int] | None = None,
) -> dict:
    """Ingest one HRRR run for one station.

    HRRR is deterministic (no perturbed members). Each forecast hour fetched
    gives one t2m value at the nearest grid cell to the station, stored as
    a single forecast row (member_id=0).

    Returns dict with ingestion summary.
    """
    if forecast_hours is None:
        forecast_hours = DEFAULT_FORECAST_HOURS

    from .stations import get as get_station
    station = get_station(station_id)

    run_time_naive = run_time.replace(tzinfo=None) if run_time.tzinfo else run_time

    rows = []

    # Cache the nearest cell index across forecast hours (same grid)
    cached_yx = None

    for fxx in forecast_hours:
        try:
            H = Herbie(
                run_time_naive,
                model="hrrr",
                product="sfc",
                fxx=fxx,
            )
            ds = H.xarray(":TMP:2 m above ground")
            if isinstance(ds, list):
                ds = ds[0]

            if cached_yx is None:
                cached_yx = _nearest_yx(
                    ds.latitude.values, ds.longitude.values, station.latitude, station.longitude,
                )
            yi, xi = cached_yx

            temp_k = float(ds["t2m"].isel(y=yi, x=xi).item())
            temp_f = (temp_k - 273.15) * 9 / 5 + 32

            valid_time = pd.Timestamp(ds.valid_time.values).to_pydatetime().replace(tzinfo=timezone.utc)

            rows.append({
                "init_time": run_time,
                "valid_time": valid_time,
                "station_id": station_id,
                "model": "hrrr",
                "member_id": 0,
                "temperature_f": temp_f,
                "tmax_f": temp_f,   # instantaneous t2m used as tmax sample (HRRR doesn't have a windowed max)
            })

            print(f"  fxx={fxx:3d}h: 1 deterministic value extracted ({temp_f:.2f}°F at {valid_time.isoformat()})")

        except Exception as e:
            print(f"  fxx={fxx:3d}h: SKIPPED ({type(e).__name__}: {e})")

        time.sleep(0.3)  # rate limit (AWS S3)

    if not rows:
        return {"model": "hrrr", "rows_inserted": 0, "members_processed": 0}

    sql = """
        INSERT INTO forecasts (init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f)
        VALUES (%(init_time)s, %(valid_time)s, %(station_id)s, %(model)s, %(member_id)s, %(temperature_f)s, %(tmax_f)s)
        ON CONFLICT (init_time, valid_time, station_id, model, member_id) DO NOTHING
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)

    return {
        "model": "hrrr",
        "rows_inserted": len(rows),
        "members_processed": 1,
        "forecast_hours": forecast_hours,
    }
