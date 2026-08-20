"""B1 breadth scout: catalog adapters + opportunity scoring + vertical bootstrap.

Research-and-discovery only — nothing in here places orders or is imported by
the live pipeline. The reasoning loop itself is weather_markets.reasoning (B0);
this package supplies Retriever backends, the opportunity matrix data, and the
deterministic scorecard around it.
"""

from weather_markets.expansion.candidates import Candidate, discover_kalshi_candidates, load_candidates
from weather_markets.expansion.catalog import VENUES, fee_cents, sync_kalshi_catalog
from weather_markets.expansion.retrievers import CompositeRetriever, build_retriever
from weather_markets.expansion.scorecard import CandidateMetrics, Scorecard, collect_metrics, score

__all__ = [
    "Candidate",
    "CandidateMetrics",
    "CompositeRetriever",
    "Scorecard",
    "VENUES",
    "build_retriever",
    "collect_metrics",
    "discover_kalshi_candidates",
    "fee_cents",
    "load_candidates",
    "score",
    "sync_kalshi_catalog",
]
