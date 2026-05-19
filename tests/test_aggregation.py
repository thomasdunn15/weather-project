from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest

from weather_markets.aggregation import (
    compute_daily_highs,
    compute_ensemble_probabilities,
    NoForecastDataError,
    fetch_observed_high,
    fetch_contracts_for_date,
)

def make_mock_conn(rows):
    """
    Mock psycopg connection.
    
    Configures cursor().fetchall() to return rows.
    Configures cursor().fetchone() to return rows[0] if rows else None.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_cursor.fetchone.return_value = rows[0] if rows else None
    
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

def test_returns_observation_when_exists():
    conn = make_mock_conn([(73,)])  # one row, one column
    result = fetch_observed_high(date(2026, 5, 10), conn)
    assert result == 73.0


def test_returns_none_when_missing():
    conn = make_mock_conn([])  # no rows
    result = fetch_observed_high(date(2026, 12, 25), conn)
    assert result is None


def test_returns_float_type():
    conn = make_mock_conn([(73,)])
    result = fetch_observed_high(date(2026, 5, 10), conn)
    assert isinstance(result, float)

def test_fetch_contracts_returns_list_of_dicts():
    rows = [
        ("KXHIGHNY-26MAY14-T70", "greater_than", 70, None),
        ("KXHIGHNY-26MAY14-T63", "less_than", None, 63),
        ("KXHIGHNY-26MAY14-B67.5", "between", 67, 68),
    ]
    conn = make_mock_conn(rows)
    
    contracts = fetch_contracts_for_date(date(2026, 5, 14), conn)
    
    assert len(contracts) == 3
    assert contracts[0] == {
        "ticker": "KXHIGHNY-26MAY14-T70",
        "bracket_type": "greater_than",
        "strike_low": 70,
        "strike_high": None,
    }


def test_fetch_contracts_returns_empty_when_no_matches():
    conn = make_mock_conn([])
    contracts = fetch_contracts_for_date(date(2026, 12, 25), conn)
    assert contracts == []


def test_fetch_contracts_returns_all_four_keys():
    rows = [("T", "between", 67, 68)]
    conn = make_mock_conn(rows)
    
    contracts = fetch_contracts_for_date(date(2026, 5, 14), conn)
    
    assert set(contracts[0].keys()) == {"ticker", "bracket_type", "strike_low", "strike_high"}

def test_compute_daily_highs_filters_by_model():
    """If model='ifs' is passed, only ECMWF rows should be returned."""
    # Mock returns 3 rows: (member_id, tmax_f) tuples
    rows = [(1, 75.0), (2, 76.0), (3, 77.0)]
    conn = make_mock_conn(rows)
    
    result = compute_daily_highs(
        datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        date(2026, 5, 17),
        conn,
        model="ifs",
    )
    
    assert result == {1: 75.0, 2: 76.0, 3: 77.0}

def test_compute_ensemble_probabilities_accepts_list():
    """Function should accept a list of values, not just a dict."""
    contracts = [{
        "ticker": "T",
        "bracket_type": "between",
        "strike_low": 70,
        "strike_high": 71,
    }]
    
    # Three values: one in bracket, two not
    highs_as_list = [70.5, 65.0, 80.0]
    
    result = compute_ensemble_probabilities(highs_as_list, contracts)
    
    # 1 of 3 values is in [70.5, 71.5) continuous range
    assert result["T"] == pytest.approx(1/3)