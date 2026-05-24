"""Cron entry point: ingest the most recent ECMWF run for a given init hour."""
import argparse
from datetime import datetime, timezone, timedelta
from weather_markets.ecmwf import ingest_ecmwf_run


# Forecast hours per init hour. 12Z spans afternoon + next-day morning;
# 00Z covers the same calendar day's afternoon peak (15-24Z).
FORECAST_HOURS_BY_RUN_HOUR = {
    0: [15, 18, 21, 24],
    12: [3, 6, 9, 12, 15, 18, 21, 24],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-hour",
        type=int,
        default=12,
        choices=sorted(FORECAST_HOURS_BY_RUN_HOUR),
        help="ECMWF init hour to ingest (default: 12).",
    )
    args = parser.parse_args()

    now = datetime.now(tz=timezone.utc)
    # ECMWF open data lags; ingest YESTERDAY's run, which is reliably published.
    target_day = now.date() - timedelta(days=1)
    run_time = datetime(
        target_day.year, target_day.month, target_day.day,
        args.run_hour, 0, tzinfo=timezone.utc,
    )
    forecast_hours = FORECAST_HOURS_BY_RUN_HOUR[args.run_hour]

    print(f"Ingesting ECMWF run for {run_time.isoformat()}")
    result = ingest_ecmwf_run(
        run_time=run_time,
        station_id="KNYC",
        forecast_hours=forecast_hours,
    )
    print(result)


if __name__ == "__main__":
    main()
