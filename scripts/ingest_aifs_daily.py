"""Cron entry point: ingest the most recent AIFS 00Z run for the staged stations.

Forward-collection for the P1 AIFS evaluation. Tries today's 00Z run first and
falls back to yesterday's if today hasn't published yet (ECMWF Open Data AIFS
lands a few hours after the 00Z cycle). ON CONFLICT DO NOTHING makes the
fallback a cheap no-op when today already succeeded.

Ingests BOTH products for each station:
  AIFS-Single (model='aifs')      — deterministic, 1 member.
  AIFS-ENS    (model='aifs_ens')  — 50 perturbed members (--no-ens to skip).

Scope is the 8 staged stations (the P1 cohort), not every registered station,
to keep the 50-member ENS pulls light on the box. Expand STAGED_STATIONS once
AIFS earns a place in the production blend.
"""
import argparse
from datetime import date, datetime, timezone, timedelta

from weather_markets.aifs import ingest_aifs_run

STAGED_STATIONS = ["KORD", "KMDW", "KMIA", "KSEA", "KLAS", "KSFO", "KLAX", "KPHX"]


def attempt(target_day: date, station_id: str, ensemble: bool) -> bool:
    run_time = datetime(target_day.year, target_day.month, target_day.day, 0, 0, tzinfo=timezone.utc)
    label = "aifs_ens" if ensemble else "aifs"
    print(f"Attempting {label} ingest for {run_time.isoformat()} / {station_id}")
    try:
        result = ingest_aifs_run(run_time=run_time, station_id=station_id, ensemble=ensemble)
        print(result)
        return result.get("rows_inserted", 0) > 0
    except Exception as e:
        print(f"  ingest raised: {type(e).__name__}: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-ens", action="store_true", help="Skip AIFS-ENS (ingest Single only).")
    args = parser.parse_args()

    today = datetime.now(tz=timezone.utc).date()
    yesterday = today - timedelta(days=1)
    variants = [False] if args.no_ens else [False, True]

    for ensemble in variants:
        for station_id in STAGED_STATIONS:
            label = "aifs_ens" if ensemble else "aifs"
            print(f"\n========= {station_id} / {label} =========")
            if attempt(today, station_id, ensemble):
                continue
            print(f"Today's 00Z {label} not yet published for {station_id}; falling back to yesterday.")
            attempt(yesterday, station_id, ensemble)


if __name__ == "__main__":
    main()
