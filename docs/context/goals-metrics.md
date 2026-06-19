# Goals, metrics & capital

> What "success" means, the capital base, risk limits, and the bar to take a city live. Audience: agents. Last verified: 2026-06-19 (capital/targets confirmed with the user).

## TL;DR
- **Capital base = $3,050** (real deployed starting capital). The `3050` returnPct denominator in `dashboard/data_live.py` is therefore **correct** — not a stale guess.
- **Objective = prove a positive edge after fees**, not a fixed return/Sharpe/drawdown target. Judged by the validation milestones + bail criteria below.
- **Live risk envelope:** KORD & KMIA each **$150 daily / $500 cumulative** kill, 500-contract cap; **aggregate $300 daily / $1,000 cumulative**; spread-regime 5¢.
- **Bar to go live:** survive a strict Bonferroni-corrected edge test (only Chicago lifetime edge≥25% passed) + a 30-day no-tune window.

## Capital
- Starting capital: **$3,050** (deployed). returnPct = cumulative P&L ÷ 3050 → matches the constant at `dashboard/data_live.py` (`/ 3050.0`). Live account balance drifts above/below with P&L (was ~$3,492 at last check).
- The backtest tab's `bankroll` default (3000 in `dashboard/static/app.js`) is just a what-if input, independent of the real base.

## Objective & validation (no fixed target)
The goal is to demonstrate real edge after fees, then scale carefully. Milestones (from the investor overview):
| Milestone | ~trades | Test |
|---|---|---|
| Month 4 | ~60 | forward mean P&L in [+2¢, +8¢]? |
| Month 9 | ~135 | pooled forward-only t-test |
| Month 12 | ~180 | forward-only t-test clears p<0.05 if true edge ≈ +5¢ |

**Bail criteria** (pre-committed): cumulative forward P&L < **−$300**; forward mean < **−1¢** over first ~60 trades; **t-stat < +1.0** on actual fills (30d); **win rate < 50%** (30d); **limit-fill rate < 40%** over first 30 attempts. Any single-day loss ≥ the daily kill → halt.

## Live risk envelope (`scripts/live_trade.py`)
| Scope | Daily loss limit | Cumulative kill | Notes |
|---|---|---|---|
| KORD (Chicago) | $150 | $500 | unit 500, 500-contract cap, edge≥25% raw / 10% blend (UNION) |
| KMIA (Miami) | $150 | $500 | unit 500, blend-only ≥10% |
| Aggregate | $300 | $1,000 | `AGGREGATE_*` constants; + spread-regime 5¢ |
These numbers are **immutable during live trading** (see [conventions.md](conventions.md)); changing them needs a precommit.

## Bar to take a city live (expansion criteria)
- **Bonferroni over 4,410 tested cells** → significance threshold **p < 0.0000113**.
- **Chicago lifetime edge≥25%: t = +4.64, p = 0.0000057 — the only cell that survived.** (edge≥10% at t=+3.05 did *not* survive.)
- **Miami:** resumed on blend-only after **every rolling 90-day window showed t > +4.10** (raw strategy t=+0.64 → that's why raw Miami was halted).
- **30-day no-tune window** after going live (no edge/sizing/model changes); re-evaluate at the window end.

## Realized performance so far
- Chicago live **day-1: +$410** (3 winners) — explicitly treated as "one lucky day," not signal.
- Miami paper edge **regime-flipped ~Feb 2026**: last-90-day win rate fell to ~37–38% (raw), which triggered the **2026-06-06 halt**; blend-only survived and was resumed 2026-06-10.
- Backtest mean was **+3–5¢/trade** but did **not** clear Bonferroni — the unbiased forward estimate is closer to 0; live data is the real test.
- Current state: **config freeze → 2026-07-10**; KORD + KMIA live on conservative params in their no-tune windows. More findings in memory (`project_*_finding`) and [../decisions/](../decisions/).

## Sources
- User confirmation (2026-06-19): capital $3,050; goal = prove edge.
- [scripts/live_trade.py](../../scripts/live_trade.py) (CITY_CONFIG + `AGGREGATE_*`), [dashboard/data_live.py](../../dashboard/data_live.py) (`3050`), [../decisions/precommits/chicago-resume-2026-06-07.md](../decisions/precommits/chicago-resume-2026-06-07.md), [../decisions/precommits/miami-resume-2026-06-10.md](../decisions/precommits/miami-resume-2026-06-10.md), [../decisions/halt-2026-06-06.md](../decisions/halt-2026-06-06.md), [../reference/investor-overview.md](../reference/investor-overview.md).

## See also
[strategy.md](strategy.md) · [decisions.md](decisions.md) · [conventions.md](conventions.md)
