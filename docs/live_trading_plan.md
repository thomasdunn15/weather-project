# Live Trading Prep — Checklist

**Status:** Pre-launch. No live capital deployed yet.
**Strategy:** KXHIGHNY (NYC daily highs), combined GEFS+IFS 00Z + rolling 45-day EMOS.
**Production filter:** |edge| ≥ 10%, entry ≥ 60¢, decision at 14:45 UTC.
**Sizing:** Unit — 75 contracts/trade, clipped if stake would exceed $50.
  (Switched from half-Kelly on 2026-06-01 after backtest showed Sharpe 1.74 vs Kelly's
   0.56-0.90. Pre-committed BEFORE first live cron fire.)
**Initial capital:** $1,000.

Phases below are **strictly sequential** — don't start a phase until the prior one's acceptance criteria pass.

---

## Phase 0 — Pre-flight (before any code change)

### 0.1 Confirm the strategy parameters are still what we think

- [ ] Production filter on dashboard matches docs above (|edge| ≥ 10%, entry ≥ 60¢)
- [ ] Paper-trade cron has been firing daily at 14:45 UTC without errors for 7 consecutive days
- [ ] ECMWF 13:00 UTC retry cron is installed (verify: `crontab -l | grep 'ingest_ecmwf_daily'` shows two lines)
- [ ] Disk usage stays under 30% during a 24h window (verify hourly cache cleanup is working)

### 0.2 Write the risk envelope and pre-committed kill criteria down

**These are immutable once live trading starts.** Numbers chosen now to avoid post-hoc rationalization.

| Limit | Value | Trigger action |
|---|---|---|
| Max stake per single trade | $50 (5% of $1k bankroll) | Order count clipped to fit cap |
| Max open contracts at any moment | 200 | New orders blocked until close (runaway-bug circuit breaker; ~4 max-stake trades) |
| Max daily P&L drawdown | −$50 | Halt new orders for 24h |
| **Cumulative kill drawdown** | **−$300 at any time months 1–6** | Halt strategy permanently, manual review required |
| Forward mean P&L over first 60 trades | < −1¢/trade | Halt strategy permanently |
| Limit fill rate over first 30 attempts | < 40% | Halt strategy, revisit execution model |
| Avg spread on filtered trades (rolling 4-week) | > 5¢ | Halt strategy (regime degradation) |

**Acceptance:** All four 0.1 items checked. Risk envelope written and committed to git.

---

## Phase 1 — Manual paper validation (1 week, no automation, no code change)

**Goal:** Build intuition about real Kalshi UX before automating anything. Verify the limit-target prices the dashboard suggests are *actually achievable* with manual entry.

### 1.1 Manual workflow each trading day

- [ ] At 14:45 UTC, open Kalshi web UI and the project dashboard side by side
- [ ] For each signal the dashboard fires:
  - [ ] Note the cross-spread entry price and the limit-target price
  - [ ] Manually place a **1-contract** limit order at the limit-target price
  - [ ] Record fill outcome (filled / not filled / partial) in a tracking sheet
- [ ] If unfilled by 15:30 UTC, cancel the order
- [ ] At day end, record actual settlement vs predicted

### 1.2 Tracking sheet columns

| Date | Ticker | Position | Cross price | Limit price | Filled? | Fill price | Settled YES/NO | P&L |

### 1.3 Acceptance criteria (after 7 trading days)

- [ ] At least 3 signals fired (paper-trade backtest predicts ~0.5/day)
- [ ] At least one limit fill (to verify fills ARE achievable inside the spread)
- [ ] Manual fill rate logged; first directional read on whether 70% fill assumption is realistic
- [ ] Any operational issues with Kalshi UI documented (rejected orders, weird states, etc.)

**Effort:** 5 min/day, 5 days = ~25 min total.
**Cost:** Capital at risk = $1 per contract attempted. Worst case ~$5-10 lost.

---

## Phase 2 — Kalshi API setup (read-only)

**Goal:** Authenticated API client that can read account state. No order placement yet.

### 2.1 Account-side setup (you do)

- [ ] Log in to Kalshi
- [ ] Navigate to API key management (Settings → API)
- [ ] Generate a new API key pair (note: Kalshi uses RSA key pairs, not bearer tokens)
- [ ] Save the private key to `~/.kalshi/` with `chmod 600`
- [ ] Save the key-id (public identifier) somewhere accessible
- [ ] Verify your account has sufficient balance ($1,000 deposited)

### 2.2 Code-side setup (I do)

- [ ] Add `KALSHI_KEY_ID` and `KALSHI_KEY_PATH` to `.env`
- [ ] Add `kalshi-python` or hand-rolled httpx client with RSA-PSS signing
- [ ] Build `src/weather_markets/kalshi_api.py` with read-only methods:
  - `get_balance()` → current cash + P&L
  - `get_positions()` → all open positions
  - `get_orders(status='open')` → all pending orders
  - `get_fills(since=ts)` → fills since timestamp
- [ ] Write a smoke-test script: `scripts/check_kalshi_api.py` that prints balance and any open positions

### 2.3 Acceptance criteria

- [ ] `uv run python scripts/check_kalshi_api.py` returns your real balance with no errors
- [ ] Can read open orders + fills (even if zero)
- [ ] Authentication headers verified against Kalshi docs

**Effort:** 1-2 hours code; 30 min Kalshi account-side.

---

## Phase 3 — Single manual order via API

**Goal:** Place ONE order via the API end-to-end. Smallest possible stake. Verify the round-trip works.

### 3.1 Build minimal order placement

- [ ] Add `place_limit_order(ticker, side, count, price_cents, post_only=False)` to `kalshi_api.py`
- [ ] Add `cancel_order(order_id)`
- [ ] Add `get_order_status(order_id)`

### 3.2 Manual smoke test

- [ ] Pick a current KXHIGHNY contract with tight spread (≤5¢)
- [ ] Manually call `place_limit_order(...)` for **1 contract** with `post_only=True` at a price 1¢ inside the spread
- [ ] Verify order appears in `get_orders()`
- [ ] If filled within 5 min: verify in `get_fills()`. If not: `cancel_order(...)` and verify gone
- [ ] Check balance updated correctly

### 3.3 Acceptance criteria

- [ ] One order placed, observed (filled OR cancelled), no errors
- [ ] Balance reconciles with expected (cost of fill / 0 if cancelled / fee charged on fill)
- [ ] Order audit trail clear (we know the order_id, can look it up later)

**Effort:** 1-2 hours.
**Cost:** ≤ $1 lost if everything goes sideways.

---

## Phase 4 — Live cron with full kill switches

**Goal:** Automate the daily decision + order placement, with all risk controls active.

### 4.1 Build the live-trade cron script

- [ ] Fork `scripts/paper_trade_log.py` → `scripts/live_trade.py`
- [ ] Same decision logic (compute edge, apply filters)
- [ ] Add risk-control checks BEFORE every order:
  - Total open contracts < 50?
  - Today's realized P&L > −$50?
  - Cumulative P&L > −$300?
  - Avg 4-week spread < 5¢?
- [ ] Half-Kelly sizing from current balance + current edge
- [ ] Place `post_only=True` limit orders at limit-target price
- [ ] If risk control fails: log + send alert + exit cleanly (no orders placed)
- [ ] Write all attempts to a new `live_trades` table (separate from paper_trades for clean accounting)

### 4.2 Schema: `live_trades` table

```sql
CREATE TABLE live_trades (
    id BIGSERIAL PRIMARY KEY,
    placed_at TIMESTAMPTZ NOT NULL,
    target_date DATE NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,           -- 'yes' or 'no'
    count INT NOT NULL,
    limit_price_cents INT NOT NULL,
    cross_price_cents INT NOT NULL,  -- what we WOULD have paid going cross
    model_prob NUMERIC,
    market_mid NUMERIC,
    edge NUMERIC,
    kalshi_order_id TEXT,
    fill_status TEXT,             -- 'pending', 'filled', 'cancelled', 'rejected'
    fill_price_cents INT,
    fill_time TIMESTAMPTZ,
    settlement TEXT,              -- 'yes', 'no', NULL
    settlement_time TIMESTAMPTZ,
    realized_pnl_cents INT,
    notes TEXT
);
```

### 4.3 Cron schedule

- [ ] Add to `docs/crontab.txt`: `45 14 * * * cd /home/tdunn/weather-project && uv run python scripts/live_trade.py >> /var/log/weather/live_trade.log 2>&1`
- [ ] **Disable the existing paper-trade cron at 14:45** OR set its `model_source` to a distinct string so live and paper don't conflict in `paper_trades` table
- [ ] Install with `crontab docs/crontab.txt`

### 4.4 Acceptance criteria (first 3 days running)

- [ ] Cron fires reliably at 14:45 UTC
- [ ] No errors in log
- [ ] Orders placed when signals fire; no orders placed when risk controls block
- [ ] `live_trades` rows match Kalshi's actual order history exactly

**Effort:** 3-4 hours code + 3 days observation.

---

## Phase 5 — Fill monitoring + escalation

**Goal:** Handle the fact that limit orders sometimes don't fill.

### 5.1 Fill checker cron

- [ ] Cron at 15:30 UTC (45 min after order placement): for any `live_trades` row from today still in `pending` status:
  - Query `get_order_status()`
  - If still open AND we haven't crossed the "escalate to cross-spread" threshold: leave alone
  - If still open AND should escalate: cancel + re-place at cross-spread price (configurable)
  - If still open AND end-of-day reached: cancel + mark `fill_status='cancelled'`
- [ ] **Default: NO escalation in Phase 5.** Unfilled = cancelled. Pure limit-only strategy. We collect data on fill rate first before deciding whether escalation helps.

### 5.2 Acceptance criteria

- [ ] Unfilled orders cleanly cancelled by EOD
- [ ] Fill rate calculated daily and logged
- [ ] After 30 attempts: review actual fill rate. If <40%, halt per kill criteria.

**Effort:** 2 hours.

---

## Phase 6 — End-of-day reconciliation

**Goal:** Pull actual fills + settlements, compute realized P&L, sanity-check accounting.

### 6.1 Reconciliation cron

- [ ] Cron at 04:00 UTC daily (well after contracts settle at midnight ET):
  - For each `live_trades` row with `fill_status='filled'` and `settlement IS NULL`:
    - Pull settlement result from Kalshi (or observation if Kalshi result not yet posted)
    - Compute `realized_pnl_cents = (100 - fill_price) if won else (-fill_price)` minus fee
    - Update row
  - Generate daily summary: P&L today, cumulative P&L, fill rate, count of risk-control blocks
  - Email/Discord the summary

### 6.2 Acceptance criteria

- [ ] Daily summary lands every morning at 04:00 UTC
- [ ] Cumulative P&L in DB matches Kalshi web UI exactly (we can audit any discrepancy)
- [ ] Settlement results match observation table (KNYC daily high)

**Effort:** 2 hours.

---

## Phase 7 — Alerts + monitoring

### 7.1 What gets an alert (immediate)

- [ ] Cron failure (any of: ECMWF ingest, GEFS ingest, live_trade, fill_checker, reconciliation)
- [ ] Any risk-control trigger fires (over the daily, weekly, or cumulative limit)
- [ ] Kill criterion fires (strategy halted)
- [ ] Disk usage > 60%
- [ ] Postgres connection failure

### 7.2 What gets a daily summary (low urgency)

- [ ] Yesterday's trades, fills, P&L
- [ ] 7-day rolling P&L, win rate, fill rate
- [ ] Avg spread on filtered trades (regime monitor)

### 7.3 Delivery

- [ ] Pick one of: Discord webhook (simplest), email via SES/Mailgun, Telegram, push notification
- [ ] Test alerts before live trading starts

**Effort:** 1-2 hours depending on delivery choice.

---

## Phase 8 — First 30 days of live trading

This is observation, not implementation. **No methodology changes during this window.** Just collect data.

- [ ] Day 1: trade 1 contract per signal. Single hour at limit only.
- [ ] Day 8 (after 1 week, ~5 trades): inspect fill rate, any unexpected behavior. Document.
- [ ] Day 30 (after ~15-20 trades): first formal review.
  - Fill rate vs expected?
  - Realized P&L vs paper-traded P&L on same days (which DB will still log via the paper-trade cron we kept running for diagnostics)?
  - Any kill criteria triggered?
  - Decision: continue to Phase 9 scale-up, or halt for review.

---

## Phase 9 — Scale-up decision point (after 60 trades / ~Month 4)

Per the report's pre-commitments:

- **If forward mean P&L lands in [+2¢, +8¢] AND fill rate ≥ 60%:** scale to $5k bankroll, half-Kelly. Continue current methodology.
- **If forward mean P&L lands in [−2¢, +1¢]:** halt. Strategy was probably p-hacked. Document and shelve.
- **If fill rate < 40%:** halt. Limit-only economics don't work; cross-spread economics don't either.
- **If avg spread > 5¢ over rolling 4 weeks:** halt. Regime degraded.

**No re-tuning of filters allowed at this checkpoint.** Either it works or it doesn't.

---

## Estimated total effort

| Phase | Code (me) | Account / observation (you) |
|---|---|---|
| 0 Pre-flight | 0 | ~30 min |
| 1 Manual paper | 0 | 25 min over 1 week |
| 2 API read-only | 1-2 h | 30 min |
| 3 Single order | 1-2 h | 10 min |
| 4 Live cron | 3-4 h | 3 days observation |
| 5 Fill monitoring | 2 h | passive |
| 6 Reconciliation | 2 h | passive |
| 7 Alerts | 1-2 h | 5 min setup |
| **Subtotal pre-live** | **10-14 h** | **~1 week elapsed** |
| 8 First 30 days | 0 | 30 days |
| 9 Review | 1-2 h | 2 h decision |

**Realistic timeline:** ~10 days from "start Phase 0" to "trading live." Then ~3-4 months of observation before any scale decision.

---

## What we are NOT doing in this plan

These are deferred to later or excluded entirely:

- **Multi-city expansion** (Chicago, etc.) — defer until NYC live results validate
- **Multi-feature EMOS** (cloud cover, dewpoint) — defer; binding constraint is data scale, not model sophistication
- **HRRR equal-weighting** — tested, +0.36¢ improvement, didn't clear pre-committed bar. Shelved.
- **KXLOWTNYC (daily lows)** — tested, decisively negative, deleted from project.
- **Intraday updates** (re-decide as the day progresses) — defer; complexity not justified before validation
- **Cross-spread fallback / escalation** — start pure limit-only, add later only if data justifies
