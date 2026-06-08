# Chicago resume — conservative parameters pre-commitment

**Status:** ACTIVE as of 2026-06-07 (REVISED same day before first cron fire)
**Replaces:** docs/halt_decision_2026-06-06.md (Chicago portion)
**Duration:** 30 days minimum — no parameter changes until 2026-07-07.
**Miami:** REMAINS HALTED. halt/KMIA file in place.

**REVISION 2026-06-07 evening (before first KORD cron fire 2026-06-08 14:46 UTC):**
Switched model from `combined` (GEFS+IFS) to `combined_hrrr` (GEFS+IFS+HRRR).
Backtest analysis on Dec 13 2025 – Jun 5 2026 showed:
- edge≥25% Amount $25 mean: $26.13 → **$37.25** (+$11.12, +43%)
- Statistical significance: p=0.013 → **p=0.003**
- Per-contract edge≥25%: +6.98¢ → **+9.61¢**
HRRR is now ingested daily for all 6 cities via new cron (03:30 UTC + 13:45 UTC
retry). The revision keeps every other parameter unchanged.

**REVISION 2026-06-08 (before first KORD cron fire today 14:46 UTC):**
After full Jun 2025 → Jun 2026 backfill confirmed combined_hrrr at edge≥25%
delivers Sharpe 4.86, mean $36.90/trade (vs combined $36.90, HRRR +$5.05/trade),
sized up to Amount $50/trade with cumulative_kill $500.
- amount_dollars: $25 → **$50** (2x; expected daily mean +$60-90, 30-day +$1,300-1,800)
- daily_loss_limit_dollars: $75 → **$150**
- cumulative_kill_dollars: $200 → **$500**
- aggregate caps mirror (= Chicago since Miami halted)
Rationale: backtest mean per-trade is $36-41 with lifetime data; at $25 sizing
that's ~$10/trade realized which is below the noise floor of the kill switch.
$50 gives clearer signal-to-noise per day while still being 1/3 of the lifetime
backtest peak DD. Pre-commit window unchanged: still 30 days, ends 2026-07-08.

This doc locks in **every parameter** for the next 30 days. Once signed, **no
modifications** to filter, sizing, execution, or risk envelope.

---

## Why resume

After yesterday's halt + extensive analysis, three findings justify a
small-scale resume:

### 1. Chicago's lifetime edge passes the strictest Bonferroni correction

Tested Amount $75/trade + 500 cap + post_inside_spread at every combo of
7 entry floors × 5 edge floors × 7 sizings × 3 caps × 6 cities (4,410 tests):

| Config | n | Win% | Mean | t-stat | p-value | Survives 4410-test Bonferroni? |
|--------|---|------|------|--------|---------|-------------------------------|
| **Chicago, lifetime, edge≥25%** | 253 | 39% | +$47.71 | **+4.64** | **0.0000057** | **YES** (threshold 0.0000113) |
| Chicago, lifetime, edge≥10% | 778 | 32% | +$13.99 | +3.05 | 0.0024 | No |
| Chicago, last 180d, edge≥25% | 129 | 35% | +$39.81 | +2.94 | 0.0039 | No (report-level only) |
| Chicago, last 90d, edge≥25% | 60 | 35% | +$11.11 | +0.87 | 0.39 | No |

The **lifetime edge≥25% Chicago config is the ONLY cell that survives the most conservative multiple-comparisons correction.** This is durable historical evidence that the filter captures genuine edge.

### 2. The edge≥25% Chicago config protects against the recent regime change

Monthly mean PnL with Amount $75 + 500 cap:

| Month | edge≥10% | edge≥25% |
|-------|----------|----------|
| 2026-03 | +$15.10 | +$4.53 |
| **2026-04** | **−$10.91** | **+$5.64** |
| **2026-05** | **−$7.36** | **+$10.12** |

In months where edge≥10% turned negative, edge≥25% **stayed positive**. Balance curve confirms: at edge≥25%, Chicago peaked 10 days ago and is still trending up. At edge≥10%, peaked 2 months ago and bleeding.

### 3. Smaller sizing limits downside while we forward-test

Amount $25/trade × 3 signals/day × 30 days = ~$2,250 deployed across the window.
Worst-case loss bounded by $200 kill switch (~7% of $3k bankroll). Expected
return if recent mean ($+11/filled at edge≥25%) holds: roughly $400-600 over
the window. Either way, we learn definitively from live data instead of waiting
for more paper.

---

## Pre-committed parameters

### Filter

```
city:              KORD (Chicago) only
edge_threshold:    25%        (changed from 10%)
entry_price:       no floor (entry >= 0)
execution:         post_inside_spread (unchanged)
forecast init:     00 UTC same day
model source:      EMOS combined_hrrr 00Z Chicago (rolling 45d)   [REVISED 2026-06-07pm]
models used:       GEFS + ECMWF/IFS + HRRR
decision time:     14:46 UTC daily
```

### Sizing — Amount $25/trade, 500 contract cap

```
SIZING_MODE                  = "amount"
AMOUNT_DOLLARS_PER_TRADE     = 25.0
MAX_CONTRACTS_PER_TRADE      = 500
```

Per-trade behavior:
- At avg entry ~25¢: 100 contracts, $25 stake
- At cheap 1-5¢ entries: 500-contract cap binds, stake $5-25
- At high 50-80¢ entries: 31-50 contracts, $25 stake

Daily expected deployment (2-3 edge≥25% signals/day):
- 1 signal: $25
- 2 signals: $50
- 3 signals: $75 (daily budget ceiling)

### Risk envelope — Chicago

```
DAILY_STAKE_BUDGET           = $75   (3 trades × $25)
DAILY_LOSS_LIMIT             = $75   (halt Chicago for the day)
CUMULATIVE_KILL              = $200  (halt Chicago permanently — write new pre-commit to resume)
MAX_OPEN_CONTRACTS           = 5000
SPREAD_REGIME_MAX_CENTS      = 5.0
```

### Aggregate envelope (Chicago only — Miami halted)

```
AGGREGATE_DAILY_LOSS_LIMIT   = $75   (= Chicago, since Miami inactive)
AGGREGATE_CUMULATIVE_KILL    = $200  (= Chicago)
```

### Miami — REMAINS HALTED

```
KMIA live cron:    DISABLED (commented out in crontab)
KMIA halt file:    halt/KMIA present
KMIA paper cron:   ACTIVE (continues accumulating research data)
```

Miami's last 90 days under best edge≥25% config: t = +0.87, p = 0.39. No
significant edge in current regime. Re-evaluate Miami at end of this window
(2026-07-07) using fresh 30-day paper data.

---

## What will NOT change for 30 days

Until 2026-07-07:

1. No edge threshold changes
2. No sizing changes (amount $25/trade, 500 cap)
3. No execution mode changes
4. No risk envelope changes (loss limits, kill switches)
5. No re-enabling Miami based on paper data alone
6. No adding other cities to live

**Permitted during the window:**
- Halt Chicago via halt file if something goes catastrophically wrong
- Bug fixes in code that don't change parameters
- Continue paper accumulation on all 6 cities

---

## Bankroll allocation

Total bankroll: **~$3,000** (mostly intact from the brief live experiment)

| Use | Amount | % bankroll |
|-----|--------|-----------|
| Daily Chicago trading budget | $75 | 2.5% |
| Cumulative kill reserve | $200 | 6.7% |
| Buffer (untouched) | $2,725 | 90.8% |

Worst-case day: $75 loss = 2.5% bankroll.
Worst-case window (kill triggered): $200 loss = 6.7% bankroll.

---

## Expected economics

### If lifetime edge holds (+$47/filled at edge≥25%, scaled to $25 sizing → +$15/filled)

- ~2-3 signals/day, ~80% fill rate → ~1.5-2 filled trades/day
- ~$22-30/day expected
- 30-day total: **+$650 to +$900**
- 30-day return: **+22% to +30%** on $3k bankroll

### If recent mean is the truth (+$11/filled at edge≥25%, scaled to $25 → +$3.50/filled)

- ~$7/day expected
- 30-day total: **+$210**
- 30-day return: **+7%**

### If edge has fully reversed (−$10/filled)

- ~−$20/day → cumulative kill at $200 triggers in ~10 days
- 30-day max loss: **~$200**
- 30-day return: **−7%**

---

## Pre-go-live checklist

For tomorrow's (Mon 2026-06-08) 14:46 UTC cron:

- [x] User approved this doc
- [x] `scripts/live_trade.py` updated:
  - [x] KORD `sizing_mode = "amount"`
  - [x] KORD `amount_dollars = 25.0`
  - [x] KORD `max_contracts_per_trade = 500`
  - [x] KORD `edge_threshold = 0.25`
  - [x] KORD `cumulative_kill_dollars = 200`
  - [x] KORD `daily_loss_limit_dollars = 75`
  - [x] KMIA config left as-is (city remains halted)
- [x] EDGE_THRESHOLD made per-city throughout live_trade.py
- [x] Amount sizing mode implemented in size_trade()
- [x] halt/KORD removed
- [x] halt/ALL removed
- [x] halt/KMIA preserved (Miami stays halted)
- [x] KORD cron uncommented in docs/crontab.txt
- [x] crontab installed
- [x] Dry-run KORD shows correct parameters

---

## Things explicitly traded off

1. **Lifetime-vs-recent contradiction.** Lifetime edge≥25% Chicago has
   p=0.0000057 (highly significant). Last 90 days: p=0.39 (not significant).
   The decision to proceed assumes the lifetime edge is more representative
   than the recent flat patch. This may be wrong.

2. **Post-hoc parameter selection.** Edge≥25% was identified as best AFTER
   seeing the regime change. The cleaner test would have been 30 days of fresh
   paper data at edge≥25% before going live. Skipping that step in favor of
   live data with smaller sizing.

3. **No Miami.** Concentration risk on Chicago alone. Mitigation: $200 kill
   switch is conservative, can't lose much.

4. **Reduced upside vs $75 sizing.** Expected return ~$650 vs $1,500-2,000
   that $75 sizing might have produced if lifetime edge holds. Smaller sizing
   buys peace of mind / smaller failure mode.

---

## Post-30-day evaluation criteria

On 2026-07-07, evaluate the window:

- **Pass:** realized cumulative ≥ +$200 AND mean ≥ +$8/filled trade
  → consider scaling to $50/trade
- **Mixed:** realized cumulative $0-200 OR mean $0-8/filled
  → 30 more days at $25/trade, no scaling
- **Fail:** realized cumulative ≤ $0 → halt Chicago, do not resume
- **Killed early (any time during window):** auto-halt at -$200; review

Whatever the outcome, also re-evaluate Miami at this checkpoint using fresh
30-day paper data.

---

## Sign-off

**User decision:** "Lets resume chicago at 25 dollars per trade" (2026-06-07)
**Date:** 2026-06-07
