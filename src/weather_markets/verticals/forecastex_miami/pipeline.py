"""Paper pipeline for forecastex-miami: ingest -> EMOS -> blend -> evaluate -> paper log.

Reuses the production library end to end; the TODOs are the vertical-specific
gaps, not new architecture. Run stages via:
    uv run python -m weather_markets.verticals.forecastex_miami.pipeline
"""

from __future__ import annotations

from datetime import date

from weather_markets.aggregation import compute_combined_daily_highs, fetch_contracts_for_date
from weather_markets.db import get_connection
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.verticals.forecastex_miami.config import VERTICAL_CONFIG

STATION = 'KMIA'


def ingest() -> None:
    """TODO: ensure daily forecast + observation ingest covers this vertical.
    For temperature verticals on an existing station this is already done by
    the production crons (scripts/ingest_*); a NEW station needs a STATIONS
    entry + backfill; a new underlying needs a new ingest module."""
    raise NotImplementedError


def signal(target: date) -> dict | None:
    """EMOS -> bracket probs -> blend -> edge, exactly the production shapes.
    TODO: adapt model list / underlying field for this vertical, then mirror
    scripts/paper_trade_log.py's insert into paper_trades (that table IS the
    validation record the backtest consumes)."""
    cfg = next(iter(VERTICAL_CONFIG.values()))
    conn = get_connection()
    try:
        highs = compute_combined_daily_highs(conn, STATION, target, cfg["models"])
        mu_sigma = fit_emos_rolling(conn, STATION, target, cfg["models"])
        contracts = fetch_contracts_for_date(conn, cfg["series_ticker"], target)
        probs = gaussian_to_bracket_probs(mu_sigma, contracts)
        # TODO: market mid + Benter blend (weather_markets.blend) + edge vs threshold
        return {"target": target, "probs": probs, "highs": highs}
    finally:
        conn.close()


if __name__ == "__main__":
    print(signal(date.today()))
