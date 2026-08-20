"""Ops copilot: reasons over our own trading data (read-only) to surface
regime shifts, config drift, and execution anomalies as operator suggestions.

Reuses `weather_markets.reasoning` end to end for the matrix -> specialists ->
debate -> master loop — no orchestration lives here, only DB/Kalshi retrieval
and rendering. This package has no write path to trading whatsoever.
"""
from weather_markets.copilot.digest import build_evidence, render_digest, run_digest

__all__ = ["build_evidence", "render_digest", "run_digest"]
