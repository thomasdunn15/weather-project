"""How large can a ForecastEx order get before impact eats the edge?

ForecastEx publishes no order book, so we cannot walk depth directly. What we DO
have is every trade print (price, quantity, timestamp). This treats the prints in
the decision window as a proxy book: to accumulate N contracts you must consume
prints from the best price outward, so the volume-weighted price of the cheapest
N contracts vs the single best print approximates the slippage of a size-N sweep.

That proxy is OPTIMISTIC in one specific way worth stating: it assumes every
print in the window was available to us at that price, when in reality some of
that volume traded before our decision moment or against orders we could not
have hit. Read the output as an upper bound on tradeable size.

Break-even is measured against the strategy's OWN realized edge per contract,
so "significant" means a stated fraction of the edge, not an abstract cent count.

  uv run python scripts/analysis/forecastex_impact.py --station KMIA
"""
import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather_markets.db import get_connection

_REPO = Path(__file__).resolve().parents[2]
CACHE = _REPO / "data" / "forecastex_settlements.json"
BACKTEST_JSON = _REPO / "data" / "forecastex_backtest.json"
STATION_PRODUCT = {"KMIA": "UHMIA", "KLAX": "UHLAX", "KDFW": "UHDFW", "KPHX": "UHPHX",
                   "KSFO": "UHSFO", "KLAS": "UHLAS", "KSEA": "UHSEA", "KAUS": "UHAUS"}
MS = {"KMIA": "EMOS combined 00Z Miami (rolling 45d)",
      "KLAX": "EMOS combined 00Z Los Angeles (rolling 45d)",
      "KDFW": "EMOS combined 00Z Dallas (rolling 45d)",
      "KPHX": "EMOS combined 00Z Phoenix (rolling 45d)",
      "KSFO": "EMOS combined 00Z San Francisco (rolling 45d)",
      "KLAS": "EMOS combined 00Z Las Vegas (rolling 45d)",
      "KSEA": "EMOS combined 00Z Seattle (rolling 45d)",
      "KAUS": "EMOS combined 00Z Austin (rolling 45d)"}
DECISION_UTC = {"KMIA": (15, 30), "KDFW": (17, 32), "KPHX": (14, 52)}
SIZES = [25, 50, 75, 100, 150, 200, 300, 500, 750, 1000]
norm_sf = lambda x: 0.5 * math.erfc(x / math.sqrt(2.0))


def picked_contracts(conn, station: str, window_h: int):
    """Re-derive the rolling45 picks so impact is measured on the strikes we'd
    actually hit, and carry each pick's direction (we pay up on the side we buy)."""
    prod = STATION_PRODUCT[station]
    hh, mm = DECISION_UTC.get(station, (14, 45))
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (pt.target_date) pt.target_date, pt.emos_mu, pt.emos_sigma
        FROM paper_trades pt JOIN contracts c ON c.ticker=pt.ticker
        WHERE c.station_id=%s AND c.platform='kalshi' AND pt.model_source=%s
          AND pt.emos_mu IS NOT NULL ORDER BY pt.target_date, pt.logged_at""", (station, MS[station]))
    model = {r[0]: (float(r[1]), float(r[2])) for r in cur.fetchall()}
    settle = {date.fromisoformat(k): v
              for k, v in json.loads(CACHE.read_text()).get(prod, {}).items()}
    cur.execute("""SELECT c.target_date,c.ticker,c.strike_low,p.last_price,p.snapshot_at
        FROM contracts c JOIN prices p ON p.ticker=c.ticker
        WHERE c.platform='forecastex' AND c.station_id=%s AND p.last_price IS NOT NULL
        ORDER BY c.target_date,c.ticker,p.snapshot_at""", (station,))
    last = {}
    for td, tk, s, px, snap in cur.fetchall():
        cut = datetime.combine(td, datetime.min.time(), tzinfo=timezone.utc).replace(hour=hh, minute=mm)
        if snap <= cut:
            last[(td, tk)] = (float(s), int(px))
    byd = defaultdict(list)
    for (td, tk), (s, px) in last.items():
        byd[td].append((tk, s, px))
    common = sorted(d for d in model if d in settle)
    half = common[len(common) // 2] if common else None

    def roll(d, w=45, mn=10):
        past = [settle[x] - model[x][0] for x in common if x < d and (d - x).days <= w]
        return statistics.mean(past) if len(past) >= mn else None

    out = []
    for d in common:
        if half and d < half:
            continue                      # match the backtest's OOS half
        off = roll(d)
        if off is None:
            continue
        mu, sg = model[d]
        mu += off
        cands = []
        for tk, s, px in byd.get(d, []):
            p = norm_sf((s + 0.5 - mu) / sg)
            e = p - px / 100.0
            if abs(e) >= 0.10 and 5 <= px <= 95:
                cands.append((abs(e), e, tk, px))
        cands.sort(reverse=True)
        for _, e, tk, px in cands[:2]:
            out.append({"date": d, "ticker": tk, "buy_yes": e > 0, "quote": px})
    return out, hh, mm


def sweep(conn, picks, hh, mm, window_h) -> dict:
    """For each pick, consume window prints from the best price outward."""
    cur = conn.cursor()
    per_size = {n: {"filled": 0, "slip": [], "short": 0} for n in SIZES}
    for pk in picks:
        cur.execute("""
            SELECT last_price, volume FROM prices
            WHERE ticker=%s
              AND snapshot_at <= (%s::date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
              AND snapshot_at >= (%s::date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
                                  - make_interval(hours => %s)
              AND volume > 0""",
            (pk["ticker"], pk["date"], hh, mm, pk["date"], hh, mm, window_h))
        prints = cur.fetchall()
        if not prints:
            for n in SIZES:
                per_size[n]["short"] += 1
            continue
        # We buy YES at the YES price, or NO at (100 - YES). Cheapest first is
        # "best" for whichever side we are buying.
        levels = sorted(((int(p) if pk["buy_yes"] else 100 - int(p), int(v)) for p, v in prints),
                        key=lambda t: t[0])
        best = levels[0][0]
        for n in SIZES:
            need, cost, got = n, 0.0, 0
            for price, vol in levels:
                take = min(need, vol)
                cost += take * price
                got += take
                need -= take
                if need <= 0:
                    break
            if got == 0:
                per_size[n]["short"] += 1
                continue
            # An IOC PARTIAL-fills — it takes whatever is there and cancels the
            # rest. So "couldn't get all N" is not a zero-fill day; it is a
            # smaller position at the swept price. Track both the full-fill rate
            # and the realized (partial) quantity, because EV depends on the
            # latter while slippage discipline depends on the former.
            if need > 0:
                per_size[n]["short"] += 1
            else:
                per_size[n]["filled"] += 1
            per_size[n]["slip"].append(cost / got - best)
            per_size[n].setdefault("got", []).append(got)
    return per_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station", default="KMIA", choices=sorted(STATION_PRODUCT))
    ap.add_argument("--window-hours", type=int, default=2)
    a = ap.parse_args()

    # realized edge per contract from the backtest artifact (net of the 1c fee)
    edge_c = None
    if BACKTEST_JSON.exists():
        for c in json.loads(BACKTEST_JSON.read_text()).get("cities", []):
            if c["station"] == a.station:
                r = c["variants"]["rolling45"]
                if r.get("avg_usd") and c.get("contracts"):
                    edge_c = r["avg_usd"] * 100 / c["contracts"]

    conn = get_connection()
    try:
        picks, hh, mm = picked_contracts(conn, a.station, a.window_hours)
        if not picks:
            print(f"{a.station}: no picks to measure.")
            return 0
        res = sweep(conn, picks, hh, mm, a.window_hours)
    finally:
        conn.close()

    print(f"\n=== {a.station} ({STATION_PRODUCT[a.station]}) size-vs-impact — "
          f"{len(picks)} picks, {a.window_hours}h pre-decision ({hh:02d}:{mm:02d} UTC) ===")
    if edge_c:
        print(f"realized edge to defend: {edge_c:.1f}c/contract (rolling45, net of fee)")
    print(f"\n{'sent':>6} {'fullfill':>9} {'avg got':>8} {'med slip':>9} "
          f"{'edge left':>10} {'EV/day idx':>11}  verdict")
    best_ev, best_n = 0.0, None
    rows = []
    for n in SIZES:
        d = res[n]
        tot = d["filled"] + d["short"]
        if not d["slip"]:
            rows.append((n, 0.0, 0.0, None, None, 0.0, "never fillable"))
            continue
        s = sorted(d["slip"])
        med = s[len(s) // 2]
        gots = d.get("got", [])
        avg_got = sum(gots) / len(gots) if gots else 0.0
        full = 100 * d["filled"] / tot if tot else 0.0
        left = (edge_c - med) if edge_c else None
        # EV index = what we actually end up holding x the edge that survives.
        ev = (avg_got * left) if (left and left > 0) else 0.0
        if ev > best_ev:
            best_ev, best_n = ev, n
        rows.append((n, full, avg_got, med, left, ev, ""))
    for i, (n, full, avg_got, med, left, ev, note) in enumerate(rows):
        if note:
            print(f"{n:6d} {0:8.0f}% {'–':>8} {'–':>9} {'–':>10} {'–':>11}  {note}")
            continue
        rel = ev / best_ev if best_ev else 0
        if left is not None and left <= 0:
            verdict = "EDGE GONE"
        elif full < 50:
            verdict = "mostly partial fills"
        elif left is not None and left < edge_c * 0.5:
            verdict = "over half the edge lost"
        elif left is not None and left < edge_c * 0.75:
            verdict = "meaningful erosion"
        else:
            verdict = "safe"
        star = "  <-- EV peak" if n == best_n else ""
        print(f"{n:6d} {full:8.0f}% {avg_got:8.0f} {med:8.1f}c {left:9.1f}c "
              f"{rel:10.0%}  {verdict}{star}")
    print("\nEV/day idx = (contracts actually filled) x (edge surviving slippage), "
          "relative to its own peak.\nFull-fill% is the discipline number; EV peak "
          "assumes you are content to partial-fill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
