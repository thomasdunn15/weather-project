"""Cron entry point: ingest the most recent ECMWF 12 UTC run."""
from datetime import datetime, timezone, timedelta
from weather_markets.ecmwf import ingest_ecmwf_run


def main() -> None:
    # At 14:45 UTC, today's 12 UTC run should be available
    now = datetime.now(tz=timezone.utc)
    run_time = datetime(now.year, now.month, now.day, 12, 0, tzinfo=timezone.utc)
    
    print(f"Ingesting ECMWF run for {run_time.isoformat()}")
    result = ingest_ecmwf_run(
        run_time=run_time,
        station_id="KNYC",
        forecast_hours=[3, 6, 9, 12, 15, 18, 21, 24],
    )
    print(result)


if __name__ == "__main__":
    main()