"""
Forecast-only EMOS backtest. No contracts, no market — just (ensemble, observation) pairs.

For each day with paired data, do leave-one-out:
- Fit EMOS on the other days
- Predict the held-out day
- Compare to observation
"""
import math
import statistics
from datetime import datetime, date, timezone, timedelta

from weather_markets.db import get_connection
from weather_markets.aggregation import compute_daily_highs, fetch_observed_high
from weather_markets.emos import fit_emos, crps_gaussian


def collect_pairs(conn, model: str, start: date, end: date):
    """Walk dates, return parallel lists of (ensemble_mean, ensemble_std, observed, date)."""
    means, stds, obs, dates = [], [], [], []
    
    target_date = start
    while target_date <= end:
        init_time = datetime(target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=timezone.utc)
        
        try:
            highs = compute_daily_highs(init_time, target_date, conn, model=model)
        except Exception:
            target_date += timedelta(days=1)
            continue
        
        observation = fetch_observed_high(target_date, conn)
        if observation is None:
            target_date += timedelta(days=1)
            continue
        
        values = list(highs.values())
        if len(values) < 2:  # need at least 2 members for std
            target_date += timedelta(days=1)
            continue
        
        means.append(statistics.mean(values))
        stds.append(statistics.stdev(values))
        obs.append(observation)
        dates.append(target_date)
        
        target_date += timedelta(days=1)
    
    return means, stds, obs, dates


def main() -> None:
    start = date(2025, 5, 1)
    
    with get_connection() as conn:
        # Auto-detect end date from observations
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id = %s", ("KNYC",))
            end = cur.fetchone()[0]
        
        print(f"Collecting GEFS forecast/observation pairs from {start} to {end}...")
        means, stds, obs, dates = collect_pairs(conn, "gefs", start, end)
        n = len(means)
        print(f"Collected {n} paired days.\n")
        
        if n < 10:
            print("Not enough data to fit EMOS reliably.")
            return
        
        # === Compute baselines ===
        # Raw ensemble: prediction = ensemble_mean. Compare to obs.
        raw_errors = [abs(m - o) for m, o in zip(means, obs)]
        raw_mae = sum(raw_errors) / len(raw_errors)
        
        raw_signed_errors = [m - o for m, o in zip(means, obs)]
        raw_bias = sum(raw_signed_errors) / len(raw_signed_errors)
        
        # === Run leave-one-out EMOS ===
        emos_errors = []
        emos_crps_values = []
        emos_signed_errors = []
        
        for i in range(n):
            train_means = means[:i] + means[i+1:]
            train_stds = stds[:i] + stds[i+1:]
            train_obs = obs[:i] + obs[i+1:]
            
            params = fit_emos(train_means, train_stds, train_obs)
            
            corrected_mu = params['a'] + params['b'] * means[i]
            corrected_var = params['c'] + params['d'] * stds[i]**2
            
            if corrected_var <= 0:
                continue  # skip invalid days
            
            corrected_sigma = math.sqrt(corrected_var)
            
            emos_errors.append(abs(corrected_mu - obs[i]))
            emos_signed_errors.append(corrected_mu - obs[i])
            emos_crps_values.append(crps_gaussian(corrected_mu, corrected_sigma, obs[i]))
        
        emos_mae = sum(emos_errors) / len(emos_errors)
        emos_bias = sum(emos_signed_errors) / len(emos_signed_errors)
        emos_crps = sum(emos_crps_values) / len(emos_crps_values)
        
        # === Print summary ===
        print(f"=== Forecast-only backtest ({n} days, leave-one-out) ===\n")
        print(f"{'Metric':<25} {'Raw Ensemble':>15} {'EMOS LOO':>15}")
        print(f"{'-'*25} {'-'*15} {'-'*15}")
        print(f"{'Mean Absolute Error':<25} {raw_mae:>13.2f}°F  {emos_mae:>13.2f}°F")
        print(f"{'Mean Signed Error':<25} {raw_bias:>+13.2f}°F  {emos_bias:>+13.2f}°F")
        print(f"{'Mean CRPS':<25} {'—':>15} {emos_crps:>14.3f}")
        
        improvement = (raw_mae - emos_mae) / raw_mae * 100
        print(f"\nEMOS improvement on MAE: {improvement:+.1f}%")
        
        # === Fit on full data and show parameters ===
        print(f"\n=== Final EMOS parameters (fit on all {n} days) ===")
        final_params = fit_emos(means, stds, obs)
        print(f"  a = {final_params['a']:+.3f}  (additive shift)")
        print(f"  b = {final_params['b']:.3f}  (multiplicative scale on mean)")
        print(f"  c = {final_params['c']:+.3f}  (additive baseline for variance)")
        print(f"  d = {final_params['d']:.3f}  (multiplicative scale on variance)")
        
        # Show how this corrects a "typical" prediction
        test_mean = 70.0
        test_std = 2.0
        corrected_mu = final_params['a'] + final_params['b'] * test_mean
        corrected_var = final_params['c'] + final_params['d'] * test_std**2
        corrected_sigma = math.sqrt(corrected_var) if corrected_var > 0 else None
        
        print(f"\nExample: raw ensemble mean=70°F, std=2°F")
        print(f"  EMOS corrected: μ={corrected_mu:.2f}°F, σ={corrected_sigma:.2f}°F" if corrected_sigma else "")


if __name__ == "__main__":
    main()