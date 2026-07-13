"""ADVERSARIAL VERIFY of research/exec-mode-compare (39e7a2a) — read-only.

Reuses exec_mode_compare's signal reconstruction (so numbers are directly
comparable) but replaces its PRICE-only fill model with a DEPTH-aware one built
from `orderbook_snapshots` (all levels, every ~5 min, since 2026-06-10).

Book convention (same as walk_book_capacity.py): orderbook_snapshots stores
resting BIDS on both sides. To BUY YES you lift the 'no' ladder (a no-bid at
price q is a yes-ask at 100-q). To BUY NO you lift the 'yes' ladder.
=> contracts available to buy `side` at limit L
   = sum(qty) over the OPPOSITE side's levels with price_cents >= 100 - L.

Arms:
  cross_depth_0  : cross at ask, fill only the depth resting at/inside the limit;
                   remainder is NEVER filled (matches live partial-fill evidence:
                   KDFW id=77 97/500, KPHX 83/250 -> remainder rested and died).
  cross_depth_px : same immediate fill, remainder rests at the cross price and
                   fills IF the price test passes (as maker, 1/4 fee) -- the
                   optimistic bound the original study implicitly assumes.
  post_depth     : POST fills full unit when the price test passes (live makers
                   that filled, filled 100%: ids 2, 24) -- unchanged, i.e. this
                   correction is applied ONLY against CROSS, the arm under test.

Usage: uv run python scripts/analysis/exec_mode_verify.py
"""
from __future__ import annotations

import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# reuse the study's own code (do not re-type its logic)
sys.path.insert(0, "/home/tdunn/wt-exec-compare/scripts/analysis")
sys.path.insert(0, "/home/tdunn/wt-exec-compare/scripts")
sys.path.insert(0, "/home/tdunn/wt-exec-compare/src")

import exec_mode_compare as X  # noqa: E402
from live_trade import CITY_CONFIG, kalshi_fee_cents  # noqa: E402
from weather_markets.db import get_connection  # noqa: E402

CITIES = ["KORD", "KMIA", "KDFW", "KPHX"]
TOL_MIN = 20
DEPTH_START = "2026-06-10"  # orderbook_snapshots coverage begins here


# ---------------------------------------------------------------- depth pulls
def fetch_books(conn, keys):
    """keys=[(ticker, ts)] -> {ticker: {'yes': [(pc,qty)], 'no': [...], 'at': ts}}"""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH sig(ticker, dts) AS (SELECT * FROM unnest(%s::text[], %s::timestamptz[]))
            SELECT s.ticker, o.side, o.price_cents, o.qty, o.snapshot_at
            FROM sig s
            JOIN LATERAL (
                SELECT snapshot_at FROM orderbook_snapshots
                WHERE ticker = s.ticker AND snapshot_at <= s.dts
                  AND snapshot_at > s.dts - (%s || ' minutes')::interval
                ORDER BY snapshot_at DESC LIMIT 1
            ) l ON TRUE
            JOIN orderbook_snapshots o
              ON o.ticker = s.ticker AND o.snapshot_at = l.snapshot_at
            """,
            ([k[0] for k in keys], [k[1] for k in keys], str(TOL_MIN)),
        )
        books = defaultdict(lambda: {"yes": [], "no": [], "at": None})
        for tk, side, pc, qty, at in cur.fetchall():
            books[tk][side].append((pc, qty))
            books[tk]["at"] = at
    return books


def depth_at(book, side, limit):
    """Contracts buyable of `side` at price <= limit (lift the opposite ladder)."""
    opp = "no" if side == "yes" else "yes"
    return sum(q for pc, q in book[opp] if pc >= 100 - limit)


# ---------------------------------------------------------------- simulation
def pnl(entry, won, qty, maker):
    if qty <= 0:
        return 0.0
    gross = ((100 - entry) if won else -entry) / 100.0 * qty
    return gross - kalshi_fee_cents(entry, maker) / 100.0 * qty


def simulate(sigs, mode, cfg, books):
    """mode in post | cross_depth_0 | cross_depth_px | cross_nodepth (study's)"""
    unit = cfg["unit_contracts"]
    out = []
    for s in sigs:
        book = books.get(s["ticker"])
        if mode == "post":
            limit, cross, _ = X.limit_price_for("post_inside_spread", s["side"], s["bid"], s["ask"])
            crossing = limit >= cross
            filled = True if crossing else X.would_fill(s["side"], limit, s["min_ask"], s["max_bid"])
            qty = unit if filled else 0
            maker = (not crossing) and filled
            out.append({**s, "qty": qty, "entry": limit, "net": pnl(limit, s["won"], qty, maker)})
            continue

        limit, cross, _ = X.limit_price_for("cross_at_ask", s["side"], s["bid"], s["ask"])
        if mode == "cross_nodepth":
            out.append({**s, "qty": unit, "entry": limit,
                        "net": pnl(limit, s["won"], unit, False)})
            continue
        avail = depth_at(book, s["side"], limit) if book else 0
        taken = min(unit, avail)
        rest = unit - taken
        net = pnl(limit, s["won"], taken, False)
        rest_filled = 0
        if mode == "cross_depth_px" and rest > 0:
            if X.would_fill(s["side"], limit, s["min_ask"], s["max_bid"]):
                rest_filled = rest
                net += pnl(limit, s["won"], rest, True)  # rests -> maker fee
        out.append({**s, "qty": taken + rest_filled, "avail": avail, "taken": taken,
                    "entry": limit, "net": net})
    return out


def met(trades):
    filled = [t for t in trades if t["qty"] > 0]
    nets = [t["net"] for t in filled]
    allp = [t["net"] for t in trades]

    def sh(xs):
        return (statistics.mean(xs) / statistics.stdev(xs) * math.sqrt(252)
                if len(xs) > 1 and statistics.stdev(xs) > 0 else 0.0)

    peak = cum = mdd = 0.0
    for p in allp:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return dict(n=len(trades), nf=len(filled), net=sum(nets), sharpe=sh(nets),
                sh_all=sh(allp), mdd=mdd,
                qty=statistics.mean([t["qty"] for t in trades]) if trades else 0)


def perm_test(wins, n_iter=200000, base=0.4):
    """P(>= k winners in n) under independent Bernoulli(base) -- exact binomial."""
    n, k = len(wins), sum(wins)
    p = sum(math.comb(n, i) * base**i * (1 - base)**(n - i) for i in range(k, n + 1))
    return n, k, p


def main():
    with get_connection() as conn:
        print("=" * 100)
        print("A1 — DEPTH-AWARE CROSS  (book depth at the cross price, orderbook_snapshots)")
        print("=" * 100)
        allcross = []
        for city in CITIES:
            cfg = CITY_CONFIG[city]
            sigs, _, _ = X.fetch_signals(conn, city)
            sigs = [s for s in sigs if str(s["date"]) >= DEPTH_START]  # depth coverage
            books = fetch_books(conn, [(s["ticker"], X.decision_ts(cfg, s["date"])) for s in sigs])
            missing = [s for s in sigs if s["ticker"] not in books]
            sigs = [s for s in sigs if s["ticker"] in books]
            unit = cfg["unit_contracts"]

            arms = {m: simulate(sigs, m, cfg, books)
                    for m in ("post", "cross_nodepth", "cross_depth_0", "cross_depth_px")}
            print(f"\n{city}  n={len(sigs)} (depth-covered; {len(missing)} dropped no-book) "
                  f"unit={unit}  window {sigs[0]['date']}..{sigs[-1]['date']}")
            print(f"  {'arm':<16s} {'net $':>9s} {'Sharpe':>7s} {'maxDD':>9s} {'avg qty':>8s} {'fill%':>6s}")
            for m, tr in arms.items():
                x = met(tr)
                print(f"  {m:<16s} {x['net']:9.2f} {x['sharpe']:7.2f} {x['mdd']:9.2f} "
                      f"{x['qty']:8.0f} {x['qty']/unit*100:5.0f}%")

            cd = arms["cross_depth_0"]
            avails = [t["avail"] for t in cd]
            fr = [min(unit, a) / unit for a in avails]
            print(f"  depth at cross price: median {statistics.median(avails):.0f}  "
                  f"mean {statistics.mean(avails):.0f}  "
                  f"| realistic cross fill: mean {statistics.mean(fr)*100:.0f}% "
                  f"median {statistics.median(fr)*100:.0f}%  "
                  f"| {sum(1 for a in avails if a >= unit)}/{len(avails)} signals had full size")

            # the crux trades, depth-corrected
            post = {(t["date"], t["ticker"]): t for t in arms["post"]}
            only = [t for t in cd if post[(t["date"], t["ticker"])]["qty"] == 0]
            if only:
                nd = {(t["date"], t["ticker"]): t for t in arms["cross_nodepth"]}
                print(f"  CROSS-ONLY CATCHES n={len(only)}:")
                for t in sorted(only, key=lambda t: t["date"]):
                    full = nd[(t["date"], t["ticker"])]["net"]
                    print(f"    {t['date']} {t['ticker']:<26s} {t['side']:3s} edge={t['edge']:+.2f} "
                          f"entry={t['entry']:2d} won={str(t['won']):5s} "
                          f"depth={t['avail']:5d}/{unit} -> ${t['net']:+9.2f}  "
                          f"(study assumed full size: ${full:+9.2f})")
                    allcross.append({**t, "city": city, "full_net": full})
        return allcross


if __name__ == "__main__":
    cross_only = main()
    print("\n" + "=" * 100)
    print("A2 — THE n=13 CRUX (pooled, depth-corrected)")
    print("=" * 100)
    nets_full = [t["full_net"] for t in cross_only]
    nets_dep = [t["net"] for t in cross_only]
    wins = [t["won"] for t in cross_only]
    print(f"  n={len(cross_only)}  winners={sum(wins)}")
    if nets_full:
        print(f"  study (full unit): mean ${statistics.mean(nets_full):+.2f}  "
              f"median ${statistics.median(nets_full):+.2f}  total ${sum(nets_full):+.2f}")
        print(f"  depth-corrected  : mean ${statistics.mean(nets_dep):+.2f}  "
              f"median ${statistics.median(nets_dep):+.2f}  total ${sum(nets_dep):+.2f}")
        print(f"  sorted full-unit P&L: {[round(x) for x in sorted(nets_full)]}")
        print(f"  sorted depth   P&L : {[round(x) for x in sorted(nets_dep)]}")
    n, k, p = perm_test(wins)
    print(f"  binomial (indep, base 40%): {k}/{n} winners, p={p:.2e}")
    dates = defaultdict(list)
    for t in cross_only:
        dates[str(t["date"])].append(t["city"])
    print(f"  distinct dates: {len(dates)} for {len(cross_only)} trades -> "
          f"clusters: {[(d, c) for d, c in dates.items() if len(c) > 1]}")
    # cluster-robust: one Bernoulli draw per DATE (sign of the date's total)
    dsign = defaultdict(float)
    for t in cross_only:
        dsign[str(t["date"])] += t["full_net"]
    dw = [1 if v > 0 else 0 for v in dsign.values()]
    n2, k2, p2 = perm_test(dw)
    print(f"  cluster-by-date (1 obs/date): {k2}/{n2} positive days, p={p2:.3f}")
