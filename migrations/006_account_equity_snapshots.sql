-- 006_account_equity_snapshots.sql
-- Daily account-equity snapshot: one row per UTC day capturing TRUE equity
-- (cash + open-position mark-to-market) and the reconciliation P&L, so the
-- live-tab cumulative-P&L graph can overlay realized-plus-open equity going
-- forward. Written by scripts/snapshot_account_equity.py (daily cron, ~04:15 UTC).
--
-- SOURCE: balance-based, live Kalshi (GET /portfolio/balance +
-- /portfolio/deposits + /portfolio/withdrawals). This is a SEPARATE series from
-- dashboard.data_live._daily_realized_series (settlements-only realized): the two
-- are distinct measurements and must be rendered as two lines, never summed.
-- The snapshot reads NO settlements, so there is no double-count in collection.
--
-- Plain table (not a hypertable): one row/day is tiny — the 004/005
-- hypertable+compression machinery would be pure overhead here.
--
-- RECONCILIATION IDENTITY (holds on the stored columns alone):
--   computed_pnl_dollars = account_value_dollars
--                          - deposits_dollars - referral_credit_dollars
--                          + withdrawals_dollars
-- deposits_dollars is LITERAL ACH/debit funding ($3,050 to date). The audited,
-- non-API $14.99 friend-referral credit is kept in its own column so nothing is
-- mislabeled; both are subtracted (capital-in is not P&L). Withdrawals are money
-- out, added back (not a trading loss).

CREATE TABLE IF NOT EXISTS account_equity_snapshots (
    snapshot_date            DATE PRIMARY KEY,           -- one row per UTC day
    cash_dollars             NUMERIC(12,2) NOT NULL,     -- Kalshi available balance
    portfolio_value_dollars  NUMERIC(12,2) NOT NULL,     -- Kalshi mark of all open positions
    account_value_dollars    NUMERIC(12,2) NOT NULL,     -- cash + portfolio_value
    deposits_dollars         NUMERIC(12,2) NOT NULL,     -- applied ACH/debit deposits (literal)
    referral_credit_dollars  NUMERIC(12,2) NOT NULL,     -- audited non-API promo credit ($14.99)
    withdrawals_dollars      NUMERIC(12,2) NOT NULL,     -- applied withdrawals (money out)
    computed_pnl_dollars     NUMERIC(12,2) NOT NULL,     -- realized + unrealized (see identity above)
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
