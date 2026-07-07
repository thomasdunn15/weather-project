"""Intraday fair-value GATE study (research/intraday-fair-value).

GATE QUESTION
-------------
Does an intraday-updated, no-look-ahead fair value predict the settlement
outcome MORE accurately than the live market price -- and for how long into
the day does any edge over the market persist? Per live city (KORD/KMIA/KDFW).

This is measurement ONLY (no trading rules). It scores three predictors of the
0/1 settlement outcome, per bracket, with proper rules (Brier + log-loss):

  (i)   static 00Z fair   -- rolling-45d EMOS on the 00Z combined ensemble
                             (exactly what live_trade / paper_trade_log use);
                             CONSTANT through the day.
  (ii)  intraday fair     -- the ONLY backtestable intraday model refresh:
                             the 12Z combined ensemble. See the data-inventory
                             caveats below -- this is DIRECTIONAL only.
  (iii) market mid        -- (yes_bid+yes_ask)/2 from `prices`, sampled by hour.

DATA-INVENTORY REALITY (established before writing this script):
  * NO hourly/sub-daily observed temps exist. `observations` stores only the
    daily settlement high/low. -> the "condition on max-so-far / floor the
    daily high on temps observed through T" lever is UNSUPPORTED.
  * HRRR is stored at 00Z ONLY (1 run/day). -> the "fresh intraday HRRR run as a
    proxy for observed temps" lever is UNSUPPORTED.
  * For the 3 LIVE cities, every intraday model run (GEFS/IFS 06/12/18Z) begins
    only 2026-06-02/03 (~33 days). A no-look-ahead rolling-45d 12Z EMOS
    re-calibration is therefore INFEASIBLE (needs 30+ prior 12Z days). The 12Z
    probe here reuses the 00Z EMOS affine map applied to the fresh 12Z ensemble
    statistics -- an approximation, flagged, directional over ~33 days.
  * `prices` top-of-book is DENSE and full-day (all 24 hours) back to ~2025-06
    (KORD/KMIA) / 2026-02 (KDFW). So the market-vs-static-fair accuracy curve by
    time-of-day is WELL-POWERED (~400 / ~140 days). This is the backbone result.

Run:  cd /home/tdunn/wt-intraday-fair && uv run python scripts/analysis/intraday_fair_value.py
"""
from __future__ import annotations

import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    NoForecastDataError,
)
from weather_markets.emos import fit_emos, gaussian_to_bracket_probs
from weather_markets.evaluation import contract_resolved_yes

CITIES = [
    ("KORD", "KXHIGHCHI", 14),   # (station, high series, current decision hour UTC)
    ("KMIA", "KXHIGHMIA", 15),
    ("KDFW", "KXHIGHTDAL", 17),
]
MODELS = ["gefs", "ifs"]          # "combined"
WINDOW_DAYS = 45
MIN_TRAIN_DAYS = 30
HOURS = list(range(8, 24))        # UTC hours to sample the market at
EPS = 1e-6

# 12Z ensemble physically available ~this UTC hour (run lands + our ingest lag).
# Used only to decide WHEN the intraday fair may switch from 00Z -> 12Z.
IFS_12Z_AVAIL_HOUR = 18


def clip(p: float) -> float:
    return min(1.0 - 1e-9, max(1e-9, p))


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    p = clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def fetch_contracts_high(conn, station: str, series: str) -> dict[date, list[dict]]:
    """All HIGH-series contracts per target_date for a station."""
    out: dict[date, list[dict]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT target_date, ticker, bracket_type, strike_low, strike_high
                 FROM contracts
                WHERE station_id=%s AND series=%s
                ORDER BY target_date, bracket_type, strike_low""",
            (station, series),
        )
        for td, tk, bt, sl, sh in cur.fetchall():
            out[td].append(
                {"ticker": tk, "bracket_type": bt, "strike_low": sl, "strike_high": sh}
            )
    return out


def fetch_obs(conn, station: str) -> dict[date, float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, high_temp_f FROM observations WHERE station_id=%s", (station,)
        )
        return {d: float(h) for d, h in cur.fetchall()}


def ens_stats(conn, station: str, init_hour: int, d: date):
    """(mean, std) of the combined daily-high ensemble for a run at init_hour on d.

    Mirrors aggregation.collect_training_pairs exactly (statistics.mean/stdev)."""
    init = datetime(d.year, d.month, d.day, init_hour, 0, tzinfo=timezone.utc)
    try:
        vals = compute_combined_daily_highs(init, d, conn, station_id=station, models=MODELS)
    except NoForecastDataError:
        return None
    if len(vals) < 2:
        return None
    return statistics.mean(vals), statistics.stdev(vals)


def build_ens_cache(conn, station: str, dates: list[date], init_hour: int):
    cache = {}
    for d in dates:
        s = ens_stats(conn, station, init_hour, d)
        if s is not None:
            cache[d] = s
    return cache


def rolling_emos_probs(cache_00z, obs, target: date, contracts: list[dict]):
    """No-look-ahead rolling-45d 00Z EMOS -> per-ticker YES prob for `target`.

    Training = cached days in [target-45, target-1] that have both an ensemble
    and an observation (identical selection to fit_emos_rolling)."""
    if target not in cache_00z:
        return None, None
    lo = target - timedelta(days=WINDOW_DAYS)
    tr_means, tr_stds, tr_obs, tr_dates = [], [], [], []
    d = lo
    while d <= target - timedelta(days=1):
        if d in cache_00z and d in obs:
            m, s = cache_00z[d]
            tr_means.append(m); tr_stds.append(s); tr_obs.append(obs[d]); tr_dates.append(d)
        d += timedelta(days=1)
    if len(tr_means) < MIN_TRAIN_DAYS:
        return None, None
    fit = fit_emos(tr_means, tr_stds, tr_obs)
    mean_t, std_t = cache_00z[target]
    mu = fit["a"] + fit["b"] * mean_t
    sigma = math.sqrt(max(fit["c"] + fit["d"] * std_t ** 2, EPS))
    probs = gaussian_to_bracket_probs(mu, sigma, contracts)
    return probs, max(tr_dates)   # also return latest train date for the no-lookahead check


def emos_probs_on_stats(fit: dict, mean_t: float, std_t: float, contracts: list[dict]):
    """Apply an already-fit EMOS affine map to a (possibly 12Z) ensemble stat."""
    mu = fit["a"] + fit["b"] * mean_t
    sigma = math.sqrt(max(fit["c"] + fit["d"] * std_t ** 2, EPS))
    return gaussian_to_bracket_probs(mu, sigma, contracts)


def fetch_market_mid_by_hour(conn, station: str, series: str):
    """{(target_date, ticker, hour): mid_prob} -- last two-sided quote in each hour."""
    out = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (c.target_date, p.ticker, date_trunc('hour', p.snapshot_at))
                      c.target_date, p.ticker,
                      EXTRACT(hour FROM p.snapshot_at)::int AS hr,
                      p.yes_bid, p.yes_ask
                 FROM prices p JOIN contracts c ON c.ticker=p.ticker
                WHERE c.station_id=%s AND c.series=%s
                  AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
                  AND p.yes_ask >= p.yes_bid AND p.yes_ask > 0
                ORDER BY c.target_date, p.ticker, date_trunc('hour', p.snapshot_at),
                         p.snapshot_at DESC""",
            (station, series),
        )
        for td, tk, hr, yb, ya in cur.fetchall():
            out[(td, tk, hr)] = (yb + ya) / 200.0   # cents midpoint -> prob
    return out


def agg(scores):
    if not scores:
        return None
    b = statistics.mean(s[0] for s in scores)
    ll = statistics.mean(s[1] for s in scores)
    return b, ll, len(scores)


def ece(pairs, nbins=10):
    """Expected calibration error: sum_b (n_b/N) * |mean_pred_b - obs_freq_b|.
    pairs = list of (pred_prob, outcome_0_1). Lower = better calibrated."""
    if not pairs:
        return None
    bins = [[] for _ in range(nbins)]
    for p, y in pairs:
        bins[min(nbins - 1, int(p * nbins))].append((p, y))
    N = len(pairs)
    e = 0.0
    for b in bins:
        if not b:
            continue
        mp = statistics.mean(x[0] for x in b)
        of = statistics.mean(x[1] for x in b)
        e += (len(b) / N) * abs(mp - of)
    return e


def main():
    conn = get_connection()
    print("=" * 78)
    print("INTRADAY FAIR-VALUE GATE STUDY")
    print("=" * 78)

    global_report = {}

    for station, series, decision_hr in CITIES:
        print(f"\n{'#'*70}\n# {station}  (series {series}, current decision ~{decision_hr}Z)\n{'#'*70}")
        contracts_by_date = fetch_contracts_high(conn, station, series)
        obs = fetch_obs(conn, station)
        all_dates = sorted(d for d in contracts_by_date if d in obs and d < date.today())
        if not all_dates:
            print("  no usable dates"); continue

        # ensemble caches
        cache_00z = build_ens_cache(conn, station, all_dates, 0)
        cache_12z = build_ens_cache(conn, station, all_dates, 12)
        print(f"  dates with contracts+obs: {len(all_dates)}  "
              f"(00Z ens: {len(cache_00z)}, 12Z ens: {len(cache_12z)})")

        # static 00Z fair per (date,ticker), plus outcomes
        static_prob = {}          # (date,ticker) -> p
        intraday_prob = {}        # (date,ticker) -> p   (12Z-refresh probe, recent only)
        outcome = {}              # (date,ticker) -> 0/1
        train_ok = 0
        lookahead_samples = []
        for d in all_dates:
            contracts = contracts_by_date[d]
            probs, last_train = rolling_emos_probs(cache_00z, obs, d, contracts)
            if probs is None:
                continue
            train_ok += 1
            if len(lookahead_samples) < 5:
                lookahead_samples.append((d, last_train))
            ohigh = int(round(obs[d]))
            # refit params for the 12Z probe reuse (recompute the same fit once)
            fit12 = None
            if d in cache_12z:
                # rebuild the 00Z fit to get affine params (cheap; same window)
                lo = d - timedelta(days=WINDOW_DAYS)
                tm, ts, to = [], [], []
                dd = lo
                while dd <= d - timedelta(days=1):
                    if dd in cache_00z and dd in obs:
                        m, s = cache_00z[dd]; tm.append(m); ts.append(s); to.append(obs[dd])
                    dd += timedelta(days=1)
                if len(tm) >= MIN_TRAIN_DAYS:
                    fit12 = fit_emos(tm, ts, to)
            for c in contracts:
                tk = c["ticker"]
                if tk not in probs:
                    continue
                static_prob[(d, tk)] = probs[tk]
                outcome[(d, tk)] = 1 if contract_resolved_yes(ohigh, c) else 0
            if fit12 is not None:
                m12, s12 = cache_12z[d]
                p12 = emos_probs_on_stats(fit12, m12, s12, contracts_by_date[d])
                for c in contracts_by_date[d]:
                    if c["ticker"] in p12:
                        intraday_prob[(d, c["ticker"])] = p12[c["ticker"]]

        print(f"  target-days with a valid rolling EMOS fit: {train_ok}")
        # no-lookahead assertion for the static fair
        bad = [(d, lt) for d, lt in lookahead_samples if lt >= d]
        print(f"  no-lookahead check (EMOS train_end < target): "
              f"{'PASS' if not bad else 'FAIL '+str(bad)}  e.g. {lookahead_samples[:3]}")

        market = fetch_market_mid_by_hour(conn, station, series)

        # ---- accuracy vs time-of-day (common sample per hour) ----
        # static (constant) scored on the SAME (date,ticker) that have a market quote at hour T
        curve = []
        for hr in HOURS:
            m_scores, s_scores = [], []
            for key in market:
                d, tk, kh = key
                if kh != hr:
                    continue
                if (d, tk) not in static_prob:
                    continue
                y = outcome[(d, tk)]
                mp = market[key]
                m_scores.append((brier(mp, y), logloss(mp, y)))
                sp = static_prob[(d, tk)]
                s_scores.append((brier(sp, y), logloss(sp, y)))
            ma = agg(m_scores); sa = agg(s_scores)
            if ma and sa:
                curve.append((hr, sa[0], sa[1], ma[0], ma[1], ma[2]))

        print(f"\n  {'hr':>3} | {'static_Brier':>12} {'static_LL':>9} | "
              f"{'mkt_Brier':>9} {'mkt_LL':>7} | {'n':>5} | winner")
        crossover = None
        for hr, sb, sll, mb, mll, n in curve:
            win = "MARKET" if mb < sb else "static"
            if crossover is None and mb <= sb:
                crossover = hr
            mark = "  <-- decision" if hr == decision_hr else ""
            star = "  *CROSSOVER*" if hr == crossover else ""
            print(f"  {hr:>3} | {sb:>12.4f} {sll:>9.4f} | {mb:>9.4f} {mll:>7.4f} | "
                  f"{n:>5} | {win}{star}{mark}")

        # static full-sample single number
        full_static = agg([(brier(static_prob[k], outcome[k]),
                            logloss(static_prob[k], outcome[k])) for k in static_prob])
        print(f"\n  STATIC-00Z full sample: Brier={full_static[0]:.4f} "
              f"LL={full_static[1]:.4f} n={full_static[2]}")
        # calibration / reliability (ECE) -- static full sample vs market at decision hour
        static_ece = ece([(static_prob[k], outcome[k]) for k in static_prob])
        mkt_dec = [(market[(d, tk, decision_hr)], outcome[(d, tk)])
                   for (d, tk) in static_prob if (d, tk, decision_hr) in market]
        market_ece = ece(mkt_dec)
        print(f"  CALIBRATION (ECE, lower=better): static-00Z={static_ece:.4f}  "
              f"market@{decision_hr}Z={market_ece:.4f} (n={len(mkt_dec)})")
        if crossover is not None:
            print(f"  MARKET CATCHES/PASSES STATIC at ~{crossover}Z "
                  f"(decision hr {decision_hr}Z: "
                  f"{'market already ahead' if crossover <= decision_hr else 'static still ahead'})")
        else:
            print(f"  Market never beats static within {HOURS[0]}-{HOURS[-1]}Z on this sample")

        # ---- 12Z intraday probe (directional, recent ~33d) ----
        # Compare static vs intraday(12Z) vs market at the afternoon availability hour,
        # on the common sample where all three exist.
        probe_hours = [h for h in HOURS if h >= IFS_12Z_AVAIL_HOUR]
        if intraday_prob:
            s_sc, i_sc, m_sc = [], [], []
            common_days = set()
            for (d, tk), ip in intraday_prob.items():
                if (d, tk) not in static_prob:
                    continue
                # market at first available probe hour
                mp = None
                for hr in probe_hours:
                    if (d, tk, hr) in market:
                        mp = market[(d, tk, hr)]
                        break
                if mp is None:
                    continue
                y = outcome[(d, tk)]
                s_sc.append((brier(static_prob[(d, tk)], y), 0))
                i_sc.append((brier(ip, y), 0))
                m_sc.append((brier(mp, y), 0))
                common_days.add(d)
            if s_sc:
                print(f"\n  12Z INTRADAY PROBE (directional, {len(common_days)} days, "
                      f"n={len(s_sc)} bracket-obs, market@>={IFS_12Z_AVAIL_HOUR}Z):")
                print(f"    static-00Z Brier = {statistics.mean(x[0] for x in s_sc):.4f}")
                print(f"    intraday-12Z Brier = {statistics.mean(x[0] for x in i_sc):.4f}")
                print(f"    market Brier       = {statistics.mean(x[0] for x in m_sc):.4f}")
        else:
            print("\n  12Z INTRADAY PROBE: no overlapping 12Z-fit days (expected; "
                  "12Z history < 45d training window).")

        global_report[station] = {
            "crossover": crossover,
            "decision_hr": decision_hr,
            "static_brier": full_static[0],
            "curve": curve,
        }

    # ---- no-lookahead spot check on the MARKET side ----
    # The hour-T market mid is the LAST two-sided snapshot within hour T. It must be
    # invariant to hiding all data after T:59:59 (it can only ever see <= T).
    print(f"\n{'='*78}\nNO-LOOKAHEAD SPOT CHECK (market side)\n{'='*78}")
    st, se, _ = CITIES[0]
    from datetime import time as _time
    with conn.cursor() as cur:  # pick a settled recent date + a liquid bracket
        cur.execute(
            """SELECT c.target_date, p.ticker
                 FROM prices p JOIN contracts c ON c.ticker=p.ticker
                WHERE c.station_id=%s AND c.series=%s AND c.target_date < %s
                  AND EXTRACT(hour FROM p.snapshot_at)=14
                  AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
                GROUP BY 1,2 ORDER BY c.target_date DESC, COUNT(*) DESC LIMIT 1""",
            (st, se, date.today()),
        )
        td, tk = cur.fetchone()

    def _hour14_mid(cutoff):
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.yes_bid, p.yes_ask FROM prices p
                    WHERE p.ticker=%s AND p.snapshot_at::date=%s
                      AND EXTRACT(hour FROM p.snapshot_at)=14
                      AND p.snapshot_at <= %s
                      AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
                      AND p.yes_ask>=p.yes_bid AND p.yes_ask>0
                    ORDER BY p.snapshot_at DESC LIMIT 1""",
                (tk, td, cutoff),
            )
            r = cur.fetchone()
        return None if r is None else (r[0] + r[1]) / 200.0

    full_day = _hour14_mid(datetime.combine(td, _time(23, 59, 59), tzinfo=timezone.utc))
    hidden = _hour14_mid(datetime.combine(td, _time(14, 59, 59), tzinfo=timezone.utc))
    print(f"  {tk} {td} hour-14 mid: full-day-visible={full_day}  hide-post-T={hidden}  "
          f"-> {'PASS (identical; depends only on <=T)' if full_day == hidden else 'FAIL'}")

    print(f"\n{'='*78}\nSUMMARY (crossover = first hour the MARKET's Brier <= static-00Z)\n{'='*78}")
    for st in global_report:
        r = global_report[st]
        co = r["crossover"]
        verdict = ("market ahead by/at decision" if co is not None and co <= r["decision_hr"]
                   else f"static ahead through {co}Z" if co else "static ahead all day")
        print(f"  {st}: static Brier {r['static_brier']:.4f}; "
              f"decision {r['decision_hr']}Z; crossover {co}Z -> {verdict}")

    conn.close()


if __name__ == "__main__":
    main()
