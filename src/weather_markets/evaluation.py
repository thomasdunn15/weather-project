
def contract_resolved_yes(observed_high: int, contract: dict) -> bool:
    """
    Did the YES side of this contract resolve true?
    
    Compares the observed integer daily high against the contract's resolution rules.

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