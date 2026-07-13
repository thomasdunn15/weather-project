"""POST vs CROSS, per city, on that city's own history — read-only.

Rebuilds the live signal set for each city from `paper_trades` (using the SAME
threshold rule live_trade.py uses, read out of CITY_CONFIG — nothing hardcoded),
prices every execution mode with live_trade's own limit-price logic, and decides
fills EMPIRICALLY from the `prices` snapshot history.

Fill rule (resting limit order placed at the city's decision time, live until the
20:00 UTC `monitor_fills --cancel-unfilled` cron):
  BUY YES @ L  -> filled iff min(yes_ask) <= L over the window
  BUY NO  @ L  -> NO ask = 100 - yes_bid, so filled iff max(yes_bid) >= 100 - L
  cross_at_ask / cross_with_premium -> taker on existing depth -> filled

Why those are the right observables: a resting BUY-YES bid at L can only be lifted
by an incoming seller, and the seller's presence shows up as the best offer
touching L (a book cannot quote an ask below a resting bid without them trading).
Symmetrically for NO. Neither observable is contaminated by our own order: a
resting YES bid moves `yes_bid`, not `yes_ask`; a resting NO bid moves `yes_ask`,
not `yes_bid`. So the rule reads the *other* side of the book in both cases.

LIMITATION: this is a PRICE fill model, not a SIZE/depth fill model. It answers
"did the market trade through my limit", not "was there enough size there".
A crossing order into a thin book still partially fills (KPHX, 83/250 live).

Usage:  uv run python scripts/analysis/exec_mode_compare.py [--city KORD] [--gate-only]
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from datetime import datetime, time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # src/

from live_trade import (  # noqa: E402  - the production logic, imported not copied
    CITY_CONFIG,
    SMART_CROSS_EDGE_THRESHOLD,
    kalshi_fee_cents,
    resolve_exec_path,
)
from weather_markets.blend import walkforward_blends  # noqa: E402
from weather_markets.db import get_connection  # noqa: E402
from weather_markets.evaluation import contract_resolved_yes  # noqa: E402

CITIES = ["KORD", "KMIA", "KDFW", "KPHX"]
MODES = ["post_inside_spread", "cross_at_ask", "cross_with_premium_1", "smart_live"]
CANCEL_HOUR_UTC = 20  # monitor_fills.py --cancel-unfilled runs `0 20 * * *`
SNAP_TOLERANCE_MIN = 20  # decision-time book = last snapshot within this lookback


# --- live_trade.py:754-775, verbatim behaviour (the block is inline in the cron,
# --- not a function, so it cannot be imported; kept byte-faithful, incl. the
# --- spread<=1 fallback to crossing and the 1..99 clamp.
def limit_price_for(exec_path: str, side: str, bid: int, ask: int, premium: int = 0) -> tuple[int, int, bool]:
    """-> (limit_price, cross_entry, post_only_safe)"""
    spread = int(ask) - int(bid)
    cross_entry = int(ask) if side == "yes" else 100 - int(bid)
    if exec_path == "post_inside_spread":
        if spread > 1:
            limit_price = cross_entry - (spread - 1)
            post_only_safe = True
        else:
            limit_price = cross_entry
            post_only_safe = False
    elif exec_path == "cross_at_ask":
        limit_price = cross_entry
        post_only_safe = False
    elif exec_path == "cross_with_premium":
        limit_price = cross_entry + premium
        post_only_safe = False
    else:
        raise ValueError(f"unknown exec_path {exec_path!r}")
    return max(1, min(99, limit_price)), cross_entry, post_only_safe


RELAX = 0  # cents of slack on the fill test; see --relax (sensitivity, not the base case)


def would_fill(side: str, limit: int, min_ask, max_bid) -> bool:
    """RELAX>0 loosens the test by N cents. The gate's errors are ALL false
    negatives (real maker orders that filled without the 5-min top-of-book ever
    printing through our limit), so RELAX=1 gives an UPPER bound on POST's fill
    rate — the sensitivity case that favours posting."""
    if side == "yes":
        return min_ask is not None and min_ask <= limit + RELAX
    return max_bid is not None and max_bid >= (100 - limit - RELAX)


def decision_ts(cfg: dict, target_date) -> datetime:
    return datetime.combine(
        target_date, time(cfg["decision_hour"], cfg["decision_minute"]), tzinfo=timezone.utc
    )


def end_ts(target_date) -> datetime:
    return datetime.combine(target_date, time(CANCEL_HOUR_UTC, 0), tzinfo=timezone.utc)


# ---------------------------------------------------------------- data pulls
def fetch_book_windows(conn, rows: list[tuple]) -> tuple[dict, dict]:
    """rows = [(ticker, decision_ts, end_ts)] -> (touch_at_decision, window_extremes)"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH sig(ticker, dts, ets) AS (SELECT * FROM unnest(
                    %s::text[], %s::timestamptz[], %s::timestamptz[]))
            SELECT s.ticker, p.yes_bid, p.yes_ask, p.snapshot_at
            FROM sig s
            LEFT JOIN LATERAL (
                SELECT yes_bid, yes_ask, snapshot_at FROM prices
                WHERE ticker = s.ticker AND snapshot_at <= s.dts
                  AND snapshot_at > s.dts - (%s || ' minutes')::interval
                ORDER BY snapshot_at DESC LIMIT 1
            ) p ON TRUE
            """,
            ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows],
             str(SNAP_TOLERANCE_MIN)),
        )
        touch = {t: (b, a, s) for t, b, a, s in cur.fetchall() if b is not None and a is not None}

        cur.execute(
            """
            WITH sig(ticker, dts, ets) AS (SELECT * FROM unnest(
                    %s::text[], %s::timestamptz[], %s::timestamptz[]))
            SELECT s.ticker, min(p.yes_ask), max(p.yes_bid), count(p.*)
            FROM sig s
            LEFT JOIN prices p ON p.ticker = s.ticker
                 AND p.snapshot_at > s.dts AND p.snapshot_at <= s.ets
            GROUP BY s.ticker
            """,
            ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]),
        )
        window = {t: (mn, mx, n) for t, mn, mx, n in cur.fetchall()}
    return touch, window


def fetch_signals(conn, city: str) -> list[dict]:
    """Live signal set for `city`, rebuilt from paper_trades + decision-time book."""
    cfg = CITY_CONFIG[city]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pt.target_date, pt.ticker, pt.model_prob_yes,
                   c.bracket_type, c.strike_low, c.strike_high, c.station_id, c.series,
                   o.high_temp_f, o.low_temp_f
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            LEFT JOIN observations o ON o.date = pt.target_date AND o.station_id = c.station_id
            WHERE pt.model_source = %s
            ORDER BY pt.target_date, pt.ticker
            """,
            (cfg["paper_model_source"],),
        )
        raw = cur.fetchall()

    keys = [(tk, decision_ts(cfg, td), end_ts(td)) for td, tk, *_ in raw]
    touch, window = fetch_book_windows(conn, keys)

    blends = walkforward_blends(city, cfg["city_name"], paper_model_source=cfg["paper_model_source"])
    raw_thresh = cfg["edge_threshold"]
    blend_thresh = cfg["blend_edge_threshold"]
    use_union, use_blend = cfg["use_union"], cfg["use_blend"]

    sigs, dropped_nobook, dropped_noobs = [], 0, 0
    for td, tk, model_p, bt, sl, sh, station, series, high, low in raw:
        if tk not in touch:
            dropped_nobook += 1
            continue
        bid, ask, snap = touch[tk]
        # KXLOWT* settle on the daily LOW; KXHIGH* on the daily HIGH.
        obs = low if series.startswith("KXLOWT") else high
        if obs is None:
            dropped_noobs += 1
            continue
        yes_won = contract_resolved_yes(
            int(obs), {"bracket_type": bt, "strike_low": sl, "strike_high": sh}
        )

        market_mid = (bid + ask) / 200.0
        model_p = float(model_p)
        raw_edge = model_p - market_mid
        fit = blends.get(td)
        blend_edge = (float(fit.predict(model_p, market_mid)) - market_mid) if fit else None

        raw_fires = abs(raw_edge) >= raw_thresh
        blend_fires = blend_edge is not None and abs(blend_edge) >= blend_thresh
        if use_union:
            if not (raw_fires or blend_fires):
                continue
            edge = raw_edge if raw_fires else blend_edge
        elif use_blend:
            if not blend_fires:
                continue
            edge = blend_edge
        else:
            if not raw_fires:
                continue
            edge = raw_edge

        side = "yes" if edge > 0 else "no"
        won = yes_won if side == "yes" else (not yes_won)
        mn_ask, mx_bid, n_snap = window.get(tk, (None, None, 0))
        sigs.append({
            "date": td, "ticker": tk, "side": side, "edge": edge,
            "bid": int(bid), "ask": int(ask), "won": won,
            "min_ask": mn_ask, "max_bid": mx_bid, "n_snap": n_snap,
        })
    sigs.sort(key=lambda s: (s["date"], s["ticker"]))
    return sigs, dropped_nobook, dropped_noobs


# ---------------------------------------------------------------- simulation
def price_signal(sig: dict, mode: str, cfg: dict) -> tuple[int, int, str]:
    """-> (limit, cross_entry, exec_path) for one signal under one mode."""
    if mode == "smart_live":
        path = resolve_exec_path(
            "smart", sig["edge"],
            cfg.get("smart_cross_edge_threshold", SMART_CROSS_EDGE_THRESHOLD))
        premium = 0
    elif mode == "cross_with_premium_1":
        path, premium = "cross_with_premium", 1
    else:
        path, premium = mode, 0
    limit, cross, _ = limit_price_for(path, sig["side"], sig["bid"], sig["ask"], premium)
    return limit, cross, path


def simulate(sigs: list[dict], mode: str, cfg: dict) -> list[dict]:
    n = cfg["unit_contracts"]
    out = []
    for s in sigs:
        limit, cross, path = price_signal(s, mode, cfg)
        crossing = path in ("cross_at_ask", "cross_with_premium") or limit >= cross
        filled = True if crossing else would_fill(s["side"], limit, s["min_ask"], s["max_bid"])
        entry = limit
        is_maker = (path == "post_inside_spread") and entry < cross
        pnl = 0.0
        if filled:
            gross = ((100 - entry) if s["won"] else -entry) / 100.0 * n
            fee = kalshi_fee_cents(entry, is_maker) / 100.0 * n
            pnl = gross - fee
        out.append({**s, "mode": mode, "limit": limit, "cross": cross, "path": path,
                    "filled": filled, "maker": is_maker, "entry": entry, "net": pnl,
                    "gross": (((100 - entry) if s["won"] else -entry) / 100.0 * n) if filled else 0.0})
    return out


def metrics(trades: list[dict]) -> dict:
    n = len(trades)
    filled = [t for t in trades if t["filled"]]
    pnls = [t["net"] for t in filled]
    tot = sum(pnls)
    all_pnls = [t["net"] for t in trades]  # unfilled count as 0

    def _sharpe(xs):
        if len(xs) > 1 and statistics.stdev(xs) > 0:
            return statistics.mean(xs) / statistics.stdev(xs) * math.sqrt(252)
        return 0.0

    peak = cum = 0.0
    mdd = 0.0
    for p in all_pnls:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return {
        "n": n, "filled": len(filled), "fill_pct": (len(filled) / n * 100) if n else 0.0,
        "gross": sum(t["gross"] for t in filled), "net": tot,
        "per_filled": (tot / len(filled)) if filled else 0.0,
        "sharpe": _sharpe(pnls), "sharpe_all": _sharpe(all_pnls), "maxdd": mdd,
        "win": (sum(t["won"] for t in filled) / len(filled) * 100) if filled else 0.0,
    }


# ---------------------------------------------------------------- ground truth
def ground_truth_gate(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticker, side, placed_at, limit_price_cents, cross_price_cents,
                   fill_status, fill_count, count
            FROM live_trades
            WHERE fill_status NOT IN ('cancelled', 'rejected')
            ORDER BY id
            """
        )
        rows = cur.fetchall()
    keys = [(tk, pa, end_ts(pa.date())) for _, tk, _, pa, *_ in rows]
    _, window = fetch_book_windows(conn, keys)

    buckets = {"all": [], "maker": [], "taker": []}
    for tid, tk, side, pa, limit, cross, status, fc, cnt in rows:
        mn, mx, nsnap = window.get(tk, (None, None, 0))
        maker = cross is not None and limit < cross
        pred = would_fill(side, limit, mn, mx) if maker else True
        act = (fc or 0) > 0
        rec = (tid, tk, side, limit, cross, status, fc, cnt, pred, act, nsnap)
        buckets["all"].append(rec)
        buckets["maker" if maker else "taker"].append(rec)

    print("=" * 78)
    print("GROUND-TRUTH GATE — fill model replayed on real live_trades orders")
    print("=" * 78)
    for name, recs in buckets.items():
        if not recs:
            continue
        tp = sum(1 for r in recs if r[8] and r[9])
        fp = sum(1 for r in recs if r[8] and not r[9])
        fn = sum(1 for r in recs if not r[8] and r[9])
        tn = sum(1 for r in recs if not r[8] and not r[9])
        agree = (tp + tn) / len(recs) * 100
        print(f"\n{name.upper():6s} n={len(recs):3d}   agreement {agree:5.1f}%"
              f"   [pred fill/actual fill] TP={tp} FP={fp} FN={fn} TN={tn}")
    miss = [r for r in buckets["maker"] if r[8] != r[9]]
    if miss:
        print("\n  maker-order disagreements:")
        for tid, tk, side, limit, cross, status, fc, cnt, pred, act, nsnap in miss:
            print(f"   id={tid:<4d} {tk:<28s} {side:3s} L={limit:2d} X={cross:2d} "
                  f"status={status:<15s} fill={fc}/{cnt} pred={pred} snaps={nsnap}")
    print()


# ---------------------------------------------------------------- report
def fmt(m: dict) -> str:
    return (f"{m['n']:5d} {m['fill_pct']:6.1f}% {m['net']:10.2f} {m['per_filled']:9.2f} "
            f"{m['sharpe']:7.2f} {m['sharpe_all']:8.2f} {m['maxdd']:9.2f} {m['win']:6.1f}%")


HDR = f"{'mode':<22s} {'n':>5s} {'fill':>7s} {'net $':>10s} {'$/fill':>9s} {'Sharpe':>7s} {'Sh(all)':>8s} {'maxDD':>9s} {'win':>7s}"


def report_city(conn, city: str) -> None:
    cfg = CITY_CONFIG[city]
    sigs, d_book, d_obs = fetch_signals(conn, city)
    rule = ("UNION raw>=%.2f OR blend>=%.2f" % (cfg["edge_threshold"], cfg["blend_edge_threshold"])
            if cfg["use_union"] else
            "BLEND-only >=%.2f" % cfg["blend_edge_threshold"] if cfg["use_blend"] else
            "RAW-only >=%.2f" % cfg["edge_threshold"])
    print("=" * 110)
    print(f"{city} ({cfg['city_name']})  {cfg['paper_model_source']}")
    print(f"  rule: {rule} | unit {cfg['unit_contracts']} | decision "
          f"{cfg['decision_hour']:02d}:{cfg['decision_minute']:02d}Z | "
          f"live smart_cross {cfg['smart_cross_edge_threshold']:.2f}")
    print(f"  signals n={len(sigs)}  (dropped: no decision-time book {d_book}, no observation {d_obs})")
    if not sigs:
        return
    print(f"  window {sigs[0]['date']} .. {sigs[-1]['date']}")
    cut = int(len(sigs) * 0.6)
    halves = {"FULL": sigs, "TRAIN(60%)": sigs[:cut], "TEST(40%)": sigs[cut:]}

    for label, subset in halves.items():
        print(f"\n  --- {label}  n={len(subset)}  "
              f"({subset[0]['date']} .. {subset[-1]['date']})" if subset else f"\n  --- {label} empty")
        print("  " + HDR)
        for mode in MODES:
            m = metrics(simulate(subset, mode, cfg))
            tag = mode + (f" (LIVE)" if mode == "smart_live" else "")
            print(f"  {tag:<22s} " + fmt(m))

    # adverse selection: trades CROSS fills that POST misses
    post = {(t["date"], t["ticker"]): t for t in simulate(sigs, "post_inside_spread", cfg)}
    cross = simulate(sigs, "cross_at_ask", cfg)
    only = [t for t in cross if not post[(t["date"], t["ticker"])]["filled"]]
    both = [t for t in cross if post[(t["date"], t["ticker"])]["filled"]]
    print(f"\n  ADVERSE SELECTION (cross-only catches, i.e. POST would have missed):")
    if only:
        nets = [t["net"] for t in only]
        print(f"    n={len(only)}  mean net/trade ${statistics.mean(nets):+.2f}  "
              f"total ${sum(nets):+.2f}  win {sum(t['won'] for t in only)/len(only)*100:.1f}%")
    else:
        print("    n=0 (POST fills everything CROSS does)")
    if both:
        nets = [t["net"] for t in both]
        print(f"    (comparison: both-fill trades, priced at cross: n={len(both)} "
              f"mean ${statistics.mean(nets):+.2f}  win {sum(t['won'] for t in both)/len(both)*100:.1f}%)")

    # DECOMPOSITION — the whole POST-vs-CROSS gap is exactly these two terms:
    #   price-improvement POST earns on the fills it DOES get  (always >= 0)
    #   minus the P&L of the fills it MISSES                   (sign = the crux)
    saved = sum(post[(t["date"], t["ticker"])]["net"] - t["net"] for t in both)
    forgone = sum(t["net"] for t in only)
    print(f"\n  DECOMPOSITION of POST − CROSS = ${saved - forgone:+.2f}")
    print(f"    + price improvement on the {len(both)} shared fills : ${saved:+.2f}")
    print(f"    − P&L of the {len(only)} fills POST misses           : ${forgone:+.2f}")
    print()


def _selfcheck() -> None:
    # post_inside_spread: bid 40 ask 45 (spread 5) -> YES limit 41, NO limit 56
    assert limit_price_for("post_inside_spread", "yes", 40, 45) == (41, 45, True)
    assert limit_price_for("post_inside_spread", "no", 40, 45) == (56, 60, True)
    # spread <= 1 -> falls back to crossing (live_trade.py:761-763)
    assert limit_price_for("post_inside_spread", "yes", 44, 45) == (45, 45, False)
    assert limit_price_for("cross_at_ask", "no", 40, 45) == (60, 60, False)
    assert limit_price_for("cross_with_premium", "yes", 40, 45, 1) == (46, 45, False)
    # fill rule
    assert would_fill("yes", 41, 41, 99) and not would_fill("yes", 41, 42, 99)
    assert would_fill("no", 56, 0, 44) and not would_fill("no", 56, 0, 43)
    # maker fee is 1/4 the taker fee rate
    assert kalshi_fee_cents(50, True) * 4 >= kalshi_fee_cents(50, False)
    print("selfcheck OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", action="append", choices=CITIES)
    ap.add_argument("--gate-only", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--relax", type=int, default=0,
                    help="cents of slack in the fill test (sensitivity; 1 = upper bound on POST fills)")
    a = ap.parse_args()
    if a.selfcheck:
        _selfcheck()
        sys.exit(0)
    _selfcheck()
    RELAX = a.relax
    if RELAX:
        print(f"*** SENSITIVITY RUN: fill test relaxed by {RELAX}c (POST fill rate = upper bound) ***\n")
    with get_connection() as conn:
        ground_truth_gate(conn)
        if not a.gate_only:
            for c in (a.city or CITIES):
                report_city(conn, c)
