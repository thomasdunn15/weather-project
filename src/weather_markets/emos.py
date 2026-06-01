import math
from datetime import date, timedelta
from scipy import stats

from .aggregation import collect_training_pairs


def crps_gaussian(mu: float, sigma: float, observation: float) -> float:
    """
    Continuous Ranked Probability Score for a Gaussian forecast.
    
    Lower is better. CRPS = 0 means perfect prediction.
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    
    z = (observation - mu) / sigma
    return sigma * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / math.sqrt(math.pi))

def gaussian_to_bracket_probs(
    mu: float,
    sigma: float,
    contracts: list[dict],
) -> dict[str, float]:
    """
    Compute YES probabilities for each contract under a Gaussian forecast.
    
    Uses half-degree rounding for the integer→continuous boundary correction.
    """
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    
    result = {}
    for contract in contracts:
        bracket_type = contract["bracket_type"]
        
        if bracket_type == "greater_than":
            # P(integer > K) = P(continuous >= K + 0.5)
            threshold = contract["strike_low"] + 0.5
            prob = 1 - stats.norm.cdf((threshold - mu) / sigma)
        elif bracket_type == "less_than":
            # P(integer < K) = P(continuous < K - 0.5)
            threshold = contract["strike_high"] - 0.5
            prob = stats.norm.cdf((threshold - mu) / sigma)
        elif bracket_type == "between":
            # P(low <= integer <= high) = P(low - 0.5 <= continuous < high + 0.5)
            lower = contract["strike_low"] - 0.5
            upper = contract["strike_high"] + 0.5
            prob = (
                stats.norm.cdf((upper - mu) / sigma)
                - stats.norm.cdf((lower - mu) / sigma)
            )
        else:
            raise ValueError(f"Unknown bracket_type: {bracket_type!r}")
        
        result[contract["ticker"]] = float(prob)
    
    return result

import numpy as np
from scipy.optimize import minimize


def fit_emos(
    ensemble_means: list[float],
    ensemble_stds: list[float],
    observations: list[float],
) -> dict:
    """
    Fit EMOS parameters by minimizing total CRPS.
    
    Model: Y ~ N(a + b*mean, c + d*var)
    
    Args:
        ensemble_means: List of ensemble means for each training day.
        ensemble_stds: List of ensemble standard deviations (same length).
        observations: List of observed values (same length).
    
    Returns:
        Dict with keys 'a', 'b', 'c', 'd' and optimization metadata.
    """
    if not (len(ensemble_means) == len(ensemble_stds) == len(observations)):
        raise ValueError("All input lists must have the same length")
    
    if len(ensemble_means) < 2:
        raise ValueError(f"Need at least 2 training days, got {len(ensemble_means)}")
    
    means = np.array(ensemble_means)
    stds = np.array(ensemble_stds)
    obs = np.array(observations)
    
    def total_crps(params):
        a, b, c, d = params
        variances = c + d * stds ** 2
        # With the bounds below, variances stays positive; clamp as a numerical guard only.
        variances = np.maximum(variances, 1e-6)

        mu = a + b * means
        sigma = np.sqrt(variances)

        z = (obs - mu) / sigma
        score = sigma * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / math.sqrt(math.pi))
        return score.sum()
    
    # Initial guess: identity (no correction)
    x0 = np.array([0.0, 1.0, 1.0, 1.0])
    
    # Bounds keep c + d*var > 0 structurally: c floored above 0, d non-negative.
    bounds = [
        (None, None),   # a: any shift
        (None, None),   # b: any scale
        (1e-3, None),   # c: variance floor strictly positive
        (0.0, None),    # d: spread contributes non-negatively
    ]
    
    result = minimize(total_crps, x0, method='L-BFGS-B', bounds=bounds)
    
    if not np.all(np.isfinite(result.x)):
        raise RuntimeError(f"EMOS optimization produced non-finite params: {result.message}")

    if not result.success:
        raise RuntimeError(f"EMOS optimization failed: {result.message}")
    
    a, b, c, d = result.x

    return {
        "a": float(a),
        "b": float(b),
        "c": float(c),
        "d": float(d),
        "final_crps": float(result.fun),
        "n_iter": int(result.nit),
    }


def fit_emos_rolling(
    target_date: date,
    conn,
    *,
    window_days: int = 45,
    station_id: str = "KNYC",
    model: str = "combined",
    min_train_days: int = 30,
    init_hour: int = 12,
) -> dict | None:
    """
    Fit EMOS parameters on a trailing window of (forecast, observation) pairs
    ending one day before target_date.

    The window adapts to data availability: if observations through target_date - 1
    are not yet in the DB, the window slides back to the latest observed day.
    Days where forecast or observation data is missing are skipped, so
    n_train_days_used may be less than window_days.

    init_hour defaults to 12 for the 12Z combined workflow; pass init_hour=0
    when training on 00Z runs (e.g., the ECMWF-only market-open workflow).
    The init_hour must match the init you intend to use for prediction —
    parameters fit on 00Z statistics aren't valid for 12Z forecasts.

    Returns None when fewer than min_train_days effective days are available;
    the caller decides the fallback. On success returns the dict from fit_emos
    augmented with: train_start, train_end, n_train_days_used.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(date) FROM observations WHERE date <= %s AND station_id = %s",
            (target_date - timedelta(days=1), station_id),
        )
        row = cur.fetchone()
    train_end = row[0] if row else None
    if train_end is None:
        return None
    train_start = train_end - timedelta(days=window_days - 1)

    if model == "combined":
        models_arg = ["gefs", "ifs"]
    elif model == "combined_hrrr":
        models_arg = ["gefs", "ifs", "hrrr"]
    else:
        models_arg = [model]
    means, stds, obs, dates = collect_training_pairs(
        conn, train_start, train_end,
        station_id=station_id, models=models_arg,
        init_hour=init_hour,
    )

    if len(means) < min_train_days:
        return None

    result = fit_emos(means, stds, obs)
    result["train_start"] = dates[0]
    result["train_end"] = dates[-1]
    result["n_train_days_used"] = len(means)
    return result


def fit_emos_rolling_equal_weight(
    target_date: date,
    conn,
    *,
    window_days: int = 45,
    station_id: str = "KNYC",
    models: list[str] | None = None,
    min_train_days: int = 30,
    init_hour: int = 0,
) -> dict | None:
    """Rolling EMOS fit using equal-model weighting (vs flat member weighting).

    Calls collect_training_pairs_equal_weight, then runs the same fit_emos
    optimizer as the flat-weight version. Use for HRRR-weighting experiments.
    """
    from .aggregation import collect_training_pairs_equal_weight

    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(date) FROM observations WHERE date <= %s AND station_id = %s",
            (target_date - timedelta(days=1), station_id),
        )
        row = cur.fetchone()
    train_end = row[0] if row else None
    if train_end is None:
        return None
    train_start = train_end - timedelta(days=window_days - 1)

    means, stds, obs, dates = collect_training_pairs_equal_weight(
        conn, train_start, train_end,
        station_id=station_id, models=models, init_hour=init_hour,
    )
    if len(means) < min_train_days:
        return None

    result = fit_emos(means, stds, obs)
    result["train_start"] = dates[0]
    result["train_end"] = dates[-1]
    result["n_train_days_used"] = len(means)
    return result


def fit_emos_rolling_for_lows(
    target_date: date,
    conn,
    *,
    window_days: int = 45,
    station_id: str = "KNYC",
    model: str = "combined",
    min_train_days: int = 30,
) -> dict | None:
    """Rolling EMOS for day-ahead morning lows.

    Mirrors fit_emos_rolling but uses collect_training_pairs_for_lows. Training
    pairs are (predicted_morning_low_from_prior_day_00Z, observed_low_on_day_D).
    init_hour is implicitly 00Z (day-ahead architecture).

    Returns None when fewer than min_train_days effective days are available.
    """
    from .aggregation import collect_training_pairs_for_lows

    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(date) FROM observations WHERE date <= %s AND station_id = %s AND low_temp_f IS NOT NULL",
            (target_date - timedelta(days=1), station_id),
        )
        row = cur.fetchone()
    train_end = row[0] if row else None
    if train_end is None:
        return None
    train_start = train_end - timedelta(days=window_days - 1)

    if model == "combined":
        models_arg = ["gefs", "ifs"]
    elif model == "combined_hrrr":
        models_arg = ["gefs", "ifs", "hrrr"]
    else:
        models_arg = [model]

    means, stds, obs, dates = collect_training_pairs_for_lows(
        conn, train_start, train_end,
        station_id=station_id, models=models_arg,
    )

    if len(means) < min_train_days:
        return None

    result = fit_emos(means, stds, obs)
    result["train_start"] = dates[0]
    result["train_end"] = dates[-1]
    result["n_train_days_used"] = len(means)
    return result