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

## Configuration

| Parameter | Value | Rationale |
|---|---|---|
| edge_threshold (raw) | 1.00 | Effectively disabled (raw has no edge) |
| blend_edge_threshold | 0.10 | Backtest-validated cutoff |
| sizing_mode | amount | Dollar-cap risk per trade |
| amount_dollars | $15/trade | Conservative — half KORD's $50 unit at 30¢ avg = ~$15 |
| max_contracts_per_trade | 500 | Depth cap |
| max_signals_per_day | **1** | Anti-stacking — start ultra-conservative |
| daily_loss_limit | $100 | Tighter than KORD's $150 (smaller scale) |
| cumulative_kill | $300 | Tighter than KORD's $500 (30-day evaluation window) |
| max_open_contracts | 3000 | Tighter than KORD's 5000 |

## Aggregate cross-city limits (updated)

| Limit | Old | New | Source |
|---|---|---|---|
| AGG daily loss | $150 | **$250** | KORD $150 + KMIA $100 |
| AGG cumulative kill | $500 | **$800** | KORD $500 + KMIA $300 |

## No-tuning window
**30 days from today** (until 2026-07-10). No parameter changes during this
window — including: edge threshold, sizing mode/amount, max_signals_per_day,
loss limits. Halt is allowed (discretionary or hit-limit) but no resume with
different params until re-evaluation.

## Re-evaluation criteria (2026-07-10)

| Metric | Bail threshold |
|---|---|
| Realized P&L | < −$200 cumulative over 30 days |
| t-stat on actual fills | < +1.0 over 30 days |
| Win rate on actual fills | < 50% over 30 days |
| Any single-day loss | ≥ daily kill threshold ($100) |

If ANY bail threshold hit, halt KMIA and analyze before resume.

If ALL acceptable: hold params for another 30 days; consider sizing increase
to $25/trade after 60 days clean.

## What the dashboard will show
- Miami city card: ACTIVE (green), shows realized + unrealized
- Hero: open contracts will reflect KMIA positions
- Next cron timer will include KMIA at 15:30 UTC alongside KORD at 14:46 UTC
