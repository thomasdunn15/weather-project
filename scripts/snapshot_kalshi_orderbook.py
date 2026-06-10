# scripts/snapshot_kalshi_orderbook.py
"""Snapshot the full Kalshi order book (all price levels with quantities) for
every active daily-high contract across every registered station.

Powers the walk-the-book execution backtest: without per-level depth data,
we can only run synthetic-depth simulations. With 30+ days of real depth
data, we can model the marginal-cost curve at each price level and validate
whether scaling beyond top-of-book actually adds EV.

Runs every 5 minutes (same cadence as snapshot_kalshi_prices.py). For each
active contract, fetches the full orderbook, stores one row per (snapshot,
ticker, side, price_cents). The yes/no arrays get split into separate rows
so SQL queries can walk them per-side without parsing JSON.

Idempotent: ON CONFLICT DO NOTHING on the primary key (snapshot_at, ticker,
side, price_cents) handles concurrent or repeated runs.
"""
from __future__ import annotations

import sys
from datetime import datetime, date, timedelta, timezone

from weather_markets.db import get_connection
from weather_markets.kalshi_api import KalshiClient, KalshiAuthError, parse_count
from weather_markets.stations import all_stations


INSERT_SQL = """
INSERT INTO orderbook_snapshots (snapshot_at, ticker, side, price_cents, qty)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (snapshot_at, ticker, side, price_cents) DO NOTHING
"""


def _level_to_cents_qty(level) -> tuple[int, int] | None:
    """Kalshi returns price as a fixed-point string (e.g., '0.4500') and qty
    as a fixed-point string (e.g., '500.0000'). Convert to (cents, contracts).
    Skip if either is malformed."""
    try:
        price_dollars = float(level[0])
        qty = float(level[1])
        cents = int(round(price_dollars * 100))
        qty_int = int(round(qty))
        if 1 <= cents <= 99 and qty_int > 0:
            return cents, qty_int
    except (ValueError, TypeError, IndexError):
        pass
    return None


def snapshot_for_series(client: KalshiClient, conn, series: str, today: date) -> tuple[int, int]:
    """Fetch all active contracts for a series and snapshot each orderbook.
    Returns (n_contracts_snapped, n_rows_inserted)."""
    n_contracts = 0
    n_rows = 0
    snap_ts = datetime.now(tz=timezone.utc)

    # Pull active contracts for this series for today (and a buffer for forward
    # listings — Kalshi sometimes lists tomorrow's contracts during the day).
    with conn.cursor() as cur:
        cur.execute(
            """SELECT ticker FROM contracts
               WHERE series=%s AND target_date BETWEEN %s AND %s
                 AND platform='kalshi'""",
            (series, today, today + timedelta(days=2)),
        )
        tickers = [r[0] for r in cur.fetchall()]

    if not tickers:
        return 0, 0

    rows_to_insert = []
    for ticker in tickers:
        try:
            resp = client.get_orderbook(ticker)
        except Exception as e:
            print(f"  {ticker}: orderbook fetch failed — {e}", file=sys.stderr)
            continue

        # Kalshi response: orderbook_fp.{yes_dollars, no_dollars} where each
        # array contains [price_dollars_str, qty_fp_str] pairs. Older docs say
        # the wrapper is "orderbook" with "yes"/"no" keys — handle both.
        book = resp.get("orderbook_fp") or resp.get("orderbook") or {}
        yes_levels = book.get("yes_dollars") or book.get("yes") or []
        no_levels = book.get("no_dollars") or book.get("no") or []

        for level in yes_levels:
            parsed = _level_to_cents_qty(level)
            if parsed:
                cents, qty = parsed
                rows_to_insert.append((snap_ts, ticker, "yes", cents, qty))
        for level in no_levels:
            parsed = _level_to_cents_qty(level)
            if parsed:
                cents, qty = parsed
                rows_to_insert.append((snap_ts, ticker, "no", cents, qty))
        n_contracts += 1

    # Bulk insert
    if rows_to_insert:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows_to_insert)
        n_rows = len(rows_to_insert)
    conn.commit()
    return n_contracts, n_rows


def main() -> None:
    today = date.today()
    try:
        client = KalshiClient()
    except KalshiAuthError as e:
        print(f"Kalshi auth failed — skipping orderbook snapshot: {e}", file=sys.stderr)
        sys.exit(1)

    n_series = 0
    total_contracts = 0
    total_rows = 0
    with get_connection() as conn:
        for station in all_stations():
            if not station.kalshi_series:
                continue   # KMDW/KSFO — Polymarket-only stations
            for series in (station.kalshi_series, station.kalshi_series_low):
                if not series:
                    continue
                try:
                    c, r = snapshot_for_series(client, conn, series, today)
                    n_series += 1
                    total_contracts += c
                    total_rows += r
                    print(f"{station.station_id} / {series}: {c} contracts, {r} levels")
                except Exception as e:
                    print(f"  {station.station_id} / {series} snapshot raised: {type(e).__name__}: {e}", file=sys.stderr)

    print(f"\nTotal: {n_series} series, {total_contracts} contracts snapped, {total_rows} levels inserted")


if __name__ == "__main__":
    main()
