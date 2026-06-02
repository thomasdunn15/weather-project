"""Backfill ECMWF runs across a date range for a given init hour.

Example:
    uv run python scripts/backfill_ecmwf_runs.py --run-hour 0 --start 2025-11-24 --end 2026-05-23

Each date is processed independently; failures are logged and the loop
continues so you can leave this running in tmux overnight.
"""
import argparse
import time
from datetime import datetime, date, timezone, timedelta
from weather_markets.ecmwf import ingest_ecmwf_run


FORECAST_HOURS_BY_RUN_HOUR = {
    0: [15, 18, 21, 24],
    12: [3, 6, 9, 12, 15, 18, 21, 24],
}


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-hour", type=int, required=True, choices=sorted(FORECAST_HOURS_BY_RUN_HOUR))
    parser.add_argument("--start", type=parse_date, required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", type=parse_date, required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--station", default="KNYC",
                        help="Station ID (default KNYC). Must exist in src/weather_markets/stations.py")
    parser.add_argument("--forecast-hours", type=lambda s: [int(x) for x in s.split(",")],
                        default=None, help="Override forecast-hour list, comma-separated (e.g. '30,33,36').")
    parser.add_argument("--use-instantaneous", action="store_true",
                        help="Extract instantaneous 2t into temperature_f instead of mx2t3 into tmax_f. "
                             "Use for daily-low forecasts at morning hours.")
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    forecast_hours = args.forecast_hours if args.forecast_hours is not None else FORECAST_HOURS_BY_RUN_HOUR[args.run_hour]
    total_days = (args.end - args.start).days + 1

    print(
        f"Backfilling {total_days} day(s) of ECMWF {args.run_hour:02d}Z runs "
        f"from {args.start} to {args.end} (forecast_hours={forecast_hours})"
    )

    succeeded = 0
    failed = 0
    overall_start = time.time()

    current = args.start
    while current <= args.end:
        run_time = datetime(
            current.year, current.month, current.day,
            args.run_hour, 0, tzinfo=timezone.utc,
        )
        print(f"\n=== {run_time.isoformat()} ===", flush=True)
        t0 = time.time()
        try:
            result = ingest_ecmwf_run(
                run_time=run_time,
                station_id=args.station,
                forecast_hours=forecast_hours,
                use_instantaneous=args.use_instantaneous,
            )
            elapsed = time.time() - t0
            print(f"OK in {elapsed:.0f}s: {result.get('rows_inserted')} rows", flush=True)
            succeeded += 1
        except Exception as e:
            elapsed = time.time() - t0
            print(f"FAILED after {elapsed:.0f}s: {type(e).__name__}: {e}", flush=True)
            failed += 1

        current += timedelta(days=1)

    total = time.time() - overall_start
    print(f"\n=== Done: {succeeded} OK, {failed} failed in {total/60:.1f} min ===")


if __name__ == "__main__":
    main()
