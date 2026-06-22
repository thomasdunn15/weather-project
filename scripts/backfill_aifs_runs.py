"""Backfill ECMWF-AIFS runs across a date range for the 00Z init.

AIFS is a GLOBAL 0.25° grid, so unlike a per-station regional backfill this
downloads each (init, fxx) GRIB exactly ONCE and extracts every requested
station from that single file (Herbie caches it; we re-`.sel` per station). That
keeps the box's network/disk light. Each downloaded GRIB day is purged after the
day's rows are written (--no-purge to keep them).

  AIFS-Single (default):  product='oper'  -> forecasts.model='aifs'      (member 0)
  AIFS-ENS    (--ensemble): product='enfo' -> forecasts.model='aifs_ens'  (members 1..50)

Examples (run in tmux, line-buffered):
    # AIFS-Single, full window, all 8 staged stations:
    uv run python scripts/backfill_aifs_runs.py \
        --start 2024-04-01 --end 2026-06-18 \
        --stations KORD,KMDW,KMIA,KSEA,KLAS,KSFO,KLAX,KPHX

    # AIFS-ENS, its ~11-month sub-window:
    uv run python scripts/backfill_aifs_runs.py --ensemble \
        --start 2025-07-15 --end 2026-06-18 \
        --stations KORD,KMDW,KMIA,KSEA,KLAS,KSFO,KLAX,KPHX

Each date is independent; failures are logged and the loop continues.
"""
import argparse
import shutil
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

from herbie import Herbie

from weather_markets.aifs import (
    DEFAULT_FORECAST_HOURS,
    EXPECTED_ENS_MEMBERS,
    build_rows,
    lon_for_grid,
    _extract_member_temps_k,
    _valid_time_utc,
)
from weather_markets.db import get_connection
from weather_markets.stations import get as get_station

INSERT_SQL = """
    INSERT INTO forecasts (init_time, valid_time, station_id, model, member_id, temperature_f, tmax_f)
    VALUES (%(init_time)s, %(valid_time)s, %(station_id)s, %(model)s, %(member_id)s, %(temperature_f)s, %(tmax_f)s)
    ON CONFLICT (init_time, valid_time, station_id, model, member_id) DO NOTHING
"""

CACHE_ROOT = Path.home() / "data" / "aifs"


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _rows_present(conn, station_id: str, run_time: datetime, model: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM forecasts WHERE station_id=%s AND model=%s AND init_time=%s",
            (station_id, model, run_time),
        )
        return cur.fetchone()[0]


def _purge_day(run_time: datetime) -> None:
    day_dir = CACHE_ROOT / f"{run_time:%Y%m%d}"
    shutil.rmtree(day_dir, ignore_errors=True)


def backfill_day(conn, run_time: datetime, stations: list[str], product: str,
                 db_model: str, forecast_hours: list[int], expected_per_fxx: int) -> dict:
    """Download each fxx once, extract all stations, insert. Returns counts."""
    target_rows = expected_per_fxx * len(forecast_hours)
    todo = [s for s in stations if _rows_present(conn, s, run_time, db_model) < target_rows]
    if not todo:
        return {"skipped": True}

    run_naive = run_time.replace(tzinfo=None)
    rows: list[dict] = []
    for fxx in forecast_hours:
        try:
            H = Herbie(run_naive, model="aifs", product=product, fxx=fxx)
            ds = H.xarray(":2t:sfc:")
            if isinstance(ds, list):
                ds = ds[0]
            key = "t2m" if "t2m" in ds.data_vars else list(ds.data_vars)[0]
            lon_min = float(ds.longitude.values.min())
            lon_max = float(ds.longitude.values.max())
            valid_time = _valid_time_utc(ds)
            n_each = []
            for st in todo:
                station = get_station(st)
                lon = lon_for_grid(lon_min, lon_max, station.longitude)
                temps = _extract_member_temps_k(ds, key, station.latitude, lon)
                rows.extend(build_rows(run_time, valid_time, st, db_model, temps))
                n_each.append(len(temps))
            n = n_each[0] if n_each else 0
            tag = "WARNING incomplete: " if (product == "enfo" and n < EXPECTED_ENS_MEMBERS) else ""
            print(f"  fxx={fxx:3d}h: {tag}{n} member(s) x {len(todo)} station(s) "
                  f"[{db_model}] @ {valid_time.isoformat()}", flush=True)
        except Exception as e:
            print(f"  fxx={fxx:3d}h: SKIPPED ({type(e).__name__}: {e})", flush=True)
        time.sleep(0.3)  # one rate-limit pause per DOWNLOAD (not per station)

    if rows:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows)
        conn.commit()
    return {"skipped": False, "rows": len(rows), "stations": len(todo)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=parse_date, required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", type=parse_date, required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--stations", required=True,
                        help="Comma-separated station IDs, e.g. KORD,KMDW,KMIA,KSEA")
    parser.add_argument("--ensemble", action="store_true",
                        help="Backfill AIFS-ENS (enfo, model='aifs_ens'). Default: AIFS-Single (oper).")
    parser.add_argument("--forecast-hours", type=lambda s: [int(x) for x in s.split(",")],
                        default=None, help="Override forecast-hour list (default 18,24).")
    parser.add_argument("--no-purge", action="store_true", help="Keep downloaded GRIBs.")
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    stations = [s.strip() for s in args.stations.split(",") if s.strip()]
    for s in stations:
        get_station(s)  # validate up front

    forecast_hours = args.forecast_hours if args.forecast_hours is not None else DEFAULT_FORECAST_HOURS
    product = "enfo" if args.ensemble else "oper"
    db_model = "aifs_ens" if args.ensemble else "aifs"
    expected_per_fxx = EXPECTED_ENS_MEMBERS if args.ensemble else 1

    total_days = (args.end - args.start).days + 1
    print(f"Backfilling {total_days} day(s) of {db_model} 00Z "
          f"({product}) from {args.start} to {args.end} "
          f"for {len(stations)} station(s): {','.join(stations)} "
          f"(forecast_hours={forecast_hours}, purge={not args.no_purge})", flush=True)

    conn = get_connection()
    succeeded = failed = skipped = 0
    overall = time.time()
    current = args.start
    while current <= args.end:
        run_time = datetime(current.year, current.month, current.day, 0, 0, tzinfo=timezone.utc)
        print(f"\n=== {run_time.date()} ===", flush=True)
        t0 = time.time()
        try:
            res = backfill_day(conn, run_time, stations, product, db_model,
                               forecast_hours, expected_per_fxx)
            if res.get("skipped"):
                print("  SKIP (already complete)", flush=True)
                skipped += 1
            else:
                print(f"  OK in {time.time()-t0:.0f}s: {res['rows']} rows "
                      f"across {res['stations']} station(s)", flush=True)
                succeeded += 1
        except Exception as e:
            print(f"  FAILED after {time.time()-t0:.0f}s: {type(e).__name__}: {e}", flush=True)
            failed += 1
        finally:
            if not args.no_purge:
                _purge_day(run_time)
        current += timedelta(days=1)

    conn.close()
    print(f"\n=== Done {db_model}: {succeeded} OK, {skipped} skipped, {failed} failed "
          f"in {(time.time()-overall)/60:.1f} min ===", flush=True)


if __name__ == "__main__":
    main()
