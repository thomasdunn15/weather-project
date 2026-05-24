"""In-sample backtest using EMOS-corrected forecasts. Optimistically biased."""
import math
import statistics
from datetime import datetime, date, timezone, timedelta

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_daily_highs,
    fetch_observed_high,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos, gaussian_to_bracket_probs
from weather_markets.evaluation import evaluate_predictions


def collect_training_data(conn, start: date, end: date):
    """Walk dates, return parallel lists of means, stds, observations, and per-day metadata."""
    means, stds, obs, dates = [], [], [], []
    
    target_date = start
    while target_date <= end:
        init_time = datetime(
            target_date.year, target_date.month, target_date.day,
            12, 0, tzinfo=timezone.utc,
        )
        
        try:
            highs = compute_daily_highs(init_time, target_date, conn)
        except Exception:
            target_date += timedelta(days=1)
            continue
        
        observation = fetch_observed_high(target_date, conn)
        if observation is None:
            target_date += timedelta(days=1)
            continue
        
        values = list(highs.values())
        means.append(statistics.mean(values))
        stds.append(statistics.stdev(values))
        obs.append(observation)
        dates.append(target_date)
        
        target_date += timedelta(days=1)
    
    return means, stds, obs, dates


def main() -> None:
    start = date(2026, 5, 5)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                ("KNYC",),
            )
            end = cur.fetchone()[0]
        
        # Collect training data
        means, stds, obs, dates = collect_training_data(conn, start, end)
        
        # Fit EMOS on all data
        params = fit_emos(means, stds, obs)
        print(f"Fitted: a={params['a']:.3f} b={params['b']:.3f} c={params['c']:.3f} d={params['d']:.3f}")
        print()
        
        # Apply EMOS to each day and compute Brier
        print(f"{'Date':<12} {'EMOS μ':>8} {'EMOS σ':>8} {'Obs':>5} {'Brier':>8}")
        print(f"{'-'*12} {'-'*8} {'-'*8} {'-'*5} {'-'*8}")
        
        total_brier = 0
        count = 0
        for d, m, s, o in zip(dates, means, stds, obs):
            corrected_mu = params['a'] + params['b'] * m
            corrected_var = params['c'] + params['d'] * s**2
            
            if corrected_var <= 0:
                print(f"{str(d):<12} INVALID sigma squared")
                continue
            
            corrected_sigma = math.sqrt(corrected_var)
            
            contracts = fetch_contracts_for_date(d, conn)
            if not contracts:
                continue
            
            probs = gaussian_to_bracket_probs(corrected_mu, corrected_sigma, contracts)
            scores = evaluate_predictions(probs, contracts, int(o))
            
            mean_brier = sum(scores.values()) / len(scores)
            total_brier += mean_brier
            count += 1
            
            print(f"{str(d):<12} {corrected_mu:>8.2f} {corrected_sigma:>8.2f} {o:>5.0f} {mean_brier:>8.4f}")
        
        if count > 0:
            print(f"\nOverall mean Brier across {count} days: {total_brier/count:.4f}")
            print(f"Compare to raw ensemble mean Brier: 0.1102")


if __name__ == "__main__":
    main()