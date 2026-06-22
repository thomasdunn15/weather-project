"""P4 — Model-weighted combined_hrrr backtest (KORD, KMIA).

READ-ONLY analysis. Does NOT modify production / EMOS / blend / trading code.

Question: does equal-MODEL-weighting (HRRR at 1/3, not ~1/82) of combined_hrrr
convert its forecast-skill gain into tradeable, out-of-sample edge vs the
production flat-member combined_hrrr baseline?

Method (full per-day bracket grid — the model picks its OWN trades):
  1. For each city, compute the rolling-45d EMOS Gaussian (mu, sigma) per target
     day for combined_hrrr under BOTH weightings ("model" and "member"=flat),
     straight from the forecast_model_skill harness (rolling_emos_predictions on
     a series assembled per weighting). Restricted to days with all 3 models
     (gefs+ifs+hrrr) present so model vs flat are apples-to-apples.
  2. Rebuild the full bracket grid per day: every listed contract, its
     decision-time market price (DISTINCT ON snapshot <= cron cutoff, exactly as
     live_trade/data_backtest do), and its realized YES/NO outcome.
  3. modelP = gaussian_to_bracket_probs(mu, sigma, contracts) per bracket and
     weighting. ALSO a walk-forward Benter blend (logit blend of modelP + mktP,
     refit every 7d on data strictly before the target day — no lookahead),
     fit separately for model- and flat-weighting.
  4. Strategy = fire on EVERY bracket with |edge| >= threshold (production rule),
     side BUY_YES if edge>0 else BUY_NO; entry = cross (ask / 100-bid). P&L net
     of Kalshi fees via dashboard.sim_python.simulate_pnl (authoritative sim),
     under three execution modes:
        cross      -> cross_at_ask   (~99% fill; taker)            [realistic]
        limit_70   -> post_inside_spread (~70% fill; maker)        [realistic]
        limit_100  -> inside spread, 100% fill                     [optimistic upper bound]
  5. Sweep strategy(raw/blend) x weighting(model/flat) x edge-threshold x side x
     price-band. Rank by a robust composite (mean rank of profit, Sharpe, P/DD).
  6. Robustness: in-sample best, split-half (H1 vs H2), walk-forward (pick params
     on first 70% by composite, measure last 30% OOS). Deploy bar = OOS Sharpe
     > 2.5 on the STRICTER of the two realistic exec modes.

Sizing: unit = 500 contracts (Sharpe / composite are sizing-invariant for
unit/scaling; profit & DD scale together). Run:
  uv run python scripts/analysis/backtest_mw.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))                          # dashboard.*
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))  # forecast_model_skill

import forecast_model_skill as fms                      # noqa: E402
from weather_markets.db import get_connection           # noqa: E402
from weather_markets.emos import gaussian_to_bracket_probs  # noqa: E402
from weather_markets.evaluation import contract_resolved_yes  # noqa: E402
from weather_markets.stations import get as get_station  # noqa: E402
from weather_markets.blend import _fit_logistic, BlendFit, MIN_N_FIT  # noqa: E402
from dashboard.sim_python import simulate_pnl           # noqa: E402

# ----------------------------------------------------------------------------
MODELS = ("gefs", "ifs", "hrrr")          # combined_hrrr
CITIES = {
    "KORD": {"decision": (14, 46), "series": "KXHIGHCHI", "name": "Chicago"},
    "KMIA": {"decision": (15, 30), "series": "KXHIGHMIA", "name": "Miami"},
}
THRESHOLDS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]
SIDES = ["both", "yes", "no"]
BANDS = [("all", 1, 99), ("p3_97", 3, 97), ("p10_90", 10, 90)]
# variant = (strategy, weighting); prob column chosen per variant
VARIANTS = [
    ("raw", "model"), ("blend", "model"),     # model-weighted
    ("raw", "flat"), ("blend", "flat"),       # flat-member baseline
]
EXEC_REALISTIC = ["limit_70", "cross"]   # post_inside_spread(~70%), cross_at_ask(~99%)
EXEC_OPTIMISTIC = "limit_100"
EXEC_ALL = ["limit_70", "cross", "limit_100"]
EXEC_LABEL = {"limit_70": "post_inside_spread~70%", "cross": "cross_at_ask~99%",
              "limit_100": "inside_spread_100%(optim)"}
SEL_EXEC = "limit_70"        # exec mode used to SELECT params (stricter realistic fill)
UNIT_CONTRACTS = 500
START_BAL = 3050.0


# ----------------------------- mu/sigma ------------------------------------
def build_mu_sigma(conn, station_id, tz):
    """{weighting: {date: (mu, sigma)}} for combined_hrrr, both weightings.

    Reuses the harness: fetch_member_highs + rolling_emos_predictions. The
    per-weighting member assembly mirrors forecast_model_skill exactly
    ("model" -> per-model mean so HRRR=1/3; "member" -> flat pooled members).
    Only days with all 3 models present are used (so model vs flat compare on
    the identical day set).
    """
    obs = fms.fetch_obs(conn, station_id)
    mh = {m: fms.fetch_member_highs(conn, station_id, m, tz) for m in MODELS}
    common = set(obs)
    for m in MODELS:
        common &= set(mh[m])
    dates = sorted(common)

    out = {}
    for weighting in ("model", "member"):
        series = []
        for d in dates:
            member_lists = [list(mh[m][d].values()) for m in MODELS]
            if any(len(ml) == 0 for ml in member_lists):
                continue
            if weighting == "model":
                members = [statistics.mean(ml) for ml in member_lists]
            else:
                members = [v for ml in member_lists for v in ml]
            mean, std = fms.mean_std(members)
            series.append((d, mean, std, obs[d]))
        out[weighting] = {d: (mu, sigma) for d, mu, sigma, _ in fms.rolling_emos_predictions(series)}
    return out


# ------------------------------- grid --------------------------------------
def decision_cutoff(d, hm):
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=timezone.utc)


def build_grid(conn, city, cfg, musig):
    """Full per-day bracket grid. One row per (date, bracket) where: both
    weightings have a mu/sigma, the bracket has a decision-time price, and the
    day is settled (observed high known)."""
    station_id = city
    obs = fms.fetch_obs(conn, station_id)
    contracts_by_date = fms.load_contracts_by_date(conn, station_id, cfg["series"])

    mods = musig["model"]
    flat = musig["member"]
    dates = sorted(set(mods) & set(flat) & set(contracts_by_date) & set(obs))

    rows = []
    with conn.cursor() as cur:
        for d in dates:
            contracts = contracts_by_date[d]
            tickers = [c["ticker"] for c in contracts]
            cutoff = decision_cutoff(d, cfg["decision"])
            cur.execute(
                """SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                   FROM prices WHERE ticker = ANY(%s) AND snapshot_at <= %s
                     AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL
                   ORDER BY ticker, snapshot_at DESC""",
                (tickers, cutoff),
            )
            px = {t: (int(b), int(a)) for t, b, a in cur.fetchall()}
            mu_m, sg_m = mods[d]
            mu_f, sg_f = flat[d]
            p_model = gaussian_to_bracket_probs(mu_m, sg_m, contracts)
            p_flat = gaussian_to_bracket_probs(mu_f, sg_f, contracts)
            obs_high = int(round(obs[d]))
            for c in contracts:
                tk = c["ticker"]
                if tk not in px:
                    continue
                yb, ya = px[tk]
                mid = (yb + ya) / 200.0
                yes_won = 1 if contract_resolved_yes(obs_high, c) else 0
                rows.append({
                    "date": d, "ticker": tk,
                    "bracket_type": c["bracket_type"],
                    "strike_low": c["strike_low"], "strike_high": c["strike_high"],
                    "yes_bid": yb, "yes_ask": ya, "mid": mid, "yes_won": yes_won,
                    "p_model": float(p_model[tk]), "p_flat": float(p_flat[tk]),
                })
    return rows


# --------------------------- walk-forward blend ----------------------------
def walk_forward_blends(rows, prob_key, refit_every_days=7):
    """Replicates blend.walkforward_blends on the full grid using the SAME
    _fit_logistic primitive. Trains on (prob_key, mid, yes_won) for all priced
    grid brackets STRICTLY before each target date. {date: BlendFit|None}."""
    data = sorted((r["date"], r[prob_key], r["mid"], float(r["yes_won"])) for r in rows)
    unique_dates = sorted({r[0] for r in data})
    out, cur_fit, last_refit = {}, None, None
    for d in unique_dates:
        if last_refit is None or (d - last_refit).days >= refit_every_days:
            train = [(mp, mk, y) for (td, mp, mk, y) in data if td < d]
            if len(train) >= MIN_N_FIT:
                a = np.array(train, dtype=float)
                alpha, bm, bk = _fit_logistic(a[:, 0], a[:, 1], a[:, 2])
                cur_fit = BlendFit("x", alpha, bm, bk, len(train), str(d))
                last_refit = d
        out[d] = cur_fit
    return out


def attach_probs(rows):
    """Add blend_model / blend_flat columns (None until a fit exists)."""
    wf_model = walk_forward_blends(rows, "p_model")
    wf_flat = walk_forward_blends(rows, "p_flat")
    for r in rows:
        fm = wf_model.get(r["date"])
        ff = wf_flat.get(r["date"])
        r["blend_model"] = float(fm.predict(r["p_model"], r["mid"])) if fm else None
        r["blend_flat"] = float(ff.predict(r["p_flat"], r["mid"])) if ff else None
    return rows


PROB_COL = {("raw", "model"): "p_model", ("raw", "flat"): "p_flat",
            ("blend", "model"): "blend_model", ("blend", "flat"): "blend_flat"}


# ----------------------------- selection -----------------------------------
def select_trades(rows, variant, threshold, side, band):
    """Fire on every bracket with |edge|>=threshold within side/band filters.
    Returns sim-ready row dicts for simulate_pnl."""
    col = PROB_COL[variant]
    _, lo, hi = band
    out = []
    for r in rows:
        p = r[col]
        if p is None:
            continue
        edge = p - r["mid"]
        if abs(edge) < threshold:
            continue
        if edge > 0:
            if side == "no":
                continue
            position, cross = "BUY_YES", r["yes_ask"]
            won = bool(r["yes_won"])
        else:
            if side == "yes":
                continue
            position, cross = "BUY_NO", 100 - r["yes_bid"]
            won = not bool(r["yes_won"])
        if cross < lo or cross > hi:
            continue
        out.append({
            "target_date": r["date"], "logged_at": r["date"], "ticker": r["ticker"],
            "position": position, "entry_price_cents": int(cross),
            "market_yes_bid": r["yes_bid"], "market_yes_ask": r["yes_ask"],
            "bracket_type": r["bracket_type"],
            "strike_low": r["strike_low"], "strike_high": r["strike_high"],
            "model_prob_yes": p, "edge": edge, "won": won,
        })
    return out


def run_sim(sim_rows, exec_mode):
    if not sim_rows:
        return None
    df = pd.DataFrame(sim_rows)
    return simulate_pnl(df, START_BAL, "unit", contracts=UNIT_CONTRACTS,
                        execution_mode=exec_mode)


def metrics(sim_df):
    """Robust metrics from the sim history (mirrors diagnostic_city_params:
    daily-aggregated annualized Sharpe, absolute max-DD, P/DD)."""
    if sim_df is None or len(sim_df) <= 1:
        return None
    h = sim_df.iloc[1:].copy()
    filled = h[h["filled"] == True]  # noqa: E712
    n = int(len(filled))
    if n == 0:
        return None
    profit = float(h["trade_pnl"].sum())
    n_won = int(filled["won"].sum())
    hit = n_won / n
    # daily aggregation
    h["d"] = pd.to_datetime(h["date"]).dt.date
    daily = h.groupby("d")["trade_pnl"].sum().sort_index()
    pnls = list(daily.values)
    days = list(daily.index)
    # max drawdown (absolute $, on cumulative daily equity)
    eq = peak = maxdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    # annualized Sharpe on daily P&L
    sharpe = None
    if len(pnls) >= 3 and statistics.pstdev(pnls) > 0:
        sd = statistics.stdev(pnls)
        if sd > 0:
            span = (days[-1] - days[0]).days
            years = span / 365.25 if span > 0 else 0
            ppy = (len(pnls) / years) if years > 0 else 0
            sharpe = (statistics.mean(pnls) / sd) * math.sqrt(ppy) if ppy > 0 else None
    pdd = (profit / maxdd) if maxdd > 0 else (float("inf") if profit > 0 else 0.0)
    return {"profit": profit, "n": n, "n_days": len(pnls), "hit": hit,
            "sharpe": sharpe, "maxdd": maxdd, "pdd": pdd,
            "expectancy": profit / n}


# ------------------------------- sweep -------------------------------------
def sweep(rows, variant, exec_mode, min_n, min_days):
    results = []
    for thr in THRESHOLDS:
        for side in SIDES:
            for band in BANDS:
                sim_rows = select_trades(rows, variant, thr, side, band)
                if len(sim_rows) < min_n:
                    continue
                m = metrics(run_sim(sim_rows, exec_mode))
                if m is None or m["n"] < min_n or m["n_days"] < min_days:
                    continue
                params = {"variant": f"{variant[0]}-{variant[1]}", "strategy": variant[0],
                          "weighting": variant[1], "threshold": thr, "side": side,
                          "band": band[0], "band_lo": band[1], "band_hi": band[2]}
                results.append((params, m))
    return results


def composite_best(results):
    """Mean-rank of (profit desc, sharpe desc, pdd desc); lowest mean wins,
    profit tiebreak. Mirrors diagnostic_city_params.composite_best."""
    if not results:
        return None
    def ranks(key, tf):
        order = sorted(range(len(results)), key=lambda i: tf(results[i][1][key]), reverse=True)
        rk = [0] * len(results)
        for pos, i in enumerate(order):
            rk[i] = pos
        return rk
    rp = ranks("profit", lambda v: v)
    rs = ranks("sharpe", lambda v: (-1e9 if v is None else v))
    rd = ranks("pdd", lambda v: (1e9 if v == float("inf") else v))
    avg = [(rp[i] + rs[i] + rd[i]) / 3 for i in range(len(results))]
    best = min(range(len(results)), key=lambda i: (avg[i], -results[i][1]["profit"]))
    return results[best]


def metrics_for_params(rows, params, exec_mode):
    variant = (params["strategy"], params["weighting"])
    band = (params["band"], params["band_lo"], params["band_hi"])
    sim_rows = select_trades(rows, variant, params["threshold"], params["side"], band)
    return metrics(run_sim(sim_rows, exec_mode)), sim_rows


# ----------------------------- robustness ----------------------------------
def split_half(rows, params):
    dts = sorted({r["date"] for r in rows})
    if len(dts) < 4:
        return None
    mid = dts[len(dts) // 2]
    out = {}
    for half, sub in (("h1", [r for r in rows if r["date"] < mid]),
                      ("h2", [r for r in rows if r["date"] >= mid])):
        hm = {}
        for ex in EXEC_REALISTIC:
            m, _ = metrics_for_params(sub, params, ex)
            hm[ex] = m
        out[half] = hm
    return {"split_date": str(mid), **out}


def walk_forward(rows, variant, min_n, min_days):
    """Pick params on first 70% of DATES (composite, SEL_EXEC), measure last 30%."""
    dts = sorted({r["date"] for r in rows})
    if len(dts) < 10:
        return None
    split = dts[int(len(dts) * 0.70)]
    train = [r for r in rows if r["date"] < split]
    test = [r for r in rows if r["date"] >= split]
    tres = sweep(train, variant, SEL_EXEC, max(10, min_n // 2), max(5, min_days // 2))
    if not tres:
        tres = sweep(train, variant, SEL_EXEC, 8, 4)
    best = composite_best(tres)
    if not best:
        return None
    params, is_m = best
    oos = {}
    for ex in EXEC_REALISTIC + [EXEC_OPTIMISTIC]:
        m, _ = metrics_for_params(test, params, ex)
        oos[ex] = m
    return {"split_date": str(split), "train_params": params,
            "is_profit": is_m["profit"], "is_sharpe": is_m["sharpe"],
            "n_train_dates": len(train), "n_test_dates": len(test), "oos": oos}


# -------------------------------- main -------------------------------------
def jround(x, n=3):
    if x is None:
        return None
    if x == float("inf"):
        return "inf"
    return round(float(x), n)


def m_compact(m):
    if m is None:
        return None
    return {k: jround(m[k]) for k in ("profit", "n", "n_days", "hit", "sharpe", "maxdd", "pdd", "expectancy")}


def main():
    out_all = {}
    for city, cfg in CITIES.items():
        print(f"\n{'='*78}\n{city} ({cfg['name']}) — combined_hrrr model-weighted vs flat\n{'='*78}")
        with get_connection() as conn:
            st = get_station(city)
            musig = build_mu_sigma(conn, city, st.timezone)
            rows = build_grid(conn, city, cfg, musig)
        attach_probs(rows)
        dts = sorted({r["date"] for r in rows})
        print(f"grid rows={len(rows)}  trading-days={len(dts)}  "
              f"range={dts[0]}..{dts[-1]}" if dts else "NO GRID ROWS")
        if not dts:
            out_all[city] = {"error": "no grid rows"}
            continue
        n_city = len(rows)
        min_n = 30 if n_city >= 1500 else 20
        min_days = 15 if n_city >= 1500 else 10

        city_out = {"grid_rows": n_city, "trading_days": len(dts),
                    "range": [str(dts[0]), str(dts[-1])], "variants": {}}

        for variant in VARIANTS:
            vkey = f"{variant[0]}-{variant[1]}"
            res = sweep(rows, variant, SEL_EXEC, min_n, min_days)
            if not res:
                # relax for thin data (KMIA)
                res = sweep(rows, variant, SEL_EXEC, 12, 6)
            best = composite_best(res)
            if not best:
                city_out["variants"][vkey] = {"error": "no config met min-n"}
                print(f"\n  [{vkey}] no config met min-n")
                continue
            params, _ = best
            # in-sample metrics across all exec modes
            is_metrics = {}
            for ex in EXEC_ALL:
                m, _ = metrics_for_params(rows, params, ex)
                is_metrics[ex] = m
            sh = split_half(rows, params)
            wf = walk_forward(rows, variant, min_n, min_days)
            city_out["variants"][vkey] = {
                "best_params": params,
                "in_sample": {ex: m_compact(is_metrics[ex]) for ex in EXEC_ALL},
                "split_half": ({"split_date": sh["split_date"],
                                "h1": {ex: m_compact(sh["h1"][ex]) for ex in EXEC_REALISTIC},
                                "h2": {ex: m_compact(sh["h2"][ex]) for ex in EXEC_REALISTIC}} if sh else None),
                "walk_forward": ({"split_date": wf["split_date"], "train_params": wf["train_params"],
                                  "is_profit": jround(wf["is_profit"]), "is_sharpe": jround(wf["is_sharpe"]),
                                  "n_train_dates": wf["n_train_dates"], "n_test_dates": wf["n_test_dates"],
                                  "oos": {ex: m_compact(wf["oos"][ex]) for ex in EXEC_REALISTIC + [EXEC_OPTIMISTIC]}} if wf else None),
            }
            # console summary
            p = params
            print(f"\n  [{vkey}] BEST: edge={p['threshold']:.2f} side={p['side']} band={p['band']}")
            for ex in EXEC_REALISTIC:
                m = is_metrics[ex]
                if m:
                    print(f"      IS  {EXEC_LABEL[ex]:<26} profit=${m['profit']:>9.0f} n={m['n']:<4} "
                          f"hit={m['hit']:.2f} Sharpe={('%.2f'%m['sharpe']) if m['sharpe'] is not None else 'NA':>6} "
                          f"maxDD=${m['maxdd']:>8.0f} P/DD={('%.2f'%m['pdd']) if m['pdd']!=float('inf') else 'inf'}")
            if wf and wf["oos"]:
                for ex in EXEC_REALISTIC:
                    m = wf["oos"][ex]
                    if m:
                        sval = ('%.2f'%m['sharpe']) if m['sharpe'] is not None else 'NA'
                        print(f"      OOS {EXEC_LABEL[ex]:<26} profit=${m['profit']:>9.0f} n={m['n']:<4} "
                              f"hit={m['hit']:.2f} Sharpe={sval:>6}  (train pick: edge={wf['train_params']['threshold']:.2f} "
                              f"{wf['train_params']['side']}/{wf['train_params']['band']})")
        out_all[city] = city_out

    Path("/tmp/bt_mw_results.json").write_text(json.dumps(out_all, indent=2, default=str))
    print(f"\n\nJSON -> /tmp/bt_mw_results.json")
    # ----- deploy-gate summary (stricter realistic OOS Sharpe vs 2.5) -----
    print(f"\n{'='*78}\nDEPLOY GATE (OOS Sharpe > 2.5 on STRICTER realistic exec)\n{'='*78}")
    for city in CITIES:
        co = out_all.get(city, {})
        for vlab, vkey in (("MODEL-WEIGHTED (best of raw/blend-mw)", "model"),
                           ("FLAT BASELINE  (best of raw/blend-flat)", "flat")):
            # choose the better OOS-stricter-Sharpe variant within this weighting
            cands = []
            for strat in ("raw", "blend"):
                v = co.get("variants", {}).get(f"{strat}-{vkey}")
                if not v or not v.get("walk_forward") or not v["walk_forward"].get("oos"):
                    continue
                oos = v["walk_forward"]["oos"]
                shs = [oos[ex]["sharpe"] for ex in EXEC_REALISTIC
                       if oos.get(ex) and oos[ex]["sharpe"] is not None]
                if not shs:
                    continue
                cands.append((min(shs), f"{strat}-{vkey}", v))
            if not cands:
                print(f"  {city} {vlab}: no OOS result")
                continue
            strict, name, v = max(cands, key=lambda t: t[0])
            verdict = "PASS" if strict is not None and strict > 2.5 else "FAIL"
            print(f"  {city:5} {vlab:42} {name:11} OOS stricter Sharpe={strict:6.2f}  ->  {verdict}")


if __name__ == "__main__":
    main()
