import pytest
from weather_markets.evaluation import contract_resolved_yes, brier_score, evaluate_predictions

# Helper: build a contract dict
def make_contract(bracket_type, strike_low=None, strike_high=None):
    return {
        "bracket_type": bracket_type,
        "strike_low": strike_low,
        "strike_high": strike_high,
    }


# contract_resolved_yes tests

def test_greater_than_resolves_yes_when_above():
    contract = make_contract("greater_than", strike_low=70)
    assert contract_resolved_yes(71, contract) is True


def test_greater_than_resolves_no_at_boundary():
    contract = make_contract("greater_than", strike_low=70)
    assert contract_resolved_yes(70, contract) is False  # NOT greater than 70


def test_greater_than_resolves_no_when_below():
    contract = make_contract("greater_than", strike_low=70)
    assert contract_resolved_yes(65, contract) is False


def test_less_than_resolves_yes_when_below():
    contract = make_contract("less_than", strike_high=63)
    assert contract_resolved_yes(62, contract) is True


def test_less_than_resolves_no_at_boundary():
    contract = make_contract("less_than", strike_high=63)
    assert contract_resolved_yes(63, contract) is False  # NOT less than 63


def test_between_resolves_yes_at_either_boundary():
    contract = make_contract("between", strike_low=73, strike_high=74)
    assert contract_resolved_yes(73, contract) is True
    assert contract_resolved_yes(74, contract) is True


def test_between_resolves_no_outside_range():
    contract = make_contract("between", strike_low=73, strike_high=74)
    assert contract_resolved_yes(72, contract) is False
    assert contract_resolved_yes(75, contract) is False


def test_unknown_bracket_type_raises():
    contract = make_contract("sideways", strike_low=70, strike_high=80)
    with pytest.raises(ValueError, match="sideways"):
        contract_resolved_yes(70, contract)


# brier_score tests

def test_brier_perfect_prediction_yes():
    assert brier_score(1.0, True) == 0.0


def test_brier_perfect_prediction_no():
    assert brier_score(0.0, False) == 0.0


def test_brier_maximally_wrong_yes():
    assert brier_score(0.0, True) == 1.0


def test_brier_maximally_wrong_no():
    assert brier_score(1.0, False) == 1.0


def test_brier_coin_flip():
    assert brier_score(0.5, True) == 0.25
    assert brier_score(0.5, False) == 0.25


def test_brier_close_to_correct():
    # (0.7 - 1)^2 = 0.09
    assert brier_score(0.7, True) == pytest.approx(0.09)

def test_evaluate_predictions_correct():
    # If model predicted 60% yes for a contract that resolved yes,
    # Brier = (0.6 - 1)^2 = 0.16
    contracts = [{"ticker": "T", "bracket_type": "greater_than", "strike_low": 70, "strike_high": None}]
    probabilities = {"T": 0.6}
    observed_high = 75  # resolves yes
    
    scores = evaluate_predictions(probabilities, contracts, observed_high)
    
    assert scores["T"] == pytest.approx(0.16)


def test_evaluate_predictions_perfect():
    contracts = [{"ticker": "T", "bracket_type": "greater_than", "strike_low": 70, "strike_high": None}]
    probabilities = {"T": 1.0}
    observed_high = 75
    
    scores = evaluate_predictions(probabilities, contracts, observed_high)
    
    assert scores["T"] == 0.0


def test_evaluate_predictions_multiple_contracts():
    contracts = [
        {"ticker": "A", "bracket_type": "greater_than", "strike_low": 70, "strike_high": None},
        {"ticker": "B", "bracket_type": "less_than", "strike_low": None, "strike_high": 60},
    ]
    probabilities = {"A": 0.5, "B": 0.5}
    observed_high = 75  # A: resolves yes, B: resolves no
    
    scores = evaluate_predictions(probabilities, contracts, observed_high)
    
    assert scores["A"] == 0.25  # (0.5 - 1)^2
    assert scores["B"] == 0.25  # (0.5 - 0)^2