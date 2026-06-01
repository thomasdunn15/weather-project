# NYC Weather Contract Trading — Project Overview

**Author:** Project owner
**Date:** 2026-05-28
**Status:** Pre-launch. One year of paper-trade backtest complete. Live capital not yet deployed.

This document describes what the system does, what it has shown in backtest, what
it has not shown, and what would have to happen for the strategy to be considered
validated. It is descriptive, not promotional. Numbers are reproducible from the
backing PostgreSQL database.

---

## 1. What the system trades

**Venue:** Kalshi (CFTC-regulated event-contract exchange).

**Contract family:** `KXHIGHNY` — daily binary contracts on the high temperature
recorded at the official NYC observation station (KNYC, located in Central Park).
Each trading day Kalshi lists a strip of contracts covering possible daily highs,
each resolving YES or NO at midnight ET based on the NWS observation.

Three contract shapes appear in the strip:
- **`greater_than`** — "high > X°F"
- **`less_than`** — "high < X°F"
- **`between`** — "X°F ≤ high ≤ Y°F" (typically 1°F-wide brackets covering the mode of the forecast)

Contracts trade in cents, settle at 100¢ if YES, 0¢ if NO. Bid/ask spreads on
in-the-money brackets are typically 2–5¢ wide.

## 2. What the system predicts

A probability distribution over the next day's high temperature at KNYC, expressed
as a Gaussian (μ, σ) over degrees Fahrenheit. That distribution is converted to a
probability for each listed Kalshi contract, which is then compared to the market's
mid-price to compute an **edge** (model probability − market mid).

## 3. Forecast pipeline

```
   Raw NWP ensembles  →  Combined daily-high members  →  EMOS calibration  →  Bracket probabilities
       (GEFS + IFS)         (per ensemble member,            (rolling 45-day        (Gaussian CDF
                             max over hourly forecast        OLS-like fit            applied to
                             window)                          to recent obs)         each contract)
```

### 3.1 Numerical weather model inputs

| Model | Source | Members | Init hours used | Notes |
|---|---|---|---|---|
| **GEFS** | NCEP (NOAA) | 31 | 00Z | Global 0.25° |
| **ECMWF IFS** | ECMWF open data | 50 | 00Z | Global 0.4° |
| **HRRR** | NCEP regional | 1 (deterministic) | 00Z | Tested, did not improve calibration; not in production ensemble |

For each ensemble member, the daily-high member value is the maximum 2m
temperature across the relevant forecast hours covering the NYC afternoon
window (15Z–24Z = 11 AM – 8 PM EDT). This yields 31 + 50 = 81 ensemble members
per forecast day.

### 3.2 EMOS calibration

The raw ensemble is biased and under-dispersed (typical of NWP). We fit
**Ensemble Model Output Statistics** (Gneiting et al., 2005), a non-homogeneous
Gaussian regression:

```
  Y ~ N(a + b·ensemble_mean,  c + d·ensemble_variance)
```

Parameters `(a, b, c, d)` are re-fit daily on a **trailing 45-day window** of
(forecast, observation) pairs. We chose w=45 empirically — sweeps from 30 to 90
days showed essentially no difference in annual CRPS, so the choice is not
load-bearing.

The result is a calibrated forecast distribution N(μ, σ) over tomorrow's high.

### 3.3 Bracket probabilities

For each listed Kalshi contract we compute its probability under N(μ, σ) using the
Gaussian CDF, with a half-degree continuity correction (since temperatures are
recorded as integers, "high > 78" maps to P(continuous ≥ 78.5)).

## 4. Trading logic

For each contract:

1. Compute model probability `p_model` from the calibrated Gaussian.
2. Take a snapshot of the Kalshi order book at **14:45 UTC** (≈ 9:45 AM ET) — well
   before the 4 PM forecast resolution window, so afternoon temperature evolution
   is still uncertain.
3. Compute market mid `p_market = (yes_bid + yes_ask) / 200`.
4. Edge = `p_model − p_market`.
5. Filter: trade only when
   - `|edge| ≥ 0.10` (10 percentage points of probability), **and**
   - `entry_price_cents ≥ 60` (avoid low-priced contracts where Kalshi fees dominate)
6. Direction: positive edge → BUY YES; negative edge → BUY NO.

These filters were chosen on backtest data, which is the central
statistical caveat (see §7).

## 5. Infrastructure

- **Database:** PostgreSQL 16 with the TimescaleDB extension. Tables for
  `forecasts`, `observations`, `prices`, `contracts`, `paper_trades`.
- **Ingestion:** Python cron jobs pull GEFS/IFS via Herbie (open-data S3 mirrors),
  Kalshi prices via the public REST API, observations via NWS daily observation
  files.
- **Forecast loop:** Daily cron computes the combined ensemble, fits rolling EMOS,
  snapshots the order book, evaluates edges, and writes paper trades to the
  `paper_trades` table. Idempotent on `(target_date, ticker, model_source)`.
- **Dashboard:** Streamlit app for diagnostics: backtest charts, calibration
  curves, paper-trade P&L simulation, recent trade log.
- **Hosting:** Single cloud VM. Long-running backfills run under `tmux`. There is
  no failover; this is a one-machine project.

## 6. Backtest results

**Configuration backtested:** Combined GEFS + IFS, 00Z init, 14:45 UTC decision
time, rolling 45-day EMOS, |edge| ≥ 10%, entry ≥ 60¢.

**Window:** 2025-05-27 through 2026-05-26 (one year of resolved trades).

### 6.1 Trade counts

| Filter | Trades |
|---|---|
| All paper trades logged | 3,792 |
| After `|edge| ≥ 10%` | ~480 |
| After `entry ≥ 60¢` (production filter) | **189** |

### 6.2 Per-trade economics (cross-spread execution, paying the ask)

| Metric | Value |
|---|---|
| Trades (n) | 189 |
| Mean P&L per trade | **+3.07¢** |
| Standard deviation | 41.81¢ |
| Standard error of mean | 3.04¢ |
| t-statistic vs zero | 1.01 |
| One-tailed p-value | 0.156 |
| Bootstrap 5th-percentile mean | **−1.93¢** |

Reading the bootstrap: the data is consistent with a true mean as low as −1.93¢
or as high as ~+8¢. Zero is comfortably inside that range. **At the conventional
95% significance bar, no positive edge has been demonstrated.**

### 6.3 Per-trade economics (limit-target execution, 1¢ inside the spread)

If instead of crossing the spread we post a limit at `ask − (spread − 1)`:

| Fill assumption | Mean P&L | t-stat | One-tail p |
|---|---|---|---|
| 100% (idealized) | +5.05¢ | 1.68 | 0.046 |
| 70% (more realistic) | +3.54¢ | 1.42 | 0.078 |
| 50% (conservative) | +2.54¢ | 1.22 | 0.111 |

The 100% case **barely** clears the 5% bar; the realistic cases do not. Real fill
rates are unknown until live trading begins. Missed fills produce $0 P&L (no
exposure, no fee).

### 6.4 Bankroll simulation ($100 start, 189 trades, year backtest)

Median final balance across 200 random fill-pattern seeds:

| Kelly fraction | Cross spread | Limit 100% | Limit 70% |
|---|---|---|---|
| 10% | $131 | $165 | $143 |
| 20% | $127 | **$195** | $165 |
| 25% | $111 | $185 | $160 |
| 33% | $74 | $137 | $132 |
| 50% | $12 | $26 | $44 |
| 75% | <$1 | <$1 | <$1 |

The expected-value optimum is **~20% Kelly with limit execution**. Above 33%
Kelly, all modes lose money in expectation because one early cluster of losses
cripples compound growth.

### 6.5 Win rate and decomposition

- **Win rate on filtered trades:** ~55–56% (the database has exact numbers per
  bracket type).
- Edges are roughly symmetric between BUY_YES and BUY_NO positions.
- Most P&L variance comes from the `between` (1°F-wide) contracts, where small
  forecast errors flip wins to losses.

## 7. Statistical caveats — what the backtest does *not* prove

This section is the most important part of the document.

### 7.1 Multiple comparisons / specification search

Choosing "EMOS combined, 00Z init, 14:45 decision, 45-day window, |edge| ≥ 10%,
entry ≥ 60¢" required searching over:

- 2 model combinations (combined, combined+HRRR)
- 2 init hours (00Z, 12Z)
- ~5 entry-price floors tested (0, 55, 60, 65, 69¢)
- ~4 edge thresholds tested (5%, 7.5%, 10%, 12.5%)
- 3 EMOS window lengths sanity-checked

This is on the order of 20+ effective comparisons. A Bonferroni-corrected
significance bar would require p < 0.05/20 = **0.0025**, which no configuration
clears.

Translated: the headline "p = 0.046 under limit-100" is probably an artifact of
having searched many variants and reported the best. The unbiased estimate of
forward-looking edge is somewhere between 0 and the backtest's +5¢/trade — closer
to 0 than to +5 once specification search is accounted for.

### 7.2 The 12Z combined regime was abandoned

An earlier configuration (12Z init, 18:45 decision) was tested and showed no
edge after fees. We pivoted to 00Z. The 00Z result above is therefore the second
configuration tried, not the first.

### 7.3 HRRR addition was tested and did not help

We ingested a year of HRRR forecasts and added them as a single deterministic
member (1 of 82 ensemble members). Backtest mean moved from +3.07¢ to +3.19¢ —
statistical noise. HRRR is not in production.

### 7.4 No live execution data exists yet

All numbers above assume:
- Snapshot prices reflect prices we could have transacted at.
- Limit orders fill at known rates (we have no empirical fill rate).
- No slippage between order placement and fill.

Real execution will differ. The size and direction of that difference is unknown.

## 8. Cost structure

**Kalshi trading fee per contract:**
`$0.07 × P × (1 − P)`, rounded up to the nearest cent, charged at entry. No
settlement fee.

Worked example: a 70¢ contract incurs `0.07 × 0.7 × 0.3 = $0.0147 → $0.02/contract`.
Across the 189 backtested trades the fee burden was ~$0.018/trade, included in
all P&L figures above.

**Other costs:** None on Kalshi (no margin interest, no data fees). Infrastructure
costs are dominated by the cloud VM and S3 egress for forecast downloads
(~$30–50/month).

## 9. Capital plan

The intended initial deployment is **$1,000** of personal capital, sized as
follows:

- Position sizing: half-Kelly at most, on limit-target execution (corresponds to
  ~$5–25 per trade given typical edges).
- Expected trade frequency: 0.5–1 trade per day on average; ~180 trades/year
  matching the backtest.
- Worst-case drawdown if true edge is zero: ~$300–400 over 6 months based on
  bankroll simulation, before the strategy would be killed by the rules in §10.

This is risk capital. The expected-value calculation above suggests modest gains
under the optimistic interpretation of the backtest, but it is fully consistent
with breaking even or losing money once specification search is properly
discounted.

## 10. Forward validation plan and kill criteria

The only clean route to genuine statistical confidence is forward data not used
in any specification search.

| Milestone | Trades | Test |
|---|---|---|
| Month 4 | ~60 | Replication check: does forward mean P&L land in [+2¢, +8¢]? |
| Month 9 | ~135 | Pooled (forward-only) t-test |
| Month 12 | ~180 | Forward-only t-test; clears p<0.05 if true edge ≈ +5¢/trade |

**Pre-committed kill criteria** (set before live trading begins, to avoid post-hoc
rationalization):

- Cumulative forward P&L < −$300 at any point in months 1–6 → stop.
- Forward mean P&L < −1¢ over the first 60 trades → stop.
- Limit-fill rate < 40% measured over the first 30 trade attempts → revisit
  execution strategy before scaling.

## 11. Open questions / known limitations

- **Different contract type:** `KXLOWNY` (daily lows) has not been tested. Daily
  lows have different forecast skill characteristics and may or may not show
  similar edge.
- **Different station:** Other Kalshi-listed cities (Chicago, LA, Miami) have not
  been evaluated. Each would require its own EMOS calibration and backfill.
- **Adversarial selection:** Kalshi market makers see the same public forecasts.
  If our edge is real, it should erode as more participants run similar
  pipelines.
- **Forecast model changes:** GEFS and IFS are operationally maintained by
  governments; major model upgrades (e.g., GFS v17, IFS Cy49) shift the
  forecast distribution and require EMOS re-equilibration. The 45-day window
  handles this gracefully but masks the regime change.
- **Weather regime risk:** The backtest year (May 2025 – May 2026) spans one
  particular climate state. A summer with unusual variance behavior (e.g., a
  series of heat waves outside the training window) could degrade calibration.

## 12. Glossary

- **EMOS** — Ensemble Model Output Statistics. A post-processing technique that
  takes a raw NWP ensemble and outputs a calibrated probability distribution,
  correcting for bias and dispersion errors.
- **CRPS** — Continuous Ranked Probability Score. The loss function EMOS
  minimizes; lower is better.
- **Edge** — Difference between our model's YES probability and the market's
  implied probability (mid-price).
- **Kelly fraction** — The optimal stake size to maximize log-wealth growth under
  the Kelly criterion. "Half Kelly" stakes 50% of that to reduce variance.
- **Bracket** — A Kalshi contract on a temperature range (e.g., 78–79°F).
- **Cross the spread** — Take liquidity by paying the ask (buying) or hitting the
  bid (selling). Guarantees a fill at the worse price.
- **Limit inside the spread** — Post a passive order between bid and ask. Better
  price if filled, may not fill at all.

## 13. References to source

All numbers in this document come from the project's PostgreSQL database
(`weather` DB, schema in `src/weather_markets/db.py`). Reproducible via:

- `scripts/dashboard.py` — interactive view of all backtest panels
- `scripts/backfill_paper_trades.py` — regenerates the paper-trade table
- `docs/edge_test_protocol.md` — pre-registered evaluation protocol
- `src/weather_markets/emos.py` — EMOS implementation
- `src/weather_markets/aggregation.py` — ensemble combination logic
