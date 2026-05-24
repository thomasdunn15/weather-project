# scripts/test_old_gefs.py
"""Test if Herbie can fetch old GEFS data."""
import time
from datetime import datetime, timezone
from weather_markets.gefs import ingest_gefs_run


def main() -> None:
    # Try January 1, 2026 (about 4 months ago)
    run_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    
    print(f"Testing ingest for {run_time.isoformat()}")
    print(f"Forecast hours: [6, 9, 12]")
    
    start = time.time()
    try:
        result = ingest_gefs_run(
            run_time=run_time,
            station_id="KNYC",
            forecast_hours=[6, 9, 12],
        )
        elapsed = time.time() - start
        print(f"\nSuccess in {elapsed:.1f}s")
        print(result)
    except Exception as e:
        elapsed = time.time() - start
        print(f"\nFailed after {elapsed:.1f}s: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()