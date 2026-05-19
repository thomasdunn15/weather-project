"""Compare model, EMOS, and Kalshi Brier scores across backtest days."""
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
from weather_markets.evaluation import evaluate_predictions, contract_resolved_yes, brier_score


def fetch_market_probs(contracts, snapshot_time, conn):
    """
    For each contract, get yes_bid and yes_ask closest to (but not after) snapshot_time.
    Return dict {ticker: implied_probability_from_mid_price}.
    """
    tickers = [c["ticker"] for c in contracts]
    
    sql = """
        SELECT DISTINCT ON (ticker)
            ticker,
            yes_bid,
            yes_ask
        FROM prices
        WHERE ticker = ANY(%s)
          AND snapshot_at <= %s
        ORDER BY ticker, snapshot_at DESC
    """
    
    with conn.cursor() as cur:
        cur.execute(sql, (tickers, snapshot_time))
        rows = cur.fetchall()
    
    result = {}
    for ticker, bid, ask in rows:
        if bid is None or ask is None:
            continue
        mid = (bid + ask) / 2
        result[ticker] = mid / 100  # convert cents to probability
    
    return result


def collect_training_data(conn, start: date, end: date):
    """Same as before — collect ensemble stats for each day."""
    means, stds, obs, dates = [], [], [], []
    
    target_date = start
    while target_date <= end:
        init_time = datetime(target_date.year, target_date.month, target_date.day, 12, 0, tzinfo=timezone.utc)
        
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
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id = %s", ("KNYC",))
            end = cur.fetchone()[0]
        
        means, stds, obs, dates = collect_training_data(conn, start, end)
        n = len(means)
        
        # Header
        print(f"{'Date':<12} {'Obs':>5} {'Raw Brier':>10} {'EMOS Brier':>12} {'Mkt Brier':>10}")
        print(f"{'-'*12} {'-'*5} {'-'*10} {'-'*12} {'-'*10}")
        
        raw_total, emos_total, mkt_total = 0.0, 0.0, 0.0
        raw_count, emos_count, mkt_count = 0, 0, 0
        
        for i in range(n):
            held_out_date = dates[i]
            held_out_mean = means[i]
            held_out_std = stds[i]
            held_out_obs = obs[i]
            
            # === Raw ensemble Brier ===
            init_time = datetime(held_out_date.year, held_out_date.month, held_out_date.day, 12, 0, tzinfo=timezone.utc)
            highs = compute_daily_highs(init_time, held_out_date, conn)
            contracts = fetch_contracts_for_date(held_out_date, conn)
            
            if not contracts:
                continue
            
            raw_probs = compute_ensemble_probabilities(highs, contracts)
            raw_scores = evaluate_predictions(raw_probs, contracts, int(held_out_obs))
            raw_brier = sum(raw_scores.values()) / len(raw_scores)
            raw_total += raw_brier
            raw_count += 1
            
            # === EMOS LOO Brier ===
            train_means = means[:i] + means[i+1:]
            train_stds = stds[:i] + stds[i+1:]
            train_obs = obs[:i] + obs[i+1:]
            params = fit_emos(train_means, train_stds, train_obs)
            
            corrected_mu = params['a'] + params['b'] * held_out_mean
            corrected_var = params['c'] + params['d'] * held_out_std**2
            
            if corrected_var > 0:
                corrected_sigma = math.sqrt(corrected_var)
                emos_probs = gaussian_to_bracket_probs(corrected_mu, corrected_sigma, contracts)
                emos_scores = evaluate_predictions(emos_probs, contracts, int(held_out_obs))
                emos_brier = sum(emos_scores.values()) / len(emos_scores)
                emos_total += emos_brier
                emos_count += 1
            else:
                emos_brier = None
            
            # === Market Brier ===
            market_probs = fetch_market_probs(contracts, init_time, conn)
            if market_probs:
                # Build a Brier score using market's implied probs as predictions
                mkt_scores = []
                for c in contracts:
                    if c["ticker"] not in market_probs:
                        continue
                    p = market_probs[c["ticker"]]
                    outcome = contract_resolved_yes(int(held_out_obs), c)
                    mkt_scores.append(brier_score(p, outcome))
                
                if mkt_scores:
                    mkt_brier = sum(mkt_scores) / len(mkt_scores)
                    mkt_total += mkt_brier
                    mkt_count += 1
                else:
                    mkt_brier = None
            else:
                mkt_brier = None
            
            # Print row
            mkt_str = f"{mkt_brier:.4f}" if mkt_brier is not None else "—"
            emos_str = f"{emos_brier:.4f}" if emos_brier is not None else "—"
            print(f"{str(held_out_date):<12} {held_out_obs:>5.0f} {raw_brier:>10.4f} {emos_str:>12} {mkt_str:>10}")
        
        # Summary
        print()
        if raw_count > 0:
            print(f"Raw ensemble mean Brier:  {raw_total/raw_count:.4f}  ({raw_count} days)")
        if emos_count > 0:
            print(f"EMOS LOO mean Brier:      {emos_total/emos_count:.4f}  ({emos_count} days)")
        if mkt_count > 0:
            print(f"Market (mid) mean Brier:  {mkt_total/mkt_count:.4f}  ({mkt_count} days)")


if __name__ == "__main__":
    main()