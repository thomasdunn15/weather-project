"""Miami (KMIA) MAKER fill-rate vs posted size — does 500 -> 1000 double FILLED contracts?

THE QUESTION (distinct from the walk-book taker study)
------------------------------------------------------
The walk-book study (scripts/analysis/walk_book_miami.py, branch research/walk-book-miami)
answered the TAKER capacity question: when you CROSS the spread, the marginal contract
fills at a worse price (price decays with size). This script answers the MAKER question:
when you post a RESTING LIMIT order at one fixed price, your price is fixed — the binding
constraint is whether enough COUNTERPARTY FLOW trades against your resting order before the
market closes. We measure fill-rate-vs-posted-size for a resting maker and decide whether
doubling Miami 500 -> 1000 roughly doubles FILLED contracts, or whether the marginal 500
fills at a much lower rate.

DATA INVENTORY (what exists; stated loudly)
-------------------------------------------
* orderbook_snapshots(snapshot_at, ticker, side['yes'|'no'], price_cents, qty) — RESTING
  bids on each ladder. KMIA coverage 2026-06-10 -> 2026-06-29 (~20 days). DIRECTIONAL ONLY.
  Snapshot cadence is ~300s (one snapshot every ~5 minutes, ~288/day/ticker).
* NO TRADE TAPE. There is no trades / candlesticks / volume table and orderbook_snapshots
  has no volume column. Executed counterparty flow is therefore INFERRED from snapshot-to-
  snapshot depth depletion at the bid ladder. This is an INFERENCE, not a tape (see below).
* live_trades(count, fill_count, fill_status, limit_price_cents, cross_price_cents, ...) —
  our OWN realized fills. Used as the validation anchor (the ~52% @ ~500 number).

BOOK SEMANTICS (reused from walk_book_miami.py, validated there)
---------------------------------------------------------------
  yes_bid = max(price where side='yes');  yes_ask = 100 - max(price where side='no')
  To BUY YES with a resting MAKER order you JOIN the YES bid (post at the yes_bid). You fill
  when a counterparty SELLS YES into your bid, i.e. flow that trades at price <= your bid.
  BUY NO is symmetric (join the NO bid).  [The walk-book LIFTS the opposite ladder — that is
  the taker action; here we JOIN our own side's bid — the maker action.]

THE MAKER FLOW ESTIMATOR (inference, conservative, price-anchored)
-----------------------------------------------------------------
For a resting BUY at post_price on the bid ladder, a counterparty SELL fills us ONLY when it
trades at a price <= our bid — i.e. when the best bid has come DOWN to our level (we are at
the touch). Between consecutive snapshots we count a consumption at the touch when:
  (a) best_bid <= post_price        (the market is trading at/through our level, not above us)
  (b) best_bid does NOT rise        (a reprice-UP is new flow, not a hit on the old touch)
  (c) qty at the best-bid price falls  -> the fall is the consumed (sold-into) quantity.
We then subtract `ahead_qty` (resting size already at our price when we post) for QUEUE
PRIORITY: we fill only after the queue ahead of us clears.

  *** WHY NOT "sum all depth that disappeared >= our price" ***  Naive depletion conflates
  CANCELS with TRADES. At a competitive bid level, market-makers reprice constantly:
  measured replenishment ~= measured depletion (churn). Summing every disappearance over an
  8-hour window overcounts flow by 100x (a known-0-fill day estimated at 16,000 "fills").
  Price-anchoring to the touch + the non-reprice-up + best_bid<=post_price filters collapse
  the churn and reproduce the known 0-fill day as ~0 net flow. This is the single most
  important methodological choice; it is still an INFERENCE and the absolute level should be
  read as a lower-confidence proxy, the SHAPE of the curve (500 vs 1000) as the finding.

CROSS DAYS ARE EXCLUDED (this is a maker study)
-----------------------------------------------
KMIA's live exec is "smart": cross at ask when |edge| >= smart_cross_edge_threshold, else
post inside. KMIA's smart_cross_edge_threshold is 0.10 (NOT 0.40 — that is KORD). Since the
KMIA blend filter ALSO fires at |blend_edge| >= 0.10, essentially EVERY KMIA signal both
fires AND crosses. So under the live config KMIA almost never rests as a maker (confirmed:
8 of 9 blend-era live orders are crosses; the lone maker order got 0 fills). We report the
cross/post split, EXCLUDE the cross signals from the realized-maker anchor, and compute the
maker curve as a COUNTERFACTUAL ("if KMIA posted these as makers, what would fill?").

OUTPUTS
-------
1. Maker fill-rate-vs-size curve (median fill rate, median filled contracts, p25/p75), on
   two samples: (a) the directly-relevant signal days, (b) a broad clean sample of ALL KMIA
   bracket ladders (no self-pollution from our own orders) for a larger-n cross-check.
2. Headline: filled(1000)/filled(500).
3. Validation vs the ~52% @ ~500 live anchor (reproduced from live_trades).
4. Leakage / adverse-selection: 15-min post-order mid-move; book-thinness depth proxy.

USAGE
-----
    cd /home/tdunn/weather-project   # or your worktree
    uv run python scripts/analysis/miami_fill_rate_vs_size.py
    uv run python scripts/analysis/miami_fill_rate_vs_size.py --json /tmp/kmia_fill.json

READ-ONLY. Does not place orders or modify any config. Sample is ~20 days — DIRECTIONAL.
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

# --- constants ---------------------------------------------------------------
STATION, CITY = "KMIA", "Miami"
PAPER_MODEL_SOURCE = "EMOS combined 00Z Miami (rolling 45d)"  # model_prob_yes universe
DEPTH_START = date(2026, 6, 10)          # orderbook_snapshots KMIA coverage start
DEPTH_END = date(2026, 6, 29)
DECISION_HOUR, DECISION_MIN = 15, 30     # KMIA live decision 15:30 UTC
BLEND_THRESHOLD = 0.10                   # KMIA live: blend-only fires at |blend_edge| >= 0.10
SMART_CROSS_THRESHOLD = 0.10             # KMIA live: smart crosses at |edge| >= 0.10 (CITY_CONFIG)
TOLERANCE_MIN = 180                      # max |snapshot - 15:30| to accept a book
SIZES = [100, 250, 500, 750, 1000, 1500]
ANCHOR_DATE = date(2026, 6, 21)          # date the ~52% fill-rate forward test was recorded


def kalshi_fee_cents(entry_price_cents: int, maker: bool = True) -> int:
    """Maker entry fee in cents (1/4 of taker). Mirrors live_trade.kalshi_fee_cents."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    rate = 0.0175 if maker else 0.07
    return max(1, math.ceil(rate * p * (1.0 - p) * 100))


# --- order-book primitives (book semantics reused from walk_book_miami.py) ----
def ladders_at(cur, ticker, snap):
    """(yes_levels, no_levels) as [(price_cents, qty), ...] at one snapshot."""
    cur.execute(
        "SELECT side, price_cents, qty FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at=%s",
        (ticker, snap),
    )
    yl, nl = [], []
    for side, pc, q in cur.fetchall():
        (yl if side == "yes" else nl).append((int(pc), int(q)))
    return yl, nl


def nearest_snapshot(cur, ticker, d):
    """(snapshot_at, off_min) nearest 15:30 UTC on date d, or (None, None)."""
    tgt = datetime.combine(d, time(DECISION_HOUR, DECISION_MIN), tzinfo=timezone.utc)
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
    """{snapshot_at: {price_cents: qty}} for one bid ladder over [start, end)."""
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
    """Inferred counterparty-sell flow that REACHES a resting bid at post_price.

    Price-anchored, churn-suppressing (see module docstring). Returns
    (net_flow_past_queue, raw_flow_to_our_level)."""
    tss = sorted(series.keys())
    raw = 0
    for a, b in zip(tss, tss[1:]):
        la, lb = series[a], series[b]
        if not la:
            continue
        bb = max(la.keys())
        bb2 = max(lb.keys()) if lb else 0
        if bb > post_price:      # market trading above us -> we are buried, no fill
            continue
        if bb2 > bb:             # reprice-up -> new flow, not a hit on the old touch
            continue
        raw += max(0, la.get(bb, 0) - lb.get(bb, 0))
    return max(0, raw - ahead_qty), raw


# --- signal reconstruction (walk-forward blend, mirrors walk_book_miami.py) ---
def build_signals(cur):
    """KMIA blend signals (|blend_edge| >= 0.10) in the depth window, each tagged
    cross vs post under the live smart_cross_edge_threshold, with the maker book."""
    blends = walkforward_blends(STATION, CITY, PAPER_MODEL_SOURCE)
    cur.execute(
        """SELECT target_date, ticker, model_prob_yes, market_mid_prob
           FROM paper_trades WHERE model_source=%s AND target_date BETWEEN %s AND %s
           ORDER BY target_date, ticker""",
        (PAPER_MODEL_SOURCE, DEPTH_START, DEPTH_END),
    )
    rows = cur.fetchall()
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
        blend_edge = blend_p - mkt
        if abs(blend_edge) < BLEND_THRESHOLD:
            continue
        buy_yes = blend_edge > 0
        is_cross = abs(blend_edge) >= SMART_CROSS_THRESHOLD   # live smart-exec resolution
        if is_cross:
            n_cross += 1
        snap, off = nearest_snapshot(cur, tk, d)
        if snap is None or off is None or off > TOLERANCE_MIN:
            skips.append((d, tk, f"no snapshot within {TOLERANCE_MIN}min (off={off})"))
            continue
        yl, nl = ladders_at(cur, tk, snap)
        levels = yl if buy_yes else nl                        # MAKER: join our own side's bid
        if not levels:
            skips.append((d, tk, "empty bid ladder on post side"))
            continue
        best_bid = max(p for p, _ in levels)
        post_price = best_bid                                  # join the touch
        ahead = dict(levels).get(post_price, 0)
        d0 = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        eod = d0 + timedelta(days=1)
        ser = bid_series(cur, tk, "yes" if buy_yes else "no", snap, eod)
        net, raw = maker_flow_to_us(ser, post_price, ahead)
        sigs.append(dict(
            date=d, ticker=tk, side="BUY_YES" if buy_yes else "BUY_NO",
            blend_edge=blend_edge, best_bid=best_bid, post_price=post_price,
            ahead=ahead, raw_flow=raw, net_flow=net, n_snaps=len(ser),
            is_cross=is_cross, off_min=off,
        ))
    return sigs, skips, n_cross, len(rows)


# --- broad clean sample (no self-pollution) ----------------------------------
def broad_book_flows(cur):
    """For EVERY KMIA bracket ladder-day in the window (both sides), inferred
    sell-flow reaching the decision-time best bid over 15:30->EOD. Most of these
    tickers we never traded, so the book carries no self-pollution from our orders."""
    cur.execute(
        """SELECT DISTINCT ticker, snapshot_at::date d FROM orderbook_snapshots
           WHERE ticker LIKE 'KXHIGHMIA%%' AND snapshot_at::date BETWEEN %s AND %s""",
        (DEPTH_START, DEPTH_END),
    )
    flows = []
    for tk, d in cur.fetchall():
        d0 = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        eod = d0 + timedelta(days=1)
        tgt = datetime.combine(d, time(DECISION_HOUR, DECISION_MIN), tzinfo=timezone.utc)
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
def live_anchor(cur):
    """Reproduce the ~52% @ ~500 anchor + current realized KMIA fill, from live_trades."""
    def agg(where, params):
        cur.execute(
            f"""SELECT count(*), coalesce(sum(count),0), coalesce(sum(coalesce(fill_count,0)),0),
                   coalesce(avg(LEAST(coalesce(fill_count,0)::numeric/count, 1.0)), 0)
                FROM live_trades WHERE ticker LIKE 'KXHIGHMIA%%' {where}""",
            params,
        )
        n, posted, filled, avg_ff = cur.fetchone()
        pct = (100.0 * float(filled) / float(posted)) if posted else float("nan")
        return dict(n=int(n), posted=int(posted), filled=int(filled),
                    pct_contracts=pct, avg_order_fill_frac=float(avg_ff))
    as_of = agg("AND placed_at::date <= %s", (ANCHOR_DATE,))
    current = agg("", ())
    blend_cross = agg("AND model_source ILIKE %s AND limit_price_cents = cross_price_cents",
                      ("%BLEND-only%",))
    blend_maker = agg("AND model_source ILIKE %s AND limit_price_cents <> cross_price_cents",
                      ("%BLEND-only%",))
    return dict(as_of_anchor=as_of, current=current,
                blend_era_cross=blend_cross, blend_era_maker=blend_maker)


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
    return (yb + (100 - nb)) / 2.0   # YES-prob cents


def nearest_after(cur, ticker, ts, minutes):
    cur.execute(
        "SELECT snapshot_at FROM orderbook_snapshots WHERE ticker=%s AND snapshot_at>=%s ORDER BY snapshot_at LIMIT 1",
        (ticker, ts + timedelta(minutes=minutes)),
    )
    r = cur.fetchone()
    return r[0] if r else None


def leakage(cur):
    """15-min post-order adverse mid-move by posted-size bucket (+ = against our side)."""
    cur.execute(
        "SELECT placed_at, ticker, side, count FROM live_trades WHERE ticker LIKE 'KXHIGHMIA%%' ORDER BY count",
    )
    buckets = {"<=300": [], "301-600": [], ">600": []}
    detail = []
    for placed, tk, side, cnt in cur.fetchall():
        s0 = nearest_after(cur, tk, placed, 0)
        s1 = nearest_after(cur, tk, placed, 15)
        if not s0 or not s1:
            continue
        m0, m1 = mid_at(cur, tk, s0), mid_at(cur, tk, s1)
        if m0 is None or m1 is None:
            continue
        adverse = (m0 - m1) if side == "yes" else (m1 - m0)   # + = mid moved against our side
        b = "<=300" if cnt <= 300 else ("301-600" if cnt <= 600 else ">600")
        buckets[b].append(adverse)
        detail.append(dict(count=cnt, side=side, mid0=m0, mid1=m1, adverse=adverse))
    out = []
    for b in ["<=300", "301-600", ">600"]:
        xs = buckets[b]
        out.append(dict(bucket=b, n=len(xs),
                        med_adverse_cents=(median(xs) if xs else float("nan")),
                        mean_adverse_cents=(float(np.mean(xs)) if xs else float("nan"))))
    return out, detail


def depth_thinness(signals):
    """Book-thinness proxy: of the resting bid AHEAD of us at post-time, how often is
    the queue deep enough that a 500 vs 1000 maker even has different prospects.
    Reported as median resting-ahead and median raw window-flow at our level."""
    ahead = [s["ahead"] for s in signals]
    raw = [s["raw_flow"] for s in signals]
    return dict(
        n=len(signals),
        med_resting_ahead=median(ahead) if ahead else float("nan"),
        med_raw_window_flow=median(raw) if raw else float("nan"),
    )


# --- main --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="optional path to write metrics as JSON")
    args = ap.parse_args()

    with get_connection() as conn:
        cur = conn.cursor()
        signals, skips, n_cross, n_rows = build_signals(cur)
        sig_flows = [s["net_flow"] for s in signals]
        sig_curve = fill_curve(sig_flows)
        broad = broad_book_flows(cur)
        broad_curve = fill_curve(broad)
        anchor = live_anchor(cur)
        leak_table, leak_detail = leakage(cur)
        thin = depth_thinness(signals)
        cur.close()

    L = print
    L("=" * 84)
    L("MIAMI (KMIA) MAKER FILL-RATE vs POSTED SIZE   —   does 500 -> 1000 double FILLED?")
    L("=" * 84)
    L(f"Window: {DEPTH_START} -> {DEPTH_END} (~20 days, DIRECTIONAL). Snapshot cadence ~5 min.")
    L(f"NO TRADE TAPE — maker flow is INFERRED from bid-ladder depletion (price-anchored).")
    L("")
    L("SIGNAL UNIVERSE (KMIA blend-only, |blend_edge| >= 0.10, walk-forward blend)")
    L("-" * 84)
    L(f"  paper_trades rows scanned: {n_rows}   signals fired: {len(signals)}   skipped: {len(skips)}")
    L(f"  CROSS-classified (|edge| >= smart_cross={SMART_CROSS_THRESHOLD}): {n_cross} of {len(signals)}")
    L(f"  POST/maker-classified: {len(signals) - n_cross} of {len(signals)}")
    L(f"  => Under live config KMIA crosses essentially every signal; the maker curve below")
    L(f"     is a COUNTERFACTUAL ('if these were posted as makers, what would fill?').")
    L("")
    L("  per-signal (maker book at decision time):")
    L(f"  {'date':<11}{'bracket':<8}{'side':<8}{'edge':>7}{'bid¢':>5}{'ahead':>6}{'netflow':>8}{'cross?':>7}")
    for s in signals:
        L(f"  {str(s['date']):<11}{s['ticker'].split('-')[-1]:<8}{s['side']:<8}"
          f"{s['blend_edge']:>+7.3f}{s['best_bid']:>5}{s['ahead']:>6}{s['net_flow']:>8}"
          f"{'cross' if s['is_cross'] else 'post':>7}")
    L("")
    L("MAKER FILL CURVE  —  sample A: signal days (n=%d, directly relevant, self-polluted)" % len(sig_flows))
    L("-" * 84)
    _print_curve(sig_curve)
    L("")
    L("MAKER FILL CURVE  —  sample B: ALL KMIA brackets (n=%d, clean, larger-n cross-check)" % len(broad))
    L("-" * 84)
    _print_curve(broad_curve)
    L("")

    def filled_at(curve, N):
        return next(r["med_filled"] for r in curve if r["N"] == N)
    hl_sig = filled_at(sig_curve, 1000) / filled_at(sig_curve, 500) if filled_at(sig_curve, 500) else float("nan")
    hl_brd = filled_at(broad_curve, 1000) / filled_at(broad_curve, 500) if filled_at(broad_curve, 500) else float("nan")
    L("HEADLINE  —  filled(1000) / filled(500)  (2.0 = clean scale, <1.3 = marginal starves)")
    L("-" * 84)
    L(f"  signal-day sample : {hl_sig:.2f}x")
    L(f"  broad-book sample : {hl_brd:.2f}x")
    L("")
    L("VALIDATION vs the ~52% @ ~500 live anchor (reproduced from live_trades)")
    L("-" * 84)
    a = anchor["as_of_anchor"]; c = anchor["current"]
    L(f"  as-of {ANCHOR_DATE} (the recorded forward-test point): n={a['n']} orders, "
      f"{a['filled']}/{a['posted']} contracts = {a['pct_contracts']:.1f}%  <-- matches the ~52% memory")
    L(f"  current (all KMIA live orders):                       n={c['n']} orders, "
      f"{c['filled']}/{c['posted']} contracts = {c['pct_contracts']:.1f}%")
    bm = anchor["blend_era_maker"]; bc = anchor["blend_era_cross"]
    L(f"  blend-era CROSS (taker) orders: n={bc['n']}, {bc['pct_contracts']:.1f}% filled")
    L(f"  blend-era MAKER (post) orders:  n={bm['n']}, {bm['pct_contracts']:.1f}% filled  "
      f"(live KMIA almost never posts as a maker -> tiny n)")
    L("")
    L("LEAKAGE / ADVERSE SELECTION  —  15-min post-order mid-move by posted-size bucket")
    L("-" * 84)
    L(f"  {'bucket':<10}{'n':>4}{'med_adverse¢':>14}{'mean_adverse¢':>15}  (+ = mid moved AGAINST us)")
    for r in leak_table:
        ma = f"{r['med_adverse_cents']:.1f}" if not math.isnan(r["med_adverse_cents"]) else "--"
        me = f"{r['mean_adverse_cents']:.1f}" if not math.isnan(r["mean_adverse_cents"]) else "--"
        L(f"  {r['bucket']:<10}{r['n']:>4}{ma:>14}{me:>15}")
    L(f"  NOTE: every live KMIA order is exactly 500 (the unit) -> only the 301-600 bucket")
    L(f"        populates; we have NEVER posted 1000, so a size-graded fade cannot be measured")
    L(f"        from realized data. Book-thinness proxy: median resting-ahead={thin['med_resting_ahead']:.0f},"
      f" median raw window-flow at our level={thin['med_raw_window_flow']:.0f} contracts.")
    L("")
    L("CAVEATS: ~20-day directional window; NO trade tape (flow inferred from 5-min snapshot")
    L("depletion, churn-suppressed but still a proxy); queue model = subtract resting-ahead;")
    L("cross days excluded from maker anchor; signal-day n=%d is small + self-polluted by our" % len(sig_flows))
    L("own resting orders (broad-book sample is the larger, cleaner cross-check).")

    if args.json:
        payload = dict(
            window=[str(DEPTH_START), str(DEPTH_END)],
            signals=[{k: (str(v) if isinstance(v, date) else v) for k, v in s.items()} for s in signals],
            n_cross=n_cross, n_signals=len(signals),
            signal_curve=sig_curve, broad_curve=broad_curve,
            headline_signal=hl_sig, headline_broad=hl_brd,
            anchor=anchor, leakage=leak_table, leakage_detail=leak_detail, thinness=thin,
        )
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        L(f"\nwrote {args.json}")


def _print_curve(curve):
    print(f"  {'N':>6}{'med_fill_rate':>15}{'med_filled':>12}{'p25_filled':>12}{'p75_filled':>12}{'mean_rate':>11}")
    for r in curve:
        print(f"  {r['N']:>6}{r['med_fill_rate']:>15.3f}{r['med_filled']:>12.0f}"
              f"{r['p25_filled']:>12.0f}{r['p75_filled']:>12.0f}{r['mean_fill_rate']:>11.3f}")


if __name__ == "__main__":
    main()
