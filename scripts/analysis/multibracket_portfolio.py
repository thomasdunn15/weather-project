"""Multi-bracket portfolio sizing analysis.

Today's strategy bets a single bracket per day per city (the one with the
biggest |edge|). This analysis tests betting MULTIPLE high-edge brackets
simultaneously, with allocation proportional to |edge|. The expected payoff
is similar but variance per day should drop — Sharpe ↑.

Three sizing modes compared:
  - SINGLE   — bet only the highest-|edge| bracket (status quo)
  - SPREAD-K — bet top K brackets, equal-dollar across them
  - WEIGHTED — bet top K brackets, dollar allocation ∝ |edge|

For each (city, mode, K), simulate over the held-out test slice using both
raw model and blend probabilities. Report final balance + Sharpe + Max DD.

Usage:
    uv run python scripts/analysis/multibracket_portfolio.py
    uv run python scripts/analysis/multibracket_portfolio.py --city KORD
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict

import numpy as np

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes
from weather_markets.blend import fit_blend


def _city_model_source(city_code, city_name):
    if city_code == "KNYC":
        return "EMOS combined 00Z (rolling 45d)"
    return f"EMOS combined 00Z {city_name} (rolling 45d)"


def fetch_settled_grouped_by_date(city_code, city_name):
    """Returns {target_date: [trade_dict, ...]} for all settled paper_trades."""
    ms = _city_model_source(city_code, city_name)
    by_date = defaultdict(list)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT pt.target_date, pt.ticker, pt.position, pt.entry_price_cents,
                      pt.model_prob_yes, pt.market_yes_bid, pt.market_yes_ask,
                      c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
               FROM paper_trades pt
               JOIN contracts c ON c.ticker = pt.ticker
               LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                 WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
               WHERE pt.model_source = %s
                 AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
                 AND pt.model_prob_yes IS NOT NULL
               ORDER BY pt.target_date""", (ms,))
        for td, ticker, pos, entry, mp, bid, ask, bt, sl, sh, high in cur.fetchall():
            if high is None:
                continue
            mkt = (int(bid) + int(ask)) / 200.0
            won_yes = contract_resolved_yes(int(high), {"bracket_type": bt,
                                                          "strike_low": sl,
                                                          "strike_high": sh})
            by_date[td].append({
                "ticker": ticker, "pos": pos, "entry": int(entry),
                "p_model": float(mp), "p_market": mkt,
                "bid": int(bid), "ask": int(ask),
                "won_yes": bool(won_yes),
            })
    return dict(sorted(by_date.items()))


def kalshi_fee_cents(entry):
    if entry <= 0 or entry >= 100: return 0
    p = entry / 100
    return max(1, math.ceil(0.07 * p * (1 - p) * 100))


def trade_pnl(entry_cents, contracts, won):
    """Net P&L in dollars: gross - Kalshi fees."""
    fee = contracts * kalshi_fee_cents(entry_cents) / 100
    gross = contracts * ((100 - entry_cents) if won else -entry_cents) / 100
    return gross - fee


def simulate_strategy(days_dict, *, sizing_mode, K, edge_filter, prob_field,
                      amount_per_day=50.0, depth_cap=500, bankroll=3000.0,
                      blend_fit=None, post_inside_spread=True):
    """sizing_mode: 'single', 'spread', or 'weighted'.
       K: number of brackets to consider per day (if mode != single).
       amount_per_day: total dollars deployed per day (split across brackets in spread/weighted).
       For 'single' mode, the full amount_per_day goes to the one chosen bracket.
    """
    balance = bankroll; peak = bankroll; max_dd = 0; max_dd_dollars = 0
    pnls_per_day = []   # one row per day = sum of all bracket P&Ls that day
    n_days_traded = 0
    for td, trades in days_dict.items():
        # Compute current-strategy edge for each candidate
        candidates = []
        for t in trades:
            if prob_field == "p_blend":
                if blend_fit is None: continue
                p = float(blend_fit.predict(t["p_model"], t["p_market"]))
            else:
                p = t["p_model"]
            edge = p - t["p_market"]
            if abs(edge) < edge_filter: continue
            # Determine side from blended-edge sign (in blend mode this can flip)
            buy_yes = edge > 0
            won = t["won_yes"] if buy_yes else (not t["won_yes"])
            cross = t["ask"] if buy_yes else (100 - t["bid"])
            entry = cross
            if post_inside_spread:
                spread = t["ask"] - t["bid"]
                if spread > 1:
                    entry = max(1, cross - (spread - 1))
            if entry <= 0 or entry >= 100: continue
            candidates.append({"ticker": t["ticker"], "abs_edge": abs(edge),
                                "entry": entry, "won": won})

        if not candidates: continue
        # Choose how many to bet on
        candidates.sort(key=lambda c: -c["abs_edge"])
        if sizing_mode == "single":
            chosen = candidates[:1]
            weights = [1.0]
        else:
            chosen = candidates[:K]
            if sizing_mode == "spread":
                weights = [1.0 / len(chosen)] * len(chosen)
            elif sizing_mode == "weighted":
                total = sum(c["abs_edge"] for c in chosen)
                weights = [c["abs_edge"] / total for c in chosen]
            else:
                raise ValueError(sizing_mode)

        # Compute P&L for each chosen bracket
        day_pnl = 0
        n_filled = 0
        for c, w in zip(chosen, weights):
            stake = amount_per_day * w
            contracts = min(depth_cap, int(stake / (c["entry"] / 100)))
            if contracts < 1: continue
            day_pnl += trade_pnl(c["entry"], contracts, c["won"])
            n_filled += 1
        if n_filled == 0: continue
        pnls_per_day.append(day_pnl)
        balance += day_pnl
        n_days_traded += 1
        peak = max(peak, balance)
        dd = (balance - peak) / peak * 100
        if dd < max_dd: max_dd = dd; max_dd_dollars = balance - peak

    if not pnls_per_day:
        return None
    m = statistics.mean(pnls_per_day)
    s = statistics.stdev(pnls_per_day) if len(pnls_per_day) > 1 else 0
    sharpe = (m / s) * math.sqrt(252) if s > 0 else 0
    return {
        "final": balance, "ret_pct": (balance / bankroll - 1) * 100,
        "n_days": n_days_traded, "max_dd_pct": max_dd, "max_dd_dollars": max_dd_dollars,
        "sharpe": sharpe, "mean_daily_pnl": m, "std_daily_pnl": s,
    }


def run_city(city_code, city_name, train_frac=0.7):
    days = fetch_settled_grouped_by_date(city_code, city_name)
    if len(days) < 60:
        print(f"\n{city_name}: only {len(days)} days; skip")
        return
    # Split chronologically
    dates_sorted = list(days.keys())
    cut = int(len(dates_sorted) * train_frac)
    train_dates = dates_sorted[:cut]
    test_dates = dates_sorted[cut:]
    train_days = {d: days[d] for d in train_dates}
    test_days = {d: days[d] for d in test_dates}

    fit = fit_blend(city_code, city_name, max_target_date=train_dates[-1])

    print(f"\n{'='*88}\n{city_name} ({city_code}) — test days={len(test_days)}, train days={len(train_days)}")
    if fit:
        print(f"  Blend fit: α={fit.alpha:+.3f} β_m={fit.beta_model:+.3f} β_mkt={fit.beta_market:+.3f} (mkt {fit.market_share()*100:.0f}%)")

    # Per (strategy, K, mode): pick best edge filter by Sharpe
    edge_grids = {"p_model": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
                  "p_blend": [0.02, 0.03, 0.05, 0.07, 0.10, 0.15]}
    modes = [("single", 1), ("spread", 2), ("spread", 3), ("weighted", 2), ("weighted", 3)]

    for prob_field, label in [("p_model", "RAW MODEL"), ("p_blend", "BLEND")]:
        if prob_field == "p_blend" and fit is None: continue
        print(f"\n  {label}")
        print(f"  {'mode':<14} {'best edge':>10} {'days':>5} {'final':>9} {'ret':>7} {'maxDD':>8} {'Sharpe':>8}")
        for mode, K in modes:
            best = None
            for ef in edge_grids[prob_field]:
                r = simulate_strategy(test_days, sizing_mode=mode, K=K, edge_filter=ef,
                                       prob_field=prob_field, blend_fit=fit)
                if r and r["n_days"] >= 15:
                    if best is None or r["sharpe"] > best[1]["sharpe"]:
                        best = (ef, r)
            if best:
                label2 = f"{mode}@K={K}" if mode != "single" else "single"
                print(f"  {label2:<14} {best[0]*100:>9.0f}% {best[1]['n_days']:>5} ${best[1]['final']:>7.0f} {best[1]['ret_pct']:>+6.1f}% {best[1]['max_dd_pct']:>+7.1f}% {best[1]['sharpe']:>7.2f}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--city", default=None)
    args = p.parse_args()

    CITIES = [("KORD","Chicago"),("KMIA","Miami"),("KAUS","Austin"),
              ("KDEN","Denver"),("KLAX","Los Angeles"),("KNYC","NYC")]
    if args.city:
        CITIES = [(c,n) for c,n in CITIES if c == args.city]
    for code, name in CITIES:
        run_city(code, name)


if __name__ == "__main__":
    main()
