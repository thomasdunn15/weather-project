import httpx
from datetime import datetime, timezone, date
from psycopg.types.json import Jsonb
from weather_markets.db import get_connection

BRACKET_TYPE_MAP = {
    'greater': 'greater_than',
    'less': 'less_than',
    'between': 'between',
}

_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def ticker_event_date(ticker: str) -> date:
    """Event (target) date from a Kalshi daily-high ticker, e.g.
    'KXHIGHTPHX-26JUN15-B106.5' -> date(2026, 6, 15).

    The ticker date is authoritative — it matches Kalshi's contract title
    ("...on Jun 15"). Do NOT use occurrence_datetime.date(): for the newer
    "T"-prefixed western/central series (KXHIGHTPHX/TLV/TSEA/TDAL/TNOLA),
    Kalshi sets occurrence_datetime to the settle day (event+1 in UTC), which
    silently shifted target_date one day late (2026-06-18 bug)."""
    seg = ticker.split("-")[1]            # "26JUN15"
    return date(2000 + int(seg[0:2]), _MONTHS[seg[2:5]], int(seg[5:7]))

def dollars_to_cents(dollar_str: str) -> int:
    """Convert Kalshi's dollar string format (e.g., '0.0500') to cents (5)."""
    return int(round(float(dollar_str) * 100))

def fetch_markets(series_ticker: str, status: str = "open", limit: int = 200) -> list[dict]:
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    base_params = {
        "series_ticker": series_ticker,
        "status": status,
        "limit": 200,  # max per page
    }
    
    all_markets = []
    cursor = None
    
    while True:
        params = dict(base_params)
        if cursor:
            params["cursor"] = cursor
        
        response = httpx.get(url, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        
        all_markets.extend(data.get("markets", []))
        
        cursor = data.get("cursor", "")
        if not cursor:
            break
    
    return all_markets

def parse_contracts(raw_markets: list[dict], station_id: str = "KNYC") -> list[tuple]:

    rows = []
    
    for m in raw_markets:
        # Map strike_type to bracket_type
        strike_type = m['strike_type']
        bracket_type = BRACKET_TYPE_MAP[strike_type]
        
        # Map strikes based on type
        if strike_type == 'greater':
            strike_low = float(m['floor_strike'])
            strike_high = None
        elif strike_type == 'less':
            strike_low = None
            strike_high = float(m['cap_strike'])
        elif strike_type == 'between':
            strike_low = float(m['floor_strike'])
            strike_high = float(m['cap_strike'])
        else:
            raise ValueError(f"Unknown strike_type: {strike_type!r}")
        
        # Build the tuple
        rows.append((
            m['ticker'],
            m['ticker'].split('-')[0],   # series
            station_id,
            ticker_event_date(m['ticker']),   # authoritative; NOT occurrence_datetime.date()
            strike_low,
            strike_high,
            bracket_type,
            datetime.fromisoformat(m['expiration_time']),
            datetime.fromisoformat(m['close_time']),
            Jsonb(m),
        ))
    
    return rows

def insert_contracts(rows: list[tuple], conn) -> int:
    if not rows:
        return 0
    
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO contracts (
                ticker, series, station_id, target_date,
                strike_low, strike_high, bracket_type,
                expiration_time, last_trading_time, raw_metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker) DO NOTHING
            """,
            rows,
        )
    
    return len(rows)

def discover_kalshi_contracts(series_ticker: str = "KXHIGHNY", station_id: str = "KNYC") -> dict:
    with get_connection() as conn:
        markets = fetch_markets(series_ticker=series_ticker, status="open")
        rows = parse_contracts(markets, station_id=station_id)
        count = insert_contracts(rows, conn)
    
    return {
        "series_ticker": series_ticker,
        "station_id": station_id,
        "markets_fetched": len(markets),
        "rows_attempted": count,
    }

def parse_prices(raw_markets: list[dict], snapshot_at: datetime) -> list[tuple]:
    rows = []
    
    for m in raw_markets:
        rows.append((
            snapshot_at,
            m['ticker'],
            dollars_to_cents(m['yes_bid_dollars']),
            dollars_to_cents(m['yes_ask_dollars']),
            dollars_to_cents(m['no_bid_dollars']),
            dollars_to_cents(m['no_ask_dollars']),
            dollars_to_cents(m['last_price_dollars']),
            int(round(float(m['volume_fp']))),
            int(round(float(m['volume_24h_fp']))),
            int(round(float(m['open_interest_fp']))),
        ))
    
    return rows

def insert_prices(rows: list[tuple], conn) -> int:

    if not rows:
        return 0
    
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO prices (
                snapshot_at, ticker, yes_bid, yes_ask, no_bid, no_ask,
                last_price, volume, volume_24h, open_interest
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (snapshot_at, ticker) DO NOTHING
            """,
            rows,
        )
    
    return len(rows)

def snapshot_kalshi_prices(series_ticker: str = "KXHIGHNY") -> dict:

    snapshot_at = datetime.now(timezone.utc)
    
    with get_connection() as conn:
        markets = fetch_markets(series_ticker=series_ticker, status="open")
        rows = parse_prices(markets, snapshot_at)
        count = insert_prices(rows, conn)
    
    return {
        "series_ticker": series_ticker,
        "snapshot_at": snapshot_at,
        "rows_attempted": count,
    }