"""Ops-copilot driver: gather evidence, run the B0 reasoning engine once,
render the daily operator digest.

All orchestration is `weather_markets.reasoning.ReasoningEngine` — this module
only wires DB/Kalshi data into it and renders the result. Read-only end to
end; this system has no ability to place or adjust a trade.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from weather_markets.copilot import metrics as m
from weather_markets.copilot.retrievers import (
    build_retriever,
    calibration_chunks,
    config_drift_chunks,
    data_health_chunks,
    execution_chunks,
    regime_chunks,
    settlement_chunks,
)
from weather_markets.reasoning import (
    EngineResult,
    Matrix,
    ModelsConfig,
    ReasoningEngine,
    completer_for,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = REPO_ROOT / "docs" / "matrices" / "ops_digest.json"

DIGEST_QUESTION_TEMPLATE = (
    "Produce today's operator digest ({today}, UTC) for a live weather-prediction-market "
    "trading system. This system is READ-ONLY analytics — you have no ability to place or "
    "adjust trades, and every suggestion you make must be phrased as a suggestion requiring "
    "explicit human operator approval, never as an action taken.\n\n"
    "For each of the 5 monitoring areas: state whether anything is anomalous (a regime shift, "
    "calibration drift, execution issue, config divergence, or data gap). For each flagged item, "
    "give: (1) the evidence chunk id(s) it rests on, (2) a plausible cause, (3) one concrete "
    "suggested action for the operator to consider. If an area looks normal, say so briefly — do "
    "not manufacture a finding. Rank flagged items by operator urgency, most urgent first. This "
    "is analytics only, not financial advice."
)


def build_evidence(conn, kalshi=None, now: datetime | None = None) -> list:
    now = now or datetime.now(timezone.utc)
    cities = m.live_cities(conn)
    chunks = []
    chunks += calibration_chunks(m.collect_calibration(conn, now))
    chunks += regime_chunks(m.collect_regime(conn, cities, now))
    chunks += execution_chunks(m.collect_execution(conn, now))
    chunks += config_drift_chunks(m.collect_config_drift(conn, REPO_ROOT, now))
    chunks += data_health_chunks(m.collect_data_health(conn, cities, now))
    if kalshi is not None:
        chunks += settlement_chunks(kalshi)
    return chunks


def run_digest(conn, kalshi=None, now: datetime | None = None) -> EngineResult:
    now = now or datetime.now(timezone.utc)
    chunks = build_evidence(conn, kalshi, now)
    retriever = build_retriever(chunks)
    # Sonnet master: the flag-and-summarize job doesn't need Opus (~halves cost)
    engine = ReasoningEngine(
        retriever,
        completer_for("copilot", models=ModelsConfig(master="claude-sonnet-5")),
    )
    question = DIGEST_QUESTION_TEMPLATE.format(today=now.strftime("%Y-%m-%d"))
    matrix = Matrix.load(MATRIX_PATH)
    return engine.run(question, matrix)


def render_digest(result: EngineResult, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [
        f"# Operator Digest — {now.strftime('%Y-%m-%d %H:%MZ')}",
        "",
        "_Analytics only, not financial advice. Every item below is a suggestion — "
        "this system never places or adjusts trades._",
        "",
        f"**Debate rounds:** {result.debate_rounds}",
        "",
        result.decision.text,
        "",
        "## Grounded findings",
        "",
    ]
    if result.decision.grounded:
        for cl in result.decision.grounded:
            lines.append(f"- {cl.text} `[{', '.join(cl.chunk_ids)}]`")
    else:
        lines.append("_(none)_")
    if result.decision.ungrounded:
        lines += ["", "## Flagged — unverified, not asserted", ""]
        for cl in result.decision.ungrounded:
            lines.append(f"- {cl.text}")
    lines += ["", "## Specialist reports", ""]
    for r in result.reports:
        lines += [f"### {r.point_name}", "", r.summary, ""]
    lines += ["", "## Evidence appendix", ""]
    for c in result.decision.evidence:
        ref = f" ({c.ref})" if c.ref else ""
        lines.append(f"- `[{c.id}]` {c.source}{ref}: {c.text}")
    return "\n".join(lines)
