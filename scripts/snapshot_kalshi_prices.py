# scripts/snapshot_kalshi_prices.py
"""Snapshot current prices for every registered station's daily-high series."""
from weather_markets.kalshi import snapshot_kalshi_prices
from weather_markets.stations import all_stations


def main() -> None:
    for station in all_stations():
        try:
            result = snapshot_kalshi_prices(series_ticker=station.kalshi_series)
            print(f"{station.station_id} / {station.kalshi_series}: {result}")
        except Exception as e:
            print(f"  {station.station_id} snapshot raised: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
