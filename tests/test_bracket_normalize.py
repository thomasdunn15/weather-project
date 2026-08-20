"""Polymarket [lo,hi) -> Kalshi-inclusive bracket normalization (the lows-bug class)."""
from weather_markets.evaluation import contract_resolved_yes, kalshi_equivalent_bracket


def test_pm_between_half_open():
    b = kalshi_equivalent_bracket("polymarket", "between", 92, 93)  # gte92lt93 = exactly 92
    assert contract_resolved_yes(92, b) is True
    assert contract_resolved_yes(93, b) is False


def test_pm_gte_maps_to_strictly_above():
    b = kalshi_equivalent_bracket("polymarket", "greater_than", 96, None)  # T >= 96
    assert contract_resolved_yes(96, b) is True
    assert contract_resolved_yes(95, b) is False


def test_pm_lt_unchanged_and_kalshi_identity():
    b = kalshi_equivalent_bracket("polymarket", "less_than", None, 88)  # T < 88
    assert contract_resolved_yes(87, b) is True
    assert contract_resolved_yes(88, b) is False
    k = kalshi_equivalent_bracket("kalshi", "between", 92, 93)  # inclusive both ends
    assert contract_resolved_yes(93, k) is True
