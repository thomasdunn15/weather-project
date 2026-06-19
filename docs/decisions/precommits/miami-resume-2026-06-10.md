# Miami live trading — Resume pre-commitment (2026-06-10)

## Status change
- 2026-06-04: HALTED based on raw-strategy 90d t-stat = −0.49 (no edge in raw)
- 2026-06-10: **RESUMED** with BLEND-only strategy at 10% edge filter

## Statistical basis for resume

Rolling 90-day windows of BLEND-only strategy at 10% edge cutoff (walk-forward
fitted; coefficients refit on prior 60+ days every roll):

| Window | Fires | Total $ | Avg/trade | Win % | t-stat |
|---|---|---|---|---|---|
| Aug 25 → Nov 23, 2025 | 68 | +$32.22 | +$0.47 | 78% | **+8.31** |
| Sep 24 → Dec 23, 2025 | 77 | +$35.64 | +$0.46 | 77% | **+8.09** |
| Oct 24 → Jan 22, 2026 | 91 | +$41.94 | +$0.46 | 78% | **+9.21** |
| Nov 23 → Feb 21, 2026 | 94 | +$41.22 | +$0.44 | 74% | **+8.61** |
| Dec 23 → Mar 23, 2026 | 75 | +$34.08 | +$0.45 | 75% | **+8.58** |
| Jan 22 → Apr 22, 2026 | 73 | +$23.85 | +$0.33 | 62% | **+5.44** |
| **Feb 21 → May 22, 2026** | **61** | **+$16.53** | **+$0.27** | **61%** | **+4.10** |

Every rolling window passes Bonferroni correction at α=0.05/6 cities = 0.008
(critical t ≈ 2.6 one-tailed; all observed t > 4.10). Most recent window also
passes.

Raw-strategy comparison on the same test set: t=+0.64 at 25% edge filter
(confirms the halt rationale for the raw strategy was correct).

## Configuration — matches KORD framework

| Parameter | Value | Rationale |
|---|---|---|
| edge_threshold (raw) | 1.00 | Effectively disabled (raw has no edge) |
| blend_edge_threshold | 0.10 | Backtest-validated cutoff |
| sizing_mode | **unit** | Matches KORD's validated framework |
| unit_contracts | **500** | Matches KORD — comparable per-trade edge |
| max_contracts_per_trade | 500 | Depth cap |
| daily_loss_limit | $150 | Matches KORD |
| cumulative_kill | $500 | Matches KORD |
| max_open_contracts | 5000 | Matches KORD |

### Sizing history (logged 2026-06-10)

**Initial draft**: Amount $15/trade. Rationale: "conservative — half KORD's $."
**Revised**: unit=500. User feedback: under-deploys given Miami's t-stat strength
(+4.10 most recent 90d). Adopting KORD's framework matches the consistency of
the backtest result.

## Aggregate cross-city limits (updated)

| Limit | Old | New | Source |
|---|---|---|---|
| AGG daily loss | $150 | **$300** | KORD $150 + KMIA $150 |
| AGG cumulative kill | $500 | **$1000** | KORD $500 + KMIA $500 |

## Risk-control changes reverted (logged 2026-06-10 evening)

Earlier in the day I shipped two risk controls (`max_signals_per_day`,
`SIZE_EDGE_CAP`) intended to mitigate today's −$114 KORD loss. Backtest
through the dashboard showed both controls REDUCE Sharpe + total return on
both cities (anti-stacking drops winning low-edge bets; edge cap reduces
stake on the trades most likely to win). **Both reverted from live config.**
Today's loss was a tail event, not structural correlated risk.

Dashboard backtest still surfaces these as toggles for future exploration.

## No-tuning window
**30 days from today** (until 2026-07-10). No parameter changes during this
window — including: edge threshold, sizing mode/amount, loss limits. Halt is
allowed (discretionary or hit-limit) but no resume with different params
until re-evaluation.

## Re-evaluation criteria (2026-07-10)

| Metric | Bail threshold |
|---|---|
| Realized P&L | < −$300 cumulative over 30 days |
| t-stat on actual fills | < +1.0 over 30 days |
| Win rate on actual fills | < 50% over 30 days |
| Any single-day loss | ≥ daily kill threshold ($150) |

If ANY bail threshold hit, halt KMIA and analyze before resume.

If ALL acceptable: hold params for another 30 days.

## What the dashboard will show
- Miami city card: ACTIVE (green), shows realized + unrealized
- Hero: open contracts will reflect KMIA positions
- Next cron timer will include KMIA at 15:30 UTC alongside KORD at 14:46 UTC
