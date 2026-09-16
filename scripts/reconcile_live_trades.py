"""Daily reconciliation cron for live_trades. Fires at 12:00 UTC.

Books every unsettled row (target_date < today) from KALSHI'S OWN RECORDS:
  - the market's settled result (GET /markets/{ticker} -> result), and
  - the order's final fill, cost and fees (GET /portfolio/orders/{id}).
    realized = (fill_count if outcome_side == result else 0) - fill_cost - fees

Why not our observations / stored fill_count (the old method):
  - observations settled Chicago on KORD while Kalshi settles KMDW, and a bad
    KMIA row (85F vs Kalshi's 90F on 08-29) flipped two $500 outcomes;
  - fill_count is a snapshot -- resting orders kept filling after it was taken;
  - fill_price_cents is mixed YES/NO-leg convention on some rows.
Checked 2026-09-16: this formula ties to /portfolio/settlements to the cent.

Kalshi finalizes weather markets ~11:15 UTC the next day; a row whose market
isn't finalized is left for the next run. Orders Kalshi no longer returns
(404, roughly pre-07-12) are left untouched.

--rebuild re-books already-settled rows too (idempotent: venue truth is final).
"""
import argparse
import sys
from datetime import datetime, timezone

import httpx

from weather_markets.db import get_connection
from weather_markets.kalshi_api import KalshiClient


def venue_booking(client, ticker: str, order_id: str) -> dict:
    """What Kalshi says one order made. status: settled | not_finalized | venue_unavailable."""
    try:
        order = client._request("GET", f"/portfolio/orders/{order_id}")["order"]
        result = client.get_market(ticker)["market"].get("result")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"status": "venue_unavailable"}
        raise
    if result not in ("yes", "no"):
        return {"status": "not_finalized"}
    f = lambda k: float(order.get(k) or 0)
    filled = f("fill_count_fp")
    cost = f("maker_fill_cost_dollars") + f("taker_fill_cost_dollars")
    fees = f("maker_fees_dollars") + f("taker_fees_dollars")
    payout = filled if order["outcome_side"] == result else 0.0
    return {
        "status": "settled",
        "settlement": result,
        "won": filled > 0 and order["outcome_side"] == result,
        "pnl_cents": round((payout - cost - fees) * 100),
        "fee_cents": round(fees * 100),
        "fill_count": round(filled),
        "fill_status": ("cancelled" if filled == 0 else
                        "filled" if filled >= f("initial_count_fp") else "partial"),
    }


def reconcile_one(conn, client, row, dry_run: bool = False) -> dict:
    """Book one live_trades row from the venue. Returns the booking."""
    id_, ticker, order_id = row[0], row[1], row[2]
    b = {"id": id_, **venue_booking(client, ticker, order_id)}
    if b["status"] != "settled" or dry_run:
        return b
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE live_trades
            SET settlement = %s,
                settlement_time = COALESCE(settlement_time, NOW()),
                realized_pnl_cents = %s,
                kalshi_fee_cents = %s,
                fill_count = %s,
                fill_status = %s
            WHERE id = %s
            """,
            (b["settlement"], b["pnl_cents"], b["fee_cents"], b["fill_count"],
             b["fill_status"], id_),
        )
    return b


def print_daily_summary(conn) -> None:
    print("\n" + "=" * 60)
    print("DAILY SUMMARY")
    print("=" * 60)

    with conn.cursor() as cur:
        # Yesterday's activity
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE fill_status IN ('filled','partial','partial_resting')) AS filled,
                   COUNT(*) FILTER (WHERE fill_status = 'pending') AS pending,
                   COUNT(*) FILTER (WHERE fill_status IN ('cancelled','expired')) AS unfilled,
                   COALESCE(SUM(realized_pnl_cents), 0) AS pnl
            FROM live_trades
            WHERE target_date = CURRENT_DATE - INTERVAL '1 day'
        """)
        f, p, u, pnl = cur.fetchone()
        print(f"  Yesterday: {f} filled, {p} still pending, {u} unfilled. P&L: ${int(pnl)/100:+,.2f}")

        # Last 7 days
        cur.execute("""
            SELECT COUNT(*) AS attempted,
                   COUNT(*) FILTER (WHERE fill_status IN ('filled','partial','partial_resting')) AS filled,
                   COALESCE(SUM(realized_pnl_cents), 0) AS pnl
            FROM live_trades
            WHERE placed_at >= NOW() - INTERVAL '7 days'
        """)
        a, f, pnl = cur.fetchone()
        fill_rate = (f / a * 100) if a > 0 else 0
        print(f"  7-day:    {a} attempted, {f} filled ({fill_rate:.0f}% fill rate). P&L: ${int(pnl)/100:+,.2f}")

        # Cumulative
        cur.execute("""
            SELECT COUNT(*) AS total_filled,
                   COALESCE(SUM(realized_pnl_cents), 0) AS pnl_total,
                   COALESCE(AVG(realized_pnl_cents), 0) AS pnl_avg
            FROM live_trades
            WHERE fill_status IN ('filled','partial','partial_resting') AND settlement IS NOT NULL
        """)
        total_f, pnl_total, pnl_avg = cur.fetchone()
        print(f"  Lifetime: {total_f} settled trades. Cumulative P&L: ${int(pnl_total)/100:+,.2f}, "
              f"mean per trade: {float(pnl_avg)/int(total_f) if total_f else 0:+.1f}¢")

        # Rolling 4-week spread for regime monitoring
        cur.execute("""
            SELECT AVG(market_yes_ask - market_yes_bid), COUNT(*)
            FROM paper_trades
            WHERE target_date >= CURRENT_DATE - INTERVAL '28 days'
              AND entry_price_cents >= 60 AND ABS(edge) >= 0.10
              AND market_yes_bid IS NOT NULL AND market_yes_ask IS NOT NULL
              AND model_source = 'EMOS combined 00Z (rolling 45d)'
        """)
        spr, n = cur.fetchone()
        if n and n >= 5:
            print(f"  Spread regime: 4wk avg {float(spr):.2f}¢ on {n} filtered paper-trades")
            if float(spr) > 5:
                print(f"  ⚠️  SPREAD REGIME DEGRADED — kill threshold is 5¢")

    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-summary", action="store_true", help="Skip the daily summary print")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute bookings but write nothing")
    parser.add_argument("--rebuild", action="store_true",
                        help="Also re-book rows that are already settled")
    args = parser.parse_args()

    client = KalshiClient()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, ticker, kalshi_order_id, fill_count, count,
                       realized_pnl_cents, fill_status
                FROM live_trades
                WHERE fill_status IN ('filled','partial','partial_resting','pending')
                  AND kalshi_order_id IS NOT NULL
                  AND target_date < CURRENT_DATE
                  {"" if args.rebuild else "AND settlement IS NULL"}
                ORDER BY target_date, id
            """)
            rows = cur.fetchall()

        print(f"=== reconcile_live_trades ({datetime.now(timezone.utc).isoformat()}) "
              f"{'REBUILD ' if args.rebuild else ''}{'DRY-RUN' if args.dry_run else ''} ===")
        print(f"  rows to process: {len(rows)}")

        settled = skipped = 0
        total_pnl = delta = 0
        for row in rows:
            id_, ticker, _, old_fill, count, old_pnl, old_status = row
            b = reconcile_one(conn, client, row, dry_run=args.dry_run)
            if b["status"] != "settled":
                skipped += 1
                print(f"  #{id_} {ticker}: {b['status']}")
                continue
            settled += 1
            total_pnl += b["pnl_cents"]
            delta += b["pnl_cents"] - (old_pnl or 0)
            old = f"${old_pnl/100:+.2f}" if old_pnl is not None else "unbooked"
            print(f"  #{id_} {ticker} {b['fill_count']}/{count} {b['fill_status']}: "
                  f"{b['settlement']}, P&L ${b['pnl_cents']/100:+.2f}"
                  + ("" if old_pnl == b["pnl_cents"] else
                     f"  (was {old}, {old_status} {old_fill})"))

        print(f"\n  booked: {settled}, skipped: {skipped}, "
              f"P&L of booked rows: ${total_pnl/100:+,.2f}, change vs table: ${delta/100:+,.2f}")

        if not args.no_summary:
            print_daily_summary(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
