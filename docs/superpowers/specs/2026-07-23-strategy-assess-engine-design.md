# Spec: strategy-research ingest + `strategy-assess` engine

*Design APPROVED (Sections 1–3, 2026-07-23). This is the implementation spec — under
review before any code (HARD GATE). Not committed (commit only when asked).*

## Goal

Ingest external strategy research (white papers) and use the existing reasoning engine to
reason **adversarially** about whether a strategy is worth *testing* on a given market — across
weather AND liquid non-weather markets. Output is triage ("worth a backtest? here's the probe"),
never "implement." Scalability is first-class: which markets can absorb more contracts, and how far.

## Approved decisions (design)

- **Output = A + C.** A = triage; C = adversarial (attack the paper's claim against our
  efficient-market / fee reality). Never "implement" — the quant harness decides that.
- **Ingest = assisted discovery + tagged ingest + mandatory re-verify.** Papers → `##`-sectioned
  markdown with **explicit** focus-point tags (kills the silent-drop bug behind the Denver wrong
  verdict). Killed/refuted claims MUST be independently re-verified before entering as guardrails
  (the step that overturned 2 of the harness's 5 kills).
- **Candidate = `(strategy_id, market_candidate_id)`.** The market is an existing expansion
  `Candidate` (which already binds venue); the strategy is a small YAML def. No new market model.
- **Reframe:** forecasting (EMOS/Benter) stays in weather (BTC direction ≈ coin-flip, our finding).
  The edge that *travels* to liquid markets is the structural **favorite-longshot harvest — be the
  favorite (≥50¢), fade the <30¢ longshot.**

## Architecture — reuse map (grounded in the code)

REUSE unchanged: `ReasoningEngine` + debate/master/grounding; `Matrix`; `Candidate` +
`collect_metrics` (real avg_volume/OI/spread, paper history, venue facts); `CompositeRetriever` /
`MockRetriever`; `completer_for("expansion")` (subscription backend, ~$0); `sync_kalshi_catalog`
(accepts any category → liquid markets get REAL numbers); the `expansion_scout.py` CLI pattern.

The three retriever legs already exist in `build_retriever`: `corpus_chunks` (ingested paper),
`history_chunks` (our evidence), `catalog_chunks` (market facts). The one real gap: those chunks
carry the *expansion* matrix tags, not `strategy_eval` tags.

## The `strategy_eval` matrix (7 focus points) — Section 2, approved

mechanism (.netfee/.oos) · market_fit (.preconditions/.flow) · our_evidence (.paper/.live) ·
economics (.fees/.adverse_selection) · scalability (.absorption/.decay/.ceiling) · access
(.regulatory) · testability (.probe/.data). Full JSON in the implementation spec below.

**Scalability honesty rule:** no deep historical order-book depth exists (top-of-book +
going-forward 5-min snapshots only) → report a proxy-grounded RANGE + flag the depth probe, never
a fabricated precise ceiling. Each market lands on the **edge × scale quadrant**: ⭐ edge+deep
(rare; FLB on liquid retail = best shot) · edge+thin = weather (scale by breadth) · no-edge+deep =
avoid · no-edge+thin = ignore.

## Evidence base → first candidates

Lit review: `docs/research/md/2026-07-23-prediction-market-strategy-lit-review.md` (19 sources,
adversarially verified; ratifies "efficient, thin, fee-eaten, breadth-is-the-lever"). Independent
re-verification of the 5 harness-killed claims: **2 OVERTURNED** (single-name MM ~2×; labor
inefficiency pocket) → had we ingested raw kills we'd have fed the engine 2 FALSE guardrails.
Seed strategies: **S1** passive-MM / FLB harvest · **S2** Benter blend net-of-fee · **S3**
Kalshi↔ForecastEx cross-venue arb · **S4** FLB-fade on Kalshi labor/unemployment.

---

# Implementation spec (file-by-file)

## 1. `docs/matrices/strategy_eval.json` (NEW — data)

Same shape as `breadth_expansion.json`. Points/sub-points:

```json
{
  "name": "strategy-eval",
  "description": "Is an external strategy worth backtesting on a given market? Adversarial: the market is efficient and fee-eaten by default; a claim earns a probe only by surviving mechanism, fit, evidence, economics, scalability, access, and testability.",
  "points": [
    {"id": "mechanism", "name": "Mechanism validity", "description": "What is the edge and does it survive our reality — measured net of fees, out-of-sample, not gross/in-sample?",
     "sub_points": [{"id": "mechanism.netfee", "name": "Edge measured after fees"}, {"id": "mechanism.oos", "name": "Out-of-sample, not in-sample (Brier-only = WEAK, not proof)"}]},
    {"id": "market_fit", "name": "Market fit / preconditions", "description": "Does this market have the regime the edge needs?",
     "sub_points": [{"id": "market_fit.preconditions", "name": "FLB needs favorite/longshot regime; Benter needs a model that beats naive priors (weather yes, BTC no); arb needs an equivalent 2nd-venue contract"}, {"id": "market_fit.flow", "name": "Is the naive YES-longshot flow the edge feeds on actually present?"}]},
    {"id": "our_evidence", "name": "Our internal evidence", "description": "What do our own paper/live trades say for THIS market?",
     "sub_points": [{"id": "our_evidence.paper", "name": "paper_trades economics (empty → probe first)"}, {"id": "our_evidence.live", "name": "Fills / paper-vs-live divergence"}]},
    {"id": "economics", "name": "Fee & adverse-selection economics", "description": "Does the edge clear fees and survive toxic flow?",
     "sub_points": [{"id": "economics.fees", "name": "Clears Kalshi 2c/1c, ForecastEx ~half"}, {"id": "economics.adverse_selection", "name": "Single-name toxicity, ~33% return SD, one-sided-flow / inventory risk"}]},
    {"id": "scalability", "name": "Scalability", "description": "How many contracts can this absorb, and how far does that scale?",
     "sub_points": [{"id": "scalability.absorption", "name": "Catalog avg_volume/OI (real) + snapshot depth"}, {"id": "scalability.decay", "name": "Edge degrades with size (larger maker posts less-advantageous prices)"}, {"id": "scalability.ceiling", "name": "Realistic max contracts/day + scaling PATH (deepen vs add-markets) + proxy-vs-measured flag"}]},
    {"id": "access", "name": "Access / regulatory", "description": "Can a US person trade it via a real API?",
     "sub_points": [{"id": "access.regulatory", "name": "Venue access, geoblock (Polymarket NEVER circumvented), US-person, API"}]},
    {"id": "testability", "name": "Testability", "description": "Can we actually run the probe cheaply?",
     "sub_points": [{"id": "testability.probe", "name": "The exact backtest / data check"}, {"id": "testability.data", "name": "Do we have or can we cheaply get the data?"}]}
  ]
}
```

## 2. `docs/strategies/strategies.yaml` (NEW — data, drop-in like candidates.yaml)

Schema: `id, title, preconditions, applies_to (candidate-id globs), question_frame`. Seeds:

```yaml
- id: s1-flb-harvest
  title: Passive market-making / favorite-longshot harvest
  preconditions: >-
    Needs a favorite/longshot regime (contracts trading >=50c vs <30c) and naive
    YES-longshot retail flow to fade. Structural, not forecasting-based.
  applies_to: ["kalshi-*", "forecastex-*"]
  question_frame: >-
    Should we backtest the passive-MM / favorite-longshot-harvest strategy on {market}
    (venue {venue}, avg volume {avg_volume})? Be the favorite side (>=50c), never the
    longshot. Decide: does the net-of-fee edge survive here, is the longshot flow present,
    and how many contracts can it absorb before the edge decays?

- id: s2-benter-netfee
  title: Benter two-step model+market blend, net of fee
  preconditions: >-
    Needs a predictive model that beats naive priors (weather EMOS yes; BTC direction no).
  applies_to: ["kalshi-*", "forecastex-*"]
  question_frame: >-
    Should we backtest a Benter model+market blend on {market}? Only if a calibrated model
    beats the market prior here. Decide net-of-fee edge, OOS not in-sample, and scale ceiling.

- id: s3-xvenue-arb
  title: Kalshi <-> ForecastEx cross-venue arbitrage
  preconditions: >-
    Needs an equivalent contract on a second venue (same underlying + settlement).
  applies_to: ["forecastex-*"]
  question_frame: >-
    Should we backtest Kalshi<->ForecastEx arb on {market}? Requires an equivalent 2nd-venue
    contract and net-of-both-commissions spread. Decide feasibility + capacity.

- id: s4-labor-flb-fade
  title: FLB-fade on Kalshi labor / unemployment
  preconditions: >-
    Needs a labor/economics market with <30c longshots carrying naive flow.
  applies_to: ["kalshi-*"]
  question_frame: >-
    Should we backtest fading <30c longshots on {market} (labor/unemployment)? The edge is
    structural FLB, NOT forecasting. Decide net-of-fee edge, flow presence, and scale ceiling.
```

## 3. `docs/strategies/corpus/` (NEW — the ingested papers)

Drop-in markdown, `##`-sectioned. Each section's FIRST line after the heading is an explicit tag
comment (strict — no keyword-guessing here):

```markdown
## Burgi-Deng-Whelan: passive MM nets +2.6% net-of-commission at >=50c
<!-- fp: mechanism.netfee, scalability.decay | kind: evidence -->
...body...

## CLAIM (harness-killed): favorite-longshot bias is un-capturable
<!-- fp: economics.adverse_selection | kind: guardrail | reverified: 2026-07-23 KILL_CORRECT (Whelan 2025: +2.6% net) -->
...body...
```

Rules (enforced by lint, §5): every section needs `fp:`; `kind: guardrail` sections need
`reverified:`. Seeded from the lit review with the re-verification verdicts baked in.

## 4. `src/weather_markets/expansion/strategy_retrievers.py` (NEW — ~50 lines)

```python
STRATEGY_CORPUS = REPO_ROOT / "docs" / "strategies" / "corpus"

def strat_market_chunks(m: CandidateMetrics) -> list[Chunk]:
    # same facts as catalog_chunks, re-tagged to strategy_eval ids:
    #   avg_volume/OI/spread -> scalability.absorption, market_fit.flow
    #   ceiling range + path -> scalability.ceiling, scalability.decay   (via scaling_summary, §6)
    #   venue fees           -> economics.fees, economics.adverse_selection
    #   venue regulatory/api -> access.regulatory

def strat_evidence_chunks(m: CandidateMetrics) -> list[Chunk]:
    # paper_trades      -> our_evidence.paper ; capacity finding -> scalability.ceiling
    # prior verdict     -> our_evidence.live
    # if m.paper_n == 0 -> ONE chunk: "no internal evidence for {market} -> run a data probe
    #                       first" tagged our_evidence.paper, testability.data

def build_strategy_retriever(m, corpus_dirs=(STRATEGY_CORPUS,)) -> CompositeRetriever:
    return CompositeRetriever([
        MockRetriever(strat_market_chunks(m) + strat_evidence_chunks(m)),
        MockRetriever(corpus_chunks(corpus_dirs, strict=True)),  # strict = explicit tags
    ])
```

`corpus_chunks` (in `retrievers.py`) gets a small extension: parse a leading
`<!-- fp: a, b | kind: ... | reverified: ... -->` line → use those tags explicitly; `strict=True`
means untagged sections raise instead of silently dropping. Expansion keeps `strict=False`
(current lenient behavior, unchanged).

## 5. `lint_strategy_corpus(dir=STRATEGY_CORPUS) -> list[str]` (NEW — in strategy_retrievers.py)

Returns error strings (empty = clean). Enforces: every `##` section has `fp:`; guardrail sections
have `reverified:`. Called by both subcommands (abort on errors) and by the test.

## 6. `scaling_summary(m: CandidateMetrics) -> tuple[str, str, bool]` (NEW — in scorecard.py)

Deterministic, honest proxy. Returns `(ceiling_range, scaling_path, is_proxy)`:
- `ceiling_range`: `avg_volume` None → "unknown"; else `~{5%}-{15%} contracts/day (proxy)`
  bounded by the ~500-700 measured Kalshi weather ceiling as a reference note.
- `scaling_path`: high volume AND our_evidence present → "deepen-in-market (edge+deep)"; else
  "add-markets (weather's only path)".
- `is_proxy`: True (always — real depth unmeasured) until a walk-book capacity run exists.

Used by `strat_market_chunks` (§4) and the `strategy-rank` table (§7). Existing expansion `rank`
render left unchanged (it already has an est. ceiling).

## 7. Two subcommands in `scripts/expansion_scout.py` (NEW — ~45 lines, mirror cmd_assess)

- `strategy-rank` — load strategies.yaml; for each strategy × its `applies_to` markets, a
  deterministic row: `market | venue | avg_volume | ceiling_range | scaling_path | precondition?`.
  No LLM. Lets you compare markets on scalability before spending an assess.
- `strategy-assess <strategy_id> <market_id> [--out]` — `_find` the candidate → `collect_metrics`
  → `lint_strategy_corpus` (abort on errors) → `build_strategy_retriever` →
  `Matrix.load(strategy_eval.json)` → `ReasoningEngine(..., completer_for("expansion"))` →
  `engine.run(strategy.question_frame.format(market=..., venue=..., avg_volume=...), matrix)` →
  render the A-triage + C-adversarial report (reuse `render_assess` shape) → write `--out` to
  `docs/research/md/`.

## 8. Tests (`tests/test_strategy_assess.py`, NEW)

- `test_lint_catches_untagged_and_missing_reverify` — a tmp corpus with a good section, an
  untagged section, and a guardrail missing `reverified:` → lint returns both errors. **(the
  must-have — this is the guard against the Denver silent-drop failure mode.)**
- `test_assess_smoke` — `build_strategy_retriever` + a scripted completer (reuse the mock from
  `test_reasoning`) → `engine.run` returns a decision; grounded claims ⊆ retrieved evidence ids.
  No network.

## Build order

1. `strategy_eval.json` → 2. extend `corpus_chunks` (explicit tags + `strict`) + `strategy_retrievers.py`
(chunks + `build_strategy_retriever` + `lint_strategy_corpus`) → 3. `scaling_summary` in scorecard →
4. two subcommands → 5. `strategies.yaml` → 6. seed `docs/strategies/corpus/` from the lit review →
7. tests → 8. smoke: `strategy-rank`; `strategy-assess s1-flb-harvest kalshi-nyc`; then a liquid
market (one-time `sync --category <Financials/Economics>` + a candidate row → real numbers).

## Non-goals / skipped (ponytail)

- Bespoke strategy candidate class / registry format → reuse `Candidate` + a YAML.
- New CLI file → two subcommands on the existing scout.
- Walk-book rewrite → `scaling_summary` proxy + flag; run `walk_book_capacity.py` when sizing.
- Per-strategy corpus tags → naive query-ranked retrieval for v1; add tags only if strategies
  cross-contaminate (ponytail comment marks it).
- Touching the expansion `rank` render → unchanged.
- Any live/implement path → assess is triage only, never emits "implement."

## Constraints

`uv run` only; subscription backend for strategy research; UTC; memory-light (no-swap box); never
fabricate a capacity ceiling; secrets gitignored; **commit only when asked**; JS↔Python sim parity
untouched (not in scope). HARD GATE — no implementation code until this spec is approved.
