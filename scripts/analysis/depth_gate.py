"""Gate the DEPTH model before trusting it (adversarial verify, read-only).

G1. Does the orderbook-derived top-of-book agree with the `prices` table?
    orderbook: yes_bid = max(yes level), yes_ask = 100 - max(no level).
    If these disagree with prices.yes_bid/yes_ask, one feed is wrong and BOTH
    this verification AND the original study (which uses `prices`) are suspect.

G2. Replay the depth model on REAL live_trades crossing orders: predict the
    immediate fill from book depth at the limit at placement time, compare to
    the actual fill_count. This is the only honest test of "how much size does
    a cross actually get".
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict

sys.path.insert(0, "/home/tdunn/wt-exec-compare/scripts")
sys.path.insert(0, "/home/tdunn/wt-exec-compare/src")

from weather_markets.db import get_connection  # noqa: E402

TOL = "10 minutes"


def books_at(conn, keys):
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH sig(k, ticker, dts) AS (SELECT * FROM unnest(
                    %s::int[], %s::text[], %s::timestamptz[]))
            SELECT s.k, o.side, o.price_cents, o.qty, o.snapshot_at
            FROM sig s
            JOIN LATERAL (
                SELECT snapshot_at FROM orderbook_snapshots
                WHERE ticker = s.ticker AND snapshot_at <= s.dts
                  AND snapshot_at > s.dts - interval '%s'
                ORDER BY snapshot_at DESC LIMIT 1
            ) l ON TRUE
            JOIN orderbook_snapshots o
              ON o.ticker = s.ticker AND o.snapshot_at = l.snapshot_at
            """ % ("%s", "%s", "%s", TOL),
            ([k[0] for k in keys], [k[1] for k in keys], [k[2] for k in keys]),
        )
        b = defaultdict(lambda: {"yes": [], "no": [], "at": None})
        for k, side, pc, qty, at in cur.fetchall():
            b[k][side].append((pc, qty))
            b[k]["at"] = at
    return b


def top(book):
    yb = max((pc for pc, q in book["yes"]), default=None)
    nb = max((pc for pc, q in book["no"]), default=None)
    return yb, (100 - nb if nb is not None else None)


def depth_at(book, side, limit):
    opp = "no" if side == "yes" else "yes"
    return sum(q for pc, q in book[opp] if pc >= 100 - limit)


with get_connection() as conn:
    # ---------------- G1: orderbook top-of-book vs prices table
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.ticker, p.snapshot_at, p.yes_bid, p.yes_ask
            FROM prices p JOIN contracts c ON c.ticker = p.ticker
            WHERE c.station_id IN ('KORD','KMIA','KDFW','KPHX')
              AND p.snapshot_at >= '2026-06-11' AND p.snapshot_at < '2026-07-13'
              AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
            ORDER BY random() LIMIT 400
            """
        )
        rows = cur.fetchall()
    bk = books_at(conn, [(i, tk, ts) for i, (tk, ts, _, _) in enumerate(rows)])
    bd = ad = n = 0
    exact_b = exact_a = 0
    for i, (tk, ts, pb, pa) in enumerate(rows):
        if i not in bk:
            continue
        yb, ya = top(bk[i])
        if yb is None or ya is None:
            continue
        n += 1
        bd += abs(yb - pb)
        ad += abs(ya - pa)
        exact_b += (yb == pb)
        exact_a += (ya == pa)
    print("=" * 90)
    print("G1 — orderbook_snapshots top-of-book vs `prices` table (400 random quotes, 4 cities)")
    print("=" * 90)
    print(f"  matched n={n}   yes_bid exact {exact_b/n*100:.1f}%  mean|diff| {bd/n:.2f}c"
          f"   |   yes_ask exact {exact_a/n*100:.1f}%  mean|diff| {ad/n:.2f}c")

    # ---------------- G2: depth model vs REAL live crossing fills
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.ticker, c.station_id, t.side, t.placed_at,
                   t.limit_price_cents, t.cross_price_cents, t.count, t.fill_count,
                   t.fill_status
            FROM live_trades t JOIN contracts c ON c.ticker = t.ticker
            WHERE t.fill_status NOT IN ('cancelled','rejected')
              AND t.placed_at >= '2026-06-10'
              AND t.limit_price_cents >= t.cross_price_cents   -- crossing (taker) orders
            ORDER BY t.id
            """
        )
        lt = cur.fetchall()
    bk = books_at(conn, [(r[0], r[1], r[4]) for r in lt])
    print()
    print("=" * 90)
    print("G2 — DEPTH MODEL vs REAL live crossing orders (predicted immediate fill vs actual)")
    print("=" * 90)
    print(f"  {'id':>4s} {'stn':<5s} {'sd':<3s} {'L':>3s} {'cnt':>5s} {'actual':>7s} {'pred':>6s} "
          f"{'act%':>5s} {'pred%':>5s}  status")
    ratios, acts, preds = [], [], []
    per_city = defaultdict(lambda: {"act": [], "pred": []})
    for tid, tk, stn, side, pa, L, Xp, cnt, fc, st in lt:
        if tid not in bk:
            print(f"  {tid:>4d} {stn:<5s} — no book snapshot within {TOL}")
            continue
        pred = min(cnt, depth_at(bk[tid], side, L))
        fc = fc or 0
        acts.append(fc / cnt)
        preds.append(pred / cnt)
        per_city[stn]["act"].append(fc / cnt)
        per_city[stn]["pred"].append(pred / cnt)
        print(f"  {tid:>4d} {stn:<5s} {side:<3s} {L:>3d} {cnt:>5d} {fc:>7d} {pred:>6d} "
              f"{fc/cnt*100:4.0f}% {pred/cnt*100:4.0f}%  {st}")
    print(f"\n  n={len(acts)} crossing orders since depth coverage began")
    print(f"  ACTUAL   mean fill {statistics.mean(acts)*100:.0f}%  median {statistics.median(acts)*100:.0f}%")
    print(f"  MODEL    mean fill {statistics.mean(preds)*100:.0f}%  median {statistics.median(preds)*100:.0f}%")
    print(f"  -> model {'UNDER' if statistics.mean(preds) < statistics.mean(acts) else 'OVER'}"
          f"states real cross fills by {abs(statistics.mean(acts)-statistics.mean(preds))*100:.0f}pp")
    for stn, d in sorted(per_city.items()):
        print(f"    {stn}: n={len(d['act'])} actual mean {statistics.mean(d['act'])*100:3.0f}%  "
              f"model mean {statistics.mean(d['pred'])*100:3.0f}%")
