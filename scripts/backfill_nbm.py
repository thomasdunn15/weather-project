#!/usr/bin/env python
"""Backfill NBM core daily-Tmax (model='nbm') into `forecasts` for the staged set.

Additive only (model='nbm'); resumable (ON CONFLICT DO NOTHING); box-safe
(remove_grib auto-deletes each GRIB, periodic cache purge, RAM guard). Sequential
— do NOT run concurrently with the AIFS backfill. Long job: run in tmux,
line-buffered.

Per-station start dates are obs/model-bounded so we only fetch scoreable days:
  KORD, KMIA  -> 2024-06-01  (live/edge cities; obs back to 2017, GEFS/IFS from 2024-04)
  KMDW, KSEA, KLAS, KLAX, KPHX -> 2025-01-01  (CF6 obs start 2025-01)
  KSFO        -> 2026-01-01  (CF6 obs start 2026-01)
Edge cities (KORD, KMIA, KSEA) run FIRST so the bracket-edge-Brier verdict is
computable before the hard stations finish.

Run: cd /home/tdunn/weather-project && \
     uv run python /home/tdunn/wt-p1-nbm/scripts/backfill_nbm.py 2>&1 | tee nbm_backfill.log
"""
import argparse
import os
import time
from datetime import datetime, timedelta, timezone

from weather_markets.nbm import ingest_nbm_run, purge_cache

# station -> start date (inclusive). Order = edge cities first.
STAGED: dict[str, str] = {
    "KORD": "2024-06-01",
    "KMIA": "2024-06-01",
    "KSEA": "2025-01-01",
    "KMDW": "2025-01-01",
    "KLAS": "2025-01-01",
    "KLAX": "2025-01-01",
    "KPHX": "2025-01-01",
    "KSFO": "2026-01-01",
}
DEFAULT_END = "2026-06-19"
RAM_FLOOR_MB = 450          # pause if MemAvailable drops below this (OOM guard)
PURGE_EVERY = 40            # purge idx cache every N station-days


def mem_available_mb() -> int:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 1 << 30


def wait_for_ram():
    while mem_available_mb() < RAM_FLOOR_MB:
        print(f"  [ram-guard] MemAvailable={mem_available_mb()}MB < {RAM_FLOOR_MB}MB — pausing 30s", flush=True)
        time.sleep(30)


def daterange(start: str, end: str):
    d = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    last = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    while d <= last:
        yield d
        d += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default=",".join(STAGED), help="comma list; default = all staged (edge first)")
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--since", default=None, help="override start date for ALL stations (e.g. 2025-06-01)")
    args = ap.parse_args()

    stations = [s for s in args.stations.split(",") if s]
    t_start = time.time()
    grand = 0
    for st in stations:
        start = args.since or STAGED.get(st, "2025-01-01")
        days = list(daterange(start, args.end))
        print(f"\n#### {st}: {start} -> {args.end}  ({len(days)} days)", flush=True)
        ins = win = done = 0
        for d in days:
            wait_for_ram()
            try:
                r = ingest_nbm_run(d, station_id=st)
                ins += r["rows_inserted"]
                win += r["core_windows"]
            except Exception as e:  # noqa: BLE001
                print(f"  {d:%Y-%m-%d}: ERROR {type(e).__name__}: {str(e)[:120]}", flush=True)
            done += 1
            grand += 1
            if done % PURGE_EVERY == 0:
                purge_cache()
                el = time.time() - t_start
                print(f"  …{st} {done}/{len(days)} | rows={ins} windows={win} | "
                      f"{el/grand:.2f}s/day | RAM={mem_available_mb()}MB", flush=True)
        purge_cache()
        print(f"  DONE {st}: {done} days, {win} windows, {ins} rows inserted", flush=True)
    purge_cache()
    print(f"\nALL DONE: {grand} station-days in {(time.time()-t_start)/60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
