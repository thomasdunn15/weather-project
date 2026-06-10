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


def fetch_vwap_and_fees(client: KalshiClient, ticker: str, kalshi_order_id: str, side: str) -> tuple[int | None, int | None, int]:
    """Pull fills for this order, compute VWAP in YES-equivalent cents + total fees in cents.

    Returns (vwap_yes_cents, total_fees_cents, filled_count). All None/0 if no fills found.

    Why: the order endpoint returns the LIMIT price, not the actual avg fill price.
    Kalshi often fills at better prices than our limit (especially with partial
    crosses through the book). Storing the limit price systematically overstates
    cost on profitable fills.
    """
    try:
        fills_resp = client.get_fills(ticker=ticker, limit=200)
    except Exception:
        return None, None, 0
    all_fills = fills_resp.get("fills", [])
    # Filter to fills for this specific order
    my_fills = [f for f in all_fills if f.get("order_id") == kalshi_order_id and f.get("side") == side]
    if not my_fills:
        return None, None, 0
    total_count = 0.0
    total_cost = 0.0
    total_fees = 0.0
    for f in my_fills:
        cnt = float(f.get("count_fp", 0))
        price_key = "yes_price_dollars" if side == "yes" else "no_price_dollars"
        price = float(f.get(price_key, 0))
        total_count += cnt
        total_cost += cnt * price
        total_fees += float(f.get("fee_cost", 0))
    if total_count < 1:
        return None, None, 0
    vwap = (total_cost / total_count) * 100  # cents on the side we bought
    # Convert NO-side VWAP to YES-equivalent for consistency in storage
    vwap_yes_cents = int(round(vwap if side == "yes" else 100 - vwap))
    return vwap_yes_cents, int(round(total_fees * 100)), int(total_count)


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

    # Look up our side from the live_trades row so we can VWAP correctly.
    with conn.cursor() as cur:
        cur.execute("SELECT side FROM live_trades WHERE id=%s", (id_,))
        side = cur.fetchone()[0]

    # Get VWAP from actual fills (limit price would overstate cost when filled
    # at better than limit, distorting downstream P&L reconciliation).
    vwap_yes_cents, fees_cents, filled_qty = fetch_vwap_and_fees(client, ticker, kalshi_order_id, side)
    # Fall back to order limit price if no fills found (shouldn't happen for executed)
    if vwap_yes_cents is None:
        vwap_yes_cents = parse_dollars_to_cents(order, "yes_price_dollars") or \
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
                    kalshi_fee_cents = %s,
                    fill_time = NOW()
                WHERE id = %s
            """, (vwap_yes_cents or None, filled_qty, fees_cents, id_))
        return f"filled ({filled_qty} @ {vwap_yes_cents}¢ YES-eq, fees ${(fees_cents or 0)/100:.2f})"

    if kstatus == "canceled":
        if filled_qty > 0:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE live_trades
                    SET fill_status = 'partial',
                        fill_price_cents = %s,
                        fill_count = %s,
                        kalshi_fee_cents = %s,
                        fill_time = NOW()
                    WHERE id = %s
                """, (vwap_yes_cents or None, filled_qty, fees_cents, id_))
            return f"partial ({filled_qty} @ {vwap_yes_cents}¢ YES-eq, fees ${(fees_cents or 0)/100:.2f})"
        else:
            with conn.cursor() as cur:
                cur.execute("UPDATE live_trades SET fill_status='cancelled' WHERE id=%s", (id_,))
            return "cancelled (0 fills)"

    if kstatus == "resting":
        # FIX 2026-06-10: resting orders may have PARTIAL fills (we filled some
        # contracts at the limit but the rest is still resting). Record those
        # partial fills so the dashboard shows accurate position size, and so
        # reconcile_live_trades has the right qty when settlement lands.
        if filled_qty > 0:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE live_trades
                    SET fill_status = 'partial_resting',
                        fill_price_cents = %s,
                        fill_count = %s,
                        kalshi_fee_cents = %s,
                        fill_time = COALESCE(fill_time, NOW())
                    WHERE id = %s
                """, (vwap_yes_cents or None, filled_qty, fees_cents, id_))
            partial_msg = f"partial-resting ({filled_qty} filled @ {vwap_yes_cents}¢ YES-eq, {parse_count(order, 'remaining_count_fp')} still resting)"
        else:
            partial_msg = "still_pending"

        if cancel_unfilled:
            try:
                client.cancel_order(kalshi_order_id)
                with conn.cursor() as cur:
                    # If partial fills, update status to 'partial' (final); else 'cancelled'
                    final_status = "partial" if filled_qty > 0 else "cancelled"
                    cur.execute("UPDATE live_trades SET fill_status=%s WHERE id=%s",
                                (final_status, id_))
                return f"cancelled by us (EOD) — {partial_msg}"
            except Exception as e:
                return f"error cancelling: {type(e).__name__}: {e}"
        else:
            return partial_msg

    return f"unknown kalshi status: {kstatus}"


def _run_once(client, cancel_unfilled: bool, verbose: bool = True) -> bool:
    """One pass over open orders. Returns True if all OK, False on any error."""
    today = datetime.now(timezone.utc).date()
    if verbose:
        print(f"\n=== monitor_fills ({datetime.now(timezone.utc).isoformat()}, today={today}) ===")
        print(f"  cancel_unfilled: {cancel_unfilled}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Include partial_resting rows too — they can collect more fills
            # over time. Without re-checking them, dashboard shows stale
            # fill_count even as the resting order keeps filling.
            cur.execute("""
                SELECT id, kalshi_order_id, ticker, count
                FROM live_trades
                WHERE fill_status IN ('pending', 'partial_resting') AND target_date = %s
                ORDER BY placed_at
            """, (today,))
            rows = cur.fetchall()

        if verbose:
            print(f"  pending + partial_resting rows for today: {len(rows)}")

        had_error = False
        for row in rows:
            result = update_one_pending(conn, client, row, cancel_unfilled)
            if verbose:
                print(f"  {row[2]} (id={row[0]}, order_id={row[1]}): {result}")
            if result.startswith("error"):
                had_error = True
    return not had_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cancel-unfilled", action="store_true",
                        help="If an order is still resting, cancel it. Use for EOD run only.")
    parser.add_argument("--loop", type=int, metavar="SECONDS", default=0,
                        help="Loop forever, re-checking every N seconds (e.g., --loop 15 for "
                             "near-realtime dashboard updates). Default 0 = single pass.")
    parser.add_argument("--until", type=str, metavar="HH:MM", default=None,
                        help="Stop loop at this UTC time (e.g., --until 20:00). Used with --loop "
                             "to terminate at EOD. Without this, --loop runs indefinitely.")
    args = parser.parse_args()

    try:
        client = KalshiClient()
    except KalshiAuthError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    # Parse --until into time-of-day check
    stop_at = None
    if args.until:
        try:
            hh, mm = args.until.split(":")
            stop_at = (int(hh), int(mm))
        except ValueError:
            print(f"FAIL: --until must be HH:MM format, got {args.until!r}", file=sys.stderr)
            return 1

    # Single-shot mode (default — preserves existing cron behavior)
    if args.loop <= 0:
        ok = _run_once(client, args.cancel_unfilled)
        client.close()
        return 0 if ok else 2

    # Loop mode — keep refreshing every N seconds
    print(f"monitor_fills LOOP MODE: every {args.loop}s"
          + (f", stopping at {args.until} UTC" if stop_at else " (no stop time — Ctrl-C to quit)"))
    import time
    try:
        while True:
            now = datetime.now(timezone.utc)
            if stop_at and (now.hour, now.minute) >= stop_at:
                print(f"\nReached stop time {args.until} UTC — exiting loop.")
                break
            try:
                _run_once(client, args.cancel_unfilled, verbose=True)
            except Exception as e:
                print(f"  ERR (continuing): {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(args.loop)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt — exiting loop.")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
