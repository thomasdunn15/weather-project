"""Read-only per-model forecast-skill comparison for the daily-HIGH strategy.

Answers: among the models we currently ingest (GEFS, IFS, HRRR), which carries
the most day-ahead skill, does combining them beat any single model, and how
correlated are their errors (i.e. how much room is there for a *new* model to
add independent signal)?

Method (mirrors production daily-high path, aggregation.compute_daily_highs):
  - 00Z init, target = same UTC calendar day D.
  - Per ensemble member, daily high = MAX(tmax_f) over local-day-D valid times
    (station IANA tz).
  - Skill of the ENSEMBLE MEAN: bias / MAE / RMSE vs the realized CF6 high.
    (MAE/RMSE of the ensemble mean is what external benchmarks — WeatherBench-2,
    ECMWF scorecards — publish for 2 m temperature, so it is the cross-comparable
    metric.)
  - Probabilistic skill: fair (PWM) ensemble CRPS, and a rolling-45-day
    EMOS-calibrated Gaussian CRPS (mirrors emos.fit_emos production calibration).
  - DECISION-RELEVANT reliability: per-station bracket-edge Brier. The same
    rolling-EMOS Gaussian is turned into a YES probability for each production
    Kalshi bracket (emos.gaussian_to_bracket_probs — the exact bins the backtest
    trades) and scored against the realized bracket with evaluation.brier_score.
    CRPS measures the whole distribution; Brier measures how well the model
    prices the discrete contracts we actually trade — an addition can lower CRPS
    yet *worsen* bracket-edge calibration, so both are reported.

Read-only: SELECTs only. No writes, no trading.

Run: cd /home/tdunn/weather-project && uv run python scripts/analysis/forecast_model_skill.py
"""
import statistics
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from weather_markets.db import get_connection
from weather_markets.emos import fit_emos, crps_gaussian, gaussian_to_bracket_probs
from weather_markets.evaluation import brier_score, contract_resolved_yes
from weather_markets import stations as stations_mod

EMOS_WINDOW = 45

# Cities where the per-city diagnostic found a robust edge (Chicago O'Hare +
# Midway, Miami, Seattle). Highlighted in the bracket-edge Brier table because
# reliability there is what actually converts to traded edge.
EDGE_CITIES = {"KORD", "KMDW", "KMIA", "KSEA"}


# ─────────────────────────────────────────────────────────────────────────────
# MODEL / CONFIG REGISTRY — the one place to plug in a new forecast model.
#
# To score a new model (Phase-1 candidates: aifs, nbm, gem), add ONE
# ScoringConfig entry below. Nothing else changes: the raw model strings are
# auto-collected into MODELS (so fetch_member_highs pulls them), and the config
# flows through every table — pooled skill, rolling-EMOS CRPS, per-station MAE,
# per-station CRPS, and the bracket-edge Brier.
#
#   ScoringConfig("combined_aifs", ("gefs", "ifs", "aifs"))            # pool members
#   ScoringConfig("aifs",          ("aifs",))                          # single model
#   ScoringConfig("combined_nbm",  ("gefs", "ifs", "nbm"))             # add NBM
#
# Fields:
#   name      — label shown in every table.
#   members   — raw `forecasts.model` strings pooled for this config. Scored on
#               a day only when EVERY listed model has >=1 member present.
#   weighting — "member" (flat member pool; production default) or "model"
#               (equal-weight each model's mean — used by avg_g_i).
#   headline  — include in the rolling-EMOS CRPS / per-station / Brier tables
#               (the production-relevant views). The pooled-skill table always
#               lists every config regardless.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ScoringConfig:
    name: str
    members: tuple[str, ...]
    weighting: str = "member"   # "member" | "model"
    headline: bool = True


CONFIGS: list[ScoringConfig] = [
    ScoringConfig("gefs", ("gefs",)),
    ScoringConfig("ifs", ("ifs",)),
    ScoringConfig("hrrr", ("hrrr",), headline=False),
    ScoringConfig("nbm", ("nbm",), headline=False),          # NBM core alone (pooled-skill table)
    ScoringConfig("combined", ("gefs", "ifs")),
    ScoringConfig("combined_hrrr", ("gefs", "ifs", "hrrr")),
    ScoringConfig("combined_nbm", ("gefs", "ifs", "nbm")),    # Phase-1: + NBM calibrated daily-Tmax
    ScoringConfig("avg_g_i", ("gefs", "ifs"), weighting="model", headline=False),
]

# Raw models to fetch from the DB = union of every config's members.
MODELS = sorted({m for c in CONFIGS for m in c.members})
HEADLINE_CONFIGS = [c for c in CONFIGS if c.headline]


def fetch_member_highs(conn, station_id, model, tz):
    """Return {D(date): {member_id: daily_high_f}} for 00Z runs, local-day-D max."""
    sql = """
        SELECT (init_time AT TIME ZONE 'UTC')::date AS d,
               member_id,
               MAX(tmax_f) AS hi
        FROM forecasts
        WHERE station_id = %s AND model = %s
          AND EXTRACT(hour FROM init_time AT TIME ZONE 'UTC') = 0
          AND tmax_f IS NOT NULL
          AND (valid_time AT TIME ZONE %s)::date = (init_time AT TIME ZONE 'UTC')::date
        GROUP BY d, member_id
    """
    out = defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute(sql, (station_id, model, tz))
        for d, mid, hi in cur.fetchall():
            out[d][mid] = float(hi)
    return out


def fetch_obs(conn, station_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, high_temp_f FROM observations WHERE station_id=%s",
            (station_id,),
        )
        return {d: float(h) for d, h in cur.fetchall()}


def load_contracts_by_date(conn, station_id, series):
    """Production Kalshi bracket set for a station, grouped: {D(date): [contract]}.

    This is the bulk form of aggregation.fetch_contracts_for_date — identical
    SELECT (same columns, same `series` filter, default platform), just without
    the per-date WHERE so the whole history loads in ONE query (the box is
    RAM/round-trip constrained). The per-date bracket lists are therefore
    byte-identical to what production scores: bins come straight from the
    `contracts` table, never invented here.

    Returns {} when `series` is empty (station has no Kalshi daily-high market,
    e.g. KMDW/KSFO) — those stations simply get no Brier.
    """
    if not series:
        return {}
    sql = """
        SELECT target_date, ticker, bracket_type, strike_low, strike_high
        FROM contracts
        WHERE station_id = %s AND series = %s
        ORDER BY target_date, bracket_type, strike_low
    """
    out = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(sql, (station_id, series))
        for tdate, ticker, bt, lo, hi in cur.fetchall():
            out[tdate].append(
                {"ticker": ticker, "bracket_type": bt, "strike_low": lo, "strike_high": hi}
            )
    return dict(out)


def score_day_brackets(mu, sigma, contracts, observed_high):
    """Bracket-edge Brier for one day on the production Kalshi bracket set.

    Turns the EMOS-calibrated Gaussian N(mu, sigma) into a YES probability for
    each production contract (emos.gaussian_to_bracket_probs — the SAME bins the
    backtest trades), then scores each against the realized bracket with
    evaluation.contract_resolved_yes + evaluation.brier_score. No bins are
    invented; `contracts` is whatever the production fetch returns.

    Returns dict:
      briers       — per-bracket Brier (probability vs YES/NO), one per contract.
      resolved_yes — 1/0 YES outcome per contract (same order).
      prob_sum     — sum of model YES probabilities (~1 when the brackets
                     partition the integer line; a conservation sanity check,
                     not used in the score itself).
    """
    probs = gaussian_to_bracket_probs(mu, sigma, contracts)
    briers, resolved = [], []
    prob_sum = 0.0
    for c in contracts:
        p = probs[c["ticker"]]
        prob_sum += p
        yes = contract_resolved_yes(observed_high, c)
        resolved.append(1 if yes else 0)
        briers.append(brier_score(p, yes))
    return {"briers": briers, "resolved_yes": resolved, "prob_sum": prob_sum}


def fair_ens_crps(members, y):
    """Fair (almost-unbiased) ensemble CRPS estimator.

    CRPS = mean_i |x_i - y| - 1/(2 m(m-1)) * sum_{i,j} |x_i - x_j|
    For m == 1 reduces to |x - y| (deterministic CRPS == abs error).
    """
    a = np.sort(np.asarray(members, dtype=float))
    m = len(a)
    s1 = np.mean(np.abs(a - y))
    if m == 1:
        return float(s1)
    # sum_{i<j}(x_j - x_i) for ascending-sorted a  ==  sum_k (2k-(m-1)) x_k
    k = np.arange(m)
    pair = float(np.sum((2 * k - (m - 1)) * a))   # = sum_{i<j} |x_i - x_j|
    return float(s1 - pair / (m * (m - 1)))


def mean_std(members):
    if len(members) < 2:
        return statistics.mean(members), 0.0
    return statistics.mean(members), statistics.stdev(members)


def rolling_emos_predictions(series):
    """Yield (date, mu, sigma, obs) for each out-of-sample day.

    series: list of (date, mean, std, obs) with std>0. Rolling 45-day train ->
    predict next day with the EMOS-calibrated Gaussian. Shared by the CRPS and
    the bracket-Brier paths so both score the IDENTICAL calibrated Gaussian.
    """
    series = [r for r in series if r[2] > 0]
    series.sort(key=lambda r: r[0])
    for i in range(len(series)):
        train = series[max(0, i - EMOS_WINDOW):i]
        if len(train) < EMOS_WINDOW:
            continue
        means = [t[1] for t in train]
        stds = [t[2] for t in train]
        obs = [t[3] for t in train]
        try:
            p = fit_emos(means, stds, obs)
        except Exception:
            continue
        d, mu_raw, sd_raw, y = series[i]
        mu = p["a"] + p["b"] * mu_raw
        var = p["c"] + p["d"] * sd_raw ** 2
        if var <= 0:
            continue
        yield d, mu, var ** 0.5, y


def rolling_emos_crps(series):
    """Out-of-sample rolling-EMOS Gaussian CRPS list (closed-form, per day)."""
    return [crps_gaussian(mu, sigma, y) for _d, mu, sigma, y in rolling_emos_predictions(series)]


def agg(errs):
    e = np.asarray(errs, dtype=float)
    return {
        "n": len(e),
        "bias": float(np.mean(e)),
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e ** 2))),
    }


def main():
    station_ids = sorted(stations_mod.STATIONS.keys())
    conn = get_connection()

    # Accumulators -------------------------------------------------------
    # raw ensemble-mean errors, per config, pooled
    pooled_err = defaultdict(list)         # config -> [signed errors]
    pooled_crps = defaultdict(list)        # config -> [fair ens crps]
    per_station_mae = defaultdict(dict)    # config -> {station: mae}
    per_station_crps = defaultdict(dict)
    emos_series = defaultdict(lambda: defaultdict(list))  # config -> station -> series

    # matched-sample (gefs & ifs both present) errors
    matched_err = defaultdict(list)        # config -> errors on gefs&ifs days
    # error-correlation accumulators
    g_err_all, i_err_all = [], []
    # hrrr-matched (all three present)
    hrrr_match_err = defaultdict(list)

    for st in station_ids:
        tz = stations_mod.STATIONS[st].timezone
        obs = fetch_obs(conn, st)
        mh = {m: fetch_member_highs(conn, st, m, tz) for m in MODELS}
        all_dates = sorted(set().union(*[set(mh[m].keys()) for m in MODELS]) & set(obs.keys()))

        st_err = defaultdict(list)
        st_crps = defaultdict(list)
        for d in all_dates:
            y = obs[d]
            present = {m: list(mh[m].get(d, {}).values()) for m in MODELS}

            def record(cfg, members):
                if not members:
                    return
                mu = statistics.mean(members)
                err = mu - y
                pooled_err[cfg].append(err)
                st_err[cfg].append(err)
                c = fair_ens_crps(members, y)
                pooled_crps[cfg].append(c)
                st_crps[cfg].append(c)
                mn, sd = mean_std(members)
                emos_series[cfg][st].append((d, mn, sd, y))

            # Declarative configs — one generic path drives every entry in the
            # registry, so a new model is scored by adding a ScoringConfig only.
            for cfg in CONFIGS:
                member_lists = [present[m] for m in cfg.members]
                if not all(member_lists):           # every constituent model must be present
                    continue
                if cfg.weighting == "model":         # equal-weight each model's mean
                    members = [statistics.mean(ml) for ml in member_lists]
                else:                                # flat member pool (production default)
                    members = [v for ml in member_lists for v in ml]
                record(cfg.name, members)

            # Bespoke matched-sample + error-correlation block (GEFS/IFS/HRRR
            # specific — unchanged, still the basis of §3 and the HRRR sample).
            g, i, h = present.get("gefs", []), present.get("ifs", []), present.get("hrrr", [])
            if g and i:
                matched_err["gefs"].append(statistics.mean(g) - y)
                matched_err["ifs"].append(statistics.mean(i) - y)
                matched_err["combined"].append(statistics.mean(g + i) - y)
                g_err_all.append(statistics.mean(g) - y)
                i_err_all.append(statistics.mean(i) - y)
            if g and i and h:
                hrrr_match_err["combined"].append(statistics.mean(g + i) - y)
                hrrr_match_err["combined_hrrr"].append(statistics.mean(g + i + h) - y)
                hrrr_match_err["hrrr"].append(statistics.mean(h) - y)

        for cfg in CONFIGS:
            if st_err[cfg.name]:
                per_station_mae[cfg.name][st] = agg(st_err[cfg.name])["mae"]
                per_station_crps[cfg.name][st] = float(np.mean(st_crps[cfg.name]))

    # ---- Rolling-EMOS predictions: ONE fit per (headline config, station),
    #      from which BOTH the CRPS (unchanged metric) and the new bracket-edge
    #      Brier are derived (so EMOS is not re-fit twice). -------------------
    emos_crps = defaultdict(list)              # cfg -> pooled out-of-sample CRPS
    per_station_emos_crps = defaultdict(dict)  # cfg -> {st: mean CRPS}
    per_station_brier = defaultdict(dict)      # cfg -> {st: mean per-bracket Brier}
    per_station_brier_n = defaultdict(dict)    # cfg -> {st: (n_days, n_brackets)}
    pooled_brier = defaultdict(list)           # cfg -> per-bracket Brier (stations w/ market)
    edge_brier = defaultdict(list)             # cfg -> per-bracket Brier, EDGE_CITIES only

    for st in station_ids:
        series_ticker = stations_mod.STATIONS[st].kalshi_series
        cbd = load_contracts_by_date(conn, st, series_ticker)   # {} if no Kalshi market
        for cfg in HEADLINE_CONFIGS:
            preds = list(rolling_emos_predictions(emos_series[cfg.name][st]))
            if not preds:
                continue
            st_c = [crps_gaussian(mu, s, y) for _d, mu, s, y in preds]
            emos_crps[cfg.name].extend(st_c)
            per_station_emos_crps[cfg.name][st] = float(np.mean(st_c))
            if not cbd:
                continue
            st_briers, n_days = [], 0
            for d, mu, sigma, y in preds:
                contracts = cbd.get(d)
                if not contracts:
                    continue
                # CF6 highs are whole °F; round to the integer the contract resolves on.
                res = score_day_brackets(mu, sigma, contracts, int(round(y)))
                st_briers.extend(res["briers"])
                n_days += 1
            if st_briers:
                per_station_brier[cfg.name][st] = float(np.mean(st_briers))
                per_station_brier_n[cfg.name][st] = (n_days, len(st_briers))
                pooled_brier[cfg.name].extend(st_briers)
                if st in EDGE_CITIES:
                    edge_brier[cfg.name].extend(st_briers)

    headline_names = [c.name for c in HEADLINE_CONFIGS]

    # ---------------- OUTPUT ----------------
    print("=" * 78)
    print("PER-MODEL DAY-AHEAD SKILL (00Z init, same-day high, all 13 stations pooled)")
    print("=" * 78)
    print(f"{'config':<16}{'n':>7}{'bias':>9}{'MAE':>9}{'RMSE':>9}{'ensCRPS':>10}")
    for cfg in CONFIGS:
        if not pooled_err[cfg.name]:
            continue
        a = agg(pooled_err[cfg.name])
        c = float(np.mean(pooled_crps[cfg.name]))
        print(f"{cfg.name:<16}{a['n']:>7}{a['bias']:>9.2f}{a['mae']:>9.2f}{a['rmse']:>9.2f}{c:>10.3f}")

    print("\n" + "=" * 78)
    print("MATCHED SAMPLE — days where BOTH GEFS & IFS present (apples-to-apples)")
    print("=" * 78)
    print(f"{'config':<16}{'n':>7}{'bias':>9}{'MAE':>9}{'RMSE':>9}")
    for cfg in ["gefs", "ifs", "combined"]:
        a = agg(matched_err[cfg])
        print(f"{cfg:<16}{a['n']:>7}{a['bias']:>9.2f}{a['mae']:>9.2f}{a['rmse']:>9.2f}")
    if len(g_err_all) > 2:
        r = float(np.corrcoef(g_err_all, i_err_all)[0, 1])
        print(f"\nGEFS-mean error vs IFS-mean error: Pearson r = {r:.3f}  (n={len(g_err_all)})")
        print("  (high r -> errors shared -> little room for a same-family model to add signal)")

    print("\n" + "=" * 78)
    print("HRRR MATCHED SAMPLE — days where GEFS & IFS & HRRR all present")
    print("=" * 78)
    print(f"{'config':<16}{'n':>7}{'bias':>9}{'MAE':>9}{'RMSE':>9}")
    for cfg in ["hrrr", "combined", "combined_hrrr"]:
        if hrrr_match_err[cfg]:
            a = agg(hrrr_match_err[cfg])
            print(f"{cfg:<16}{a['n']:>7}{a['bias']:>9.2f}{a['mae']:>9.2f}{a['rmse']:>9.2f}")

    print("\n" + "=" * 78)
    print("ROLLING-45d EMOS-CALIBRATED CRPS (out-of-sample, pooled over stations)")
    print("=" * 78)
    print(f"{'config':<16}{'n_eval':>8}{'meanCRPS':>11}")
    for cfg in headline_names:
        if emos_crps[cfg]:
            print(f"{cfg:<16}{len(emos_crps[cfg]):>8}{float(np.mean(emos_crps[cfg])):>11.3f}")

    print("\n" + "=" * 78)
    print("PER-STATION MAE of ENSEMBLE MEAN (°F)  [combined = gefs+ifs]")
    print("=" * 78)
    hdr = f"{'station':<9}" + "".join(f"{c:>14}" for c in headline_names)
    print(hdr)
    for st in station_ids:
        row = f"{st:<9}"
        for c in headline_names:
            v = per_station_mae[c].get(st)
            row += f"{v:>14.2f}" if v is not None else f"{'-':>14}"
        print(row)

    print("\n" + "=" * 78)
    print("PER-STATION ROLLING-45d EMOS CRPS (°F, out-of-sample)  [* = EDGE CITY]")
    print("=" * 78)
    print(f"{'station':<9}" + "".join(f"{c:>14}" for c in headline_names))
    for st in station_ids:
        mark = "*" if st in EDGE_CITIES else " "
        row = f"{mark}{st:<8}"
        for c in headline_names:
            v = per_station_emos_crps[c].get(st)
            row += f"{v:>14.3f}" if v is not None else f"{'-':>14}"
        print(row)

    print("\n" + "=" * 78)
    print("PER-STATION BRACKET-EDGE BRIER  [* = EDGE CITY]")
    print("  rolling-EMOS Gaussian -> production Kalshi brackets; lower = better.")
    print("  decision-relevant reliability (vs CRPS, which scores the whole pdf).")
    print("=" * 78)
    print(f"{'station':<9}" + "".join(f"{c:>14}" for c in headline_names))
    for st in station_ids:
        mark = "*" if st in EDGE_CITIES else " "
        row = f"{mark}{st:<8}"
        for c in headline_names:
            v = per_station_brier[c].get(st)
            row += f"{v:>14.4f}" if v is not None else f"{'-':>14}"
        print(row)
    print("  '-' = no production Kalshi daily-high market for that station "
          "(KMDW, KSFO: kalshi_series empty).")

    print("\nPOOLED bracket-edge Brier (all stations with a Kalshi market):")
    print(f"{'config':<16}{'n_days':>9}{'n_brk':>9}{'Brier':>11}")
    for c in headline_names:
        if pooled_brier[c]:
            n_days = sum(nd for nd, _ in per_station_brier_n[c].values())
            print(f"{c:<16}{n_days:>9}{len(pooled_brier[c]):>9}{float(np.mean(pooled_brier[c])):>11.4f}")

    print("\nEDGE CITIES bracket-edge Brier (KORD, KMIA, KSEA; KMDW has no Kalshi high market):")
    print(f"{'config':<16}{'n_brk':>9}{'Brier':>11}")
    for c in headline_names:
        if edge_brier[c]:
            print(f"{c:<16}{len(edge_brier[c]):>9}{float(np.mean(edge_brier[c])):>11.4f}")

    conn.close()


if __name__ == "__main__":
    main()
