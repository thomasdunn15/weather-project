from datetime import date
import httpx

from weather_markets.db import get_connection

def fetch_cf6_year(year: int, station_id: str = "KNYC") -> dict:

    if not isinstance(year, int):
        raise TypeError("Year must be an integer")
    if not 2000 <= year <= 2030:
        raise ValueError(f"year must be between 2000 and 2030, got {year}")

    url = "https://mesonet.agron.iastate.edu/json/cf6.py"
    response = httpx.get(
        url,
        params={"station": station_id, "year": year},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def parse_observations(raw_data: dict, station_id: str) -> list[tuple]:
    rows = []
    for entry in raw_data['results']:
        high = entry.get('high')
        if high is None:
            continue
        d = date.fromisoformat(entry['valid'])
        rows.append((d, station_id, float(high)))
    return rows

def insert_observations(rows: list[tuple], conn) -> int:
    if not rows:
        return 0
    
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO observations (date, station_id, high_temp_f)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
    
    return len(rows)
def ingest_observations(years: list[int], station_id: str = "KNYC") -> dict:
    
    per_year_results = {}
    
    for year in years:
        try:
            with get_connection() as conn:
                raw = fetch_cf6_year(year, station_id)
                rows = parse_observations(raw, station_id)
                count = insert_observations(rows, conn)
                per_year_results[year] = {
                    "status": "success",
                    "rows_inserted": count,
                }
                print(f"Year {year}: inserted {count} rows")
        except Exception as e:
            per_year_results[year] = {
                "status": "failed",
                "error": str(e),
            }
            print(f"Year {year}: FAILED - {e}")
    
    return {
        "station_id": station_id,
        "years_processed": list(years),
        "per_year": per_year_results,
    }