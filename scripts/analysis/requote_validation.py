"""Paper-validate the monitor_fills 45-minute maker RE-QUOTE (READ-ONLY analysis).

QUESTION
--------
scripts/monitor_fills.py can (OFF by default; --requote) cancel each FULLY-unfilled
resting MAKER order older than 45 min and re-post it as a CROSS at the ask, iff
|edge| >= a per-city re-quote threshold Y (else leave to expire). It has never
been paper-validated. Does enabling it improve net edge (fill rate + net P&L +
net Sharpe) on the live cities WITHOUT importing adverse selection?

MECHANISM BEING SIMULATED (from monitor_fills._requote_decision / requote_unfilled_makers)
  - Acts ONLY on orders with fill_status='pending' AND filled_qty==0 (FULLY unfilled).
    A partially-filled order returns 'skip_partial' -> NOT re-quoted (double-fill guard).
  - Fires at elapsed >= REQUOTE_AFTER_MINUTES (45).
  - If |edge| >= Y_city: cancel + repost as a CROSS at the current ask (taker fee).
    If |edge| <  Y_city: leave to expire (identical to baseline).
  - RUNAWAY guard: one re-quote per order (modelled: a single T+45 cross attempt).
  Y_city (monitor_fills.REQUOTE_CROSS_EDGE_THRESHOLD): KXHIGHCHI .25 / KXHIGHMIA .10 / KXHIGHTDAL .25

WHY the addressable population is the crux
  An order can only be re-quoted if it POSTED as a maker (resolve_exec_path:
  post_inside when |edge| < smart_cross_edge_threshold) AND then sat fully unfilled.
  - KMIA: smart_cross = 0.10 == its only entry filter (blend_edge >= 0.10) => EVERY
    fired KMIA signal crosses at placement => ~0 maker orders => re-quote ~never applies.
  - KORD/KDFW: post as maker only when |edge| in [entry_floor, 0.40); the re-quote can
    only convert those that ALSO have |edge| >= 0.25 AND got zero first-window fill.

METHOD (adapts prior art, reuses its validated semantics):
  * signal reconstruction: walk-forward blend (weather_markets.blend.walkforward_blends),
    lookahead-free, mirrors walk_book_miami.py / miami_fill_rate_vs_size.py.
  * first-window MAKER fill: churn-suppressed bid-ladder depletion over
    [decision, decision+45m] (maker_flow_to_us), the model validated to the live
    ~52% KMIA / ~90% KORD fill anchors.
  * re-quote fill: walk the ask ladder at the T+45 snapshot (taker), taker fee.
  * settlement: contract_resolved_yes(high, bracket) from observations+contracts.

READ-ONLY. No orders, no writes, no config change. Run:
    uv run python scripts/analysis/requote_validation.py
    uv run python scripts/analysis/requote_validation.py --json /tmp/requote.json
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from statistics import median, pstdev, mean

from weather_markets.db import get_connection
from weather_markets.blend import walkforward_blends, apply_blend
from weather_markets.evaluation import contract_resolved_yes

# --- book window: orderbook_snapshots coverage (all live cities) -------------
DEPTH_START = date(2026, 6, 10)
DEPTH_END = date(2026, 7, 5)
REQUOTE_AFTER_MIN = 45          # monitor_fills.REQUOTE_AFTER_MINUTES
TOL_MIN = 90                    # max |snapshot - decision| to accept a decision book

CITIES = {
    "KORD": dict(series="KXHIGHCHI", city_code="KORD", city_name="Chicago",
                 pms="EMOS combined_hrrr 00Z Chicago (rolling 45d)",
                 dec=(14, 46), use_union=True, raw_thr=0.25, blend_thr=0.10,
                 smart_cross=0.40, requote_Y=0.25, unit=500),
    "KMIA": dict(series="KXHIGHMIA", city_code="KMIA", city_name="Miami",
                 pms="EMOS combined 00Z Miami (rolling 45d)",
                 dec=(15, 30), use_union=False, raw_thr=1.00, blend_thr=0.10,
                 smart_cross=0.10, requote_Y=0.10, unit=500),
    "KDFW": dict(series="KXHIGHTDAL", city_code="KDFW", city_name="Dallas",
                 pms="EMOS combined 00Z Dallas (rolling 45d)",
                 dec=(17, 32), use_union=True, raw_thr=0.25, blend_thr=0.10,
                 smart_cross=0.40, requote_Y=0.25, unit=500),
}


# --- fee (mirrors scripts/live_trade.kalshi_fee_cents; parity-tested) ---------
def fee_cents(entry_price_cents: int, maker: bool) -> int:
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    rate = 0.0175 if maker else 0.07
    return max(1, math.ceil(rate * p * (1.0 - p) * 100))


# --- book primitives (reused verbatim from walk_book_miami / miami_fill_rate) -
def ladders_at(cur, ticker, snap):
    cur.execute("SELECT side, price_cents, qty FROM orderbook_snapshots "
                "WHERE ticker=%s AND snapshot_at=%s", (ticker, snap))
    yl, nl = [], []
    for side, pc, q in cur.fetchall():
        (yl if side == "yes" else nl).append((int(pc), int(q)))
    return yl, nl


def nearest_snapshot(cur, ticker, target_dt, day):
    d0 = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    d1 = d0 + timedelta(days=1)
    cur.execute(
        """SELECT snapshot_at, abs(extract(epoch FROM (snapshot_at-%s)))/60.0 off_min
           FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at>=%s AND snapshot_at<%s
           ORDER BY off_min ASC LIMIT 1""", (target_dt, ticker, d0, d1))
    r = cur.fetchone()
    return (r[0], float(r[1])) if r else (None, None)


def bid_series(cur, ticker, side, start, end):
    cur.execute("""SELECT snapshot_at, price_cents, qty FROM orderbook_snapshots
                   WHERE ticker=%s AND side=%s AND snapshot_at>=%s AND snapshot_at<%s
                   ORDER BY snapshot_at""", (ticker, side, start, end))
    s = {}
    for ts, pc, q in cur.fetchall():
        s.setdefault(ts, {})[int(pc)] = int(q)
    return s


def maker_flow_to_us(series, post_price, ahead_qty):
    """Inferred counterparty flow reaching a resting bid at post_price
    (churn-suppressed bid-ladder depletion). Verbatim from miami_fill_rate."""
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


def ask_ladder_from_levels(levels):
    asks = [(100 - pc, q) for pc, q in levels if 0 < pc < 100 and q > 0]
    asks.sort(key=lambda x: x[0])
    return asks


def cross_fill(ask_ladder, won, size):
    """(filled, net_cents) walking the ask ladder as a taker, settled."""
    rem, gross, fee, filled = size, 0, 0, 0
    for ask, q in ask_ladder:
        take = min(rem, q)
        if take <= 0:
            break
        filled += take
        gross += take * (100 - ask) if won else -take * ask
        fee += take * fee_cents(ask, maker=False)
        rem -= take
        if rem <= 0:
            break
    return filled, gross - fee


def maker_settle(entry_cents, won, filled):
    """(filled, net_cents) for a resting maker fill at entry_cents, settled."""
    if filled <= 0:
        return 0, 0
    gross = filled * (100 - entry_cents) if won else -filled * entry_cents
    fee = filled * fee_cents(entry_cents, maker=True)
    return filled, gross - fee


# --- signal load -------------------------------------------------------------
def load_rows(cur, pms):
    cur.execute("""
        SELECT pt.target_date, pt.ticker, pt.model_prob_yes,
               pt.market_yes_bid, pt.market_yes_ask,
               c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
        FROM paper_trades pt
        JOIN contracts c ON c.ticker = pt.ticker
        LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
             WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
        WHERE pt.model_source = %s AND pt.target_date BETWEEN %s AND %s
          AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
          AND pt.model_prob_yes IS NOT NULL
        ORDER BY pt.target_date, pt.ticker""", (pms, DEPTH_START, DEPTH_END))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def build_signals(cur, cfg, fill_model="join"):
    """Fired signals in the book window, classified maker/cross under live exec,
    with first-window maker fill + T+45 cross book, settled.

    fill_model:
      'join'   — post AT the touch, sit BEHIND the full resting queue (ahead=best-bid qty).
                 Conservative (matches miami_fill_rate anchor calibration). LOWER fill.
      'inside' — post 1c INSIDE the spread (best_bid+1), jump the queue (ahead=0).
                 Matches live post_inside_spread exec. HIGHER fill (optimistic bound)."""
    blends = walkforward_blends(cfg["city_code"], cfg["city_name"], cfg["pms"])
    rows = load_rows(cur, cfg["pms"])
    dh, dm = cfg["dec"]
    out, skips = [], {"no_blend": 0, "no_snap": 0, "unsettled": 0, "no_book": 0, "not_fired": 0}
    for r in rows:
        d = r["target_date"]
        fit = blends.get(d)
        if fit is None:
            skips["no_blend"] += 1
            continue
        mp = float(r["model_prob_yes"])
        mkt = (int(r["market_yes_bid"]) + int(r["market_yes_ask"])) / 200.0
        raw_edge = mp - mkt
        blend_p = float(apply_blend(fit, mp, mkt))
        blend_edge = blend_p - mkt
        raw_fires = abs(raw_edge) >= cfg["raw_thr"]
        blend_fires = abs(blend_edge) >= cfg["blend_thr"]
        if cfg["use_union"]:
            if raw_fires:
                edge, src = raw_edge, "raw"
            elif blend_fires:
                edge, src = blend_edge, "blend"
            else:
                skips["not_fired"] += 1
                continue
        else:  # blend-only (KMIA)
            if not blend_fires:
                skips["not_fired"] += 1
                continue
            edge, src = blend_edge, "blend"
        buy_yes = edge > 0
        is_cross = abs(edge) >= cfg["smart_cross"]

        if r["high_temp_f"] is None:
            skips["unsettled"] += 1
            continue
        yes_won = bool(contract_resolved_yes(int(r["high_temp_f"]),
                       {"bracket_type": r["bracket_type"],
                        "strike_low": r["strike_low"], "strike_high": r["strike_high"]}))
        won = yes_won if buy_yes else (not yes_won)

        dec_dt = datetime.combine(d, time(dh, dm), tzinfo=timezone.utc)
        snap, off = nearest_snapshot(cur, r["ticker"], dec_dt, d)
        if snap is None or off > TOL_MIN:
            skips["no_snap"] += 1
            continue
        yl, nl = ladders_at(cur, r["ticker"], snap)

        # cross book at decision (for cross-classified signals)
        lift0 = ask_ladder_from_levels(nl if buy_yes else yl)

        # maker post: join our side's touch
        my_side = "yes" if buy_yes else "no"
        my_levels = yl if buy_yes else nl
        if not my_levels:
            skips["no_book"] += 1
            continue
        best_bid = max(p for p, _ in my_levels)
        if fill_model == "inside":
            post_price = min(best_bid + 1, 99)   # 1c inside; entry paid = this
            ahead = 0                            # queue-jump the touch
        else:
            post_price = best_bid                # join the touch, entry = best_bid
            ahead = dict(my_levels).get(best_bid, 0)
        w_end = snap + timedelta(minutes=REQUOTE_AFTER_MIN)
        ser = bid_series(cur, r["ticker"], my_side, snap, w_end)
        net, raw = maker_flow_to_us(ser, best_bid, ahead)
        filled_first = min(net, cfg["unit"])

        # T+45 cross book (for the re-quote)
        tdt = dec_dt + timedelta(minutes=REQUOTE_AFTER_MIN)
        snap45, off45 = nearest_snapshot(cur, r["ticker"], tdt, d)
        lift45 = []
        if snap45 is not None:
            yl2, nl2 = ladders_at(cur, r["ticker"], snap45)
            lift45 = ask_ladder_from_levels(nl2 if buy_yes else yl2)

        out.append(dict(
            date=str(d), ticker=r["ticker"], src=src, buy_yes=buy_yes,
            edge=edge, aedge=abs(edge), is_cross=is_cross, won=won,
            unit=cfg["unit"], best_bid=best_bid, post_price=post_price, ahead=ahead,
            net_flow=net, raw_flow=raw, filled_first=filled_first,
            lift0=lift0, lift45=lift45, off=off,
        ))
    return out, skips, len(rows)


def sharpe(xs):
    """Per-trade Sharpe = mean/pstdev of per-signal net $ (unitless, not annualized)."""
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    sd = pstdev(xs)
    return (mean(xs) / sd) if sd > 0 else float("nan")


def simulate(sigs, cfg):
    """Baseline vs re-quote on the ADDRESSABLE (maker-classified) population.
    Returns per-arm metrics + adverse-selection groups."""
    Y = cfg["requote_Y"]
    makers = [s for s in sigs if not s["is_cross"]]
    crossers = [s for s in sigs if s["is_cross"]]

    base_pnl, rq_pnl = [], []          # per-signal net $ (maker population)
    base_filled = rq_filled = ordered = 0
    grp_first, grp_requote = [], []    # adverse selection
    n_addressable = 0                  # zero-first-fill & |edge|>=Y (re-quote would bite)
    n_requote_got_fill = 0

    for s in makers:
        ordered += s["unit"]
        entry = s["post_price"]
        # BASELINE: maker first-window fill only
        bf, bnet = maker_settle(entry, s["won"], s["filled_first"])
        base_pnl.append(bnet / 100.0)
        base_filled += bf
        # RE-QUOTE arm
        if s["filled_first"] > 0:
            # skip_partial guard -> identical to baseline
            rq_pnl.append(bnet / 100.0)
            rq_filled += bf
            grp_first.append(s)
        else:
            # fully unfilled -> re-quote iff |edge| >= Y
            if s["aedge"] >= Y and s["lift45"]:
                n_addressable += 1
                rf, rnet = cross_fill(s["lift45"], s["won"], s["unit"])
                rq_pnl.append(rnet / 100.0)
                rq_filled += rf
                if rf > 0:
                    n_requote_got_fill += 1
                    s = dict(s, requote_filled=rf, requote_net=rnet)
                    grp_requote.append(s)
            else:
                # leave_expire (or no T+45 book) -> identical to baseline (0 fill)
                if s["aedge"] >= Y and not s["lift45"]:
                    n_addressable += 1  # would fire but no book to fill against
                rq_pnl.append(bnet / 100.0)  # 0
                rq_filled += bf

    def winrate(grp):
        filled = [g for g in grp if (g.get("requote_filled") or g["filled_first"]) > 0]
        if not filled:
            return float("nan"), 0
        return 100.0 * sum(1 for g in filled if g["won"]) / len(filled), len(filled)

    def edge_per_ct(grp, which):
        num = den = 0.0
        for g in grp:
            if which == "first":
                f, net = g["filled_first"], maker_settle(g["post_price"], g["won"], g["filled_first"])[1]
            else:
                f, net = g.get("requote_filled", 0), g.get("requote_net", 0)
            num += net; den += f
        return (num / den) if den else float("nan")

    wr_f, nf = winrate(grp_first)
    wr_r, nr = winrate(grp_requote)
    return dict(
        n_maker=len(makers), n_cross=len(crossers),
        ordered=ordered,
        base=dict(fill_rate=100.0 * base_filled / ordered if ordered else float("nan"),
                  net_pnl=sum(base_pnl), sharpe=sharpe(base_pnl), filled=base_filled),
        requote=dict(fill_rate=100.0 * rq_filled / ordered if ordered else float("nan"),
                     net_pnl=sum(rq_pnl), sharpe=sharpe(rq_pnl), filled=rq_filled),
        n_addressable=n_addressable, n_requote_got_fill=n_requote_got_fill,
        adverse=dict(first_win=wr_f, first_n=nf, first_edge_ct=edge_per_ct(grp_first, "first"),
                     rq_win=wr_r, rq_n=nr, rq_edge_ct=edge_per_ct(grp_requote, "requote")),
    )


def broad_book_gate(cur, cfg, minutes):
    """Validation gate (step 7): median maker fill-rate at unit=500 across EVERY
    bracket-day in the window (join-the-touch, no self-pollution), over a
    `minutes`-long window from the decision snapshot. Compare to live anchors."""
    dh, dm = cfg["dec"]
    cur.execute("""SELECT DISTINCT ticker, snapshot_at::date d FROM orderbook_snapshots
                   WHERE ticker LIKE %s AND snapshot_at::date BETWEEN %s AND %s""",
                (cfg["series"] + "%", DEPTH_START, DEPTH_END))
    pairs = cur.fetchall()
    rates = []
    for tk, d in pairs:
        tgt = datetime.combine(d, time(dh, dm), tzinfo=timezone.utc)
        snap, off = nearest_snapshot(cur, tk, tgt, d)
        if snap is None or off > TOL_MIN:
            continue
        end = snap + timedelta(minutes=minutes)
        for side in ("yes", "no"):
            cur.execute("SELECT price_cents, qty FROM orderbook_snapshots "
                        "WHERE ticker=%s AND side=%s AND snapshot_at=%s", (tk, side, snap))
            lv = cur.fetchall()
            if not lv:
                continue
            best = max(int(p) for p, _ in lv)
            ser = bid_series(cur, tk, side, snap, end)
            net, _ = maker_flow_to_us(ser, best, 0)  # queue-jump baseline for capacity
            rates.append(min(net, 500) / 500.0)
    return (100.0 * median(rates) if rates else float("nan"),
            100.0 * mean(rates) if rates else float("nan"), len(rates))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--fill-model", choices=["join", "inside"], default="join",
                    help="join=behind full queue (conservative, anchor-calibrated); "
                         "inside=post 1c inside, jump queue (matches live post_inside, optimistic)")
    args = ap.parse_args()

    report = {"window": [str(DEPTH_START), str(DEPTH_END)], "requote_after_min": REQUOTE_AFTER_MIN,
              "fill_model": args.fill_model, "cities": {}}
    with get_connection() as conn, conn.cursor() as cur:
        for code, cfg in CITIES.items():
            sigs, skips, n_rows = build_signals(cur, cfg, fill_model=args.fill_model)
            res = simulate(sigs, cfg)
            res["cand_rows"] = n_rows
            res["skips"] = skips
            res["fired"] = len(sigs)
            g45 = broad_book_gate(cur, cfg, REQUOTE_AFTER_MIN)
            gday = broad_book_gate(cur, cfg, 600)
            res["gate"] = dict(med45=g45[0], mean45=g45[1], med_day=gday[0], mean_day=gday[1], n=g45[2])
            report["cities"][code] = res

    L = print
    L("=" * 92)
    L(f"RE-QUOTE (45-min maker -> cross) PAPER VALIDATION  [READ-ONLY]  fill_model={args.fill_model}")
    L(f"book window {DEPTH_START} .. {DEPTH_END}  |  first-window = decision..+{REQUOTE_AFTER_MIN}m  |  unit=500")
    L("first-window maker fill = churn-suppressed bid-ladder depletion (validated to live anchors)")
    L("=" * 92)
    for code, cfg in CITIES.items():
        r = report["cities"][code]
        L(f"\n### {code} ({cfg['city_name']}, {cfg['series']})  "
          f"smart_cross={cfg['smart_cross']:.2f}  requote_Y={cfg['requote_Y']:.2f}")
        L(f"  candidate paper rows={r['cand_rows']}  fired signals={r['fired']}  "
          f"(maker/addressable={r['n_maker']}  cross-at-placement={r['n_cross']})  skips={r['skips']}")
        L(f"  ADDRESSABLE by re-quote (fully-unfilled maker & |edge|>=Y): {r['n_addressable']}  "
          f"-> got a T+45 cross fill: {r['n_requote_got_fill']}")
        b, q = r["base"], r["requote"]
        L(f"  {'arm':<10}{'fill%':>8}{'netP&L$':>11}{'Sharpe':>9}{'filled_ct':>11}")
        L(f"  {'baseline':<10}{b['fill_rate']:>8.1f}{b['net_pnl']:>11.2f}{b['sharpe']:>9.2f}{b['filled']:>11}")
        L(f"  {'requote':<10}{q['fill_rate']:>8.1f}{q['net_pnl']:>11.2f}{q['sharpe']:>9.2f}{q['filled']:>11}")
        L(f"  {'DELTA':<10}{q['fill_rate']-b['fill_rate']:>8.1f}{q['net_pnl']-b['net_pnl']:>11.2f}"
          f"{q['sharpe']-b['sharpe']:>9.2f}{q['filled']-b['filled']:>11}")
        a = r["adverse"]
        L(f"  ADVERSE SELECTION: first-window fills  win%={a['first_win']:.1f} (n={a['first_n']}) "
          f"edge={a['first_edge_ct']:.2f}c/ct  |  RE-QUOTED fills  win%={a['rq_win']:.1f} "
          f"(n={a['rq_n']}) edge={a['rq_edge_ct']:.2f}c/ct")
        g = r["gate"]
        L(f"  VALIDATION GATE (broad-book, all brackets n={g['n']}): median maker fill @500 "
          f"45m={g['med45']:.0f}% full-day={g['med_day']:.0f}%  (live anchors: KORD~90 KMIA~52)")
    L("\n" + "=" * 92)
    if args.json:
        # strip un-serializable ladders
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2, default=str)
        L(f"wrote {args.json}")


if __name__ == "__main__":
    main()
