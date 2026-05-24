"""Compare EMOS (fit on 199 days) vs Kalshi market over 13 days.

Uses the year-long EMOS parameters for better-calibrated predictions
than the previous 13-day LOO approach.
"""
import math
import statistics
from datetime import datetime, date, timezone, timedelta

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_daily_highs,
    compute_ensemble_probabilities,
    fetch_observed_high,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos, gaussian_to_bracket_probs
from weather_markets.evaluation import (
    evaluate_predictions,
    contract_resolved_yes,
    brier_score,
)


def collect_pairs(conn, model: str, start: date, end: date):
    """Same helper as forecast_only backtest."""
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
        if len(values) < 2:
            target_date += timedelta(days=1)
            continue
        
        means.append(statistics.mean(values))
        stds.append(statistics.stdev(values))
        obs.append(observation)
        dates.append(target_date)
        
        target_date += timedelta(days=1)
    
    return means, stds, obs, dates


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id = %s", ("KNYC",))
            max_obs_date = cur.fetchone()[0]
        
        # Step 1: Collect ALL training data and fit EMOS once
        print(f"Collecting all GEFS training data...")
        all_means, all_stds, all_obs, all_dates = collect_pairs(
            conn, "gefs", date(2025, 5, 1), max_obs_date
        )
        print(f"Training on {len(all_means)} paired days.\n")
        
        emos_params = fit_emos(all_means, all_stds, all_obs)
        print(f"EMOS parameters:")
        print(f"  a = {emos_params['a']:+.3f}")
        print(f"  b = {emos_params['b']:.3f}")
        print(f"  c = {emos_params['c']:+.3f}")
        print(f"  d = {emos_params['d']:.3f}\n")
        
        # Step 2: Walk the 13 days where we have contracts AND prices
        target_dates = [date(2026, 5, d) for d in range(5, 18)]
        
        print(f"{'Date':<12} {'Obs':>5} {'Raw Brier':>10} {'EMOS Brier':>12} {'Mkt Brier':>10}")
        print(f"{'-'*12} {'-'*5} {'-'*10} {'-'*12} {'-'*10}")
        
        raw_total, emos_total, mkt_total = 0.0, 0.0, 0.0
        raw_count, emos_count, mkt_count = 0, 0, 0
        
        for target_date in target_dates:
            init_time = datetime(
                target_date.year, target_date.month, target_date.day,
                12, 0, tzinfo=timezone.utc,
            )
            
            try:
                highs = compute_daily_highs(init_time, target_date, conn, model="gefs")
            except Exception:
                continue
            
            observed = fetch_observed_high(target_date, conn)
            if observed is None:
                continue
            
            contracts = fetch_contracts_for_date(target_date, conn)
            if not contracts:
                continue
            
            observation = int(observed)
            
            # Raw Brier
            raw_probs = compute_ensemble_probabilities(highs, contracts)
            raw_scores = evaluate_predictions(raw_probs, contracts, observation)
            raw_brier = sum(raw_scores.values()) / len(raw_scores)
            raw_total += raw_brier
            raw_count += 1
            
            # EMOS Brier (using year-long params)
            values = list(highs.values())
            ensemble_mean = statistics.mean(values)
            ensemble_std = statistics.stdev(values)
            
            corrected_mu = emos_params['a'] + emos_params['b'] * ensemble_mean
            corrected_var = emos_params['c'] + emos_params['d'] * ensemble_std**2
            
            emos_brier = None
            if corrected_var > 0:
                corrected_sigma = math.sqrt(corrected_var)
                emos_probs = gaussian_to_bracket_probs(corrected_mu, corrected_sigma, contracts)
                emos_scores = evaluate_predictions(emos_probs, contracts, observation)
                emos_brier = sum(emos_scores.values()) / len(emos_scores)
                emos_total += emos_brier
                emos_count += 1
            
            # Market Brier
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                    FROM prices
                    WHERE ticker = ANY(%s) AND snapshot_at <= %s
                    ORDER BY ticker, snapshot_at DESC
                """, (tickers, init_time))
                price_rows = cur.fetchall()
            
            market_brier = None
            if price_rows:
                price_dict = {t: (b, a) for t, b, a in price_rows if b is not None and a is not None}
                mkt_scores = []
                for c in contracts:
                    if c["ticker"] in price_dict:
                        bid, ask = price_dict[c["ticker"]]
                        mid_prob = (bid + ask) / 200
                        outcome = contract_resolved_yes(observation, c)
                        mkt_scores.append(brier_score(mid_prob, outcome))
                if mkt_scores:
                    market_brier = sum(mkt_scores) / len(mkt_scores)
                    mkt_total += market_brier
                    mkt_count += 1
            
            emos_str = f"{emos_brier:.4f}" if emos_brier is not None else "—"
            mkt_str = f"{market_brier:.4f}" if market_brier is not None else "—"
            print(f"{str(target_date):<12} {observation:>5} {raw_brier:>10.4f} {emos_str:>12} {mkt_str:>10}")
        
        print()
        if raw_count > 0:
            print(f"Raw ensemble mean Brier:        {raw_total/raw_count:.4f}  ({raw_count} days)")
        if emos_count > 0:
            print(f"EMOS (year-long params) Brier:  {emos_total/emos_count:.4f}  ({emos_count} days)")
        if mkt_count > 0:
            print(f"Market (mid) mean Brier:        {mkt_total/mkt_count:.4f}  ({mkt_count} days)")


if __name__ == "__main__":
    main()