"""Tests for the ops copilot: pure chunk builders (no DB) + a mocked
end-to-end digest run, mirroring tests/test_reasoning.py and
tests/test_expansion.py's fetch/render split."""
from __future__ import annotations

import json

from weather_markets.copilot.digest import DIGEST_QUESTION_TEMPLATE, MATRIX_PATH, render_digest
from weather_markets.copilot.metrics import (
    CalibrationMetrics,
    ConfigDriftMetrics,
    DataHealthMetrics,
    ExecutionMetrics,
    RegimeMetrics,
)
from weather_markets.copilot.retrievers import (
    build_retriever,
    calibration_chunks,
    config_drift_chunks,
    data_health_chunks,
    execution_chunks,
    regime_chunks,
    settlement_chunks,
)
from weather_markets.reasoning import Matrix, ReasoningEngine, Role


def test_calibration_chunks_skips_thin_history():
    metrics = [
        CalibrationMetrics(station_id="KORD", n_recent=2, brier_recent=0.1, n_prior=1, brier_prior=0.2),
        CalibrationMetrics(station_id="KMIA", n_recent=20, brier_recent=0.30, n_prior=15, brier_prior=0.12),
    ]
    chunks = calibration_chunks(metrics)
    assert [c.id for c in chunks] == ["calib:KMIA"]
    assert chunks[0].tags == ["calibration_drift", "calibration_drift.brier"]
    assert "0.3" in chunks[0].text and "0.12" in chunks[0].text


def test_regime_chunks_emit_error_and_edge_separately():
    metrics = [
        RegimeMetrics(
            station_id="KDFW", n_error_recent=5, forecast_error_recent=3.2, forecast_error_prior=2.1,
            n_edge_recent=5, abs_edge_recent=0.05, abs_edge_prior=0.20,
        ),
    ]
    chunks = regime_chunks(metrics)
    ids = {c.id for c in chunks}
    assert ids == {"regime:KDFW:error", "regime:KDFW:edge"}


def test_execution_chunks_flags_adverse_selection_only_when_crossed():
    metrics = [
        ExecutionMetrics(
            station_id="KPHX", n_recent=10, fill_rate_recent=0.9, fill_rate_prior=0.95,
            n_crossed_recent=0, avg_cross_over_limit_cents_recent=None, n_rejected_or_expired_recent=1,
        ),
    ]
    chunks = execution_chunks(metrics)
    assert [c.id for c in chunks] == ["exec:KPHX:fill"]


def test_config_drift_chunks_include_rationale_only_when_doc_found():
    metrics = [
        ConfigDriftMetrics(station_id="KORD", n_days=10, daily_pnl_dollars=[1.0, -2.0], naive_sharpe=-0.7,
                            doc_text="[docs/decisions/x.md]\nrationale text"),
        ConfigDriftMetrics(station_id="KSEA", n_days=3, daily_pnl_dollars=[0.5], naive_sharpe=None, doc_text=""),
    ]
    chunks = config_drift_chunks(metrics)
    ids = {c.id for c in chunks}
    assert ids == {"config:KORD:pnl", "config:KORD:rationale", "config:KSEA:pnl"}


def test_data_health_chunks_flag_empty_equity_table():
    m = DataHealthMetrics(
        forecast_max_init={"gefs": None}, observation_days_behind={"KORD": 1},
        price_snapshot_age_minutes=5.0, equity_snapshot_date=None,
        equity_snapshot_age_days=None, equity_identity_gap_dollars=None,
    )
    chunks = data_health_chunks(m)
    equity = next(c for c in chunks if c.id == "health:equity")
    assert "EMPTY" in equity.text
    forecasts = next(c for c in chunks if c.id == "health:forecasts")
    assert "NONE INGESTED" in forecasts.text


class _FakeKalshi:
    def __init__(self, pages):
        self._pages = list(pages)

    def get_settlements(self, cursor=None):
        return self._pages.pop(0) if self._pages else {"settlements": []}


def test_settlement_chunks_maps_ticker_prefix_to_city_and_nets_pnl():
    kalshi = _FakeKalshi([
        {
            "settlements": [
                {"ticker": "KXHIGHCHI-26JUL07-B87.5", "revenue": 10000, "yes_total_cost_dollars": 30.0,
                 "no_total_cost_dollars": 0.0, "fee_cost": 2.5, "settled_time": "2026-07-20T00:00:00Z"},
                {"ticker": "KXHIGHUNKNOWN-1", "revenue": 500, "yes_total_cost_dollars": 1.0,
                 "no_total_cost_dollars": 0.0, "fee_cost": 0.1, "settled_time": "2026-07-20T00:00:00Z"},
            ],
            "cursor": None,
        },
    ])
    chunks = settlement_chunks(kalshi, days=45)
    assert len(chunks) == 1
    assert chunks[0].id == "settle:Chicago"
    assert "67.50" in chunks[0].text  # 100 - 30 - 2.5


def test_build_retriever_caps_evidence_and_scopes_by_matrix():
    from weather_markets.reasoning import Chunk

    chunks = [Chunk(id=f"c{i}", text="x", source="s", tags=["data_health"]) for i in range(5)]
    retriever = build_retriever(chunks)
    assert len(retriever.retrieve("anything", ["data_health"])) == 5
    assert retriever.retrieve("anything", ["nonexistent"]) == []


class _FakeCompleter:
    def __init__(self):
        self.seen_roles = []

    def complete(self, prompt: str, *, role: Role, system=None) -> str:
        self.seen_roles.append(role)
        if role == "specialist":
            return "Findings citing [health:equity]."
        if role == "debate":
            return "NO_CHALLENGES"
        return json.dumps({
            "decision": "Everything nominal today.",
            "claims": [{"text": "Equity reconciliation ties out.", "chunk_ids": ["health:equity"]}],
        })


def test_digest_end_to_end_with_scripted_completer_and_render():
    from weather_markets.reasoning import Chunk, MockRetriever

    matrix = Matrix.load(MATRIX_PATH)
    chunks = [
        Chunk(id="health:equity", text="Reconciliation ties out.", source="account_equity_snapshots",
              tags=["data_health", "data_health.account"]),
    ]
    completer = _FakeCompleter()
    result = ReasoningEngine(MockRetriever(chunks), completer).run(
        DIGEST_QUESTION_TEMPLATE.format(today="2026-07-22"), matrix
    )
    assert completer.seen_roles.count("specialist") == len(matrix.points)
    text = render_digest(result)
    assert "Operator Digest" in text
    assert "never places or adjusts trades" in text
    assert "Everything nominal today." in text
