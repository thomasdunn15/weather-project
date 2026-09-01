-- Manually-entered Robinhood positions, 2026-09-01.
--
-- WHY THIS EXISTS: Robinhood publishes no API for event contracts, so nothing
-- can read back what was actually traded there (see BROKER in
-- dashboard/data_forecastex.py). This is the substitute: the operator presses a
-- button on the pick they just typed into the phone, and the card as it read at
-- that moment is written down.
--
-- The specific failure it fixes: picks are re-derived from the live tape on
-- every poll, so a signal that has since moved out of range simply vanishes
-- from the tab — leaving a real position with no record of the price, edge or
-- model that justified it.
--
-- Separate from fx_live_trades, which is IBKR-shaped: it requires a conid, and
-- reconcile_fx_trades.py would try to settle these rows against a broker that
-- never saw them.
CREATE TABLE IF NOT EXISTS rh_entries (
    id serial PRIMARY KEY,
    entered_at timestamptz NOT NULL DEFAULT now(),
    target_date date NOT NULL,           -- EVENT date
    station_id text NOT NULL,
    fx_contract_id text NOT NULL,        -- UHLAX_090126_77
    side text NOT NULL CHECK (side IN ('yes','no')),
    strike double precision NOT NULL,
    contracts int NOT NULL CHECK (contracts > 0),
    limit_price_cents int NOT NULL CHECK (limit_price_cents BETWEEN 1 AND 99),

    -- the card, frozen exactly as it read when the button was pressed
    market_last_cents int,
    model_prob_yes double precision,
    edge double precision,
    emos_mu double precision,
    emos_sigma double precision,

    -- pressed BEFORE the decision time? A provisional pick can stop being a
    -- signal by the time the strategy actually evaluates, and the record has to
    -- say so rather than imply the strategy endorsed it.
    provisional boolean NOT NULL,
    note text,

    -- one entry per contract per side per day; pressing twice is a mis-click
    UNIQUE (target_date, fx_contract_id, side)
);

CREATE INDEX IF NOT EXISTS rh_entries_target_date_idx ON rh_entries (target_date DESC);
