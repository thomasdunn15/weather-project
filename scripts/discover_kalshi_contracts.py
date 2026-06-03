# scripts/discover_kalshi_contracts.py
"""Discover currently-active Kalshi daily-high contracts for every registered station."""
from weather_markets.kalshi import discover_kalshi_contracts
from weather_markets.stations import all_stations


def main() -> None:
    for station in all_stations():
        print(f"--- {station.station_id} / {station.kalshi_series} ({station.city}) ---")
        try:
            result = discover_kalshi_contracts(
                series_ticker=station.kalshi_series,
                station_id=station.station_id,
            )
            print(result)
        except Exception as e:
            print(f"  {station.station_id} discover raised: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
