"""Phase 2 smoke test: verify Kalshi API auth and read-only endpoints work.

Run: uv run python scripts/check_kalshi_api.py

Defaults to the demo environment (KALSHI_API_BASE in .env). NO orders placed.

Exits 0 on success, 1 on auth failure, 2 on network/parse error so this can
be wired into a healthcheck cron later.
"""
import sys
from datetime import datetime, timezone

from weather_markets.kalshi_api import KalshiClient, KalshiAuthError, parse_position, parse_count


def main() -> int:
    print("=" * 60)
    print("KALSHI API SMOKE TEST")
    print("=" * 60)

    try:
        client = KalshiClient()
    except KalshiAuthError as e:
        print(f"FAIL (config): {e}", file=sys.stderr)
        return 1

    print(f"  api_base:  {client.api_base}")
    print(f"  key_id:    {client.key_id[:8]}...{client.key_id[-4:]}")
    print(f"  key_path:  {client.key_path}")
    print()

    is_demo = "demo" in client.api_base
    if not is_demo:
        print("!! NOT POINTING AT DEMO ENVIRONMENT — real-money account in use.")
        print()

    # 1. Balance
    print("[1/4] GET /portfolio/balance")
    try:
        bal = client.get_balance()
    except KalshiAuthError as e:
        print(f"  AUTH FAIL: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"  ERROR ({type(e).__name__}): {e}", file=sys.stderr)
        return 2
    cents = bal.get("balance")
    if cents is None:
        print(f"  unexpected payload: {bal}")
    else:
        print(f"  balance: ${cents/100:,.2f}")

    # 2. Positions
    print("\n[2/4] GET /portfolio/positions")
    try:
        positions = client.get_positions()
        market_positions = positions.get("market_positions", [])
        event_positions = positions.get("event_positions", [])
        print(f"  open market positions: {len(market_positions)}")
        print(f"  open event positions:  {len(event_positions)}")
        for p in market_positions[:5]:
            qty = parse_position(p)
            tk = p.get("ticker", "?")
            side = "YES" if qty > 0 else ("NO" if qty < 0 else "flat")
            print(f"    {tk}: position={qty} ({side})")
    except Exception as e:
        print(f"  ERROR ({type(e).__name__}): {e}", file=sys.stderr)
        return 2

    # 3. Open orders
    print("\n[3/4] GET /portfolio/orders?status=resting")
    try:
        orders = client.get_orders(status="resting", limit=20)
        order_list = orders.get("orders", [])
        print(f"  resting orders: {len(order_list)}")
        for o in order_list[:5]:
            remaining = parse_count(o, "remaining_count_fp")
            price = o.get('yes_price_dollars') or o.get('no_price_dollars')
            print(f"    {o.get('ticker')}: side={o.get('side')} remaining={remaining} @ {price}")
    except Exception as e:
        print(f"  ERROR ({type(e).__name__}): {e}", file=sys.stderr)
        return 2

    # 4. Recent fills (last 7 days)
    print("\n[4/4] GET /portfolio/fills (last 7 days)")
    try:
        import time
        min_ts = int(time.time()) - 7 * 86400
        fills = client.get_fills(min_ts=min_ts, limit=20)
        fill_list = fills.get("fills", [])
        print(f"  fills in last 7 days: {len(fill_list)}")
        for f in fill_list[:5]:
            ts = f.get("created_time", "?")
            count = parse_count(f, "count_fp")
            price = f.get('yes_price_dollars') or f.get('no_price_dollars')
            print(f"    {ts}  {f.get('ticker')}: {f.get('side')} {count} @ {price}")
    except Exception as e:
        print(f"  ERROR ({type(e).__name__}): {e}", file=sys.stderr)
        return 2

    print("\n" + "=" * 60)
    print("ALL CHECKS PASSED  ✓")
    print("=" * 60)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
