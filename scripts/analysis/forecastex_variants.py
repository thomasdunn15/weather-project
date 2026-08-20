"""Which ForecastEx strategy variant actually survives, per city and overall?

Sweeps four axes on the held-out half, scoring every result NET OF EACH CITY'S
MEASURED SPREAD (scripts/analysis/forecastex_spread.py) rather than the
zero-spread assumption the original backtest used:

  strategy      raw | blend | union   (blend = Benter-style logit of model+market)
  edge          0.10 .. 0.25
  min entry     0 | 10 | 20 | 30c     (a fixed ~8c spread is fatal to cheap
                                       contracts and trivial to dear ones)
  picks/day     1 | 2 | 3

THE DISCIPLINE PROBLEM. 9 cities x ~100 variants is ~900 draws; the best of 900
looks spectacular by luck alone, and this stack has been burned before —
per-city parameter tuning previously overfit 6 of 11 cities. So the headline
here is NOT the per-city winner. It is:

  1. the best SINGLE variant applied UNIFORMLY to every city, which cannot fit
     any one city's noise, and
  2. whether a variant's advantage shows up in BOTH halves of the OOS window.

Per-city bests are printed, but flagged as what they are: candidates to be
distrusted until a forward test says otherwise.

Blend is fit walk-forward — coefficients come only from days strictly before
the day being scored, mirroring the rolling debias — so it carries no lookahead.

  uv run python scripts/analysis/forecastex_variants.py --all
  uv run python scripts/analysis/forecastex_variants.py --station KMIA --top 15
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.forecastex import PRODUCT_TO_STATION

_REPO = Path(__file__).resolve().parents[2]
SETTLE_CACHE = _REPO / "data" / "forecastex_settlements.json"
SPREAD_JSON = _REPO / "data" / "forecastex_spread.json"
OUT_JSON = _REPO / "data" / "forecastex_variants.json"
STATION_PRODUCT = {v: k for k, v in PRODUCT_TO_STATION.items()}

MODEL_SOURCE = {
    "KMIA": "Miami", "KLAX": "Los Angeles", "KDFW": "Dallas", "KPHX": "Phoenix",
    "KSFO": "San Francisco", "KLAS": "Las Vegas", "KSEA": "Seattle",
    "KAUS": "Austin", "KMSY": "New Orleans", "KMDW": "Chicago",
}
DECISION_UTC = {"KMIA": (15, 30), "KDFW": (17, 32), "KPHX": (14, 52)}
FEE_C = 1.0

STRATEGIES = ("raw", "blend", "union")
THRESHOLDS = (0.10, 0.15, 0.20, 0.25)
MIN_ENTRY = (0, 10, 20, 30)
MAX_PICKS = (1, 2, 3)

norm_sf = lambda x: 0.5 * math.erfc(x / math.sqrt(2.0))
_clip = lambda p: min(max(p, 1e-6), 1 - 1e-6)
_logit = lambda p: math.log(_clip(p) / (1 - _clip(p)))
_sig = lambda x: 1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, x))))


def load_city(conn, station: str):
    """Model mu/sigma per day, ForecastEx settled highs, and the last pre-decision
    print per contract."""
    prod = STATION_PRODUCT[station]
    hh, mm = DECISION_UTC.get(station, (14, 45))
    src = f"EMOS combined 00Z {MODEL_SOURCE[station]} (rolling 45d)"
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (pt.target_date) pt.target_date, pt.emos_mu, pt.emos_sigma
            FROM paper_trades pt JOIN contracts c ON c.ticker=pt.ticker
            WHERE c.station_id=%s AND c.platform='kalshi' AND pt.model_source=%s
              AND pt.emos_mu IS NOT NULL ORDER BY pt.target_date, pt.logged_at""",
            (station, src))
        model = {r[0]: (float(r[1]), float(r[2])) for r in cur.fetchall()}
        cur.execute("""SELECT c.target_date, c.ticker, c.strike_low, p.last_price, p.snapshot_at
            FROM contracts c JOIN prices p ON p.ticker=c.ticker
            WHERE c.platform='forecastex' AND c.station_id=%s AND p.last_price IS NOT NULL
            ORDER BY c.target_date, c.ticker, p.snapshot_at""", (station,))
        rows = cur.fetchall()
    last = {}
    for td, tk, strike, px, snap in rows:
        cut = datetime.combine(td, datetime.min.time(), tzinfo=timezone.utc
                               ).replace(hour=hh, minute=mm)
        if snap <= cut:
            last[(td, tk)] = (float(strike), int(px))
    byd = defaultdict(list)
    for (td, tk), (strike, px) in last.items():
        byd[td].append((tk, strike, px))
    settle = {date.fromisoformat(k): v
              for k, v in json.loads(SETTLE_CACHE.read_text()).get(prod, {}).items()}
    return model, settle, byd


def fit_blend(hist: list[tuple]) -> tuple[float, float, float] | None:
    """Newton-fit logit(y) ~ a + b*logit(p_model) + c*logit(p_market).

    Returns None below 60 observations — a blend fit on thin history is just a
    noisier copy of the model, and pretending otherwise is how a 'blend' variant
    wins a sweep without meaning anything.
    """
    if len(hist) < 60:
        return None
    X = [(1.0, _logit(pm), _logit(pk)) for pm, pk, _ in hist]
    y = [float(o) for _, _, o in hist]
    beta = [0.0, 1.0, 0.0]
    for _ in range(25):
        g = [0.0] * 3
        H = [[0.0] * 3 for _ in range(3)]
        for xi, yi in zip(X, y):
            p = _sig(sum(b * x for b, x in zip(beta, xi)))
            w = max(p * (1 - p), 1e-9)
            for a in range(3):
                g[a] += (yi - p) * xi[a]
                for b_ in range(3):
                    H[a][b_] += w * xi[a] * xi[b_]
        for a in range(3):                       # ridge: these inputs are collinear
            H[a][a] += 1e-4
        try:
            step = _solve3(H, g)
        except ZeroDivisionError:
            return None
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return tuple(beta)


def _solve3(A, b):
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            raise ZeroDivisionError
        M[i], M[piv] = M[piv], M[i]
        for r in range(3):
            if r == i:
                continue
            f = M[r][i] / M[i][i]
            for c in range(i, 4):
                M[r][c] -= f * M[i][c]
    return [M[i][3] / M[i][i] for i in range(3)]


def replay(model, settle, byd, spread_c: float):
    """One pass producing, per day, every candidate with its model/market prob and
    outcome. Variants then filter this rather than re-deriving it 100 times."""
    common = sorted(d for d in model if d in settle)
    if len(common) < 20:
        return None, None
    half = common[len(common) // 2]

    def roll_offset(d, w=45, mn=10):
        past = [settle[x] - model[x][0] for x in common if x < d and (d - x).days <= w]
        return statistics.mean(past) if len(past) >= mn else None

    per_day, hist = {}, []
    for d in common:
        off = roll_offset(d)
        if off is None:
            continue
        mu, sg = model[d]
        mu += off
        high = settle[d]
        fit = fit_blend(hist) if d >= half else None
        cands = []
        for tk, strike, px in byd.get(d, []):
            if not 5 <= px <= 95:
                continue
            p_model = norm_sf((strike + 0.5 - mu) / sg)
            p_mkt = px / 100.0
            won_yes = high > strike
            hist.append((p_model, p_mkt, won_yes))
            p_bl = (_sig(fit[0] + fit[1] * _logit(p_model) + fit[2] * _logit(p_mkt))
                    if fit else None)
            cands.append({"px": px, "p_model": p_model, "p_blend": p_bl,
                          "won_yes": won_yes})
        if d >= half and cands:
            per_day[d] = cands
    return per_day, half


def score(per_day, strategy, thresh, min_entry, max_picks, spread_c, contracts=500):
    """Net cents per day for one variant. Entry pays the full measured spread —
    ForecastEx has no maker rebate, so every fill crosses."""
    daily = {}
    n = 0
    for d, cands in per_day.items():
        picks = []
        for c in cands:
            edges = []
            if strategy in ("raw", "union"):
                edges.append(c["p_model"] - c["px"] / 100.0)
            if strategy in ("blend", "union") and c["p_blend"] is not None:
                edges.append(c["p_blend"] - c["px"] / 100.0)
            if not edges:
                continue
            e = max(edges, key=abs)
            if abs(e) < thresh:
                continue
            entry = c["px"] if e > 0 else 100 - c["px"]
            if entry < min_entry:
                continue
            picks.append((abs(e), entry, (c["won_yes"] if e > 0 else not c["won_yes"])))
        picks.sort(reverse=True)
        if not picks:
            continue
        tot = 0.0
        for _, entry, won in picks[:max_picks]:
            tot += ((100 - entry) if won else -entry) - FEE_C - spread_c
            n += 1
        daily[d] = tot * contracts
    if len(daily) < 8:
        return None
    v = list(daily.values())
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    sharpe = (statistics.mean(v) / sd) * (252 ** 0.5) if sd > 0 else None
    days = sorted(daily)
    mid = days[len(days) // 2]
    h1 = sum(daily[x] for x in days if x < mid) / 100
    h2 = sum(daily[x] for x in days if x >= mid) / 100
    return {"net": sum(v) / 100, "sharpe": round(sharpe, 2) if sharpe else None,
            "tstat": round(sharpe * math.sqrt(len(v) / 252), 2) if sharpe else None,
            "days": len(v), "trades": n, "h1": round(h1), "h2": round(h2),
            "both_halves": h1 > 0 and h2 > 0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", default="KMIA", choices=sorted(STATION_PRODUCT))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    spreads = {c["station"]: c["median_c"]
               for c in json.loads(SPREAD_JSON.read_text())["cities"]} \
        if SPREAD_JSON.exists() else {}
    if not spreads:
        print("run forecastex_spread.py --all --json first"); return 1

    stations = sorted(STATION_PRODUCT) if a.all else [a.station]
    conn = get_connection()
    per_city, uniform = {}, defaultdict(list)
    try:
        for st in stations:
            sp = spreads.get(st)
            if sp is None:
                continue
            per_day, half = replay(*load_city(conn, st), sp)
            if not per_day:
                print(f"{st}: too little overlap to score"); continue
            res = {}
            for s in STRATEGIES:
                for th in THRESHOLDS:
                    for me in MIN_ENTRY:
                        for mp in MAX_PICKS:
                            r = score(per_day, s, th, me, mp, sp)
                            if r:
                                res[(s, th, me, mp)] = r
                                uniform[(s, th, me, mp)].append((st, r))
            per_city[st] = (sp, res)
            print(f"{st}: scored {len(res)} variants (spread {sp:.1f}c, OOS from {half})")
    finally:
        conn.close()

    # --- the honest headline: one config, every city, no per-city fitting -----
    print("\n" + "=" * 78)
    print("BEST UNIFORM VARIANT — same config for all cities, so it cannot fit one")
    print("=" * 78)
    rows = []
    for key, hits in uniform.items():
        if len(hits) < len(per_city):
            continue                       # must be scorable everywhere
        tot = sum(r["net"] for _, r in hits)
        pos = sum(1 for _, r in hits if r["net"] > 0)
        both = sum(1 for _, r in hits if r["both_halves"])
        rows.append((tot, key, pos, both, len(hits)))
    rows.sort(reverse=True)
    print(f"{'strategy':>9}{'edge':>6}{'minPx':>7}{'picks':>6}{'total net':>12}"
          f"{'cities +':>10}{'both halves':>13}")
    for tot, (s, th, me, mp), pos, both, n in rows[:a.top]:
        print(f"{s:>9}{th:6.2f}{me:7d}{mp:6d}${tot:11,.0f}{pos:7d}/{n}{both:10d}/{n}")

    baseline = next((r for r in rows if r[1] == ("raw", 0.10, 0, 2)), None)
    if baseline:
        print(f"\n  current live config (raw, 0.10, no min price, 2 picks): "
              f"${baseline[0]:,.0f}  — rank "
              f"{[r[1] for r in rows].index(('raw',0.10,0,2)) + 1} of {len(rows)}")

    print("\n" + "=" * 78)
    print("PER-CITY BEST — treat as overfit candidates, not conclusions")
    print("=" * 78)
    print(f"{'city':6}{'spread':>8}{'strategy':>9}{'edge':>6}{'minPx':>7}{'picks':>6}"
          f"{'net':>10}{'t':>6}{'both halves':>13}")
    for st, (sp, res) in per_city.items():
        if not res:
            continue
        k, r = max(res.items(), key=lambda kv: kv[1]["net"])
        print(f"{st:6}{sp:7.1f}c{k[0]:>9}{k[1]:6.2f}{k[2]:7d}{k[3]:6d}"
              f"${r['net']:9,.0f}{r['tstat'] or 0:6.2f}"
              f"{'yes' if r['both_halves'] else 'NO':>13}")

    if a.json:
        OUT_JSON.write_text(json.dumps({
            "note": "net of each city's measured spread; uniform ranking is the "
                    "trustworthy view, per-city bests are overfit candidates",
            "uniform": [{"strategy": s, "edge": th, "min_entry": me, "picks": mp,
                         "total_net": round(tot), "cities_positive": pos,
                         "both_halves": both, "n_cities": n}
                        for tot, (s, th, me, mp), pos, both, n in rows[:40]],
        }, indent=1))
        print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
