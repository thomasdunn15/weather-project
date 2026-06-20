"""Unit tests for the bracket-edge Brier scoring added to the offline
forecast-skill harness (scripts/analysis/forecast_model_skill.py).

The harness turns the rolling-EMOS calibrated Gaussian into per-bracket
probabilities on the SAME production Kalshi bracket set the backtest uses, then
Brier-scores them against the realized bracket. These tests pin the two
properties that make that number trustworthy, with no DB needed:

  - a (near-)perfect forecast scores Brier ~= 0, and
  - the per-day bracket probabilities sum to ~1 (the brackets partition the
    integer line, so model mass is conserved).

Run: uv run pytest tests/test_forecast_model_skill.py
"""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "analysis"
sys.path.insert(0, str(SCRIPTS_DIR))

import forecast_model_skill as fms  # noqa: E402


def partition_brackets():
    """A complete production-style Kalshi partition of the integer line:
    less_than(70) | [70,71] [72,73] [74,75] [76,77] [78,79] | greater_than(79).
    Covers <=69, 70..79, >=80 with no gaps/overlaps."""
    return [
        {"ticker": "LT70", "bracket_type": "less_than", "strike_low": None, "strike_high": 70},
        {"ticker": "B70_71", "bracket_type": "between", "strike_low": 70, "strike_high": 71},
        {"ticker": "B72_73", "bracket_type": "between", "strike_low": 72, "strike_high": 73},
        {"ticker": "B74_75", "bracket_type": "between", "strike_low": 74, "strike_high": 75},
        {"ticker": "B76_77", "bracket_type": "between", "strike_low": 76, "strike_high": 77},
        {"ticker": "B78_79", "bracket_type": "between", "strike_low": 78, "strike_high": 79},
        {"ticker": "GT79", "bracket_type": "greater_than", "strike_low": 79, "strike_high": None},
    ]


def test_perfect_forecast_scores_near_zero_brier():
    contracts = partition_brackets()
    observed = 75  # lands squarely in [74,75]
    result = fms.score_day_brackets(mu=75.0, sigma=0.01, contracts=contracts, observed_high=observed)
    # Every bracket's Brier ~= 0: the realized bracket has p~=1, the rest p~=0.
    assert max(result["briers"]) < 1e-6


def test_bracket_probs_sum_to_one():
    contracts = partition_brackets()
    # Holds for any Gaussian because the brackets tile the integer line.
    for mu, sigma in [(75.0, 3.0), (60.0, 5.0), (90.0, 2.0)]:
        result = fms.score_day_brackets(mu=mu, sigma=sigma, contracts=contracts, observed_high=75)
        assert result["prob_sum"] == pytest.approx(1.0, abs=1e-9)


def test_exactly_one_bracket_resolves_yes():
    contracts = partition_brackets()
    result = fms.score_day_brackets(mu=75.0, sigma=3.0, contracts=contracts, observed_high=75)
    assert sum(result["resolved_yes"]) == 1


def test_confident_wrong_forecast_scores_near_one_on_two_brackets():
    # mu far above the realized 60: the model puts ~all mass on >=80 (a NO) and
    # ~none on the realized <=69 bracket (a YES) -> those two each ~= 1.
    contracts = partition_brackets()
    result = fms.score_day_brackets(mu=85.0, sigma=0.5, contracts=contracts, observed_high=60)
    assert max(result["briers"]) > 0.99
