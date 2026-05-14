"""
Backfill historical GEFS runs for dates that already have contracts.
"""
from datetime import datetime, timezone
from weather_markets.gefs import ingest_gefs_run


def main() -> None:
    # Run for each day at 12 UTC (afternoon-peak coverage)
    # These dates are the targets we want to evaluate.
    # We need init_times that PRECEDE the peak heating of each target.
    
    # To predict May 5 (NYC), we need init_time before May 5 noon EDT.
    # The 12 UTC May 5 run = 8 AM EDT May 5, before peak.
    
    target_dates_and_inits = [
        # (init_time)
        datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
    ]
    
    for init_time in target_dates_and_inits:
        print(f"\n=== Ingesting {init_time.isoformat()} ===")
        try:
            result = ingest_gefs_run(run_time=init_time, station_id="KNYC")
            print(result)
        except Exception as e:
            print(f"Failed for {init_time}: {e}")


if __name__ == "__main__":
    main()