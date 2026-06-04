# Chicago + Miami live trading pre-commitment (DRAFT)

**Status:** DRAFT — not active until you review, edit, and sign off.
**Date drafted:** 2026-06-04
**Replaces:** Phase 8 NYC live trading (halted 2026-06-04 after pre-committed cross-city test showed NYC FAIL).

This doc locks in **every parameter** that drives real-money decisions on
KXHIGHCHI (Chicago) and KXHIGHMIA (Miami) for the next 30 days. Once signed,
**no modifications** to filter, sizing, or risk envelope. The discipline of
pre-commitment is the only thing that protects you from p-hacking yourself
into broke.

If during the 30-day window you want to change something: **stop trading
first, write a new pre-commit doc, then change.** Never change while live.

---

## Why this exists

The pre-committed cross-city test (docs/cross_city_precommit.md, 2026-06-04
verdict) produced:

| City | Verdict | Mean (limit) | t-stat | n |
|------|---------|--------------|--------|---|
| Chicago | **PASS** | +3.83¢ | +2.72 | 868 |
| Miami   | **effective PASS** | +7.49¢ | +4.11 | 521 |
| NYC     | FAIL    | −0.55¢ | −0.44 | 897 |
| Austin  | MIXED   | +0.52¢ | +0.33 | 634 |

Filter-cell overlap analysis: 20 of 23 filter cells (87%) are positive on
**both** Chicago and Miami under limit execution; 0 cells where Chicago wins
but Miami loses. Monotone increase in mean as edge threshold tightens on
both cities. Robust to filter choice.

User decision (2026-06-04): pivot live trading focus from NYC to
Chicago + Miami. **Skipping the 30-day forward paper-trade window** that
the original cross-city pre-commit recommended — this is the aggressive
choice and is documented as such for transparency.

---

## The pre-committed strategy

### Filter (identical to the passing backtest cell)

```
edge threshold:  |edge| ≥ 10%
entry-price:     no floor (entry ≥ 0¢)
execution:       limit-100% (post 1¢ inside the spread, hold to expiry)
forecast init:   00 UTC same day
model source:    EMOS combined 00Z {city} (rolling 45d)
```

**Per-city decision time (UTC) — chosen from time-of-day analysis on
intraday price snapshots, 2026-06-04:**

```
Chicago decision time:  14:46 UTC  (no compelling alternative in the data)
Miami decision time:    15:30 UTC  (~+2c/trade better than 14:46 on recent intraday)
```

Same filter, same execution model, same EMOS calibration approach for both.
If one city diverges in performance during live trading, that is data, not
a reason to tweak the other.

### Sizing — daily $ budget, not fixed contract count

Total starting bankroll: **planned $2,000; actual at go-live $1,039**
(deposit not fully cleared as of 2026-06-04 13:09 UTC). User decision
2026-06-04: **proceed at the planned $200/day deployment despite the
mismatch** — effective daily risk is therefore **20% of actual bankroll
until the $2k deposit clears**, not 10% as originally planned.

**Daily risk budget: $200/day**, allocated 75/25 to Miami/Chicago to
dampen Chicago's recent underperformance (May 2026 paper data showed all
times of day negative on a small but consistent sample — see "Things
explicitly traded off" below).

```
DAILY_STAKE_BUDGET_MIAMI    = 150.0   # 7.5% of bankroll, 75% of daily total
DAILY_STAKE_BUDGET_CHICAGO  =  50.0   # 2.5% of bankroll, 25% of daily total
TOTAL_DAILY_STAKE_BUDGET    = 200.0   # 10% of bankroll
```

**Per-trade caps** (so a single high-entry signal can't blow the daily budget):

```
PER_TRADE_STAKE_CAP_MIAMI    = 75.0    # half the city's daily budget
PER_TRADE_STAKE_CAP_CHICAGO  = 30.0    # ~60% of city's daily budget
```

**Logic on each cron tick:**
1. Compute `remaining_budget = DAILY_STAKE_BUDGET_<city> − stake_deployed_today`
2. `stake = min(PER_TRADE_STAKE_CAP_<city>, remaining_budget)`
3. `contracts = stake / (entry_price_cents / 100)` (rounded down)
4. Skip if `contracts == 0` (remaining budget too small)

With avg entry ~25-30¢ this implies ~250-500 contracts/day Miami, ~80-170
contracts/day Chicago. Exact counts vary with entry price.

### Loss limits (separate from stake budgets)

Under limit-100% execution your max loss per trade = stake (contracts go
to 0 if you lose). So daily LOSS limit ≈ daily STAKE limit if all bets lose.

```
DAILY_LOSS_LIMIT_MIAMI       = 150.0   # halt Miami for the day (same as stake budget)
DAILY_LOSS_LIMIT_CHICAGO     =  50.0   # halt Chicago for the day
AGGREGATE_DAILY_LOSS_LIMIT   = 200.0   # halt both for the day
```

### Cumulative kill switches

For a bad streak: assume up to 70% of bets lose for a week. Worst week
Miami = 5 days × $150 = $750 worst case stake at risk. Set kill switches
so a string of losses triggers halt before bankroll is significantly impaired.

```
CUMULATIVE_KILL_MIAMI        = 400.0   # 20% of bankroll, halt city until manual review
CUMULATIVE_KILL_CHICAGO      = 150.0   # 7.5% of bankroll, halt city until manual review
AGGREGATE_CUMULATIVE_KILL    = 500.0   # 25% of bankroll, halt BOTH permanently
```

If aggregate kill triggers ($500 down across both): write a new pre-commit
doc and review the strategy before resuming. Not a "wait 30 days and
restart" — a "the data has shown this doesn't work, redesign before risking
more capital" event.

### Other limits

```
MAX_OPEN_CONTRACTS_PER_CITY    = 500    # circuit breaker, not expected to bind
SPREAD_REGIME_MAX_CENTS        = 5.0    # if 4wk avg spread > this, halt city
```

If aggregate kicks in, both cities halt. If only one city's per-city limit
kicks in, only that city halts; the other keeps trading.

### Halt files (per city + aggregate)

```
~/weather-project/halt/KORD       — halts Chicago only
~/weather-project/halt/KMIA       — halts Miami only
~/weather-project/halt/ALL        — halts both cities
```

Manual halt: `touch halt/{KORD|KMIA|ALL}`. live_trade reads on each run.

### Capital allocation

Total starting bankroll: **$2,000** (after fund deposit).

**Formally split 75/25 Miami/Chicago** via the daily stake budgets above.
Both cities draw from the same Kalshi account; the split is enforced by
the per-city DAILY_STAKE_BUDGET caps in live_trade.py.

Why this split (vs 50/50 or 100/0):
- Miami passed the pre-committed test with t=4.11 — strongest cross-city
  signal. Recent forward paper performance roughly consistent with backfill
  (slight degradation in magnitude but directionally correct).
- Chicago passed the pre-committed test with t=2.72 — clear pass on
  backfill, but recent ~30 days of paper data showed all times of day
  negative with win rate dropping 38% → 27%. Could be noise (small sample)
  or genuine edge degradation. 25% weight caps the damage if recent
  underperformance is real, while preserving some exposure if it recovers.

Worst-case-day scenario: both cities deploy full budgets and all lose →
$200 loss = 10% of bankroll. Recover in ~25 days of breakeven trading, or
~10-15 days of average-positive trading.

Worst-case-week scenario: 5 losing days × $200 = $1,000 max stake at risk,
but cumulative kill switches trigger first ($400 Miami + $150 Chicago = $550
or aggregate $500). Halts before bankroll falls below ~$1,400.

---

## What will NOT change for 30 days

For the next 30 days from go-live:

1. **No changes to the filter** (entry, edge, execution model)
2. **No changes to sizing** (unit count, stake caps)
3. **No changes to risk envelope** (loss limits, kill switches)
4. **No new cities added to the live cron**
5. **No methodology changes based on individual trade outcomes**
6. **No "let me just try X" experiments**

Permitted during live:
- Add more cities to **paper trade** logging (zero real-money impact)
- Add more cities to backfill/research (zero real-money impact)
- Investigate bugs in the data pipeline (read-only)
- Halt trading (any city or both) via halt files
- Stop live trading entirely if a real bug surfaces (write new pre-commit to resume)

---

## Pre-go-live checklist

Before the first live cron fires, all of these must be true:

- [ ] User has reviewed and approved this doc
- [ ] `scripts/live_trade.py` updated to iterate {KORD, KMIA} and apply per-city limits
- [ ] Halt-file infrastructure (`halt/KORD`, `halt/KMIA`, `halt/ALL`) created
- [ ] Per-city pre-commit constants in `live_trade.py` match this doc exactly
- [ ] Crontab updated: one cron line per city at 14:46 UTC (or one line that handles both)
- [ ] Test fire: run `live_trade.py --dry-run` for one city, verify it correctly identifies trades without placing orders
- [ ] Kalshi account has sufficient cash balance to cover MAX_STAKE_DOLLARS × MAX_OPEN_CONTRACTS for both cities
- [ ] reconcile_live_trades.py works for KXHIGHCHI and KXHIGHMIA contracts (might need station-id awareness)
- [ ] monitor_fills.py works for non-NYC tickers
- [ ] Dashboard's Live Trading tab shows KORD + KMIA correctly
- [ ] User has decided what to do if both cities pass AND user wants to scale up (this is a future-state, not for now)

---

## Post-30-day evaluation

After 30 days of live trading:

- **Evaluate per city:** realized mean P&L per trade, t-stat, total realized P&L
- **Compare to backtest expectation:** Chicago +3.83¢/trade, Miami +7.49¢/trade. Allow for ~30% degradation due to imperfect limit fills.
- **Pass thresholds (per city):** realized mean ≥ +1.0¢/trade AND t ≥ 1.0
- **Fail = halt that city, write new pre-commit before resuming**
- **Mixed = consider 30 more days OR halt + redesign**

Do not change the filter or sizing during the 30-day window even if early
results look bad. Pre-commitment exists exactly for that "early results look
bad, let me tweak it" moment.

---

## Things the user is explicitly trading off

By skipping the 30-day forward paper-trade window, you accept:

1. **Selection bias is real.** The pre-committed test used a specific filter.
   Lots of OTHER filters could have been chosen and the data might not have
   shown the same edge under all of them. The cell-overlap analysis (87%
   positive on both cities) mitigates this but doesn't eliminate it.

2. **Live limit fills will be worse than backtest.** Backtest assumed 100%
   fill rate on limit-100% orders. Real-life fill rate is typically 60-80%.
   Expected realized return is ~25-40% lower than backtest mean.

3. **The historical data is ~1 year.** A second year of data could show
   regression to the mean. Going live now bets that the one year we have
   is representative.

4. **No out-of-sample validation.** Forward paper trading was the
   out-of-sample test. Skipping it means the live trades ARE the
   out-of-sample test, with real money.

5. **Chicago has been losing for the last ~30 days of intraday paper data.**
   Win rate dropped from 38% (backfill) to 27% (recent), with all times of
   day negative. Could be small-sample noise (n=66) or genuine edge
   degradation (other algos entered the market, weather pattern shift).
   The 25% Chicago weight is the response: capped exposure if recent
   underperformance is real; some exposure if it recovers. **You will be
   live-trading a strategy with a recent negative-mean window. Accept that
   risk consciously, not by default.**

These are the costs of skipping forward testing. The benefit is faster
deployment if the edge is real.

---

## Sign-off

**User signature (proposal):** _________________
**Date:** _________________

**Note:** "signature" is just typing "approved" or similar in chat. The
purpose is to make the moment of commitment explicit so you can't later
claim "I didn't really agree to that."
