-- 007: expansion_* catalog tables — B1 breadth scout (research data only).
-- Namespaced away from trading state; nothing in the live pipeline reads these.
-- Apply: psql -d weather -f migrations/007_expansion_catalog.sql

CREATE TABLE IF NOT EXISTS expansion_series (
    venue          TEXT NOT NULL,          -- 'kalshi' | 'forecastex'
    series_ticker  TEXT NOT NULL,
    category       TEXT,
    title          TEXT,
    frequency      TEXT,
    payload        JSONB,                  -- full series object (settlement sources etc.)
    first_seen     TIMESTAMPTZ NOT NULL,
    last_seen      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (venue, series_ticker)
);

-- One row per (market, snapshot). Open markets: snapshot_at = sync time, so
-- repeated syncs build a sparse time series. Settled markets: snapshot_at =
-- close_time, so re-syncing history is idempotent (no duplicate rows).
CREATE TABLE IF NOT EXISTS expansion_market_snapshots (
    venue          TEXT NOT NULL,
    market_ticker  TEXT NOT NULL,
    series_ticker  TEXT NOT NULL,
    snapshot_at    TIMESTAMPTZ NOT NULL,
    status         TEXT NOT NULL,
    yes_bid        INTEGER,
    yes_ask        INTEGER,
    last_price     INTEGER,
    volume         BIGINT,
    volume_24h     BIGINT,
    open_interest  BIGINT,
    open_time      TIMESTAMPTZ,
    close_time     TIMESTAMPTZ,
    result         TEXT,                   -- 'yes'/'no' once settled, else ''
    PRIMARY KEY (venue, market_ticker, snapshot_at)
);

CREATE INDEX IF NOT EXISTS idx_expansion_mkt_series
    ON expansion_market_snapshots (venue, series_ticker, snapshot_at DESC);
