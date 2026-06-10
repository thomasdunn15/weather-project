"""Walk-the-book execution backtest — SYNTHETIC depth.

We don't have historical order-book depth (only top-of-book bid/ask snapshots),
so this backtest uses parametric assumptions about how depth grows as you walk
up the ask side. Three scenarios:
  THIN   — small books (~200 contracts within 5¢ of touch)
  MEDIUM — typical Chicago (~500 contracts within 5¢)
  THICK  — good days (~1500 contracts within 5¢)

For each historical signal, simulates walking the book:
  - Start at displayed ask
  - Buy at each price level up to (fair_value − min_marginal_edge × 100)
  - Cap total fill at target_contracts
  - Compute resulting average fill price and per-contract PnL

Compare to baselines:
  - SINGLE: take 500 contracts at the displayed ask (current live behavior)
  - SINGLE-CAP: take min(target, top-of-book qty assumption) at ask
  - WALK:   parameterized walk-the-book strategy

Usage:
    uv run python scripts/analysis/walk_book_synthetic.py
    uv run python scripts/analysis/walk_book_synthetic.py --min-marginal-edge 0.05
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import namedtuple

import numpy as np

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes
from weather_markets.blend import fit_blend


# --- Synthetic depth profiles ---
# depth_at_offset(cents_above_ask) returns INCREMENTAL contracts at that level.
DEPTH_PROFILES = {
    "thin": [
        (0, 50), (1, 30), (2, 50), (3, 50), (5, 100), (8, 150),
        (12, 200), (18, 300), (25, 500), (35, 800), (50, 1500),
    ],
    "medium": [
        (0, 100), (1, 80), (2, 100), (3, 100), (5, 200), (8, 300),
        (12, 500), (18, 800), (25, 1500), (35, 2500), (50, 5000),
    ],
    "thick": [
        (0, 250), (1, 200), (2, 300), (3, 300), (5, 500), (8, 800),
        (12, 1500), (18, 2500), (25, 5000), (35, 10000), (50, 20000),
    ],
}


def kalshi_fee_cents(entry):
    if entry <= 0 or entry >= 100: return 0
    p = entry / 100
    return max(1, math.ceil(0.07 * p * (1 - p) * 100))


Fill = namedtuple("Fill", ["price_cents", "qty"])


def walk_book(displayed_ask, target_contracts, max_price_cents, profile):
    """Return list of Fills as we walk up the synthetic book.
    Stops when target met OR next price exceeds max_price_cents."""
    fills = []
    remaining = target_contracts
    for offset, qty_at_level in profile:
        level_price = displayed_ask + offset
        if level_price > max_price_cents: break
        if level_price >= 100: break
        fill_qty = min(remaining, qty_at_level)
        if fill_qty <= 0: continue
        fills.append(Fill(level_price, fill_qty))
        remaining -= fill_qty
        if remaining <= 0: break
    return fills


def fills_to_pnl(fills, won, displayed_ask):
    """Returns (total_contracts, weighted_avg_price, total_pnl, total_fee)."""
    if not fills: return 0, 0, 0, 0
    total_qty = sum(f.qty for f in fills)
    total_cost = sum(f.qty * f.price_cents for f in fills)
    total_fee = sum(f.qty * kalshi_fee_cents(f.price_cents) for f in fills)
    avg_price = total_cost / total_qty
    if won:
        gross = sum(f.qty * (100 - f.price_cents) for f in fills)
    else:
        gross = -sum(f.qty * f.price_cents for f in fills)
    return total_qty, avg_price, (gross - total_fee) / 100.0, total_fee / 100.0


def fetch_kord_union_signals(min_raw_edge=0.25, min_blend_edge=0.10):
    """Pull KORD paper_trades that pass union filter, with their outcomes."""
    ms = "EMOS combined_hrrr 00Z Chicago (rolling 45d)"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT pt.target_date, pt.position, pt.model_prob_yes,
                   pt.market_yes_bid, pt.market_yes_ask,
                   c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
            FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
            LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
              WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
            WHERE pt.model_source = %s
              AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
            ORDER BY pt.target_date""", (ms,))
        all_rows = cur.fetchall()
    fit = fit_blend("KORD", "Chicago", paper_model_source=ms)

    signals = []
    for td, pos, mp, bid, ask, bt, sl, sh, high in all_rows:
        if high is None: continue
        mp = float(mp); mkt = (int(bid)+int(ask))/200
        bp = float(fit.predict(mp, mkt))
        raw_e = mp - mkt; blend_e = bp - mkt
        if not (abs(raw_e) >= min_raw_edge or abs(blend_e) >= min_blend_edge):
            continue
        buy_yes = (raw_e > 0) if abs(raw_e) >= min_raw_edge else (blend_e > 0)
        # Fair value depends on which side we're taking
        # For BUY_YES: fair_value of YES = model probability (or blend prob)
        # For BUY_NO:  fair_value of NO  = 1 - model probability
        fair_yes = mp  # use raw model as fair-value reference
        fair_no = 1 - mp
        won_yes = bool(contract_resolved_yes(int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh}))
        won = won_yes if buy_yes else not won_yes
        # Displayed ask we'll buy from depends on side:
        if buy_yes:
            displayed_ask = int(ask)
            fair_cents = fair_yes * 100
        else:
            displayed_ask = 100 - int(bid)  # buying NO at "ask" = 100 - YES bid
            fair_cents = fair_no * 100
        signals.append({
            "date": td, "buy_yes": buy_yes, "won": won,
            "displayed_ask": displayed_ask, "fair_cents": fair_cents,
            "raw_edge": raw_e, "blend_edge": blend_e,
        })
    return signals, fit


def run_strategy(signals, label, *, target_contracts, min_marginal_edge_cents, profile, bankroll=3000):
    """Returns dict of aggregate stats."""
    total_pnl = 0; total_qty = 0; total_fee = 0
    won_count = 0; n_trades = 0
    pnls_per_trade = []
    fills_per_trade = []
    for s in signals:
        max_price = max(0, s["fair_cents"] - min_marginal_edge_cents)
        fills = walk_book(s["displayed_ask"], target_contracts, max_price, profile)
        if not fills: continue
        qty, avg_price, pnl, fee = fills_to_pnl(fills, s["won"], s["displayed_ask"])
        if qty == 0: continue
        n_trades += 1
        total_qty += qty
        total_fee += fee
        total_pnl += pnl
        if s["won"]: won_count += 1
        pnls_per_trade.append(pnl)
        fills_per_trade.append(qty)
    if not pnls_per_trade:
        return None
    m = statistics.mean(pnls_per_trade); sd = statistics.stdev(pnls_per_trade) if len(pnls_per_trade) > 1 else 0
    sharpe = (m / sd) * math.sqrt(252) if sd > 0 else 0
    return {
        "label": label,
        "n_trades": n_trades,
        "win_pct": won_count / n_trades * 100,
        "total_qty": total_qty,
        "avg_qty_per_trade": total_qty / n_trades,
        "total_pnl": total_pnl,
        "total_fee": total_fee,
        "final": bankroll + total_pnl,
        "sharpe": sharpe,
        "mean_per_trade": m, "std_per_trade": sd,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", type=int, default=2000, help="Target contracts per trade")
    p.add_argument("--min-marginal-edge", type=float, default=0.10,
                   help="Stop walking when next contract's edge < this (decimal, 0.10 = 10%)")
    args = p.parse_args()

    target = args.target
    min_edge_cents = args.min_marginal_edge * 100

    signals, fit = fetch_kord_union_signals()
    print(f"KORD union signals (raw≥25% OR blend≥10%): n = {len(signals)} historical trades\n")
    print(f"Walk-the-book sim: target={target} contracts, stop when marginal edge < {args.min_marginal_edge:.0%}\n")

    # Baseline: SINGLE-PRICE limit order at displayed ask (current live behavior)
    # We model this as a depth-of-1 'profile' that buys 500 contracts at the ask
    single_profile = [(0, 500)]
    base = run_strategy(signals, f"single-price (500 @ ask)", target_contracts=500,
                        min_marginal_edge_cents=min_edge_cents, profile=single_profile)
    if base:
        print(f"BASELINE  {base['label']}")
        print(f"   n_trades={base['n_trades']:>4}  avg_qty={base['avg_qty_per_trade']:>6.0f}  total_qty={base['total_qty']:>7,}  "
              f"final ${base['final']:>7,.0f}  Sharpe {base['sharpe']:>5.2f}  per-trade ${base['mean_per_trade']:>+7.0f}")

    print()
    print("WALK-THE-BOOK per depth profile:")
    for profile_name, profile in DEPTH_PROFILES.items():
        r = run_strategy(signals, f"walk · {profile_name} book", target_contracts=target,
                         min_marginal_edge_cents=min_edge_cents, profile=profile)
        if r:
            uplift = r['total_pnl'] - base['total_pnl']
            avg_fill_pct = r['avg_qty_per_trade'] / target * 100
            print(f"   {profile_name:<8} avg_qty={r['avg_qty_per_trade']:>6.0f} ({avg_fill_pct:.0f}% of target)  "
                  f"total_qty={r['total_qty']:>7,}  final ${r['final']:>7,.0f}  Sharpe {r['sharpe']:>5.2f}  "
                  f"vs baseline ${uplift:>+8,.0f}")

    print()
    print(f"Notes:")
    print(f"  - Single-price baseline: 500 contracts at displayed ask, every trade (current live behavior)")
    print(f"  - Walk-the-book: starts at ask, walks up at synthetic depth until target qty filled or marginal edge < {args.min_marginal_edge:.0%}")
    print(f"  - The TRUE answer depends on Kalshi's actual depth. Run with --target and --min-marginal-edge to test")
    print(f"    a range; current Chicago KORD depth is probably between 'thin' and 'medium' on most days.")


if __name__ == "__main__":
    main()
