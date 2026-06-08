"""Backfill historical Kalshi prices via the candlesticks endpoints.

For each contract in the `contracts` table with target_date in the given range,
fetches OHLC candlesticks for its trading window and inserts close-bid/close-ask
snapshots into the `prices` table.

Routing:
  - Pre-cutoff markets (close_time < 2026-03-28) → /historical/markets/{ticker}/candlesticks
  - Post-cutoff markets → /series/{series}/markets/{ticker}/candlesticks

Both endpoints return OHLC for yes_bid, yes_ask, price (last), volume, open_interest
per period. We record close-of-period values as point-in-time snapshots.

Idempotent: ON CONFLICT (snapshot_at, ticker) DO NOTHING.

Run with:
    uv run python scripts/backfill_kalshi_prices.py --start-date 2025-05-01 --end-date 2026-05-01

Period interval choices: 1 (1-min), 60 (1-hour, default), 1440 (1-day).
60 is enough granularity for daily paper-trade reconstruction at 14:45 UTC.
"""
import argparse
import time
from datetime import date, datetime, timedelta, timezone
import httpx

from weather_markets.db import get_connection


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
HISTORICAL_CUTOFF = datetime(2026, 3, 28, tzinfo=timezone.utc)

REQUEST_DELAY_SECONDS = 0.1       # per-contract pace
MAX_RETRIES_ON_429 = 5
RETRY_BACKOFF_SECONDS = 2.0

INSERT_SQL = """
    INSERT INTO prices (
        snapshot_at, ticker, yes_bid, yes_ask, no_bid, no_ask,
        last_price, volume, volume_24h, open_interest
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (snapshot_at, ticker) DO NOTHING
"""


def get_with_retry(url: str, params: dict) -> httpx.Response | None:
    """GET with retry-on-429; returns None on 404 (market not in this partition)."""
    for attempt in range(MAX_RETRIES_ON_429 + 1):
        r = httpx.get(url, params=params, timeout=30)
        if r.status_code == 404:
            return None
        if r.status_code != 429:
            r.raise_for_status()
            return r
        wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
        time.sleep(wait)
    raise RuntimeError(f"Exhausted retries on 429 for {url}")


def cents(value_str) -> int | None:
    """Convert dollar-string to integer cents. None-safe."""
    if value_str is None:
        return None
    try:
        return int(round(float(value_str) * 100))
    except (ValueError, TypeError):
        return None


def to_int(value_str) -> int | None:
    if value_str is None:
        return None
    try:
        return int(round(float(value_str)))
    except (ValueError, TypeError):
        return None


def parse_candlestick(c: dict, ticker: str) -> tuple | None:
    """Parse a candlestick dict into a prices row tuple.

    Handles both schemas: live (close_dollars + _fp) and historical (close + raw)."""
    end_ts = c.get("end_period_ts")
    if end_ts is None:
        return None
    snapshot_at = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    yes_bid_obj = c.get("yes_bid") or {}
    yes_ask_obj = c.get("yes_ask") or {}
    price_obj = c.get("price") or {}

    yes_bid = cents(yes_bid_obj.get("close_dollars") or yes_bid_obj.get("close"))
    yes_ask = cents(yes_ask_obj.get("close_dollars") or yes_ask_obj.get("close"))
    last_price = cents(price_obj.get("close_dollars") or price_obj.get("close"))

    volume = to_int(c.get("volume_fp") or c.get("volume"))
    open_interest = to_int(c.get("open_interest_fp") or c.get("open_interest"))

    # No NO-side fields in candlesticks; no_bid = 100 - yes_ask (derived), no_ask = 100 - yes_bid.
    no_bid = (100 - yes_ask) if yes_ask is not None else None
    no_ask = (100 - yes_bid) if yes_bid is not None else None

    return (
        snapshot_at, ticker, yes_bid, yes_ask, no_bid, no_ask,
        last_price, volume, None, open_interest,
    )


def fetch_candlesticks(ticker: str, series: str, start_ts: int, end_ts: int,
                       use_historical: bool, period_interval: int) -> list[dict]:
    """Fetch candlesticks for one ticker, routing to historical or live endpoint."""
    if use_historical:
        url = f"{BASE_URL}/historical/markets/{ticker}/candlesticks"
    else:
        url = f"{BASE_URL}/series/{series}/markets/{ticker}/candlesticks"
    params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval}
    r = get_with_retry(url, params)
    if r is None:
        return []
    return r.json().get("candlesticks", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), required=True)
    parser.add_argument("--end-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), required=True)
    parser.add_argument("--period-interval", type=int, default=60, choices=[1, 60, 1440],
                        help="Candlestick interval in minutes (default 60).")
    parser.add_argument("--window-days", type=int, default=7,
                        help="How many days before close_time to start fetching (default 7).")
    parser.add_argument("--series", default=None,
                        help="Optional series filter (e.g. KXLOWTCHI). Default: all series.")
    args = parser.parse_args()

    # Get contracts in date range, optionally filtered to a series.
    with get_connection() as conn:
        with conn.cursor() as cur:
            if args.series:
                cur.execute("""
                    SELECT ticker, series, expiration_time, last_trading_time
                    FROM contracts
                    WHERE target_date BETWEEN %s AND %s AND series = %s
                    ORDER BY target_date, ticker
                """, (args.start_date, args.end_date, args.series))
            else:
                cur.execute("""
                    SELECT ticker, series, expiration_time, last_trading_time
                    FROM contracts
                    WHERE target_date BETWEEN %s AND %s
                    ORDER BY target_date, ticker
                """, (args.start_date, args.end_date))
            contracts = cur.fetchall()

    print(f"Backfilling prices for {len(contracts)} contracts ({args.start_date} → {args.end_date})")
    print(f"Period interval: {args.period_interval} minutes, window: {args.window_days} days before close")

    succeeded = 0
    failed = 0
    no_data = 0
    total_rows = 0
    t0 = time.time()

    with get_connection() as conn:
        for i, row in enumerate(contracts, 1):
            ticker, series, expiration, last_trading = row
            series = series or "KXHIGHNY"

            end_t = expiration or last_trading or datetime.now(tz=timezone.utc)
            start_t = (last_trading or end_t) - timedelta(days=args.window_days)

            use_historical = (last_trading is not None and last_trading < HISTORICAL_CUTOFF)

            try:
                candlesticks = fetch_candlesticks(
                    ticker, series,
                    int(start_t.timestamp()), int(end_t.timestamp()),
                    use_historical, args.period_interval,
                )
            except Exception as e:
                print(f"  [{i}/{len(contracts)}] {ticker}: FAILED ({type(e).__name__}: {e})", flush=True)
                failed += 1
                continue

            parsed = [p for p in (parse_candlestick(c, ticker) for c in candlesticks) if p]

            if parsed:
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, parsed)
                total_rows += len(parsed)
                succeeded += 1
            else:
                no_data += 1

            if i % 50 == 0 or i == len(contracts):
                elapsed = time.time() - t0
                rate = i / elapsed
                eta = (len(contracts) - i) / rate if rate > 0 else 0
                print(
                    f"  [{i}/{len(contracts)}] {ticker[:30]:30s} +{len(parsed)} rows "
                    f"(total {total_rows}, {elapsed:.0f}s elapsed, ETA {eta:.0f}s)",
                    flush=True,
                )

            time.sleep(REQUEST_DELAY_SECONDS)

    elapsed = time.time() - t0
    print(f"\n=== Done in {elapsed/60:.1f} min ===")
    print(f"  contracts processed: {len(contracts)}")
    print(f"  with prices:         {succeeded}")
    print(f"  no candlestick data: {no_data}")
    print(f"  failed:              {failed}")
    print(f"  total price rows:    {total_rows}")


if __name__ == "__main__":
    main()
