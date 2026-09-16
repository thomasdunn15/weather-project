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

from weather_markets.alerts import send_alert
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


def collect_resolutions(client: PolymarketClient, max_pages: int = 25) -> dict:
    """market_slug -> {net, cost_c, realized_c, fee_c} from the VENUE's own
    POSITION_RESOLUTION records.

    THIS, NOT OUR ARITHMETIC, IS THE SOURCE OF TRUTH FOR SETTLED P&L.

    Reconstructing P&L from trade activity plus our own bracket logic failed
    twice in two days. On 2026-08-23 an inline half-open bracket read booked a
    loss as a win. On 2026-08-25 the deeper problem surfaced: collect_executions
    keys on aggressorExecution.order.id, so a MAKER fill carries no execution of
    ours and reads as "no fill". The 08-23 corrective YES long (150 @ 60c, a
    resting GTC order) filled and won +$54.18, and we recorded it as unfilled
    while booking -$66.51 on the short it replaced. Cumulative was -$176.81
    against a venue truth of -$49.13.

    Polymarket nets by MARKET, not by order, so one resolution can cover several
    of our order rows; the caller attributes it once per (target_date, ticker).
    Reading `realized` straight from the venue removes bracket semantics, fill
    attribution, fee modelling and settlement-source questions in one move.
    """
    out: dict[str, dict] = {}
    cursor, pages = None, 0
    while pages < max_pages:
        params = {"cursor": cursor} if cursor else None
        resp = client._request("GET", "/v1/portfolio/activities", params=params)
        for a in resp.get("activities", []):
            if a.get("type") != "ACTIVITY_TYPE_POSITION_RESOLUTION":
                continue
            pr = a["positionResolution"]
            before, after = pr["beforePosition"], pr["afterPosition"]
            fee_c = float((before.get("fees") or {}).get("value") or 0) * 100.0

            # 2026-09-16, fourth correction: the after-position fields are NOT
            # a P&L. A losing LONG leaves after.realized at 0 and after.cost at
            # its pre-fee basis, which the previous reading booked as a GAIN
            # (09-01 and 09-12 Miami longs, +$115 booked on -$123 lost; ledger
            # +$420.44 against venue cash +$166.34). What the venue does state
            # consistently is on the BEFORE record: cashValue is the payout at
            # resolution (0 on a loss, |net| on a win) and cost is the full
            # basis including fees. payout - cost reproduces all 15 settled
            # markets and ties to the account balance to the cent.
            payout_c = float((before.get("cashValue") or {}).get("value") or 0) * 100.0
            cost_c = float(before["cost"]["value"]) * 100.0
            out[pr["marketSlug"]] = {
                "net": float(before.get("netPositionDecimal") or 0),
                "cost_c": cost_c,
                "realized_c": payout_c - cost_c,
                "fee_c": fee_c,
            }
        cursor = resp.get("nextCursor")
        pages += 1
        if resp.get("eof") or not cursor:
            break
    return out



# The operator's own cash is readable from the venue; only the promo credit is
# not (it arrives outside the deposit feed), so it stays a constant here.
PROMO_CREDIT_CENTS = 0           # 2026-09-16: the credit is a $20 REFERRAL_BONUS in the venue feed, counted with deposits
DRIFT_ALERT_CENTS = 200          # $2 — above fee-rounding, below a real miss


def venue_deposits_cents(client, max_pages: int = 25) -> float:
    """Total COMPLETED account deposits, in cents, from the venue's own feed.

    Pending and failed transfers share the ACCOUNT_DEPOSIT type — 13 records on
    2026-08-28 of which only 3 had completed — so the status filter is what
    makes this a funding figure rather than an intent figure.
    """
    total, cursor, pages = 0.0, None, 0
    while pages < max_pages:
        resp = client._request("GET", "/v1/portfolio/activities",
                               params={"cursor": cursor} if cursor else None)
        for a in resp.get("activities", []):
            if a.get("type") not in ("ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
                                     "ACTIVITY_TYPE_REFERRAL_BONUS"):
                continue
            ch = a["accountBalanceChange"]
            if ch.get("status") == "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED":
                total += float(ch["amount"]["value"]) * 100.0
        cursor = resp.get("nextCursor")
        pages += 1
        if resp.get("eof") or not cursor:
            break
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write; otherwise report only")
    a = ap.parse_args()

    client = PolymarketClient()
    try:
        execs = collect_executions(client)
        resolutions = collect_resolutions(client)
        # Gather the cash figures here too — the client is closed below, and
        # the cross-check that uses them runs after the DB work.
        try:
            cash_c = sum(float(b["currentBalance"]) for b in
                         client.get_balance()["balances"]) * 100.0
            deposits_c = venue_deposits_cents(client)
        except Exception as e:
            print(f"(cash cross-check unavailable: {type(e).__name__}: {e})")
            cash_c = deposits_c = None
    finally:
        client.close()
    print(f"found executions for {len(execs)} order(s), "
          f"{len(resolutions)} settled position(s)\n")

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
        booked: set[tuple] = set()      # (target_date, ticker) already credited
        for (rid, td, ticker, intent, req, oid, had_fill, had_px,
             settled, lo, hi, btype, obs) in rows:
            res = resolutions.get(ticker)
            e = execs.get(oid)

            # SETTLED: take the venue's own realized figure, once per market.
            # Polymarket nets by market, so several of our order rows can share
            # one resolution — credit the first and zero the rest so the column
            # the kill switch sums stays exactly equal to the venue's number.
            if res is not None:
                key = (td, ticker)
                first = key not in booked
                booked.add(key)
                pnl_c = res["realized_c"] if first else 0.0
                verdict = ("win" if res["realized_c"] > 0 else "loss") if first else "netted"
                n = abs(res["net"]) if first else 0.0
                avg_c = (res["cost_c"] / n) if n else 0.0
                total += pnl_c
                print(f"{str(td):11}{ticker[:41]:42}{req:5.0f}{n:8.1f}{avg_c:6.1f}c"
                      f"{res['fee_c'] if first else 0:6.1f}c{verdict:>8}"
                      f"{('$%.2f' % (pnl_c / 100)):>10}")
                updates.append((n or (had_fill or 0), avg_c or had_px,
                                verdict, pnl_c, rid))
                continue

            if not e or e["shares"] <= 0:
                print(f"{str(td):11}{ticker[:41]:42}{req:5.0f}{'—':>8}{'—':>7}"
                      f"{'—':>7}{'no fill':>8}{'—':>10}")
                continue
            n = e["shares"]
            avg_c = e["notional_c"] / n
            fee_c = e["fee_c"]

            # Not yet resolved by the venue: report the fill, book nothing.
            # We deliberately no longer settle these ourselves. The old path
            # scored our own bracket logic against observations and got it
            # wrong twice in two days — see collect_resolutions().
            print(f"{str(td):11}{ticker[:41]:42}{req:5.0f}{n:8.1f}{avg_c:6.1f}c"
                  f"{fee_c:6.1f}c{'open':>8}{'—':>10}")
            updates.append((n, avg_c, None, None, rid))

        print(f"\n{FEE_NOTE}")
        print(f"cumulative realized: ${total/100:+,.2f}  "
              f"(kill switch fires below -$300.00)")

        # CROSS-CHECK AGAINST CASH. Per-trade arithmetic has been wrong three
        # times now — half-open brackets (08-23), maker fills invisible to the
        # execution replay (08-25), and wins hiding in afterPosition.cost while
        # we read afterPosition.realized (08-28). Every one was caught by the
        # operator noticing a number looked off, not by us. The account balance
        # is the one figure the venue cannot state two ways, so reconcile to it
        # and say so out loud when they disagree.
        if cash_c is not None:
            implied_c = cash_c - deposits_c - PROMO_CREDIT_CENTS
            drift_c = total - implied_c
            print(f"venue cash ${cash_c/100:,.2f} - deposits ${deposits_c/100:,.2f} "
                  f"- promo ${PROMO_CREDIT_CENTS/100:.2f} = ${implied_c/100:+,.2f} implied")
            print(f"drift vs per-trade sum: ${drift_c/100:+,.2f}")
            if abs(drift_c) > DRIFT_ALERT_CENTS:
                send_alert(
                    f"Polymarket P&L drift ${drift_c/100:+,.2f}: per-trade sum says "
                    f"${total/100:+,.2f}, cash says ${implied_c/100:+,.2f}. "
                    f"The cash figure is the trustworthy one.",
                    severity="warning", source="reconcile_pm_trades")

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
