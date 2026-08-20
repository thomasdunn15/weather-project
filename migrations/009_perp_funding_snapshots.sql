-- Perp funding-rate collection for the cross-venue funding-spread study
-- (docs/strategies/assessments/2026-08-05-s5-perp-xvenue-funding.md).
-- kalshi rows are finalized 8h rates re-pulled from the public history endpoint
-- (self-healing); coinbase rows are hourly forward-snapshots — Coinbase exposes
-- no public funding history, so missed hours are lost.
CREATE TABLE IF NOT EXISTS perp_funding_snapshots (
    venue        text NOT NULL,             -- 'kalshi' | 'coinbase'
    symbol       text NOT NULL,             -- normalized: BTC, ETH, ..., kSHIB, GOLD
    funding_time timestamptz NOT NULL,      -- window the rate applies to, as reported
    funding_rate double precision NOT NULL, -- per-interval rate (kalshi 8h, coinbase 1h)
    mark_price   double precision,
    observed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (venue, symbol, funding_time)
);
