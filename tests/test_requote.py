"""Unit tests for the 45-minute re-quote decision logic (scripts/monitor_fills).

Covers the pure decision function + per-city threshold map, including the two
guards: RUNAWAY (one re-quote per order) and DOUBLE-FILL (never re-quote an order
that already has fills). The cancel/repost orchestration is I/O and validated
separately (paper); this pins the decision rule.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import monitor_fills as mf  # noqa: E402


def test_thresholds_per_city():
    assert mf.requote_threshold_for("KXHIGHCHI-26JUN21-B71.5") == 0.25   # KORD
    assert mf.requote_threshold_for("KXHIGHMIA-26JUN21-B83.5") == 0.10   # KMIA
    assert mf.requote_threshold_for("KXHIGHTDAL-26JUN21-T93") == 0.25    # Dallas
    assert mf.requote_threshold_for("KXHIGHWEIRD-26JUN21-B1") == mf.DEFAULT_REQUOTE_Y


def _d(edge, ticker="KXHIGHCHI-26JUN21-B71.5", elapsed=50.0, already=False, filled=0):
    return mf._requote_decision(edge, ticker, elapsed, already, filled)


def test_requote_when_elapsed_and_edge_clears_Y():
    # KORD Y=0.25: edge 0.30 ≥ 0.25, 50m elapsed, fresh, unfilled → cross
    assert _d(0.30) == "requote_cross"
    # sign-agnostic on edge
    assert _d(-0.30) == "requote_cross"
    # KMIA Y=0.10: edge 0.12 clears
    assert _d(0.12, ticker="KXHIGHMIA-26JUN21-B83.5") == "requote_cross"


def test_leave_expire_when_edge_below_Y():
    assert _d(0.20) == "leave_expire"                                   # KORD 0.20 < 0.25
    assert _d(0.08, ticker="KXHIGHMIA-26JUN21-B83.5") == "leave_expire"  # KMIA 0.08 < 0.10


def test_not_elapsed_skips():
    assert _d(0.40, elapsed=44.9) == "skip_not_elapsed"
    assert _d(0.40, elapsed=45.0) == "requote_cross"   # boundary: >= 45m acts


def test_runaway_guard_one_requote_per_order():
    # Already re-quoted once → never again, even though otherwise eligible.
    assert _d(0.40, already=True) == "skip_already"


def test_double_fill_guard_skips_partials():
    # Any fills present → do not cancel/re-quote (would risk a second position).
    assert _d(0.40, filled=1) == "skip_partial"
    assert _d(0.40, filled=500) == "skip_partial"


def test_guard_precedence():
    # already-requoted beats partial beats not-elapsed beats edge.
    assert _d(0.40, already=True, filled=10, elapsed=10) == "skip_already"
    assert _d(0.40, filled=10, elapsed=10) == "skip_partial"
    assert _d(0.40, elapsed=10) == "skip_not_elapsed"
