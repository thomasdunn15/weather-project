#!/usr/bin/env python3
"""Dallas (KDFW) paper-watchlist tracker — read-only, paper_trades only.

WHY THIS EXISTS
---------------
The per-city diagnostic (docs/research/md/2026-06-20-per-city-strategy-diagnostic.md)
found Dallas is NOT a robust-edge city: at the production baseline (|edge|>=0.10)
it loses (-$7.18, Sharpe -1.93) and it is negative in BOTH history halves. Its only
positive signal is a single walk-forward fold — combined, T0.25, both, 10-90c —
worth +$3.17 on n=27 (+11.74c/trade, OOS Sharpe 4.52). That clears the deploy bar
(OOS walk-forward Sharpe > 2.5) but on a tiny, almost-certainly-noisy sample that the
study itself flags as a "tuned OOS blip, not trustworthy."

So Dallas does not go live. It goes on a PAPER WATCHLIST: keep accumulating honest,
forward out-of-sample trades under a fixed rule and re-check whether the OOS edge
persists as n grows. Promotion to live requires the deploy bar held on a meaningfully
larger forward sample — not the n=27 in-sample-selected blip.

WHAT IT TRACKS
--------------
The KORD-style UNION rule at raw threshold 0.25 (the watchlist rule the operator
asked for): fire if |raw_edge| >= 0.25 OR |blend_edge| >= 0.10.
  - raw side    = sign(edge)         (BUY_YES if edge>0 else BUY_NO)
  - blend side  = sign(blend_edge)
  - when both fire they agree (verified on live KORD); raw-only -> raw side;
    blend-only -> blend side.

The blend leg is reconstructed here with the production WALK-FORWARD blend
(weather_markets.blend.walkforward_blends): one fit per date trained only on
strictly-earlier settled data, so it is lookahead-free and matches how live trading
would have blended. NOTE: the daily paper cron does not currently log a Dallas blend
variant (get_blend needs >=100 settled and Dallas never had a logged blend row), so
this tracker fits the blend itself. The underlying RAW Dallas signal is logged daily
by scripts/paper_trade_log.py, which is how forward OOS samples accumulate with no
cron change.

P&L mirrors the canonical model exactly (1 contract/signal, like the diagnostic):
  gross = (100 - entry) if the chosen side won else -entry
  fee   = kalshi_fee_cents(entry)   # 0.07 * p*(1-p), rounded up, min 1c
  net   = gross - fee
Settlement via weather_markets.evaluation.contract_resolved_yes on the integer high.

This is a NON-trading, read-only monitor. It changes no live config and places no
orders. Run it whenever you want a read on the watchlist:

    uv run python scripts/analysis/dallas_watchlist.py
    uv run python scripts/analysis/dallas_watchlist.py --since 2026-06-21 --json /tmp/dfw_watch.json
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date
from statistics import mean, stdev

from weather_markets.db import get_connection
from weather_markets.blend import walkforward_blends, apply_blend
from weather_markets.evaluation import contract_resolved_yes

# --- watchlist constants -----------------------------------------------------
STATION = "KDFW"
CITY = "Dallas"
PAPER_MODEL_SOURCE = "EMOS combined 00Z Dallas (rolling 45d)"
RAW_THRESHOLD = 0.25        # union raw leg (the watchlist rule: T=0.25)
BLEND_THRESHOLD = 0.10      # union blend leg (KORD value)
WATCHLIST_START = date(2026, 6, 21)   # forward-OOS clock starts here
DEPLOY_BAR = 2.5            # walk-forward OOS Sharpe required to graduate to live

# Documented historical walk-forward OOS (per-city diagnostic, 2026-06-20) — context
# only; the verdict rests on the FORWARD sample this tracker accumulates.
DIAG_OOS = {"params": "combined, T0.25, both, 10-90c", "profit": 3.17, "n": 27,
            "cents_per_trade": 11.74, "sharpe": 4.52,
            "baseline": "-$7.18 / Sharpe -1.93, both halves negative"}


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Canonical Kalshi entry fee in cents (mirrors dashboard/sim_python.py)."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


def load_signals(conn):
    """All settled Dallas raw signals joined to strikes + observed high."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pt.target_date, pt.ticker, pt.model_prob_yes, pt.market_mid_prob,
                   pt.market_yes_bid, pt.market_yes_ask, pt.edge, pt.position,
                   pt.entry_price_cents, c.bracket_type, c.strike_low, c.strike_high,
                   o.high_temp_f
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            JOIN observations o ON o.date = pt.target_date AND o.station_id = c.station_id
            WHERE pt.model_source = %s AND o.high_temp_f IS NOT NULL
            ORDER BY pt.target_date, pt.ticker
            """,
            (PAPER_MODEL_SOURCE,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def entry_for_side(row: dict, side: str) -> int | None:
    """Entry price (cents) for the chosen side. Uses the logged entry when the
    union side matches the raw-logged side; otherwise derives from the quote
    (BUY_YES -> yes_ask, BUY_NO -> 100 - yes_bid) for the rare blend-only flip."""
    if side == row["position"]:
        return int(row["entry_price_cents"])
    bid, ask = row["market_yes_bid"], row["market_yes_ask"]
    if side == "BUY_YES":
        return int(ask) if ask is not None else None
    return (100 - int(bid)) if bid is not None else None


def evaluate(rows, raw_t, blend_t):
    """Apply the union rule; return list of fired trades with net cents + provenance."""
    blends = walkforward_blends(STATION, CITY, PAPER_MODEL_SOURCE)
    trades = []
    n_dates_with_fit = 0
    seen_dates = set()
    for r in rows:
        d = r["target_date"]
        if d not in seen_dates:
            seen_dates.add(d)
            if blends.get(d) is not None:
                n_dates_with_fit += 1

        raw_edge = float(r["edge"])
        raw_fires = abs(raw_edge) >= raw_t

        blend_edge = None
        fit = blends.get(d)
        if fit is not None and r["market_mid_prob"] is not None and r["model_prob_yes"] is not None:
            blend_p = apply_blend(fit, float(r["model_prob_yes"]), float(r["market_mid_prob"]))
            blend_edge = blend_p - float(r["market_mid_prob"])
        blend_fires = blend_edge is not None and abs(blend_edge) >= blend_t

        if not (raw_fires or blend_fires):
            continue

        # Side: raw wins the tie-break (KORD: when both fire they agree).
        if raw_fires:
            side, leg = r["position"], "raw"
        else:
            side = "BUY_YES" if blend_edge > 0 else "BUY_NO"
            leg = "blend-only"

        entry = entry_for_side(r, side)
        if entry is None or entry <= 0 or entry >= 100:
            continue

        yes_won = contract_resolved_yes(int(r["high_temp_f"]), {
            "bracket_type": r["bracket_type"],
            "strike_low": r["strike_low"],
            "strike_high": r["strike_high"],
        })
        win = yes_won if side == "BUY_YES" else (not yes_won)
        gross = (100 - entry) if win else -entry
        net = gross - kalshi_fee_cents(entry)
        trades.append({"date": str(d), "net": net, "entry": entry, "leg": leg,
                       "side": side, "win": win})
    return trades, n_dates_with_fit


def metrics(trades):
    """Daily-aggregated net P&L metrics (matches the diagnostic's convention)."""
    if not trades:
        return None
    daily = defaultdict(int)
    for t in trades:
        daily[t["date"]] += t["net"]
    dates = sorted(daily)
    pnls = [daily[d] for d in dates]
    n_days = len(dates)
    profit = sum(pnls)
    eq = peak = maxdd = 0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    sharpe_ann = None
    if n_days >= 3:
        sd = stdev(pnls)
        if sd > 0:
            span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
            years = span / 365.25 if span > 0 else 0
            ppy = (n_days / years) if years > 0 else 0
            if ppy > 0:
                sharpe_ann = (mean(pnls) / sd) * math.sqrt(ppy)
    wins = sum(1 for t in trades if t["net"] > 0)
    pdd = (profit / maxdd) if maxdd > 0 else (float("inf") if profit > 0 else 0.0)
    return {
        "n_trades": len(trades), "n_days": n_days,
        "net_dollars": profit / 100.0, "max_dd_dollars": maxdd / 100.0,
        "profit_to_dd": pdd, "sharpe_ann": sharpe_ann,
        "win_rate": wins / len(trades), "cents_per_trade": profit / len(trades),
        "raw_legs": sum(1 for t in trades if t["leg"] == "raw"),
        "blend_only_legs": sum(1 for t in trades if t["leg"] == "blend-only"),
    }


def _fmt(m):
    if m is None:
        return "  (no trades in window)"
    sh = "n/a" if m["sharpe_ann"] is None else f"{m['sharpe_ann']:.2f}"
    pdd = "inf" if m["profit_to_dd"] == float("inf") else f"{m['profit_to_dd']:.2f}"
    return (f"  trades={m['n_trades']} (raw={m['raw_legs']}, blend-only={m['blend_only_legs']})"
            f"  days={m['n_days']}\n"
            f"  net=${m['net_dollars']:.2f}  {m['cents_per_trade']:+.2f}c/trade  "
            f"win={m['win_rate']:.0%}  maxDD=${m['max_dd_dollars']:.2f}  P/DD={pdd}\n"
            f"  Sharpe (ann.) = {sh}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=date.fromisoformat, default=WATCHLIST_START,
                    help=f"forward-OOS window start (default {WATCHLIST_START})")
    ap.add_argument("--raw-threshold", type=float, default=RAW_THRESHOLD)
    ap.add_argument("--blend-threshold", type=float, default=BLEND_THRESHOLD)
    ap.add_argument("--json", help="optional path to write the metrics as JSON")
    args = ap.parse_args()

    with get_connection() as conn:
        rows = load_signals(conn)
    trades, n_fit = evaluate(rows, args.raw_threshold, args.blend_threshold)
    fwd = [t for t in trades if date.fromisoformat(t["date"]) >= args.since]
    full_m, fwd_m = metrics(trades), metrics(fwd)

    print(f"\n=== Dallas (KDFW) paper-watchlist — UNION raw>={args.raw_threshold:.2f} "
          f"OR blend>={args.blend_threshold:.2f} ===")
    print(f"model_source: {PAPER_MODEL_SOURCE!r}")
    print(f"signals scanned: {len(rows)}   dates with a walk-forward blend fit: {n_fit}")
    print(f"\nHistorical diagnostic walk-forward OOS (context, NOT the live verdict):")
    print(f"  {DIAG_OOS['params']} -> +${DIAG_OOS['profit']:.2f}, n={DIAG_OOS['n']}, "
          f"{DIAG_OOS['cents_per_trade']:+.2f}c/trade, Sharpe {DIAG_OOS['sharpe']:.2f}")
    print(f"  baseline (all data): {DIAG_OOS['baseline']}  -> tuned blip, watchlist only")
    print(f"\nFull-sample union (all logged Dallas history — IN-SAMPLE, selection-biased, context only):")
    print(_fmt(full_m))
    print(f"\nFORWARD out-of-sample (target_date >= {args.since}) — the graduation clock "
          f"[deploy bar: Sharpe > {DEPLOY_BAR}]:")
    print(_fmt(fwd_m))
    if fwd_m is None:
        print("  -> 0 forward trades yet; the daily paper cron logs Dallas raw signals,\n"
              "     so this window fills in as new trading days settle. Re-run periodically.")
    else:
        sh = fwd_m["sharpe_ann"]
        verdict = ("INSUFFICIENT n" if fwd_m["n_trades"] < 30 else
                   ("CLEARS bar" if sh is not None and sh > DEPLOY_BAR else "below bar"))
        print(f"  -> forward verdict: {verdict} "
              f"(need sustained Sharpe>{DEPLOY_BAR} on a real sample to promote to live)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"full_sample": full_m, "forward": fwd_m,
                       "since": str(args.since), "n_signals": len(rows),
                       "raw_threshold": args.raw_threshold,
                       "blend_threshold": args.blend_threshold}, f, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
