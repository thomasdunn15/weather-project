# scripts/discover_kalshi_contracts.py
"""Discover currently-active Kalshi daily-high AND daily-low contracts.

Lows added 2026-08-24, alongside the matching change in snapshot_kalshi_prices.py.
Order matters between the two: prices carry a foreign key onto contracts, so a
KXLOWT price row is rejected until its contract exists. Discovery runs 14:30 UTC,
the price snapshot every 5 minutes, so discovery always leads.
"""
from weather_markets.kalshi import discover_kalshi_contracts
from weather_markets.stations import all_stations


def main() -> None:
    for station in all_stations():
        # "" where that side has no Kalshi market (KMDW/KSFO have no high;
        # KSFO and several others have no low series listed).
        for series in (station.kalshi_series, station.kalshi_series_low):
            if not series:
                continue
            print(f"--- {station.station_id} / {series} ({station.city}) ---")
            try:
                result = discover_kalshi_contracts(
                    series_ticker=series,
                    station_id=station.station_id,
                )
                print(result)
            except Exception as e:
                print(f"  {station.station_id} / {series} discover raised: "
                      f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
