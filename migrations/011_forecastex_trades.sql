-- ForecastEx (IBKR) live probe trades, 2026-08-20. Separate from live_trades
-- and pm_live_trades: the reconcile path is IBKR-shaped and settlement uses
-- ForecastEx's OWN settled high (Weather Underground), not the NWS CLI value
-- our observations table carries. Scoring these against observations would
-- invent edge -- see weather_markets.forecastex for the measured offsets.
--
-- Contracts are identified by conid because ForecastEx has no stable public
-- ticker in IBKR; the ForecastEx contract id (UHMIA_082026_94) is kept
-- alongside it so rows join back to our own contracts/prices tables.
CREATE TABLE IF NOT EXISTS fx_live_trades (
    id serial PRIMARY KEY,
    placed_at timestamptz NOT NULL,
    target_date date NOT NULL,           -- EVENT date (IBKR maturity is this +1)
    station_id text NOT NULL,
    fx_contract_id text NOT NULL,        -- UHMIA_082026_94
    conid bigint NOT NULL,               -- the leg actually bought
    side text NOT NULL CHECK (side IN ('yes','no')),
    strike double precision NOT NULL,
    count int NOT NULL CHECK (count > 0),
    limit_price_cents int NOT NULL CHECK (limit_price_cents BETWEEN 1 AND 99),
    posted boolean NOT NULL,             -- true = rested below the ask, false = crossed
    strategy text NOT NULL,              -- raw | blend | union
    model_source text NOT NULL,
    model_prob_yes double precision,
    market_last_prob double precision,   -- last print; ForecastEx publishes no book
    assumed_spread_cents double precision,
    edge double precision,
    ibkr_order_id text,
    fill_count int NOT NULL DEFAULT 0,
    fill_avg_price_cents double precision,
    settlement text,                     -- 'win' / 'loss' once scored
    realized_pnl_cents double precision, -- net of the flat 1c/contract fee
    notes text
);

CREATE INDEX IF NOT EXISTS fx_live_trades_target_date_idx
    ON fx_live_trades (target_date DESC);
CREATE INDEX IF NOT EXISTS fx_live_trades_unsettled_idx
    ON fx_live_trades (target_date) WHERE settlement IS NULL AND fill_count > 0;

-- One order per contract per day, so a re-run cannot double the position.
CREATE UNIQUE INDEX IF NOT EXISTS fx_live_trades_one_per_contract_idx
    ON fx_live_trades (target_date, fx_contract_id, side);
