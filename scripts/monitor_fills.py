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
from datetime import datetime, timezone, timedelta
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.kalshi_api import KalshiClient, KalshiAuthError, parse_count, parse_dollars_to_cents


# Kalshi status → our fill_status
KALSHI_STATUS_MAP = {
    "resting": "pending",       # still open
    "executed": "filled",       # fully filled
    "canceled": "cancelled",    # cancelled (Kalshi uses US spelling)
}

# ---- 45-minute re-quote for unfilled maker orders ----------------------------
# Research 2026-06-21 (execution-policy maker-vs-taker), Recommendation rule 4:
# an unfilled resting (maker) order is cancelled after REQUOTE_AFTER_MINUTES and
# re-posted as a CROSS at the ask — but ONLY if |edge| >= the per-city threshold
# Y; otherwise it is left to expire. TIF is GTC-only (no IOC), so this is a
# cancel + repost. OFF by default: enable with --requote (live) or
# --requote-dry-run (log-only); must be PAPER-VALIDATED before the cron uses it.
REQUOTE_AFTER_MINUTES = 45
REQUOTE_CROSS_EDGE_THRESHOLD = {   # ticker series prefix -> Y_city
    "KXHIGHCHI": 0.25,    # KORD
    "KXHIGHMIA": 0.10,    # KMIA
    "KXHIGHTDAL": 0.25,   # Dallas (paper watchlist)
}
DEFAULT_REQUOTE_Y = 0.25
REQUOTE_MARKER = "REQUOTE@45m"     # notes marker → one re-quote per order (runaway guard)


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


def requote_threshold_for(ticker: str) -> float:
    """Per-city re-quote cross threshold Y (|edge| >= Y → cross at ask on re-quote)."""
    return REQUOTE_CROSS_EDGE_THRESHOLD.get((ticker or "").split("-")[0], DEFAULT_REQUOTE_Y)


def _requote_decision(edge: float, ticker: str, elapsed_min: float,
                      already_requoted: bool, filled_qty: int) -> str:
    """PURE decision for the time-based re-quote (unit-tested, no I/O). Returns:
      'skip_already'     — already re-quoted once (RUNAWAY guard: one re-quote/order)
      'skip_partial'     — order has fills already; only FULLY-unfilled orders re-quote
      'skip_not_elapsed' — younger than REQUOTE_AFTER_MINUTES
      'leave_expire'     — elapsed but |edge| < Y_city → let it expire (no cross)
      'requote_cross'    — elapsed and |edge| >= Y_city → cancel + repost cross at ask
    """
    if already_requoted:
        return "skip_already"
    if filled_qty > 0:
        return "skip_partial"
    if elapsed_min < REQUOTE_AFTER_MINUTES:
        return "skip_not_elapsed"
    if abs(edge) < requote_threshold_for(ticker):
        return "leave_expire"
    return "requote_cross"


def requote_unfilled_makers(client, *, now=None, dry_run: bool = False, verbose: bool = True) -> bool:
    """Cancel + repost (as a cross at the ask) each FULLY-UNFILLED resting maker
    order older than REQUOTE_AFTER_MINUTES, iff |edge| >= the per-city threshold;
    otherwise leave it to expire. GTC-only TIF → cancel + V2 create (re-post).

    DOUBLE-FILL guard: re-checks the LIVE order fill state right BEFORE cancelling
    (skip if it started filling) and again AFTER cancelling (if it filled during
    the cancel, record the fill and do NOT repost — never two positions).
    RUNAWAY guard: one re-quote per order, enforced by a notes marker.
    `dry_run` logs decisions without any API writes. Returns True on no errors."""
    # live_trade owns the cross-price + guaranteed-fill (V2 create) helpers.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from live_trade import place_with_guaranteed_fill, fetch_live_cross_price

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=REQUOTE_AFTER_MINUTES)
    today = now.date()
    if verbose:
        print(f"\n=== requote pass ({now.isoformat()}, T={REQUOTE_AFTER_MINUTES}m, dry_run={dry_run}) ===")
    had_error = False
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, kalshi_order_id, ticker, side, count, edge, placed_at, client_order_id, notes
                FROM live_trades
                WHERE fill_status = 'pending' AND target_date = %s
                  AND kalshi_order_id IS NOT NULL
                  AND placed_at <= %s
                ORDER BY placed_at
            """, (today, cutoff))
            rows = cur.fetchall()
        if verbose:
            print(f"  unfilled resting orders aged >= {REQUOTE_AFTER_MINUTES}m: {len(rows)}")

        for (id_, koid, ticker, side, count, edge, placed_at, coid, notes) in rows:
            elapsed_min = (now - placed_at).total_seconds() / 60.0
            already = REQUOTE_MARKER in (notes or "")
            # Double-fill guard #1: re-fetch the LIVE order state before deciding.
            try:
                order = client.get_order(koid, ticker=ticker)
                order = order.get("order", order)
                filled_qty = max(0, parse_count(order, "initial_count_fp")
                                 - parse_count(order, "remaining_count_fp"))
                resting = order.get("status", "").lower() == "resting"
            except Exception as e:
                print(f"  {ticker} (id={id_}): get_order failed: {e}", file=sys.stderr)
                had_error = True
                continue
            decision = _requote_decision(float(edge), ticker, elapsed_min, already, filled_qty)
            if decision == "requote_cross" and not resting:
                decision = "skip_partial"   # no longer resting (filled/cancelled) → leave it
            y = requote_threshold_for(ticker)
            if decision != "requote_cross":
                if verbose:
                    print(f"  {ticker} (id={id_}): {decision} "
                          f"(edge={edge:.3f} Y={y} elapsed={elapsed_min:.0f}m filled={filled_qty})")
                continue

            if dry_run:
                ask = fetch_live_cross_price(client, ticker, side)
                print(f"  {ticker} (id={id_}): WOULD requote → cross@ask {ask}c "
                      f"(edge={edge:.3f} >= Y{y}, count={count}) [dry-run, no writes]")
                continue

            try:
                client.cancel_order(koid)
            except Exception as e:
                print(f"  {ticker} (id={id_}): cancel failed: {e}", file=sys.stderr)
                had_error = True
                continue
            # Double-fill guard #2: did it fill during the cancel? If so, keep that
            # fill and do NOT repost.
            try:
                o2 = client.get_order(koid, ticker=ticker)
                o2 = o2.get("order", o2)
                filled2 = max(0, parse_count(o2, "initial_count_fp") - parse_count(o2, "remaining_count_fp"))
            except Exception:
                filled2 = 0
            if filled2 > 0:
                with conn.cursor() as cur:
                    cur.execute("UPDATE live_trades SET fill_status='partial', "
                                "notes=COALESCE(notes,'')||%s WHERE id=%s",
                                (f" | {REQUOTE_MARKER} aborted: {filled2} filled during cancel", id_))
                print(f"  {ticker} (id={id_}): {filled2} filled during cancel → recorded, NOT reposted")
                continue

            ask = fetch_live_cross_price(client, ticker, side)
            if ask is None:
                with conn.cursor() as cur:
                    cur.execute("UPDATE live_trades SET fill_status='cancelled', "
                                "notes=COALESCE(notes,'')||%s WHERE id=%s",
                                (f" | {REQUOTE_MARKER}: cancelled, no ask available", id_))
                print(f"  {ticker} (id={id_}): no ask → cancelled, not reposted")
                continue
            new_coid = f"{coid}-rq" if coid else None
            status, price_used, new_koid, coid_used, note = place_with_guaranteed_fill(
                client, ticker=ticker, side=side, count=count, limit_price=ask,
                cross_price=ask, primary_post_only=False, client_order_id=new_coid)
            with conn.cursor() as cur:
                if status == "placed":
                    cur.execute("""UPDATE live_trades
                        SET kalshi_order_id=%s, client_order_id=COALESCE(%s, client_order_id),
                            limit_price_cents=%s, cross_price_cents=%s, fill_status='pending',
                            placed_at=NOW(), notes=COALESCE(notes,'')||%s
                        WHERE id=%s""",
                        (new_koid, coid_used, price_used, price_used,
                         f" | {REQUOTE_MARKER} cross@{price_used}c (edge={edge:.3f}>=Y{y}){note}", id_))
                    print(f"  {ticker} (id={id_}): REQUOTED as cross@{price_used}c (edge={edge:.3f})")
                else:
                    cur.execute("UPDATE live_trades SET fill_status='cancelled', "
                                "notes=COALESCE(notes,'')||%s WHERE id=%s",
                                (f" | {REQUOTE_MARKER} repost REJECTED: {note}", id_))
                    print(f"  {ticker} (id={id_}): cancelled; repost REJECTED: {note}", file=sys.stderr)
                    had_error = True
    return not had_error


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
    parser.add_argument("--requote", action="store_true",
                        help="After the fill pass, run the 45-min re-quote: cancel each unfilled "
                             "maker order older than 45m and re-post as a cross at the ask iff "
                             "|edge|>=Y_city. PLACES REAL ORDERS — paper-validate before cron use.")
    parser.add_argument("--requote-dry-run", action="store_true",
                        help="Log what the 45-min re-quote WOULD do (which orders, ask price) "
                             "without cancelling or placing anything. Safe to run live.")
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
        if args.requote or args.requote_dry_run:
            ok = requote_unfilled_makers(client, dry_run=args.requote_dry_run) and ok
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
                if args.requote or args.requote_dry_run:
                    requote_unfilled_makers(client, dry_run=args.requote_dry_run, verbose=True)
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
