"""Entry-timing decay study — is there a better intraday ENTRY TIME than the
current per-city decision times?

Current live decision times (UTC): KORD 14:46, KMIA 15:30, KDFW 17:32.

CORE HYPOTHESIS (from the Miami walk-book, 55c->61c repricing): the market
reprices TOWARD our 00Z forecast through the morning, so we may be entering
LATE and forfeiting edge that was larger earlier. Against that: entering earlier
means a thinner book (worse fills). This script finds the risk-adjusted sweet
spot per city.

WHY EARLIER-ENTRY EDGE IS REAL, NOT HINDSIGHT (the key validity point)
---------------------------------------------------------------------
`model_prob_yes` in paper_trades is a SINGLE value per (target_date, ticker),
fit ONCE from the 00Z ensemble (forecast_init_time hour == 0 for every row;
COUNT(DISTINCT model_prob_yes) == row count). It does NOT update at 06Z/12Z.
The 00Z ensemble is fully ingested by ~07:00 UTC (GEFS 06:15, IFS 07:00,
HRRR 03:30) and the EMOS rolling-45d fit uses only prior-day settled data.
=> For ANY candidate entry time >= ~07:30 UTC (our earliest grid point is
   11:00 for KORD), the model_p we would have used earlier is IDENTICAL to the
   one used at the current decision time. So the entire edge change across the
   morning is MARKET-driven (the market moving toward/away from our fixed
   forecast), and capturing it earlier is legitimately executable. This removes
   the usual staleness/lookahead threat. (Moving a decision before ~07:30 UTC
   would break this — flagged, but out of grid.)

DATA CADENCE (drives the grid design)
-------------------------------------
`prices` (top-of-book) is HOURLY on the top-of-hour across the full history
(2025-05 -> 2026-05) and only went to 5-min cadence on 2026-06-04. So for a
long-history, apples-to-apples decay/P&L comparison the candidate grid uses
ABSOLUTE UTC HOUR marks (consistent coverage every day) PLUS the exact decision
time T0, whose market bid/ask/mid is read straight from paper_trades
(market_yes_bid/ask/mid_prob at market_snapshot_at). `orderbook_snapshots`
(depth) is 5-min but only covers 2026-06-10 -> 2026-07-05 (26 days).

WHAT IT COMPUTES
----------------
A) EDGE-DECAY CURVE (long history, prices + paper T0): median |raw edge| and
   |blend edge| at each candidate time over the decision-fired universe, plus
   the market-mid level. Answers: does the market reprice toward us before T0?
B) MAKER FILL + POST-SIDE DEPTH (26-day orderbook): per-candidate maker-flow
   fill inference (miami_fill_rate method, ALWAYS posting at own-side touch,
   independent of smart-exec) + near-money depth. Validates the ~52% KMIA /
   ~90% KORD anchors and shows whether the book is materially thinner earlier.
   Fill window = entry -> 20:00 UTC (production cancel time).
C) NET P&L + SHARPE GRID:
   C1 GROSS (long history, 100% fill, production smart-exec entry price):
      isolates the EDGE effect of entry time on P&L/Sharpe. Primary.
   C2 FILL-ADJUSTED (26-day orderbook): inferred maker fill on posted legs +
      near-money depth cap on crossed legs. Secondary, small-sample/DIRECTIONAL.

UNIVERSE / SCOPE CAVEAT
-----------------------
paper_trades logs only DECISION-TIME-FIRED signals, so model_p exists only for
those contracts. We trace that universe across entry times (does an earlier
entry help the trades we take?). We do NOT try to discover brackets that fire
ONLY earlier (their model_p was never logged) — that means re-running
paper_trade_log across the morning, out of scope.

READ-ONLY. Places no orders, changes no cron/config. Sharpe mirrors
scripts/analysis/dallas_watchlist.py (per-day P&L, annualized by realized trade
frequency; deploy bar 2.5).

    uv run python scripts/analysis/entry_timing_decay.py
    uv run python scripts/analysis/entry_timing_decay.py --city KMIA
    uv run python scripts/analysis/entry_timing_decay.py --json /tmp/entry_timing.json
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean, median, stdev

import numpy as np

from weather_markets.db import get_connection
from weather_markets.blend import walkforward_blends, apply_blend

# --- config -----------------------------------------------------------------
CITIES = {
    "KORD": dict(
        city="Chicago", series="KXHIGHCHI",
        model_source="EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        decision=(14, 46), strategy="union",
        raw_thr=0.25, blend_thr=0.10, smart_cross=0.40,
        max_signals=2, unit=500, size_edge_cap=0.40,
        abs_hours=[11, 12, 13, 14, 15, 16],
    ),
    "KMIA": dict(
        city="Miami", series="KXHIGHMIA",
        model_source="EMOS combined 00Z Miami (rolling 45d)",
        decision=(15, 30), strategy="blend",
        raw_thr=1.00, blend_thr=0.10, smart_cross=0.10,
        max_signals=1, unit=500, size_edge_cap=0.40,
        abs_hours=[12, 13, 14, 15, 16, 17],
    ),
    "KDFW": dict(
        city="Dallas", series="KXHIGHTDAL",
        model_source="EMOS combined 00Z Dallas (rolling 45d)",
        decision=(17, 32), strategy="union",
        raw_thr=0.25, blend_thr=0.10, smart_cross=0.40,
        max_signals=99, unit=500, size_edge_cap=0.40,
        abs_hours=[14, 15, 16, 17, 18, 19],
    ),
}

PRICE_TOL_MIN = 15                 # nearest `prices` snapshot within this many min
BOOK_TOL_MIN = 20                  # nearest orderbook snapshot within this many min
FILL_DEADLINE = time(20, 0)        # monitor_fills --cancel-unfilled at 20:00 UTC
DEPTH_START = date(2026, 6, 10)    # orderbook_snapshots coverage
DEPTH_END = date(2026, 7, 5)
ANCHOR = {"KMIA": 0.52, "KORD": 0.90}   # forward-test fill anchors to sanity-check


# --- candidate grid ---------------------------------------------------------
def decision_dt(cfg, d: date) -> datetime:
    hh, mm = cfg["decision"]
    return datetime.combine(d, time(hh, mm), tzinfo=timezone.utc)


def candidate_specs(cfg):
    """Ordered list of {label, kind, hour, off_min} by offset-from-decision."""
    dmin = cfg["decision"][0] * 60 + cfg["decision"][1]
    specs = [dict(label=f"{h:02d}:00", kind="hour", hour=h, off_min=h * 60 - dmin)
             for h in cfg["abs_hours"]]
    specs.append(dict(label="DEC", kind="dec", hour=None, off_min=0))
    specs.sort(key=lambda s: s["off_min"])
    return specs


# --- primitives -------------------------------------------------------------
def kalshi_fee_cents(entry_price_cents: int, maker: bool) -> int:
    """Entry fee in cents. Maker = 1/4 of taker. Mirrors live_trade.kalshi_fee_cents."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    rate = 0.0175 if maker else 0.07
    return max(1, math.ceil(rate * p * (1.0 - p) * 100))


def yes_wins(bracket_type: str, sl, sh, high: int) -> bool:
    if bracket_type == "greater_than":
        return high > sl
    if bracket_type == "less_than":
        return high < sh
    if bracket_type == "between":
        return sl <= high <= sh
    return False


# --- order-book primitives (reused from walk_book_miami / miami_fill_rate) ---
def ladders_at(cur, ticker, snap):
    cur.execute(
        "SELECT side, price_cents, qty FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at=%s",
        (ticker, snap),
    )
    yl, nl = [], []
    for side, pc, q in cur.fetchall():
        (yl if side == "yes" else nl).append((int(pc), int(q)))
    return yl, nl


def nearest_book_snapshot(cur, ticker, target_ts, d):
    d0 = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
    d1 = d0 + timedelta(days=1)
    cur.execute(
        """SELECT snapshot_at, abs(extract(epoch FROM (snapshot_at-%s)))/60.0 off_min
           FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at>=%s AND snapshot_at<%s
           ORDER BY off_min ASC LIMIT 1""",
        (target_ts, ticker, d0, d1),
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
    Price-anchored, churn-suppressing. Returns (net_past_queue, raw_to_level)."""
    tss = sorted(series.keys())
    raw = 0
    for a, b in zip(tss, tss[1:]):
        la, lb = series[a], series[b]
        if not la:
            continue
        bb = max(la.keys())
        bb2 = max(lb.keys()) if lb else 0
        if bb > post_price:      # market trading above our post -> buried, no fill
            continue
        if bb2 > bb:             # reprice-up -> new flow, not a hit on the old touch
            continue
        raw += max(0, la.get(bb, 0) - lb.get(bb, 0))
    return max(0, raw - ahead_qty), raw


# --- signal firing (mirrors live_trade union / blend logic) -----------------
def evaluate(cfg, model_p, mid, fit):
    """Return dict(side, decision_p, edge_mag, leg, raw_mag, blend_mag) or None."""
    raw_edge = model_p - mid
    raw_mag = abs(raw_edge)
    raw_fires = (cfg["strategy"] in ("union", "raw")) and raw_mag >= cfg["raw_thr"]

    blend_p = blend_mag = None
    blend_fires = False
    if fit is not None:
        blend_p = float(apply_blend(fit, model_p, mid))
        blend_mag = abs(blend_p - mid)
        blend_fires = (cfg["strategy"] in ("union", "blend")) and blend_mag >= cfg["blend_thr"]

    if cfg["strategy"] == "union":
        if not (raw_fires or blend_fires):
            return None
        if raw_fires:
            dp, mag, leg = model_p, raw_mag, ("raw" if not blend_fires else "both")
        else:
            dp, mag, leg = blend_p, blend_mag, "blend-only"
    elif cfg["strategy"] == "blend":
        if not blend_fires:
            return None
        dp, mag, leg = blend_p, blend_mag, "blend-only"
    else:  # raw
        if not raw_fires:
            return None
        dp, mag, leg = model_p, raw_mag, "raw"

    side = "BUY_YES" if dp > mid else "BUY_NO"
    return dict(side=side, decision_p=dp, edge_mag=mag, leg=leg,
                raw_mag=raw_mag, blend_mag=blend_mag)


def entry_price_cents(side, yes_bid, yes_ask, cross):
    if side == "BUY_YES":
        return yes_ask if cross else yes_bid
    return (100 - yes_bid) if cross else (100 - yes_ask)


def size_contracts(cfg, edge_mag):
    scale = min(1.0, cfg["size_edge_cap"] / max(edge_mag, 0.01))
    return int(round(cfg["unit"] * scale))


# --- metrics (mirror dallas_watchlist.compute_metrics) ----------------------
def compute_metrics(trades):
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
    sharpe = None
    if n_days >= 3:
        sd = stdev(pnls)
        if sd > 0:
            span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
            years = span / 365.25 if span > 0 else 0
            ppy = (n_days / years) if years > 0 else 0
            if ppy > 0:
                sharpe = (mean(pnls) / sd) * math.sqrt(ppy)
    wins = sum(1 for t in trades if t["net"] > 0)
    return dict(
        n_trades=len(trades), n_days=n_days, net_dollars=profit / 100.0,
        max_dd_dollars=maxdd / 100.0, sharpe=sharpe,
        win_rate=wins / len(trades), cents_per_trade=profit / len(trades),
    )


# --- data loading -----------------------------------------------------------
def load_universe(conn, cfg, start_d, end_d):
    """Decision-time fired paper_trades joined to strikes + observed high.
    Carries the real decision-time bid/ask/mid (market_snapshot_at)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT pt.target_date, pt.ticker, pt.model_prob_yes,
                      pt.market_yes_bid, pt.market_yes_ask, pt.market_mid_prob,
                      c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
               FROM paper_trades pt
               JOIN contracts c ON c.ticker = pt.ticker
               LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                 WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
               WHERE pt.model_source=%s AND pt.target_date BETWEEN %s AND %s
               ORDER BY pt.target_date, pt.ticker""",
            (cfg["model_source"], start_d, end_d),
        )
        rows = []
        for td, tk, mp, yb, ya, mid, bt, sl, sh, high in cur.fetchall():
            rows.append(dict(
                d=td, ticker=tk, model_p=float(mp),
                yb_dec=(int(yb) if yb is not None else None),
                ya_dec=(int(ya) if ya is not None else None),
                mid_dec=(float(mid) if mid is not None else None),
                bt=bt, sl=sl, sh=sh, high=(int(high) if high is not None else None),
            ))
    return rows


def load_price_series(conn, tickers, start_d, end_d):
    """{(ticker, date): sorted [(ts, yes_bid, yes_ask)]} for same-day snapshots."""
    idx = defaultdict(list)
    if not tickers:
        return idx
    with conn.cursor() as cur:
        cur.execute(
            """SELECT ticker, snapshot_at, yes_bid, yes_ask FROM prices
               WHERE ticker = ANY(%s) AND snapshot_at::date BETWEEN %s AND %s
                 AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL
               ORDER BY ticker, snapshot_at""",
            (list(tickers), start_d, end_d),
        )
        for tk, ts, yb, ya in cur.fetchall():
            yb, ya = int(yb), int(ya)
            if yb > ya:            # locked/crossed book — skip
                continue
            idx[(tk, ts.astimezone(timezone.utc).date())].append((ts, yb, ya))
    return idx


def bidask_at(series, key, want_ts, tol_min=PRICE_TOL_MIN):
    arr = series.get(key)
    if not arr:
        return None
    best = min(arr, key=lambda r: abs((r[0] - want_ts).total_seconds()))
    if abs((best[0] - want_ts).total_seconds()) > tol_min * 60:
        return None
    return best[1], best[2]        # yes_bid, yes_ask


def bidask_for_spec(cfg, row, spec, price_idx):
    """(yes_bid, yes_ask) for this row at this candidate, or None."""
    if spec["kind"] == "dec":
        if row["yb_dec"] is None or row["ya_dec"] is None or row["yb_dec"] > row["ya_dec"]:
            return None
        return row["yb_dec"], row["ya_dec"]
    want = datetime.combine(row["d"], time(spec["hour"], 0), tzinfo=timezone.utc)
    return bidask_at(price_idx, (row["ticker"], row["d"]), want)


def target_dt_for_spec(cfg, row, spec):
    if spec["kind"] == "dec":
        return decision_dt(cfg, row["d"])
    return datetime.combine(row["d"], time(spec["hour"], 0), tzinfo=timezone.utc)


# --- Analysis A: edge decay curve -------------------------------------------
def analysis_decay(cfg, universe, price_idx, blends, specs):
    acc = {s["label"]: dict(raw=[], blend=[], mid=[]) for s in specs}
    for r in universe:
        fit = blends.get(r["d"])
        for s in specs:
            ba = bidask_for_spec(cfg, r, s, price_idx)
            if ba is None:
                continue
            yb, ya = ba
            mid = (yb + ya) / 200.0
            acc[s["label"]]["raw"].append(abs(r["model_p"] - mid))
            acc[s["label"]]["mid"].append(mid)
            if fit is not None:
                bp = float(apply_blend(fit, r["model_p"], mid))
                acc[s["label"]]["blend"].append(abs(bp - mid))
    out = []
    for s in specs:
        b = acc[s["label"]]
        out.append(dict(
            label=s["label"], off=s["off_min"], n=len(b["raw"]),
            med_raw=(median(b["raw"]) if b["raw"] else None),
            med_blend=(median(b["blend"]) if b["blend"] else None),
            med_mid=(median(b["mid"]) if b["mid"] else None),
        ))
    return out


# --- Analysis C1: gross P&L / Sharpe grid (long history) --------------------
def analysis_grid_gross(cfg, universe, price_idx, blends, specs):
    grid = {}
    for s in specs:
        by_day = defaultdict(list)
        for r in universe:
            if r["high"] is None:
                continue
            ba = bidask_for_spec(cfg, r, s, price_idx)
            if ba is None:
                continue
            yb, ya = ba
            mid = (yb + ya) / 200.0
            ev = evaluate(cfg, r["model_p"], mid, blends.get(r["d"]))
            if ev is None:
                continue
            cross = ev["edge_mag"] >= cfg["smart_cross"]
            entry = entry_price_cents(ev["side"], yb, ya, cross)
            if entry <= 0 or entry >= 100:
                continue
            fee = kalshi_fee_cents(entry, maker=(not cross))
            won = ((ev["side"] == "BUY_YES") == yes_wins(r["bt"], r["sl"], r["sh"], r["high"]))
            pnl_c = (100 - entry - fee) if won else (-entry - fee)
            n = size_contracts(cfg, ev["edge_mag"])
            by_day[r["d"].isoformat()].append(dict(edge=ev["edge_mag"], net=n * pnl_c, leg=ev["leg"]))
        trades = []
        for iso, sigs in by_day.items():
            sigs.sort(key=lambda x: -x["edge"])
            for x in sigs[: cfg["max_signals"]]:
                trades.append(dict(date=iso, net=x["net"], leg=x["leg"]))
        grid[s["label"]] = compute_metrics(trades)
    return grid


# --- Analysis B + C2: fill inference + fill-adjusted grid (26-day) ----------
def analysis_fill_and_grid(conn, cfg, universe, price_idx, blends, specs):
    uni = [r for r in universe if DEPTH_START <= r["d"] <= DEPTH_END and r["high"] is not None]
    fill_by = {s["label"]: [] for s in specs}     # maker-post fill (always post)
    depth_by = {s["label"]: [] for s in specs}    # near-money post-side depth
    adj_by = {s["label"]: defaultdict(list) for s in specs}

    with conn.cursor() as cur:
        for r in uni:
            fit = blends.get(r["d"])
            deadline = datetime.combine(r["d"], FILL_DEADLINE, tzinfo=timezone.utc)
            for s in specs:
                ba = bidask_for_spec(cfg, r, s, price_idx)
                if ba is None:
                    continue
                yb, ya = ba
                mid = (yb + ya) / 200.0
                ev = evaluate(cfg, r["model_p"], mid, fit)
                if ev is None:
                    continue
                want = target_dt_for_spec(cfg, r, s)
                snap, off = nearest_book_snapshot(cur, r["ticker"], want, r["d"])
                if snap is None or off > BOOK_TOL_MIN:
                    continue
                yl, nl = ladders_at(cur, r["ticker"], snap)
                buy_yes = ev["side"] == "BUY_YES"
                own = yl if buy_yes else nl
                if not own:
                    continue
                n = size_contracts(cfg, ev["edge_mag"])

                # ---- maker-post fill (ALWAYS, for the liquidity table B) ----
                best_bid = max(p for p, _ in own)
                ahead = dict(own).get(best_bid, 0)
                ser = bid_series(cur, r["ticker"], "yes" if buy_yes else "no", snap, deadline)
                net_flow, _ = maker_flow_to_us(ser, best_bid, ahead)
                post_fill = min(1.0, net_flow / n) if n else 0.0
                fill_by[s["label"]].append(post_fill)
                depth_by[s["label"]].append(sum(q for _, q in sorted(own, key=lambda x: -x[0])[:3]))

                # ---- fill-adjusted P&L (smart-exec: cross vs post) ----------
                cross = ev["edge_mag"] >= cfg["smart_cross"]
                if cross:
                    opp = nl if buy_yes else yl
                    avail = sum(q for _, q in sorted(opp, key=lambda x: -x[0])[:3])
                    fill_frac = min(1.0, avail / n) if n else 0.0
                    entry = entry_price_cents(ev["side"], yb, ya, cross=True)
                    maker = False
                else:
                    fill_frac = post_fill
                    entry = entry_price_cents(ev["side"], yb, ya, cross=False)
                    maker = True
                if entry <= 0 or entry >= 100:
                    continue
                fee = kalshi_fee_cents(entry, maker=maker)
                won = (buy_yes == yes_wins(r["bt"], r["sl"], r["sh"], r["high"]))
                pnl_c = (100 - entry - fee) if won else (-entry - fee)
                filled = int(round(n * fill_frac))
                adj_by[s["label"]][r["d"].isoformat()].append(
                    dict(edge=ev["edge_mag"], net=filled * pnl_c, leg=ev["leg"]))

    fill_rows = []
    for s in specs:
        fr, dp = fill_by[s["label"]], depth_by[s["label"]]
        fill_rows.append(dict(
            label=s["label"], off=s["off_min"], n=len(fr),
            med_fill=(median(fr) if fr else None),
            mean_fill=(float(np.mean(fr)) if fr else None),
            med_depth=(median(dp) if dp else None),
        ))
    adj_grid = {}
    for s in specs:
        trades = []
        for iso, sigs in adj_by[s["label"]].items():
            sigs.sort(key=lambda x: -x["edge"])
            for x in sigs[: cfg["max_signals"]]:
                trades.append(dict(date=iso, net=x["net"], leg=x["leg"]))
        adj_grid[s["label"]] = compute_metrics(trades)
    return fill_rows, adj_grid


# --- reporting --------------------------------------------------------------
def lbl(s_label, off):
    tag = "*" if s_label == "DEC" else " "
    disp = "DEC " if s_label == "DEC" else s_label
    return f"{disp}{tag}({off:+4d}m)"


def sh(x):
    return "n/a" if x is None else f"{x:.2f}"


def pct(v, w=5, d=1):
    return f"{'-':>{w + 1}}" if v is None else f"{v * 100:{w}.{d}f}%"


def run_city(conn, code, args):
    cfg = CITIES[code]
    specs = candidate_specs(cfg)
    print("\n" + "=" * 82)
    print(f"  {code} ({cfg['city']})  decision {cfg['decision'][0]:02d}:{cfg['decision'][1]:02d} UTC"
          f"  |  {cfg['strategy']}  unit={cfg['unit']}  smart_cross={cfg['smart_cross']:.2f}"
          f"  blend_thr={cfg['blend_thr']:.2f}")
    print("=" * 82)

    universe = load_universe(conn, cfg, args.start, args.end)
    tickers = {r["ticker"] for r in universe}
    dmin = min((r["d"] for r in universe), default=args.start)
    price_idx = load_price_series(conn, tickers, dmin, args.end)
    blends = walkforward_blends(code, cfg["city"], cfg["model_source"])
    n_settled = sum(1 for r in universe if r["high"] is not None)
    print(f"  universe: {len(universe)} decision-fired signals ({n_settled} settled)  "
          f"{dmin} -> {args.end}   [DEC = current live decision time]")

    decay = analysis_decay(cfg, universe, price_idx, blends, specs)
    print("\n  A) EDGE DECAY (median over decision-fired universe; model_p fixed = 00Z run)")
    base = next(x for x in decay if x["label"] == "DEC")
    print("     candidate         n   med|raw|  vs_DEC   med|blend|   med_mid")
    for x in decay:
        if x["med_raw"] is not None and base["med_raw"] is not None:
            dv = f"{(x['med_raw'] - base['med_raw']) * 100:+5.1f}pp"
        else:
            dv = "   -   "
        print(f"    {lbl(x['label'], x['off']):>14} {x['n']:5d}   {pct(x['med_raw'])}  {dv}   "
              f"{pct(x['med_blend'])}     {pct(x['med_mid'])}")

    gross = analysis_grid_gross(cfg, universe, price_idx, blends, specs)
    print("\n  C1) GROSS P&L/SHARPE by entry time (long history, 100% fill, smart-exec price)")
    print("     candidate        trades  days    net$   c/trade  win%  Sharpe  maxDD$")
    for s in specs:
        m = gross[s["label"]]
        if m is None:
            print(f"    {lbl(s['label'], s['off_min']):>14}     (no trades)")
            continue
        print(f"    {lbl(s['label'], s['off_min']):>14}  {m['n_trades']:5d} {m['n_days']:5d} "
              f"{m['net_dollars']:8.0f} {m['cents_per_trade']:+8.1f} {m['win_rate'] * 100:4.0f}%  "
              f"{sh(m['sharpe']):>6} {m['max_dd_dollars']:7.0f}")

    fill_rows, adj = analysis_fill_and_grid(conn, cfg, universe, price_idx, blends, specs)
    print("\n  B) MAKER-POST FILL + POST-SIDE DEPTH by entry time (26-day orderbook; ->20:00)")
    print("     candidate         n   med_fill  mean_fill  med_depth(3lvl)")
    for x in fill_rows:
        pd = "     -" if x["med_depth"] is None else f"{x['med_depth']:6.0f}"
        print(f"    {lbl(x['label'], x['off']):>14} {x['n']:4d}    {pct(x['med_fill'], 4, 0)}     "
              f"{pct(x['mean_fill'], 4, 0)}        {pd}")
    anchor = ANCHOR.get(code)
    bf = next((x for x in fill_rows if x["label"] == "DEC"), None)
    if anchor is not None and bf and bf["med_fill"] is not None:
        print(f"     anchor check @DEC: inferred med_fill={bf['med_fill'] * 100:.0f}% "
              f"vs forward-test ~{anchor * 100:.0f}% (forward-test used ->EOD; ->20:00 reads lower)")

    print("\n  C2) FILL-ADJUSTED P&L/SHARPE by entry time (26-day window; DIRECTIONAL)")
    print("     candidate        trades  days    net$   c/trade  win%  Sharpe")
    for s in specs:
        m = adj[s["label"]]
        if m is None:
            print(f"    {lbl(s['label'], s['off_min']):>14}     (no trades)")
            continue
        print(f"    {lbl(s['label'], s['off_min']):>14}  {m['n_trades']:5d} {m['n_days']:5d} "
              f"{m['net_dollars']:8.0f} {m['cents_per_trade']:+8.1f} {m['win_rate'] * 100:4.0f}%  "
              f"{sh(m['sharpe']):>6}")

    return dict(code=code, decay=decay, gross=gross, fill=fill_rows, adj=adj,
                n_universe=len(universe), n_settled=n_settled)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", choices=list(CITIES), help="single city (default: all)")
    ap.add_argument("--start", type=date.fromisoformat, default=date(2025, 1, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--json", help="write machine-readable results here")
    args = ap.parse_args()

    codes = [args.city] if args.city else list(CITIES)
    print("ENTRY-TIMING DECAY STUDY  (read-only; DEC* = current live decision time)")
    print(f"window {args.start} -> {args.end}  |  grid = absolute UTC hours + exact DEC  |  "
          f"fill deadline 20:00 UTC")
    results = {}
    with get_connection() as conn:
        for code in codes:
            results[code] = run_city(conn, code, args)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
