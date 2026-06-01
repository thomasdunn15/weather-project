"""Phase 3 acceptance test: place ONE limit order end-to-end, then cancel.

Defaults to DRY-RUN. Pass --confirm to actually place a real order.

Hard-coded safety constraints — by design, you cannot use this script to do
anything that would lose more than ~$1:

  - count is fixed at 1 contract (no flag to override)
  - post_only=True (Kalshi rejects if it would cross — won't accidentally
    market-buy)
  - default price is set to 1¢ (so even if it filled, max loss is 1¢ + fee).
    Pass --aggressive to use a price 1¢ inside the current spread instead
    (more likely to fill quickly, max loss is the contract price + fee)
  - script cancels the order at the end regardless of fill status

Usage:
    # Pure dry run — prints what would happen, no API call
    uv run python scripts/test_place_order.py --ticker KXHIGHNY-26JUN01-B72.5

    # Place a real order at 1¢ (almost certainly won't fill)
    uv run python scripts/test_place_order.py --ticker KXHIGHNY-26JUN01-B72.5 --confirm

    # Place at limit-1¢-inside-spread (more likely to fill, slightly riskier)
    uv run python scripts/test_place_order.py --ticker KXHIGHNY-26JUN01-B72.5 --confirm --aggressive
"""
import argparse
import sys
import time
from uuid import uuid4

from weather_markets.kalshi_api import KalshiClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", required=True, help="KXHIGHNY ticker, e.g. KXHIGHNY-26JUN01-B72.5")
    parser.add_argument("--side", default="yes", choices=["yes", "no"], help="yes (default) or no")
    parser.add_argument("--confirm", action="store_true",
                        help="Actually place the order. Without this, the script is a dry-run.")
    parser.add_argument("--aggressive", action="store_true",
                        help="Use price 1¢ inside the current spread instead of 1¢. More likely to fill.")
    parser.add_argument("--keep-open", action="store_true",
                        help="Don't auto-cancel at end of script. Default is auto-cancel for safety.")
    args = parser.parse_args()

    print("=" * 60)
    print("PHASE 3 ORDER-PLACEMENT TEST")
    print("=" * 60)

    client = KalshiClient()
    print(f"  api_base: {client.api_base}")
    is_live = "demo" not in client.api_base
    print(f"  env:      {'LIVE / real money' if is_live else 'demo'}")

    # Determine price
    if args.aggressive:
        print(f"\nFetching current book for {args.ticker}...")
        # We don't have a get_orderbook method, so use the public markets endpoint
        # to pull bid/ask. This is read-only and unauthenticated.
        import httpx
        r = httpx.get(
            f"{client.api_base}/markets/{args.ticker}",
            headers={"Accept": "application/json"},
            timeout=15,
        )
        r.raise_for_status()
        m = r.json().get("market", {})
        if args.side == "yes":
            bid = m.get("yes_bid"); ask = m.get("yes_ask")
            if not bid or not ask or ask <= bid + 1:
                print(f"  Spread too narrow or empty (bid={bid}, ask={ask}); using 1¢ instead")
                price = 1
            else:
                price = ask - 1
        else:
            bid = m.get("no_bid"); ask = m.get("no_ask")
            if not bid or not ask or ask <= bid + 1:
                print(f"  Spread too narrow or empty (bid={bid}, ask={ask}); using 1¢ instead")
                price = 1
            else:
                price = ask - 1
        print(f"  current {args.side} bid={bid}, ask={ask} → using limit price {price}¢")
    else:
        price = 1
        print(f"\n  Using safe minimum price: 1¢")

    print(f"\nIntended order:")
    print(f"  ticker:        {args.ticker}")
    print(f"  side:          {args.side}")
    print(f"  count:         1")
    print(f"  price:         {price}¢")
    print(f"  post_only:     True (won't cross spread)")
    print(f"  max loss:      ~${(price + 1) / 100:.2f}  (price + fee, if filled and resolves wrong)")

    if not args.confirm:
        print("\n" + "=" * 60)
        print("DRY-RUN — no API call made. Re-run with --confirm to place.")
        print("=" * 60)
        return 0

    print("\n" + "=" * 60)
    print(f"Placing order in 3 seconds... (Ctrl-C to abort)")
    print("=" * 60)
    time.sleep(3)

    client_order_id = str(uuid4())
    print(f"\nPlacing order (client_order_id={client_order_id})...")
    try:
        resp = client.place_limit_order(
            ticker=args.ticker,
            side=args.side,
            count=1,
            price_cents=price,
            post_only=True,
            client_order_id=client_order_id,
        )
    except Exception as e:
        print(f"  FAIL ({type(e).__name__}): {e}", file=sys.stderr)
        return 2

    order = resp.get("order", resp)
    order_id = order.get("order_id")
    if not order_id:
        print(f"  ERROR: no order_id in response: {resp}", file=sys.stderr)
        return 2
    print(f"  order_id: {order_id}")
    print(f"  status:   {order.get('status')}")
    print(f"  resp:     {resp}")

    # Verify via get_order
    print(f"\nReading back via GET /portfolio/orders/{order_id}...")
    try:
        check = client.get_order(order_id)
        print(f"  status:   {check.get('order', check).get('status')}")
    except Exception as e:
        print(f"  ERROR reading order back: {e}", file=sys.stderr)

    # Cancel
    if args.keep_open:
        print(f"\n--keep-open set, leaving order in market. Cancel manually if needed.")
    else:
        print(f"\nCancelling...")
        try:
            cancel_resp = client.cancel_order(order_id)
            print(f"  cancel resp: {cancel_resp}")
        except Exception as e:
            print(f"  WARN cancel failed: {e}", file=sys.stderr)
            print(f"  IMPORTANT: order {order_id} may still be live. Cancel manually in Kalshi UI.")
            return 2

    print("\n" + "=" * 60)
    print("PHASE 3 TEST COMPLETE  ✓")
    print("=" * 60)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
