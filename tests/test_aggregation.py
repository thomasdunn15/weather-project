from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest

from weather_markets.aggregation import (
    compute_daily_highs,
    compute_ensemble_probabilities,
    NoForecastDataError,
)

def make_mock_conn(fetchall_returns):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = fetchall_returns
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn

def test_returns_dict_of_member_to_high():
    conn = make_mock_conn([(0, 68.5), (1, 67.2)])
    highs = compute_daily_highs(
        init_time=datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        target_date=date(2026, 5, 14),
        conn=conn,
    )
    assert highs == {0: 68.5, 1: 67.2}


def test_raises_on_empty():
    conn = make_mock_conn([])
    with pytest.raises(NoForecastDataError):
        compute_daily_highs(
            init_time=datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
            target_date=date(2026, 5, 14),
            conn=conn,
        )

def test_error_message_includes_inputs():
    conn = make_mock_conn([])
    with pytest.raises(NoForecastDataError, match="2026-05-14"):
        compute_daily_highs(
            init_time=datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
            target_date=date(2026, 5, 14),
            conn=conn,
        )

def test_handles_31_members():
    rows = [(i, 70.0 + i * 0.1) for i in range(31)]
    conn = make_mock_conn(rows)
    
    highs = compute_daily_highs(
        init_time=datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        target_date=date(2026, 5, 14),
        conn=conn,
    )
    
    assert len(highs) == 31
    assert 0 in highs
    assert 30 in highs
    assert highs[0] == 70.0
    assert highs[30] == 73.0

def test_preserves_float_precision():
    precise_value = 68.524476318359375  
    conn = make_mock_conn([(0, precise_value)])
    
    highs = compute_daily_highs(
        init_time=datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        target_date=date(2026, 5, 14),
        conn=conn,
    )
    
    assert highs[0] == precise_value 

def test_all_above_threshold_gives_prob_one():
    highs = {0: 80.0, 1: 81.0, 2: 79.5}  # all > 70
    contracts = [
        {"ticker": "T70", "bracket_type": "greater_than", 
         "strike_low": 70, "strike_high": None}
    ]
    probs = compute_ensemble_probabilities(highs, contracts)
    assert probs["T70"] == 1.0

def test_greater_than_with_mixed_highs():
    highs = {0: 65, 1: 70, 2: 71, 3: 75}  # 2 of 4 are >= 71
    contracts = [{
        "ticker": "T70", "bracket_type": "greater_than",
        "strike_low": 70, "strike_high": None
    }]
    probs = compute_ensemble_probabilities(highs, contracts)
    assert probs["T70"] == 0.5

def test_less_than_basic():
    highs = {0: 60.0, 1: 62.0, 2: 65.0, 3: 70.0}  # 2 of 4 are < 63
    contracts = [{
        "ticker": "T63", "bracket_type": "less_than",
        "strike_low": None, "strike_high": 63
    }]
    probs = compute_ensemble_probabilities(highs, contracts)
    assert probs["T63"] == 0.5


def test_between_basic():
    highs = {0: 72.0, 1: 73.5, 2: 74.0, 3: 75.0}  # 73 and 74 → 73.5 and 74.0 count
    contracts = [{
        "ticker": "B73.5", "bracket_type": "between",
        "strike_low": 73, "strike_high": 74
    }]
    probs = compute_ensemble_probabilities(highs, contracts)
    assert probs["B73.5"] == 0.5


def test_unknown_bracket_type_raises():
    highs = {0: 70.0}
    contracts = [{
        "ticker": "X", "bracket_type": "sideways",  # invalid
        "strike_low": 70, "strike_high": 71
    }]
    with pytest.raises(ValueError, match="sideways"):
        compute_ensemble_probabilities(highs, contracts)


def test_empty_highs_raises():
    with pytest.raises(ValueError, match="empty"):
        compute_ensemble_probabilities({}, [])


def test_empty_contracts_returns_empty_dict():
    highs = {0: 70.0, 1: 72.0}
    probs = compute_ensemble_probabilities(highs, [])
    assert probs == {}