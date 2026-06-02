"""Backfill HRRR 00Z runs across a date range.

Each date is processed independently; failures are logged and the loop
continues so this can run unattended in tmux.

Example:
    uv run python scripts/backfill_hrrr_runs.py --start 2025-05-27 --end 2026-05-13
"""
import argparse
import time
from datetime import date, datetime, timedelta, timezone

from weather_markets.hrrr import ingest_hrrr_run


FORECAST_HOURS = [15, 18, 21, 24]   # NYC afternoon peak window from 00Z init


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=parse_date, required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", type=parse_date, required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--station", default="KNYC",
                        help="Station ID (default KNYC). Must exist in src/weather_markets/stations.py")
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    total_days = (args.end - args.start).days + 1
    print(f"Backfilling {total_days} day(s) of HRRR 00Z runs from {args.start} to {args.end}")
    print(f"  forecast_hours={FORECAST_HOURS}")

    succeeded = 0
    failed = 0
    overall_start = time.time()

    current = args.start
    while current <= args.end:
        run_time = datetime(current.year, current.month, current.day, 0, 0, tzinfo=timezone.utc)
        print(f"\n=== {run_time.isoformat()} ===", flush=True)
        t0 = time.time()
        try:
            result = ingest_hrrr_run(
                run_time=run_time, station_id=args.station, forecast_hours=FORECAST_HOURS,
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
