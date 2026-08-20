"""Strategy-assessment retriever legs + corpus linter + strategy registry.

Sibling to retrievers.py, but for the (strategy x market) assessment instead of
the (market) expansion assessment. Reuses CandidateMetrics wholesale — the same
real catalog/paper facts, re-emitted under strategy_eval matrix tags so the
strategy specialists retrieve them. Three legs:

- strat_market_chunks:   market facts (volume/OI/spread, fees, scale, access)
- strat_evidence_chunks: our own paper/live evidence (empty market -> "probe first")
- corpus_chunks(strict): the ingested papers in docs/strategies/corpus/

Pure at import (no IO); the DB work already happened in collect_metrics.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from weather_markets.expansion.candidates import REPO_ROOT
from weather_markets.expansion.catalog import fee_cents
from weather_markets.expansion.retrievers import (
    CompositeRetriever,
    corpus_chunks,
    parse_fp_comment,
)
from weather_markets.expansion.scorecard import CandidateMetrics, scaling_summary
from weather_markets.reasoning import Chunk, MockRetriever

STRATEGY_CORPUS = REPO_ROOT / "docs" / "strategies" / "corpus"
STRATEGIES_YAML = REPO_ROOT / "docs" / "strategies" / "strategies.yaml"
STRATEGY_MATRIX = REPO_ROOT / "docs" / "matrices" / "strategy_eval.json"


class Strategy(BaseModel):
    id: str
    title: str
    preconditions: str = ""
    applies_to: list[str] = []      # candidate-id globs (fnmatch)
    question_frame: str             # .format(market=, venue=, avg_volume=)


def load_strategies(path: str | Path = STRATEGIES_YAML) -> list[Strategy]:
    data = yaml.safe_load(Path(path).read_text()) or []
    out = [Strategy.model_validate(d) for d in data]
    if len({s.id for s in out}) != len(out):
        raise ValueError(f"duplicate strategy ids in {path}")
    return out


# ----- retriever legs (re-tag CandidateMetrics facts to strategy_eval ids) ----

def _flb_regime_chunk(m: CandidateMetrics) -> Chunk:
    """The measured favorite-longshot signal for this market — the evidence that
    lets the engine tell an overpriced-longshot market (fade) from a coin-flip
    (no regime) from a favorites-underpriced market (be the favorite)."""
    c = m.candidate
    r = m.flb_regime
    if not r:
        text = (
            f"Favorite-longshot regime for {c.id} is UNMEASURED. Run "
            "scripts/analysis/flb_regime.py --write to populate it from Kalshi "
            "candlesticks; until then the FLB edge is UNPROVEN for this specific "
            "market — the general/weather FLB literature does not establish it here."
        )
    else:
        speed = f"{r['resolution_hours']:.0f}h median life" if r.get("resolution_hours") else "life ?"
        parts = [f"Measured favorite-longshot regime for {c.id}, from "
                 f"{r.get('n_markets', '?')} settled markets' pre-resolution prices "
                 f"({speed}): {r.get('verdict', '')}."]
        if r.get("longshot_mass") is not None:
            parts.append(f"Longshot mass {r['longshot_mass']:.0%} (share priced <30c).")
        if r.get("longshot_overpricing_pp") is not None:
            parts.append(f"<30c longshots overpricing {r['longshot_overpricing_pp']:+.1f}pp "
                         "(positive = overpriced = harvestable by fading the longshot).")
        if r.get("favorite_underpricing_pp") is not None:
            parts.append(f"Favorites (>=50c) underpricing {r['favorite_underpricing_pp']:+.1f}pp "
                         "(positive = favorites win more than priced = the 'be the favorite' edge).")
        text = " ".join(parts)
    return Chunk(
        id=f"strat:{c.id}:flb_regime", text=text, source="flb_regime",
        ref="flb_regime table (scripts/analysis/flb_regime.py)",
        tags=["market_fit", "market_fit.preconditions", "market_fit.flow",
              "mechanism", "mechanism.netfee"],
    )


def strat_market_chunks(m: CandidateMetrics) -> list[Chunk]:
    c, v = m.candidate, m.venue
    ceiling_range, path, is_proxy = scaling_summary(m)
    out = [
        Chunk(
            id=f"strat:{c.id}:absorption",
            text=(
                f"Market {c.id} on {v.name}: avg settled volume "
                f"{f'{m.avg_volume:,.0f}' if m.avg_volume else 'unknown'} contracts, "
                f"avg open interest {f'{m.avg_open_interest:,.0f}' if m.avg_open_interest else 'unknown'}, "
                f"median open spread {f'{m.med_spread_cents:.0f}c' if m.med_spread_cents else 'unknown'}. "
                f"Catalog shows {m.n_open} open and {m.n_settled} settled markets."
            ),
            source="expansion_catalog",
            ref=f"expansion_market_snapshots/{m.series_ticker}",
            tags=["scalability", "scalability.absorption", "market_fit", "market_fit.flow"],
        ),
        Chunk(
            id=f"strat:{c.id}:ceiling",
            text=(
                f"Scale ceiling for {c.id}: {ceiling_range}; scaling path = {path}."
                + (" PROXY — real order-book depth is unmeasured (only top-of-book + 5-min "
                   "snapshots exist); run scripts/analysis/walk_book_capacity.py to measure."
                   if is_proxy else "")
                + " Measured Kalshi weather ceiling is ~500-700 contracts/city as a reference."
            ),
            source="capacity_proxy",
            ref="scripts/analysis/walk_book_synthetic.py",
            tags=["scalability", "scalability.ceiling", "scalability.decay"],
        ),
        Chunk(
            id=f"strat:{c.id}:fees",
            text=(
                f"Fees on {v.name}: taker {fee_cents(50, v.key)}c / maker "
                f"{fee_cents(50, v.key, maker=True)}c per contract at 50c. Single-name "
                "temperature/event brackets carry adverse selection (~33% per-trade return "
                "SD, ~13x the mean); one-sided order flow predicts maker losses — size down "
                "or step aside on toxic one-sided flow."
            ),
            source="venue_facts",
            ref="src/weather_markets/expansion/catalog.py",
            tags=["economics", "economics.fees", "economics.adverse_selection"],
        ),
        Chunk(
            id=f"strat:{c.id}:access",
            text=(
                f"Access {v.name}: {v.regulatory} API: {v.api}"
                + (f" Open questions: {'; '.join(v.open_questions)}" if v.open_questions else "")
            ),
            source="venue_facts",
            ref="src/weather_markets/expansion/catalog.py",
            tags=["access", "access.regulatory"],
        ),
    ]
    out.append(_flb_regime_chunk(m))
    return out


def strat_evidence_chunks(m: CandidateMetrics) -> list[Chunk]:
    c = m.candidate
    out: list[Chunk] = []
    if m.paper_n > 0:
        out.append(
            Chunk(
                id=f"strat:{c.id}:paper",
                text=(
                    f"Our own paper_trades for {c.id} (station {c.station_id or 'n/a'}): "
                    f"{m.paper_n} rows over {m.paper_span_days} days"
                    + (f", mean |edge| {m.paper_mean_abs_edge:.1%}." if m.paper_mean_abs_edge else ".")
                    + " Deploy bar: walk-forward OOS Sharpe > 2.5 on realistic execution."
                ),
                source="paper_trades",
                ref=f"paper_trades station={c.station_id}",
                tags=["our_evidence", "our_evidence.paper", "mechanism", "mechanism.oos"],
            )
        )
    else:
        out.append(
            Chunk(
                id=f"strat:{c.id}:noevidence",
                text=(
                    f"No internal paper/live evidence for {c.id} — we have never traded this "
                    "market. Any edge claim here is external-only; run a data probe / paper "
                    "period before sizing. This is the default for BTC and other liquid "
                    "non-weather markets."
                ),
                source="paper_trades",
                ref="paper_trades (none)",
                tags=["our_evidence", "our_evidence.paper", "testability", "testability.data"],
            )
        )
    out.append(
        Chunk(
            id=f"strat:{c.id}:capacity",
            text=(
                "Measured single-venue depth ceilings on Kalshi (capacity studies "
                "2026-06-29/07-05): ~500-700 contracts/city across all live cities; book "
                "liquidity, not order type, is the constraint. Breadth, not size, is the "
                "growth lever."
            ),
            source="capacity_findings",
            ref="docs/research/md (capacity studies)",
            tags=["scalability", "scalability.ceiling", "scalability.decay"],
        )
    )
    if c.prior:
        out.append(
            Chunk(
                id=f"strat:{c.id}:prior",
                text=f"Prior verdict on {c.id}: {c.prior}. Do not re-litigate without new data.",
                source="decisions",
                ref="docs/decisions/",
                tags=["our_evidence", "our_evidence.live"],
            )
        )
    return out


# ----- corpus lint (the guard against the Denver silent-drop failure) ---------

def lint_strategy_corpus(corpus_dir: str | Path = STRATEGY_CORPUS) -> list[str]:
    """Return a list of error strings (empty = clean). Enforces: every ``##``
    content section carries an explicit ``fp:`` tag; ``kind: guardrail`` sections
    carry a ``reverified:`` verdict (a 'don't' rule can't enter unverified)."""
    errors: list[str] = []
    d = Path(corpus_dir)
    if not d.is_dir():
        return errors  # no corpus yet is fine — engine just has no paper leg
    for f in sorted(d.rglob("*.md")):
        sections = re.split(r"\n(?=##? )", f.read_text(errors="replace"))
        for i, sec in enumerate(sections):
            text = sec.strip()
            if len(text) < 80 or not text.startswith("## "):
                continue
            heading = text.splitlines()[0]
            fp = parse_fp_comment(sec)
            if fp is None:
                errors.append(f"{f.name} §{i} {heading!r}: missing <!-- fp: ... --> tag")
            elif fp["kind"] == "guardrail" and not fp["reverified"]:
                errors.append(f"{f.name} §{i} {heading!r}: guardrail without reverified:")
    return errors


def build_strategy_retriever(
    m: CandidateMetrics, corpus_dirs: tuple[Path, ...] = (STRATEGY_CORPUS,)
) -> CompositeRetriever:
    """Assemble the 3 legs. Lints the corpus first and RAISES on any error — a
    silently-dropped or unverified section must never reach an assess run."""
    for d in corpus_dirs:
        errs = lint_strategy_corpus(d)
        if errs:
            raise ValueError("strategy corpus lint failed:\n  " + "\n  ".join(errs))
    return CompositeRetriever(
        [
            MockRetriever(strat_market_chunks(m) + strat_evidence_chunks(m)),
            MockRetriever(corpus_chunks(corpus_dirs, strict=True)),
        ]
    )
