"""Checks for the B1 breadth scout: pure parts only (no DB, no network)."""

from pathlib import Path

import pytest

from weather_markets.expansion.bootstrap import bootstrap
from weather_markets.expansion.candidates import DEFAULT_REGISTRY, Candidate, load_candidates
from weather_markets.expansion.catalog import VENUES, ForecastExCatalog, fee_cents
from weather_markets.expansion.retrievers import CompositeRetriever, catalog_chunks, corpus_chunks, history_chunks
from weather_markets.expansion.scorecard import CandidateMetrics, score
from weather_markets.reasoning import Matrix, MockRetriever

MATRIX = Matrix.load(Path(__file__).resolve().parents[1] / "docs" / "matrices" / "breadth_expansion.json")


def _metrics(**over) -> CandidateMetrics:
    base = dict(
        candidate=Candidate(id="t", venue="kalshi", kind="city", station_id="KORD"),
        venue=VENUES["kalshi"],
        series_ticker="KXHIGHCHI",
        series_title="Highest temperature in Chicago",
        settlement_sources=["NWS"],
        n_open=6,
        n_settled=500,
        avg_volume=20000.0,
        med_spread_cents=2.0,
        avg_open_interest=3000.0,
        underlying="daily_high_temp",
        station_known=True,
        hrrr_ok=True,
        paper_n=800,
        paper_mean_abs_edge=0.12,
        paper_span_days=400,
    )
    base.update(over)
    return CandidateMetrics(**base)


def test_matrix_loads_with_scorecard_ids():
    from weather_markets.expansion.scorecard import WEIGHTS

    point_ids = {p.id for p in MATRIX.points}
    assert point_ids == set(WEIGHTS)


def test_forecastex_fee_half_of_kalshi():
    assert fee_cents(50, "forecastex") <= fee_cents(50, "kalshi") // 2 + 1
    assert fee_cents(50, "kalshi", maker=True) == 1  # min 1c floor


def test_scorecard_go_and_gates():
    good = score(_metrics())
    assert good.verdict.startswith("GO")
    assert good.ceiling_contracts == 700  # capped at capacity-study ceiling

    unknown = score(_metrics(underlying="unknown", settlement_sources=[]))
    assert unknown.verdict.startswith("NO-GO")
    assert "data" in unknown.verdict and "resolution" in unknown.verdict

    geo = score(_metrics(venue=VENUES["polymarket_us"]))
    assert "regulatory" in geo.verdict


def test_prior_verdict_carried():
    m = _metrics(candidate=Candidate(id="t", venue="kalshi", kind="city",
                                     station_id="KDEN", prior="HOLD 2026-07-07"))
    assert "HOLD 2026-07-07" in score(m).verdict


def test_seed_registry_loads():
    cands = load_candidates(DEFAULT_REGISTRY)
    assert any(c.id == "forecastex-miami" for c in cands)
    assert all(c.venue in VENUES for c in cands)


def test_forecastex_adapter_is_a_stub():
    with pytest.raises(NotImplementedError):
        ForecastExCatalog().sync(conn=None)


def test_retriever_scope_and_cap():
    m = _metrics()
    chunks = catalog_chunks(m) + history_chunks(m)
    assert all(c.tags for c in chunks)
    r = CompositeRetriever([MockRetriever(chunks)])
    fee_hits = r.retrieve("fees", ["fees", "fees.maker"])
    assert fee_hits and all(set(c.tags) & {"fees", "fees.maker"} for c in fee_hits)
    assert len(r.retrieve("everything", [p.id for p in MATRIX.points])) <= 16


def test_corpus_chunks_tagged(tmp_path):
    (tmp_path / "note.md").write_text(
        "# venue\n\n## Fees\nThe maker fee schedule is a quarter of the taker commission rate, "
        "which materially changes breakeven economics for thin edges.\n\n## Nothing\nshort\n"
    )
    chunks = corpus_chunks([tmp_path])
    assert len(chunks) == 1 and "fees" in chunks[0].tags


def test_bootstrap_scaffold(tmp_path):
    c = Candidate(id="forecastex-miami-test", venue="forecastex", kind="venue-port",
                  station_id="KMIA", series_ticker="KXHIGHMIA")
    dest = bootstrap(c, root=tmp_path)
    names = {p.name for p in dest.iterdir()}
    assert {"config.py", "pipeline.py", "backtest_walkforward.py", "README.md"} <= names
    text = (dest / "backtest_walkforward.py").read_text()
    assert "2.5" in text and "--live" not in text.replace("never wired to --live", "")
    compile((dest / "config.py").read_text(), "config.py", "exec")
    compile((dest / "pipeline.py").read_text(), "pipeline.py", "exec")
    compile((dest / "backtest_walkforward.py").read_text(), "backtest.py", "exec")
    with pytest.raises(FileExistsError):
        bootstrap(c, root=tmp_path)
