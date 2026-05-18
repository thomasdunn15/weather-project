import math
from scipy import stats


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
        # Ensure positive variance
        variances = c + d * stds ** 2
        if np.any(variances <= 0):
            return 1e10  # huge penalty
        
        mu = a + b * means
        sigma = np.sqrt(variances)
        
        # Vectorized CRPS over all days
        z = (obs - mu) / sigma
        # ... CRPS formula ...
        score = sigma * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / math.sqrt(math.pi))
        return score.sum()
    
    # Initial guess: identity (no correction)
    x0 = np.array([0.0, 1.0, 0.0, 1.0])
    
    result = minimize(total_crps, x0, method='L-BFGS-B')
    
    if not result.success:
        raise RuntimeError(f"EMOS optimization failed: {result.message}")
    
    a, b, c, d = result.x
    print(result)
    return {
        "a": float(a),
        "b": float(b),
        "c": float(c),
        "d": float(d),
        "final_crps": float(result.fun),
        "n_iter": int(result.nit),
    }