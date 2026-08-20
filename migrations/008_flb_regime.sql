-- 008: flb_regime — per-series favorite-longshot metric (research data only).
-- Computed by scripts/analysis/flb_regime.py --write from Kalshi candlesticks;
-- read by collect_metrics -> strategy_eval engine as market-fit evidence.
-- Nothing in the live trading pipeline reads this.
-- Apply: psql -d weather -f migrations/008_flb_regime.sql

CREATE TABLE IF NOT EXISTS flb_regime (
    series_ticker            TEXT PRIMARY KEY,
    n_markets                INTEGER NOT NULL,   -- settled markets actually priced
    longshot_mass            REAL,               -- fraction of markets priced <30c
    longshot_overpricing_pp  REAL,               -- <30c bucket: implied - actual YES (pct pts, +ve = overpriced)
    favorite_underpricing_pp REAL,               -- >=50c bucket: actual YES - implied (pct pts, +ve = favorites win more than priced)
    resolution_hours         REAL,               -- median market lifetime open->close, in hours (fast vs slow)
    verdict                  TEXT,
    buckets                  JSONB,              -- full per-bucket detail
    computed_at              TIMESTAMPTZ NOT NULL
);
