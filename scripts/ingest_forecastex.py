"""Ingest ForecastEx public market data (contracts + EOD prices + tick trades).

Reuses the existing `contracts` / `prices` tables with platform='forecastex' —
no new schema. ForecastEx "exceed {strike}" maps exactly onto our
bracket_type='greater_than' + strike_low convention, so scoring works unchanged
(see src/weather_markets/forecastex.py for the verification + BASIS WARNING).

Tick prints land in `prices` with snapshot_at = the trade timestamp and
last_price = the YES price in cents, so a backtest can price a trade at OUR
decision time rather than at the close. yes_bid/yes_ask stay NULL: ForecastEx
publishes no public order book (that needs the IBKR API).

Idempotent (ON CONFLICT DO NOTHING) — safe to re-run and safe to cron every
10 minutes against today, which is exactly how the forward collector works.

  uv run python scripts/ingest_forecastex.py                  # today (cron)
  uv run python scripts/ingest_forecastex.py --backfill 190   # history
  uv run python scripts/ingest_forecastex.py --date 2026-08-14
"""
import argparse
from datetime import date, datetime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.forecastex import (
    PRODUCT_TO_STATION, ForecastExClient, parse_contract_id, weather_rows,
)

CONTRACT_SQL = """
    INSERT INTO contracts (ticker, series, station_id, target_date, strike_low,
                           strike_high, bracket_type, expiration_time, platform)
    VALUES (%s,%s,%s,%s,%s,NULL,'greater_than',%s,'forecastex')
    ON CONFLICT (ticker) DO NOTHING
"""
PRICE_SQL = """
    INSERT INTO prices (snapshot_at, ticker, last_price, volume, open_interest)
    VALUES (%s,%s,%s,%s,%s)
    ON CONFLICT (snapshot_at, ticker) DO NOTHING
"""


def _cents(v) -> int | None:
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def ingest_day(conn, client: ForecastExClient, day: date) -> tuple[int, int, int]:
    """Returns (contracts_seen, eod_price_rows, tick_rows) for one date."""
    price_rows = client.prices(day)
    pair_rows = client.pairs(day)

    contracts: dict[str, tuple] = {}
    eod: list[tuple] = []
    # EOD close per contract (YES side carries the price we model on)
    for cid, station, event, strike, row in weather_rows(price_rows):
        exp = row.get("expiration_date") or None
        contracts[cid] = (cid, cid.split("_")[0], station, event, strike, exp)
        if row.get("subtype") != "YES":
            continue
        close_at = datetime.combine(day, datetime.min.time(),
                                    tzinfo=timezone.utc) + timedelta(hours=23, minutes=59)
        eod.append((close_at, cid, _cents(row.get("end_price")),
                    int(float(row.get("pair_quantity") or 0)),
                    int(float(row.get("open_interest") or 0))))

    ticks: list[tuple] = []
    for cid, station, event, strike, row in weather_rows(pair_rows):
        contracts.setdefault(cid, (cid, cid.split("_")[0], station, event, strike,
                                   row.get("expiration_date") or None))
        ts = row.get("pair_time")
        px = _cents(row.get("yes_price"))
        if not ts or px is None:
            continue
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            continue
        ticks.append((when, cid, px, int(float(row.get("quantity") or 0)), None))

    with conn.cursor() as cur:
        for c in contracts.values():
            cur.execute(CONTRACT_SQL, c)
        for row in eod:
            if row[2] is not None:
                cur.execute(PRICE_SQL, row)
        for row in ticks:
            cur.execute(PRICE_SQL, row)
    conn.commit()
    return len(contracts), len(eod), len(ticks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--backfill", type=int, metavar="N",
                    help="also ingest the N days BEFORE the target date")
    args = ap.parse_args()

    target = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    days = [target - timedelta(days=i) for i in range(0, (args.backfill or 0) + 1)]

    conn = get_connection()
    client = ForecastExClient()
    tot_c = tot_p = tot_t = 0
    try:
        for day in sorted(days):
            try:
                c, p, t = ingest_day(conn, client, day)
            except Exception as e:                      # one bad day must not kill a backfill
                conn.rollback()
                print(f"  {day}: FAILED {type(e).__name__}: {e}")
                continue
            tot_c, tot_p, tot_t = tot_c + c, tot_p + p, tot_t + t
            if c or t:
                print(f"  {day}: contracts={c:4d} eod={p:4d} ticks={t:5d}")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"{stamp} forecastex ingest: {len(days)} day(s), "
              f"{tot_c} contract rows, {tot_p} eod, {tot_t} ticks "
              f"({len(PRODUCT_TO_STATION)} mapped products)")
        return 0
    finally:
        client.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
