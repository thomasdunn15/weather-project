"""Cron entry point: ingest the most recent ECMWF 12 UTC run."""
from datetime import datetime, timezone, timedelta
from weather_markets.ecmwf import ingest_ecmwf_run


def main() -> None:
    now = datetime.now(tz=timezone.utc)
    # ECMWF open data lags; ingest YESTERDAY's 12 UTC run, which is reliably published.
    target_day = now.date() - timedelta(days=1)
    run_time = datetime(target_day.year, target_day.month, target_day.day, 12, 0, tzinfo=timezone.utc)
    print(f"Ingesting ECMWF run for {run_time.isoformat()}")
    result = ingest_ecmwf_run(run_time=run_time, station_id="KNYC",
                              forecast_hours=[3, 6, 9, 12, 15, 18, 21, 24])
    print(result)


if __name__ == "__main__":
    main()