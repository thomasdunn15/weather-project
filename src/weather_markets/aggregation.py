"""
Aggregation functions for ensemble forecasts.
"""
from datetime import date, datetime

class NoForecastDataError(Exception):
    """Raised when no forecast data exists for the requested query."""
    pass

def compute_daily_highs(
    init_time: datetime,
    target_date: date,
    conn,
    station_id: str = "KNYC",
    timezone_name: str = "America/New_York",
) -> dict[int, float]:

    sql = """
        SELECT member_id, MAX(tmax_f) AS daily_high_f
        FROM forecasts
        WHERE init_time = %s
          AND station_id = %s
          AND valid_time AT TIME ZONE %s >= %s::timestamp
          AND valid_time AT TIME ZONE %s <  (%s::date + interval '1 day')::timestamp
        GROUP BY member_id
        ORDER BY member_id
    """
    
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (init_time, station_id, timezone_name, target_date, timezone_name, target_date),
        )
        rows = cur.fetchall()
    
    if not rows:
        raise NoForecastDataError(
            f"No forecasts for init_time={init_time}, "
            f"target_date={target_date}, station_id={station_id}"
        )
    
    return {member_id: high for member_id, high in rows}

def is_yes(high, contract):
    bracket_type = contract["bracket_type"]
    if bracket_type == "greater_than":
        return high >= contract["strike_low"] + 1
    elif bracket_type == "less_than":
        return high < contract["strike_high"]
    elif bracket_type == "between":
        return (
            contract["strike_low"] <= high 
            and high < contract["strike_high"] + 1
        )
    else:
        raise ValueError(f"Unknown bracket_type: {bracket_type!r}")

def compute_ensemble_probabilities(highs, contracts):
    if not highs:
        raise ValueError("highs cannot be empty")
    
    n_members = len(highs)
    result = {}
    for contract in contracts:
        yes_count = sum(1 for h in highs.values() if is_yes(h, contract))
        result[contract["ticker"]] = yes_count / n_members
    return result
