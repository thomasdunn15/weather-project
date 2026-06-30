#!/usr/bin/env python3
"""Walk-the-book CAPACITY analysis for Kalshi Miami (KMIA) — REAL order-book depth.

QUESTION
--------
How much size can KMIA absorb before the *marginal* contract's edge goes
negative? Directly informs whether Miami can safely double from 500 -> 1000
contracts. Read-only: no orders, no live-config change, no DB writes.

WHY THIS IS NOT walk_book_synthetic.py
--------------------------------------
scripts/analysis/walk_book_synthetic.py walks PARAMETRIC depth profiles
(thin/medium/thick) because at the time we had no historical depth. We now
have `orderbook_snapshots` (resting ladders every ~5 min). This script walks
the REAL resting book at each signal's decision time.

BOOK SEMANTICS (confirmed against a live KMIA snapshot)
-------------------------------------------------------
`orderbook_snapshots(snapshot_at, ticker, side['yes'|'no'], price_cents, qty)`
stores resting BIDS on each side. So:
  yes_bid = max(price where side='yes');  yes_ask = 100 - max(price where side='no')
To BUY YES you must LIFT the 'no' ladder: a resting NO bid at price p is, for
the YES buyer, an offer to sell YES at (100 - p). Best YES ask = 100 - max(no
price); walk DESC by no-price (== ascending YES ask), taking that level's qty.
To BUY NO is symmetric: lift the 'yes' ladder, NO ask = 100 - yes price.

Fee (taker, since walking/lifting the book is a marketable order):
  fee_cents(p) = max(1, ceil(0.07 * (p/100) * (1 - p/100) * 100))  on the entry price.
(Maker is 1/4 of this, but a walk-the-book lift is a taker action.)

SIGNALS
-------
KMIA live rule = BLEND-ONLY, |blend_edge| >= 0.10, unit 500, decision 15:30 UTC
(docs/context/strategy.md). The blend is reconstructed WALK-FORWARD
(weather_markets.blend.walkforward_blends) exactly like dallas_watchlist.py:
one fit per target_date trained only on strictly-earlier settled data, so it is
lookahead-free and matches how live would have blended.

  fair_value (BUY_YES) = blend_p          ;  fair_value (BUY_NO) = 1 - blend_p
  blend_edge = blend_p - market_mid       ;  side = BUY_YES if blend_edge>0 else BUY_NO

`model_prob_yes` only exists in paper_trades, so paper_trades (model_source
'EMOS combined 00Z Miami (rolling 45d)') is necessarily the candidate universe.
We ALSO report a raw-model fair (fair = model_prob_yes) — raw is looser than
blend, so it OVERSTATES optimal size; the blend cliff is the trustworthy one.

WHAT IT COMPUTES (per signal, at sizes 100/250/500/750/1000/1500/2000)
----------------------------------------------------------------------
  * VWAP and marginal ask; slippage vs the touch (best ask)
  * marginal edge at size = fair - marginal_ask/100 - fee(marginal_ask)/100
  * n*  = largest cumulative size whose marginal edge stays > 0 (the edge cliff)
  * realized $ vs fixed size (settlement via contract_resolved_yes on the high)
  * expected $ vs fixed size (fair-implied) -> the size where total EV peaks

USAGE
-----
    uv run python scripts/analysis/walk_book_miami.py
    uv run python scripts/analysis/walk_book_miami.py --blend-threshold 0.10 --json /tmp/kmia_cap.json

Sample is SMALL (~20 days of depth, ~a couple dozen signals). Results are
DIRECTIONAL; depth varies by time-of-day and regime. Caveat accordingly.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from statistics import median

import numpy as np

from weather_markets.db import get_connection
from weather_markets.blend import walkforward_blends, apply_blend
from weather_markets.evaluation import contract_resolved_yes

# --- constants ---------------------------------------------------------------
STATION = "KMIA"
CITY = "Miami"
PAPER_MODEL_SOURCE = "EMOS combined 00Z Miami (rolling 45d)"
BLEND_THRESHOLD = 0.10               # KMIA live: blend-only >= 10%
DECISION_HOUR, DECISION_MIN = 15, 30  # 15:30 UTC live decision
DEPTH_START = date(2026, 6, 10)      # orderbook_snapshots KMIA coverage
DEPTH_END = date(2026, 6, 29)
SIZES = [100, 250, 500, 750, 1000, 1500, 2000]
LIVE_UNIT = 500
TOLERANCE_MIN = 180                  # max |snapshot - 15:30| to accept (minutes)


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Canonical taker entry fee in cents (mirrors dashboard/sim_python.py)."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


# --- order-book primitives ---------------------------------------------------
def ask_ladder_from_levels(levels: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Convert resting bids on the side we LIFT into an ascending ask ladder.

    `levels` is [(price_cents, qty), ...] of the resting-bid side (the 'no' side
    when buying YES, the 'yes' side when buying NO). A resting bid at price p is
    an offer to sell the contract we want at ask = 100 - p. Cheapest ask first
    => highest resting-bid price first.
    """
    asks = [(100 - pc, q) for pc, q in levels if 0 < pc < 100 and q > 0]
    asks.sort(key=lambda x: x[0])  # ascending ask
    return asks


def total_depth(ask_ladder) -> int:
    return sum(q for _, q in ask_ladder)


def marginal_ask(ask_ladder, size: int):
    """Ask price (cents) paid for the `size`-th contract; None if book too thin."""
    cum = 0
    for ask, q in ask_ladder:
        cum += q
        if cum >= size:
            return ask
    return None


def vwap_cents(ask_ladder, size: int):
    """(VWAP cents, filled qty) for the first min(size, depth) contracts."""
    rem, cost, filled = size, 0, 0
    for ask, q in ask_ladder:
        take = min(rem, q)
        if take <= 0:
            break
        cost += take * ask
        filled += take
        rem -= take
        if rem <= 0:
            break
    return (cost / filled if filled else None), filled


def n_star(ask_ladder, fair: float) -> int:
    """Largest cumulative size whose MARGINAL edge stays > 0 (the edge cliff).

    Walk ascending asks; accumulate a level's qty while
    fair - ask/100 - fee/100 > 0; stop at the first non-positive level.
    Ask rises monotonically along the ladder so marginal edge is (essentially)
    monotone-decreasing — the small fee curvature near 50c is sub-cent and does
    not create a meaningful re-crossing.
    """
    n = 0
    for ask, q in ask_ladder:
        marg = fair - ask / 100.0 - kalshi_fee_cents(ask) / 100.0
        if marg > 0:
            n += q
        else:
            break
    return n


def realized_pnl_cents(ask_ladder, won: bool, size: int):
    """(filled, net_cents) of a fixed-size order: fill min(size, depth), settle."""
    rem, gross, fee, filled = size, 0, 0, 0
    for ask, q in ask_ladder:
        take = min(rem, q)
        if take <= 0:
            break
        filled += take
        gross += take * (100 - ask) if won else -take * ask
        fee += take * kalshi_fee_cents(ask)
        rem -= take
        if rem <= 0:
            break
    return filled, gross - fee


def expected_pnl_cents(ask_ladder, fair: float, size: int):
    """(filled, expected_net_cents) using fair value instead of realized outcome."""
    rem, tot, filled = size, 0.0, 0
    for ask, q in ask_ladder:
        take = min(rem, q)
        if take <= 0:
            break
        filled += take
        marg = fair - ask / 100.0 - kalshi_fee_cents(ask) / 100.0  # $/contract
        tot += take * marg * 100.0                                  # -> cents
        rem -= take
        if rem <= 0:
            break
    return filled, tot


# --- data --------------------------------------------------------------------
def load_rows(conn):
    """KMIA combined paper_trades in the depth window, joined to strikes + high.

    LEFT JOIN on the observed high so an unsettled target_date (e.g. today) still
    yields a row — its capacity (marginal edge / n*) is computable from the book
    even though realized P&L is not.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pt.target_date, pt.ticker, pt.model_prob_yes, pt.market_mid_prob,
                   pt.market_yes_bid, pt.market_yes_ask, pt.edge, pt.position,
                   pt.entry_price_cents, c.bracket_type, c.strike_low, c.strike_high,
                   o.high_temp_f
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
              WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
            WHERE pt.model_source = %s
              AND pt.target_date BETWEEN %s AND %s
            ORDER BY pt.target_date, pt.ticker
            """,
            (PAPER_MODEL_SOURCE, DEPTH_START, DEPTH_END),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def nearest_snapshot(conn, ticker: str, target_date: date):
    """The snapshot_at for `ticker` on `target_date` nearest 15:30 UTC, with the
    absolute offset in minutes. Returns (snapshot_at, off_min) or (None, None)."""
    target_ts = datetime.combine(target_date, time(DECISION_HOUR, DECISION_MIN), tzinfo=timezone.utc)
    day0 = datetime.combine(target_date, time(0, 0), tzinfo=timezone.utc)
    day1 = day0 + timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT snapshot_at, abs(extract(epoch FROM (snapshot_at - %s)))/60.0 AS off_min
               FROM orderbook_snapshots
               WHERE ticker = %s AND snapshot_at >= %s AND snapshot_at < %s
               ORDER BY off_min ASC LIMIT 1""",
            (target_ts, ticker, day0, day1),
        )
        row = cur.fetchone()
    return (row[0], float(row[1])) if row else (None, None)


def ladders_at(conn, ticker: str, snap_at):
    """Return (yes_levels, no_levels) as [(price_cents, qty), ...] at snap_at."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT side, price_cents, qty FROM orderbook_snapshots
               WHERE ticker = %s AND snapshot_at = %s""",
            (ticker, snap_at),
        )
        yes_levels, no_levels = [], []
        for side, pc, q in cur.fetchall():
            (yes_levels if side == "yes" else no_levels).append((int(pc), int(q)))
    return yes_levels, no_levels


# --- signal build ------------------------------------------------------------
def build_signals(conn, blend_threshold: float, tol_min: float):
    rows = load_rows(conn)
    blends = walkforward_blends(STATION, CITY, PAPER_MODEL_SOURCE)
    signals, skips = [], []
    for r in rows:
        d = r["target_date"]
        fit = blends.get(d)
        if fit is None:
            skips.append((d, r["ticker"], "no walk-forward blend fit yet"))
            continue
        if r["market_mid_prob"] is None or r["model_prob_yes"] is None:
            skips.append((d, r["ticker"], "missing model/market prob"))
            continue
        mp = float(r["model_prob_yes"])
        mkt = float(r["market_mid_prob"])
        blend_p = float(apply_blend(fit, mp, mkt))
        blend_edge = blend_p - mkt
        if abs(blend_edge) < blend_threshold:
            skips.append((d, r["ticker"], f"|blend_edge|={abs(blend_edge):.3f} < {blend_threshold}"))
            continue
        buy_yes = blend_edge > 0
        side = "BUY_YES" if buy_yes else "BUY_NO"
        fair_blend = blend_p if buy_yes else 1.0 - blend_p
        fair_raw = mp if buy_yes else 1.0 - mp

        snap_at, off_min = nearest_snapshot(conn, r["ticker"], d)
        if snap_at is None or off_min is None or off_min > tol_min:
            skips.append((d, r["ticker"], f"no snapshot within {tol_min:.0f}min of 15:30 "
                                          f"(nearest off={off_min})"))
            continue
        yes_levels, no_levels = ladders_at(conn, r["ticker"], snap_at)
        lift = no_levels if buy_yes else yes_levels
        ask_ladder = ask_ladder_from_levels(lift)
        if not ask_ladder:
            skips.append((d, r["ticker"], "empty ask ladder on lifted side"))
            continue

        # settlement (None if the day has not settled yet)
        won = None
        if r["high_temp_f"] is not None:
            yes_won = bool(contract_resolved_yes(int(r["high_temp_f"]), {
                "bracket_type": r["bracket_type"],
                "strike_low": r["strike_low"], "strike_high": r["strike_high"],
            }))
            won = yes_won if buy_yes else (not yes_won)

        signals.append({
            "date": d, "ticker": r["ticker"], "side": side, "buy_yes": buy_yes,
            "blend_edge": blend_edge, "fair_blend": fair_blend, "fair_raw": fair_raw,
            "model_p": mp, "market_mid": mkt, "blend_p": blend_p,
            "won": won, "high": r["high_temp_f"],
            "snap_at": snap_at, "off_min": off_min,
            "yes_levels": yes_levels, "no_levels": no_levels,
            "ask_ladder": ask_ladder, "touch": ask_ladder[0][0],
            "depth": total_depth(ask_ladder),
            "logged_yes_bid": r["market_yes_bid"], "logged_yes_ask": r["market_yes_ask"],
            "n_star_blend": n_star(ask_ladder, fair_blend),
            "n_star_raw": n_star(ask_ladder, fair_raw),
        })
    return signals, skips, len(rows)


# --- reporting ---------------------------------------------------------------
def q(xs, p):
    return float(np.percentile(xs, p)) if xs else float("nan")


def fmt_signal_id(s):
    return f"{s['date']} {s['ticker'].split('-')[-1]:<8} {s['side']}"


def worked_example(s):
    """Audit one real signal: ladder, walked asks, marginal edge by size, n*."""
    out = []
    out.append("=" * 78)
    out.append("WORKED EXAMPLE (auditable book-walk)")
    out.append("=" * 78)
    out.append(f"  {fmt_signal_id(s)}")
    out.append(f"  snapshot_at = {s['snap_at']}  ({s['off_min']:.0f} min from 15:30 UTC)")
    out.append(f"  model_p={s['model_p']:.3f}  market_mid={s['market_mid']:.3f}  "
               f"blend_p={s['blend_p']:.3f}  blend_edge={s['blend_edge']:+.3f}")
    out.append(f"  side={s['side']}  fair(blend)={s['fair_blend']:.3f}  fair(raw)={s['fair_raw']:.3f}"
               + (f"  high={s['high']}F  won={s['won']}" if s["won"] is not None else "  (unsettled)"))

    # book-semantics check
    no_max = max((pc for pc, _ in s["no_levels"]), default=None)
    yes_max = max((pc for pc, _ in s["yes_levels"]), default=None)
    yes_ask = (100 - no_max) if no_max is not None else None
    out.append("")
    out.append(f"  SEMANTICS CHECK: max(no_price)={no_max} -> yes_ask = 100 - {no_max} = {yes_ask}"
               f"   yes_bid = max(yes_price) = {yes_max}")
    out.append(f"                   (paper_trades logged yes_bid={s['logged_yes_bid']} "
               f"yes_ask={s['logged_yes_ask']} at decision time)")

    lifted = "no" if s["buy_yes"] else "yes"
    out.append("")
    out.append(f"  LIFTED LADDER ('{lifted}' resting bids -> ascending {('YES' if s['buy_yes'] else 'NO')} asks), top 12 levels:")
    out.append(f"    {'ask¢':>5} {'qty':>6} {'cum':>7}   (= 100 - {lifted}_price)")
    cum = 0
    for ask, qty in s["ask_ladder"][:12]:
        cum += qty
        out.append(f"    {ask:>5} {qty:>6} {cum:>7}")
    out.append(f"    ... total depth on this side = {s['depth']:,} contracts")

    out.append("")
    out.append(f"  WALK by cumulative size  (touch ask = {s['touch']}¢, fair_blend = {s['fair_blend']:.3f}):")
    out.append(f"    {'size':>5} {'vwap¢':>7} {'marg_ask¢':>9} {'slip¢':>6} {'marg_edge(blend)':>17} {'marg_edge(raw)':>15}")
    for size in SIZES:
        ma = marginal_ask(s["ask_ladder"], size)
        vw, filled = vwap_cents(s["ask_ladder"], size)
        if ma is None:
            out.append(f"    {size:>5} {'n/a':>7} {'n/a':>9} {'n/a':>6}   depth {s['depth']} < {size}")
            continue
        fee = kalshi_fee_cents(ma)
        me_b = s["fair_blend"] - ma / 100.0 - fee / 100.0
        me_r = s["fair_raw"] - ma / 100.0 - fee / 100.0
        out.append(f"    {size:>5} {vw:>7.2f} {ma:>9} {ma - s['touch']:>6} "
                   f"{me_b:>+17.4f} {me_r:>+15.4f}")
    out.append("")
    out.append(f"  n* (edge cliff, marginal edge > 0):  blend = {s['n_star_blend']:,}   "
               f"raw = {s['n_star_raw']:,}   (raw looser => larger, as expected)")
    return "\n".join(out)


def size_table(signals):
    """Aggregate across signals at each fixed size."""
    rows = []
    for size in SIZES:
        fillable = [s for s in signals if s["depth"] >= size]
        marg_asks = [marginal_ask(s["ask_ladder"], size) for s in fillable]
        slips = [ma - s["touch"] for ma, s in zip(marg_asks, fillable)]
        marg_edges_b = [s["fair_blend"] - ma / 100.0 - kalshi_fee_cents(ma) / 100.0
                        for ma, s in zip(marg_asks, fillable)]
        pos = sum(1 for me in marg_edges_b if me > 0)

        # realized (only settled signals); fills min(size, depth)
        settled = [s for s in signals if s["won"] is not None]
        r_cents, r_filled = 0, 0
        for s in settled:
            f, c = realized_pnl_cents(s["ask_ladder"], s["won"], size)
            r_cents += c
            r_filled += f
        # expected (all signals with a book)
        e_cents, e_filled = 0.0, 0
        for s in signals:
            f, c = expected_pnl_cents(s["ask_ladder"], s["fair_blend"], size)
            e_cents += c
            e_filled += f
        rows.append({
            "size": size,
            "n_fillable": len(fillable),
            "med_marg_ask": median(marg_asks) if marg_asks else float("nan"),
            "med_slip": median(slips) if slips else float("nan"),
            "med_marg_edge": median(marg_edges_b) if marg_edges_b else float("nan"),
            "pct_pos": (100.0 * pos / len(fillable)) if fillable else float("nan"),
            "real_total": r_cents / 100.0,
            "real_filled": r_filled,
            "real_per_k": (r_cents / r_filled) if r_filled else float("nan"),  # ¢/contract
            "exp_total": e_cents / 100.0,
            "exp_filled": e_filled,
            "exp_per_k": (e_cents / e_filled) if e_filled else float("nan"),
        })
    return rows


def expected_peak(signals, grid_step=25, grid_max=2600):
    """Fine scan of total EXPECTED $ vs fixed size to find the aggregate peak."""
    best_s, best_v = 0, float("-inf")
    curve = []
    for size in range(grid_step, grid_max + 1, grid_step):
        tot = 0.0
        for s in signals:
            _, c = expected_pnl_cents(s["ask_ladder"], s["fair_blend"], size)
            tot += c
        tot /= 100.0
        curve.append((size, tot))
        if tot > best_v:
            best_v, best_s = tot, size
    return best_s, best_v, curve


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blend-threshold", type=float, default=BLEND_THRESHOLD)
    ap.add_argument("--tolerance-min", type=float, default=TOLERANCE_MIN,
                    help="max |snapshot - 15:30 UTC| in minutes to accept a book")
    ap.add_argument("--json", help="optional path to write metrics as JSON")
    args = ap.parse_args()

    with get_connection() as conn:
        signals, skips, n_rows = build_signals(conn, args.blend_threshold, args.tolerance_min)

    print(f"\n=== KMIA walk-the-book CAPACITY (REAL depth) — blend-only |edge| >= "
          f"{args.blend_threshold:.2f} ===")
    print(f"model_source: {PAPER_MODEL_SOURCE!r}")
    print(f"depth window: {DEPTH_START} -> {DEPTH_END}   live unit = {LIVE_UNIT}   decision 15:30 UTC")
    print(f"candidate paper_trades rows in window: {n_rows}   ->  fired blend signals: {len(signals)}"
          f"   over {len({s['date'] for s in signals})} days")
    if signals:
        offs = [s["off_min"] for s in signals]
        print(f"chosen snapshots: median |offset from 15:30| = {median(offs):.0f} min "
              f"(max {max(offs):.0f})")
        sides = {}
        for s in signals:
            sides[s["side"]] = sides.get(s["side"], 0) + 1
        print(f"sides: {sides}")
    if not signals:
        print("\nNo signals — nothing to walk. (Widen --tolerance-min or check the window.)")
        return

    # ---- worked example: a BUY_YES signal with the deepest lifted book ----
    yes_sigs = [s for s in signals if s["buy_yes"]] or signals
    example = max(yes_sigs, key=lambda s: s["depth"])
    print("\n" + worked_example(example))

    # ---- aggregate table ----
    rows = size_table(signals)
    print("\n" + "=" * 78)
    print("P&L-vs-SIZE  (fixed-size order on every signal; fills min(size, depth))")
    print("=" * 78)
    print(f"{'size':>5} {'#fill':>6} {'medMargAsk¢':>11} {'medSlip¢':>8} {'medMargEdge':>11} "
          f"{'%edge>0':>7} | {'real$':>9} {'real¢/ct':>8} | {'exp$':>9} {'exp¢/ct':>7}")
    for r in rows:
        print(f"{r['size']:>5} {r['n_fillable']:>6} {r['med_marg_ask']:>11.1f} {r['med_slip']:>8.1f} "
              f"{r['med_marg_edge']:>+11.4f} {r['pct_pos']:>6.0f}% | "
              f"{r['real_total']:>+9.2f} {r['real_per_k']:>+8.2f} | "
              f"{r['exp_total']:>+9.2f} {r['exp_per_k']:>+7.2f}")
    print("  real$/exp$ = total across all signals; ¢/ct = per-contract (cents). "
          "real fills min(size,depth) of settled signals.")

    # ---- n* distribution ----
    nb = sorted(s["n_star_blend"] for s in signals)
    nr = sorted(s["n_star_raw"] for s in signals)
    print("\n" + "=" * 78)
    print("n* — EDGE-CLIFF per signal (largest size with marginal edge > 0)")
    print("=" * 78)
    print(f"  blend fair:  min={nb[0]:,}  Q1={q(nb,25):,.0f}  median={median(nb):,.0f}  "
          f"Q3={q(nb,75):,.0f}  max={nb[-1]:,}")
    print(f"  raw   fair:  min={nr[0]:,}  Q1={q(nr,25):,.0f}  median={median(nr):,.0f}  "
          f"Q3={q(nr,75):,.0f}  max={nr[-1]:,}   (raw OVERSTATES capacity)")
    print(f"  signals whose blend n* >= 500 : {sum(1 for x in nb if x >= 500)}/{len(nb)}")
    print(f"  signals whose blend n* >= 1000: {sum(1 for x in nb if x >= 1000)}/{len(nb)}")

    # ---- aggregate expected-PnL peak ----
    peak_size, peak_val, _curve = expected_peak(signals)

    # ---- ANSWERS ----
    r500 = next(r for r in rows if r["size"] == 500)
    r1000 = next(r for r in rows if r["size"] == 1000)
    print("\n" + "=" * 78)
    print("ANSWERS")
    print("=" * 78)
    print(f"(a) AT THE CURRENT 500:")
    print(f"    median marginal edge = {r500['med_marg_edge']:+.4f}  "
          f"({r500['pct_pos']:.0f}% of fillable signals still +EV at the 500th contract)")
    print(f"    median slippage vs touch = {r500['med_slip']:.1f}¢   "
          f"({r500['n_fillable']}/{len(signals)} signals have >=500 depth on the lifted side)")
    print(f"    expected per-contract edge at 500 = {r500['exp_per_k']:+.2f}¢   "
          f"realized = {r500['real_per_k']:+.2f}¢")
    print(f"(b) DOUBLING TO 1000:")
    print(f"    median marginal edge = {r1000['med_marg_edge']:+.4f}  "
          f"({r1000['pct_pos']:.0f}% of fillable signals +EV at the 1000th contract; "
          f"{r1000['n_fillable']}/{len(signals)} have >=1000 depth)")
    decay = r500["exp_per_k"] - r1000["exp_per_k"]
    print(f"    per-contract EXPECTED edge decays {r500['exp_per_k']:+.2f}¢ -> {r1000['exp_per_k']:+.2f}¢ "
          f"(−{decay:.2f}¢/ct, {100*decay/r500['exp_per_k'] if r500['exp_per_k'] else float('nan'):.0f}% haircut)")
    print(f"    median n* (blend) = {median(nb):,.0f}  -> "
          f"{'survives' if median(nb) >= 1000 else 'does NOT survive'} to 1000 at the median signal")
    print(f"(c) CAPACITY CEILING (total expected P&L peaks, marginal edge -> 0):")
    print(f"    aggregate expected $ peaks at size ≈ {peak_size:,} contracts (${peak_val:+.2f} total EV)")
    print(f"    per-signal median edge-cliff n* (blend) = {median(nb):,.0f} contracts")

    print("\nCAVEATS: sample is small (~20 days depth, "
          f"{len(signals)} signals / {len({s['date'] for s in signals})} days) — DIRECTIONAL only. "
          "Depth varies by time-of-day & regime; taker fees assumed (maker would extend capacity). "
          "Walk-forward blend is lookahead-free but the universe is the paper-logged combined rows.")

    if args.json:
        payload = {
            "blend_threshold": args.blend_threshold,
            "depth_window": [str(DEPTH_START), str(DEPTH_END)],
            "n_candidate_rows": n_rows, "n_signals": len(signals),
            "n_days": len({str(s["date"]) for s in signals}),
            "size_table": rows,
            "n_star_blend": {"min": nb[0], "q1": q(nb, 25), "median": median(nb),
                             "q3": q(nb, 75), "max": nb[-1]},
            "n_star_raw": {"min": nr[0], "q1": q(nr, 25), "median": median(nr),
                           "q3": q(nr, 75), "max": nr[-1]},
            "expected_peak_size": peak_size, "expected_peak_value": peak_val,
            "signals": [{
                "date": str(s["date"]), "ticker": s["ticker"], "side": s["side"],
                "blend_edge": s["blend_edge"], "fair_blend": s["fair_blend"],
                "touch": s["touch"], "depth": s["depth"],
                "n_star_blend": s["n_star_blend"], "n_star_raw": s["n_star_raw"],
                "off_min": s["off_min"], "won": s["won"],
            } for s in signals],
        }
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
