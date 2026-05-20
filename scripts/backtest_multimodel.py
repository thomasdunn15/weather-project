"""
Six-way forecast comparison over the full year.

Compares raw vs EMOS for GEFS, ECMWF, and combined ensembles.
Metrics: MAE (accuracy of mean) and CRPS (overall probabilistic quality).

EMOS is fit once on all available days (fit-once rather than LOO).
With ~365 days, each day contributes <0.3% to the fit, so this is
effectively out-of-sample.
"""
import math
import statistics
from datetime import datetime, date, timezone, timedelta

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_daily_highs,
    compute_combined_daily_highs,
    fetch_observed_high,
)
from weather_markets.emos import fit_emos, crps_gaussian


def collect_ensemble_stats(conn, source: str, start: date, end: date):
    """
    For each day, compute ensemble (mean, std) for the given source.
    
    source is one of: 'gefs', 'ifs', 'combined'.
    
    Returns parallel lists (means, stds, obs, dates) for days where
    this source AND an observation exist.
    """
    means, stds, obs, dates = [], [], [], []
    
    target_date = start
    while target_date <= end:
        init_time = datetime(
            target_date.year, target_date.month, target_date.day,
            12, 0, tzinfo=timezone.utc,
        )
        
        try:
            if source == "combined":
                values = compute_combined_daily_highs(init_time, target_date, conn)
            else:
                highs = compute_daily_highs(init_time, target_date, conn, model=source)
                values = list(highs.values())
        except Exception:
            target_date += timedelta(days=1)
            continue
        
        if len(values) < 2:
            target_date += timedelta(days=1)
            continue
        
        observation = fetch_observed_high(target_date, conn)
        if observation is None:
            target_date += timedelta(days=1)
            continue
        
        means.append(statistics.mean(values))
        stds.append(statistics.stdev(values))
        obs.append(observation)
        dates.append(target_date)
        
        target_date += timedelta(days=1)
    
    return means, stds, obs, dates


def evaluate_source(conn, source: str, start: date, end: date) -> dict:
    """
    Compute raw and EMOS metrics for one ensemble source.
    
    Returns dict with raw_mae, raw_bias, emos_mae, emos_bias, emos_crps, n_days.
    """
    means, stds, obs, dates = collect_ensemble_stats(conn, source, start, end)
    n = len(means)
    
    if n < 10:
        return {"source": source, "n_days": n, "error": "insufficient data"}
    
    # Raw metrics (prediction = ensemble mean)
    raw_abs_errors = [abs(m - o) for m, o in zip(means, obs)]
    raw_signed = [m - o for m, o in zip(means, obs)]
    raw_mae = sum(raw_abs_errors) / n
    raw_bias = sum(raw_signed) / n
    
    # Raw CRPS (treat ensemble as Gaussian with its own mean/std, no correction)
    raw_crps_values = []
    for m, s, o in zip(means, stds, obs):
        if s > 0:
            raw_crps_values.append(crps_gaussian(m, s, o))
    raw_crps = sum(raw_crps_values) / len(raw_crps_values) if raw_crps_values else None
    
    # Fit EMOS once on all data
    params = fit_emos(means, stds, obs)
    
    # EMOS metrics
    emos_abs_errors = []
    emos_signed = []
    emos_crps_values = []
    
    for m, s, o in zip(means, stds, obs):
        corrected_mu = params['a'] + params['b'] * m
        corrected_var = params['c'] + params['d'] * s**2
        if corrected_var <= 0:
            continue
        corrected_sigma = math.sqrt(corrected_var)
        emos_abs_errors.append(abs(corrected_mu - o))
        emos_signed.append(corrected_mu - o)
        emos_crps_values.append(crps_gaussian(corrected_mu, corrected_sigma, o))
    
    emos_mae = sum(emos_abs_errors) / len(emos_abs_errors)
    emos_bias = sum(emos_signed) / len(emos_signed)
    emos_crps = sum(emos_crps_values) / len(emos_crps_values)
    
    return {
        "source": source,
        "n_days": n,
        "raw_mae": raw_mae,
        "raw_bias": raw_bias,
        "raw_crps": raw_crps,
        "emos_mae": emos_mae,
        "emos_bias": emos_bias,
        "emos_crps": emos_crps,
        "params": params,
    }


def main() -> None:
    start = date(2025, 5, 1)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM observations WHERE station_id = %s",
                ("KNYC",),
            )
            end = cur.fetchone()[0]
        
        print(f"Evaluating sources from {start} to {end}...\n")
        
        results = []
        for source in ["gefs", "ifs", "combined"]:
            print(f"Processing {source}...")
            r = evaluate_source(conn, source, start, end)
            results.append(r)
    
    # Print comparison table
    print("\n" + "=" * 70)
    print("MAE COMPARISON (lower = more accurate mean prediction)")
    print("=" * 70)
    print(f"{'Source':<12} {'Days':>6} {'Raw MAE':>10} {'EMOS MAE':>10} {'Improvement':>12}")
    print(f"{'-'*12} {'-'*6} {'-'*10} {'-'*10} {'-'*12}")
    for r in results:
        if "error" in r:
            print(f"{r['source']:<12} {r['n_days']:>6} {'(insufficient data)':>34}")
            continue
        imp = (r['raw_mae'] - r['emos_mae']) / r['raw_mae'] * 100
        print(f"{r['source']:<12} {r['n_days']:>6} {r['raw_mae']:>9.2f}° {r['emos_mae']:>9.2f}° {imp:>+11.1f}%")
    
    print("\n" + "=" * 70)
    print("CRPS COMPARISON (lower = better probabilistic forecast)")
    print("=" * 70)
    print(f"{'Source':<12} {'Raw CRPS':>10} {'EMOS CRPS':>11} {'Improvement':>12}")
    print(f"{'-'*12} {'-'*10} {'-'*11} {'-'*12}")
    for r in results:
        if "error" in r:
            continue
        imp = (r['raw_crps'] - r['emos_crps']) / r['raw_crps'] * 100
        print(f"{r['source']:<12} {r['raw_crps']:>9.3f} {r['emos_crps']:>10.3f} {imp:>+11.1f}%")
    
    print("\n" + "=" * 70)
    print("BIAS (raw, should be near zero after EMOS)")
    print("=" * 70)
    print(f"{'Source':<12} {'Raw Bias':>10} {'EMOS Bias':>11}")
    print(f"{'-'*12} {'-'*10} {'-'*11}")
    for r in results:
        if "error" in r:
            continue
        print(f"{r['source']:<12} {r['raw_bias']:>+9.2f}° {r['emos_bias']:>+10.2f}°")
    
    print("\n" + "=" * 70)
    print("EMOS PARAMETERS")
    print("=" * 70)
    for r in results:
        if "error" in r:
            continue
        p = r['params']
        print(f"{r['source']:<12} a={p['a']:+.2f}  b={p['b']:.3f}  c={p['c']:+.2f}  d={p['d']:+.3f}")


if __name__ == "__main__":
    main()