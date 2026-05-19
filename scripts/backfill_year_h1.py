# scripts/backfill_year_h1.py — first half
"""Backfill GEFS 12 UTC runs for first half of past year."""
import time
from datetime import datetime, timezone, timedelta
from weather_markets.gefs import ingest_gefs_run

def main() -> None:
    start = datetime(2025, 5, 18, 12, 0, tzinfo=timezone.utc)  # one year ago
    end = datetime(2025, 11, 30, 12, 0, tzinfo=timezone.utc)
    
    current = start
    while current <= end:
        print(f"\n=== {current.isoformat()} ===")
        start_time = time.time()
        try:
            result = ingest_gefs_run(
                run_time=current,
                station_id="KNYC",
                forecast_hours=[6, 9, 12],
            )
            elapsed = time.time() - start_time
            print(f"OK in {elapsed:.0f}s: {result.get('rows_inserted', '?')} rows")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"FAILED after {elapsed:.0f}s: {type(e).__name__}: {e}")
        
        current += timedelta(days=1)

if __name__ == "__main__":
    main()