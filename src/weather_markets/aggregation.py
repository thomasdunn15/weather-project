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
    bias_correction: float = 0.0,
    model: str = "gefs",
) -> dict[int, float]:

    sql = """
        SELECT member_id, MAX(tmax_f) AS daily_high_f
        FROM forecasts
        WHERE init_time = %s
          AND station_id = %s
          AND model = %s
          AND valid_time AT TIME ZONE %s >= %s::timestamp
          AND valid_time AT TIME ZONE %s <  (%s::date + interval '1 day')::timestamp
        GROUP BY member_id
        ORDER BY member_id
    """
    
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (init_time, station_id, model, timezone_name, target_date, timezone_name, target_date),
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

def compute_ensemble_probabilities(
    highs,  # dict[int, float] or list[float]
    contracts: list[dict],
) -> dict[str, float]:
    """..."""
    # Normalize input to a list of values
    if isinstance(highs, dict):
        values = list(highs.values())
    else:
        values = list(highs)
    
    if not values:
        raise ValueError("highs cannot be empty")
    
    n_members = len(values)
    result = {}
    for contract in contracts:
        yes_count = sum(1 for h in values if is_yes(h, contract))
        result[contract["ticker"]] = yes_count / n_members
    return result

def fetch_observed_high(
    target_date: date,
    conn,
    station_id: str = "KNYC",
) -> float | None:

    sql = """
        SELECT high_temp_f
        FROM observations
        WHERE date = %s AND station_id = %s
    """
    
    with conn.cursor() as cur:
        cur.execute(sql, (target_date, station_id))
        row = cur.fetchone()
    
    if row is None:
        return None
    
    return float(row[0])

def fetch_contracts_for_date(
    target_date: date,
    conn,
    station_id: str = "KNYC",
) -> list[dict]:
    """
    Fetch all Kalshi contracts whose target_date matches the given date.
    
    Returns:
        List of contract dicts with keys: ticker, bracket_type, strike_low, strike_high.
        Empty list if no contracts exist for that date.
    """

    sql = """
        SELECT ticker, bracket_type, strike_low, strike_high
        FROM contracts
        WHERE target_date = %s
          AND station_id = %s
        ORDER BY bracket_type, strike_low
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (target_date, station_id),
        )
        rows = cur.fetchall()

    return [
    {"ticker": t, "bracket_type": b, "strike_low": l, "strike_high": h}
    for t, b, l, h in rows
    ]

def compute_combined_daily_highs(
    init_time: datetime,
    target_date: date,
    conn,
    station_id: str = "KNYC",
    timezone_name: str = "America/New_York",
    models: list[str] | None = None,
) -> list[float]:
    """
    Compute daily highs across multiple models, returning a single combined list of values.
    
    Member IDs are not preserved (since they could collide across models).
    Returns a flat list of high values.
    """
    if models is None:
        models = ["gefs", "ifs"]
    
    all_values = []
    for model in models:
        try:
            highs = compute_daily_highs(
                init_time, target_date, conn,
                station_id=station_id,
                timezone_name=timezone_name,
                model=model,
            )
            all_values.extend(highs.values())
        except NoForecastDataError:
            continue  # OK if one model is missing
    
    if not all_values:
        raise NoForecastDataError(
            f"No forecast data for any model on {target_date} from {init_time}"
        )
    
    return all_values