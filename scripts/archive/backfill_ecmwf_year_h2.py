"""Backfill ECMWF IFS ensemble runs for second half of past year."""
import time
from datetime import datetime, timezone, timedelta
from weather_markets.ecmwf import ingest_ecmwf_run


def main() -> None:
    start = datetime(2025, 12, 1, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    
    current = start
    while current <= end:
        print(f"\n=== {current.isoformat()} ===")
        start_time = time.time()
        try:
            result = ingest_ecmwf_run(
                run_time=current,
                station_id="KNYC",
                forecast_hours=[3, 6, 9, 12, 15, 18, 21, 24],
            )
            elapsed = time.time() - start_time
            print(f"OK in {elapsed:.0f}s: {result.get('rows_inserted')} rows")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"FAILED after {elapsed:.0f}s: {type(e).__name__}: {e}")
        
        current += timedelta(days=1)


if __name__ == "__main__":
    main()