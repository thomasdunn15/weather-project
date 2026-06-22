#!/usr/bin/env python
"""Smoke test for NBM ingest: KORD, a few dates. Writes additive nbm/nbm_qmd rows
to `forecasts`, then verifies them with the EXACT harness query (so we know the
skill harness will pick them up) and sanity-checks vs the observed high.
Run from worktree: uv run python scripts/analysis/smoke_nbm.py
"""
import os
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

from weather_markets.nbm import ingest_nbm_run, purge_cache
from weather_markets.db import get_connection
from weather_markets.stations import get as get_station

ST = "KORD"
TZ = get_station(ST).timezone
CORE_DATES = ["2026-06-11", "2026-06-12", "2026-06-13"]
QMD_DATE = "2026-06-13"

# The harness's fetch_member_highs query, verbatim, so the smoke proves exactly
# what forecast_model_skill will see.
HARNESS_SQL = """
    SELECT (init_time AT TIME ZONE 'UTC')::date AS d, member_id, MAX(tmax_f) AS hi
    FROM forecasts
    WHERE station_id=%s AND model=%s
      AND EXTRACT(hour FROM init_time AT TIME ZONE 'UTC') = 0
      AND tmax_f IS NOT NULL
      AND (valid_time AT TIME ZONE %s)::date = (init_time AT TIME ZONE 'UTC')::date
    GROUP BY d, member_id ORDER BY d, member_id
"""


def main():
    for ds in CORE_DATES:
        rt = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
        print(f"--- ingest core {ST} {ds} ---")
        print(ingest_nbm_run(rt, station_id=ST))
    print(f"--- ingest qmd {ST} {QMD_DATE} fxx=[24] ---")
    rt = datetime.fromisoformat(QMD_DATE).replace(tzinfo=timezone.utc)
    print(ingest_nbm_run(rt, station_id=ST, forecast_hours=[24], include_qmd=True))

    conn = get_connection()
    with conn.cursor() as cur:
        for model in ("nbm", "nbm_qmd"):
            print(f"\n=== harness view: {ST} model={model} (daily-high per member, local day D) ===")
            cur.execute(HARNESS_SQL, (ST, model, TZ))
            rows = cur.fetchall()
            by_day = {}
            for d, mid, hi in rows:
                by_day.setdefault(d, {})[mid] = hi
            for d, mem in sorted(by_day.items()):
                cur.execute("SELECT high_temp_f FROM observations WHERE station_id=%s AND date=%s", (ST, d))
                o = cur.fetchone()
                obs = o[0] if o else None
                vals = list(mem.values())
                mean = sum(vals) / len(vals)
                print(f"  {d}: members={len(mem)} member_ids={sorted(mem)[:6]}{'...' if len(mem)>6 else ''} "
                      f"mean_high={mean:.2f}°F  obs_high={obs}  err={mean-obs:+.2f}" if obs else
                      f"  {d}: members={len(mem)} mean_high={mean:.2f}°F  obs=NA")
    conn.close()

    rss = int(open(f"/proc/{os.getpid()}/status").read().split("VmRSS:")[1].split()[0]) / 1024
    print(f"\nRSS={rss:.0f} MB")
    du = os.popen("du -sh ~/data/_p1_nbm 2>/dev/null").read().strip()
    print(f"cache size: {du or 'absent'}")
    purge_cache()
    print("purged cache:", not os.path.isdir(os.path.expanduser('~/data/_p1_nbm')))


if __name__ == "__main__":
    main()
