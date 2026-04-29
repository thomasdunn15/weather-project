-- 001_initial_schema.sql
-- Initial Tables for week 1: forecasts, observations, prices, and contracts.

CREATE TABLE IF NOT EXISTS forecasts(
    init_time       TIMESTAMPTZ NOT NULL,
    valid_time      TIMESTAMPTZ NOT NULL,
    station_id      TEXT NOT NULL,
    model           TEXT NOT NULL,
    member_id       INTEGER NOT NULL,
    temperature_f   DOUBLE PRECISION,
    tmax_f          DOUBLE PRECISION,
    PRIMARY KEY (init_time, valid_time, station_id, model, member_id)
);

SELECT create_hypertable('forecasts', 'valid_time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS observations (
    date          DATE NOT NULL,
    station_id    TEXT NOT NULL,
    high_temp_f   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (date, station_id)
);

SELECT create_hypertable('observations', 'date', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS contracts(
    ticker              TEXT PRIMARY KEY,
    series              TEXT NOT NULL,
    station_id          TEXT NOT NULL,
    target_date         DATE NOT NULL,
    strike_low          DOUBLE PRECISION,
    strike_high         DOUBLE PRECISION,
    bracket_type TEXT NOT NULL CHECK (bracket_type IN ('between', 'greater_than', 'less_than')),
    expiration_time     TIMESTAMPTZ,
    last_trading_time   TIMESTAMPTZ,
    raw_metadata        JSONB,
    discovered_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS prices(
    snapshot_at     TIMESTAMPTZ NOT NULL,
    ticker          TEXT NOT NULL REFERENCES contracts(ticker),
    yes_bid         INTEGER,
    yes_ask         INTEGER,
    no_bid          INTEGER,
    no_ask          INTEGER,
    last_price      INTEGER,
    volume          BIGINT,
    volume_24h      BIGINT,
    open_interest   BIGINT,
    PRIMARY KEY (snapshot_at, ticker)
);

SELECT create_hypertable('prices', 'snapshot_at', if_not_exists => TRUE);

--indexes
CREATE INDEX IF NOT EXISTS idx_forecasts_station_valid ON forecasts (station_id, valid_time, init_time DESC);
CREATE INDEX IF NOT EXISTS idx_prices_ticker_snapshot ON prices (ticker, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_contracts_station_date ON contracts (station_id, target_date);