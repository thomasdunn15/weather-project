"""Phase 5: fill monitoring + cancellation cron. Fires at 20:00 UTC (end-of-day).

For every live_trades row with fill_status='pending' from today:
  - Query Kalshi for the order's current state
  - If executed/filled: update fill_price_cents, fill_count, fill_time, fill_status='filled'
  - If partially filled: same with fill_status='partial'
  - If still resting at EOD: cancel via Kalshi API, mark fill_status='cancelled'
  - If rejected by Kalshi: mark fill_status='rejected'

Policy: pure limit-only for Phase 5. No escalation to cross-spread. We collect
real fill-rate data before deciding whether escalation helps.

Run multiple times during the trading window is safe — only updates rows
that need updating. Suggested cron times: 15:30, 16:30, 17:30, 20:00 UTC.

Exit codes:
  0 — clean run
  1 — Kalshi auth / config error
  2 — partial run (some rows couldn't be updated)
"""
import argparse
import sys
from datetime import datetime, timezone

from weather_markets.db import get_connection
from weather_markets.kalshi_api import KalshiClient, KalshiAuthError, parse_count, parse_dollars_to_cents


# Kalshi status → our fill_status
KALSHI_STATUS_MAP = {
    "resting": "pending",       # still open
    "executed": "filled",       # fully filled
    "canceled": "cancelled",    # cancelled (Kalshi uses US spelling)
}


def update_one_pending(conn, client: KalshiClient, row, cancel_unfilled: bool) -> str:
    """Update one pending row. Returns 'filled', 'cancelled', 'still_pending', or 'error:<msg>'."""
    id_, kalshi_order_id, ticker, original_count = row

    if not kalshi_order_id:
        # Order placement may have failed before we got an order_id. Mark rejected.
        with conn.cursor() as cur:
            cur.execute("UPDATE live_trades SET fill_status='rejected' WHERE id=%s", (id_,))
        return "rejected (no kalshi_order_id)"

    try:
        resp = client.get_order(kalshi_order_id, ticker=ticker)
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    order = resp.get("order", resp)
    kstatus = order.get("status", "").lower()

    # Determine our mapped status + extract fill info
    # Kalshi orders endpoint returns _fp counts and _dollars prices.
    fill_price_cents = parse_dollars_to_cents(order, "yes_price_dollars") or \
                       parse_dollars_to_cents(order, "no_price_dollars")
    initial = parse_count(order, "initial_count_fp")
    remaining = parse_count(order, "remaining_count_fp")
    filled_qty = max(0, initial - remaining)

    if kstatus == "executed":
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE live_trades
                SET fill_status = 'filled',
                    fill_price_cents = %s,
                    fill_count = %s,
                    fill_time = NOW()
                WHERE id = %s
            """, (fill_price_cents or None, filled_qty, id_))
        return f"filled ({filled_qty} @ {fill_price_cents}¢)"

    if kstatus == "canceled":
        if filled_qty > 0:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE live_trades
                    SET fill_status = 'partial',
                        fill_price_cents = %s,
                        fill_count = %s,
                        fill_time = NOW()
                    WHERE id = %s
                """, (fill_price_cents or None, filled_qty, id_))
            return f"partial ({filled_qty} @ {fill_price_cents}¢)"
        else:
            with conn.cursor() as cur:
                cur.execute("UPDATE live_trades SET fill_status='cancelled' WHERE id=%s", (id_,))
            return "cancelled (0 fills)"

    if kstatus == "resting":
        if cancel_unfilled:
            try:
                client.cancel_order(kalshi_order_id)
                with conn.cursor() as cur:
                    cur.execute("UPDATE live_trades SET fill_status='cancelled' WHERE id=%s", (id_,))
                return "cancelled by us (EOD)"
            except Exception as e:
                return f"error cancelling: {type(e).__name__}: {e}"
        else:
            return "still_pending"

    return f"unknown kalshi status: {kstatus}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cancel-unfilled", action="store_true",
                        help="If an order is still resting, cancel it. Use for EOD run only.")
    args = parser.parse_args()

    try:
        client = KalshiClient()
    except KalshiAuthError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).date()
    print(f"=== monitor_fills ({datetime.now(timezone.utc).isoformat()}, today={today}) ===")
    print(f"  cancel_unfilled: {args.cancel_unfilled}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, kalshi_order_id, ticker, count
                FROM live_trades
                WHERE fill_status = 'pending' AND target_date = %s
                ORDER BY placed_at
            """, (today,))
            rows = cur.fetchall()

        print(f"  pending rows for today: {len(rows)}")

        had_error = False
        for row in rows:
            result = update_one_pending(conn, client, row, args.cancel_unfilled)
            print(f"  {row[2]} (id={row[0]}, order_id={row[1]}): {result}")
            if result.startswith("error"):
                had_error = True

    client.close()
    return 2 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
