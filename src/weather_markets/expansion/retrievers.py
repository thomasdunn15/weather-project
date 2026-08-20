"""Retriever backends for the B0 reasoning engine.

Three evidence sources, all emitted as tagged Chunks and scope-filtered by the
existing MockRetriever machinery (its scope+keyword filter is exactly what we
need — the *backends* here are real data, only the ranking stays naive):

- catalog_chunks:  synced expansion_* tables (per-candidate metrics)
- history_chunks:  our own paper_trades / capacity findings / venue facts
- corpus_chunks:   the domain doc corpus (docs/research, context, decisions,
                   plus drop-in docs/expansion/corpus/)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from weather_markets.expansion.candidates import REPO_ROOT
from weather_markets.expansion.catalog import VENUES, fee_cents
from weather_markets.expansion.scorecard import CandidateMetrics
from weather_markets.reasoning import Chunk, MockRetriever, Retriever

DEFAULT_CORPUS_DIRS = (
    REPO_ROOT / "docs" / "research" / "md",
    REPO_ROOT / "docs" / "context",
    REPO_ROOT / "docs" / "decisions",
    REPO_ROOT / "docs" / "expansion" / "corpus",
)

# focus-point tagging for doc sections, keyed by matrix ids
_TAG_KEYWORDS = {
    "data": ("gefs", "ifs ", "hrrr", "nwp", "herbie", "ingest", "nbm", "aifs", "grib"),
    "tract": ("emos", "calibrat", "gaussian", "bracket prob", "crps", "brier"),
    "resolution": ("settle", "resolution", "cli report", "nws", "settlement"),
    "market": ("liquidity", "depth", "volume", "spread", "capacity", "fill", "order book", "orderbook"),
    "fees": ("fee", "maker", "taker", "commission"),
    "durability": ("edge", "sharpe", "alpha", "decay", "efficien"),
    "capital": ("capital", "sizing", "kelly", "margin", "bankroll", "t+1", "withdraw"),
    "regulatory": ("cftc", "geoblock", "regulat", "jurisdiction", "us persons", "access"),
}
_MAX_CHUNK_CHARS = 1200
_MAX_EVIDENCE = 16  # cap per retrieve; candidate-specific chunks are listed first

_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)


def parse_fp_comment(section: str) -> dict | None:
    """Parse an explicit focus-point tag comment out of a markdown section.

    Convention (order-independent): ``<!-- fp: a, b | kind: guardrail |
    reverified: ... -->``. Returns {fp: [...], kind, reverified} for the first
    comment carrying an ``fp:`` field, else None. Used by the strategy corpus
    (explicit tags kill the silent-drop bug) and its linter.
    """
    for raw in _COMMENT_RE.findall(section):
        fields: dict[str, str] = {}
        for part in raw.split("|"):
            k, sep, v = part.partition(":")
            if sep:
                fields[k.strip().lower()] = v.strip()
        if "fp" in fields:
            return {
                "fp": [t.strip() for t in fields["fp"].split(",") if t.strip()],
                "kind": fields.get("kind") or None,
                "reverified": fields.get("reverified") or None,
            }
    return None


def catalog_chunks(m: CandidateMetrics) -> list[Chunk]:
    c = m.candidate
    out = [
        Chunk(
            id=f"cat:{c.id}:series",
            text=(
                f"Candidate {c.id} ({c.kind}, venue {m.venue.name}): series "
                f"{m.series_ticker or 'none'} '{m.series_title or '?'}'. Catalog shows "
                f"{m.n_open} open and {m.n_settled} settled markets. Settlement sources: "
                f"{', '.join(m.settlement_sources) or 'not listed on series'}."
            ),
            source="expansion_catalog",
            ref=f"expansion_series/{m.series_ticker}",
            tags=["resolution", "resolution.source", "data"],
        ),
        Chunk(
            id=f"cat:{c.id}:liquidity",
            text=(
                f"Liquidity for {c.id}: avg settled-market volume "
                f"{f'{m.avg_volume:,.0f}' if m.avg_volume else 'unknown'} contracts, "
                f"median open spread {f'{m.med_spread_cents:.0f}c' if m.med_spread_cents else 'unknown'}, "
                f"avg open interest {f'{m.avg_open_interest:,.0f}' if m.avg_open_interest else 'unknown'}."
            ),
            source="expansion_catalog",
            ref=f"expansion_market_snapshots/{m.series_ticker}",
            tags=["market", "market.depth", "market.spread", "market.volume"],
        ),
    ]
    v = m.venue
    out.append(
        Chunk(
            id=f"cat:{c.id}:venue",
            text=(
                f"Venue facts {v.name}: fees taker {fee_cents(50, v.key)}c / maker "
                f"{fee_cents(50, v.key, maker=True)}c per contract at 50c. API: {v.api} "
                f"Regulatory: {v.regulatory} Resolution: {v.resolution} "
                f"Capital cycle: {v.capital_cycle} Status: {v.status}"
                + (f" Open questions: {'; '.join(v.open_questions)}" if v.open_questions else "")
            ),
            source="venue_facts",
            ref="src/weather_markets/expansion/catalog.py",
            tags=["fees", "fees.maker", "regulatory", "regulatory.access",
                  "capital", "capital.cycle", "resolution", "resolution.timing"],
        )
    )
    return out


def history_chunks(m: CandidateMetrics) -> list[Chunk]:
    c = m.candidate
    out = [
        Chunk(
            id=f"hist:{c.id}:paper",
            text=(
                f"Our own trading history for station {c.station_id or 'n/a'}: "
                f"{m.paper_n} paper_trades rows spanning {m.paper_span_days} days"
                + (f", mean |edge| {m.paper_mean_abs_edge:.1%}." if m.paper_mean_abs_edge else ".")
                + " Deploy bar: walk-forward OOS Sharpe > 2.5 on realistic execution;"
                " every live city except Chicago/Miami is an operator override of that bar."
            ),
            source="paper_trades",
            ref=f"paper_trades station={c.station_id}",
            tags=["durability", "durability.evidence", "tract", "tract.emos"],
        ),
        Chunk(
            id=f"hist:{c.id}:capacity",
            text=(
                "Measured single-venue depth ceilings on Kalshi (capacity studies "
                "2026-06-29/07-05): ~500-700 contracts per city across all three live "
                "cities; book liquidity, not order type, is the constraint. Breadth, "
                "not size, is the growth lever."
            ),
            source="capacity_findings",
            ref="docs/research/md (capacity studies)",
            tags=["market", "market.depth", "capital"],
        ),
    ]
    if c.prior:
        out.append(
            Chunk(
                id=f"hist:{c.id}:prior",
                text=f"Prior verdict on {c.id}: {c.prior}. Do not re-litigate without new data.",
                source="decisions",
                ref="docs/decisions/",
                tags=["durability", "durability.evidence"],
            )
        )
    return out


def corpus_chunks(dirs: Sequence[Path] = DEFAULT_CORPUS_DIRS,
                  strict: bool = False) -> list[Chunk]:
    """Markdown corpus split by ## headings, tagged by focus-point.

    Two modes:
    - lenient (default): tags inferred from keywords; untagged sections dropped
      (they'd never be retrievable anyway). Used by the expansion corpus.
    - strict: every ``##`` content section MUST carry an explicit
      ``<!-- fp: ... -->`` tag; an untagged one RAISES instead of silently
      dropping. Used by the strategy corpus (whose tags are strategy_eval ids,
      which keyword inference can't produce). H1 title/preamble is exempt.
    """
    chunks: list[Chunk] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            sections = re.split(r"\n(?=##? )", f.read_text(errors="replace"))
            for i, sec in enumerate(sections):
                text = sec.strip()[:_MAX_CHUNK_CHARS]
                if len(text) < 80:
                    continue
                fp = parse_fp_comment(sec)
                if strict:
                    if not text.startswith("## "):
                        continue  # H1 title / preamble — not a tagged content section
                    if fp is None:
                        raise ValueError(
                            f"{f}: section {i} has no <!-- fp: ... --> tag (strict corpus)"
                        )
                    tags = fp["fp"]
                elif fp is not None:
                    tags = fp["fp"]
                else:
                    low = text.lower()
                    tags = [fp_ for fp_, kws in _TAG_KEYWORDS.items() if any(k in low for k in kws)]
                    if not tags:
                        continue
                chunks.append(
                    Chunk(
                        id=f"doc:{f.stem}:{i}",
                        text=text,
                        source="doc_corpus",
                        ref=str(f.relative_to(REPO_ROOT)) if f.is_relative_to(REPO_ROOT) else str(f),
                        tags=tags,
                    )
                )
    return chunks


class CompositeRetriever:
    """Concatenates backends in priority order, capped at _MAX_EVIDENCE chunks
    so specialist prompts stay bounded (cap is by order: candidate-specific
    catalog/history evidence first, doc corpus fills the remainder)."""

    def __init__(self, retrievers: Sequence[Retriever]) -> None:
        self.retrievers = list(retrievers)

    def retrieve(self, query: str, matrix_scope: Sequence[str]) -> list[Chunk]:
        out: list[Chunk] = []
        for r in self.retrievers:
            out.extend(r.retrieve(query, matrix_scope))
        return out[:_MAX_EVIDENCE]


def build_retriever(metrics: CandidateMetrics,
                    corpus_dirs: Sequence[Path] = DEFAULT_CORPUS_DIRS) -> CompositeRetriever:
    return CompositeRetriever(
        [
            MockRetriever(catalog_chunks(metrics) + history_chunks(metrics)),
            MockRetriever(corpus_chunks(corpus_dirs)),
        ]
    )
