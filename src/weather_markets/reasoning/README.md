# weather_markets.reasoning

Reusable matrix → specialists → debate → master reasoning engine. Built once
here so B1 (expansion research), B2 (ops copilot), and B3 (live experiment)
all import the same machinery.

**Pure by construction:** importing this package touches no network, DB, or
trading code. All IO lives in two injected seams:

- `Retriever` (protocol) — `retrieve(query, matrix_scope) -> list[Chunk]`.
  Real backends are DB queries / live-data adapters; `MockRetriever` ships now.
- `Completer` (protocol) — implemented by `ClaudeClient` (thin Anthropic SDK
  wrapper, lazy import, key from `anthropic_api_key` in the gitignored `.env`
  via `Settings`, else the SDK's own env resolution). Tests inject fakes.

## Pieces

| Piece | What it does |
|---|---|
| `Matrix` / `FocusPoint` / `SubPoint` (`matrix.py`) | Typed taxonomy that scopes retrieval; unique-id validator; `Matrix.load(path)` for JSON/YAML |
| `Chunk` (`retriever.py`) | Evidence unit: `id`, `text`, `source`, `ref`, matrix-point `tags` |
| `ModelsConfig` (`client.py`) | Role → model config: `specialist` (haiku, fast/cheap), `debate` (sonnet, mid), `master` (opus, strong); overridable per call |
| `SpecialistAgent` | Retrieves only within its focus point's slice, summarizes with `[chunk_id]` citations |
| `DebateLayer` | Cross-examines reports, challenged specialists revise; hard `max_rounds` cap, stops early on `NO_CHALLENGES` |
| `MasterAgent` | Emits JSON decision + claims with chunk ids. **Guardrail:** claims with missing/unknown ids land in `Decision.ungrounded` — flagged, never asserted |
| `ReasoningEngine` | Runs the whole loop: `run(question, matrix) -> EngineResult` |

## Usage

```python
from weather_markets.reasoning import ClaudeClient, Matrix, ReasoningEngine

matrix = Matrix.load("docs/matrices/venue_expansion.json")
engine = ReasoningEngine(retriever=MyDbRetriever(), completer=ClaudeClient())
result = engine.run("Should we expand to ForecastEx?", matrix)
print(result.decision.text)
for claim in result.decision.ungrounded:
    print("FLAGGED:", claim.text)
```

Offline demo (no key, no network): `uv run python scripts/reasoning_demo.py`
Tests: `uv run pytest tests/test_reasoning.py`

## Backends

Two `Completer` backends; `completer_for(entrypoint)` routes between them:

| Entrypoint | Default backend | Billing |
|---|---|---|
| `expansion` (B1, human-triggered) | `ClaudeCodeCompleter` — Claude Code CLI headless | Claude subscription (no per-token cost) |
| `copilot` (B2, cron) | `ClaudeClient` — Anthropic API | metered API key |
| `advisor` (B3, live experiment) | `ClaudeClient` — Anthropic API | metered API key |

Override per run with `REASONING_BACKEND=api|claude_code` (process env var,
e.g. `REASONING_BACKEND=api uv run python scripts/expansion_scout.py ...`).

**Subscription setup:** run `claude setup-token` once, put the result in the
gitignored `.env` as `CLAUDE_CODE_OAUTH_TOKEN=...` (next to
`ANTHROPIC_API_KEY`). The CLI backend defaults to `SUBSCRIPTION_MODELS`
(master = Sonnet) because a Pro plan doesn't include Opus — pass a
`ModelsConfig` to override any tier. JSON contracts on the CLI path are
enforced by instruction + parse + one retry against the same pydantic models
(`contracts.MasterOutput`) the API path validates with.

## Notes

- Sync + sequential (cron/CLI usage; memory-light for the no-swap box).
- `CompletionRefused` is raised if Claude declines a request.
- Adaptive thinking is sent for debate/master tiers only (Haiku predates it).
