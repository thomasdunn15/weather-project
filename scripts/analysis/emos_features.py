"""EMOS feature engineering analysis.

Tests whether adding extra features to the EMOS location model improves
out-of-sample CRPS on each city's settled-day forecast history.

Baseline EMOS: Y ~ N(a + b·mean, c + d·var)
Extended EMOS: Y ~ N(a + b·mean + γ₁·x₁ + γ₂·x₂ + ..., c + d·var)

Features tested (each added independently, then in combinations):
  - yesterday_obs       — observed high yesterday at this station (persistence)
  - dow_weekend         — 1 if Sat/Sun else 0 (retail/market behavior shift)
  - sin_doy, cos_doy    — fourier encoding of day-of-year (seasonality residual)
  - ens_spread          — ensemble std (already absorbed by σ but maybe interacts)
  - abs_ens_mean_minus_climo — distance from city's annual mean climatology

Evaluation: rolling 45-day train, predict the next day, compute CRPS per day.
Compare mean CRPS over the held-out period.

Usage:
    uv run python scripts/analysis/emos_features.py
    uv run python scripts/analysis/emos_features.py --city KORD
"""
from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import numpy as np
from scipy.optimize import minimize
from scipy import stats

from weather_markets.db import get_connection
from weather_markets.stations import all_stations, get as get_station
from weather_markets.aggregation import compute_combined_daily_highs


# ---------- CRPS objective (closed-form for Gaussian) ----------
def gaussian_crps(obs: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    sigma = np.maximum(sigma, 1e-6)
    z = (obs - mu) / sigma
    return sigma * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / math.sqrt(math.pi))


# ---------- generic extended-EMOS fit ----------
def fit_extended_emos(means: np.ndarray, stds: np.ndarray, obs: np.ndarray,
                      extra: Optional[np.ndarray] = None) -> dict:
    """Fits Y ~ N(a + b·means + Γ·extra, c + d·stds²) by minimizing total CRPS.

    extra: (n, k) matrix of additional location features, or None.
    Returns dict with a, b, c, d, gamma (length k), and final_crps.
    """
    k = 0 if extra is None else extra.shape[1]

    def loss(params):
        a, b, c, d = params[:4]
        gamma = params[4:4 + k]
        var = np.maximum(c + d * stds ** 2, 1e-6)
        mu = a + b * means
        if k > 0:
            mu = mu + extra @ gamma
        return gaussian_crps(obs, mu, np.sqrt(var)).sum()

    x0 = np.concatenate([[0.0, 1.0, 1.0, 1.0], np.zeros(k)])
    bounds = [(None, None), (None, None), (1e-3, None), (0.0, None)] + [(None, None)] * k
    res = minimize(loss, x0, method="L-BFGS-B", bounds=bounds)
    if not res.success:
        raise RuntimeError(f"fit failed: {res.message}")
    a, b, c, d = res.x[:4]
    gamma = res.x[4:4 + k].tolist()
    return {"a": float(a), "b": float(b), "c": float(c), "d": float(d),
            "gamma": gamma, "final_crps": float(res.fun), "n": len(obs)}


# ---------- data loading ----------
def fetch_city_history(city_code: str, conn) -> list[dict]:
    """For each day with both a combined-ensemble forecast AND an observation,
    return: date, ens_mean, ens_std, obs.  Limits to last ~1 year for speed.
    """
    rows = []
    cur = conn.cursor()
    # Pull all observations we have for this station — start there to drive iteration
    cur.execute(
        """SELECT date, high_temp_f FROM observations
           WHERE station_id=%s AND date BETWEEN '2025-06-26' AND CURRENT_DATE
           ORDER BY date""",
        (city_code,))
    obs_rows = cur.fetchall()
    if not obs_rows:
        return []
    for obs_date, high in obs_rows:
        if high is None:
            continue
        # Build the ensemble for that date's 00Z init
        init_time = datetime(obs_date.year, obs_date.month, obs_date.day, 0, 0, tzinfo=timezone.utc)
        try:
            members = compute_combined_daily_highs(init_time, obs_date, conn,
                                                   station_id=city_code, models=["gefs", "ifs"])
        except Exception:
            continue
        if len(members) < 2:
            continue
        rows.append({
            "date": obs_date,
            "mean": statistics.mean(members),
            "std": statistics.stdev(members),
            "obs": float(high),
        })
    return rows


def attach_features(rows: list[dict]) -> list[dict]:
    """Augment each row with extra features computed from the row sequence."""
    # yesterday_obs: previous-day observed high (per-city, just sequential lookup
    # since rows are sorted by date and each city is processed alone)
    prev_obs = None
    for r in rows:
        r["yest_obs"] = prev_obs if prev_obs is not None else r["obs"]   # bootstrap
        prev_obs = r["obs"]
    # Compute city climatology mean (used for abs deviation feature)
    climo_mean = statistics.mean(r["obs"] for r in rows) if rows else 0
    for r in rows:
        doy = r["date"].timetuple().tm_yday
        r["sin_doy"] = math.sin(2 * math.pi * doy / 365.25)
        r["cos_doy"] = math.cos(2 * math.pi * doy / 365.25)
        r["dow_weekend"] = 1.0 if r["date"].weekday() >= 5 else 0.0
        r["ens_spread"] = r["std"]
        r["abs_mean_minus_climo"] = abs(r["mean"] - climo_mean)
    return rows


# ---------- rolling evaluation ----------
def rolling_crps(rows: list[dict], feature_names: list[str], window: int = 45) -> Optional[dict]:
    """Train on prior window_days, predict the next day's CRPS. Return mean CRPS."""
    if len(rows) < window + 30:    # require ~30 held-out days for credible mean
        return None
    crps_list = []
    for i in range(window, len(rows)):
        train = rows[i - window:i]
        test = rows[i]
        means = np.array([r["mean"] for r in train])
        stds = np.array([r["std"] for r in train])
        obs = np.array([r["obs"] for r in train])
        extra = None
        if feature_names:
            extra = np.array([[r[f] for f in feature_names] for r in train])
        try:
            fit = fit_extended_emos(means, stds, obs, extra)
        except Exception:
            continue
        # Predict the held-out day
        mu = fit["a"] + fit["b"] * test["mean"]
        if feature_names:
            mu += sum(g * test[f] for g, f in zip(fit["gamma"], feature_names))
        sigma = math.sqrt(max(fit["c"] + fit["d"] * test["std"] ** 2, 1e-6))
        crps_list.append(float(gaussian_crps(np.array([test["obs"]]),
                                              np.array([mu]), np.array([sigma]))[0]))
    if not crps_list:
        return None
    return {"mean_crps": statistics.mean(crps_list), "n_eval": len(crps_list)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--city", default=None)
    p.add_argument("--window", type=int, default=45)
    args = p.parse_args()

    CITIES = [("KORD","Chicago"),("KMIA","Miami"),("KAUS","Austin"),
              ("KDEN","Denver"),("KLAX","Los Angeles"),("KNYC","NYC")]
    if args.city:
        CITIES = [(c,n) for c,n in CITIES if c == args.city]

    # Feature sets to test — each row of results = one feature set
    feature_sets = [
        ("baseline",                []),
        ("+ yesterday_obs",          ["yest_obs"]),
        ("+ dow_weekend",            ["dow_weekend"]),
        ("+ sin/cos_doy",            ["sin_doy", "cos_doy"]),
        ("+ abs(mean - climo)",      ["abs_mean_minus_climo"]),
        ("+ yest + doy",             ["yest_obs", "sin_doy", "cos_doy"]),
        ("+ yest + doy + dow",       ["yest_obs", "sin_doy", "cos_doy", "dow_weekend"]),
        ("+ all five",               ["yest_obs", "sin_doy", "cos_doy", "dow_weekend", "abs_mean_minus_climo"]),
    ]

    print(f"{'='*92}\nRolling EMOS feature evaluation — window={args.window}d, predict next day, then advance\n{'='*92}")

    for code, name in CITIES:
        with get_connection() as conn:
            rows = fetch_city_history(code, conn)
        if len(rows) < args.window + 30:
            print(f"\n{name} ({code}): only {len(rows)} usable days — skipping")
            continue
        rows = attach_features(rows)
        baseline = rolling_crps(rows, [], window=args.window)
        if baseline is None:
            print(f"\n{name} ({code}): could not fit baseline — skipping"); continue

        print(f"\n{name} ({code}) — n_days={len(rows)}, n_eval={baseline['n_eval']}, baseline mean CRPS = {baseline['mean_crps']:.3f}°F")
        print(f"  {'feature set':<26} {'mean CRPS':>10} {'Δ vs baseline':>15} {'better?':>10}")
        for label, feats in feature_sets:
            res = rolling_crps(rows, feats, window=args.window)
            if res is None:
                print(f"  {label:<26} {'(failed)':>10}")
                continue
            delta = res["mean_crps"] - baseline["mean_crps"]
            arrow = "✓ better" if delta < -0.001 else ("✗ worse" if delta > 0.001 else "≈ same")
            print(f"  {label:<26} {res['mean_crps']:>9.3f}°F {delta:>+13.3f}°F {arrow:>10}")


if __name__ == "__main__":
    main()
