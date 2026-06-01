"""Cron entry point: ingest the most recent HRRR 00Z run.

HRRR is NOAA's high-resolution regional model. Open data is on AWS S3 and
typically lands within an hour of the run time. Tries today's 00Z first
(usually published by ~02-03 UTC), falls back to yesterday on failure.
"""
import argparse
import time
from datetime import date, datetime, timedelta, timezone

from weather_markets.hrrr import ingest_hrrr_run


# 00Z forecast hours covering NYC afternoon peak (15-24 UTC = 11 AM - 8 PM EDT).
# Matches ECMWF 00Z pattern for parallelism.
FORECAST_HOURS = [15, 18, 21, 24]


def attempt_ingest(target_day: date, forecast_hours: list[int]) -> bool:
    """Try to ingest one HRRR 00Z run. Returns True if any rows were inserted."""
    run_time = datetime(target_day.year, target_day.month, target_day.day, 0, 0, tzinfo=timezone.utc)
    print(f"Attempting HRRR ingest for {run_time.isoformat()}")
    try:
        result = ingest_hrrr_run(
            run_time=run_time, station_id="KNYC", forecast_hours=forecast_hours,
        )
        print(result)
        return result.get("rows_inserted", 0) > 0
    except Exception as e:
        print(f"  ingest raised: {type(e).__name__}: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()

    today = datetime.now(tz=timezone.utc).date()
    yesterday = today - timedelta(days=1)

    if attempt_ingest(today, FORECAST_HOURS):
        return
    print(f"Today's HRRR 00Z run not yet published; falling back to yesterday.")
    attempt_ingest(yesterday, FORECAST_HOURS)


if __name__ == "__main__":
    main()
