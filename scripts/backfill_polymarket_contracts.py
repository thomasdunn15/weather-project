"""Backfill Polymarket US weather contracts into the contracts table.

Polymarket US slug format: tc-temp-{city}high-{YYYY-MM-DD}-{spec}f
  spec patterns:
    lt80f          → less_than 80
    gte80lt81f     → between 80 and 81
    gte88f         → greater_than 88

City code → station_id mapping:
    mdwhigh → KMDW (Chicago Midway)
    nychigh → KNYC (New York Central Park)
    miahigh → KMIA (Miami)
    laxhigh → KLAX (Los Angeles)
    sfohigh → KSFO (San Francisco)

Stores with platform='polymarket' to keep separate from Kalshi rows.
"""
import argparse
import re
from datetime import datetime

from weather_markets.db import get_connection
from weather_markets.polymarket import PolymarketClient


CITY_CODE_TO_STATION = {
    "mdwhigh": "KMDW",
    "nychigh": "KNYC",
    "miahigh": "KMIA",
    "laxhigh": "KLAX",
    "sfohigh": "KSFO",
}
# Slug regex: tc-temp-{city}-{date}-{spec}f
SLUG_RE = re.compile(
    r"^tc-temp-(?P<city>[a-z]+)-(?P<date>\d{4}-\d{2}-\d{2})-(?P<spec>[a-z0-9]+)f$"
)
SPEC_LT = re.compile(r"^lt(\d+)$")
SPEC_GTE_LT = re.compile(r"^gte(\d+)lt(\d+)$")
SPEC_GTE = re.compile(r"^gte(\d+)$")


def parse_slug(slug: str) -> dict | None:
    m = SLUG_RE.match(slug)
    if not m:
        return None
    city_code = m.group("city")
    station_id = CITY_CODE_TO_STATION.get(city_code)
    if not station_id:
        return None
    date_str = m.group("date")
    spec = m.group("spec")
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    if (m2 := SPEC_LT.match(spec)):
        bracket_type = "less_than"
        strike_low = None
        strike_high = float(m2.group(1))
    elif (m2 := SPEC_GTE_LT.match(spec)):
        bracket_type = "between"
        strike_low = float(m2.group(1))
        strike_high = float(m2.group(2))
    elif (m2 := SPEC_GTE.match(spec)):
        bracket_type = "greater_than"
        strike_low = float(m2.group(1))
        strike_high = None
    else:
        return None

    return {
        "station_id": station_id,
        "target_date": target_date,
        "bracket_type": bracket_type,
        "strike_low": strike_low,
        "strike_high": strike_high,
        "series": f"tc-temp-{city_code}",
    }


INSERT_SQL = """
INSERT INTO contracts (
    ticker, series, station_id, target_date,
    strike_low, strike_high, bracket_type,
    expiration_time, last_trading_time, platform, raw_metadata
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'polymarket', %s::jsonb)
ON CONFLICT (ticker) DO UPDATE SET
    expiration_time = EXCLUDED.expiration_time,
    last_trading_time = EXCLUDED.last_trading_time,
    raw_metadata = EXCLUDED.raw_metadata
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--include-closed", action="store_true",
                        help="Also fetch closed/settled markets (default: active only)")
    args = parser.parse_args()

    client = PolymarketClient(base_url="https://gateway.polymarket.us")

    # Paginate through ALL climate markets (active + optionally closed)
    all_markets = []
    for active_flag in (["true"] if not args.include_closed else ["true", "false"]):
        offset = 0
        while True:
            params = {"limit": 100, "offset": offset, "categories": "climate", "active": active_flag}
            r = client._request("GET", "/v1/markets", params=params)
            items = r.get("markets", []) if isinstance(r, dict) else []
            if not items:
                break
            all_markets.extend(items)
            if len(items) < 100:
                break
            offset += 100
            if offset > 50000:
                print(f"  safety cap hit at offset={offset}"); break
    print(f"Total climate markets fetched: {len(all_markets)}")

    # Parse + insert
    import json
    n_inserted = 0
    n_skipped = 0
    by_station = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            for m in all_markets:
                slug = m.get("slug","")
                parsed = parse_slug(slug)
                if not parsed:
                    n_skipped += 1
                    continue
                # endDate / startDate
                end_dt = m.get("endDate")
                cur.execute(
                    INSERT_SQL,
                    (
                        slug, parsed["series"], parsed["station_id"], parsed["target_date"],
                        parsed["strike_low"], parsed["strike_high"], parsed["bracket_type"],
                        end_dt, end_dt,
                        json.dumps(m),
                    ),
                )
                n_inserted += 1
                by_station[parsed["station_id"]] = by_station.get(parsed["station_id"], 0) + 1
    print(f"Inserted/upserted: {n_inserted}, skipped (parse fail): {n_skipped}")
    print(f"Per station: {by_station}")


if __name__ == "__main__":
    main()
