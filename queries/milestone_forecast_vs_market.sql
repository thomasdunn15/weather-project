WITH member_highs AS (
    -- per-member daily high for the target date
    SELECT 
        member_id,
        MAX(tmax_f) AS daily_high_f
    FROM forecasts
    WHERE init_time = '2026-05-13 12:00:00+00'
      AND valid_time >= '2026-05-14 04:00:00+00'
      AND valid_time <  '2026-05-15 04:00:00+00'
    GROUP BY member_id
),
latest_prices AS (
    -- most recent snapshot per ticker
    SELECT DISTINCT ON (ticker)
        ticker,
        yes_bid,
        yes_ask,
        snapshot_at
    FROM prices
    ORDER BY ticker, snapshot_at DESC
),
contract_probs AS (
    -- model-implied probability per contract
    SELECT 
        c.ticker,
        c.bracket_type,
        c.strike_low,
        c.strike_high,
        AVG(
            CASE
                WHEN c.bracket_type = 'greater_than' AND mh.daily_high_f >= c.strike_low + 1 THEN 1.0
                WHEN c.bracket_type = 'less_than' AND mh.daily_high_f < c.strike_high THEN 1.0
                WHEN c.bracket_type = 'between' AND mh.daily_high_f >= c.strike_low AND mh.daily_high_f < c.strike_high + 1 THEN 1.0
                ELSE 0.0
            END
        ) AS model_prob
    FROM contracts c
    CROSS JOIN member_highs mh
    WHERE c.target_date = '2026-05-14'
    GROUP BY c.ticker, c.bracket_type, c.strike_low, c.strike_high
)
SELECT 
    cp.ticker,
    cp.bracket_type,
    cp.strike_low,
    cp.strike_high,
    ROUND((cp.model_prob * 100)::numeric, 1) AS model_prob_pct,
    lp.yes_bid,
    lp.yes_ask,
    -- "Edge" = model probability vs market ask price (in cents)
    -- Positive means model thinks YES is underpriced (potential buy)
    -- Negative means model thinks YES is overpriced (potential sell or avoid)
    ROUND((cp.model_prob * 100 - lp.yes_ask)::numeric, 1) AS edge_vs_ask
FROM contract_probs cp
LEFT JOIN latest_prices lp ON cp.ticker = lp.ticker
ORDER BY cp.bracket_type, cp.strike_low;