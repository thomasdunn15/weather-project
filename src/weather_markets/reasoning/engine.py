"""Pure orchestration: matrix -> specialists -> debate -> master.

No IO in this module. Evidence comes from an injected `Retriever`, text from
an injected `Completer`; given those two the engine is deterministic and
side-effect free. B1/B2/B3 import this instead of re-implementing the loop.
"""

from __future__ import annotations

import re
from typing import Sequence

from pydantic import BaseModel

from weather_markets.reasoning.client import Completer
from weather_markets.reasoning.contracts import Claim, MasterOutput, parse_json_payload
from weather_markets.reasoning.matrix import FocusPoint, Matrix
from weather_markets.reasoning.retriever import Chunk, Retriever

NO_CHALLENGES = "NO_CHALLENGES"

MASTER_SYSTEM = (
    "You are the master decision agent. You may only support claims with the "
    "evidence chunks provided in the prompt — never outside knowledge. Output "
    "strict JSON, nothing else."
)


class SpecialistReport(BaseModel):
    point_id: str
    point_name: str
    summary: str
    chunks: list[Chunk]


class Decision(BaseModel):
    text: str
    grounded: list[Claim]
    ungrounded: list[Claim]  # flagged, never asserted as fact
    evidence: list[Chunk]


class EngineResult(BaseModel):
    decision: Decision
    reports: list[SpecialistReport]
    debate_rounds: int
    debate_transcript: list[str]


def _render_chunks(chunks: Sequence[Chunk]) -> str:
    lines = []
    for c in chunks:
        ref = f", ref={c.ref}" if c.ref else ""
        lines.append(f"[{c.id}] (source={c.source}{ref}) {c.text}")
    return "\n".join(lines) or "(no evidence retrieved)"


class SpecialistAgent:
    """Investigates one focus point, retrieving only within its matrix slice."""

    def __init__(self, point: FocusPoint, retriever: Retriever, completer: Completer) -> None:
        self.point = point
        self.retriever = retriever
        self.completer = completer

    def investigate(self, question: str) -> SpecialistReport:
        chunks = self.retriever.retrieve(question, self._scope())
        prompt = (
            f"You are the specialist for focus point \"{self.point.name}\": "
            f"{self.point.description}\n"
            f"Sub-points: {', '.join(s.name for s in self.point.sub_points) or '(none)'}\n\n"
            f"Question: {question}\n\n"
            f"Evidence (the only source you may use):\n{_render_chunks(chunks)}\n\n"
            "Write a concise findings summary for your focus point only. Cite "
            "evidence ids in square brackets after each claim, e.g. [c1]. If "
            "the evidence does not cover something, say so — do not invent facts."
        )
        summary = self.completer.complete(prompt, role="specialist")
        return SpecialistReport(
            point_id=self.point.id, point_name=self.point.name, summary=summary, chunks=chunks
        )

    def revise(self, question: str, report: SpecialistReport, challenge: str) -> SpecialistReport:
        prompt = (
            f"Your earlier findings for focus point \"{self.point.name}\" were challenged.\n\n"
            f"Question: {question}\n\nYour findings:\n{report.summary}\n\n"
            f"Challenge: {challenge}\n\n"
            f"Evidence (the only source you may use):\n{_render_chunks(report.chunks)}\n\n"
            "Write a revised findings summary addressing the challenge, with the "
            "same citation rules. If the challenge is wrong, say why, citing evidence."
        )
        summary = self.completer.complete(prompt, role="specialist")
        return report.model_copy(update={"summary": summary})

    def _scope(self) -> list[str]:
        return [self.point.id, *(s.id for s in self.point.sub_points)]


class DebateLayer:
    """Cross-examines specialist reports; challenged specialists revise.

    Hard cap: at most `max_rounds` critique passes, stopping early on
    NO_CHALLENGES.
    """

    def __init__(self, completer: Completer, max_rounds: int = 2) -> None:
        if max_rounds < 0:
            raise ValueError("max_rounds must be >= 0")
        self.completer = completer
        self.max_rounds = max_rounds

    def run(
        self,
        question: str,
        reports: list[SpecialistReport],
        specialists: dict[str, SpecialistAgent],
    ) -> tuple[list[SpecialistReport], list[str]]:
        current = {r.point_id: r for r in reports}
        transcript: list[str] = []
        for _ in range(self.max_rounds):
            critique = self.completer.complete(self._critique_prompt(question, current), role="debate")
            transcript.append(critique)
            challenges = _parse_challenges(critique, set(current))
            if not challenges:
                break
            for point_id, challenge in challenges.items():
                current[point_id] = specialists[point_id].revise(question, current[point_id], challenge)
        return list(current.values()), transcript

    def _critique_prompt(self, question: str, reports: dict[str, SpecialistReport]) -> str:
        body = "\n\n".join(
            f"## {r.point_id} — {r.point_name}\n{r.summary}\nEvidence ids: "
            f"{', '.join(c.id for c in r.chunks) or '(none)'}"
            for r in reports.values()
        )
        return (
            "You are a verification reviewer for a panel of specialist reports.\n\n"
            f"Question: {question}\n\n{body}\n\n"
            "Identify contradictions between reports, claims lacking citations, "
            "or misread evidence. Output one line per challenge, formatted "
            "exactly as '<point_id>: <challenge>' using the point ids above. If "
            f"there are no challenges, output exactly {NO_CHALLENGES}."
        )


def _parse_challenges(critique: str, known_ids: set[str]) -> dict[str, str]:
    if NO_CHALLENGES in critique:
        return {}
    challenges: dict[str, str] = {}
    for line in critique.splitlines():
        m = re.match(r"^\s*([\w.-]+)\s*:\s*(.+)$", line)
        if m and m.group(1) in known_ids:
            pid, text = m.group(1), m.group(2).strip()
            challenges[pid] = f"{challenges[pid]} {text}" if pid in challenges else text
    return challenges


class MasterAgent:
    """Emits a decision grounded strictly in retrieved chunks.

    Guardrail: every claim must carry chunk ids from the retrieved evidence;
    claims with missing or unknown ids are returned in `Decision.ungrounded`
    (flagged), never merged into the grounded set.
    """

    def __init__(self, completer: Completer) -> None:
        self.completer = completer

    def decide(self, question: str, reports: list[SpecialistReport]) -> Decision:
        evidence: dict[str, Chunk] = {}
        for r in reports:
            for c in r.chunks:
                evidence.setdefault(c.id, c)
        body = "\n\n".join(f"## {r.point_name}\n{r.summary}" for r in reports)
        prompt = (
            f"Question: {question}\n\nSpecialist findings:\n{body}\n\n"
            f"Evidence:\n{_render_chunks(list(evidence.values()))}\n\n"
            "Decide. Output strict JSON only, shaped as:\n"
            '{"decision": "<the decision and rationale>", '
            '"claims": [{"text": "<one factual claim>", "chunk_ids": ["<id>"]}]}\n'
            "Every factual claim goes in claims with the evidence ids that "
            "support it. If you cannot support a claim with evidence, still "
            'list it with "chunk_ids": [] so it is flagged instead of asserted.'
        )
        raw = self.completer.complete(prompt, role="master", system=MASTER_SYSTEM)
        out = parse_json_payload(raw, MasterOutput)
        known = set(evidence)
        grounded = [c for c in out.claims if c.chunk_ids and set(c.chunk_ids) <= known]
        ungrounded = [c for c in out.claims if not (c.chunk_ids and set(c.chunk_ids) <= known)]
        return Decision(
            text=out.decision,
            grounded=grounded,
            ungrounded=ungrounded,
            evidence=list(evidence.values()),
        )


class ReasoningEngine:
    """One call does the whole loop: matrix -> specialists -> debate -> master."""

    def __init__(self, retriever: Retriever, completer: Completer, max_debate_rounds: int = 2) -> None:
        self.retriever = retriever
        self.completer = completer
        self.max_debate_rounds = max_debate_rounds

    def run(self, question: str, matrix: Matrix) -> EngineResult:
        specialists = {
            p.id: SpecialistAgent(p, self.retriever, self.completer) for p in matrix.points
        }
        reports = [specialists[p.id].investigate(question) for p in matrix.points]
        reports, transcript = DebateLayer(self.completer, self.max_debate_rounds).run(
            question, reports, specialists
        )
        decision = MasterAgent(self.completer).decide(question, reports)
        return EngineResult(
            decision=decision,
            reports=reports,
            debate_rounds=len(transcript),
            debate_transcript=transcript,
        )
