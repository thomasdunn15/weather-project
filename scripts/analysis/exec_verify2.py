"""Verify pass 2 — after the snapshot-depth model FAILED its ground-truth gate
(predicts 12% fill on real crossing orders that actually filled 88%).

Now use REAL fill fractions from live_trades instead of a book model.

V1. Maker (POST) vs taker (CROSS) realized fill fractions, per city.
V2. Do the 13 crux trades appear in live_trades?  What ACTUALLY happened?
V3. Empirical-fill-haircut P&L: cross gets its city's realized mean fill,
    post gets the maker realized mean fill.
V4. Break-even: how much must the cross-only catches be haircut / how many
    must be losers before CROSS loses to POST?
V5. Does book depth predict realized fill at all? (can we haircut selectively?)
V6. Leave-one-out on the crux trades.
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict

sys.path.insert(0, "/home/tdunn/wt-exec-compare/scripts/analysis")
sys.path.insert(0, "/home/tdunn/wt-exec-compare/scripts")
sys.path.insert(0, "/home/tdunn/wt-exec-compare/src")

import exec_mode_compare as X  # noqa: E402
from live_trade import CITY_CONFIG  # noqa: E402
from weather_markets.db import get_connection  # noqa: E402

CITIES = ["KORD", "KMIA", "KDFW", "KPHX"]

with get_connection() as conn:
    # ---------------------------------------------------- V1 realized fills
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.station_id, t.id,
                   (t.limit_price_cents < t.cross_price_cents) AS is_maker,
                   t.count, coalesce(t.fill_count,0), t.fill_status, t.placed_at::date
            FROM live_trades t JOIN contracts c ON c.ticker = t.ticker
            WHERE t.fill_status NOT IN ('cancelled','rejected')
            ORDER BY t.id
            """
        )
        rows = cur.fetchall()
    grp = defaultdict(list)
    for stn, tid, mk, cnt, fc, st, d in rows:
        grp[("maker" if mk else "taker", stn)].append(fc / cnt)
        grp[("maker" if mk else "taker", "ALL")].append(fc / cnt)
    print("=" * 92)
    print("V1 — REALIZED fill fraction on REAL live orders (the only honest size evidence)")
    print("=" * 92)
    print(f"  {'type':<6s} {'stn':<5s} {'n':>3s} {'mean':>6s} {'median':>7s} {'zero':>5s} "
          f"{'<50%':>5s} {'100%':>5s}")
    for k in sorted(grp, key=lambda k: (k[0], k[1])):
        v = grp[k]
        print(f"  {k[0]:<6s} {k[1]:<5s} {len(v):>3d} {statistics.mean(v)*100:5.0f}% "
              f"{statistics.median(v)*100:6.0f}% {sum(1 for x in v if x==0):>5d} "
              f"{sum(1 for x in v if 0<x<0.5):>5d} {sum(1 for x in v if x>=0.999):>5d}")

    # ---------------------------------------------------- V2 crux trades live?
    print()
    print("=" * 92)
    print("V2 — the crux trades vs REALITY (were they actually placed live? what filled?)")
    print("=" * 92)
    crux = []
    for city in CITIES:
        cfg = CITY_CONFIG[city]
        sigs, _, _ = X.fetch_signals(conn, city)
        post = {(t["date"], t["ticker"]): t for t in X.simulate(sigs, "post_inside_spread", cfg)}
        cross = X.simulate(sigs, "cross_at_ask", cfg)
        for t in cross:
            if not post[(t["date"], t["ticker"])]["filled"]:
                crux.append({**t, "city": city})
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, target_date, id, side, limit_price_cents, cross_price_cents,
                   count, coalesce(fill_count,0), fill_status, edge
            FROM live_trades WHERE fill_status NOT IN ('cancelled','rejected')
            """
        )
        live = {(d, tk): r for tk, d, *r in
                [(a, b, c, dd, e, f, g, h, i, j) for a, b, c, dd, e, f, g, h, i, j in cur.fetchall()]}
    for t in sorted(crux, key=lambda t: (t["city"], t["date"])):
        k = (t["date"], t["ticker"])
        lv = live.get(k)
        tag = "NOT TRADED LIVE"
        if lv:
            tid, side, L, Xp, cnt, fc, st, edge = lv
            mode = "POST" if L < Xp else "CROSS"
            tag = f"LIVE {mode} id={tid} L={L} X={Xp} filled {fc}/{cnt} ({fc/cnt*100:.0f}%) {st}"
        print(f"  {t['city']} {t['date']} {t['ticker']:<27s} edge={t['edge']:+.2f} "
              f"won={str(t['won']):5s} study_net=${t['net']:+8.2f}  | {tag}")

    # ---------------------------------------------------- V3/V4 haircuts
    print()
    print("=" * 92)
    print("V3/V4 — empirical-fill haircut + break-even on the crux")
    print("=" * 92)
    taker_f = {s: statistics.mean(v) for (ty, s), v in grp.items() if ty == "taker"}
    maker_f = statistics.mean(grp[("maker", "ALL")])
    print(f"  maker realized fill (all cities, n={len(grp[('maker','ALL')])}) = {maker_f*100:.0f}%")
    print(f"  taker realized fill per city: "
          + "  ".join(f"{s}={v*100:.0f}%" for s, v in sorted(taker_f.items()) if s in CITIES))
    print()
    print(f"  {'city':<5s} {'POST':>9s} {'CROSS':>9s} {'CROSS x fill':>13s} {'gap':>9s} "
          f"{'break-even fill':>16s}  verdict")
    for city in CITIES:
        cfg = CITY_CONFIG[city]
        sigs, _, _ = X.fetch_signals(conn, city)
        p = X.metrics(X.simulate(sigs, "post_inside_spread", cfg))["net"]
        c = X.metrics(X.simulate(sigs, "cross_at_ask", cfg))["net"]
        f = taker_f.get(city, 1.0)
        # POST also haircut by the maker realized fill (fair to both arms)
        ph = p * maker_f
        ch = c * f
        be = (ph / c * 100) if c > 0 else float("nan")
        print(f"  {city:<5s} {ph:9.2f} {c:9.2f} {ch:13.2f} {ch-ph:9.2f} {be:15.1f}%  "
              f"{'CROSS' if ch > ph else 'POST'}")

    # how many of the crux must be losers to erase the gap, per city
    print()
    for city in CITIES:
        cfg = CITY_CONFIG[city]
        sigs, _, _ = X.fetch_signals(conn, city)
        p = X.metrics(X.simulate(sigs, "post_inside_spread", cfg))["net"]
        cr = X.simulate(sigs, "cross_at_ask", cfg)
        post = {(t["date"], t["ticker"]): t for t in X.simulate(sigs, "post_inside_spread", cfg)}
        only = [t for t in cr if not post[(t["date"], t["ticker"])]["filled"]]
        shared = sum(t["net"] for t in cr if post[(t["date"], t["ticker"])]["filled"])
        gap = (shared + sum(t["net"] for t in only)) - p
        # flip winners to losers (a loser = -entry/100*unit - fee), biggest first
        flips = sorted(only, key=lambda t: -t["net"])
        need, run = 0, gap
        for t in flips:
            loss = -t["entry"] / 100.0 * cfg["unit_contracts"]
            run -= (t["net"] - loss)
            need += 1
            if run <= 0:
                break
        print(f"  {city}: CROSS−POST = ${gap:+.2f}; flipping {need} of {len(only)} crux "
              f"trade(s) from win->loss erases it (run={run:+.1f})")

    # ---------------------------------------------------- V6 leave-one-out
    print()
    print("=" * 92)
    print("V6 — leave-one-out on the crux trades (KORD/KDFW: does 1 trade carry it?)")
    print("=" * 92)
    for city in ["KORD", "KDFW"]:
        cfg = CITY_CONFIG[city]
        sigs, _, _ = X.fetch_signals(conn, city)
        p = X.metrics(X.simulate(sigs, "post_inside_spread", cfg))["net"]
        cr = X.simulate(sigs, "cross_at_ask", cfg)
        post = {(t["date"], t["ticker"]): t for t in X.simulate(sigs, "post_inside_spread", cfg)}
        only = [t for t in cr if not post[(t["date"], t["ticker"])]["filled"]]
        base = sum(t["net"] for t in cr)
        print(f"  {city}: POST ${p:+.2f}  CROSS ${base:+.2f}")
        for t in only:
            print(f"    drop {t['date']} ({t['ticker'][-8:]}, ${t['net']:+.0f}) -> "
                  f"CROSS ${base - t['net']:+.2f}  {'CROSS' if base - t['net'] > p else 'POST'} wins")
