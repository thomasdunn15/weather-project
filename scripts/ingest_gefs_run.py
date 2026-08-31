"""
Daily GEFS run ingestion. Pulls a GEFS run for every station registered in
weather_markets.stations.

GEFS GRIB files are downloaded once per member (the file covers the whole
North-America grid), and per-station extraction is cheap, so iterating all
stations adds minimal cost over single-station ingest.

Designed to be run by cron at 04, 10, 16, 22 UTC (four hours after each
GEFS publication time of 00, 06, 12, 18 UTC).

--run-hour EXISTS BECAUSE 00Z IS THE ONLY RUN THAT MATTERS FOR TRADING, AND IT
USED TO BE UNREPAIRABLE. live_trade uses INIT_HOUR=0 and halts outright on a
partial ensemble. Without an explicit run hour every invocation ingests
most_recent_completed_run(now), so only the ~06:15 cron ever fetches 00Z, and a
retry later in the morning silently fetches 06Z or 12Z instead. So when the
06:15 run of 2026-08-26 wedged on KDFW (see STATION_TIMEOUT_S), nothing could
repair 00Z, because nothing could ask for it. ECMWF had --run-hour and four
retries; GEFS had neither. That asymmetry is what turned one hung download into
a lost trading day.

  uv run python scripts/ingest_gefs_run.py                  # latest completed
  uv run python scripts/ingest_gefs_run.py --run-hour 0     # today's 00Z
"""
import argparse
import signal
from datetime import datetime, timezone, timedelta

from weather_markets.gefs import ingest_gefs_run
from weather_markets.stations import all_stations

# A station is 31 members x 8 forecast hours and takes ~5 minutes, so this is 3x
# headroom. It exists because Herbie's S3 reads have no socket timeout and DO
# hang forever: on 2026-08-26 the 06:15 run blocked on KDFW at 13:37 and was
# still sleeping in wait_woken 14 hours later, having burned 113 seconds of CPU.
# KMIA is 7th alphabetically, never got 00Z data, and the 15:30 Miami trader
# correctly refused to trade all day. A twin from 2026-08-06 had been hanging
# for TWENTY DAYS holding 224MB on a box with 7.6GB and no swap.
#
# Per-station rather than per-run: one wedged station should cost one station,
# not the twelve that come after it alphabetically.
STATION_TIMEOUT_S = 15 * 60


def most_recent_completed_run(now: datetime) -> datetime:
    """
    Return the most recently completed GEFS run init_time.

    GEFS runs at 00/06/12/18 UTC and takes ~4 hours to fully publish.
    Subtract 4 hours from now and round down to the nearest 6-hour boundary.
    """
    cutoff = now - timedelta(hours=6)
    run_hour = (cutoff.hour // 6) * 6
    return cutoff.replace(hour=run_hour, minute=0, second=0, microsecond=0)


def run_for_hour(now: datetime, run_hour: int) -> datetime:
    """Today's run at `run_hour`, or yesterday's if it cannot have published yet.

    Guards against a retry scheduled before publication silently reaching into
    the future and ingesting nothing.
    """
    candidate = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    if candidate > now - timedelta(hours=4):
        candidate -= timedelta(days=1)
    return candidate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-hour", type=int, choices=[0, 6, 12, 18], default=None,
                    help="ingest this init hour specifically (default: most recent completed). "
                         "Use 0 for the run live_trade depends on.")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    run_time = (most_recent_completed_run(now) if a.run_hour is None
                else run_for_hour(now, a.run_hour))
    forecast_hours = [3, 6, 9, 12, 15, 18, 21, 24]

    print(f"Ingesting GEFS run {run_time.isoformat()} for all registered stations")

    def _too_slow(signum, frame):
        raise TimeoutError(f"exceeded STATION_TIMEOUT_S ({STATION_TIMEOUT_S}s)")
    signal.signal(signal.SIGALRM, _too_slow)

    failed = []
    for station in all_stations():
        print(f"--- {station.station_id} ({station.city}) ---", flush=True)
        signal.alarm(STATION_TIMEOUT_S)
        try:
            result = ingest_gefs_run(
                run_time=run_time,
                station_id=station.station_id,
                forecast_hours=forecast_hours,
            )
            print(result, flush=True)
        except Exception as e:
            # One station's failure shouldn't kill the whole run. A TimeoutError
            # arrives here too, which is the point: the alarm converts a silent
            # forever-hang into an ordinary per-station failure the loop absorbs.
            print(f"  {station.station_id} ingest raised: {type(e).__name__}: {e}", flush=True)
            failed.append(station.station_id)
        finally:
            signal.alarm(0)

    # Non-zero exit so a retry cron, or a human reading the log, can tell a
    # partial run from a clean one. A silent kill mid-loop still shows up as a
    # missing tail in the log — flush=True above is what makes that legible.
    if failed:
        print(f"\nFAILED stations: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
