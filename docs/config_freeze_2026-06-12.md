# Config freeze: 2026-06-12 → 2026-07-10

## Why

Between 2026-06-07 and 2026-06-11 the live config changed almost daily
(combined_hrrr switch, union mode, unit-500 sizing, smart execution, risk
controls added AND reverted same day, Miami resume + resize, data guards).
Each change restarted the forward-validation clock. The backtest already
says the strategy works; the missing evidence is that *live execution of a
fixed config* works. That evidence only accumulates while the config is
frozen.

## The frozen config

| | KORD | KMIA |
|---|---|---|
| Strategy | UNION: raw ≥ 25% OR blend ≥ 10% | BLEND-only ≥ 10% |
| Model | combined_hrrr (GEFS+IFS+HRRR) 00Z | combined (GEFS+IFS) 00Z |
| Sizing | unit 500 | unit 500 |
| Execution | smart (cross ≥ 40% edge, else post inside) | smart |
| Decision time | 14:46 UTC | 15:30 UTC |
| Daily loss / cum kill | $150 / $500 | $150 / $500 |
| Data guard | full ensemble required (31 GEFS + 50 IFS + 1 HRRR) | full ensemble (31 GEFS + 50 IFS) |

Aggregate: daily $300, cumulative kill $1,000.

## Rules

1. **Only safety bugs justify changes** — wrong data being traded on,
   broken order placement, broken reconciliation. Not strategy ideas, not
   one bad day, not a better backtest number.
2. **Strategy ideas go to [backlog.md](backlog.md)**, dated, with the
   evidence that prompted them. They get evaluated together on 2026-07-10.
3. **Halts are allowed** (risk-limit or discretionary). Resume only with
   the same frozen params.
4. Code changes that do NOT alter trading behavior (tests, dashboards,
   monitoring, data backfills, analysis scripts) are fine.

## Re-evaluation: 2026-07-10

Decide with full evidence, in one sitting:
- ~30 days of frozen-config forward results, both cities (vs. bail criteria
  in miami_resume_2026-06-10_precommit.md and chicago_resume_2026-06-07)
- KMDW-trained model validation (prep allowed during freeze; deploy only at
  re-eval)
- Real-depth walk-the-book execution analysis (~3 weeks of orderbook
  snapshots by then)
- Backlog items, batched
