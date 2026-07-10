#!/usr/bin/env python3
"""Maker FILL-RATE vs posted size — station-parameterized (KORD | KMIA | KDFW).

Generalizes scripts/analysis/miami_fill_rate_vs_size.py (branch research/miami-
fill-rate) to any live station. Answers the MAKER question: when you post a
RESTING limit order at a fixed price, your price is fixed — the binding
constraint is whether enough COUNTERPARTY FLOW trades against you before close.
Does doubling 500 -> 1000 roughly double FILLED contracts, or does the marginal
500 starve? READ-ONLY. No orders, no config change.

DATA (stated loudly)
--------------------
* orderbook_snapshots — RESTING bids each ladder, ~5-min cadence, coverage since
  2026-06-10. DIRECTIONAL. NO TRADE TAPE: counterparty flow is INFERRED from
  price-anchored, churn-suppressed bid-ladder depletion (see docstring of the
  Miami original for the full rationale — the 0-fill-day sanity check, why naive
  depletion overcounts 100x, etc.). Absolute level = lower-confidence proxy; the
  SHAPE (500 vs 1000) is the finding.
* live_trades — our OWN realized fills, the validation anchor (KORD ~90%,
  KMIA ~52%, KDFW ~thin/0).

SIGNAL RECONSTRUCTION mirrors scripts/live_trade.py exactly (UNION for KORD/KDFW,
blend-only for KMIA; raw side preferential; is_cross = |decision_edge| >=
smart_cross_edge_threshold). For KMIA this reproduces the published Miami study.

MAKER FLOW ESTIMATOR (price-anchored, conservative)
---------------------------------------------------
For a resting BUY at post_price we count consumption between snapshots only when
(a) best_bid <= post_price, (b) best_bid does NOT rise (reprice-up = new flow),
(c) qty at the best-bid price falls. Subtract ahead_qty (queue priority).

USAGE
-----
    uv run python scripts/analysis/fill_rate_capacity.py --station KORD
    uv run python scripts/analysis/fill_rate_capacity.py --station KDFW --json /tmp/kdfw_fill.json
    uv run python scripts/analysis/fill_rate_capacity.py --station KMIA \
        --depth-start 2026-06-10 --depth-end 2026-06-29 --anchor-date 2026-06-21
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

STATION_CFG = {
    "KORD": dict(
        city="Chicago", series="KXHIGHCHI",
        paper_model_source="EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        use_union=True, raw_thr=0.25, blend_thr=0.10, smart_cross_thr=0.40,
        decision_hour=14, decision_min=46,
        depth_start=date(2026, 6, 10), depth_end=date(2026, 7, 7),
    ),
    "KMIA": dict(
        city="Miami", series="KXHIGHMIA",
        paper_model_source="EMOS combined 00Z Miami (rolling 45d)",
        use_union=False, raw_thr=1.00, blend_thr=0.10, smart_cross_thr=0.10,
        decision_hour=15, decision_min=30,
        depth_start=date(2026, 6, 10), depth_end=date(2026, 6, 29),
    ),
    "KDFW": dict(
        city="Dallas", series="KXHIGHTDAL",
        paper_model_source="EMOS combined 00Z Dallas (rolling 45d)",
        use_union=True, raw_thr=0.25, blend_thr=0.10, smart_cross_thr=0.40,
        decision_hour=17, decision_min=32,
        depth_start=date(2026, 6, 10), depth_end=date(2026, 7, 7),
    ),
    "KPHX": dict(
        city="Phoenix", series="KXHIGHTPHX",
        paper_model_source="EMOS combined 00Z Phoenix (rolling 45d)",
        # RAW-only @0.20 via union path with blend disabled (blend_thr=1.00). Live 250-unit.
        use_union=True, raw_thr=0.20, blend_thr=1.00, smart_cross_thr=0.40,
        decision_hour=14, decision_min=52,
        depth_start=date(2026, 6, 10), depth_end=date(2026, 7, 10),
    ),
}

TOLERANCE_MIN = 180
SIZES = [100, 250, 500, 750, 1000, 1500]


# --- order-book primitives ---------------------------------------------------
def ladders_at(cur, ticker, snap):
    cur.execute(
        "SELECT side, price_cents, qty FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at=%s",
        (ticker, snap),
    )
    yl, nl = [], []
    for side, pc, q in cur.fetchall():
        (yl if side == "yes" else nl).append((int(pc), int(q)))
    return yl, nl


def nearest_snapshot(cur, ticker, d, dh, dm):
    tgt = datetime.combine(d, time(dh, dm), tzinfo=timezone.utc)
    d0 = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
    d1 = d0 + timedelta(days=1)
    cur.execute(
        """SELECT snapshot_at, abs(extract(epoch FROM (snapshot_at-%s)))/60.0 off_min
           FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at>=%s AND snapshot_at<%s
           ORDER BY off_min ASC LIMIT 1""",
        (tgt, ticker, d0, d1),
    )
    r = cur.fetchone()
    return (r[0], float(r[1])) if r else (None, None)


def bid_series(cur, ticker, side, start, end):
    cur.execute(
        """SELECT snapshot_at, price_cents, qty FROM orderbook_snapshots
           WHERE ticker=%s AND side=%s AND snapshot_at>=%s AND snapshot_at<%s
           ORDER BY snapshot_at""",
        (ticker, side, start, end),
    )
    s = {}
    for ts, pc, q in cur.fetchall():
        s.setdefault(ts, {})[int(pc)] = int(q)
    return s


def maker_flow_to_us(series, post_price, ahead_qty):
    """Inferred counterparty-sell flow reaching a resting bid at post_price.
    Returns (net_flow_past_queue, raw_flow_to_our_level)."""
    tss = sorted(series.keys())
    raw = 0
    for a, b in zip(tss, tss[1:]):
        la, lb = series[a], series[b]
        if not la:
            continue
        bb = max(la.keys())
        bb2 = max(lb.keys()) if lb else 0
        if bb > post_price:
            continue
        if bb2 > bb:
            continue
        raw += max(0, la.get(bb, 0) - lb.get(bb, 0))
    return max(0, raw - ahead_qty), raw


# --- signal reconstruction (mirrors live_trade union/blend logic) ------------
def build_signals(cur, cfg, depth_start, depth_end):
    blends = walkforward_blends(cfg["_station"], cfg["city"], cfg["paper_model_source"])
    cur.execute(
        """SELECT target_date, ticker, model_prob_yes, market_mid_prob
           FROM paper_trades WHERE model_source=%s AND target_date BETWEEN %s AND %s
           ORDER BY target_date, ticker""",
        (cfg["paper_model_source"], depth_start, depth_end),
    )
    rows = cur.fetchall()
    raw_thr, blend_thr, cross_thr = cfg["raw_thr"], cfg["blend_thr"], cfg["smart_cross_thr"]
    use_union = cfg["use_union"]
    sigs, skips, n_cross = [], [], 0
    for d, tk, mp, mkt in rows:
        if mp is None or mkt is None:
            skips.append((d, tk, "missing model/market prob"))
            continue
        fit = blends.get(d)
        if fit is None:
            skips.append((d, tk, "no walk-forward blend fit yet"))
            continue
        mp, mkt = float(mp), float(mkt)
        blend_p = float(apply_blend(fit, mp, mkt))
        raw_edge = mp - mkt
        blend_edge = blend_p - mkt
        raw_fires = abs(raw_edge) >= raw_thr
        blend_fires = abs(blend_edge) >= blend_thr
        if use_union:
            if not (raw_fires or blend_fires):
                continue
            if raw_fires:
                decision_edge, sig_src = raw_edge, ("union_both" if blend_fires else "union_raw_only")
            else:
                decision_edge, sig_src = blend_edge, "union_blend_only"
        else:
            if not blend_fires:
                continue
            decision_edge, sig_src = blend_edge, "blend"
        buy_yes = decision_edge > 0
        is_cross = abs(decision_edge) >= cross_thr
        if is_cross:
            n_cross += 1
        snap, off = nearest_snapshot(cur, tk, d, cfg["decision_hour"], cfg["decision_min"])
        if snap is None or off is None or off > TOLERANCE_MIN:
            skips.append((d, tk, f"no snapshot within {TOLERANCE_MIN}min (off={off})"))
            continue
        yl, nl = ladders_at(cur, tk, snap)
        levels = yl if buy_yes else nl            # MAKER: join our OWN side's bid
        if not levels:
            skips.append((d, tk, "empty bid ladder on post side"))
            continue
        best_bid = max(p for p, _ in levels)
        post_price = best_bid
        ahead = dict(levels).get(post_price, 0)
        d0 = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        eod = d0 + timedelta(days=1)
        ser = bid_series(cur, tk, "yes" if buy_yes else "no", snap, eod)
        net, raw = maker_flow_to_us(ser, post_price, ahead)
        sigs.append(dict(
            date=d, ticker=tk, side="BUY_YES" if buy_yes else "BUY_NO",
            sig_src=sig_src, decision_edge=decision_edge, best_bid=best_bid,
            post_price=post_price, ahead=ahead, raw_flow=raw, net_flow=net,
            n_snaps=len(ser), is_cross=is_cross, off_min=off,
        ))
    return sigs, skips, n_cross, len(rows)


def broad_book_flows(cur, cfg, depth_start, depth_end):
    """Every bracket ladder-day in the window (both sides), inferred sell-flow to
    the decision-time best bid over decision->EOD. Clean (mostly un-traded tickers)."""
    cur.execute(
        """SELECT DISTINCT ticker, snapshot_at::date d FROM orderbook_snapshots
           WHERE ticker LIKE %s AND snapshot_at::date BETWEEN %s AND %s""",
        (cfg["series"] + "%", depth_start, depth_end),
    )
    dh, dm = cfg["decision_hour"], cfg["decision_min"]
    flows = []
    for tk, d in cur.fetchall():
        d0 = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        eod = d0 + timedelta(days=1)
        tgt = datetime.combine(d, time(dh, dm), tzinfo=timezone.utc)
        cur.execute(
            """SELECT snapshot_at FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at>=%s
               AND snapshot_at<%s ORDER BY abs(extract(epoch FROM(snapshot_at-%s))) LIMIT 1""",
            (tk, d0, eod, tgt),
        )
        r = cur.fetchone()
        if not r:
            continue
        snap = r[0]
        for side in ("yes", "no"):
            cur.execute(
                "SELECT price_cents, qty FROM orderbook_snapshots WHERE ticker=%s AND side=%s AND snapshot_at=%s",
                (tk, side, snap),
            )
            lv = cur.fetchall()
            if not lv:
                continue
            best = max(int(p) for p, _ in lv)
            ser = bid_series(cur, tk, side, snap, eod)
            net, _ = maker_flow_to_us(ser, best, 0)
            flows.append(net)
    return flows


def fill_curve(flows):
    rows = []
    for N in SIZES:
        fr = [min(f, N) / N for f in flows]
        fc = [min(f, N) for f in flows]
        rows.append(dict(
            N=N,
            med_fill_rate=median(fr) if fr else float("nan"),
            med_filled=median(fc) if fc else float("nan"),
            p25_filled=float(np.percentile(fc, 25)) if fc else float("nan"),
            p75_filled=float(np.percentile(fc, 75)) if fc else float("nan"),
            mean_fill_rate=float(np.mean(fr)) if fr else float("nan"),
        ))
    return rows


# --- validation anchor (realized live fills) ---------------------------------
def live_anchor(cur, cfg, anchor_date):
    prefix = cfg["series"] + "%"

    def agg(where, params):
        cur.execute(
            f"""SELECT count(*), coalesce(sum(count),0), coalesce(sum(coalesce(fill_count,0)),0)
                FROM live_trades WHERE ticker LIKE %s {where}""",
            (prefix, *params),
        )
        n, posted, filled = cur.fetchone()
        pct = (100.0 * float(filled) / float(posted)) if posted else float("nan")
        return dict(n=int(n), posted=int(posted), filled=int(filled), pct_contracts=pct)

    current = agg("", ())
    cross = agg("AND limit_price_cents = cross_price_cents", ())
    maker = agg("AND limit_price_cents <> cross_price_cents", ())
    as_of = agg("AND placed_at::date <= %s", (anchor_date,)) if anchor_date else None
    return dict(current=current, cross=cross, maker=maker, as_of=as_of, anchor_date=anchor_date)


# --- leakage / adverse selection ---------------------------------------------
def mid_at(cur, ticker, snap):
    cur.execute(
        "SELECT side, max(price_cents) FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at=%s GROUP BY side",
        (ticker, snap),
    )
    yb = nb = None
    for s, p in cur.fetchall():
        if s == "yes":
            yb = int(p)
        else:
            nb = int(p)
    if yb is None or nb is None:
        return None
    return (yb + (100 - nb)) / 2.0


def nearest_after(cur, ticker, ts, minutes):
    cur.execute(
        "SELECT snapshot_at FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at>=%s ORDER BY snapshot_at LIMIT 1",
        (ticker, ts + timedelta(minutes=minutes)),
    )
    r = cur.fetchone()
    return r[0] if r else None


def leakage(cur, cfg):
    cur.execute(
        "SELECT placed_at, ticker, side, count FROM live_trades WHERE ticker LIKE %s ORDER BY count",
        (cfg["series"] + "%",),
    )
    buckets = {"<=300": [], "301-600": [], ">600": []}
    for placed, tk, side, cnt in cur.fetchall():
        s0 = nearest_after(cur, tk, placed, 0)
        s1 = nearest_after(cur, tk, placed, 15)
        if not s0 or not s1:
            continue
        m0, m1 = mid_at(cur, tk, s0), mid_at(cur, tk, s1)
        if m0 is None or m1 is None:
            continue
        adverse = (m0 - m1) if side == "yes" else (m1 - m0)
        b = "<=300" if cnt <= 300 else ("301-600" if cnt <= 600 else ">600")
        buckets[b].append(adverse)
    out = []
    for b in ["<=300", "301-600", ">600"]:
        xs = buckets[b]
        out.append(dict(bucket=b, n=len(xs),
                        med_adverse_cents=(median(xs) if xs else float("nan")),
                        mean_adverse_cents=(float(np.mean(xs)) if xs else float("nan"))))
    return out


def depth_thinness(signals):
    ahead = [s["ahead"] for s in signals]
    raw = [s["raw_flow"] for s in signals]
    return dict(n=len(signals),
                med_resting_ahead=median(ahead) if ahead else float("nan"),
                med_raw_window_flow=median(raw) if raw else float("nan"))


def _print_curve(curve):
    print(f"  {'N':>6}{'med_fill_rate':>15}{'med_filled':>12}{'p25_filled':>12}{'p75_filled':>12}{'mean_rate':>11}")
    for r in curve:
        print(f"  {r['N']:>6}{r['med_fill_rate']:>15.3f}{r['med_filled']:>12.0f}"
              f"{r['p25_filled']:>12.0f}{r['p75_filled']:>12.0f}{r['mean_fill_rate']:>11.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", required=True, choices=list(STATION_CFG.keys()))
    ap.add_argument("--depth-start", type=date.fromisoformat, default=None)
    ap.add_argument("--depth-end", type=date.fromisoformat, default=None)
    ap.add_argument("--anchor-date", type=date.fromisoformat, default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    cfg = dict(STATION_CFG[args.station])
    cfg["_station"] = args.station
    depth_start = args.depth_start or cfg["depth_start"]
    depth_end = args.depth_end or cfg["depth_end"]

    with get_connection() as conn:
        cur = conn.cursor()
        signals, skips, n_cross, n_rows = build_signals(cur, cfg, depth_start, depth_end)
        sig_flows = [s["net_flow"] for s in signals]
        sig_curve = fill_curve(sig_flows)
        broad = broad_book_flows(cur, cfg, depth_start, depth_end)
        broad_curve = fill_curve(broad)
        anchor = live_anchor(cur, cfg, args.anchor_date)
        leak_table = leakage(cur, cfg)
        thin = depth_thinness(signals)
        cur.close()

    L = print
    L("=" * 88)
    L(f"{args.station} ({cfg['city']}) MAKER FILL-RATE vs POSTED SIZE — does 500 -> 1000 double FILLED?")
    L("=" * 88)
    mode = ("UNION raw>=%.0f%% OR blend>=%.0f%%" % (cfg["raw_thr"] * 100, cfg["blend_thr"] * 100)
            if cfg["use_union"] else "BLEND-only >=%.0f%%" % (cfg["blend_thr"] * 100))
    L(f"filter: {mode}   smart_cross>= {cfg['smart_cross_thr']:.0%}   "
      f"decision {cfg['decision_hour']:02d}:{cfg['decision_min']:02d}Z")
    L(f"Window: {depth_start} -> {depth_end} (DIRECTIONAL). NO TRADE TAPE — flow INFERRED from")
    L(f"price-anchored bid-ladder depletion (~5-min cadence). SHAPE (500 vs 1000) is the finding.")
    L("")
    L(f"SIGNAL UNIVERSE: paper rows {n_rows} -> signals {len(signals)} (skipped {len(skips)})")
    n = max(1, len(signals))
    L(f"  CROSS (|edge|>= smart_cross={cfg['smart_cross_thr']:.0%}): {n_cross}/{len(signals)} = {100*n_cross/n:.0f}%")
    L(f"  POST/maker: {len(signals)-n_cross}/{len(signals)} = {100*(len(signals)-n_cross)/n:.0f}%  "
      f"(the maker curve is directly relevant to this POST fraction)")
    srcs = {}
    for s in signals:
        srcs[s["sig_src"]] = srcs.get(s["sig_src"], 0) + 1
    L(f"  sources: {srcs}")
    L("")
    if signals:
        L("  per-signal (maker book at decision time):")
        L(f"  {'date':<11}{'bracket':<9}{'side':<8}{'edge':>8}{'bid':>5}{'ahead':>7}{'netflow':>9}{'cross?':>7}")
        for s in signals:
            L(f"  {str(s['date']):<11}{s['ticker'].split('-')[-1]:<9}{s['side']:<8}"
              f"{s['decision_edge']:>+8.3f}{s['best_bid']:>5}{s['ahead']:>7}{s['net_flow']:>9}"
              f"{'cross' if s['is_cross'] else 'post':>7}")
    L("")
    L("MAKER FILL CURVE — sample A: signal days (n=%d, directly relevant, self-polluted)" % len(sig_flows))
    L("-" * 88)
    _print_curve(sig_curve)
    L("")
    L("MAKER FILL CURVE — sample B: ALL %s brackets (n=%d, clean, larger-n cross-check)" % (cfg["series"], len(broad)))
    L("-" * 88)
    _print_curve(broad_curve)
    L("")

    def filled_at(curve, N):
        return next(r["med_filled"] for r in curve if r["N"] == N)
    hl_sig = filled_at(sig_curve, 1000) / filled_at(sig_curve, 500) if filled_at(sig_curve, 500) else float("nan")
    hl_brd = filled_at(broad_curve, 1000) / filled_at(broad_curve, 500) if filled_at(broad_curve, 500) else float("nan")
    L("HEADLINE — filled(1000)/filled(500)  (2.0 = clean scale, <1.3 = marginal 500 starves)")
    L("-" * 88)
    L(f"  signal-day sample : {hl_sig:.2f}x")
    L(f"  broad-book sample : {hl_brd:.2f}x")
    L("")
    L("VALIDATION vs live_trades realized fills")
    L("-" * 88)
    c = anchor["current"]
    L(f"  current (all {cfg['city']} live orders): n={c['n']} orders, "
      f"{c['filled']}/{c['posted']} contracts = {c['pct_contracts']:.1f}%")
    if anchor["as_of"] is not None:
        a = anchor["as_of"]
        L(f"  as-of {anchor['anchor_date']}: n={a['n']} orders, "
          f"{a['filled']}/{a['posted']} contracts = {a['pct_contracts']:.1f}%")
    cr, mk = anchor["cross"], anchor["maker"]
    L(f"  CROSS (taker; limit==cross): n={cr['n']}, {cr['pct_contracts']:.1f}% filled")
    L(f"  MAKER (post; limit<>cross):  n={mk['n']}, {mk['pct_contracts']:.1f}% filled")
    L("")
    L("LEAKAGE / ADVERSE SELECTION — 15-min post-order mid-move by posted-size bucket")
    L("-" * 88)
    L(f"  {'bucket':<10}{'n':>4}{'med_adverse':>13}{'mean_adverse':>14}  (+ = mid moved AGAINST us)")
    for r in leak_table:
        ma = f"{r['med_adverse_cents']:.1f}" if not math.isnan(r["med_adverse_cents"]) else "--"
        me = f"{r['mean_adverse_cents']:.1f}" if not math.isnan(r["mean_adverse_cents"]) else "--"
        L(f"  {r['bucket']:<10}{r['n']:>4}{ma:>13}{me:>14}")
    L(f"  book-thinness proxy: median resting-ahead={thin['med_resting_ahead']:.0f}, "
      f"median raw window-flow at our level={thin['med_raw_window_flow']:.0f} contracts.")
    L("")
    L("CAVEATS: directional window (orderbook since 2026-06-10); NO trade tape (flow inferred,")
    L("churn-suppressed but a proxy); queue model subtracts resting-ahead; signal-day n is small +")
    L("self-polluted by our own orders (broad-book is the larger, cleaner cross-check).")

    if args.json:
        payload = dict(
            station=args.station, city=cfg["city"], window=[str(depth_start), str(depth_end)],
            n_rows=n_rows, n_signals=len(signals), n_cross=n_cross,
            signal_curve=sig_curve, broad_curve=broad_curve,
            headline_signal=hl_sig, headline_broad=hl_brd,
            anchor=anchor, leakage=leak_table, thinness=thin,
            signals=[{k: (str(v) if isinstance(v, date) else v) for k, v in s.items()} for s in signals],
        )
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        L(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
