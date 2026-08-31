"""Tests for scripts/live_signals_terminal.py — the read-only signals monitor.

Three things must hold or the monitor is actively misleading:
  1. a bracket maps to the probability the traders use (PM inclusive pairs),
  2. a signal appears/disappears as its edge crosses the venue threshold,
  3. a PLACED row survives its edge dropping below that threshold.

Run: uv run pytest tests/test_live_signals_terminal.py
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import live_signals_terminal as lst   # noqa: E402
import live_trade_polymarket as pm    # noqa: E402
from weather_markets.emos import gaussian_to_bracket_probs      # noqa: E402
from weather_markets.evaluation import kalshi_equivalent_bracket  # noqa: E402


# ---------------------------------------------------------------------------
# 1. bracket -> probability
# ---------------------------------------------------------------------------
def test_pm_between_bracket_prices_the_inclusive_pair():
    """`gte92lt93` is "92 to 93", so its probability must equal Kalshi B92.5's.

    Reading it as [92, 93) roughly halves model_p and can invert the side —
    that is the 2026-08-23 bug that put us on both sides of one Miami bracket.
    """
    mu, sigma = 92.4, 1.6
    pm_b = kalshi_equivalent_bracket("polymarket", "between", 92, 93) | {"ticker": "pm"}
    kalshi_b = kalshi_equivalent_bracket("kalshi", "between", 92, 93) | {"ticker": "k"}
    half_open = {"ticker": "bug", "bracket_type": "between",
                 "strike_low": 92, "strike_high": 92}   # the old, wrong reading
    p = gaussian_to_bracket_probs(mu, sigma, [pm_b, kalshi_b, half_open])
    assert p["pm"] == p["k"]
    assert p["pm"] > 1.7 * p["bug"]


def test_pm_tails_still_map_onto_kalshi_rules():
    b = kalshi_equivalent_bracket("polymarket", "greater_than", 95, None)
    assert b["strike_low"] == 94        # PM T >= 95 == Kalshi T > 94
    assert kalshi_equivalent_bracket("polymarket", "less_than", None, 70)["strike_high"] == 70


def test_bracket_label():
    assert lst.bracket_label("between", 92, 93) == "92-93"
    assert lst.bracket_label("greater_than", 95, None) == ">95"
    assert lst.bracket_label("less_than", None, 70) == "<70"


# ---------------------------------------------------------------------------
# 2. threshold transitions — a signal appears when it clears, vanishes when it doesn't
# ---------------------------------------------------------------------------
def _pm_row(p_model):
    """One Polymarket quote at mid 0.50 through the trader's own gate."""
    sigs = pm.choose_signals([{"ticker": "tc-x", "bid": 49, "ask": 51, "p_model": p_model}])
    return [lst.Row(venue="polymarket", city="KMIA", contract=s["ticker"], label="92-93",
                    side="YES" if s["intent"].endswith("LONG") else "NO",
                    model_p=s["p_model"], market_p=s["mid"], edge=s["edge"],
                    threshold=pm.EDGE_THRESHOLD, entry=s["entry"], status="LIVE")
            for s in sigs]


def test_signal_appears_only_once_it_clears_the_threshold():
    below = _pm_row(0.50 + pm.EDGE_THRESHOLD - 0.01)
    above = _pm_row(0.50 + pm.EDGE_THRESHOLD + 0.01)
    assert lst.merge(below, []) == []
    assert [r.contract for r in lst.merge(above, [])] == ["tc-x"]


def test_signal_disappears_when_the_edge_decays_and_nothing_was_placed():
    assert lst.merge(_pm_row(0.80), []) != []
    assert lst.merge(_pm_row(0.55), []) == []       # edge 0.05 < 0.25 -> gone


def test_merge_orders_by_absolute_edge_with_pins_first():
    live = [lst.Row("kalshi", "KMIA", "b", "1-2", "YES", 0.5, 0.2, 0.30, 0.10, 20, "LIVE"),
            lst.Row("kalshi", "KMIA", "c", "3-4", "NO", 0.1, 0.5, -0.40, 0.10, 50, "LIVE")]
    pin = [lst.Row("kalshi", "KMIA", "a", "5-6", "YES", 0.6, 0.5, 0.10, None, 50, "FILLED")]
    assert [r.contract for r in lst.merge(live, pin)] == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# 3. pinning — the whole point of the tool
# ---------------------------------------------------------------------------
def _placed(edge_at_entry=0.30, status="PLACED", detail="unreconciled"):
    # threshold=None: the trade tables record no signal_source, so a pinned row
    # cannot say which rule fired. merge() fills it in only from a live signal.
    return lst.Row(venue="polymarket", city="KMIA", contract="tc-x", label="92-93",
                   side="YES", model_p=0.80, market_p=0.50, edge=edge_at_entry,
                   threshold=None, entry=51, status=status, detail=detail)


def test_placed_row_survives_its_edge_dropping_below_threshold():
    gone = _pm_row(0.55)                       # edge 0.05, no longer a signal
    assert gone == []
    out = lst.merge(gone, [_placed()])
    assert [(r.contract, r.status) for r in out] == [("tc-x", "PLACED")]
    assert out[0].edge == 0.30                 # falls back to the entry-time numbers
    assert out[0].quoted_at is None            # rendered "at entry", not as a live quote
    assert out[0].threshold is None            # rendered "—", never a guessed number


def test_placed_row_adopts_the_current_numbers_while_still_firing():
    live = _pm_row(0.85)                       # edge +0.35, same contract and side
    out = lst.merge(live, [_placed()])
    assert len(out) == 1 and out[0].status == "PLACED"
    assert out[0].edge == live[0].edge and out[0].edge != 0.30
    assert out[0].threshold == pm.EDGE_THRESHOLD   # recovered from the live signal


def test_a_side_flip_shows_both_rows_rather_than_overwriting():
    """We hold YES; the model now says NO on the same contract. Show both."""
    live = _pm_row(0.10)                       # edge -0.40 -> NO
    assert live[0].side == "NO"
    out = lst.merge(live, [_placed()])
    assert sorted(r.side for r in out) == ["NO", "YES"]


def test_fill_count_zero_reads_unreconciled_not_no_fill():
    assert lst._fill_status(0, None) == ("PLACED", "unreconciled")
    assert lst._fill_status(0, None, "pending") == ("PLACED", "unreconciled")
    assert lst._fill_status(0, None, "unfilled") == ("PLACED", "unfilled")
    assert lst._fill_status(111, 59.0, "partial_resting") == ("FILLED", "111 @ 59c (partial_resting)")


# ---------------------------------------------------------------------------
# read-only guard
# ---------------------------------------------------------------------------
def test_the_monitor_cannot_touch_an_order():
    src = (_ROOT / "scripts" / "live_signals_terminal.py").read_text()
    body = src.split('"""', 2)[2]              # skip the module docstring, which names them
    for forbidden in (r"create_order", r"place_order", r"submit_order", r"\.reply\(",
                      r"KalshiClient\(", r"PolymarketClient\(", r"IBKRClient\(",
                      r"\bDELETE\b", r"\bINSERT\b", r"\bUPDATE\b"):
        assert not re.search(forbidden, body), f"{forbidden} must not appear in the monitor"
