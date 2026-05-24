"""Fit EMOS parameters on historical paired forecasts and observations."""
import statistics
from datetime import datetime, date, timezone, timedelta

from weather_markets.db import get_connection
from weather_markets.aggregation import compute_daily_highs, fetch_observed_high
from weather_markets.emos import fit_emos


def main() -> None:
    start = date(2026, 5, 5)
    
    training_means = []
    training_stds = []
    training_obs = []
    
    with get_connection() as conn:
        # Auto-detect end date
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                ("KNYC",),
            )
            end = cur.fetchone()[0]
        
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
            training_means.append(statistics.mean(values))
            training_stds.append(statistics.stdev(values))
            training_obs.append(observation)
            
            print(
                f"{target_date}: "
                f"mean={training_means[-1]:6.2f}, "
                f"std={training_stds[-1]:.2f}, "
                f"obs={observation}"
            )
            
            target_date += timedelta(days=1)
    
    print(f"\nFitting EMOS on {len(training_obs)} days...")
    result = fit_emos(training_means, training_stds, training_obs)
    
    print(f"\nFitted parameters:")
    print(f"  a = {result['a']:+.3f}  (additive shift on mean)")
    print(f"  b = {result['b']:.3f}  (multiplicative scale on mean)")
    print(f"  c = {result['c']:+.3f}  (additive baseline for variance)")
    print(f"  d = {result['d']:.3f}  (multiplicative scale on variance)")
    print(f"  Final total CRPS: {result['final_crps']:.2f}")
    
    # Show what EMOS does for each training day
    print(f"\nTraining day predictions (corrected):")
    print(f"{'Date':<12} {'Raw mean':>10} {'EMOS μ':>10} {'EMOS σ':>10} {'Obs':>6}")
    print(f"{'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*6}")
    
    a, b, c, d = result['a'], result['b'], result['c'], result['d']
    target_date = start
    i = 0
    while target_date <= end and i < len(training_means):
        m = training_means[i]
        s = training_stds[i]
        obs = training_obs[i]
        
        corrected_mu = a + b * m
        corrected_var = c + d * s**2
        corrected_sigma = corrected_var ** 0.5
        
        print(
            f"{str(target_date):<12} "
            f"{m:>10.2f} "
            f"{corrected_mu:>10.2f} "
            f"{corrected_sigma:>10.2f} "
            f"{obs:>6.0f}"
        )
        
        i += 1
        target_date += timedelta(days=1)


if __name__ == "__main__":
    main()