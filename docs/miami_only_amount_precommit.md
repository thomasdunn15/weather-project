# Miami-only live trading with Amount $ sizing — pre-commitment

**Status:** ACTIVE as of 2026-06-06
**Replaces:** docs/chicago_miami_live_precommit.md (Chicago portion suspended; Miami sizing changed)
**Duration:** 30 days minimum — no parameter changes until 2026-07-06.

This doc locks in **every parameter** that drives real-money trading for the
next 30 days. Once signed, **no modifications** to filter, sizing, execution,
or risk envelope. Pre-commitment discipline is the only protection against
reactive tweaking on noise.

---

## Why this exists

After 2 days of multi-city live trading and extensive backtest analysis:

1. **Chicago shows fragility.** Recent intraday paper data was negative; edge
   at entry≥30¢ filter is negative (−8.4% return). The pre-committed test
   PASS was driven entirely by low-entry leverage that may not persist.
2. **Miami is the most robust signal across every filter tested.** Only city
   with positive edge at the strict entry≥30¢ filter (+44% return, Sharpe 5.19).
3. **Amount $ sizing dramatically outperforms Unit in empirical backtest**
   across every city. Driven by adverse selection (post_inside_spread skips
   losers) + better capital allocation toward where edge actually lives
   (5-25¢ entry zone).
4. **Dashboard empirical comparison showed Miami at Amount $50 → $28k final
   on $3k base** with Sharpe well above any other configuration tested.

Decision: concentrate live capital on the most robust signal (Miami) with
the sizing strategy the empirical data favors (Amount $).

---

## Pre-committed strategy

### Filter (unchanged from prior pre-commit)

```
edge threshold:  |edge| ≥ 10%
entry-price:     no floor (entry ≥ 0¢)
execution:       post_inside_spread (post 1¢ inside the spread when room exists)
forecast init:   00 UTC same day
model source:    EMOS combined 00Z Miami (rolling 45d)
decision time:   15:30 UTC daily (per intraday analysis)
```

### Sizing — Amount $75/trade with 1500 contract cap

```
SIZING_MODE                  = "amount"
AMOUNT_DOLLARS_PER_TRADE     = 75.0
MAX_CONTRACTS_PER_TRADE      = 1500
```

**Per-trade behavior:**
- At avg entry ~20¢: ~375 contracts, $75 stake
- At cheap 1-5¢ entries: 1500-contract cap binds, stake $15-75
- At high 50-80¢ entries: 100-150 contracts, $75 stake

**Daily expected deployment** (2-3 signals/day typical):
- Best case (1 signal): $75/day deployed
- Typical (2 signals): $150/day deployed
- Aggressive (3 signals): $225/day deployed

### Per-city risk envelope

```
DAILY_STAKE_BUDGET_MIAMI    = 225.0   # 7.5% of $3k bankroll
DAILY_LOSS_LIMIT_MIAMI      = 225.0   # halt Miami for the day
CUMULATIVE_KILL_MIAMI       = 600.0   # halt city permanently — write new pre-commit to resume
MAX_OPEN_CONTRACTS_MIAMI    = 5000
SPREAD_REGIME_MAX_CENTS     = 5.0
```

### Aggregate envelope (only one city live)

Same as per-city since Miami is the only live city:

```
AGGREGATE_DAILY_LOSS_LIMIT     = 225.0   # = Miami
AGGREGATE_CUMULATIVE_KILL      = 600.0   # = Miami
```

### Chicago — paper trade only

```
KORD live cron:    DISABLED in crontab (commented out)
KORD paper cron:   ACTIVE (paper_trade_log.py continues iterating KORD)
KORD halt file:    "halt/KORD" should be present as belt-and-suspenders
```

KORD remains in the stations registry and continues to receive daily
forecast ingestion + paper-trade logging. The data accumulates for
research and potential future re-commitment. **No live capital deployed
on KORD for 30 days.**

---

## What will NOT change for 30 days

Until 2026-07-06:

1. **No filter changes** (entry, edge, execution).
2. **No sizing changes** (amount value, contract cap).
3. **No risk envelope changes** (loss limits, kill switches).
4. **No new cities added to live.**
5. **No switching Miami to Unit** or any other sizing mode.
6. **No re-enabling Chicago live** based on day-to-day P&L.
7. **No fiddling with execution mode** — post_inside_spread is locked.

**Permitted during the window:**
- Halt Miami via halt files (`halt/KMIA` or `halt/ALL`) if something goes catastrophically wrong.
- Halt aggregate trading if cumulative loss exceeds the kill switch.
- Add Denver/Phoenix/LA to research / paper trading (no live money).
- Bug fixes in code that don't change parameters.

---

## Bankroll allocation

Total bankroll: **$3,000** (cleared from prior deposits).

| Use | Amount | % bankroll |
|-----|--------|-----------|
| Daily Miami trading budget | $225 | 7.5% |
| Cumulative kill reserve | $600 | 20% |
| Buffer (untouched) | $2,175 | 72.5% |

Worst-case-day scenario: $225 loss = 7.5% bankroll. Recover in ~3-5
average-positive trading days at Miami's expected edge.

Worst-case-week scenario: 5 × $225 = $1,125 max stake deployed, but
cumulative kill triggers at $600 first. Effective worst week: −$600 = 20%
bankroll. Halt + reassess required.

---

## Pre-go-live checklist

Before tomorrow's 15:30 UTC KMIA cron fires:

- [ ] User reviewed and approved this doc
- [ ] `scripts/live_trade.py` updated:
  - [ ] `KMIA` sizing_mode = "amount"
  - [ ] `KMIA` amount_dollars_per_trade = 75.0
  - [ ] `KMIA` max_contracts_per_trade = 1500
  - [ ] `KORD` live cron disabled
- [ ] `halt/KORD` touched to belt-and-suspenders halt KORD live
- [ ] Crontab updated: KORD live line commented out
- [ ] Dry-run KMIA shows expected behavior
- [ ] Kalshi balance ≥ $1,500 (covers worst case + buffer)

---

## Things explicitly traded off (read carefully)

By choosing this configuration over Miami at $50/trade or the prior
multi-city setup, you accept:

1. **Concentration risk.** All live capital is on Miami's edge. No
   cross-city diversification.

2. **Higher per-trade variance vs $50.** Each trade has 50% more dollar
   risk. Bigger swings up and down.

3. **Loss of Chicago's day-1 demonstrated profitability.** Day 1 made
   +$410 on Chicago. You're abandoning a strategy that's already worked
   based on empirical analysis you trust more than 1-day outcomes.

4. **Untested sizing in live conditions.** Amount $ has strong backtest
   support but only 1 day of live exposure (via the even-split approach).
   First time testing this exact configuration.

5. **Adverse selection assumption may not persist.** The empirical
   backtest's success depends on Kalshi's order flow staying
   price-revealing. If the market gets more retail-noise-driven, the
   maker-strategy's edge could shrink.

6. **You're picking maximum expected return over minimum-regret.** $50
   would have been the conservative ratchet-up plan. $75 is the
   commit-fully-to-the-data plan. You're choosing data over caution.

---

## Post-30-day evaluation

On 2026-07-06, evaluate the window:

- **Pass thresholds:** realized mean ≥ +$10/trade AND positive cumulative P&L
- **Mixed:** positive cumulative but < $10/trade mean → consider 30 more days at $50
- **Fail:** negative cumulative → halt Miami, write new pre-commit, do not resume without analysis

Per-trade backtest expectation at Amount $75: ~$30/filled trade.
Realistic live should be 30-50% of that due to imperfect fills:
**$15-20/filled trade as a healthy realized number.**

Do not change parameters mid-window even if early results look bad.
Pre-commitment exists exactly for the "early results look bad, let me
tweak" moment.

---

## Sign-off

**User signature:** _________________ (type "approved")
**Date:** 2026-06-06
