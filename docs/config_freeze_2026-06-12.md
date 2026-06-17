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

## Changes applied during the freeze (safety/correctness only)

- **2026-06-15 — guaranteed order placement.** A post_only signal (T74 YES,
  +31% edge) was 400-rejected when the book moved under our maker limit so it
  would cross; the bot dropped it and the user placed it by hand. Fixed under
  the "broken order placement" exception: on a maker rejection the order is
  resubmitted as a taker at the current ask (`place_with_guaranteed_fill`),
  and rejected orders are now persisted to `live_trades` with
  `fill_status='rejected'` (previously they left no DB trace, so the dashboard
  looked like the bot never tried the signal). No change to which signals fire
  or to sizing. The smart-cross *threshold* question (should a 31% edge have
  crossed in the first place) stays in the backlog for re-eval.

- **2026-06-17 — per-city smart-cross threshold (KMIA fill mechanics).** Both
  KMIA blend orders (B93.5 YES +12.3%, B91.5 NO −14.0%) posted as passive
  maker orders and never filled — B93.5's market then ran 58¢→81¢ (the model
  was right; we missed it). Root cause: KMIA is blend-only with inherently
  small edges (~10-15%), all below the global 40% smart-cross threshold, so it
  NEVER crossed → chronic missed fills. Fix: per-city
  `smart_cross_edge_threshold` — KMIA=0.10 (crosses), KORD=0.40 (unchanged).
  This is an EXECUTION knob only: the 10% edge FILTER is untouched, so the same
  signals fire and sizing is identical — they just take liquidity instead of
  resting below a moving market. Filed as a fill-mechanics fix, not a strategy
  change. (Today's already-resting KMIA orders predate the fix; it takes effect
  at the next 15:30 UTC cron.)

## Re-evaluation: 2026-07-10

Decide with full evidence, in one sitting:
- ~30 days of frozen-config forward results, both cities (vs. bail criteria
  in miami_resume_2026-06-10_precommit.md and chicago_resume_2026-06-07)
- KMDW-trained model validation (prep allowed during freeze; deploy only at
  re-eval)
- Real-depth walk-the-book execution analysis (~3 weeks of orderbook
  snapshots by then)
- Backlog items, batched
