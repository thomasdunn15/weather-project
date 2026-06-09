"""Backtest using BLENDED probabilities — find optimal per-city edge threshold.

For each city:
  1. Fit blend on first 70% of paper_trades (chronological, no lookahead).
  2. Evaluate sim on last 30% (held-out) with BLENDED p.
  3. Sweep edge thresholds; report P&L, Sharpe, n_trades for each.
  4. Compare to RAW MODEL sim on same held-out set as a baseline.

Sim defaults: $50/trade, depth cap 500, post_inside_spread, $3000 starting,
Kalshi fees. Matches the React Backtest panel defaults.

Note: edge filter ranges differ between raw model (likely 0.15-0.30+) and
blend (likely 0.03-0.10) because blend pulls strongly toward market, so the
magnitude of |blend - market| is much smaller than |model - market|.
"""
from __future__ import annotations

import argparse
import math
import statistics

import numpy as np

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes
from weather_markets.blend import fit_blend, BlendFit


def _model_source(city_code, city_name):
    return ("EMOS combined 00Z (rolling 45d)" if city_code == "KNYC"
            else f"EMOS combined 00Z {city_name} (rolling 45d)")


def fetch_all_settled(city_code, city_name):
    """All settled paper_trades chronologically. Returns list of dicts."""
    ms = _model_source(city_code, city_name)
    rows = []
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
            rows.append({
                "date": td, "ticker": ticker, "pos": pos, "entry": int(entry),
                "p_model": float(mp), "p_market": (int(bid)+int(ask))/200.0,
                "bid": int(bid), "ask": int(ask),
                "bt": bt, "sl": sl, "sh": sh, "high": int(high),
            })
    return rows


def kalshi_fee_cents(entry):
    if entry <= 0 or entry >= 100: return 0
    p = entry / 100
    return max(1, math.ceil(0.07 * p * (1 - p) * 100))


def simulate(rows, *, prob_field, edge_field, edge_filter,
             amount_dollars=50.0, depth_cap=500, bankroll=3000.0,
             post_inside_spread=True):
    """Walk rows chronologically; bet when |edge_field| >= edge_filter.

    prob_field: which probability drives the trade decision ("p_model" or "p_blend")
    edge_field: which edge to filter on ("edge_model" or "edge_blend")
    """
    balance = bankroll; peak = bankroll
    max_dd = 0.0; max_dd_dollars = 0.0
    pnls = []; n_won = 0; n_filtered = 0
    for r in rows:
        if abs(r[edge_field]) < edge_filter: continue
        e = r["entry"]
        if post_inside_spread and r["ask"] > r["bid"] + 1:
            e = max(1, e - (r["ask"] - r["bid"] - 1))
        if e <= 0 or e >= 100: continue
        # Choose side based on the prob field's sign of edge vs market
        # For "raw model" mode: pos comes from paper_trades (already chosen)
        # For "blend" mode: re-derive pos from sign of edge_blend
        if edge_field == "edge_blend":
            won_yes = contract_resolved_yes(r["high"], {"bracket_type": r["bt"], "strike_low": r["sl"], "strike_high": r["sh"]})
            buy_yes = r["edge_blend"] > 0
            won = bool(won_yes) if buy_yes else not bool(won_yes)
        else:
            won_yes = contract_resolved_yes(r["high"], {"bracket_type": r["bt"], "strike_low": r["sl"], "strike_high": r["sh"]})
            won = bool(won_yes) if r["pos"] == "BUY_YES" else not bool(won_yes)
        contracts = min(depth_cap, int(amount_dollars / (e / 100)))
        if contracts < 1: continue
        fee = contracts * kalshi_fee_cents(e) / 100
        gross = contracts * ((100 - e) if won else -e) / 100
        pnl = gross - fee
        pnls.append(pnl); balance += pnl
        n_filtered += 1; n_won += int(won)
        peak = max(peak, balance)
        dd = (balance - peak) / peak * 100
        if dd < max_dd: max_dd = dd; max_dd_dollars = balance - peak
    if not pnls:
        return None
    m = statistics.mean(pnls); s = statistics.stdev(pnls) if len(pnls) > 1 else 0
    sharpe = (m / s) * math.sqrt(252) if s > 0 else 0
    return {
        "final": balance, "ret_pct": (balance/bankroll - 1)*100,
        "n": n_filtered, "win": n_won/n_filtered*100,
        "max_dd_pct": max_dd, "max_dd_dollars": max_dd_dollars,
        "sharpe": sharpe,
    }


def run_city(city_code, city_name, train_frac=0.7, verbose=True):
    rows = fetch_all_settled(city_code, city_name)
    if len(rows) < 200:
        if verbose: print(f"\n{city_name} ({city_code}): only {len(rows)} settled — skipping (need ≥200)")
        return None

    cutoff_idx = int(len(rows) * train_frac)
    train_rows = rows[:cutoff_idx]
    test_rows = rows[cutoff_idx:]

    # Fit blend on TRAIN ONLY (no lookahead)
    train_cutoff_date = train_rows[-1]["date"]
    fit = fit_blend(city_code, city_name, max_target_date=train_cutoff_date)
    if fit is None:
        if verbose: print(f"\n{city_name}: insufficient train data for blend fit")
        return None

    # Apply blend to test rows
    p_model_arr = np.array([r["p_model"] for r in test_rows])
    p_market_arr = np.array([r["p_market"] for r in test_rows])
    p_blend_arr = fit.predict(p_model_arr, p_market_arr)
    for i, r in enumerate(test_rows):
        r["p_blend"] = float(p_blend_arr[i])
        r["edge_model"] = r["p_model"] - r["p_market"]
        r["edge_blend"] = r["p_blend"] - r["p_market"]

    if verbose:
        print(f"\n{'='*84}\n{city_name} ({city_code}) — train n={len(train_rows)}, test n={len(test_rows)}")
        print(f"  Blend fit: α={fit.alpha:+.3f}  β_model={fit.beta_model:+.3f}  β_market={fit.beta_market:+.3f}  (mkt share {fit.market_share()*100:.0f}%)")

    # Raw-model baseline on test: sweep
    raw_grid = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    blend_grid = [0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]

    if verbose:
        print(f"\n  RAW MODEL on test set ($50/trade, cap 500, post_inside_spread):")
        print(f"  {'edge≥':>5} {'n':>5} {'final':>8} {'ret':>7} {'win':>5} {'maxDD':>8} {'sharpe':>7}")
    raw_results = []
    for f in raw_grid:
        r = simulate(test_rows, prob_field="p_model", edge_field="edge_model", edge_filter=f)
        if r:
            raw_results.append((f, r))
            if verbose: print(f"  {f*100:>4.0f}% {r['n']:>5} ${r['final']:>6.0f} {r['ret_pct']:>+6.1f}% {r['win']:>4.0f}% {r['max_dd_pct']:>+7.1f}% {r['sharpe']:>6.2f}")

    if verbose:
        print(f"\n  BLEND on test set (post_inside_spread):")
        print(f"  {'edge≥':>5} {'n':>5} {'final':>8} {'ret':>7} {'win':>5} {'maxDD':>8} {'sharpe':>7}")
    blend_results = []
    for f in blend_grid:
        r = simulate(test_rows, prob_field="p_blend", edge_field="edge_blend", edge_filter=f)
        if r:
            blend_results.append((f, r))
            if verbose: print(f"  {f*100:>4.0f}% {r['n']:>5} ${r['final']:>6.0f} {r['ret_pct']:>+6.1f}% {r['win']:>4.0f}% {r['max_dd_pct']:>+7.1f}% {r['sharpe']:>6.2f}")

    # Best by Sharpe with n>=20
    best_raw = max((x for x in raw_results if x[1]["n"] >= 20), key=lambda x: x[1]["sharpe"], default=None)
    best_blend = max((x for x in blend_results if x[1]["n"] >= 20), key=lambda x: x[1]["sharpe"], default=None)

    if verbose:
        if best_raw and best_blend:
            print(f"\n  BEST RAW   @ edge {best_raw[0]*100:.0f}%: final ${best_raw[1]['final']:.0f}, Sharpe {best_raw[1]['sharpe']:.2f}, n={best_raw[1]['n']}")
            print(f"  BEST BLEND @ edge {best_blend[0]*100:.0f}%: final ${best_blend[1]['final']:.0f}, Sharpe {best_blend[1]['sharpe']:.2f}, n={best_blend[1]['n']}")
            sharpe_lift = best_blend[1]['sharpe'] - best_raw[1]['sharpe']
            pnl_lift = best_blend[1]['final'] - best_raw[1]['final']
            print(f"  → BLEND lift: ΔSharpe {sharpe_lift:+.2f}, ΔFinal ${pnl_lift:+.0f}")

    return {"city": city_code, "fit": fit, "best_raw": best_raw, "best_blend": best_blend}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--city", default=None)
    args = p.parse_args()

    CITIES = [("KORD","Chicago"),("KMIA","Miami"),("KAUS","Austin"),
              ("KDEN","Denver"),("KLAX","Los Angeles"),("KNYC","NYC")]
    if args.city:
        CITIES = [(c, n) for c, n in CITIES if c == args.city]

    results = []
    for code, name in CITIES:
        r = run_city(code, name, verbose=True)
        if r: results.append(r)

    # Final summary
    print(f"\n{'='*84}\nSUMMARY — per-city best raw vs best blend on held-out test set")
    print(f"  {'City':<14} {'Raw best':>22} {'Blend best':>22} {'ΔSharpe':>8} {'ΔFinal':>9}")
    for r in results:
        if r['best_raw'] and r['best_blend']:
            br = r['best_raw']; bb = r['best_blend']
            raw_str = f"e≥{br[0]*100:.0f}% ${br[1]['final']:.0f} Sh{br[1]['sharpe']:.2f}"
            bl_str = f"e≥{bb[0]*100:.0f}% ${bb[1]['final']:.0f} Sh{bb[1]['sharpe']:.2f}"
            d_sh = bb[1]['sharpe'] - br[1]['sharpe']
            d_pl = bb[1]['final'] - br[1]['final']
            print(f"  {r['city']:<14} {raw_str:>22} {bl_str:>22} {d_sh:>+8.2f} ${d_pl:>+8.0f}")


if __name__ == "__main__":
    main()
