#!/usr/bin/env python
"""Daily forward-ingest of NBM core calibrated daily-Tmax for the Phase-1 staged
stations (model='nbm'). Research/validation only — NOT in the trading path.

Ingests today's 00Z run; falls back to yesterday's if today's hasn't published.
Additive + idempotent (ON CONFLICT DO NOTHING), so re-running / the retry cron is
a no-op once the data is in. Cron entrypoint (see docs/crontab.txt).

Run: cd /home/tdunn/weather-project && uv run python scripts/ingest_nbm_daily.py
"""
from datetime import datetime, timedelta, timezone

from weather_markets.nbm import ingest_nbm_run, purge_cache

# Phase-1 staged set (edge cities first, then NBM's hard target stations).
STAGED_STATIONS = ["KORD", "KMIA", "KSEA", "KMDW", "KLAS", "KLAX", "KPHX", "KSFO"]


def main():
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for st in STAGED_STATIONS:
        for init in (today, today - timedelta(days=1)):
            r = ingest_nbm_run(init, station_id=st)
            print(f"{st} {init:%Y-%m-%d} 00Z: {r['rows_inserted']} rows, {r['core_windows']} window(s)")
            if r["core_windows"]:
                break  # today's run landed — don't also pull yesterday
    purge_cache()


if __name__ == "__main__":
    main()
