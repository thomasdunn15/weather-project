-- 003_live_trades.sql
-- Live (real-money) trade log. Distinct from paper_trades to keep the
-- accounting unambiguous: paper_trades = "what the model would have done",
-- live_trades = "what actually happened on Kalshi".
--
-- One row per ATTEMPTED order (placed_at + ticker + side + count is unique).
-- An order can fill fully, fill partially, be cancelled, or be rejected —
-- fill_status tracks the final state. realized_pnl_cents is populated by the
-- reconciliation cron once Kalshi settles the contract.

CREATE TABLE IF NOT EXISTS live_trades (
    id                  BIGSERIAL PRIMARY KEY,

    -- When and what
    placed_at           TIMESTAMPTZ NOT NULL,
    target_date         DATE NOT NULL,
    ticker              TEXT NOT NULL REFERENCES contracts(ticker),

    -- Trade direction + size
    side                TEXT NOT NULL CHECK (side IN ('yes','no')),
    count               INTEGER NOT NULL CHECK (count > 0),
    limit_price_cents   INTEGER NOT NULL CHECK (limit_price_cents BETWEEN 1 AND 99),
    -- What we WOULD have paid going cross-spread, recorded so we can compare
    -- limit-vs-cross economics post-hoc:
    cross_price_cents   INTEGER NOT NULL,

    -- Model context that drove the trade
    model_source        TEXT NOT NULL,
    model_prob_yes      DOUBLE PRECISION NOT NULL,
    market_mid_prob     DOUBLE PRECISION NOT NULL,
    edge                DOUBLE PRECISION NOT NULL,

    -- Kalshi-side state
    kalshi_order_id     TEXT UNIQUE,
    client_order_id     TEXT UNIQUE,           -- our idempotency key
    fill_status         TEXT NOT NULL CHECK (fill_status IN
                          ('pending','filled','partial','cancelled','rejected','expired')),
    fill_price_cents    INTEGER,
    fill_count          INTEGER,
    fill_time           TIMESTAMPTZ,

    -- Settlement (populated by reconciliation cron)
    settlement          TEXT CHECK (settlement IN ('yes','no')),
    settlement_time     TIMESTAMPTZ,
    realized_pnl_cents  INTEGER,                -- net of fee
    kalshi_fee_cents    INTEGER,

    -- Provenance
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS live_trades_target_date_idx ON live_trades(target_date DESC);
CREATE INDEX IF NOT EXISTS live_trades_placed_at_idx   ON live_trades(placed_at DESC);
CREATE INDEX IF NOT EXISTS live_trades_status_idx      ON live_trades(fill_status)
    WHERE fill_status IN ('pending','partial');
CREATE INDEX IF NOT EXISTS live_trades_unsettled_idx   ON live_trades(target_date)
    WHERE settlement IS NULL AND fill_status IN ('filled','partial');

-- updated_at trigger
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS live_trades_updated_at ON live_trades;
CREATE TRIGGER live_trades_updated_at BEFORE UPDATE ON live_trades
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
