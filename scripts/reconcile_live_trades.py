"""Daily reconciliation cron for live_trades. Fires at 04:00 UTC.

For each live_trades row that's:
  - filled (or partial) AND
  - settlement IS NULL AND
  - target_date < today (the contract should have resolved)

we:
  1. Pull the day's observed daily high from our observations table
  2. Determine whether the contract resolved YES or NO using existing
     contract_resolved_yes() logic
  3. Compute realized P&L:
       won = (settled YES if side='yes', settled NO if side='no')
       payoff = 100 if won else 0
       realized_pnl_cents = payoff - fill_price - kalshi_fee
  4. Update the live_trades row

Then prints a daily summary: yesterday's trades, fills, P&L; 7-day rolling
stats. This same output is what the alerts cron sends to Discord/email.

Idempotent: only updates rows where settlement IS NULL, so re-running is
safe. Exits nonzero if any DB or Kalshi error.
"""
import argparse
import math
import sys
from datetime import datetime, date, timezone

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes


def kalshi_fee_cents(entry_price_cents: int) -> int:
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


def reconcile_one(conn, row) -> dict:
    """Reconcile one live_trades row. Returns updated fields."""
    (id_, target_date, ticker, side, count, fill_price_cents,
     bracket_type, strike_low, strike_high, high_temp_f) = row

    if high_temp_f is None:
        return {"id": id_, "status": "no_observation_yet"}

    contract = {"bracket_type": bracket_type, "strike_low": strike_low, "strike_high": strike_high}
    resolved_yes = contract_resolved_yes(int(high_temp_f), contract)
    settlement = "yes" if resolved_yes else "no"
    won = (side == settlement)

    # Kalshi stores fill_price in YES-side cents (VWAP after monitor_fills fix).
    # What we actually paid depends on which side we bought:
    #   - BUY_YES at fill X:  paid X per contract
    #   - BUY_NO at fill X:   paid (100 - X) per contract (the NO-side equiv)
    # P&L per contract: payoff - paid. Won = $1 payoff, lost = $0.
    if side == "yes":
        paid_per_contract = int(fill_price_cents)
    else:  # "no"
        paid_per_contract = 100 - int(fill_price_cents)
    per_contract_pnl = (100 - paid_per_contract) if won else -paid_per_contract

    # Prefer kalshi_fee_cents already stored (actual fees from Kalshi fills).
    # Fall back to formula only if monitor_fills hasn't populated it yet.
    with conn.cursor() as cur:
        cur.execute("SELECT kalshi_fee_cents FROM live_trades WHERE id=%s", (id_,))
        stored_fee = cur.fetchone()[0]
    if stored_fee is not None:
        total_fee_cents = int(stored_fee)
    else:
        total_fee_cents = kalshi_fee_cents(paid_per_contract) * int(count)
    realized_pnl_cents = per_contract_pnl * int(count) - total_fee_cents

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE live_trades
            SET settlement = %s,
                settlement_time = NOW(),
                realized_pnl_cents = %s,
                kalshi_fee_cents = COALESCE(kalshi_fee_cents, %s)
            WHERE id = %s AND settlement IS NULL
            """,
            (settlement, realized_pnl_cents, total_fee_cents, id_),
        )
    return {"id": id_, "status": "settled",
            "settlement": settlement, "won": won,
            "pnl_cents": realized_pnl_cents}


def print_daily_summary(conn) -> None:
    print("\n" + "=" * 60)
    print("DAILY SUMMARY")
    print("=" * 60)

    with conn.cursor() as cur:
        # Yesterday's activity
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE fill_status IN ('filled','partial')) AS filled,
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
                   COUNT(*) FILTER (WHERE fill_status IN ('filled','partial')) AS filled,
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
            WHERE fill_status IN ('filled','partial') AND settlement IS NOT NULL
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
    args = parser.parse_args()

    with get_connection() as conn:
        # Find unsettled filled trades whose observation is in
        with conn.cursor() as cur:
            cur.execute("""
                SELECT lt.id, lt.target_date, lt.ticker, lt.side, lt.count, lt.fill_price_cents,
                       c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
                FROM live_trades lt
                JOIN contracts c ON c.ticker = lt.ticker
                LEFT JOIN observations o ON o.date = lt.target_date AND o.station_id = c.station_id
                WHERE lt.fill_status IN ('filled','partial')
                  AND lt.settlement IS NULL
                  AND lt.target_date < CURRENT_DATE
                ORDER BY lt.target_date
            """)
            rows = cur.fetchall()

        print(f"=== reconcile_live_trades ({datetime.now(timezone.utc).isoformat()}) ===")
        print(f"  unsettled filled trades to process: {len(rows)}")

        settled = pending = 0
        total_pnl = 0
        for row in rows:
            result = reconcile_one(conn, row)
            if result["status"] == "settled":
                settled += 1
                total_pnl += result["pnl_cents"]
                print(f"  {row[2]} ({row[3]}x{row[4]}): {result['settlement']}, "
                      f"P&L ${result['pnl_cents']/100:+.2f}")
            else:
                pending += 1
                print(f"  {row[2]}: {result['status']} (target_date={row[1]})")

        print(f"\n  settled: {settled}, still-pending: {pending}, "
              f"total P&L this run: ${total_pnl/100:+,.2f}")

        if not args.no_summary:
            print_daily_summary(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
