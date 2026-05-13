"""
Daily GEFS run ingestion. Pulls the most recently completed run.

Designed to be run by cron at 04, 10, 16, 22 UTC (four hours after each 
GEFS publication time of 00, 06, 12, 18 UTC).
"""
from datetime import datetime, timezone, timedelta
from weather_markets.gefs import ingest_gefs_run

def most_recent_completed_run(now: datetime) -> datetime:
    """
    Return the most recently completed GEFS run init_time.
    
    GEFS runs at 00/06/12/18 UTC and takes ~4 hours to fully publish.
    Subtract 4 hours from now and round down to the nearest 6-hour boundary.
    """
    cutoff = now - timedelta(hours=6)
    run_hour = (cutoff.hour // 6) * 6
    return cutoff.replace(hour=run_hour, minute=0, second=0, microsecond=0)


def main() -> None:
    now = datetime.now(timezone.utc)
    run_time = most_recent_completed_run(now)
    
    print(f"Ingesting GEFS run {run_time.isoformat()}")
    result = ingest_gefs_run(run_time=run_time, station_id="KNYC")
    print(result)


if __name__ == "__main__":
    main()