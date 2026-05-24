"""
Leave-one-out cross-validation for EMOS.

This is the honest out-of-sample evaluation: for each day, fit EMOS on 
the other 12 days, then evaluate predictions on the held-out day. 
The resulting Brier score reflects how EMOS would perform on truly 
unseen data, not data it's already been trained on.
"""
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
    """
    Walk dates, return parallel lists of (means, stds, observations, dates).
    Same helper used in the in-sample script.
    """
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
        # Find the latest date with an observation
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                ("KNYC",),
            )
            end = cur.fetchone()[0]
        
        # Get all training data first
        means, stds, obs, dates = collect_training_data(conn, start, end)
        n = len(means)
        print(f"Collected {n} days of training data: {dates[0]} to {dates[-1]}\n")
        
        # Print header
        print(f"{'Date':<12} {'EMOS μ':>8} {'EMOS σ':>8} {'Obs':>5} {'Brier':>8}")
        print(f"{'-'*12} {'-'*8} {'-'*8} {'-'*5} {'-'*8}")
        
        total_brier = 0.0
        count = 0
        
        # For each day, leave it out, fit on the rest, evaluate on the held-out day
        for i in range(n):
            held_out_date = dates[i]
            held_out_mean = means[i]
            held_out_std = stds[i]
            held_out_obs = obs[i]
            
            # Build training set without index i
            train_means = means[:i] + means[i+1:]
            train_stds = stds[:i] + stds[i+1:]
            train_obs = obs[:i] + obs[i+1:]
            
            # Fit EMOS on the remaining 12 days
            params = fit_emos(train_means, train_stds, train_obs)
            
            # Apply fitted params to the held-out day's raw ensemble stats
            corrected_mu = params['a'] + params['b'] * held_out_mean
            corrected_var = params['c'] + params['d'] * held_out_std**2
            
            if corrected_var <= 0:
                print(f"{str(held_out_date):<12} SKIPPED: invalid variance")
                continue
            
            corrected_sigma = math.sqrt(corrected_var)
            
            # Compute Brier on the held-out day using its actual contracts
            contracts = fetch_contracts_for_date(held_out_date, conn)
            if not contracts:
                print(f"{str(held_out_date):<12} SKIPPED: no contracts")
                continue
            
            probs = gaussian_to_bracket_probs(corrected_mu, corrected_sigma, contracts)
            scores = evaluate_predictions(probs, contracts, int(held_out_obs))
            
            mean_brier = sum(scores.values()) / len(scores)
            total_brier += mean_brier
            count += 1
            
            print(
                f"{str(held_out_date):<12} "
                f"{corrected_mu:>8.2f} "
                f"{corrected_sigma:>8.2f} "
                f"{held_out_obs:>5.0f} "
                f"{mean_brier:>8.4f}"
            )
        
        if count > 0:
            avg_brier = total_brier / count
            print(f"\nLeave-one-out mean Brier across {count} days: {avg_brier:.4f}")
            print(f"\nComparison:")
            print(f"  Raw ensemble:      0.1102")
            print(f"  EMOS in-sample:    0.0831")
            print(f"  EMOS LOO (honest): {avg_brier:.4f}")


if __name__ == "__main__":
    main()