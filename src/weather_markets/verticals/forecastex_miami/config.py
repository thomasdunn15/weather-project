"""CITY_CONFIG-style entry for the forecastex-miami vertical (paper-only).

Copy of the live_trade.py CITY_CONFIG shape so a validated vertical can be
promoted by pasting this dict — a manual operator decision, never automated.
"""

VERTICAL_CONFIG = {
    "KMIA": {
        "city_name": "forecastex-miami",
        "venue": "forecastex",
        "series_ticker": 'KXHIGHMIA',
        "underlying": "daily_high_temp",
        "models": ["gefs", "ifs"],            # TODO: validate model set for this vertical
        "decision_hour": 15,                   # TODO: pick via entry-timing check (UTC)
        "decision_minute": 0,
        "use_blend": True,
        "edge_threshold": 0.25,                # TODO: validate on paper data before trusting
        "blend_edge_threshold": 0.10,
        "sizing_mode": "unit",
        "unit_contracts": 50,                  # minimal size if EVER promoted (operator decision)
        "max_contracts_per_trade": 50,
        "daily_loss_limit_dollars": 25.0,
        "cumulative_kill_dollars": 100.0,
        "is_active": False,                    # paper-only; promotion is manual
    }
}
