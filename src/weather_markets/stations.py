"""Weather-station registry.

One entry per (city, contract series) pair we trade. Adding a new city is a
config entry here — no code changes anywhere else.

Each station has:
  - station_id: NWS station code used in observations CF6 reports (KNYC, KORD, ...)
  - latitude / longitude: for forecast grid lookups (GEFS, IFS, HRRR)
  - kalshi_series: Kalshi series ticker for daily-HIGH contracts on this station
  - timezone: IANA zone, used for solar-day boundary in aggregation
  - tz_abbr: short label for dashboard display

Conventions:
  - Lat/lon are for the station itself (where observations are recorded)
  - We round to ~0.05° in code; forecast grids are 0.25° (GEFS) and 0.4° (IFS)
    so finer precision than that doesn't help
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    station_id: str         # NWS code (also primary key in our DB)
    city: str               # display name
    latitude: float
    longitude: float
    kalshi_series: str      # Kalshi series ticker for KX HIGH daily contracts
    timezone: str           # IANA zone
    tz_abbr: str            # short label, used by aggregation for solar-day cutoff


# All stations we currently model. To add a new city, add an entry here and
# (separately) backfill its observations + forecasts.
STATIONS: dict[str, Station] = {
    "KNYC": Station(
        station_id="KNYC",
        city="New York",
        latitude=40.78,
        longitude=-73.97,
        kalshi_series="KXHIGHNY",
        timezone="America/New_York",
        tz_abbr="ET",
    ),
    "KORD": Station(
        station_id="KORD",
        city="Chicago",
        latitude=41.99,
        longitude=-87.93,
        kalshi_series="KXHIGHCHI",
        timezone="America/Chicago",
        tz_abbr="CT",
    ),
    "KMIA": Station(
        station_id="KMIA",
        city="Miami",
        latitude=25.79,
        longitude=-80.29,
        kalshi_series="KXHIGHMIA",
        timezone="America/New_York",
        tz_abbr="ET",
    ),
    "KAUS": Station(
        station_id="KAUS",
        city="Austin",
        latitude=30.19,
        longitude=-97.67,
        kalshi_series="KXHIGHAUS",
        timezone="America/Chicago",
        tz_abbr="CT",
    ),
    "KDEN": Station(
        station_id="KDEN",
        city="Denver",
        latitude=39.86,
        longitude=-104.67,
        kalshi_series="KXHIGHDEN",
        timezone="America/Denver",
        tz_abbr="MT",
    ),
    "KLAX": Station(
        station_id="KLAX",
        city="Los Angeles",
        latitude=33.94,
        longitude=-118.41,
        kalshi_series="KXHIGHLAX",
        timezone="America/Los_Angeles",
        tz_abbr="PT",
    ),
}


def get(station_id: str) -> Station:
    """Look up a station by NWS code. Raises KeyError on unknown station."""
    try:
        return STATIONS[station_id]
    except KeyError:
        known = ", ".join(sorted(STATIONS))
        raise KeyError(f"unknown station {station_id!r}; known: {known}") from None


def all_stations() -> list[Station]:
    """All registered stations, in deterministic order."""
    return [STATIONS[k] for k in sorted(STATIONS)]
