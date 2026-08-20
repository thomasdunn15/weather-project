"""Strategy-assess engine: corpus lint (the silent-drop guard) + mocked assess loop."""

from __future__ import annotations

import json

import pytest

from weather_markets.expansion import Candidate, VENUES
from weather_markets.expansion.scorecard import CandidateMetrics, scaling_summary
from weather_markets.expansion.strategy_retrievers import (
    STRATEGY_CORPUS,
    STRATEGY_MATRIX,
    build_strategy_retriever,
    lint_strategy_corpus,
    load_strategies,
)
from weather_markets.reasoning import Matrix, ReasoningEngine, Role


def _metrics(**over) -> CandidateMetrics:
    base = dict(
        candidate=Candidate(id="kalshi-test", venue="kalshi", kind="city", station_id="KORD"),
        venue=VENUES["kalshi"],
        series_ticker="KXHIGHTEST",
        series_title="Test high temp",
        settlement_sources=[],
        n_open=5,
        n_settled=100,
        avg_volume=6000.0,
        med_spread_cents=2.0,
        avg_open_interest=3000.0,
        underlying="daily_high_temp",
        station_known=True,
        hrrr_ok=True,
        paper_n=200,
        paper_mean_abs_edge=0.08,
        paper_span_days=90,
    )
    base.update(over)
    return CandidateMetrics(**base)


class FakeCompleter:
    """Scripted Completer: canned specialist/debate output + master JSON."""

    def __init__(self, master_json: str) -> None:
        self.master_json = master_json

    def complete(self, prompt: str, *, role: Role, system: str | None = None) -> str:
        if role == "specialist":
            return "Findings for this focus point."
        if role == "debate":
            return "NO_CHALLENGES"
        return self.master_json


def test_lint_catches_untagged_and_missing_reverify(tmp_path):
    (tmp_path / "corpus.md").write_text(
        "# Title\n\n"
        "## Good evidence section with an explicit tag and enough body text here to pass\n"
        "<!-- fp: mechanism.netfee | kind: evidence -->\n"
        "Some evidence body that is comfortably longer than eighty characters so it counts.\n\n"
        "## Untagged section that should be flagged because it carries no fp comment at all\n"
        "This section is long enough to be a real content chunk but has no fp tag anywhere.\n\n"
        "## A guardrail with no reverified verdict, which the lint must reject outright here\n"
        "<!-- fp: economics.fees | kind: guardrail -->\n"
        "A don't-rule that never got independently re-verified — must be blocked from ingest.\n"
    )
    errors = lint_strategy_corpus(tmp_path)
    assert len(errors) == 2
    assert any("missing <!-- fp" in e for e in errors)
    assert any("guardrail without reverified" in e for e in errors)


def test_real_seeded_corpus_lints_clean():
    assert lint_strategy_corpus(STRATEGY_CORPUS) == []


def test_strategies_yaml_loads_and_frames_format():
    strategies = load_strategies()
    ids = {s.id for s in strategies}
    assert {"s1-flb-harvest", "s2-benter-netfee", "s3-xvenue-arb", "s4-labor-flb-fade"} <= ids
    for s in strategies:  # every question_frame must accept the three fields
        s.question_frame.format(market="m", venue="v", avg_volume="1,000")


def test_scaling_summary_is_flagged_proxy_with_a_path():
    ceiling, path, is_proxy = scaling_summary(_metrics(avg_volume=6000.0, paper_n=200))
    assert is_proxy and "proxy" in ceiling and "assess edge" in path
    # paper data but thin book -> assess, don't claim edge
    _, thin_path, _ = scaling_summary(_metrics(avg_volume=1000.0, paper_n=200))
    assert "internal data — assess" in thin_path
    # no internal data -> probe first, never an edge claim
    _, nodata_path, _ = scaling_summary(_metrics(avg_volume=6000.0, paper_n=0))
    assert "probe" in nodata_path
    # no volume -> unknown, still a flagged proxy
    ceiling2, _, proxy2 = scaling_summary(_metrics(avg_volume=None))
    assert proxy2 and "unknown" in ceiling2


def test_assess_smoke_no_network(tmp_path):
    (tmp_path / "c.md").write_text(
        "# Corpus\n\n"
        "## Passive MM nets a positive return net of commission on favorite-side contracts\n"
        "<!-- fp: mechanism.netfee, economics.fees | kind: evidence -->\n"
        "Makers buying the favorite side earn a small positive return after commission here.\n"
    )
    master_json = json.dumps(
        {
            "decision": "Paper-first probe worthwhile; measure net-of-fee edge and flow.",
            "claims": [
                {"text": "Fees are quantified for this venue.", "chunk_ids": ["strat:kalshi-test:fees"]},
                {"text": "Regulators will approve soon.", "chunk_ids": []},
                {"text": "Volume triples next year.", "chunk_ids": ["strat:kalshi-test:nope"]},
            ],
        }
    )
    retriever = build_strategy_retriever(_metrics(), corpus_dirs=(tmp_path,))
    matrix = Matrix.load(STRATEGY_MATRIX)
    result = ReasoningEngine(retriever, FakeCompleter(master_json)).run("Backtest MM here?", matrix)

    ev_ids = {c.id for c in result.decision.evidence}
    assert [c.text for c in result.decision.grounded] == ["Fees are quantified for this venue."]
    assert all(set(cl.chunk_ids) <= ev_ids for cl in result.decision.grounded)
    # the empty-cite and unknown-id claims are flagged, never asserted
    assert {c.text for c in result.decision.ungrounded} == {
        "Regulators will approve soon.",
        "Volume triples next year.",
    }
    assert "strat:kalshi-test:fees" in ev_ids  # the market-facts leg surfaced


def test_flb_regime_chunk_measured_and_unmeasured():
    from weather_markets.expansion.strategy_retrievers import strat_market_chunks

    m = _metrics(flb_regime={"longshot_mass": 0.87, "longshot_overpricing_pp": 8.6,
                             "favorite_underpricing_pp": -2.0, "resolution_hours": 720.0,
                             "verdict": "FLB PRESENT", "n_markets": 15})
    fid = f"strat:{m.candidate.id}:flb_regime"
    fc = {c.id: c for c in strat_market_chunks(m)}[fid]
    assert "FLB PRESENT" in fc.text and "+8.6pp" in fc.text and "market_fit" in fc.tags
    # unmeasured market -> honest "unproven here" chunk, still tagged market_fit
    fc2 = {c.id: c for c in strat_market_chunks(_metrics(flb_regime=None))}[fid]
    assert "UNMEASURED" in fc2.text and "market_fit" in fc2.tags


def test_build_rejects_dirty_corpus(tmp_path):
    (tmp_path / "bad.md").write_text(
        "## An untagged content section long enough to count as a real chunk but no fp tag\n"
        "Body text that is definitely more than eighty characters so it is not skipped early.\n"
    )
    with pytest.raises(ValueError, match="lint failed"):
        build_strategy_retriever(_metrics(), corpus_dirs=(tmp_path,))
