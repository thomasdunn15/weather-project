"""Backfill historical CF6 observation data for KNYC."""
from datetime import date
from weather_markets.observations import ingest_observations


def main() -> None:
    current_year = date.today().year
    years = list(range(current_year - 3, current_year + 1))
    
    print(f"Backfilling years: {years}")
    result = ingest_observations(years=years)
    print(result)


if __name__ == "__main__":
    main()