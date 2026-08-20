"""Reconcile ForecastEx (IBKR) probe trades: fills, then settlement.

Exists for the same reason as reconcile_pm_trades.py, and was written before the
trader was ever cronned rather than after it bit us: live_trade_forecastex.py
reads cumulative realized_pnl_cents to decide whether to halt, and nothing else
writes that column. Without this the $200 probe stop can never fire.

SETTLEMENT SOURCE. ForecastEx settles on Weather Underground, NOT the NWS CLI in
our observations table. Scoring against observations would invent edge — the
measured gap runs to -2.4F on some stations. The settled value is recovered from
ForecastEx's own strike ladder and cached in data/forecastex_settlements.json by
forecastex_backtest.py, which runs at 05:00 UTC. A day is therefore scoreable
only after that cron has seen it settle.

  uv run python scripts/reconcile_fx_trades.py            # report only
  uv run python scripts/reconcile_fx_trades.py --apply
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.forecastex import FEE_CENTS_PER_CONTRACT
from weather_markets.ibkr import IBKRClient, IBKRError

SETTLE_CACHE = Path(__file__).resolve().parents[1] / "data" / "forecastex_settlements.json"
STATION_PRODUCT = {"KMIA": "UHMIA", "KDFW": "UHDFW", "KLAX": "UHLAX", "KPHX": "UHPHX"}


def ibkr_fills(client: IBKRClient) -> dict:
    """order_id -> (filled_qty, avg_price_cents) from IBKR's order list.

    Returns {} when the session is dead rather than raising: settlement scoring
    of already-filled rows must still work when the gateway is logged out.
    """
    try:
        resp = client.live_orders()
    except IBKRError as e:
        print(f"  (IBKR unreachable, fills skipped: {str(e)[:90]})")
        return {}
    out = {}
    for o in (resp.get("orders") or []):
        oid = str(o.get("order_id") or "")
        filled = o.get("filledQuantity") or o.get("cumQuantity") or o.get("filled")
        px = o.get("avgPrice") or o.get("average_price") or o.get("price")
        if not oid or filled in (None, ""):
            continue
        try:
            qty = float(filled)
            avg = float(px) * (100.0 if float(px) <= 1.0 else 1.0) if px else None
        except (TypeError, ValueError):
            continue
        out[oid] = (qty, avg)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    settled = json.loads(SETTLE_CACHE.read_text()) if SETTLE_CACHE.exists() else {}
    client = IBKRClient()
    fills = ibkr_fills(client)
    print(f"IBKR reports fills for {len(fills)} order(s)\n")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, target_date, station_id, fx_contract_id, side,
                                  strike, count, limit_price_cents, ibkr_order_id,
                                  fill_count, fill_avg_price_cents, settlement
                           FROM fx_live_trades ORDER BY target_date, id""")
            rows = cur.fetchall()
        if not rows:
            print("no fx_live_trades rows yet.")
            return 0

        print(f"{'date':11}{'city':6}{'side':5}{'strk':>6}{'req':>5}{'fill':>6}"
              f"{'avg':>7}{'settle':>9}{'P&L':>10}")
        updates, total = [], 0.0
        for (rid, td, st, cid, side, strike, req, lim, oid, had_n, had_px, done) in rows:
            n, avg = fills.get(str(oid), (had_n or 0, had_px))
            if avg is None:
                avg = float(lim)          # assume the limit if IBKR gave no average
            pnl_c, verdict = None, "open"

            high = (settled.get(STATION_PRODUCT.get(st, ""), {}) or {}).get(str(td))
            if n and n > 0 and high is not None:
                # ForecastEx semantics: YES pays iff the settled high EXCEEDS the
                # strike. Strictly greater — a high equal to the strike is a NO.
                yes_won = float(high) > float(strike)
                won = yes_won if side == "yes" else not yes_won
                pnl_c = ((100.0 - avg) if won else -avg) * n - FEE_CENTS_PER_CONTRACT * n
                verdict = "win" if won else "loss"
                total += pnl_c
            elif n and n > 0:
                verdict = "unsettled"
            elif high is not None:
                verdict = "no_fill"
                pnl_c = 0.0

            print(f"{str(td):11}{st:6}{side:5}{strike:6.0f}{req:5d}{n:6.0f}"
                  f"{avg:6.1f}c{verdict:>9}"
                  f"{('$%.2f' % (pnl_c/100)) if pnl_c is not None else '—':>10}")
            updates.append((n, avg, verdict if pnl_c is not None else None, pnl_c, rid))

        print(f"\ncumulative realized: ${total/100:+,.2f}  (probe kill at -$200.00)")
        if a.apply:
            with conn.cursor() as cur:
                for n, avg, verdict, pnl_c, rid in updates:
                    cur.execute("""UPDATE fx_live_trades
                        SET fill_count=%s, fill_avg_price_cents=%s,
                            settlement=COALESCE(%s, settlement),
                            realized_pnl_cents=COALESCE(%s, realized_pnl_cents)
                        WHERE id=%s""", (int(n), avg, verdict, pnl_c, rid))
            conn.commit()
            print(f"applied {len(updates)} row(s)")
        else:
            print(f"DRY RUN — {len(updates)} row(s) would change. Add --apply.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
