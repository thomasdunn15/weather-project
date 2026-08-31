"""Score day-ahead LOW-temperature paper trades: skill vs the market, then P&L.

Two questions, in order, because the second is meaningless without the first:

  1. SKILL. Is our Brier better than the market's on the same contracts? This is
     rule-independent — no threshold, no sizing, no fees. If the market beats us
     there is no edge to harvest and the P&L column is noise.
  2. P&L. Only if skill clears.

WHY THIS EXISTS. The lows were tested once before, on NYC, and lost ~14c/contract
(2026-03..06). That looked like a verdict on lows. It was not: on NYC the market
also beats us on HIGHS by 54-141% Brier, so the experiment tested a real question
on a city where we have no edge either way. Miami is the one city with a durable,
live-confirmed edge on highs, so it is the only fair test of the variable.

    uv run python scripts/analysis/score_lows.py
    uv run python scripts/analysis/score_lows.py --station KNYC   # the old result
"""
from __future__ import annotations

import argparse
import statistics

from weather_markets.db import get_connection
from weather_markets.evaluation import brier_score, contract_resolved_yes

SQL = """
SELECT pt.model_source, pt.target_date, pt.ticker, pt.position, pt.entry_price_cents,
       pt.model_prob_yes, pt.market_mid_prob, pt.edge, pt.edge_threshold,
       c.bracket_type, c.strike_low, c.strike_high, o.low_temp_f
FROM paper_trades pt
JOIN contracts c ON c.ticker = pt.ticker
JOIN observations o ON o.station_id = c.station_id AND o.date = pt.target_date
WHERE pt.model_source = %s AND o.low_temp_f IS NOT NULL
  AND pt.model_prob_yes IS NOT NULL AND pt.market_mid_prob IS NOT NULL
ORDER BY pt.target_date
"""

FEE = 0.07   # same flat 7% the sim charges Kalshi takers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="EMOS combined day-ahead lows KMIA (rolling 45d)")
    ap.add_argument("--threshold", type=float, default=0.10)
    a = ap.parse_args()

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(SQL, (a.source,))
        rows = cur.fetchall()
    if not rows:
        print(f"no rows for model_source={a.source!r}"); return 1

    ours = mkt = 0.0
    days, traded, wins, pnl = set(), 0, 0, 0.0
    per_day: dict = {}
    for (_src, td, tk, pos, entry, mp, mm, edge, thr, bt, lo, hi, obs) in rows:
        yes = contract_resolved_yes(int(round(obs)),
                                    {"bracket_type": bt, "strike_low": lo, "strike_high": hi})
        ours += brier_score(float(mp), yes)
        mkt += brier_score(float(mm), yes)
        days.add(td)
        if edge is None or abs(float(edge)) < a.threshold or entry is None:
            continue
        won = yes if str(pos).upper().endswith("YES") else (not yes)
        traded += 1; wins += int(won)
        p = ((100 - entry) if won else -entry) - FEE * entry
        pnl += p
        per_day[td] = per_day.get(td, 0.0) + p

    n = len(rows)
    ob, mb = ours / n, mkt / n
    print(f"{a.source}\n{n} contract-days over {len(days)} days\n")
    print("1. SKILL (rule-independent)")
    print(f"   our Brier    : {ob:.4f}")
    print(f"   market Brier : {mb:.4f}")
    print(f"   skill vs mkt : {100 * (mb - ob) / mb:+.1f}%"
          f"   {'<-- we beat the market' if ob < mb else '<-- MARKET WINS: no edge'}\n")

    print(f"2. P&L at |edge| >= {a.threshold:.0%}, 1 contract, {FEE:.0%} fee")
    if not traded:
        print("   no contract cleared the threshold"); return 0
    vals = list(per_day.values())
    sd = statistics.pstdev(vals) or 1e-9
    print(f"   trades       : {traded} on {len(per_day)} days")
    print(f"   win rate     : {100 * wins / traded:.1f}%")
    print(f"   total        : {pnl / 100:+,.2f} per contract-unit")
    print(f"   per trade    : {pnl / traded:+.2f}c")
    print(f"   daily Sharpe : {statistics.mean(vals) / sd * (len(vals) ** 0.5):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
