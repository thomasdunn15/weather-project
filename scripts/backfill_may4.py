# scripts/backfill_may4.py
"""Backfill May 4 12 UTC for 24-hour lead-time analysis."""
from datetime import datetime, timezone
from weather_markets.gefs import ingest_gefs_run


def main() -> None:
    run_time = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    print(f"Ingesting {run_time.isoformat()}...")
    result = ingest_gefs_run(run_time=run_time, station_id="KNYC")
    print(result)


if __name__ == "__main__":
    main()