"""Reconcile Polymarket live trades: fills, then settlement.

Why this has to exist: live_trade_polymarket.py places orders and never looks
back. pm_live_trades therefore reads fill_count=0 forever, which matters far
more than a wrong dashboard number — CUMULATIVE_KILL_CENTS is computed from
realized_pnl_cents, so with nothing ever reconciled THE KILL SWITCH CAN NEVER
FIRE. A probe with a disabled stop is not a probe.

Fills come from GET /v1/activities rather than GET /v1/orders/{id}: the order
endpoint 404s on the ids we store, while each ACTIVITY_TYPE_TRADE carries
trade.aggressorExecution.order.id, which does match. One order can produce
several executions (an IOC walks the book), so executions are summed per order.

Settlement uses the NWS CLI high from `observations` — correct here, unlike
ForecastEx, because Polymarket settles on the same source Kalshi does.

  uv run python scripts/reconcile_pm_trades.py            # report only
  uv run python scripts/reconcile_pm_trades.py --apply    # write to the DB
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from weather_markets.db import get_connection
from weather_markets.polymarket import PolymarketClient

FEE_NOTE = "fees are PM's commissionNotionalCollected, already netted out"


def collect_executions(client: PolymarketClient, max_pages: int = 20) -> dict:
    """order_id -> {shares, notional_cents, fee_cents, execs}. Follows nextCursor
    so a long history does not silently truncate to the first page."""
    out: dict[str, dict] = defaultdict(
        lambda: {"shares": 0.0, "notional_c": 0.0, "fee_c": 0.0, "execs": 0})
    cursor, pages = None, 0
    while pages < max_pages:
        params = {"cursor": cursor} if cursor else None
        resp = client._request("GET", "/v1/portfolio/activities", params=params)
        for a in resp.get("activities", []):
            if a.get("type") != "ACTIVITY_TYPE_TRADE":
                continue
            ex = (a.get("trade") or {}).get("aggressorExecution") or {}
            oid = ((ex.get("order") or {}).get("id"))
            if not oid:
                continue
            shares = float(ex.get("lastShares") or 0)
            if shares <= 0:
                continue
            # lastPx is quoted from the YES leg no matter which side we bought —
            # the same convention as Kalshi's V2 orders. For a BUY_SHORT the
            # price actually paid is (1 - lastPx). Verified against the positions
            # endpoint: the YES-leg reading gives 52.1c, the corrected one gives
            # 47.9c, and baseCost/shares is 0.4794.
            px = float((ex.get("lastPx") or {}).get("value") or 0) * 100.0
            if (ex.get("order") or {}).get("intent", "").endswith("SHORT"):
                px = 100.0 - px
            fee = float((ex.get("commissionNotionalCollected") or {}).get("value") or 0) * 100.0
            r = out[oid]
            r["shares"] += shares
            r["notional_c"] += shares * px
            r["fee_c"] += fee
            r["execs"] += 1
        cursor = resp.get("nextCursor")
        pages += 1
        if resp.get("eof") or not cursor:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write; otherwise report only")
    a = ap.parse_args()

    client = PolymarketClient()
    try:
        execs = collect_executions(client)
    finally:
        client.close()
    print(f"found executions for {len(execs)} order(s)\n")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.id, t.target_date, t.ticker, t.intent, t.count,
                       t.pm_order_id, t.fill_count, t.fill_avg_price_cents,
                       t.settlement, c.strike_low, c.strike_high, c.bracket_type,
                       o.high_temp_f
                FROM pm_live_trades t
                LEFT JOIN contracts c ON c.ticker = t.ticker
                LEFT JOIN observations o
                       ON o.date = t.target_date AND o.station_id = c.station_id
                ORDER BY t.target_date, t.id""")
            rows = cur.fetchall()

        print(f"{'date':11}{'ticker':42}{'req':>5}{'filled':>8}{'avg':>7}"
              f"{'fee':>7}{'settle':>8}{'P&L':>10}")
        updates, total = [], 0.0
        for (rid, td, ticker, intent, req, oid, had_fill, had_px,
             settled, lo, hi, btype, obs) in rows:
            e = execs.get(oid)
            if not e or e["shares"] <= 0:
                print(f"{str(td):11}{ticker[:41]:42}{req:5.0f}{'—':>8}{'—':>7}"
                      f"{'—':>7}{'no fill':>8}{'—':>10}")
                continue
            n = e["shares"]
            avg_c = e["notional_c"] / n
            fee_c = e["fee_c"]

            pnl_c, verdict = None, "open"
            if obs is not None and lo is not None:
                # PM brackets are half-open [lo, hi): "gte93lt94" is 93 ONLY,
                # not Kalshi's 93-94 pair. Getting this wrong inverts the result.
                in_bracket = (obs >= lo and obs < hi) if hi is not None else (obs >= lo)
                won = (not in_bracket) if intent.endswith("SHORT") else in_bracket
                pnl_c = ((100.0 - avg_c) if won else -avg_c) * n - fee_c
                verdict = "win" if won else "loss"
                total += pnl_c
            print(f"{str(td):11}{ticker[:41]:42}{req:5.0f}{n:8.1f}{avg_c:6.1f}c"
                  f"{fee_c:6.1f}c{verdict:>8}"
                  f"{('$%.2f' % (pnl_c / 100)) if pnl_c is not None else '—':>10}")
            updates.append((n, avg_c, verdict if pnl_c is not None else None,
                            pnl_c, rid))

        print(f"\n{FEE_NOTE}")
        print(f"cumulative realized: ${total/100:+,.2f}  "
              f"(kill switch fires below -$300.00)")

        if a.apply and updates:
            with conn.cursor() as cur:
                for n, avg_c, verdict, pnl_c, rid in updates:
                    cur.execute("""
                        UPDATE pm_live_trades
                        SET fill_count=%s, fill_avg_price_cents=%s,
                            settlement=COALESCE(%s, settlement),
                            realized_pnl_cents=COALESCE(%s, realized_pnl_cents)
                        WHERE id=%s""", (n, avg_c, verdict, pnl_c, rid))
            conn.commit()
            print(f"\napplied {len(updates)} row(s)")
        elif updates:
            print(f"\nDRY RUN — {len(updates)} row(s) would change. Add --apply.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
