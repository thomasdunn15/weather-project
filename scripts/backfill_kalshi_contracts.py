"""Backfill historical KXHIGHNY contracts via the Kalshi API.

Discovers contracts from two endpoints (Kalshi partitions data at 2026-03-28):
  - /historical/markets (pre-cutoff settled markets)
  - /markets?status=settled (post-cutoff but already settled)

Filters by target_date range, dedupes, and inserts into the `contracts` table
with ON CONFLICT (ticker) DO NOTHING.

Idempotent: safe to re-run; existing rows are skipped.

Run with:
    uv run python scripts/backfill_kalshi_contracts.py --start-date 2025-05-01 --end-date 2026-05-01
"""
import argparse
import time
from datetime import date, datetime
import httpx
from psycopg.types.json import Jsonb

from weather_markets.db import get_connection


REQUEST_DELAY_SECONDS = 0.25      # gentle pace between paginated calls
MAX_RETRIES_ON_429 = 5
RETRY_BACKOFF_SECONDS = 2.0       # multiplied each retry


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
BRACKET_TYPE_MAP = {"greater": "greater_than", "less": "less_than", "between": "between"}

INSERT_SQL = """
    INSERT INTO contracts (
        ticker, series, station_id, target_date,
        strike_low, strike_high, bracket_type,
        expiration_time, last_trading_time, raw_metadata
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (ticker) DO NOTHING
"""


def event_ticker_to_date(event_ticker: str) -> date:
    """KXHIGHNY-26MAR26 -> date(2026, 3, 26)."""
    date_str = event_ticker.split("-")[-1]  # "26MAR26"
    yy, mon_str, dd = date_str[0:2], date_str[2:5], date_str[5:7]
    return date(2000 + int(yy), MONTHS[mon_str], int(dd))


def get_with_retry(url: str, params: dict) -> httpx.Response:
    """GET with retry-on-429 (exponential backoff). Raises on other errors."""
    for attempt in range(MAX_RETRIES_ON_429 + 1):
        r = httpx.get(url, params=params, timeout=30)
        if r.status_code != 429:
            r.raise_for_status()
            return r
        wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
        print(f"  429 rate limited; sleeping {wait:.1f}s (attempt {attempt + 1}/{MAX_RETRIES_ON_429})", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"Exhausted retries on 429 for {url}")


def fetch_all_markets(endpoint: str, series_ticker: str, status: str | None = None) -> list[dict]:
    """Paginate through a markets endpoint, returning all results. Rate-limited."""
    all_markets = []
    cursor = None
    page = 0
    while True:
        params = {"series_ticker": series_ticker, "limit": 200}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        r = get_with_retry(f"{BASE_URL}/{endpoint}", params=params)
        data = r.json()
        page_markets = data.get("markets", [])
        all_markets.extend(page_markets)
        page += 1
        cursor = data.get("cursor", "")
        if not cursor or not page_markets:
            break
        if page % 10 == 0:
            print(f"  [{endpoint}] page {page}: {len(all_markets)} markets so far...", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_markets


def parse_market(m: dict, station_id: str = "KNYC") -> tuple | None:
    """Parse a market dict into a contracts row tuple. Returns None on bad data."""
    strike_type = m.get("strike_type")
    bracket_type = BRACKET_TYPE_MAP.get(strike_type)
    if not bracket_type:
        return None

    if strike_type == "greater":
        strike_low, strike_high = float(m["floor_strike"]), None
    elif strike_type == "less":
        strike_low, strike_high = None, float(m["cap_strike"])
    elif strike_type == "between":
        strike_low, strike_high = float(m["floor_strike"]), float(m["cap_strike"])
    else:
        return None

    try:
        target_date = event_ticker_to_date(m["event_ticker"])
    except Exception:
        return None

    def parse_dt(s: str | None):
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    return (
        m["ticker"],
        m["ticker"].split("-")[0],
        station_id,
        target_date,
        strike_low,
        strike_high,
        bracket_type,
        parse_dt(m.get("expiration_time")),
        parse_dt(m.get("close_time")),
        Jsonb(m),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series", default="KXHIGHNY")
    parser.add_argument("--start-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), required=True,
                        help="YYYY-MM-DD (inclusive, target_date)")
    parser.add_argument("--end-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), required=True,
                        help="YYYY-MM-DD (inclusive, target_date)")
    args = parser.parse_args()

    # Look up the station_id that corresponds to this series (from the registry).
    # Falls back to KNYC if the series isn't in the registry yet. Checks both
    # the daily-HIGH and daily-LOW series for each station.
    from weather_markets.stations import all_stations
    series_to_station = {}
    for s in all_stations():
        series_to_station[s.kalshi_series] = s.station_id
        if hasattr(s, "kalshi_series_low"):
            series_to_station[s.kalshi_series_low] = s.station_id
    station_id_for_series = series_to_station.get(args.series, "KNYC")

    print(f"Discovering {args.series} contracts with target_date in [{args.start_date}, {args.end_date}]")
    print(f"  (will insert with station_id={station_id_for_series})")

    # 1. Live endpoint (status=settled) for post-cutoff markets
    print("\n--- /markets?status=settled (live partition) ---", flush=True)
    live_settled = fetch_all_markets("markets", args.series, status="settled")
    print(f"  total settled live markets: {len(live_settled)}")

    # 2. Historical endpoint for pre-cutoff markets
    print("\n--- /historical/markets ---", flush=True)
    historical = fetch_all_markets("historical/markets", args.series)
    print(f"  total historical markets: {len(historical)}")

    # 3. Dedupe by ticker, filter to date range, parse
    seen: set[str] = set()
    rows: list[tuple] = []
    skipped_bad = 0
    out_of_range = 0
    for m in live_settled + historical:
        ticker = m.get("ticker")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        try:
            target = event_ticker_to_date(m["event_ticker"])
        except Exception:
            skipped_bad += 1
            continue
        if not (args.start_date <= target <= args.end_date):
            out_of_range += 1
            continue
        parsed = parse_market(m, station_id=station_id_for_series)
        if parsed:
            rows.append(parsed)
        else:
            skipped_bad += 1

    print(f"\nAfter dedupe + date filter:")
    print(f"  in range:     {len(rows)} contracts")
    print(f"  out of range: {out_of_range}")
    print(f"  bad/skipped:  {skipped_bad}")

    if not rows:
        print("\nNothing to insert. Exiting.")
        return

    # 4. Insert
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows)
    print(f"\nInserted (ON CONFLICT DO NOTHING): {len(rows)} rows attempted")


if __name__ == "__main__":
    main()
