"""Should the Polymarket live edge threshold drop from 0.25 to 0.10?

Evidence = the forward PM paper log (all 5 PM cities, logged at 0.10 so it
captures the marginal 0.10-0.25 band), settled against NWS CLI highs with the
shared bracket helpers and PM's taker fee. Entry is the logged crossing price
(YES at ask, NO at 100-bid), the same basis the live IOC-limit script pays.

Two views:
  1. per-|edge| bucket: is the 0.10-0.25 band positive on its own?
  2. the live rule (top-2 by |edge| per day, entry 5-95c, 100/contract) at
     thresholds 0.10/0.15/0.20/0.25, plus the trades a lower threshold ADDS.

    uv run python scripts/analysis/pm_edge_threshold_sweep.py [--contracts 100]
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes, kalshi_equivalent_bracket

BUCKETS = [(0.10, 0.15), (0.15, 0.20), (0.20, 0.25), (0.25, 0.35), (0.35, 1.01)]
THRESHOLDS = (0.10, 0.15, 0.20, 0.25)
MAX_PER_DAY = 2                      # live rail
ENTRY_LO, ENTRY_HI = 5, 95           # live rail


def fee_c(entry_c: float) -> float:  # == live_trade_polymarket.pm_taker_fee_cents / contract
    p = entry_c / 100.0
    return 6.0 * p * (1 - p)


def load(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.station_id, pt.target_date, pt.position, pt.entry_price_cents, pt.edge,
                   c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            JOIN observations o ON o.date = pt.target_date AND o.station_id = c.station_id
            WHERE c.platform = 'polymarket' AND pt.model_source LIKE '%%PM v2%%'
              AND pt.entry_price_cents IS NOT NULL
            ORDER BY c.station_id, pt.target_date, abs(pt.edge) DESC""")
        rows = cur.fetchall()
    out = []
    for st, td, pos, entry, edge, btype, lo, hi, obs in rows:
        yes = contract_resolved_yes(int(obs), kalshi_equivalent_bracket("polymarket", btype, lo, hi))
        won = yes if pos == "BUY_YES" else not yes
        net = ((100 - entry) if won else -entry) - fee_c(entry)
        out.append({"st": st, "td": td, "entry": int(entry), "edge": abs(edge), "won": won, "net": net})
    return out


def stats(trades, contracts):
    if not trades:
        return "n=0"
    n = len(trades)
    nets = [t["net"] for t in trades]
    m = statistics.mean(nets)
    sd = statistics.stdev(nets) if n > 1 else 0.0
    t = m / (sd / math.sqrt(n)) if sd else float("nan")
    wr = sum(t_["won"] for t_ in trades) / n
    return f"n={n:3d} win={wr:5.1%} net/c={m:+6.2f}c t={t:+5.2f} total=${sum(nets) * contracts / 100:+8.2f}"


def daily(trades, contracts):
    """Live-rule daily P&L series ($) and summary."""
    by_day = defaultdict(float)
    for t in trades:
        by_day[t["td"]] += t["net"] * contracts / 100
    v = list(by_day.values())
    if len(v) < 2:
        return f"days={len(v)} total=${sum(v):+.2f}"
    m, sd = statistics.mean(v), statistics.stdev(v)
    sharpe = m / sd * math.sqrt(252) if sd else float("nan")
    tstat = sharpe * math.sqrt(len(v) / 252) if sd else float("nan")
    ds = sorted(by_day)
    mid = ds[len(ds) // 2]
    h1, h2 = sum(by_day[d] for d in ds if d < mid), sum(by_day[d] for d in ds if d >= mid)
    return (f"days={len(v):2d} total=${sum(v):+8.2f} sharpe={sharpe:+5.2f} t={tstat:+5.2f} "
            f"halves={'++' if h1 > 0 and h2 > 0 else f'{h1:+.0f}/{h2:+.0f}'}")


def live_rule(trades, thr):
    """Top-MAX_PER_DAY by |edge| per (city, day) with |edge| >= thr and entry in bounds."""
    picked, seen = [], defaultdict(int)
    for t in trades:  # already sorted by city, day, |edge| desc
        k = (t["st"], t["td"])
        if t["edge"] >= thr and ENTRY_LO <= t["entry"] <= ENTRY_HI and seen[k] < MAX_PER_DAY:
            seen[k] += 1
            picked.append(t)
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contracts", type=int, default=100)
    a = ap.parse_args()
    trades = load(get_connection())
    cities = sorted({t["st"] for t in trades})
    print(f"PM v2 forward paper signals: {len(trades)} across {cities}\n")

    print("== 1. per-|edge| bucket, every logged signal (crossing entry, taker fee) ==")
    for lo, hi in BUCKETS:
        print(f"  [{lo:.2f},{hi:.2f})  {stats([t for t in trades if lo <= t['edge'] < hi], a.contracts)}")
    print("\n  per city, band [0.10,0.25) vs >=0.25:")
    for st in cities:
        ct = [t for t in trades if t["st"] == st]
        print(f"  {st}  band  {stats([t for t in ct if t['edge'] < 0.25], a.contracts)}")
        print(f"  {st}  >=25  {stats([t for t in ct if t['edge'] >= 0.25], a.contracts)}")

    print(f"\n== 2. live rule (top-{MAX_PER_DAY}/day by |edge|, entry {ENTRY_LO}-{ENTRY_HI}c, "
          f"{a.contracts}/contract) ==")
    for st in cities + ["ALL"]:
        ct = trades if st == "ALL" else [t for t in trades if t["st"] == st]
        base = live_rule(ct, 0.25)
        for thr in THRESHOLDS:
            p = live_rule(ct, thr)
            print(f"  {st:4s} thr={thr:.2f}  {stats(p, a.contracts)}  |  {daily(p, a.contracts)}")
        added = [t for t in live_rule(ct, 0.10) if t not in base]
        print(f"  {st:4s} ADDED by 0.25->0.10: {stats(added, a.contracts)}\n")
    return 0


if __name__ == "__main__":
    assert abs(fee_c(50) - 1.5) < 1e-9
    assert contract_resolved_yes(93, kalshi_equivalent_bracket("polymarket", "between", 92, 93))
    assert contract_resolved_yes(94, kalshi_equivalent_bracket("polymarket", "greater_than", 94, None))
    raise SystemExit(main())
