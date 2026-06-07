"""Cron entry point: ingest the most recent HRRR 00Z run for all stations.

HRRR is NOAA's high-resolution regional model. Open data is on AWS S3 and
typically lands within an hour of the run time. Tries today's 00Z first
(usually published by ~02-03 UTC), falls back to yesterday on failure.

Iterates all stations in the registry (matches gefs/observations ingest pattern).
"""
import argparse
from datetime import date, datetime, timedelta, timezone

from weather_markets.hrrr import ingest_hrrr_run
from weather_markets.stations import all_stations


# 00Z forecast hours covering afternoon peak (15-24 UTC). For Chicago/Denver
# in CDT/MDT (UTC-5/-6) that's 10-19 local; for LA (UTC-7) 8-17 local.
# Sufficient to span the daily-high window for all current stations.
FORECAST_HOURS = [15, 18, 21, 24]


def attempt_ingest_for_station(target_day: date, station_id: str, forecast_hours: list[int]) -> bool:
    """Try to ingest one HRRR 00Z run for one station. Returns True if any rows inserted."""
    run_time = datetime(target_day.year, target_day.month, target_day.day, 0, 0, tzinfo=timezone.utc)
    print(f"  [{station_id}] attempting HRRR ingest for {run_time.isoformat()}")
    try:
        result = ingest_hrrr_run(
            run_time=run_time, station_id=station_id, forecast_hours=forecast_hours,
        )
        print(f"  [{station_id}] {result}")
        return result.get("rows_inserted", 0) > 0
    except Exception as e:
        print(f"  [{station_id}] ingest raised: {type(e).__name__}: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()

    today = datetime.now(tz=timezone.utc).date()
    yesterday = today - timedelta(days=1)

    for station in all_stations():
        print(f"\n=== {station.station_id} ({station.city}) ===")
        if attempt_ingest_for_station(today, station.station_id, FORECAST_HOURS):
            continue
        print(f"  [{station.station_id}] today's HRRR 00Z not yet published; falling back to yesterday.")
        attempt_ingest_for_station(yesterday, station.station_id, FORECAST_HOURS)


if __name__ == "__main__":
    main()
