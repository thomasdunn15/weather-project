from datetime import datetime, date, timezone
from weather_markets.db import get_connection

from weather_markets.aggregation import (
    compute_daily_highs,
    compute_ensemble_probabilities,
    fetch_contracts_for_date,
    fetch_observed_high,
    NoForecastDataError,
)

from weather_markets.evaluation import evaluate_predictions

def backtest_day(
    target_date: date,
    init_time: datetime,
    conn,
) -> dict | None:
    """
    Score a single target_date using forecasts from init_time.
    
    Returns None if data is missing (forecast, observation, or contracts).
    Returns a result dict otherwise.
    """
    try:
        highs = compute_daily_highs(init_time, target_date, conn)
    except NoForecastDataError:
        return None
    
    observed = fetch_observed_high(target_date, conn)
    if observed is None:
        return None
    
    contracts = fetch_contracts_for_date(target_date, conn)
    if not contracts:
        return None
    
    probs = compute_ensemble_probabilities(highs, contracts)
    scores = evaluate_predictions(probs, contracts, observed)
    
    return {
        "target_date": target_date,
        "init_time": init_time,
        "observed": observed,
        "n_contracts": len(contracts),
        "mean_brier": sum(scores.values()) / len(scores),
        "scores": scores,
    }

def backtest_range(
    target_dates: list[date],
    init_time_offset_hours: int,
    conn,
) -> list[dict]:
    """
    For each target_date, use the 12 UTC of target_date as init_time.
    
    Skips dates with missing data.
    """
    results = []
    for target_date in target_dates:
        init_time = datetime.combine(
            target_date, 
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).replace(hour=12)
        
        result = backtest_day(target_date, init_time, conn)
        if result is not None:
            results.append(result)
    
    return results

def backtest_range(
    target_dates: list[date],
    conn,
) -> list[dict]:
    """
    Run backtest_day for each target_date using the 12 UTC of that date as init_time.
    
    Skips dates with missing forecasts/observations/contracts.
    
    Returns list of result dicts (one per successfully backtested day).
    """
    results = []
    for target_date in target_dates:
        init_time = datetime.combine(
            target_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).replace(hour=12)
        
        result = backtest_day(target_date, init_time, conn)
        if result is not None:
            results.append(result)
    
    return results