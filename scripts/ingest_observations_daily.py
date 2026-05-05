"""Daily ingestion of recent CF6 observation data for KNYC."""
from datetime import date
from weather_markets.observations import ingest_observations


def main() -> None:
    result = ingest_observations(years=[date.today().year])
    print(result)


if __name__ == "__main__":
    main()