"""Tests for the agent-advisor experiment layer (reasoning/advisor.py).

The guardrails under test are the ones that keep real money safe:
  - live gate: city not in ADVISOR_LIVE_CITIES -> baseline unchanged
  - fail-safe: ANY engine/parse error -> baseline unchanged
  - bounded actions: unknown tickers dropped, multipliers clamped
  - apply semantics: keep/resize/skip/flip, input never mutated
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from weather_markets.reasoning import Chunk
from weather_markets.reasoning.advisor import (
    ADVISOR_LIVE_CITIES,
    MATRIX,
    MAX_SIZE_MULTIPLIER,
    AdvisorError,
    AdvisorProposal,
    ScopedRetriever,
    SignalAdjustment,
    advise_signals_for_live,
    apply_adjustments,
    flip_signal,
    parse_adjustments,
    propose,
)

TODAY = date(2026, 7, 22)

CFG = {
    "city_name": "Testville",
    "models": ["gefs", "ifs"],
    "paper_model_source": "EMOS combined 00Z Testville (rolling 45d)",
    "live_model_source_tag": "EMOS combined TEST [LIVE]",
    "decision_hour": 15, "decision_minute": 0,
    "edge_threshold": 0.25, "blend_edge_threshold": 0.10,
    "unit_contracts": 100,
}


def make_signal(ticker="KXHIGHTEST-26JUL22-B85.5", side="yes", **over) -> dict:
    s = {
        "ticker": ticker, "side": side, "limit_price": 40, "cross_price": 41,
        "model_p": 0.55, "blend_p": None, "raw_edge": 0.30, "blend_edge": None,
        "signal_source": "raw", "exec_path": "post_inside_spread",
        "market_mid": 0.25, "edge": 0.30, "p_win": 0.55, "post_only": True,
        "yes_bid": 39, "yes_ask": 41, "market_snapshot_at": None,
        "ensemble_mean": 84.2, "ensemble_std": 2.1, "emos_mu": 85.0, "emos_sigma": 2.4,
    }
    s.update(over)
    return s


def proposal(**adjustments) -> AdvisorProposal:
    return AdvisorProposal(
        city="KTST", target_date=TODAY,
        adjustments={t: SignalAdjustment(ticker=t, **kw) for t, kw in adjustments.items()},
    )


# ---------------------------------------------------------------------------
# parse_adjustments
# ---------------------------------------------------------------------------

class TestParseAdjustments:
    def test_parses_clamps_and_drops_unknown_tickers(self):
        text = json.dumps({"adjustments": [
            {"ticker": "T1", "action": "resize", "size_multiplier": 99.0},
            {"ticker": "T2", "action": "skip", "size_multiplier": 1.0},
            {"ticker": "NOT-A-BASELINE-SIGNAL", "action": "flip"},
        ]})
        out = parse_adjustments(text, known_tickers={"T1", "T2"})
        assert set(out) == {"T1", "T2"}  # unknown ticker dropped
        assert out["T1"].size_multiplier == MAX_SIZE_MULTIPLIER  # clamped
        assert out["T2"].size_multiplier == 0.0  # skip forces 0

    def test_keep_forces_multiplier_one(self):
        text = json.dumps({"adjustments": [
            {"ticker": "T1", "action": "keep", "size_multiplier": 0.2}]})
        assert parse_adjustments(text, {"T1"})["T1"].size_multiplier == 1.0

    def test_json_embedded_in_prose_is_found(self):
        text = 'After weighing the evidence: {"adjustments": []} — no changes.'
        assert parse_adjustments(text, {"T1"}) == {}

    def test_no_json_raises(self):
        with pytest.raises(AdvisorError, match="no JSON"):
            parse_adjustments("I would keep everything as-is.", {"T1"})

    def test_bad_action_raises(self):
        text = json.dumps({"adjustments": [{"ticker": "T1", "action": "yolo"}]})
        with pytest.raises(AdvisorError, match="validation"):
            parse_adjustments(text, {"T1"})


# ---------------------------------------------------------------------------
# apply_adjustments / flip_signal
# ---------------------------------------------------------------------------

class TestApply:
    def test_no_adjustments_is_identity_and_does_not_mutate(self):
        signals = [make_signal()]
        out = apply_adjustments(signals, proposal())
        assert out == signals
        assert out[0] is not signals[0]  # copies, not aliases
        assert "agent_multiplier" not in out[0]  # baseline path stays byte-for-byte

    def test_skip_drops_signal(self):
        s = make_signal()
        assert apply_adjustments([s], proposal(**{s["ticker"]: {"action": "skip"}})) == []

    def test_resize_sets_multiplier(self):
        s = make_signal()
        out = apply_adjustments(
            [s], proposal(**{s["ticker"]: {"action": "resize", "size_multiplier": 0.5}}))
        assert out[0]["agent_multiplier"] == 0.5
        assert out[0]["side"] == s["side"]

    def test_flip_yes_to_no_uses_no_cost_convention(self):
        s = make_signal(side="yes", yes_bid=39, yes_ask=41)
        flipped = flip_signal(s)
        assert flipped["side"] == "no"
        assert flipped["cross_price"] == 100 - 39  # NO cost = 100 - YES bid
        assert flipped["limit_price"] == flipped["cross_price"]
        assert flipped["post_only"] is False  # flips execute as takers
        assert flipped["p_win"] == pytest.approx(1 - s["p_win"])
        assert s["side"] == "yes"  # input not mutated

    def test_flip_no_to_yes(self):
        s = make_signal(side="no", cross_price=61, p_win=0.45)
        flipped = flip_signal(s)
        assert flipped["side"] == "yes"
        assert flipped["cross_price"] == s["yes_ask"]


# ---------------------------------------------------------------------------
# propose (engine end-to-end with fakes) + retriever scoping
# ---------------------------------------------------------------------------

class FakeCompleter:
    def __init__(self, master_decision: str) -> None:
        self.master_decision = master_decision

    def complete(self, prompt, *, role, system=None):
        if role == "specialist":
            return "Findings citing [sig-1]."
        if role == "debate":
            return "NO_CHALLENGES"
        return json.dumps({"decision": self.master_decision, "claims": []})


def fake_chunks() -> list[Chunk]:
    return [
        Chunk(id="sig-1", text="signal ctx", source="live_signal", tags=["market", "calibration"]),
        Chunk(id="exe-1", text="exec ctx", source="live_signal", tags=["execution"]),
        Chunk(id="reg-today", text="regime ctx", source="live_signal", tags=["regime"]),
    ]


class TestPropose:
    def test_end_to_end_with_fake_completer(self):
        s = make_signal()
        decision = json.dumps({"adjustments": [
            {"ticker": s["ticker"], "action": "resize", "size_multiplier": 0.5, "why": "thin book"}]})
        p = propose("KTST", CFG, [s], TODAY, FakeCompleter(decision), fake_chunks())
        assert p.adjustments[s["ticker"]].size_multiplier == 0.5
        assert p.debate_rounds == 1

    def test_prose_master_output_raises_advisor_error(self):
        with pytest.raises(AdvisorError):
            propose("KTST", CFG, [make_signal()], TODAY,
                    FakeCompleter("keep everything, looks fine"), fake_chunks())

    def test_scoped_retriever_filters_by_matrix_slice(self):
        r = ScopedRetriever(fake_chunks())
        assert {c.id for c in r.retrieve("q", ["execution"])} == {"exe-1"}
        assert r.retrieve("q", ["nonexistent"]) == []
        # every matrix point id resolves to at least an empty (never error) slice
        for point in MATRIX.points:
            r.retrieve("q", MATRIX.scope_for(point))


# ---------------------------------------------------------------------------
# The live wrapper: gates + fail-safe
# ---------------------------------------------------------------------------

class TestLiveWrapper:
    def test_city_not_in_live_set_returns_baseline_without_any_io(self):
        assert "KTST" not in ADVISOR_LIVE_CITIES  # empty until operator override
        signals = [make_signal()]
        # conn=None: if the gate leaked past, build_chunks would blow up on None
        out = advise_signals_for_live("KTST", CFG, signals, conn=None, today=TODAY)
        assert out is signals

    def test_any_internal_error_returns_baseline(self, monkeypatch):
        import weather_markets.reasoning.advisor as adv
        monkeypatch.setattr(adv, "ADVISOR_LIVE_CITIES", frozenset({"KTST"}))
        monkeypatch.setattr(adv, "build_chunks",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        signals = [make_signal()]
        out = adv.advise_signals_for_live("KTST", CFG, signals, conn=None, today=TODAY)
        assert out is signals

    def test_live_set_is_empty_by_default(self):
        assert ADVISOR_LIVE_CITIES == frozenset()
