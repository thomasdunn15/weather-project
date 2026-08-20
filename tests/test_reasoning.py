"""Tests for the reasoning engine: schema, retriever protocol, mocked end-to-end loop."""

from __future__ import annotations

import json

import pytest

from weather_markets.reasoning import (
    Chunk,
    MockRetriever,
    ModelsConfig,
    Matrix,
    ReasoningEngine,
    Retriever,
    Role,
)

MATRIX = Matrix.model_validate(
    {
        "name": "venue-expansion",
        "points": [
            {
                "id": "fees",
                "name": "Fees",
                "sub_points": [{"id": "fees.maker", "name": "Maker fees"}],
            },
            {"id": "liquidity", "name": "Liquidity"},
        ],
    }
)

CHUNKS = [
    Chunk(id="c1", text="ForecastEx charges half the Kalshi fee.", source="api", tags=["fees"]),
    Chunk(id="c2", text="Maker rebates exist on ForecastEx.", source="api", tags=["fees.maker"]),
    Chunk(id="c3", text="Book depth caps near 500 contracts.", source="db", tags=["liquidity"]),
]


class FakeCompleter:
    """Scripted Completer: canned debate lines + master JSON, counts per role."""

    def __init__(self, debate_script: list[str], master_json: str) -> None:
        self.debate_script = list(debate_script)
        self.master_json = master_json
        self.calls: dict[str, int] = {"specialist": 0, "debate": 0, "master": 0}

    def complete(self, prompt: str, *, role: Role, system: str | None = None) -> str:
        self.calls[role] += 1
        if role == "specialist":
            return "Findings citing [c1]."
        if role == "debate":
            return self.debate_script.pop(0) if self.debate_script else "NO_CHALLENGES"
        return self.master_json


MASTER_JSON = json.dumps(
    {
        "decision": "Expand to ForecastEx at minimal size.",
        "claims": [
            {"text": "Fees are half of Kalshi's.", "chunk_ids": ["c1"]},
            {"text": "Regulators will approve by Q4.", "chunk_ids": []},
            {"text": "Volume doubles yearly.", "chunk_ids": ["c99"]},
        ],
    }
)


def test_matrix_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate matrix id"):
        Matrix.model_validate(
            {"name": "bad", "points": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]}
        )


def test_matrix_loads_json_and_yaml(tmp_path):
    data = MATRIX.model_dump()
    (tmp_path / "m.json").write_text(json.dumps(data))
    (tmp_path / "m.yaml").write_text(
        "name: venue-expansion\npoints:\n  - id: fees\n    name: Fees\n"
    )
    assert Matrix.load(tmp_path / "m.json") == MATRIX
    assert Matrix.load(tmp_path / "m.yaml").points[0].id == "fees"


def test_mock_retriever_respects_matrix_scope():
    retriever = MockRetriever(CHUNKS)
    assert isinstance(retriever, Retriever)
    ids = {c.id for c in retriever.retrieve("anything", ["fees", "fees.maker"])}
    assert ids == {"c1", "c2"}
    assert retriever.retrieve("anything", ["nonexistent"]) == []


def test_models_config_role_lookup():
    models = ModelsConfig(master="claude-fable-5")
    assert models.for_role("master") == "claude-fable-5"
    assert models.for_role("specialist") == "claude-haiku-4-5"


def test_end_to_end_mocked_loop():
    completer = FakeCompleter(debate_script=["NO_CHALLENGES"], master_json=MASTER_JSON)
    result = ReasoningEngine(MockRetriever(CHUNKS), completer).run("Expand venues?", MATRIX)

    assert [r.point_id for r in result.reports] == ["fees", "liquidity"]
    assert result.debate_rounds == 1  # one critique pass, no challenges
    assert completer.calls == {"specialist": 2, "debate": 1, "master": 1}

    decision = result.decision
    assert decision.text.startswith("Expand to ForecastEx")
    assert [c.text for c in decision.grounded] == ["Fees are half of Kalshi's."]
    # no-evidence claim AND unknown-chunk-id claim are both flagged, not asserted
    assert {c.text for c in decision.ungrounded} == {
        "Regulators will approve by Q4.",
        "Volume doubles yearly.",
    }


def test_debate_challenges_trigger_revision_and_round_cap():
    completer = FakeCompleter(
        debate_script=["fees: cite the maker leg", "fees: still weak", "fees: never satisfied"],
        master_json=MASTER_JSON,
    )
    result = ReasoningEngine(MockRetriever(CHUNKS), completer, max_debate_rounds=2).run(
        "Expand venues?", MATRIX
    )
    assert result.debate_rounds == 2  # hard cap despite a third pending challenge
    # 2 initial investigations + 2 revisions of the challenged specialist
    assert completer.calls["specialist"] == 4
    assert len(result.debate_transcript) == 2


def test_master_bad_json_raises():
    completer = FakeCompleter(debate_script=["NO_CHALLENGES"], master_json="not json at all")
    with pytest.raises(ValueError, match="not JSON"):
        ReasoningEngine(MockRetriever(CHUNKS), completer).run("Expand venues?", MATRIX)
