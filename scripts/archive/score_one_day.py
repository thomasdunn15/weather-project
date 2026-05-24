from datetime import datetime, date, timezone
from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_daily_highs,
    compute_ensemble_probabilities,
    fetch_contracts_for_date,
    fetch_observed_high,
)
from weather_markets.evaluation import evaluate_predictions

init_time = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
target_date = date(2026, 5, 13)

with get_connection() as conn:
    highs = compute_daily_highs(init_time, target_date, conn)
    contracts = fetch_contracts_for_date(target_date, conn)
    observed = fetch_observed_high(target_date, conn)
    probs = compute_ensemble_probabilities(highs, contracts)
    scores = evaluate_predictions(probs, contracts, observed)

print(f"Observed high: {observed}°F")
print()
print(f"{'Contract':<25} {'Model P':>10} {'Brier':>10}")
print(f"{'-'*25} {'-'*10} {'-'*10}")
for c in contracts:
    ticker = c["ticker"]
    p = probs[ticker]
    s = scores[ticker]
    print(f"{ticker:<25} {p:>10.1%} {s:>10.4f}")

print()
print(f"Mean Brier across all contracts: {sum(scores.values()) / len(scores):.4f}")