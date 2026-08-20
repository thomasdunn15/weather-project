-- Polymarket US live probe trades (Miami port, 2026-08-12). Separate from
-- live_trades: that table's reconcile path is Kalshi-API-shaped. Settlement is
-- scored by scripts/live_trade_polymarket.py itself (observations + PM fee).
CREATE TABLE IF NOT EXISTS pm_live_trades (
    id serial PRIMARY KEY,
    placed_at timestamptz NOT NULL,
    target_date date NOT NULL,
    ticker text NOT NULL,                -- PM market slug
    intent text NOT NULL,                -- ORDER_INTENT_BUY_LONG | ORDER_INTENT_BUY_SHORT
    count double precision NOT NULL,     -- requested contracts
    limit_price_cents int NOT NULL,      -- bound for the side bought (YES for LONG, NO for SHORT)
    model_source text NOT NULL,
    model_prob_yes double precision,
    market_mid_prob double precision,
    edge double precision,
    pm_order_id text,
    fill_count double precision NOT NULL DEFAULT 0,
    fill_avg_price_cents double precision,
    settlement text,                     -- 'win' / 'loss' once scored
    realized_pnl_cents double precision, -- net of PM taker fee, for the kill switch
    notes text
);
