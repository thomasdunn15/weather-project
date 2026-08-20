"""Candidate registry: seed file + auto-discovery from the synced catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from weather_markets.stations import STATIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = REPO_ROOT / "docs" / "expansion" / "candidates.yaml"


class Candidate(BaseModel):
    id: str
    venue: str                                  # key into catalog.VENUES
    kind: Literal["city", "venue-port", "category"]
    station_id: str | None = None
    series_ticker: str | None = None            # falls back to STATIONS mapping
    underlying: str = "daily_high_temp"
    prior: str | None = None                    # earlier verdict — don't re-litigate
    notes: str = ""

    def resolved_series(self) -> str | None:
        if self.series_ticker:
            return self.series_ticker
        if self.station_id and self.station_id in STATIONS:
            return STATIONS[self.station_id].kalshi_series
        return None


def load_candidates(path: str | Path = DEFAULT_REGISTRY) -> list[Candidate]:
    data = yaml.safe_load(Path(path).read_text()) or []
    out = [Candidate.model_validate(d) for d in data]
    ids = [c.id for c in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate candidate ids in {path}")
    return out


def discover_kalshi_candidates(conn, known: list[Candidate]) -> list[Candidate]:
    """Kalshi weather series in the synced catalog that nothing tracks yet:
    temperature series not mapped to a STATIONS entry become city candidates,
    everything else in the category becomes a category candidate."""
    tracked = {
        s
        for st in STATIONS.values()
        for s in (st.kalshi_series, getattr(st, "kalshi_series_low", None))
        if s
    }
    tracked |= {c.resolved_series() for c in known if c.resolved_series()}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT series_ticker, title FROM expansion_series WHERE venue = 'kalshi'"
        )
        rows = cur.fetchall()
    out = []
    for ticker, title in rows:
        if ticker in tracked:
            continue
        is_temp = ticker.startswith(("KXHIGH", "KXLOW"))
        out.append(
            Candidate(
                id=f"kalshi-{ticker.lower()}",
                venue="kalshi",
                kind="city" if is_temp else "category",
                series_ticker=ticker,
                underlying="daily_temp" if is_temp else "unknown",
                notes=f"auto-discovered from catalog: {title or ticker}",
            )
        )
    return out
