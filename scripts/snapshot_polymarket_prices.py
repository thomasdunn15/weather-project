"""Snapshot current Polymarket bid/ask + settlement into the prices table.

Run via cron every 5min (matches Kalshi snapshot cadence).

Polymarket has no historical-price endpoint, so the only way to build a price
history is forward-snapshotting. Each row in `prices` table represents a single
moment in time.

Pulls all active climate markets, plus closed markets settled within the last 7
days (to ensure we have settlement_px on file for recently-resolved markets).

Maps Polymarket's USD-decimal prices to our cents convention:
  YES bid = bestBid * 100
  YES ask = bestAsk * 100
  NO  bid = (1 - bestAsk) * 100  (NO bid in YES terms)
  NO  ask = (1 - bestBid) * 100
"""
import argparse
from datetime import datetime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.polymarket import PolymarketClient


INSERT_PRICE_SQL = """
INSERT INTO prices (
    ticker, snapshot_at, yes_bid, yes_ask, no_bid, no_ask,
    last_price, volume
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (snapshot_at, ticker) DO NOTHING
"""

# Upsert any new contract before snapshotting its price — Polymarket adds new
# tickers daily and the FK to contracts.ticker would otherwise crash the run.
UPSERT_CONTRACT_SQL = """
INSERT INTO contracts (
    ticker, series, station_id, target_date,
    strike_low, strike_high, bracket_type, platform
)
VALUES (%s, %s, %s, %s, %s, %s, %s, 'polymarket')
ON CONFLICT (ticker) DO NOTHING
"""


def _parse_polymarket_slug(slug: str):
    """tc-temp-{city}-{YYYY-MM-DD}-{spec}f -> (station_id, series, target_date,
    bracket_type, strike_low, strike_high) or None if not parseable."""
    import re
    from datetime import datetime as _dt
    CITY_TO_STATION = {
        "mdwhigh": "KMDW", "nychigh": "KNYC", "miahigh": "KMIA",
        "laxhigh": "KLAX", "sfohigh": "KSFO",
    }
    m = re.match(r"^tc-temp-(?P<city>[a-z]+)-(?P<date>\d{4}-\d{2}-\d{2})-(?P<spec>[a-z0-9]+)f$", slug)
    if not m: return None
    station = CITY_TO_STATION.get(m.group("city"))
    if not station: return None
    try:
        target_date = _dt.strptime(m.group("date"), "%Y-%m-%d").date()
    except ValueError: return None
    spec = m.group("spec")
    if (mm := re.match(r"^lt(\d+)$", spec)):
        return (station, f"tc-temp-{m.group('city')}", target_date, "less_than", None, float(mm.group(1)))
    if (mm := re.match(r"^gte(\d+)lt(\d+)$", spec)):
        return (station, f"tc-temp-{m.group('city')}", target_date, "between", float(mm.group(1)), float(mm.group(2)))
    if (mm := re.match(r"^gte(\d+)$", spec)):
        return (station, f"tc-temp-{m.group('city')}", target_date, "greater_than", float(mm.group(1)), None)
    return None


def cents_or_none(v):
    if v is None:
        return None
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-closed-days", type=int, default=7,
                        help="Also fetch closed markets settled within N days (default 7)")
    args = parser.parse_args()

    client = PolymarketClient(base_url="https://gateway.polymarket.us")
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=args.include_closed_days)

    # 1. Pull all active climate markets
    active_markets = []
    for offset in range(0, 5000, 100):
        r = client._request("GET", "/v1/markets", params={
            "limit": 100, "offset": offset,
            "categories": "climate", "active": "true",
        })
        items = r.get("markets", []) if isinstance(r, dict) else []
        if not items:
            break
        active_markets.extend(items)
        if len(items) < 100:
            break

    # 2. Pull recently closed climate markets
    closed_markets = []
    for offset in range(0, 5000, 100):
        r = client._request("GET", "/v1/markets", params={
            "limit": 100, "offset": offset,
            "categories": "climate", "closed": "true",
        })
        items = r.get("markets", []) if isinstance(r, dict) else []
        if not items:
            break
        for m in items:
            end_dt = m.get("endDate")
            if end_dt:
                try:
                    end_parsed = datetime.fromisoformat(end_dt.replace("Z","+00:00"))
                    if end_parsed >= cutoff:
                        closed_markets.append(m)
                except ValueError:
                    pass
        if len(items) < 100:
            break

    markets = active_markets + closed_markets
    print(f"Snapshotting {len(active_markets)} active + {len(closed_markets)} recently-closed = {len(markets)} total")

    import json
    n_inserted = 0
    n_failed = 0
    with get_connection() as conn, conn.cursor() as cur:
        for i, m in enumerate(markets, 1):
            slug = m.get("slug","")
            if not slug.startswith("tc-temp-"):
                continue
            try:
                bbo = client.get_bbo(slug)
            except Exception as e:
                n_failed += 1
                continue
            md = bbo.get("marketData", {})
            best_bid = md.get("bestBid", {}).get("value") if md.get("bestBid") else None
            best_ask = md.get("bestAsk", {}).get("value") if md.get("bestAsk") else None
            last_trade = md.get("lastTradePx", {}).get("value") if md.get("lastTradePx") else None
            settlement = md.get("settlementPx", {}).get("value") if md.get("settlementPx") else None
            volume = md.get("sharesTraded") or md.get("openInterest")

            yes_bid_c = cents_or_none(best_bid)
            yes_ask_c = cents_or_none(best_ask)
            no_bid_c = (100 - yes_ask_c) if yes_ask_c is not None else None
            no_ask_c = (100 - yes_bid_c) if yes_bid_c is not None else None
            last_c = cents_or_none(last_trade)

            # Upsert the contract first to satisfy the FK. Polymarket lists
            # new tickers daily; without this the snapshot crashes the first
            # time a brand-new ticker shows up.
            parsed = _parse_polymarket_slug(slug)
            if parsed:
                station_id, series, td_, bt, sl, sh = parsed
                cur.execute(UPSERT_CONTRACT_SQL, (slug, series, station_id, td_, sl, sh, bt))
            cur.execute(
                INSERT_PRICE_SQL,
                (slug, now, yes_bid_c, yes_ask_c, no_bid_c, no_ask_c,
                 last_c, int(float(volume)) if volume else None),
            )
            n_inserted += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(markets)}] {slug[:50]:<50} bid={yes_bid_c} ask={yes_ask_c}", flush=True)

    print(f"\nDone: {n_inserted} snapshots inserted, {n_failed} failed")


if __name__ == "__main__":
    main()
