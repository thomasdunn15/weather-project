# 2026-08-17 — New Orleans (KMSY) live, raw@0.15, 250-unit

## Decision
New Orleans goes live: `CITY_CONFIG["KMSY"]` added to `scripts/live_trade.py`,
RAW-only at `edge_threshold=0.15`, 250 contracts/signal, decision time 14:58
UTC. Cron installed. OPERATOR OVERRIDE of the OOS Sharpe>2.5 deploy bar —
same category as the Dallas (2026-06-22) and Phoenix (2026-07-10) go-lives.

## Evidence
Forward-test only (real-time logged `paper_trades`, excludes backfilled
history), scored at 500 contracts/signal, 7% taker fee, for comparability
with the other cities' analysis:

| Threshold | Trades | Win% | Net | Sharpe | Split-half |
|-----------|--------|------|-----|--------|-----------|
| raw@0.10 | 114 | 45.6% | +$2,745 | 2.10 | weak both halves ($285→$2,460) |
| **raw@0.15** | **67** | **55.2%** | **+$4,480** | **5.12** | +$2,895 → +$1,585 (declining, both positive) |
| raw@0.20 | 44 | 54.5% | +$3,205 | 5.50 | not split-checked |
| raw@0.25 | 33 | 51.5% | +$2,020 | 5.18 | +$2,290 → **−$270** (breaks negative) |

0.15 chosen over 0.25 specifically because it holds up across the full
window; 0.25 looked fine in aggregate but the second half is negative — the
same shape that preceded Chicago's decay. 0.15's second half is weaker than
its first (declining) but stays positive. Blend is unusable (1 total forward
row) — raw-only, no union.

## What's different from Miami's switch (2026-08-17, same day)
Miami's raw@0.10 switch was a parameter change to an existing, already-live,
already-sized city. New Orleans is a new city going live for the first time:

- **No capacity/walk-book study** — unlike KORD/KMIA/KDFW/KPHX before their
  go-lives. Sized at 250 units (Phoenix parity) rather than the 500-unit
  KORD/KMIA/KDFW standard specifically because of this gap.
- **Weaker, declining evidence** — Miami's raw@0.10 split-half *improved*
  (51.8%→63.8% win). New Orleans' best threshold *declines* (58.1%→52.8%
  win), it's just still positive rather than negative.
- **Shorter window** — 67 trades over ~7.5 weeks vs Miami's 114 over 11.

This is a real bet on unproven forward capacity and a declining-but-positive
trend, not a clean validated edge. Treat it that way.

## Risk parameters
- `unit_contracts=250`, `daily_loss_limit_dollars=75`,
  `cumulative_kill_dollars=250`, `max_open_contracts=2500` — half of
  KORD/KMIA/KDFW's limits, matching the 250/500 size ratio.
- Aggregate limits bumped: daily $575→$650, cumulative $1,875→$2,125.
- `smart_cross_edge_threshold=0.15` (crosses every firing signal) — no fill
  data exists yet to justify posting, so prioritize actually getting filled
  over maker savings, same reasoning as Miami's RAW10 switch today.
- Dry-run verified end-to-end before install: 1 signal fired
  (`KXHIGHTNOLA-26AUG17-B97.5`, edge +17.1%, 250 contracts @ 30¢).

## Rollback
`touch halt/KMSY` stops trading immediately. Remove the `--city KMSY` cron
line (docs/crontab.txt, reinstall) to decommission entirely.

## Revisit triggers
- If the declining trend continues into a third, negative sub-period —
  pull back to paper.
- After ~30 days of live fills: run a capacity/walk-book study (same as
  KORD/KDFW/KMIA/KPHX got) before considering any size increase.
