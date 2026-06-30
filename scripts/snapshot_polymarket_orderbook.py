"""Snapshot the full Polymarket US order book (every price level + size) for
the weather-temperature brackets of the cities we care about, into
`polymarket_orderbook_snapshots`.

WHY
---
We have ZERO Polymarket depth history (orderbook_snapshots is Kalshi-only).
The Polymarket viability research (docs/research/md/2026-06-29-...) found the
binding constraint is liquidity-at-size, measured from a SINGLE live read. This
script forward-collects per-level depth so the liquidity / maker-fill question
can be answered on accumulated data — mirroring snapshot_kalshi_orderbook.py so
the existing walk-the-book tooling transfers with minimal change.

READ-ONLY — NO TRADING
----------------------
This script calls ONLY Polymarket market-data GET endpoints:
    GET /v1/markets            (list/enumerate active climate markets)
    GET /v1/markets/{slug}/book  (L2 order book + stats)   [primary]
    GET /v1/markets/{slug}/bbo   (best bid/offer)          [fallback for BBO]
It NEVER constructs an order object and NEVER calls any Create/Insert/Cancel/
Replace/Close endpoint. It writes only to our local Postgres. The Polymarket
host is a real CFTC-regulated venue (gateway.polymarket.us); an accidental order
would be real money — there is deliberately no order code path in this module.

NORMALIZATION (YES/NO <-> Polymarket token; see migration 005 for the full contract)
-----------------------------------------------------------------------------------
Polymarket quotes the YES token as two ladders:
    marketData.bids   = resting YES buy orders  (YES bid @ price p, 0..1)
    marketData.offers = resting YES sell orders (YES ask @ price p, 0..1)
We map into Kalshi's "resting bid on each side" convention so walk-book code
(yes_ask = 100 - max(no price)) works unchanged across venues:
    bids   (YES bid @ p)  -> side='yes', price_cents=round(p*100),     raw_prob=p
    offers (YES ask @ p)  -> side='no',  price_cents=round((1-p)*100), raw_prob=(1-p)
We keep raw_prob (full precision) and raw_size (native shares) alongside the
rounded Kalshi-parity price_cents/qty.

Idempotent: ON CONFLICT DO NOTHING on (snapshot_at, ticker, side, price_cents).
Run every ~5 min via cron during the trading window (matches Kalshi cadence).

Usage (line-buffered for tmux):
    uv run python -u scripts/snapshot_polymarket_orderbook.py
    uv run python -u scripts/snapshot_polymarket_orderbook.py --dry-run
    uv run python -u scripts/snapshot_polymarket_orderbook.py --stations KMIA KMDW
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.polymarket import PolymarketClient

# The regulated US venue. The existing price-snapshot cron uses this host.
GATEWAY_BASE_URL = "https://gateway.polymarket.us"

# FK-safe contract upsert — identical to scripts/snapshot_polymarket_prices.py
# (kept inline rather than cross-imported: `scripts/` is not an importable
# package, so a `from scripts.* import` breaks when run as a plain script/cron).
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
    bracket_type, strike_low, strike_high) or None if not parseable.

    Mirrors scripts/snapshot_polymarket_prices.py:_parse_polymarket_slug so the
    contract metadata written here matches what the price snapshotter writes.
    """
    m = re.match(
        r"^tc-temp-(?P<city>[a-z]+)-(?P<date>\d{4}-\d{2}-\d{2})-(?P<spec>[a-z0-9]+)f$",
        slug,
    )
    if not m:
        return None
    station = CITY_TOKEN_TO_STATION.get(m.group("city"))
    if not station:
        return None
    try:
        target_date = datetime.strptime(m.group("date"), "%Y-%m-%d").date()
    except ValueError:
        return None
    spec = m.group("spec")
    series = f"tc-temp-{m.group('city')}"
    if (mm := re.match(r"^lt(\d+)$", spec)):
        return (station, series, target_date, "less_than", None, float(mm.group(1)))
    if (mm := re.match(r"^gte(\d+)lt(\d+)$", spec)):
        return (station, series, target_date, "between", float(mm.group(1)), float(mm.group(2)))
    if (mm := re.match(r"^gte(\d+)$", spec)):
        return (station, series, target_date, "greater_than", float(mm.group(1)), None)
    return None

# Cities (NWS stations) Polymarket US lists weather markets for, mapped from the
# slug city token. KMIA + KMDW are the must-haves (KMDW = Chicago MIDWAY, NOT
# KORD/O'Hare); the rest are easy adds since they share the slug format.
CITY_TOKEN_TO_STATION = {
    "miahigh": "KMIA",   # Miami            (must-have; fungible w/ Kalshi)
    "mdwhigh": "KMDW",   # Chicago MIDWAY   (must-have; NOT KORD)
    "nychigh": "KNYC",   # New York
    "laxhigh": "KLAX",   # Los Angeles
    "sfohigh": "KSFO",   # San Francisco
}
DEFAULT_STATIONS = list(CITY_TOKEN_TO_STATION.values())

INSERT_SQL = """
INSERT INTO polymarket_orderbook_snapshots (
    snapshot_at, venue, ticker, station_id, target_date, bracket_label,
    side, price_cents, qty, raw_prob, raw_size, best_bid_prob, best_ask_prob
)
VALUES (%s, 'polymarket_us', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (snapshot_at, ticker, side, price_cents) DO NOTHING
"""


def _bracket_label(bracket_type: str, strike_low, strike_high) -> str:
    """Human-readable bracket label, e.g. '93-94', '>=95', '<70'."""
    if bracket_type == "between" and strike_low is not None and strike_high is not None:
        return f"{int(strike_low)}-{int(strike_high)}"
    if bracket_type == "greater_than" and strike_low is not None:
        return f">={int(strike_low)}"
    if bracket_type == "less_than" and strike_high is not None:
        return f"<{int(strike_high)}"
    return bracket_type


def _amount_value(node) -> float | None:
    """Extract a 0..1 decimal from a Polymarket Amount-ish node.

    Handles {'value': '0.45', 'currency': 'USD'} and bare strings/numbers.
    Returns None on anything unparseable.
    """
    if node is None:
        return None
    if isinstance(node, dict):
        node = node.get("value")
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


def _book_entries(market_data: dict, key: str) -> list:
    """Return the bids/offers ladder, tolerating a couple of doc-vs-wire shapes.

    Documented shape (markets-schema.json GetMarketBookResponse):
        marketData.bids / marketData.offers : [ {px:{value}, qty:"..."} ]
    Some responses nest the ladder under marketData.book.{bids,asks/offers}.
    """
    if not isinstance(market_data, dict):
        return []
    if isinstance(market_data.get(key), list):
        return market_data[key]
    book = market_data.get("book")
    if isinstance(book, dict):
        # 'offers' may surface as 'asks' in the nested form
        alt = "asks" if key == "offers" else key
        for k in (key, alt):
            if isinstance(book.get(k), list):
                return book[k]
    return []


def _entry_px_qty(entry) -> tuple[float, float] | None:
    """A BookEntry -> (prob 0..1, size). Tolerates {px:{value},qty} and [p,q]."""
    if isinstance(entry, dict):
        p = _amount_value(entry.get("px") if "px" in entry else entry.get("price"))
        q = entry.get("qty", entry.get("size"))
    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
        p, q = _amount_value(entry[0]), entry[1]
    else:
        return None
    try:
        q = float(q)
    except (TypeError, ValueError):
        return None
    if p is None or q is None or q <= 0:
        return None
    return p, q


def _rows_for_book(
    snap_ts: datetime,
    slug: str,
    station_id: str,
    target_date,
    bracket_label: str,
    market_data: dict,
    best_bid_prob: float | None = None,
    best_ask_prob: float | None = None,
) -> list[tuple]:
    """Turn one market's order book into normalized rows (Kalshi convention).

    bids   (YES bid @ p)  -> side='yes', price_cents=round(p*100),     raw_prob=p
    offers (YES ask @ p)  -> side='no',  price_cents=round((1-p)*100), raw_prob=(1-p)

    best_bid_prob/best_ask_prob are the YES-token BBO at snapshot time. The /book
    endpoint does NOT carry BBO (its `stats` holds open/close/hi/lo, not touch),
    so callers pass values fetched from the lightweight /bbo endpoint. If not
    supplied we fall back to deriving the touch from the ladder itself.
    """
    if best_bid_prob is None:
        best_bid_prob = _amount_value(market_data.get("bestBid"))
    if best_ask_prob is None:
        best_ask_prob = _amount_value(market_data.get("bestAsk"))

    rows: list[tuple] = []

    def add(side: str, prob: float, size: float) -> None:
        cents = int(round(prob * 100))
        if not (1 <= cents <= 99):  # drop dead-tail 0/100 levels (unrepresentable)
            return
        qty = int(round(size))
        if qty <= 0:
            return
        rows.append((
            snap_ts, slug, station_id, target_date, bracket_label,
            side, cents, qty, prob, size, best_bid_prob, best_ask_prob,
        ))

    for entry in _book_entries(market_data, "bids"):
        pq = _entry_px_qty(entry)
        if pq:
            p, q = pq
            add("yes", p, q)        # YES bid

    for entry in _book_entries(market_data, "offers"):
        pq = _entry_px_qty(entry)
        if pq:
            p, q = pq
            add("no", 1.0 - p, q)   # YES ask == NO bid @ (1-p)

    return rows


def _enumerate_active_climate_markets(client: PolymarketClient) -> list[dict]:
    """READ-ONLY: GET /v1/markets, paginated, active climate markets only."""
    markets: list[dict] = []
    for offset in range(0, 5000, 100):
        r = client._request("GET", "/v1/markets", params={
            "limit": 100, "offset": offset,
            "categories": "climate", "active": "true",
        })
        items = r.get("markets", []) if isinstance(r, dict) else []
        if not items:
            break
        markets.extend(items)
        if len(items) < 100:
            break
    return markets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stations", nargs="+", default=DEFAULT_STATIONS,
        help=f"NWS stations to snapshot (default: {' '.join(DEFAULT_STATIONS)})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch + normalize + print sample rows, but DO NOT write to the DB.",
    )
    parser.add_argument(
        "--max-future-days", type=int, default=2,
        help="Also snapshot markets settling within N days ahead (forward listings).",
    )
    args = parser.parse_args()

    target_stations = set(args.stations)
    today = date.today()
    horizon = today + timedelta(days=args.max_future_days)
    snap_ts = datetime.now(tz=timezone.utc)

    print(f"[{snap_ts.isoformat()}] Polymarket orderbook snapshot "
          f"(stations={sorted(target_stations)}, dry_run={args.dry_run})", flush=True)

    try:
        client = PolymarketClient(base_url=GATEWAY_BASE_URL)
    except Exception as e:
        print(f"Polymarket auth/init failed — skipping snapshot: "
              f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # 1. Enumerate active climate markets (READ-ONLY list endpoint).
    try:
        markets = _enumerate_active_climate_markets(client)
    except Exception as e:
        print(f"Market enumeration failed: {type(e).__name__}: {e}",
              file=sys.stderr, flush=True)
        sys.exit(1)
    print(f"  enumerated {len(markets)} active climate markets", flush=True)

    # 2. Filter to our target stations' temperature brackets in window.
    targets: list[tuple[str, str, object, str, float, float, str]] = []
    for m in markets:
        slug = m.get("slug", "")
        if not slug.startswith("tc-temp-"):
            continue
        parsed = _parse_polymarket_slug(slug)
        if not parsed:
            continue
        station_id, series, td_, bt, sl, sh = parsed
        if station_id not in target_stations:
            continue
        if td_ < today or td_ > horizon:
            continue
        targets.append((slug, station_id, td_, bt, sl, sh, series))
    print(f"  {len(targets)} target brackets in window "
          f"[{today} .. {horizon}]", flush=True)

    # 3. For each target, pull the L2 book (READ-ONLY) and normalize.
    all_rows: list[tuple] = []
    n_books_ok = 0
    n_books_fail = 0
    n_empty = 0
    per_station_levels: dict[str, int] = {}

    for slug, station_id, td_, bt, sl, sh, series in targets:
        bracket_label = _bracket_label(bt, sl, sh)
        try:
            resp = client.get_orderbook(slug)   # GET /v1/markets/{slug}/book
        except Exception as e:
            n_books_fail += 1
            print(f"  {slug}: book fetch failed — {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
            continue

        market_data = resp.get("marketData", resp) if isinstance(resp, dict) else {}

        # Lightweight READ-ONLY BBO call — /book carries no touch, only stats.
        best_bid_prob = best_ask_prob = None
        try:
            bbo = client.get_bbo(slug)              # GET /v1/markets/{slug}/bbo
            bmd = bbo.get("marketData", bbo) if isinstance(bbo, dict) else {}
            best_bid_prob = _amount_value(bmd.get("bestBid"))
            best_ask_prob = _amount_value(bmd.get("bestAsk"))
        except Exception as e:
            print(f"  {slug}: bbo fetch failed (non-fatal) — {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)

        rows = _rows_for_book(snap_ts, slug, station_id, td_, bracket_label,
                              market_data, best_bid_prob, best_ask_prob)
        n_books_ok += 1
        if not rows:
            n_empty += 1
        all_rows.extend(rows)
        per_station_levels[station_id] = per_station_levels.get(station_id, 0) + len(rows)

        # FK safety: upsert contract metadata before any write (Polymarket lists
        # new tickers daily). Done in the write phase below for dry-run safety.

    # 4. Report + write.
    print(f"  books: {n_books_ok} ok ({n_empty} empty), {n_books_fail} failed; "
          f"{len(all_rows)} normalized levels", flush=True)
    for st in sorted(per_station_levels):
        print(f"    {st}: {per_station_levels[st]} levels", flush=True)

    # Sample (works for both dry-run and live): show a few brackets' touch.
    _print_sample(all_rows)

    if args.dry_run:
        print("  DRY RUN — nothing written to the database.", flush=True)
        return

    if not all_rows:
        print("  no rows to write.", flush=True)
        return

    # Upsert contracts (FK) then bulk-insert levels.
    n_written = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for slug, station_id, td_, bt, sl, sh, series in targets:
                cur.execute(UPSERT_CONTRACT_SQL,
                            (slug, series, station_id, td_, sl, sh, bt))
            cur.executemany(INSERT_SQL, all_rows)
            n_written = len(all_rows)
        conn.commit()
    print(f"  wrote {n_written} levels to polymarket_orderbook_snapshots", flush=True)


def _print_sample(rows: list[tuple], n_brackets: int = 4) -> None:
    """Print best_bid/ask + a couple depth levels for the first few brackets."""
    if not rows:
        print("  (no levels to sample)", flush=True)
        return
    # group by (station, slug)
    by_market: dict[tuple, list[tuple]] = {}
    for r in rows:
        by_market.setdefault((r[2], r[1], r[4]), []).append(r)  # station, slug, bracket_label
    # row tuple layout (see INSERT_SQL): 0 snap_ts, 1 slug, 2 station_id,
    # 3 target_date, 4 bracket_label, 5 side, 6 price_cents, 7 qty,
    # 8 raw_prob, 9 raw_size, 10 best_bid_prob, 11 best_ask_prob
    print("  --- sample (Kalshi-convention; price_cents=round(prob*100)) ---", flush=True)
    for (station, slug, bracket), levels in list(by_market.items())[:n_brackets]:
        yes = sorted([l for l in levels if l[5] == "yes"], key=lambda l: -l[6])
        no = sorted([l for l in levels if l[5] == "no"], key=lambda l: -l[6])
        yes_bid = yes[0][6] if yes else None                 # best YES bid (cents)
        yes_ask = (100 - no[0][6]) if no else None           # 100 - max no price
        bb = levels[0][10]
        ba = levels[0][11]
        print(f"  {station} {bracket:<8} ({slug})", flush=True)
        print(f"      BBO(yes-token): bid={bb} ask={ba} | "
              f"derived yes_bid={yes_bid}c yes_ask={yes_ask}c "
              f"spread={None if (yes_bid is None or yes_ask is None) else yes_ask - yes_bid}c",
              flush=True)
        for l in yes[:3]:
            print(f"      yes  {l[6]:>3}c  qty={l[7]:<6} (raw_prob={l[8]:.4f} raw_size={l[9]})", flush=True)
        for l in no[:3]:
            print(f"      no   {l[6]:>3}c  qty={l[7]:<6} (raw_prob={l[8]:.4f} raw_size={l[9]})", flush=True)


if __name__ == "__main__":
    main()
