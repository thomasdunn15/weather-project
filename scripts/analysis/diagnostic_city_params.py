"""Per-city strategy diagnostic + parameter sweep (read-only research).

Reads /tmp/pt_dataset.csv (exported from paper_trades JOIN contracts JOIN
observations, with net PnL computed via the project's canonical Kalshi fee /
settlement model) and:

  1. Computes baseline per-city metrics (profit, annualised Sharpe,
     profit/max-drawdown) at the production threshold (|edge| >= 0.10, both sides).
  2. Sweeps (model_family x edge_threshold x side x price_band) per city and finds
     the best combo for each individual metric and by composite rank (avg of the
     three metric ranks) -- the user's chosen objective.
  3. Walk-forward check: pick best params on the first 70% of each city's
     timeline, measure them on the held-out last 30%, to expose overfitting.

Sizing convention: 1 contract per signal (equal-contract). PnL in cents. Sharpe
is computed on the daily PnL series (days with >=1 trade) and annualised by
sqrt(trading-days-per-year) estimated from each strategy's own trade frequency.

Run:  cd /home/tdunn/weather-project && uv run python scripts/analysis/diagnostic_city_params.py
Writes full results to /tmp/diag.json and prints a compact summary.
"""
from __future__ import annotations
import csv, math, json
from collections import defaultdict
from statistics import mean, stdev
from datetime import date

CSV_PATH = "/tmp/pt_dataset.csv"
OUT_JSON = "/tmp/diag.json"

# series prefix -> (city label, is_low_market)
SERIES_CITY = {
    "KXHIGHNY":   ("New York", False),
    "HIGHNY":     ("New York", False),     # legacy ticker format, same station (KNYC)
    "KXHIGHCHI":  ("Chicago", False),
    "KXHIGHLAX":  ("Los Angeles", False),
    "KXHIGHDEN":  ("Denver", False),
    "KXHIGHMIA":  ("Miami", False),
    "KXHIGHAUS":  ("Austin", False),
    "KXHIGHTNOLA":("New Orleans", False),
    "KXHIGHTSEA": ("Seattle", False),
    "KXHIGHTDAL": ("Dallas", False),
    "KXHIGHTLV":  ("Las Vegas", False),
    "KXHIGHTPHX": ("Phoenix", False),
    "KXHIGHTSFO": ("San Francisco", False),   # new paper candidate (2026-07-29)
    # KXLOWTNYC intentionally EXCLUDED: it settles on the daily LOW temperature,
    # but this dataset settles every contract against the daily HIGH. Including it
    # produces a spurious "edge" (settlement mismatch). Out of scope for the
    # high-temp city strategy; would need low_temp_f settlement to evaluate.
}

THRESHOLDS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]
SIDES = ["both", "yes", "no"]
PRICE_BANDS = [("all", 1, 100), ("p3_97", 3, 97), ("p10_90", 10, 90)]


def family(ms: str) -> str:
    s = ms.lower()
    if "gefs" in s: return "GEFS"
    if "ecmwf" in s: return "ECMWF"
    if "hrrr" in s: return "combined+HRRR"
    if "equal-weight" in s or "equal_weight" in s: return "combined-EW"
    if "combined" in s: return "combined"
    return "other"


def load():
    rows = []
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            series = r["series"]
            if series not in SERIES_CITY:
                continue
            city, is_low = SERIES_CITY[series]
            rows.append({
                "date": r["target_date"],
                "city": city,
                "is_low": is_low,
                "fam": family(r["model_source"]),
                "pos": r["position"],          # BUY_YES / BUY_NO
                "entry": int(r["entry"]),
                "abs_edge": abs(float(r["edge"])),
                "net": int(r["net_cents"]),
                "won": r["won"] == "t",
            })
    return rows


def metrics(trades):
    """trades: list of dicts with date, net, entry. Returns metric dict or None."""
    if not trades:
        return None
    daily = defaultdict(int)
    for t in trades:
        daily[t["date"]] += t["net"]
    dates = sorted(daily)
    pnls = [daily[d] for d in dates]
    n_trades = len(trades)
    n_days = len(dates)
    profit = sum(pnls)
    # equity curve + max drawdown (cents)
    eq = peak = maxdd = 0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    # annualised Sharpe on daily PnL
    sharpe_ann = None
    if n_days >= 3:
        sd = stdev(pnls)
        if sd > 0:
            span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
            years = span / 365.25 if span > 0 else 0
            ppy = (n_days / years) if years > 0 else 0
            if ppy > 0:
                sharpe_ann = (mean(pnls) / sd) * math.sqrt(ppy)
    wins = sum(1 for t in trades if t["net"] > 0)
    pdd = (profit / maxdd) if maxdd > 0 else (float("inf") if profit > 0 else 0.0)
    return {
        "n_trades": n_trades, "n_days": n_days,
        "profit": profit, "maxdd": maxdd,
        "sharpe_ann": sharpe_ann,
        "profit_to_dd": pdd,
        "winrate": wins / n_trades,
        "roi_per_trade": profit / n_trades,
        "mean_stake": mean(t["entry"] for t in trades),
    }


def select(rows, fam=None, thr=0.0, side="both", band=(1, 100)):
    lo, hi = band[0], band[1]
    out = []
    for r in rows:
        if fam is not None and r["fam"] != fam: continue
        if r["abs_edge"] < thr: continue
        if side == "yes" and r["pos"] != "BUY_YES": continue
        if side == "no" and r["pos"] != "BUY_NO": continue
        if not (lo <= r["entry"] <= hi): continue
        out.append(r)
    return out


def families_for(rows):
    c = defaultdict(int)
    for r in rows: c[r["fam"]] += 1
    # keep families with enough rows to matter
    return sorted([f for f, n in c.items() if n >= 40 and f != "other"],
                  key=lambda f: -c[f])


def sweep(rows, min_n, min_days):
    """Return list of (params, metrics) for all valid combos."""
    fams = families_for(rows)
    results = []
    for fam in fams:
        for thr in THRESHOLDS:
            for side in SIDES:
                for band in PRICE_BANDS:
                    sub = select(rows, fam, thr, side, (band[1], band[2]))
                    m = metrics(sub)
                    if m is None: continue
                    if m["n_trades"] < min_n or m["n_days"] < min_days: continue
                    params = {"family": fam, "threshold": thr, "side": side, "band": band[0]}
                    results.append((params, m))
    return results


def composite_best(results):
    """Rank by profit, sharpe, profit/dd; pick min average rank."""
    if not results:
        return None
    def srt(key, transform=lambda x: x):
        order = sorted(range(len(results)),
                       key=lambda i: transform(results[i][1][key]),
                       reverse=True)
        rank = [0] * len(results)
        for pos, i in enumerate(order):
            rank[i] = pos
        return rank
    r_profit = srt("profit")
    r_sharpe = srt("sharpe_ann", lambda v: (-1e9 if v is None else v))
    r_pdd = srt("profit_to_dd", lambda v: (1e9 if v == float("inf") else v))
    avg = [(r_profit[i] + r_sharpe[i] + r_pdd[i]) / 3 for i in range(len(results))]
    best_i = min(range(len(results)), key=lambda i: (avg[i], -results[i][1]["profit"]))
    return results[best_i], avg[best_i]


def best_by(results, key, transform):
    cands = [(p, m) for p, m in results if m[key] is not None]
    if not cands: return None
    return max(cands, key=lambda pm: transform(pm[1][key]))


def fmt_money(c):  # cents -> $ string
    return f"${c/100:,.2f}"


def main():
    rows = load()
    cities = []
    seen = []
    for _, (city, _l) in SERIES_CITY.items():
        if city not in seen:
            seen.append(city)
    cities = seen

    report = {"cities": {}, "portfolio": {}}

    # ---------- Baseline (production-ish): threshold 0.10, both sides, all prices,
    # using the single most-traded family per city ----------
    print("=" * 78)
    print("BASELINE  (|edge|>=0.10, both sides, all prices, dominant model family)")
    print("=" * 78)
    print(f"{'City':<16}{'fam':<14}{'n':>5}{'days':>5}{'profit':>11}{'maxDD':>10}"
          f"{'P/DD':>7}{'Shrp':>7}{'win%':>6}")
    port = []
    for city in cities:
        crows = [r for r in rows if r["city"] == city]
        fams = families_for(crows)
        if not fams:
            continue
        fam = fams[0]
        sub = select(crows, fam, 0.10, "both", (1, 100))
        m = metrics(sub)
        if m is None:
            continue
        port.extend(sub)
        report["cities"].setdefault(city, {})["baseline"] = {"family": fam, **m}
        pdd = "inf" if m["profit_to_dd"] == float("inf") else f"{m['profit_to_dd']:.2f}"
        shp = "n/a" if m["sharpe_ann"] is None else f"{m['sharpe_ann']:.2f}"
        print(f"{city:<16}{fam:<14}{m['n_trades']:>5}{m['n_days']:>5}"
              f"{fmt_money(m['profit']):>11}{fmt_money(m['maxdd']):>10}"
              f"{pdd:>7}{shp:>7}{m['winrate']*100:>5.0f}%")
    pm = metrics(port)
    report["portfolio"]["baseline_all"] = pm
    print("-" * 78)
    pdd = "inf" if pm["profit_to_dd"] == float("inf") else f"{pm['profit_to_dd']:.2f}"
    shp = "n/a" if pm["sharpe_ann"] is None else f"{pm['sharpe_ann']:.2f}"
    print(f"{'PORTFOLIO(all)':<16}{'':<14}{pm['n_trades']:>5}{pm['n_days']:>5}"
          f"{fmt_money(pm['profit']):>11}{fmt_money(pm['maxdd']):>10}"
          f"{pdd:>7}{shp:>7}{pm['winrate']*100:>5.0f}%")

    # Robust subset: only cities whose baseline profit is positive, traded at baseline.
    robust_cities = [c for c in cities
                     if report["cities"].get(c, {}).get("baseline", {}).get("profit", 0) > 0]
    rport = []
    for city in robust_cities:
        crows = [r for r in rows if r["city"] == city]
        fam = report["cities"][city]["baseline"]["family"]
        rport.extend(select(crows, fam, 0.10, "both", (1, 100)))
    rpm = metrics(rport)
    report["portfolio"]["baseline_robust"] = rpm
    report["portfolio"]["robust_cities"] = robust_cities
    pdd = "inf" if rpm["profit_to_dd"] == float("inf") else f"{rpm['profit_to_dd']:.2f}"
    shp = "n/a" if rpm["sharpe_ann"] is None else f"{rpm['sharpe_ann']:.2f}"
    print(f"{'PORTFOLIO(+ve)':<16}{('|'.join(c[:3] for c in robust_cities)):<14}"
          f"{rpm['n_trades']:>5}{rpm['n_days']:>5}"
          f"{fmt_money(rpm['profit']):>11}{fmt_money(rpm['maxdd']):>10}"
          f"{pdd:>7}{shp:>7}{rpm['winrate']*100:>5.0f}%")

    # ---------- Baseline stability: first half vs second half ----------
    print("\n" + "=" * 78)
    print("BASELINE STABILITY  (dominant family, T=0.10, both, all; split by date)")
    print("=" * 78)
    print(f"{'City':<16}{'H1 prof':>9}{'H1 n':>6}{'H2 prof':>9}{'H2 n':>6}  verdict")
    for city in cities:
        crows = sorted([r for r in rows if r["city"] == city], key=lambda r: r["date"])
        bl = report["cities"].get(city, {}).get("baseline")
        if not bl:
            continue
        fam = bl["family"]
        dts = sorted({r["date"] for r in crows})
        mid = dts[len(dts) // 2]
        h1 = select([r for r in crows if r["date"] < mid], fam, 0.10, "both", (1, 100))
        h2 = select([r for r in crows if r["date"] >= mid], fam, 0.10, "both", (1, 100))
        m1, m2 = metrics(h1), metrics(h2)
        p1 = m1["profit"] if m1 else 0
        p2 = m2["profit"] if m2 else 0
        n1 = m1["n_trades"] if m1 else 0
        n2 = m2["n_trades"] if m2 else 0
        verdict = "STABLE+" if (p1 > 0 and p2 > 0) else ("STABLE-" if (p1 < 0 and p2 < 0) else "FLIP")
        report["cities"][city]["stability"] = {"h1_profit": p1, "h2_profit": p2,
                                                "h1_n": n1, "h2_n": n2, "verdict": verdict}
        print(f"{city:<16}{fmt_money(p1):>9}{n1:>6}{fmt_money(p2):>9}{n2:>6}  {verdict}")

    # ---------- Best per metric + composite (in-sample, full history) ----------
    print("\n" + "=" * 78)
    print("IN-SAMPLE BEST PARAMS PER CITY (full history)")
    print("=" * 78)
    for city in cities:
        crows = [r for r in rows if r["city"] == city]
        n_city = len(crows)
        # adaptive min-n: stricter for data-rich cities
        min_n, min_days = (40, 20) if n_city >= 1500 else (20, 10)
        res = sweep(crows, min_n, min_days)
        relaxed = False
        if not res:
            res = sweep(crows, 12, 6)
            relaxed = True
        if not res:
            print(f"\n{city}: insufficient data for sweep (n_rows={n_city})")
            continue
        bp = best_by(res, "profit", lambda v: v)
        bs = best_by(res, "sharpe_ann", lambda v: v)
        bd = best_by(res, "profit_to_dd", lambda v: (1e9 if v == float("inf") else v))
        comp, comp_rank = composite_best(res)
        cinfo = report["cities"].setdefault(city, {})
        cinfo["n_rows"] = n_city
        cinfo["min_n"] = min_n
        cinfo["relaxed"] = relaxed
        cinfo["best_profit"] = {"params": bp[0], **bp[1]}
        cinfo["best_sharpe"] = {"params": bs[0], **bs[1]}
        cinfo["best_pdd"] = {"params": bd[0], **bd[1]}
        cinfo["composite"] = {"params": comp[0], **comp[1]}

        def line(tag, pm):
            p, m = pm
            pdd = "inf" if m["profit_to_dd"] == float("inf") else f"{m['profit_to_dd']:.2f}"
            shp = "n/a" if m["sharpe_ann"] is None else f"{m['sharpe_ann']:.2f}"
            return (f"  {tag:<11}{p['family']:<14}T={p['threshold']:<5}{p['side']:<5}"
                    f"{p['band']:<7}n={m['n_trades']:<4}{fmt_money(m['profit']):>10}"
                    f"  P/DD={pdd:<6} Shrp={shp:<6} win={m['winrate']*100:.0f}%")
        flag = "  [RELAXED min-n: thin data]" if relaxed else ""
        print(f"\n{city}  (n_rows={n_city}){flag}")
        print(line("maxProfit", bp))
        print(line("maxSharpe", bs))
        print(line("maxP/DD", bd))
        print(line("COMPOSITE", comp))

    # ---------- Walk-forward (70/30 chronological) ----------
    print("\n" + "=" * 78)
    print("WALK-FORWARD: pick params on first 70%, measure on last 30%")
    print("=" * 78)
    print(f"{'City':<16}{'train params':<34}{'IS prof':>9}{'OOS prof':>9}"
          f"{'OOS n':>6}{'OOS P/trd':>10}{'OOS Shrp':>9}")
    for city in cities:
        crows = sorted([r for r in rows if r["city"] == city], key=lambda r: r["date"])
        if len(crows) < 60:
            continue
        dts = sorted({r["date"] for r in crows})
        split = dts[int(len(dts) * 0.70)]
        train = [r for r in crows if r["date"] < split]
        test = [r for r in crows if r["date"] >= split]
        if len(train) < 40 or len(test) < 15:
            continue
        tres = sweep(train, 20, 8) or sweep(train, 10, 5)
        if not tres:
            continue
        comp, _ = composite_best(tres)
        p = comp[0]
        band = next(b for b in PRICE_BANDS if b[0] == p["band"])
        test_sub = select(test, p["family"], p["threshold"], p["side"], (band[1], band[2]))
        tm = metrics(test_sub)
        cinfo = report["cities"].setdefault(city, {})
        cinfo["walk_forward"] = {
            "train_params": p,
            "is_profit": comp[1]["profit"],
            "oos": tm,
        }
        if tm is None:
            oos_prof = "n/a"; oos_n = 0; oos_roi = "n/a"; oos_shp = "n/a"
        else:
            oos_prof = fmt_money(tm["profit"]); oos_n = tm["n_trades"]
            oos_roi = f"{tm['roi_per_trade']:.2f}c"
            oos_shp = "n/a" if tm["sharpe_ann"] is None else f"{tm['sharpe_ann']:.2f}"
        pstr = f"{p['family']},T={p['threshold']},{p['side']},{p['band']}"
        print(f"{city:<16}{pstr:<34}{fmt_money(comp[1]['profit']):>9}{oos_prof:>9}"
              f"{oos_n:>6}{oos_roi:>10}{oos_shp:>9}")

    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=lambda o: None if o == float("inf") else o)
    print(f"\nFull results -> {OUT_JSON}")


if __name__ == "__main__":
    main()
