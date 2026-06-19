# Edge test protocol

**Pre-registered 2026-05-26, before the canonical paper-trade sample exists.**
**Do not modify after data accumulates. The point is to commit to the test before
the data tempts you to change it.**

## Purpose

Answer one binary question with statistical rigor: **does the rolling-EMOS
trading system have positive expected value after Kalshi trading fees?**

This question gates the month-6 decision (real money vs sunset thesis vs more
paper data). The model-tuning chapters of `ROADMAP.md` (DRN, foundation models,
conformal prediction) should not be started until this question is answered
with a clear yes.

## The test

**Hypothesis:**
- H₀: mean net P&L per trade = 0 (no edge after costs)
- H₁: mean net P&L per trade > 0 (positive edge after costs)

**Statistic:** Mean net P&L per trade in dollars, where:
- Net P&L = `gross_pnl - kalshi_fee` per contract (fee formula in
  `scripts/dashboard.py`: `ceil(0.07 × P × (1-P))` per contract per fill).
- One trade = one row in `paper_trades` table (one contract at unit sizing).
- Gross P&L: `+100 - entry_price_cents` if win, `-entry_price_cents` if loss
  (where win is defined by `contract_resolved_yes(observed_high, contract)`
  matched against the position).

**Test:** One-sample t-test, one-tailed, α = 0.05.

**Robustness check:** Bootstrap 95% confidence interval on the mean (10,000
resamples). If the bootstrap CI gives a different verdict from the t-test,
take the more conservative.

## Sample definition

**The sample is one model_source value in a contiguous window with no
pipeline changes.**

Distinct model configurations expected over the life of the project:
| `model_source` | active dates | comment |
|---|---|---|
| `EMOS combined (rolling 45d)` | 2026-05-25 only | 12Z combined, 18:45 UTC; retired after structural-timing insight |
| `EMOS ECMWF 00Z (rolling 45d)` | 2026-05-26 → 2026-05-28 | 00Z single-model stopgap pending GEFS 00Z backfill |
| `EMOS combined 00Z (rolling 45d)` | 2026-05-28 → 2026-05-28 (filter-less) | brief unfiltered window after GEFS 00Z backfill |
| `EMOS combined 00Z (rolling 45d) + entry≥60¢` | 2026-05-28 → ? | **canonical config with pre-registered entry-price filter** (see below) |

**Do not pool across configurations.** Each new config resets the clean-sample
clock. The canonical sample for the month-6 decision is whichever config is
running at the time of decision, with at least `n=200` trades since its
introduction.

### Pre-registered sub-strategy: entry-price filter (added 2026-05-28)

**Hypothesis (pre-registered before forward data exists):** filtering paper
trades to `entry_price_cents >= 60` captures the subset where the model is
"agreeing with market direction, more confidently" rather than betting
contrary to market consensus. The 2026-05-28 backtest discovered this pattern:

| Config | n (entry≥60) | Win rate | Mean net P&L | t-stat |
|---|---|---|---|---|
| EMOS combined 00Z | 189 | 76.2% | +3.07¢ | +1.01 |
| EMOS GEFS 00Z | 205 | 74.6% | +1.77¢ | +0.58 |
| EMOS ECMWF 00Z | 199 | 72.9% | +0.16¢ | +0.05 |
| EMOS combined 12Z @ 18:45 | 87 | 74.7% | −0.70¢ | −0.15 |

The pattern is consistent across all 4 configurations (all win rates 73-76%,
3 of 4 with positive mean net P&L) but **no single config reaches statistical
significance** at α=0.05 one-tailed (best t-stat: +1.01).

**The backtest result is descriptive only and not a decision criterion.**

**Pre-registered decision (commit NOW, evaluate after n≥200 forward trades
with the filter active):**
- Production cron `paper_trade_log.py` updated to log only trades where
  `entry_price_cents >= 60` (constant `MIN_ENTRY_PRICE_CENTS=60`).
- Forward trades from 2026-05-28 onward form the canonical sample for testing
  this hypothesis.
- All other decision-rule rows (mean ≥ +$0.05 → real money, mean ≈ 0 → more
  data, etc.) apply as written below.
- **Do not pool pre-filter and post-filter trades.** The backfilled trades
  (notes contain `as-of-recovery=...`) are descriptive only; the canonical
  test uses only forward-logged trades that pass the filter at decision time.

If a config is replaced mid-window, that's a structural change — start the
n=200 count over from the new config.

## Sample size and power

Per-trade net P&L has high variance (~$0.40 std-dev for binary contracts).
Detectable effect at n=200 with α=0.05 one-tailed:

| True mean edge | n needed for p<0.05 |
|---|---|
| +$0.10 / trade | ~44 trades (~9 days at 5/day) |
| +$0.05 / trade | ~180 trades (~36 days at 5/day) |
| +$0.02 / trade | ~1,100 trades (~7 months at 5/day) |
| +$0.01 / trade | undetectable at any reasonable sample |

**Interpretation:** This test can detect meaningful edges (5¢+/trade)
within 6 weeks. Small edges (1-2¢/trade) are below the noise floor and
would require many months of data. Be at peace with the inability to
distinguish "small edge" from "no edge" — that's a feature, not a bug,
because small edges don't compound enough to justify real-money risk.

## Decision rule

Evaluate ONCE at `n ≥ 200` trades in a single configuration.

| Result | Decision |
|---|---|
| `p < 0.05` AND mean ≥ +$0.05/trade | Real money small stakes ($2-5/contract). Proceed with monitoring. |
| `p < 0.05` AND mean +$0.02 to +$0.05/trade | More data. Re-evaluate at n=500. No real money yet. |
| `p > 0.05` AND mean ≥ +$0.05/trade | Promising but inconclusive. Continue paper to n=500. |
| `p > 0.05` AND mean near $0 | Inconclusive. Continue paper but begin questioning whether the system can ever surface edge given costs. |
| Mean < $0 (any p) | No edge in this configuration. Reconfigure (different threshold, different bracket types) or sunset. |

## What NOT to do (also pre-registered)

These are the failure modes a disciplined evaluation must avoid:

- **Do not eyeball cumulative P&L lines** and infer trends. Cumulative P&L is
  visually misleading at small n; a 3-trade winning streak looks like edge
  but isn't.
- **Do not peek and re-evaluate after wins or losses.** The test runs once,
  at `n ≥ 200`. Repeated peeking inflates Type I error.
- **Do not run subgroup analyses** ("edge is strong on BUY YES at outer
  brackets") and use them as decision criteria. That's p-hacking. Subgroup
  patterns can be reported as descriptive but cannot move the decision.
- **Do not pool across model configurations.** Each config gets its own test.
- **Do not change the decision rule** in response to results you've already
  seen. The rule is fixed before evaluation.

## Evaluation query template

To be run when `n ≥ 200` for a single `model_source`:

```sql
WITH resolved AS (
  SELECT
    pt.position,
    pt.entry_price_cents,
    pt.model_prob_yes,
    o.high_temp_f,
    c.bracket_type,
    c.strike_low,
    c.strike_high
  FROM paper_trades pt
  JOIN contracts c ON c.ticker = pt.ticker
  JOIN observations o ON o.date = pt.target_date AND o.station_id = 'KNYC'
  WHERE pt.model_source = $1  -- the specific config being evaluated
),
scored AS (
  SELECT
    entry_price_cents,
    position,
    CASE bracket_type
      WHEN 'greater_than' THEN high_temp_f > strike_low
      WHEN 'less_than'    THEN high_temp_f < strike_high
      WHEN 'between'      THEN high_temp_f BETWEEN strike_low AND strike_high
    END AS contract_yes,
    -- Win = position aligned with resolution
    CASE
      WHEN position = 'BUY_YES' AND (CASE bracket_type
        WHEN 'greater_than' THEN high_temp_f > strike_low
        WHEN 'less_than'    THEN high_temp_f < strike_high
        WHEN 'between'      THEN high_temp_f BETWEEN strike_low AND strike_high
      END) THEN TRUE
      WHEN position = 'BUY_NO' AND NOT (CASE bracket_type
        WHEN 'greater_than' THEN high_temp_f > strike_low
        WHEN 'less_than'    THEN high_temp_f < strike_high
        WHEN 'between'      THEN high_temp_f BETWEEN strike_low AND strike_high
      END) THEN TRUE
      ELSE FALSE
    END AS won
  FROM resolved
),
with_pnl AS (
  SELECT
    entry_price_cents,
    won,
    -- Gross P&L cents: +100-entry if win, -entry if loss
    CASE WHEN won THEN 100 - entry_price_cents ELSE -entry_price_cents END AS gross_pnl_cents,
    -- Kalshi fee cents: ceil(0.07 * P * (1-P) * 100), min 1
    GREATEST(1, CEILING(0.07 * entry_price_cents * (100 - entry_price_cents) / 100.0))::int AS fee_cents
  FROM scored
)
SELECT
  COUNT(*) AS n_trades,
  AVG(won::int)::numeric(5,4) AS win_rate,
  AVG((gross_pnl_cents - fee_cents) / 100.0)::numeric(8,4) AS mean_net_pnl_dollars,
  STDDEV((gross_pnl_cents - fee_cents) / 100.0)::numeric(8,4) AS sd_net_pnl_dollars,
  SUM(gross_pnl_cents - fee_cents) / 100.0 AS total_net_pnl_dollars
FROM with_pnl;
```

T-statistic: `mean_net_pnl_dollars / (sd_net_pnl_dollars / sqrt(n_trades))`.
p-value: `1 - t.cdf(t_stat, df=n_trades - 1)` (one-tailed, upper).

## Schedule

- **Now (2026-05-26):** Protocol locked. Paper trading runs.
- **2-3 weeks out:** Health check confirms cron is firing. Don't evaluate yet.
- **4-6 weeks out (n approaches 200 in canonical config):** Run the test.
  Apply the decision rule.
- **6-12 weeks (if "more data" verdict):** Continue paper, re-test at n=500.

## What this protocol does NOT cover

- **Sharpe ratio / volatility-adjusted return.** Mean per-trade P&L is the
  right primary metric for go/no-go; risk-adjusted measures are second-order
  refinements once positive edge is established.
- **Bankroll growth simulation.** The dashboard's Kelly P&L sim is a UI
  feature, not part of this test. The test uses unit-sized per-trade P&L
  because that's the cleanest signal of edge per opportunity.
- **Comparison across configs.** Each config gets evaluated in isolation;
  pairwise comparison ("is 00Z combined better than 00Z ECMWF-only?") is a
  secondary question that requires its own multiple-testing correction.
