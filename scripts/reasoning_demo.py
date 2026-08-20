"""Reasoning-engine demo on mock data — no network, no DB, no API key needed.

Runs the full matrix -> specialists -> debate -> master loop with an in-memory
retriever and a scripted Completer, then self-checks the result. To run it
against the real Claude API, replace ScriptedCompleter() with
weather_markets.reasoning.ClaudeClient() (needs anthropic_api_key in .env).

Usage (always via uv, per CLAUDE.md):
    uv run python scripts/reasoning_demo.py
"""

from __future__ import annotations

import json
import re

from weather_markets.reasoning import (
    Chunk,
    Matrix,
    MockRetriever,
    ReasoningEngine,
    Role,
)

MATRIX = Matrix.model_validate(
    {
        "name": "forecastex-expansion",
        "description": "Should we route new-city expansion through ForecastEx?",
        "points": [
            {
                "id": "fees",
                "name": "Fee structure",
                "description": "Trading costs vs Kalshi.",
                "sub_points": [{"id": "fees.maker", "name": "Maker economics"}],
            },
            {
                "id": "liquidity",
                "name": "Liquidity & depth",
                "description": "Can our size get filled?",
            },
            {
                "id": "ops",
                "name": "Operational risk",
                "description": "API maturity, settlement timing, access rules.",
            },
        ],
    }
)

CHUNKS = [
    Chunk(id="c1", text="ForecastEx fee schedule is roughly half of Kalshi's taker fee.",
          source="api:forecastex", ref="fee-schedule", tags=["fees"]),
    Chunk(id="c2", text="Maker fills on Kalshi run about a quarter of the taker rate.",
          source="db:live_trades", ref="fees study 2026-06-21", tags=["fees.maker"]),
    Chunk(id="c3", text="Kalshi book depth caps out around 500-700 contracts per city.",
          source="db:orderbook_snapshots", ref="capacity study", tags=["liquidity"]),
    Chunk(id="c4", text="DH contracts trade through resolution day; only cash settles T+1.",
          source="api:forecastex", ref="resolution-day finding", tags=["ops"]),
]


class ScriptedCompleter:
    """Offline stand-in for ClaudeClient with deterministic, prompt-aware output."""

    def __init__(self) -> None:
        self.debate_calls = 0

    def complete(self, prompt: str, *, role: Role, system: str | None = None) -> str:
        cited = re.findall(r"^\[(\w+)\]", prompt, flags=re.MULTILINE)
        if role == "specialist":
            refs = " ".join(f"[{c}]" for c in cited) or "(no evidence)"
            return f"Evidence-backed finding for this slice {refs}."
        if role == "debate":
            self.debate_calls += 1
            if self.debate_calls == 1:
                return "fees: also address the maker-fee leg explicitly."
            return "NO_CHALLENGES"
        # master: one claim per evidence id actually in the prompt, plus one
        # deliberately ungrounded claim to show the guardrail flagging it
        claim_text = {
            "c1": "Fees are materially lower than Kalshi.",
            "c2": "Maker economics are favorable.",
            "c3": "Single-venue depth is capped, so breadth needs a second venue.",
            "c4": "Contracts trade through resolution day.",
        }
        claims = [{"text": claim_text[i], "chunk_ids": [i]} for i in cited if i in claim_text]
        claims.append({"text": "ForecastEx volume will triple next year.", "chunk_ids": []})
        return json.dumps(
            {
                "decision": "Pilot ForecastEx at minimal size; keep Kalshi primary.",
                "claims": claims,
            }
        )


def main() -> None:
    engine = ReasoningEngine(MockRetriever(CHUNKS), ScriptedCompleter(), max_debate_rounds=3)
    result = engine.run("Should we expand to ForecastEx as a second venue?", MATRIX)

    print(f"Matrix: {MATRIX.name} ({len(MATRIX.points)} focus points)")
    print(f"Debate rounds: {result.debate_rounds}")
    print(f"\nDecision: {result.decision.text}\n")
    for claim in result.decision.grounded:
        print(f"  grounded   {claim.text}  <- {', '.join(claim.chunk_ids)}")
    for claim in result.decision.ungrounded:
        print(f"  UNGROUNDED (flagged, not asserted): {claim.text}")

    # self-check: the demo fails loudly if the loop or guardrail breaks
    assert result.debate_rounds == 2, "expected challenge round + NO_CHALLENGES round"
    evidence_ids = {c.id for c in result.decision.evidence}
    assert result.decision.grounded, "expected at least one grounded claim"
    assert all(set(c.chunk_ids) <= evidence_ids for c in result.decision.grounded)
    assert [c.text for c in result.decision.ungrounded] == [
        "ForecastEx volume will triple next year."
    ]
    print("\nself-check OK")


if __name__ == "__main__":
    main()
