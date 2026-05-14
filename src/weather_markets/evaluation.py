
def contract_resolved_yes(observed_high: int, contract: dict) -> bool:
    """
    Did the YES side of this contract resolve true?
    
    Compares the observed integer daily high against the contract's resolution rules.
    
    Args:
        observed_high: The observed daily high in °F (integer, as reported by NWS).
        contract: Contract dict with keys bracket_type, strike_low, strike_high.
    
    Returns:
        True if YES resolved, False if NO resolved.
    
    Raises:
        ValueError: If bracket_type is unknown.
    """
    bracket_type = contract["bracket_type"]
    
    if bracket_type == "greater_than":
        return observed_high > contract["strike_low"]
    elif bracket_type == "less_than":
        return observed_high < contract["strike_high"]
    elif bracket_type == "between":
        return contract["strike_low"] <= observed_high <= contract["strike_high"]
    else:
        raise ValueError(f"Unknown bracket_type: {bracket_type!r}")


def brier_score(probability: float, outcome: bool) -> float:
    """
    Compute the Brier score for a single probabilistic prediction.
    
    Brier = (probability - outcome)^2
    
    Args:
        probability: Predicted probability between 0 and 1.
        outcome: True (event happened, 1) or False (event didn't happen, 0).
    
    Returns:
        Squared error in [0, 1]. Lower is better. 0 is perfect.
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