"""Backfill GEFS runs across a date range for a given init hour.

Example:
    uv run python scripts/backfill_gefs_runs.py --run-hour 0 --start 2025-05-01 --end 2026-05-13

Each date is processed independently; failures are logged and the loop
continues so you can leave this running in tmux overnight.
"""
import argparse
import time
from datetime import datetime, date, timezone, timedelta
from weather_markets.gefs import ingest_gefs_run
from weather_markets.db import get_connection

GEFS_EXPECTED_MEMBERS = 31


def _already_complete(conn, station_id: str, run_time: datetime) -> bool:
    """True if this (station, init_time) already has the full GEFS ensemble in
    the DB — lets the backfill skip it WITHOUT downloading anything. Gaps are
    scattered, so a full-range pass that skips present dates is both complete
    and fast (the original full-range pass wasted hours re-downloading present
    dates)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(DISTINCT member_id) FROM forecasts "
            "WHERE station_id=%s AND model='gefs' AND init_time=%s",
            (station_id, run_time),
        )
        return cur.fetchone()[0] >= GEFS_EXPECTED_MEMBERS


# Forecast hours per init hour, chosen to cover NYC afternoon peak (~18-22 UTC).
# 12Z mirrors the daily-cron set; 00Z trims to the windows that fall in NYC daytime.
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
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    forecast_hours = args.forecast_hours if args.forecast_hours is not None else FORECAST_HOURS_BY_RUN_HOUR[args.run_hour]
    total_days = (args.end - args.start).days + 1

    print(
        f"Backfilling {total_days} day(s) of GEFS {args.run_hour:02d}Z runs "
        f"from {args.start} to {args.end} (forecast_hours={forecast_hours})"
    )

    succeeded = 0
    failed = 0
    skipped = 0
    skip_conn = get_connection()
    overall_start = time.time()

    current = args.start
    while current <= args.end:
        run_time = datetime(
            current.year, current.month, current.day,
            args.run_hour, 0, tzinfo=timezone.utc,
        )
        if _already_complete(skip_conn, args.station, run_time):
            print(f"=== {run_time.isoformat()} === SKIP (already complete)", flush=True)
            skipped += 1
            current += timedelta(days=1)
            continue
        print(f"\n=== {run_time.isoformat()} ===", flush=True)
        t0 = time.time()
        try:
            result = ingest_gefs_run(
                run_time=run_time,
                station_id=args.station,
                forecast_hours=forecast_hours,
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
