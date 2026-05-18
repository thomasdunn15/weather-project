import math
import pytest
from weather_markets.emos import crps_gaussian, gaussian_to_bracket_probs, fit_emos
import numpy as np
from scipy import stats
from scipy.optimize import minimize


def test_crps_perfect_prediction_low_sigma():
    # mu = y, very narrow distribution → CRPS near 0
    score = crps_gaussian(mu=70.0, sigma=0.01, observation=70.0)
    assert score < 0.01


def test_crps_is_positive():
    score = crps_gaussian(mu=70.0, sigma=2.0, observation=72.0)
    assert score > 0


def test_crps_symmetric():
    # Same error magnitude, opposite signs → same CRPS
    high = crps_gaussian(mu=70.0, sigma=2.0, observation=72.0)
    low = crps_gaussian(mu=70.0, sigma=2.0, observation=68.0)
    assert high == pytest.approx(low)


def test_crps_increases_with_error():
    close = crps_gaussian(mu=70.0, sigma=2.0, observation=70.5)
    far = crps_gaussian(mu=70.0, sigma=2.0, observation=75.0)
    assert far > close


def test_crps_raises_on_zero_sigma():
    with pytest.raises(ValueError):
        crps_gaussian(mu=70.0, sigma=0.0, observation=72.0)


def test_crps_raises_on_negative_sigma():
    with pytest.raises(ValueError):
        crps_gaussian(mu=70.0, sigma=-1.0, observation=72.0)


def test_crps_perfect_with_finite_sigma():
    # Perfect mean, real sigma — should be approximately sigma * (2*pdf(0) - 1/sqrt(pi))
    # = sigma * (2/sqrt(2*pi) - 1/sqrt(pi))
    # = sigma * (sqrt(2/pi) - 1/sqrt(pi))
    sigma = 1.0
    expected = sigma * (math.sqrt(2/math.pi) - 1/math.sqrt(math.pi))
    score = crps_gaussian(mu=70.0, sigma=sigma, observation=70.0)
    assert score == pytest.approx(expected)

def test_gaussian_to_probs_greater_than():
    contracts = [{
        "ticker": "T",
        "bracket_type": "greater_than",
        "strike_low": 65,
        "strike_high": None,
    }]
    result = gaussian_to_bracket_probs(70.0, 2.0, contracts)
    assert result["T"] == pytest.approx(0.9878, abs=0.001)


def test_gaussian_to_probs_less_than():
    # μ=70, σ=2, contract is <60. Truth is very low.
    contracts = [{
        "ticker": "T",
        "bracket_type": "less_than",
        "strike_low": None,
        "strike_high": 60,
    }]
    result = gaussian_to_bracket_probs(70.0, 2.0, contracts)
    assert result["T"] < 0.001


def test_gaussian_to_probs_between():
    # μ=70, σ=2, bracket [70, 71]. Mode covers this.
    contracts = [{
        "ticker": "T",
        "bracket_type": "between",
        "strike_low": 70,
        "strike_high": 71,
    }]
    result = gaussian_to_bracket_probs(70.0, 2.0, contracts)
    # Bracket spans [69.5, 71.5] in continuous space — about 0.38 mass
    assert 0.3 < result["T"] < 0.5


def test_gaussian_to_probs_symmetric_mu():
    # μ exactly between two adjacent between brackets
    contracts = [
        {"ticker": "A", "bracket_type": "between", "strike_low": 68, "strike_high": 69},
        {"ticker": "B", "bracket_type": "between", "strike_low": 70, "strike_high": 71},
    ]
    # μ = 69.5 is exactly between [67.5, 69.5) and (69.5, 71.5]
    result = gaussian_to_bracket_probs(69.5, 2.0, contracts)
    assert result["A"] == pytest.approx(result["B"])


def test_gaussian_to_probs_invalid_sigma():
    with pytest.raises(ValueError):
        gaussian_to_bracket_probs(70.0, 0.0, [])


def test_gaussian_to_probs_unknown_bracket():
    contracts = [{
        "ticker": "X",
        "bracket_type": "sideways",
        "strike_low": 70,
        "strike_high": 71,
    }]
    with pytest.raises(ValueError):
        gaussian_to_bracket_probs(70.0, 2.0, contracts)


def test_gaussian_to_probs_brackets_partition_space():
    # Half-degree adjustments make adjacent brackets meet exactly.
    # Total should be very close to 1.
    contracts = [
        {"ticker": "T63", "bracket_type": "less_than", "strike_low": None, "strike_high": 63},
        {"ticker": "B63.5", "bracket_type": "between", "strike_low": 63, "strike_high": 64},
        {"ticker": "B65.5", "bracket_type": "between", "strike_low": 65, "strike_high": 66},
        {"ticker": "B67.5", "bracket_type": "between", "strike_low": 67, "strike_high": 68},
        {"ticker": "T68", "bracket_type": "greater_than", "strike_low": 68, "strike_high": None},
    ]
    result = gaussian_to_bracket_probs(65.0, 3.0, contracts)
    total = sum(result.values())
    assert total == pytest.approx(1.0)

def test_fit_emos_recovers_identity():
    np.random.seed(42)
    n = 100
    ensemble_means = np.linspace(60, 80, n).tolist()
    ensemble_stds = [3.0] * n
    observations = (np.array(ensemble_means) + np.random.normal(0, 3, n)).tolist()
    
    result = fit_emos(ensemble_means, ensemble_stds, observations)
    
    # The corrected mean for a typical input should approximately equal the input
    # (since the data is unbiased, EMOS shouldn't shift predictions much)
    test_input = 70.0
    corrected = result["a"] + result["b"] * test_input
    assert abs(corrected - test_input) < 2.0


def test_fit_emos_corrects_bias():
    # When ensemble has constant bias, EMOS should recover it
    np.random.seed(42)
    n = 50
    ensemble_means = np.linspace(60, 80, n).tolist()
    ensemble_stds = [3.0] * n
    # Add +5°F bias
    observations = (np.array(ensemble_means) - 5 + np.random.normal(0, 1, n)).tolist()
    
    result = fit_emos(ensemble_means, ensemble_stds, observations)
    
    # 'a' should be approximately -5 (with b close to 1)
    # Or 'b' could absorb some of the bias
    # Check that a + b*mean ≈ observed
    test_mean = 70
    corrected_mean = result["a"] + result["b"] * test_mean
    expected = test_mean - 5  # mean - bias
    assert abs(corrected_mean - expected) < 2  # within 2°F


def test_fit_emos_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        fit_emos([1.0, 2.0], [1.0], [1.0, 2.0])


def test_fit_emos_rejects_too_few_samples():
    with pytest.raises(ValueError):
        fit_emos([70.0], [3.0], [69.0])