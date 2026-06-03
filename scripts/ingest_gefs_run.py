"""
Daily GEFS run ingestion. Pulls the most recently completed run for every
station registered in weather_markets.stations.

GEFS GRIB files are downloaded once per member (the file covers the whole
North-America grid), and per-station extraction is cheap, so iterating all
stations adds minimal cost over single-station ingest.

Designed to be run by cron at 04, 10, 16, 22 UTC (four hours after each
GEFS publication time of 00, 06, 12, 18 UTC).
"""
from datetime import datetime, timezone, timedelta
from weather_markets.gefs import ingest_gefs_run
from weather_markets.stations import all_stations


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
    forecast_hours = [3, 6, 9, 12, 15, 18, 21, 24]

    print(f"Ingesting GEFS run {run_time.isoformat()} for all registered stations")
    for station in all_stations():
        print(f"--- {station.station_id} ({station.city}) ---")
        try:
            result = ingest_gefs_run(
                run_time=run_time,
                station_id=station.station_id,
                forecast_hours=forecast_hours,
            )
            print(result)
        except Exception as e:
            # One station's failure shouldn't kill the whole run.
            print(f"  {station.station_id} ingest raised: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
