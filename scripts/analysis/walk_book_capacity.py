#!/usr/bin/env python3
"""Walk-the-book TAKER CAPACITY — station-parameterized (KORD | KMIA | KDFW).

Generalizes scripts/analysis/walk_book_miami.py (branch research/walk-book-miami)
to any live station. Answers the TAKER question: when you CROSS the spread, how
much size can the book absorb before the *marginal* contract's edge goes
negative? Directly informs whether a city can double 500 -> 1000. READ-ONLY: no
orders, no live-config change, no DB writes.

WHAT'S DIFFERENT FROM THE MIAMI SCRIPT
--------------------------------------
KMIA is blend-only; KORD/KDFW are UNION cities (fire if raw |edge| >= 25% OR
blend |edge| >= 10%). This tool reconstructs the LIVE signal exactly as
scripts/live_trade.py compute_signals_for_today() does:
  - raw_edge = model_p - market_mid ; blend_edge = blend_p - market_mid
  - UNION fires if |raw_edge|>=raw_thr OR |blend_edge|>=blend_thr
  - raw side is PREFERENTIAL: when raw fires, decision_p=model_p, edge=raw_edge;
    only when blend-only fires is decision_p=blend_p, edge=blend_edge.
  - side = BUY_YES if decision_edge>0 else BUY_NO ; p_win = decision fair.
  - is_cross = |decision_edge| >= smart_cross_edge_threshold  (the LIVE exec
    resolution in resolve_exec_path). KORD/KDFW cross_threshold=0.40, KMIA=0.10.

FAIR VALUES (three, so raw-optimism is visible)
-----------------------------------------------
  fair_decision = p_win               -> what LIVE actually bets on (raw-heavy
                                         for union cities; OPTIMISTIC).
  fair_blend    = blend side prob      -> the TRUSTWORTHY capacity floor.
  fair_raw      = raw model side prob  -> loosest upper bound.
For KMIA (blend-only) fair_decision == fair_blend by construction, so this tool
reproduces the original Miami walk-book when run with --station KMIA.

BOOK SEMANTICS (validated in walk_book_miami.py)
------------------------------------------------
orderbook_snapshots(snapshot_at, ticker, side['yes'|'no'], price_cents, qty)
stores resting BIDS. yes_ask = 100 - max(no price). To BUY YES you LIFT the 'no'
ladder (cheapest ask first = highest no-bid first). BUY NO lifts the 'yes' ladder.
Taker fee: max(1, ceil(0.07 * p * (1-p) * 100)) on the entry price.

USAGE
-----
    uv run python scripts/analysis/walk_book_capacity.py --station KORD
    uv run python scripts/analysis/walk_book_capacity.py --station KDFW --json /tmp/kdfw_walk.json
    uv run python scripts/analysis/walk_book_capacity.py --station KMIA \
        --depth-start 2026-06-10 --depth-end 2026-06-29   # reproduce Miami anchor

Sample is SMALL (orderbook depth since 2026-06-10). Results are DIRECTIONAL.
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

# --- per-station config (mirrors scripts/live_trade.py CITY_CONFIG) -----------
STATION_CFG = {
    "KORD": dict(
        city="Chicago", series="KXHIGHCHI",
        paper_model_source="EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        use_union=True, raw_thr=0.25, blend_thr=0.10, smart_cross_thr=0.40,
        decision_hour=14, decision_min=46, live_unit=500,
        depth_start=date(2026, 6, 10), depth_end=date(2026, 7, 7),
    ),
    "KMIA": dict(
        city="Miami", series="KXHIGHMIA",
        paper_model_source="EMOS combined 00Z Miami (rolling 45d)",
        use_union=False, raw_thr=1.00, blend_thr=0.10, smart_cross_thr=0.10,
        decision_hour=15, decision_min=30, live_unit=500,
        # default to the ORIGINAL 20-day window so --station KMIA reproduces the
        # published Miami anchor; override with --depth-end 2026-07-07 for full.
        depth_start=date(2026, 6, 10), depth_end=date(2026, 6, 29),
    ),
    "KDFW": dict(
        city="Dallas", series="KXHIGHTDAL",
        paper_model_source="EMOS combined 00Z Dallas (rolling 45d)",
        use_union=True, raw_thr=0.25, blend_thr=0.10, smart_cross_thr=0.40,
        decision_hour=17, decision_min=32, live_unit=500,
        depth_start=date(2026, 6, 10), depth_end=date(2026, 7, 7),
    ),
}

SIZES = [100, 250, 500, 750, 1000, 1500, 2000]
TOLERANCE_MIN = 180


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Canonical TAKER entry fee in cents (a book-lift is a taker action)."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


# --- order-book primitives ---------------------------------------------------
def ask_ladder_from_levels(levels):
    asks = [(100 - pc, q) for pc, q in levels if 0 < pc < 100 and q > 0]
    asks.sort(key=lambda x: x[0])
    return asks


def total_depth(ask_ladder):
    return sum(q for _, q in ask_ladder)


def marginal_ask(ask_ladder, size):
    cum = 0
    for ask, q in ask_ladder:
        cum += q
        if cum >= size:
            return ask
    return None


def vwap_cents(ask_ladder, size):
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


def n_star(ask_ladder, fair):
    """Largest cumulative size whose MARGINAL edge stays > 0 (the edge cliff)."""
    n = 0
    for ask, q in ask_ladder:
        marg = fair - ask / 100.0 - kalshi_fee_cents(ask) / 100.0
        if marg > 0:
            n += q
        else:
            break
    return n


def realized_pnl_cents(ask_ladder, won, size):
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


def expected_pnl_cents(ask_ladder, fair, size):
    rem, tot, filled = size, 0.0, 0
    for ask, q in ask_ladder:
        take = min(rem, q)
        if take <= 0:
            break
        filled += take
        marg = fair - ask / 100.0 - kalshi_fee_cents(ask) / 100.0
        tot += take * marg * 100.0
        rem -= take
        if rem <= 0:
            break
    return filled, tot


# --- data --------------------------------------------------------------------
def load_rows(conn, cfg, depth_start, depth_end):
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
            (cfg["paper_model_source"], depth_start, depth_end),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def nearest_snapshot(conn, ticker, target_date, dh, dm):
    target_ts = datetime.combine(target_date, time(dh, dm), tzinfo=timezone.utc)
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


def ladders_at(conn, ticker, snap_at):
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


# --- signal build (mirrors live_trade.compute_signals_for_today union logic) --
def build_signals(conn, cfg, depth_start, depth_end, tol_min):
    rows = load_rows(conn, cfg, depth_start, depth_end)
    blends = walkforward_blends(cfg["_station"], cfg["city"], cfg["paper_model_source"])
    raw_thr, blend_thr = cfg["raw_thr"], cfg["blend_thr"]
    cross_thr = cfg["smart_cross_thr"]
    use_union = cfg["use_union"]
    signals, skips = [], []
    n_cross = 0
    for r in rows:
        d = r["target_date"]
        if r["market_mid_prob"] is None or r["model_prob_yes"] is None:
            skips.append((d, r["ticker"], "missing model/market prob"))
            continue
        fit = blends.get(d)
        if fit is None:
            skips.append((d, r["ticker"], "no walk-forward blend fit yet"))
            continue
        mp = float(r["model_prob_yes"])
        mkt = float(r["market_mid_prob"])
        blend_p = float(apply_blend(fit, mp, mkt))
        raw_edge = mp - mkt
        blend_edge = blend_p - mkt
        raw_fires = abs(raw_edge) >= raw_thr
        blend_fires = abs(blend_edge) >= blend_thr

        # --- exact live union/blend resolution ---
        if use_union:
            if not (raw_fires or blend_fires):
                continue
            if raw_fires:
                decision_p, decision_edge = mp, raw_edge
                sig_src = "union_both" if blend_fires else "union_raw_only"
            else:
                decision_p, decision_edge = blend_p, blend_edge
                sig_src = "union_blend_only"
        else:  # blend-only
            if not blend_fires:
                continue
            decision_p, decision_edge = blend_p, blend_edge
            sig_src = "blend"

        buy_yes = decision_edge > 0
        side = "BUY_YES" if buy_yes else "BUY_NO"
        fair_decision = decision_p if buy_yes else 1.0 - decision_p
        fair_blend = blend_p if buy_yes else 1.0 - blend_p
        fair_raw = mp if buy_yes else 1.0 - mp
        is_cross = abs(decision_edge) >= cross_thr
        if is_cross:
            n_cross += 1

        snap_at, off_min = nearest_snapshot(conn, r["ticker"], d,
                                            cfg["decision_hour"], cfg["decision_min"])
        if snap_at is None or off_min is None or off_min > tol_min:
            skips.append((d, r["ticker"], f"no snapshot within {tol_min:.0f}min (off={off_min})"))
            continue
        yes_levels, no_levels = ladders_at(conn, r["ticker"], snap_at)
        lift = no_levels if buy_yes else yes_levels
        ask_ladder = ask_ladder_from_levels(lift)
        if not ask_ladder:
            skips.append((d, r["ticker"], "empty ask ladder on lifted side"))
            continue

        won = None
        if r["high_temp_f"] is not None:
            yes_won = bool(contract_resolved_yes(int(r["high_temp_f"]), {
                "bracket_type": r["bracket_type"],
                "strike_low": r["strike_low"], "strike_high": r["strike_high"],
            }))
            won = yes_won if buy_yes else (not yes_won)

        signals.append(dict(
            date=d, ticker=r["ticker"], side=side, buy_yes=buy_yes,
            sig_src=sig_src, is_cross=is_cross,
            raw_edge=raw_edge, blend_edge=blend_edge, decision_edge=decision_edge,
            fair_decision=fair_decision, fair_blend=fair_blend, fair_raw=fair_raw,
            model_p=mp, market_mid=mkt, blend_p=blend_p,
            won=won, high=r["high_temp_f"], snap_at=snap_at, off_min=off_min,
            ask_ladder=ask_ladder, touch=ask_ladder[0][0], depth=total_depth(ask_ladder),
            n_star_decision=n_star(ask_ladder, fair_decision),
            n_star_blend=n_star(ask_ladder, fair_blend),
            n_star_raw=n_star(ask_ladder, fair_raw),
        ))
    return signals, skips, n_cross, len(rows)


# --- reporting ---------------------------------------------------------------
def q(xs, p):
    return float(np.percentile(xs, p)) if xs else float("nan")


def size_table(signals, fair_key):
    rows = []
    settled = [s for s in signals if s["won"] is not None]
    for size in SIZES:
        fillable = [s for s in signals if s["depth"] >= size]
        marg_asks = [marginal_ask(s["ask_ladder"], size) for s in fillable]
        slips = [ma - s["touch"] for ma, s in zip(marg_asks, fillable)]
        marg_edges = [s[fair_key] - ma / 100.0 - kalshi_fee_cents(ma) / 100.0
                      for ma, s in zip(marg_asks, fillable)]
        pos = sum(1 for me in marg_edges if me > 0)
        r_cents, r_filled = 0, 0
        for s in settled:
            f, c = realized_pnl_cents(s["ask_ladder"], s["won"], size)
            r_cents += c
            r_filled += f
        e_cents, e_filled = 0.0, 0
        for s in signals:
            f, c = expected_pnl_cents(s["ask_ladder"], s[fair_key], size)
            e_cents += c
            e_filled += f
        rows.append(dict(
            size=size, n_fillable=len(fillable),
            med_marg_ask=median(marg_asks) if marg_asks else float("nan"),
            med_slip=median(slips) if slips else float("nan"),
            med_marg_edge=median(marg_edges) if marg_edges else float("nan"),
            pct_pos=(100.0 * pos / len(fillable)) if fillable else float("nan"),
            real_total=r_cents / 100.0, real_filled=r_filled,
            real_per_k=(r_cents / r_filled) if r_filled else float("nan"),
            exp_total=e_cents / 100.0, exp_filled=e_filled,
            exp_per_k=(e_cents / e_filled) if e_filled else float("nan"),
        ))
    return rows


def expected_peak(signals, fair_key, step=25, gmax=2600):
    best_s, best_v, curve = 0, float("-inf"), []
    for size in range(step, gmax + 1, step):
        tot = 0.0
        for s in signals:
            _, c = expected_pnl_cents(s["ask_ladder"], s[fair_key], size)
            tot += c
        tot /= 100.0
        curve.append((size, tot))
        if tot > best_v:
            best_v, best_s = tot, size
    return best_s, best_v, curve


def print_size_table(rows, label):
    print(f"\nP&L-vs-SIZE  [{label} fair]  (fixed-size CROSS on every signal; fills min(size,depth))")
    print("-" * 96)
    print(f"{'size':>5} {'#fill':>6} {'medMargAsk':>11} {'medSlip':>8} {'medMargEdge':>12} "
          f"{'%edge>0':>8} | {'exp$':>9} {'exp c/ct':>9} | {'real$':>9} {'real c/ct':>10}")
    for r in rows:
        print(f"{r['size']:>5} {r['n_fillable']:>6} {r['med_marg_ask']:>11.1f} {r['med_slip']:>8.1f} "
              f"{r['med_marg_edge']:>+12.4f} {r['pct_pos']:>7.0f}% | "
              f"{r['exp_total']:>+9.2f} {r['exp_per_k']:>+9.2f} | "
              f"{r['real_total']:>+9.2f} {r['real_per_k']:>+10.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", required=True, choices=list(STATION_CFG.keys()))
    ap.add_argument("--depth-start", type=date.fromisoformat, default=None)
    ap.add_argument("--depth-end", type=date.fromisoformat, default=None)
    ap.add_argument("--tolerance-min", type=float, default=TOLERANCE_MIN)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    cfg = dict(STATION_CFG[args.station])
    cfg["_station"] = args.station
    depth_start = args.depth_start or cfg["depth_start"]
    depth_end = args.depth_end or cfg["depth_end"]

    with get_connection() as conn:
        signals, skips, n_cross, n_rows = build_signals(conn, cfg, depth_start, depth_end,
                                                         args.tolerance_min)

    print("=" * 96)
    print(f"{args.station} ({cfg['city']}) WALK-THE-BOOK TAKER CAPACITY — REAL depth")
    print("=" * 96)
    mode = ("UNION raw>=%.0f%% OR blend>=%.0f%%" % (cfg["raw_thr"] * 100, cfg["blend_thr"] * 100)
            if cfg["use_union"] else "BLEND-only >=%.0f%%" % (cfg["blend_thr"] * 100))
    print(f"filter: {mode}   smart_cross>= {cfg['smart_cross_thr']:.0%}   "
          f"decision {cfg['decision_hour']:02d}:{cfg['decision_min']:02d}Z   live_unit={cfg['live_unit']}")
    print(f"depth window: {depth_start} -> {depth_end}   model_source: {cfg['paper_model_source']!r}")
    print(f"candidate paper rows: {n_rows}  ->  fired signals: {len(signals)} "
          f"over {len({s['date'] for s in signals})} days   (skipped {len(skips)})")
    if not signals:
        print("\nNo signals — nothing to walk.")
        return
    offs = [s["off_min"] for s in signals]
    print(f"chosen snapshots: median |offset from decision| = {median(offs):.0f} min (max {max(offs):.0f})")
    srcs = {}
    for s in signals:
        srcs[s["sig_src"]] = srcs.get(s["sig_src"], 0) + 1
    print(f"signal sources: {srcs}")

    # POST vs CROSS mix
    print("\n" + "=" * 96)
    print("POST vs CROSS MIX  (which lens binds; is_cross = |decision_edge| >= smart_cross_thr)")
    print("=" * 96)
    n = len(signals)
    print(f"  CROSS (taker, |edge|>= {cfg['smart_cross_thr']:.0%}): {n_cross}/{n} = {100*n_cross/n:.0f}%")
    print(f"  POST  (maker, below threshold)          : {n - n_cross}/{n} = {100*(n-n_cross)/n:.0f}%")
    print(f"  => TAKER walk-book binds on the CROSS fraction; MAKER fill-rate binds on the POST fraction.")

    # tables: decision (live) primary, blend (trustworthy floor) cross-check
    rows_dec = size_table(signals, "fair_decision")
    rows_bl = size_table(signals, "fair_blend")
    print("\n" + "=" * 96)
    print("TAKER PRICE-IMPACT — all fired signals")
    print("=" * 96)
    print_size_table(rows_dec, "DECISION/live (raw-heavy for union; OPTIMISTIC)")
    print_size_table(rows_bl, "BLEND/trustworthy floor")

    # cross-only subset (the signals that actually take liquidity live)
    cross_sigs = [s for s in signals if s["is_cross"]]
    if cross_sigs:
        print("\n" + "-" * 96)
        print(f"CROSS-ONLY subset (n={len(cross_sigs)}) — the signals that actually LIFT the book live:")
        print_size_table(size_table(cross_sigs, "fair_decision"), "DECISION/live, CROSS-only")

    # n* distribution
    nd = sorted(s["n_star_decision"] for s in signals)
    nb = sorted(s["n_star_blend"] for s in signals)
    nr = sorted(s["n_star_raw"] for s in signals)
    print("\n" + "=" * 96)
    print("n* — EDGE-CLIFF per signal (largest size with marginal TAKER edge > 0)")
    print("=" * 96)
    for lbl, xs in [("decision/live", nd), ("blend/floor  ", nb), ("raw/loose    ", nr)]:
        print(f"  {lbl}:  min={xs[0]:>6,}  Q1={q(xs,25):>7,.0f}  median={median(xs):>7,.0f}  "
              f"Q3={q(xs,75):>7,.0f}  max={xs[-1]:>7,}")
    print(f"  signals w/ blend n* >= 500 : {sum(1 for x in nb if x >= 500)}/{len(nb)}   "
          f">= 1000: {sum(1 for x in nb if x >= 1000)}/{len(nb)}")

    peak_dec, peakv_dec, _ = expected_peak(signals, "fair_decision")
    peak_bl, peakv_bl, _ = expected_peak(signals, "fair_blend")

    # ANSWERS
    def at(rows, sz):
        return next(r for r in rows if r["size"] == sz)
    print("\n" + "=" * 96)
    print("ANSWERS")
    print("=" * 96)
    for lbl, rows, peak, peakv, nn in [
        ("DECISION/live", rows_dec, peak_dec, peakv_dec, nd),
        ("BLEND/floor", rows_bl, peak_bl, peakv_bl, nb),
    ]:
        r5, r10 = at(rows, 500), at(rows, 1000)
        decay = r5["exp_per_k"] - r10["exp_per_k"]
        pct = (100 * decay / r5["exp_per_k"]) if r5["exp_per_k"] else float("nan")
        print(f"[{lbl}]")
        print(f"  @500 : med marg edge={r5['med_marg_edge']:+.4f} ({r5['pct_pos']:.0f}% +EV), "
              f"slip={r5['med_slip']:.1f}c, exp {r5['exp_per_k']:+.2f}c/ct  "
              f"({r5['n_fillable']}/{len(signals)} have >=500 depth)")
        print(f"  @1000: med marg edge={r10['med_marg_edge']:+.4f} ({r10['pct_pos']:.0f}% +EV), "
              f"exp {r10['exp_per_k']:+.2f}c/ct  ({r10['n_fillable']}/{len(signals)} have >=1000 depth)")
        print(f"  per-contract EXPECTED edge decay 500->1000: {r5['exp_per_k']:+.2f} -> "
              f"{r10['exp_per_k']:+.2f} c/ct  (-{decay:.2f}c, {pct:.0f}% haircut)")
        print(f"  aggregate expected$ TAKER peak at size ~= {peak:,} (${peakv:+.2f} EV); "
              f"median edge-cliff n* = {median(nn):,.0f}")
    print("\nCAVEATS: small directional window (orderbook since 2026-06-10); TAKER fees assumed "
          "(a walk-the-book lift IS taker). Walk-forward blend is lookahead-free. Union 'decision' "
          "fair is raw-heavy and OPTIMISTIC; the blend fair is the trustworthy capacity floor.")

    if args.json:
        payload = dict(
            station=args.station, city=cfg["city"], depth_window=[str(depth_start), str(depth_end)],
            n_rows=n_rows, n_signals=len(signals), n_cross=n_cross,
            n_days=len({str(s["date"]) for s in signals}),
            size_table_decision=rows_dec, size_table_blend=rows_bl,
            n_star_decision=dict(min=nd[0], q1=q(nd, 25), median=median(nd), q3=q(nd, 75), max=nd[-1]),
            n_star_blend=dict(min=nb[0], q1=q(nb, 25), median=median(nb), q3=q(nb, 75), max=nb[-1]),
            n_star_raw=dict(min=nr[0], q1=q(nr, 25), median=median(nr), q3=q(nr, 75), max=nr[-1]),
            peak_decision=[peak_dec, peakv_dec], peak_blend=[peak_bl, peakv_bl],
            signals=[{k: (str(v) if isinstance(v, date) else v)
                      for k, v in s.items() if k != "ask_ladder"} for s in signals],
        )
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
