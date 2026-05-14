from datetime import datetime, date, timezone
from unittest.mock import MagicMock

import pytest

from weather_markets.aggregation import compute_daily_highs, NoForecastDataError

def make_mock_conn(fetchall_returns):
    """Create a mock psycopg connection where cursor().fetchall() returns the given rows."""
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
    precise_value = 68.524476318359375  # Real value from your data
    conn = make_mock_conn([(0, precise_value)])
    
    highs = compute_daily_highs(
        init_time=datetime(2026, 5, 13, 12, tzinfo=timezone.utc),
        target_date=date(2026, 5, 14),
        conn=conn,
    )
    
    assert highs[0] == precise_value  # Exact equality