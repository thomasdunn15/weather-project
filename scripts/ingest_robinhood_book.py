"""Ingest the ForecastEx TOP-OF-BOOK that Robinhood publishes on its event pages.

THIS CONTRADICTS AN ASSUMPTION THE REST OF THE REPO IS BUILT ON. Every comment
about ForecastEx says "publishes no public order book, so yes_bid/yes_ask stay
NULL — depth would require the IBKR API" (see ingest_forecastex.py, the
ForecastEx tab, the backtest's "no fill model" caveat). That was true of
forecastex.com's download endpoint. It is not true of Robinhood, which renders
each climate event server-side with a `quotes` object embedded in the HTML,
keyed by the SAME ForecastEx contract id we already use as our ticker:

    "symbol": "UHMIA_090226_89",
    "yes_bid_price": "0.51", "yes_ask_price": "0.59",
    "bid_size": 500, "ask_size": ..., "last_trade_price": "0.45", ...

WHY IT MATTERS MORE THAN THE MISSING NUMBER: on 2026-09-02 UHMIA_090226_89 had
a last trade of 45c against a 51/59 book. Our edge is computed off last_price,
so the tab claimed an edge at 45c on a contract that could not be bought below
59c. The strategy's own docs already flag this ("spread is NOT charged; the
backtest enters at last_price") — this is the first time we can MEASURE it
rather than assume a fixed median spread.

Rows land in `prices` with last_price NULL and snapshot_at = the poll time, so
they cannot be mistaken for tape: every existing reader filters on
`last_price IS NOT NULL` and is unaffected. Quotes are a snapshot of a moment,
trades are events — mixing their timestamps would corrupt both.

  uv run python scripts/ingest_robinhood_book.py            # today, configured cities
  uv run python scripts/ingest_robinhood_book.py --city KLAX --dry-run
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from weather_markets.forecastex import RH_CITY_SLUG, rh_url
from weather_markets.db import get_connection

# Only the cities we actually trade. Each page is ~450 KB, so this is not free
# and there is no reason to pull a book for a city with no signal path.
CITIES = ("KMIA", "KLAX")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

BOOK_SQL = """
    INSERT INTO prices (snapshot_at, ticker, yes_bid, yes_ask, no_bid, no_ask)
    VALUES (%s,%s,%s,%s,%s,%s)
    ON CONFLICT (snapshot_at, ticker) DO NOTHING
"""


def _cents(v) -> int | None:
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def _balanced(text: str, start: int) -> str:
    """The brace-balanced object beginning at the first '{' at/after `start`."""
    j = text.index("{", start)
    depth = 0
    for k in range(j, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[j:k + 1]
    raise ValueError("unbalanced quotes object")


def fetch_quotes(station: str, day) -> dict:
    """symbol -> quote dict, parsed out of the server-rendered page."""
    url = rh_url(station, day)
    if url is None:
        raise ValueError(f"no Robinhood slug for {station}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=30).read()
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass
    text = raw.decode("utf-8", "replace")
    if '"quotes":' not in text:
        raise ValueError(f"no quotes block on {url} (page shape changed?)")
    obj = json.loads(_balanced(text, text.index('"quotes":'))
                     .encode().decode("unicode_escape"))
    return {q["symbol"]: q for q in obj.values() if q.get("symbol")}


def ingest_city(conn, station: str, day, dry_run: bool = False) -> tuple[int, int]:
    """Returns (quotes_seen, rows_written)."""
    quotes = fetch_quotes(station, day)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        # Only write books for contracts we already track, so a page-shape
        # change cannot invent tickers in `contracts`.
        cur.execute("""SELECT ticker FROM contracts
                       WHERE platform='forecastex' AND station_id=%s AND target_date=%s""",
                    (station, day))
        known = {r[0] for r in cur.fetchall()}
    rows = []
    for sym, q in quotes.items():
        if sym not in known:
            continue
        yb, ya = _cents(q.get("yes_bid_price")), _cents(q.get("yes_ask_price"))
        nb, na = _cents(q.get("no_bid_price")), _cents(q.get("no_ask_price"))
        # ForecastEx quotes only one side of each pair; the other leg is its
        # complement. Deriving it here keeps the NO reader from seeing NULLs.
        if nb is None and ya is not None:
            nb = 100 - ya
        if na is None and yb is not None:
            na = 100 - yb
        if yb is None and ya is None:
            continue
        rows.append((now, sym, yb, ya, nb, na))
    if dry_run:
        for r in sorted(rows, key=lambda r: r[1]):
            print(f"  {r[1]:18} yes {str(r[2]):>4}/{str(r[3]):<4}  no {str(r[4]):>4}/{str(r[5]):<4}")
        return len(quotes), 0
    if rows:
        with conn.cursor() as cur:
            cur.executemany(BOOK_SQL, rows)
        conn.commit()
    return len(quotes), len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", action="append", choices=sorted(RH_CITY_SLUG))
    ap.add_argument("--date", type=lambda s: datetime.fromisoformat(s).date())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    day = a.date or datetime.now(timezone.utc).date()
    conn = get_connection()
    seen = wrote = failed = 0
    try:
        for station in (a.city or CITIES):
            try:
                s, w = ingest_city(conn, station, day, a.dry_run)
                seen += s
                wrote += w
                print(f"{station}: {s} quotes, {w} rows")
            except Exception as e:                  # one bad page must not stop the rest
                failed += 1
                print(f"{station}: FAILED {type(e).__name__}: {e}")
    finally:
        conn.close()
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
          f"robinhood book: {seen} quotes, {wrote} rows, {failed} failed")
    return 1 if failed and not wrote else 0


if __name__ == "__main__":
    raise SystemExit(main())
