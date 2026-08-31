"""Polymarket -> Kalshi bracket normalization.

RETIRED ASSERTION (was `test_pm_between_half_open`, correct until 2026-08-23):

    b = kalshi_equivalent_bracket("polymarket", "between", 92, 93)
    assert contract_resolved_yes(92, b) is True
    assert contract_resolved_yes(93, b) is False   # <- wrong

It read the gte92lt93 slug as [92, 93) = "92 only". Polymarket's own market
description says "between 92F and 93F", and the ladder steps by 2, so the upper
degree belonged to no contract at all. Kept here rather than deleted so the
pre-2026-08-23 Polymarket analysis stays interpretable — see
docs/analysis-snapshots/2026-08-23-pre-bracket-fix/.
"""
import pytest

from weather_markets.evaluation import contract_resolved_yes, kalshi_equivalent_bracket


def test_pm_between_is_an_inclusive_pair():
    b = kalshi_equivalent_bracket("polymarket", "between", 92, 93)  # "92 to 93"
    assert contract_resolved_yes(92, b) is True
    assert contract_resolved_yes(93, b) is True     # the degree the old reading dropped
    assert contract_resolved_yes(91, b) is False
    assert contract_resolved_yes(94, b) is False


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


def test_pm_and_kalshi_agree_on_the_same_strikes():
    """Same station, same day, same strikes must mean the same event.

    The bug's signature was these two disagreeing, which on 2026-08-23 put our
    own model on both sides of the identical Miami 92-93 bracket.
    """
    pm = kalshi_equivalent_bracket("polymarket", "between", 92, 93)
    kx = kalshi_equivalent_bracket("kalshi", "between", 92, 93)
    for high in range(85, 100):
        assert contract_resolved_yes(high, pm) == contract_resolved_yes(high, kx), high


@pytest.mark.parametrize("ladder", [
    [("less_than", None, 88), ("between", 88, 89), ("between", 90, 91),
     ("between", 92, 93), ("between", 94, 95), ("greater_than", 96, None)],   # KMIA
    [("less_than", None, 77), ("between", 77, 78), ("between", 79, 80),
     ("between", 81, 82), ("between", 83, 84), ("greater_than", 85, None)],   # KLAX
])
def test_a_real_pm_ladder_tiles_every_degree_exactly_once(ladder):
    """The structural invariant that makes the old reading impossible.

    A market must cover every outcome exactly once. Under [a, b) semantics the
    odd degrees fell through the gaps — this test fails loudly if that returns.
    """
    brackets = [kalshi_equivalent_bracket("polymarket", bt, lo, hi)
                for bt, lo, hi in ladder]
    for high in range(60, 115):
        hits = sum(contract_resolved_yes(high, b) for b in brackets)
        assert hits == 1, f"high={high} matched {hits} brackets, expected exactly 1"
