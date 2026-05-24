-- 002_paper_trades.sql
-- Paper-trading log: once-daily prospective record of hypothetical trades.
-- One row per (target_date, ticker, model_source) — committed before outcome is known.

CREATE TABLE IF NOT EXISTS paper_trades (
    logged_at          TIMESTAMPTZ NOT NULL,
    target_date        DATE NOT NULL,
    ticker             TEXT NOT NULL REFERENCES contracts(ticker),
    model_source       TEXT NOT NULL,
    forecast_init_time TIMESTAMPTZ NOT NULL,
    ensemble_mean      DOUBLE PRECISION NOT NULL,
    ensemble_std       DOUBLE PRECISION NOT NULL,
    emos_mu            DOUBLE PRECISION,
    emos_sigma         DOUBLE PRECISION,
    model_prob_yes     DOUBLE PRECISION NOT NULL,
    market_yes_bid     INTEGER,
    market_yes_ask     INTEGER,
    market_mid_prob    DOUBLE PRECISION,
    market_snapshot_at TIMESTAMPTZ,
    edge               DOUBLE PRECISION NOT NULL,
    edge_threshold     DOUBLE PRECISION NOT NULL,
    position           TEXT NOT NULL CHECK (position IN ('BUY_YES','BUY_NO')),
    entry_price_cents  INTEGER NOT NULL,
    notes              TEXT,
    PRIMARY KEY (target_date, ticker, model_source)
);
