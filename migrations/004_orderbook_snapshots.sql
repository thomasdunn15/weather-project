-- 004_orderbook_snapshots.sql
-- Kalshi order-book depth snapshots. Powers the walk-the-book execution
-- backtest — we can't simulate optimal execution without knowing how much
-- depth was available at each price level historically.
--
-- One row per (snapshot, ticker, side, price_cents). The Kalshi orderbook
-- endpoint returns YES bids and NO bids only (asks are derived: YES_ask at
-- price X = NO_bid at price 100−X). We store the raw bid side per Kalshi's
-- convention. Walk-the-book queries convert side as needed.

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    snapshot_at         TIMESTAMPTZ NOT NULL,
    ticker              TEXT NOT NULL REFERENCES contracts(ticker),
    side                TEXT NOT NULL CHECK (side IN ('yes', 'no')),
    price_cents         INTEGER NOT NULL CHECK (price_cents BETWEEN 1 AND 99),
    qty                 INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (snapshot_at, ticker, side, price_cents)
);

-- Compound index for walk-book queries: "give me all levels for this ticker
-- at this snapshot, sorted by price"
CREATE INDEX IF NOT EXISTS idx_orderbook_ticker_snap_side_price
    ON orderbook_snapshots (ticker, snapshot_at DESC, side, price_cents);

-- Hypertable conversion (TimescaleDB) — same pattern as prices table.
-- Wrapped in DO block so re-running the migration doesn't error.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('orderbook_snapshots', 'snapshot_at',
                                  if_not_exists => TRUE,
                                  migrate_data => TRUE,
                                  chunk_time_interval => INTERVAL '7 days');
    END IF;
END $$;

-- Compression policy: after 30 days, compress old chunks. Order-book history
-- is bulky (≈6 brackets × 10 levels × 12/hour × 24h = ~17k rows/day per city)
-- and we only need recent data for backtests + a longer window for sanity.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        ALTER TABLE orderbook_snapshots SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'ticker',
            timescaledb.compress_orderby = 'snapshot_at DESC, price_cents'
        );
        PERFORM add_compression_policy('orderbook_snapshots', INTERVAL '30 days',
                                       if_not_exists => TRUE);
    END IF;
END $$;
