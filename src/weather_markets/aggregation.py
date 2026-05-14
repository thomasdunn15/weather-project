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
    """
    Compute the predicted daily high temperature (°F) for each ensemble member.
    
    For each member, the daily high is the maximum of tmax_f over all forecasts
    whose valid_time falls within the target_date in the specified timezone.
    
    Args:
        init_time: The GEFS run init_time (timezone-aware).
        target_date: The local-day date to compute highs for.
        conn: An open psycopg connection.
        station_id: Station identifier (default: KNYC).
        timezone_name: IANA timezone name (default: America/New_York).
    
    Returns:
        Dict mapping member_id to predicted daily high in °F.
    
    Raises:
        NoForecastDataError: If no forecasts exist for the given inputs.
    """
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