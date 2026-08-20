"""CF6 parse: 'M' (missing) values must not crash the year's ingest (KMIA 2026-07)."""
from datetime import date

from weather_markets.observations import parse_observations


def test_missing_markers_skipped_not_fatal():
    raw = {"results": [
        {"valid": "2026-07-07", "high": "M", "low": 78},   # missing high -> day skipped
        {"valid": "2026-07-08", "high": 91, "low": "M"},   # missing low -> low None
        {"valid": "2026-07-09", "high": 92, "low": 79},
    ]}
    assert parse_observations(raw, "KMIA") == [
        (date(2026, 7, 8), "KMIA", 91.0, None),
        (date(2026, 7, 9), "KMIA", 92.0, 79.0),
    ]
