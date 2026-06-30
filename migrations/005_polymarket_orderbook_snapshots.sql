-- 005_polymarket_orderbook_snapshots.sql
-- Polymarket US order-book depth snapshots — the venue-mirror of
-- orderbook_snapshots (Kalshi, migration 004). We have ZERO Polymarket depth
-- history; this table is forward-collected by scripts/snapshot_polymarket_orderbook.py
-- so the liquidity / maker-fill question can be answered on real data instead
-- of a single read.
--
-- READ-ONLY PROVENANCE: every row originates from the Polymarket market-data
-- GET endpoints (/v1/markets/{slug}/book and /v1/markets/{slug}/bbo). No order
-- is ever placed to populate this table.
--
-- ============================================================================
-- SCHEMA MIRRORS orderbook_snapshots (004) so the existing walk-the-book /
-- fill-rate tooling (e.g. scripts/analysis/walk_book_miami.py) transfers with
-- minimal change. The first five columns are byte-identical to 004:
--   snapshot_at, ticker, side ('yes'|'no'), price_cents (1..99), qty.
-- Three extra columns preserve the native Polymarket data that the Kalshi
-- convention rounds away (raw probability, raw fractional size, BBO context).
-- ============================================================================
--
-- ----------------------------------------------------------------------------
-- YES/NO  <->  Polymarket-token mapping  (THE NORMALIZATION CONTRACT)
-- ----------------------------------------------------------------------------
-- Polymarket's order book is quoted on the YES token only, as two ladders:
--     marketData.bids   = resting BUY orders for YES  (a YES bid at price p)
--     marketData.offers = resting SELL orders for YES (a YES ask at price p)
-- Prices `px.value` are 0..1 USD-decimal probabilities; `qty` is shares.
--
-- Kalshi's orderbook_snapshots stores RESTING BIDS on each of two sides
-- ('yes','no'), where a YES ask at price p is economically a NO bid at (1-p)
-- [see walk_book_miami.py: yes_ask = 100 - max(no price)]. To make the walk
-- semantics IDENTICAL across venues we map Polymarket into that same shape:
--
--     Polymarket `bids`   (YES bid @ p)  ->  side='yes', price_cents=round(p*100)
--     Polymarket `offers` (YES ask @ p)  ->  side='no',  price_cents=round((1-p)*100)
--
-- After this mapping the Kalshi invariants hold unchanged:
--     yes_bid = max(price where side='yes')
--     yes_ask = 100 - max(price where side='no')
-- so walk-the-book code written against Kalshi works against Polymarket as-is.
--
-- ----------------------------------------------------------------------------
-- UNIT CONVENTION
-- ----------------------------------------------------------------------------
--   price_cents : integer 1..99  (round(prob*100) after the YES/NO mapping
--                 above) — PARITY with Kalshi. Levels that round to 0 or 100
--                 are dropped (cannot be represented; they are dead-tail
--                 levels with no execution relevance).
--   raw_prob    : the native 0..1 YES-token probability for THIS row's side,
--                 i.e. p for a 'yes' row and (1-p) for a 'no' row, full
--                 precision (no rounding loss).
--   raw_size    : native share quantity as a double (Polymarket qty can be
--                 fractional; Kalshi qty is whole contracts).
--   best_bid_prob / best_ask_prob : the YES-token BBO at snapshot time
--                 (from the same /book response's stats or the /bbo endpoint),
--                 0..1, stored once per row for cheap spread/touch queries
--                 without re-deriving from the ladder.

CREATE TABLE IF NOT EXISTS polymarket_orderbook_snapshots (
    snapshot_at         TIMESTAMPTZ NOT NULL,
    venue               TEXT NOT NULL DEFAULT 'polymarket_us'
                            CHECK (venue = 'polymarket_us'),
    ticker              TEXT NOT NULL REFERENCES contracts(ticker),
    station_id          TEXT NOT NULL,
    target_date         DATE,
    bracket_label       TEXT,                    -- human-readable, e.g. '93-94' or '>=95' or '<70'
    side                TEXT NOT NULL CHECK (side IN ('yes', 'no')),
    price_cents         INTEGER NOT NULL CHECK (price_cents BETWEEN 1 AND 99),
    qty                 INTEGER NOT NULL CHECK (qty > 0),
    -- native Polymarket values (lossless companions to the Kalshi-parity cols)
    raw_prob            DOUBLE PRECISION,        -- 0..1, this row's side
    raw_size            DOUBLE PRECISION,        -- native shares (may be fractional)
    best_bid_prob       DOUBLE PRECISION,        -- YES-token BBO at snapshot (0..1)
    best_ask_prob       DOUBLE PRECISION,        -- YES-token BBO at snapshot (0..1)
    PRIMARY KEY (snapshot_at, ticker, side, price_cents)
);

-- Walk-book query index: "all levels for this ticker at this snapshot, by price"
-- (mirrors idx_orderbook_ticker_snap_side_price on the Kalshi table).
CREATE INDEX IF NOT EXISTS idx_poly_orderbook_ticker_snap_side_price
    ON polymarket_orderbook_snapshots (ticker, snapshot_at DESC, side, price_cents);

-- Per-station/day index for liquidity studies across a city's bracket set.
CREATE INDEX IF NOT EXISTS idx_poly_orderbook_station_date_snap
    ON polymarket_orderbook_snapshots (station_id, target_date, snapshot_at DESC);

-- Hypertable conversion (TimescaleDB) — identical pattern to 004.
-- Wrapped in DO block so re-running the migration doesn't error.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('polymarket_orderbook_snapshots', 'snapshot_at',
                                  if_not_exists => TRUE,
                                  migrate_data => TRUE,
                                  chunk_time_interval => INTERVAL '7 days');
    END IF;
END $$;

-- Compression policy: compress chunks older than 30 days (same as 004).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        ALTER TABLE polymarket_orderbook_snapshots SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'ticker',
            timescaledb.compress_orderby = 'snapshot_at DESC, price_cents'
        );
        PERFORM add_compression_policy('polymarket_orderbook_snapshots', INTERVAL '30 days',
                                       if_not_exists => TRUE);
    END IF;
END $$;
