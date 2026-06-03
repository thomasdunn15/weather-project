"""Daily ingestion of recent CF6 observation data for every registered station."""
from datetime import date
from weather_markets.observations import ingest_observations
from weather_markets.stations import all_stations


def main() -> None:
    years = [date.today().year]
    for station in all_stations():
        print(f"--- {station.station_id} ({station.city}) ---")
        try:
            result = ingest_observations(years=years, station_id=station.station_id)
            print(result)
        except Exception as e:
            print(f"  {station.station_id} ingest raised: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
