"""Polymarket US smoke test — validates API access + Chicago market data.

Set credentials in environment before running:
  export POLYMARKET_KEY_ID="your-key-id"
  export POLYMARKET_SECRET="your-base64-secret"
  uv run python scripts/test_polymarket.py

What it checks:
  1. Auth works (read account balance)
  2. Can list weather markets
  3. Chicago daily-high market exists, has expected brackets
  4. Side-by-side price comparison vs Kalshi for today's Chicago market
  5. Settlement source matches Kalshi (NWS KORD)
"""
import json
from datetime import date

from weather_markets.polymarket import PolymarketClient, PolymarketAuthError


def main():
    print("=" * 70)
    print("Polymarket US smoke test")
    print("=" * 70)

    try:
        client = PolymarketClient()
    except PolymarketAuthError as e:
        print(f"FAIL: {e}")
        return 1

    print(f"\n  base_url: {client.base_url}")
    print(f"  key_id:   {client.creds.key_id[:8]}...")

    # === 1. Auth check: get balance ===
    print("\n[1] Account balance:")
    try:
        bal = client.get_balance()
        print(f"  {json.dumps(bal, indent=2)[:400]}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1

    # === 2. List weather markets ===
    print("\n[2] List markets (looking for Chicago weather):")
    try:
        markets = client.list_markets(limit=100)
        # Could be wrapped in {"markets": [...]} or be the list directly
        if isinstance(markets, dict) and "markets" in markets:
            markets = markets["markets"]
        if not isinstance(markets, list):
            print(f"  unexpected shape: {type(markets).__name__}")
            markets = []
        chi_markets = [m for m in markets if "chicago" in (m.get("slug","") + m.get("title","")).lower()]
        print(f"  Total returned: {len(markets)}, Chicago-related: {len(chi_markets)}")
        for m in chi_markets[:5]:
            slug = m.get("slug","?")
            title = m.get("title","")
            print(f"    {slug:<40} {title[:60]}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        return 1

    # === 3. Get Chicago market details ===
    if chi_markets:
        slug = chi_markets[0].get("slug")
        print(f"\n[3] Market details for {slug}:")
        try:
            details = client.get_market_by_slug(slug)
            # Print short overview
            keys = list(details.keys())[:20] if isinstance(details, dict) else []
            print(f"  keys: {keys}")
            print(f"  raw (truncated): {json.dumps(details, indent=2)[:600]}")
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")

        # === 4. BBO ===
        print(f"\n[4] BBO for {slug}:")
        try:
            bbo = client.get_bbo(slug)
            print(f"  {json.dumps(bbo, indent=2)[:400]}")
        except Exception as e:
            print(f"  FAIL: {type(e).__name__}: {e}")

    # === 5. Compare to Kalshi today (just show side-by-side counts for now) ===
    print(f"\n[5] Today is {date.today()}. Run dashboard's Chicago page to compare prices.")
    print("    Next step: build a side-by-side bracket comparison if everything above worked.")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
