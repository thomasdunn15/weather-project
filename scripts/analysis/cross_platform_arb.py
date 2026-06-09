"""Cross-platform arb scaffolding — Kalshi KORD ↔ Polymarket KMDW.

Two markets, two stations (O'Hare vs Midway), ~14 miles apart. Observed daily
highs correlate strongly but not perfectly. When the two market prices for
"high temp ≥ X°F" disagree by more than the expected KORD-KMDW spread
distribution, there's potential arb.

This script computes:
  1. KORD ↔ KMDW observation correlation + distribution of (KORD - KMDW)°F
  2. What probability the historical-spread distribution puts on "KMDW ≥ X and KORD < X"
     (i.e., the natural divergence rate for "same outcome" bets)
  3. Current cross-platform price comparison for matching bracket pairs today
     (Kalshi B83.5 → Polymarket "84°F bracket" etc.)
  4. Arb detection rule: when |Kalshi P(KORD≥X) − Polymarket P(KMDW≥X)| > threshold,
     flag a candidate.

This is NOT a trading bot — it's the analysis to validate the strategy exists
before we wire it into live trading. Run periodically to monitor the arb rate.

Usage:
    uv run python scripts/analysis/cross_platform_arb.py
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np

from weather_markets.db import get_connection


def fetch_kord_kmdw_obs():
    """Returns list of (date, KORD high, KMDW high)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT o1.date, o1.high_temp_f, o2.high_temp_f
            FROM observations o1
            JOIN observations o2 ON o1.date = o2.date
            WHERE o1.station_id='KORD' AND o2.station_id='KMDW'
              AND o1.high_temp_f IS NOT NULL AND o2.high_temp_f IS NOT NULL
            ORDER BY o1.date
        """)
        return cur.fetchall()


def correlation_analysis():
    """Step 1: characterize the KORD-KMDW historical relationship."""
    rows = fetch_kord_kmdw_obs()
    if not rows:
        print("No KORD-KMDW common observations.")
        return
    diffs = [float(k) - float(m) for _, k, m in rows]
    kord_vals = np.array([float(k) for _, k, _ in rows])
    kmdw_vals = np.array([float(m) for _, _, m in rows])

    n = len(rows)
    mean_diff = statistics.mean(diffs)
    std_diff = statistics.stdev(diffs)
    abs_mean = statistics.mean(abs(d) for d in diffs)
    pct_within_1 = sum(abs(d) <= 1 for d in diffs) / n * 100
    pct_within_2 = sum(abs(d) <= 2 for d in diffs) / n * 100
    pct_within_3 = sum(abs(d) <= 3 for d in diffs) / n * 100
    pearson = np.corrcoef(kord_vals, kmdw_vals)[0, 1]

    print(f"=== KORD ↔ KMDW historical observation relationship (n={n}) ===")
    print(f"  Pearson correlation:   {pearson:.4f}")
    print(f"  Mean (KORD − KMDW):    {mean_diff:+.2f}°F   (positive = O'Hare hotter on average)")
    print(f"  Std (KORD − KMDW):     {std_diff:.2f}°F")
    print(f"  Mean |KORD − KMDW|:    {abs_mean:.2f}°F")
    print(f"  P(|KORD − KMDW| ≤ 1°): {pct_within_1:.0f}%")
    print(f"  P(|KORD − KMDW| ≤ 2°): {pct_within_2:.0f}%")
    print(f"  P(|KORD − KMDW| ≤ 3°): {pct_within_3:.0f}%")

    # Worst-case divergences: dates where they disagreed by ≥5°F
    big_misses = sorted([(d, k, m, k - m) for (d, k, m) in rows if abs(k - m) >= 5], key=lambda x: -abs(x[3]))
    if big_misses:
        print(f"\n  Largest divergences (≥5°F gap): {len(big_misses)} days")
        for d, k, m, diff in big_misses[:5]:
            print(f"    {d}  KORD={k:.0f}°F  KMDW={m:.0f}°F  Δ={diff:+.0f}°F")
    return {"mean_diff": mean_diff, "std_diff": std_diff, "corr": pearson, "n": n}


def cross_platform_today():
    """Step 3: today's matching brackets across platforms."""
    today = date.today()
    with get_connection() as conn, conn.cursor() as cur:
        # Kalshi KORD high contracts for today
        cur.execute("""
            SELECT c.ticker, c.bracket_type, c.strike_low, c.strike_high,
                   p.yes_bid, p.yes_ask, p.snapshot_at
            FROM contracts c
            LEFT JOIN LATERAL (
                SELECT yes_bid, yes_ask, snapshot_at FROM prices
                WHERE ticker=c.ticker ORDER BY snapshot_at DESC LIMIT 1
            ) p ON true
            WHERE c.station_id='KORD' AND c.target_date=%s AND c.platform='kalshi'
              AND c.ticker LIKE 'KXHIGH%%'
            ORDER BY c.strike_low NULLS FIRST, c.strike_high NULLS LAST
        """, (today,))
        kalshi = cur.fetchall()
        # Polymarket KMDW high contracts for today
        cur.execute("""
            SELECT c.ticker, c.bracket_type, c.strike_low, c.strike_high,
                   p.yes_bid, p.yes_ask, p.snapshot_at
            FROM contracts c
            LEFT JOIN LATERAL (
                SELECT yes_bid, yes_ask, snapshot_at FROM prices
                WHERE ticker=c.ticker ORDER BY snapshot_at DESC LIMIT 1
            ) p ON true
            WHERE c.station_id='KMDW' AND c.target_date=%s AND c.platform='polymarket'
            ORDER BY c.strike_low NULLS FIRST, c.strike_high NULLS LAST
        """, (today,))
        poly = cur.fetchall()

    print(f"\n=== Today ({today}) cross-platform bracket comparison ===")
    print(f"  Kalshi KORD high brackets:    {len(kalshi)}")
    print(f"  Polymarket KMDW high brackets: {len(poly)}")

    if not kalshi or not poly:
        print("  Need both platforms with contracts today to compare. Skipping match.")
        return

    # Build cumulative P(high ≥ X) curves for each platform.
    # Kalshi: brackets are 2°F inclusive (e.g., 80-81). Polymarket: 1°F inclusive
    # ("80°F" = exactly 80). Build a step function P(high ≥ X) for each platform
    # from these brackets — we can then compare at integer X for both.
    def cumulative_above(platform_rows, polymarket=False):
        """Returns {threshold_F: P_yes_above_threshold} from the listed brackets.
        For polymarket 1°F brackets and kalshi 2°F brackets the resolution differs."""
        # Sort by bracket_type then strike — between brackets cover the body,
        # less_than covers the bottom tail, greater_than the top tail.
        cumul = {}
        for tk, bt, sl, sh, bid, ask, ts in platform_rows:
            if bid is None or ask is None: continue
            mid = (int(bid) + int(ask)) / 200.0
            if bt == "greater_than":
                # P(high > sl) = P(high ≥ sl+1)
                cumul[int(sl) + 1] = mid
            elif bt == "less_than":
                # P(high < sh) is the COMPLEMENT — P(high ≥ sh) = 1 - mid
                cumul[int(sh)] = 1 - mid
            else:  # between [sl, sh] inclusive (Kalshi) or just sl (Polymarket 1°F)
                # For Kalshi B85.5 = [85,86]: this bracket says P(high in {85,86}).
                # P(high ≥ 85) = sum of all brackets with low ≥ 85 → tracked elsewhere.
                # We'll just record the bracket itself for reference.
                cumul[("between", int(sl), int(sh))] = mid
        return cumul

    k_cum = cumulative_above(kalshi)
    p_cum = cumulative_above(poly)
    print(f"\n  Kalshi cumulative P(KORD high ≥ X):")
    for k, v in sorted([(k, v) for k, v in k_cum.items() if isinstance(k, int)]):
        print(f"    ≥{k}°F : {v*100:>5.1f}%")
    print(f"\n  Polymarket cumulative P(KMDW high ≥ X):")
    for k, v in sorted([(k, v) for k, v in p_cum.items() if isinstance(k, int)]):
        print(f"    ≥{k}°F : {v*100:>5.1f}%")

    # Compare at matching thresholds
    common = sorted(set(k for k in k_cum if isinstance(k, int)) & set(p_cum.keys()))
    if common:
        print(f"\n  ARB CANDIDATES — P(KORD ≥ X) vs P(KMDW ≥ X), where X has both contracts:")
        print(f"    {'X':>3} {'Kalshi':>8} {'Poly':>8} {'gap':>8} {'arb?':>6}")
        for x in common:
            kp = k_cum.get(x); pp = p_cum.get(x)
            if kp is None or pp is None: continue
            gap = kp - pp
            arb = "✓" if abs(gap) >= 0.10 else ""    # 10% gap threshold for now
            print(f"    {x:>3}°F  {kp*100:>6.1f}%  {pp*100:>6.1f}%  {gap*100:>+6.1f}%  {arb:>6}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args = p.parse_args()

    print(f"{'='*72}\nCross-platform arb scaffolding — KORD ↔ KMDW\n{'='*72}\n")
    correlation_analysis()
    cross_platform_today()


if __name__ == "__main__":
    main()
