"""Fractional-Kelly sizing using BLENDED probabilities.

The conventional wisdom: Kelly bets blow up if your probabilities are
overconfident. Our raw model IS overconfident (it doesn't know what the
market knows). The blend is properly calibrated to the held-out outcomes,
so Kelly sized off blend should be safer AND grow faster than flat $/trade.

This script sweeps Kelly fractions (0.10, 0.25, 0.50) and stake caps (5%, 10%,
20% of bankroll) across cities, using BOTH raw model and blend probabilities.
Reports final balance, Sharpe, and Max DD on held-out test slice.

Usage:
    uv run python scripts/analysis/kelly_with_blend.py
    uv run python scripts/analysis/kelly_with_blend.py --city KORD
"""
from __future__ import annotations

import argparse
import math
import statistics

import numpy as np

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes
from weather_markets.blend import fit_blend


def _city_ms(city_code, city_name):
    if city_code == "KNYC": return "EMOS combined 00Z (rolling 45d)"
    return f"EMOS combined 00Z {city_name} (rolling 45d)"


def fetch_settled(city_code, city_name):
    ms = _city_ms(city_code, city_name)
    rows = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT pt.target_date, pt.position, pt.entry_price_cents, pt.model_prob_yes,
                      pt.market_yes_bid, pt.market_yes_ask, c.bracket_type, c.strike_low,
                      c.strike_high, o.high_temp_f
               FROM paper_trades pt
               JOIN contracts c ON c.ticker = pt.ticker
               LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                 WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
               WHERE pt.model_source = %s
                 AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
                 AND pt.model_prob_yes IS NOT NULL
               ORDER BY pt.target_date""", (ms,))
        for td, pos, entry, mp, bid, ask, bt, sl, sh, high in cur.fetchall():
            if high is None: continue
            mkt = (int(bid) + int(ask)) / 200.0
            won_yes = contract_resolved_yes(int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh})
            rows.append({"date": td, "pos": pos, "entry": int(entry), "p_model": float(mp),
                         "p_market": mkt, "bid": int(bid), "ask": int(ask),
                         "won_yes": bool(won_yes), "bt": bt, "sl": sl, "sh": sh})
    return rows


def kalshi_fee_cents(e):
    if e <= 0 or e >= 100: return 0
    p = e / 100
    return max(1, math.ceil(0.07 * p * (1 - p) * 100))


def kelly_fraction(p_win, entry_cents):
    if entry_cents <= 0 or entry_cents >= 100: return 0
    b = (100 - entry_cents) / entry_cents
    return max(0.0, p_win - (1 - p_win) / b)


def sim_kelly(rows, *, prob_field, edge_filter, kelly_frac, max_pct,
              bankroll=3000.0, post_inside_spread=True, blend_fit=None,
              depth_cap=500):
    balance = bankroll; peak = bankroll; max_dd = 0; max_dd_dollars = 0
    pnls = []; n = 0; n_won = 0
    for r in rows:
        if prob_field == "p_blend":
            if blend_fit is None: return None
            p = float(blend_fit.predict(r["p_model"], r["p_market"]))
        else:
            p = r["p_model"]
        edge = p - r["p_market"]
        if abs(edge) < edge_filter: continue
        buy_yes = edge > 0
        won = r["won_yes"] if buy_yes else (not r["won_yes"])
        cross = r["ask"] if buy_yes else (100 - r["bid"])
        entry = cross
        if post_inside_spread and r["ask"] > r["bid"] + 1:
            entry = max(1, cross - (r["ask"] - r["bid"] - 1))
        if entry <= 0 or entry >= 100: continue
        p_win = p if buy_yes else (1 - p)
        f = kelly_fraction(p_win, entry) * kelly_frac
        raw_stake = balance * f
        stake = min(raw_stake, balance * max_pct)
        contracts = int(stake / (entry / 100))
        if depth_cap: contracts = min(contracts, depth_cap)
        if contracts < 1: continue
        fee = contracts * kalshi_fee_cents(entry) / 100
        pnl = contracts * ((100 - entry) if won else -entry) / 100 - fee
        pnls.append(pnl); balance += pnl; n += 1; n_won += int(won)
        peak = max(peak, balance)
        dd = (balance - peak) / peak * 100
        if dd < max_dd: max_dd = dd; max_dd_dollars = balance - peak
    if not pnls: return None
    m = statistics.mean(pnls); s = statistics.stdev(pnls) if len(pnls) > 1 else 0
    sharpe = (m / s) * math.sqrt(252) if s > 0 else 0
    return {"final": balance, "ret_pct": (balance/bankroll - 1)*100,
            "n": n, "win_pct": n_won/n*100, "max_dd_pct": max_dd,
            "max_dd_dollars": max_dd_dollars, "sharpe": sharpe}


def sim_flat(rows, *, prob_field, edge_filter, amount=50.0, bankroll=3000.0,
             post_inside_spread=True, blend_fit=None, depth_cap=500):
    """Flat $/trade baseline for comparison."""
    balance = bankroll; peak = bankroll; max_dd = 0
    pnls = []; n = 0
    for r in rows:
        if prob_field == "p_blend":
            if blend_fit is None: return None
            p = float(blend_fit.predict(r["p_model"], r["p_market"]))
        else:
            p = r["p_model"]
        edge = p - r["p_market"]
        if abs(edge) < edge_filter: continue
        buy_yes = edge > 0
        won = r["won_yes"] if buy_yes else (not r["won_yes"])
        cross = r["ask"] if buy_yes else (100 - r["bid"])
        entry = cross
        if post_inside_spread and r["ask"] > r["bid"] + 1:
            entry = max(1, cross - (r["ask"] - r["bid"] - 1))
        if entry <= 0 or entry >= 100: continue
        contracts = int(amount / (entry / 100))
        if depth_cap: contracts = min(contracts, depth_cap)
        if contracts < 1: continue
        fee = contracts * kalshi_fee_cents(entry) / 100
        pnl = contracts * ((100 - entry) if won else -entry) / 100 - fee
        pnls.append(pnl); balance += pnl; n += 1
        peak = max(peak, balance)
        dd = (balance - peak) / peak * 100
        if dd < max_dd: max_dd = dd
    if not pnls: return None
    m = statistics.mean(pnls); s = statistics.stdev(pnls) if len(pnls) > 1 else 0
    sharpe = (m / s) * math.sqrt(252) if s > 0 else 0
    return {"final": balance, "n": n, "sharpe": sharpe, "max_dd_pct": max_dd}


def run_city(city_code, city_name, train_frac=0.7):
    rows = fetch_settled(city_code, city_name)
    if len(rows) < 200:
        print(f"\n{city_name}: only {len(rows)} settled; skip")
        return
    cut = int(len(rows) * train_frac)
    train = rows[:cut]; test = rows[cut:]
    train_cutoff = train[-1]["date"]
    fit = fit_blend(city_code, city_name, max_target_date=train_cutoff)

    print(f"\n{'='*100}\n{city_name} ({city_code}) — test n={len(test)}")

    # Baseline flat $50/trade for reference
    edge_filter_per_strat = {"p_model": 0.25, "p_blend": 0.05}
    print(f"\n  Reference flat $50/trade @ edge thresholds (model 25%, blend 5%):")
    for pf, label in [("p_model", "RAW"), ("p_blend", "BLEND")]:
        r = sim_flat(test, prob_field=pf, edge_filter=edge_filter_per_strat[pf], blend_fit=fit)
        if r:
            print(f"    {label:<6}  n={r['n']:>3}  final ${r['final']:>7.0f}  Sharpe {r['sharpe']:>5.2f}  maxDD {r['max_dd_pct']:>+6.1f}%")

    # Kelly sweep
    print(f"\n  KELLY sweep (kelly_frac × max_pct × strategy):")
    print(f"  {'strategy':<8} {'kf':>5} {'cap':>5} {'edge':>5} {'n':>4} {'final':>9} {'win%':>5} {'maxDD':>8} {'Sharpe':>7}")
    for pf in ["p_model", "p_blend"]:
        if pf == "p_blend" and fit is None: continue
        for kf in [0.10, 0.25, 0.50]:
            for max_pct in [0.05, 0.10, 0.20]:
                ef = edge_filter_per_strat[pf]
                r = sim_kelly(test, prob_field=pf, edge_filter=ef,
                              kelly_frac=kf, max_pct=max_pct, blend_fit=fit)
                if r is None or r['n'] < 10: continue
                label = "RAW" if pf == "p_model" else "BLEND"
                print(f"  {label:<8} {kf:>5} {max_pct*100:>4.0f}% {ef*100:>4.0f}% {r['n']:>4} ${r['final']:>7.0f} {r['win_pct']:>4.0f}% {r['max_dd_pct']:>+7.1f}% {r['sharpe']:>6.2f}")


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
