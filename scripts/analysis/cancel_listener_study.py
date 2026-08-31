"""Would cancelling a resting order when its edge decays have made money?

The question: our bot posts a limit order and walks away. Should it instead
watch the book and pull the order when the edge that justified it is gone?

NO NEW LOGGING WAS NEEDED. model_prob_yes is fixed for the life of an order
(EMOS off the 00Z init, it does not move intraday), and prices snapshots every
5 minutes, so the whole intraday edge path is already reconstructable:

    edge(t) = model_prob_yes - mid(t)

104 filled Kalshi orders rested >=15 min before filling, averaging 16 price
points inside the placement->fill window. That is the sample.

WHAT THIS CORRECTS. A first pass looked only at orders whose edge had fallen
below the 10% entry threshold BY FILL TIME, found 14 of them worth -$670, and
looked like a 54% improvement. Eight of those filled with 0 minutes of lag --
unreachable by any listener -- leaving n=5, of which two orders were 90% of the
benefit and one was a live winner the rule would have cancelled. Sweeping every
rule over all 104 resting orders is the honest version of that question.

SIGN CONVENTION. edge is stored as model_prob_yes - market_mid. A BUY_YES wants
it positive, a BUY_NO negative, so the edge *in our favour* is
`edge if side == yes else -edge`. Rules fire on that, never on the raw column.

    uv run python scripts/analysis/cancel_listener_study.py
    uv run python scripts/analysis/cancel_listener_study.py --min-rest 5
"""
from __future__ import annotations

import argparse
import statistics
from datetime import datetime

from weather_markets.db import get_connection

ORDERS_SQL = """
SELECT t.id, t.ticker, t.target_date, t.side, t.placed_at, t.fill_time,
       t.model_prob_yes, t.edge, t.fill_count, t.realized_pnl_cents
FROM live_trades t
WHERE t.fill_status = 'filled'
  AND t.fill_time IS NOT NULL
  AND t.model_prob_yes IS NOT NULL
  AND t.realized_pnl_cents IS NOT NULL
  AND t.fill_time > t.placed_at + (%s * interval '1 minute')
ORDER BY t.target_date, t.placed_at
"""

PATH_SQL = """
SELECT snapshot_at, (yes_bid + yes_ask) / 200.0 AS mid
FROM prices
WHERE ticker = %s AND snapshot_at > %s AND snapshot_at < %s
  AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL
ORDER BY snapshot_at
"""


def signed(edge: float, side: str) -> float:
    """Edge in the direction we actually bet. See SIGN CONVENTION above."""
    return edge if (side or "").lower().startswith("y") else -edge


def load(conn, min_rest: int) -> list[dict]:
    out = []
    with conn.cursor() as cur:
        cur.execute(ORDERS_SQL, (min_rest,))
        rows = cur.fetchall()
    for (oid, tk, td, side, placed, ft, mp, edge, fc, pnl) in rows:
        with conn.cursor() as cur:
            cur.execute(PATH_SQL, (tk, placed, ft))
            path = [(ts, float(m)) for ts, m in cur.fetchall()]
        if not path:
            continue                      # no observable path: no rule could fire
        out.append({
            "id": oid, "ticker": tk, "date": td, "side": side,
            "placed": placed, "fill_time": ft,
            "p": float(mp), "edge0": signed(float(edge), side),
            "pnl": int(pnl),
            # signed edge at each 5-min snapshot between placement and fill
            "path": [(ts, signed(float(mp) - m, side)) for ts, m in path],
        })
    return out


def cancelled(order: dict, rule) -> bool:
    """Did the rule fire at any snapshot strictly before the fill?"""
    return any(rule(e, order["edge0"]) for _, e in order["path"])


RULES: dict[str, callable] = {
    "baseline (never cancel)":      lambda e, e0: False,
    "cancel if edge < 0 (flip)":    lambda e, e0: e < 0,
    "cancel if edge < 2%":          lambda e, e0: e < 0.02,
    "cancel if edge < 4%":          lambda e, e0: e < 0.04,
    "cancel if edge < 6%":          lambda e, e0: e < 0.06,
    "cancel if edge < 8%":          lambda e, e0: e < 0.08,
    "cancel if edge < 10% (entry)": lambda e, e0: e < 0.10,
    "cancel if edge < 25% of e0":   lambda e, e0: e < 0.25 * abs(e0),
    "cancel if edge < 50% of e0":   lambda e, e0: e < 0.50 * abs(e0),
    "cancel if edge < 75% of e0":   lambda e, e0: e < 0.75 * abs(e0),
}


def score(orders: list[dict], rule) -> tuple[float, int, list[int]]:
    """(total $, n cancelled, per-order cents kept)."""
    kept, n_cancel = [], 0
    for o in orders:
        if cancelled(o, rule):
            n_cancel += 1
            kept.append(0)
        else:
            kept.append(o["pnl"])
    return sum(kept) / 100.0, n_cancel, kept


def report(title: str, orders: list[dict]) -> None:
    if not orders:
        print(f"\n{title}: no orders"); return
    print(f"\n{title}  (n={len(orders)})")
    print(f"  {'rule':30s}{'total $':>10}{'cancelled':>11}{'per order':>11}{'Sharpe':>8}")
    for name, rule in RULES.items():
        tot, n_cancel, kept = score(orders, rule)
        sd = statistics.pstdev(kept) or 1e-9
        sh = (statistics.mean(kept) / sd) * (len(kept) ** 0.5)
        print(f"  {name:30s}{tot:+10.2f}{n_cancel:11d}{tot/len(orders):+11.2f}{sh:8.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-rest", type=int, default=15,
                    help="minutes an order must have rested to be reachable (default 15)")
    a = ap.parse_args()

    conn = get_connection()
    orders = load(conn, a.min_rest)
    if not orders:
        print("no orders matched"); return 1

    print(f"Cancel-listener study — orders resting >={a.min_rest} min before filling")
    print(f"{len(orders)} orders, "
          f"{sum(len(o['path']) for o in orders) / len(orders):.0f} price points each on average")

    report("FULL SAMPLE (in-sample — every rule is chosen knowing the answer)", orders)

    # Out-of-sample discipline: split by date, not by order, so a single day's
    # orders cannot straddle the boundary and leak.
    dates = sorted({o["date"] for o in orders})
    cut = dates[len(dates) // 2]
    report(f"FIRST HALF  (<= {cut})", [o for o in orders if o["date"] <= cut])
    report(f"SECOND HALF (>  {cut})", [o for o in orders if o["date"] > cut])

    print("\nA rule is only interesting if it beats baseline in BOTH halves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
