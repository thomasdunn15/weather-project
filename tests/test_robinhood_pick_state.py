""""No trade" is a claim about today's ladder. It must not stand in for "we
could not look".

At 11:41Z on 2026-09-01 the tab said "nothing cleared the 10% edge threshold"
for both cities. Nothing had been evaluated: the model for the day is fitted by
the 14:45Z paper cron, which had not run. An operator reading that would take a
missing pipeline for a quiet market — and the SAME missing model after 14:45Z
means the opposite, a cron that failed.
"""
from datetime import datetime, timedelta, timezone

from dashboard.data_forecastex import pick_state

DECISION = datetime(2026, 9, 1, 14, 45, tzinfo=timezone.utc)
BEFORE = DECISION - timedelta(hours=3)
AFTER = DECISION + timedelta(minutes=10)
PICK = [{"ticker": "UHLAX_090126_77"}]


def test_no_model_before_the_decision_time_is_pending_not_no_trade():
    assert pick_state(None, BEFORE, DECISION) == "pending"


def test_no_model_after_the_decision_time_is_an_error():
    assert pick_state(None, AFTER, DECISION) == "error"


def test_empty_list_is_a_real_no_trade_at_any_hour():
    """[] means the threshold WAS applied and nothing cleared it."""
    assert pick_state([], BEFORE, DECISION) == "no-trade"
    assert pick_state([], AFTER, DECISION) == "no-trade"


def test_picks_are_a_trade():
    assert pick_state(PICK, AFTER, DECISION) == "trade"


def test_none_and_empty_never_collapse():
    """The regression itself: these two must not produce the same state."""
    for now in (BEFORE, AFTER):
        assert pick_state(None, now, DECISION) != pick_state([], now, DECISION)
