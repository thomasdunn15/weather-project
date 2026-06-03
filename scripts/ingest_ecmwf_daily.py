"""Cron entry point: ingest the most recent ECMWF run for a given init hour.

Tries today's run first; falls back to yesterday's if today hasn't published
yet. ECMWF Open Data typically lands ~17 UTC for the 12Z run, so an 18:30 UTC
cron usually catches today. On the ~10–20% of days today is late, the fallback
ingests yesterday's run (already in DB → ON CONFLICT no-op) so we never have
less data than always-yesterday.
"""
import argparse
from datetime import date, datetime, timezone, timedelta
from weather_markets.ecmwf import ingest_ecmwf_run
from weather_markets.stations import all_stations


# Forecast hours per init hour. 12Z spans afternoon + next-day morning;
# 00Z covers the same calendar day's afternoon peak (15-24Z).
FORECAST_HOURS_BY_RUN_HOUR = {
    0: [15, 18, 21, 24],
    12: [3, 6, 9, 12, 15, 18, 21, 24],
}


def attempt_ingest(target_day: date, run_hour: int, forecast_hours: list[int], station_id: str) -> bool:
    """Try to ingest one ECMWF run for one station. Returns True if any rows were inserted."""
    run_time = datetime(
        target_day.year, target_day.month, target_day.day,
        run_hour, 0, tzinfo=timezone.utc,
    )
    print(f"Attempting ECMWF ingest for {run_time.isoformat()} / {station_id}")
    try:
        result = ingest_ecmwf_run(
            run_time=run_time, station_id=station_id, forecast_hours=forecast_hours,
        )
        print(result)
        return result.get("rows_inserted", 0) > 0
    except Exception as e:
        print(f"  ingest raised: {type(e).__name__}: {e}")
        return False


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

    forecast_hours = FORECAST_HOURS_BY_RUN_HOUR[args.run_hour]
    today = datetime.now(tz=timezone.utc).date()
    yesterday = today - timedelta(days=1)

    for station in all_stations():
        print(f"\n========= {station.station_id} ({station.city}) =========")
        if attempt_ingest(today, args.run_hour, forecast_hours, station.station_id):
            continue
        print(f"Today's {args.run_hour:02d}Z run not yet published for {station.station_id}; "
              "falling back to yesterday.")
        attempt_ingest(yesterday, args.run_hour, forecast_hours, station.station_id)


if __name__ == "__main__":
    main()
