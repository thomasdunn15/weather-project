
def contract_resolved_yes(observed_high: int, contract: dict) -> bool:
    """
    Did the YES side of this contract resolve true?
    
    Compares the observed integer daily high against the contract's resolution rules.

    """
    bracket_type = contract["bracket_type"]
    
    # Kalshi convention (verified empirically against fills):
    #   - between [low, high) — INCLUSIVE low, EXCLUSIVE high
    #     E.g., B85.5 = [85, 86): high=85→YES, high=86→NO
    #   - greater_than > low  (i.e., low is exclusive: >low means at least low+1)
    #   - less_than < high  (i.e., high is exclusive: <high means at most high-1)
    if bracket_type == "greater_than":
        return observed_high > contract["strike_low"]
    elif bracket_type == "less_than":
        return observed_high < contract["strike_high"]
    elif bracket_type == "between":
        return contract["strike_low"] <= observed_high < contract["strike_high"]
    else:
        raise ValueError(f"Unknown bracket_type: {bracket_type!r}")


def brier_score(probability: float, outcome: bool) -> float:
    """
    Compute the Brier score for a single probabilistic prediction.
    
    Brier = (probability - outcome)^2

    """
    return (probability - outcome) ** 2

def evaluate_predictions(
    probabilities: dict[str, float],
    contracts: list[dict],
    observed_high: int,
) -> dict[str, float]:
    """
    Compute Brier scores for a set of contract predictions.
    """
    result = {}
    for contract in contracts:
        ticker = contract["ticker"]
        probability = probabilities[ticker]
        outcome = contract_resolved_yes(observed_high, contract)
        result[ticker] = brier_score(probability, outcome)
    return result

def calibration_bins(
    pairs: list[tuple[float, bool]],
    n_bins: int = 5,
) -> list[dict]:
    """
    Bin (probability, outcome) pairs and compute calibration statistics.
    
    A calibration plot maps mean predicted probability (x) to observed
    frequency (y). A perfectly calibrated model lies on the diagonal.
    """
    if n_bins < 1:
        raise ValueError(f"n_bins must be positive, got {n_bins}")
    
    # Create bin edges: [0, 0.2, 0.4, 0.6, 0.8, 1.0] for n_bins=5
    bin_edges = [i / n_bins for i in range(n_bins + 1)]
    
    # Initialize buckets
    bins = [[] for _ in range(n_bins)]
    
    # Assign each pair to a bin
    for prob, outcome in pairs:
        if not 0 <= prob <= 1:
            raise ValueError(f"probability must be in [0, 1], got {prob}")
        
        # Find which bin this prob belongs to.
        # Edge case: prob == 1.0 should go in the last bin.
        bin_idx = min(int(prob * n_bins), n_bins - 1)
        bins[bin_idx].append((prob, outcome))
    
    # Compute statistics per bin
    result = []
    for i, bin_pairs in enumerate(bins):
        if not bin_pairs:
            continue
        
        probs_in_bin = [p for p, _ in bin_pairs]
        outcomes_in_bin = [o for _, o in bin_pairs]
        
        result.append({
            "bin_low": bin_edges[i],
            "bin_high": bin_edges[i + 1],
            "mean_predicted": sum(probs_in_bin) / len(probs_in_bin),
            "fraction_true": sum(outcomes_in_bin) / len(outcomes_in_bin),
            "count": len(bin_pairs),
        })
    
    return result