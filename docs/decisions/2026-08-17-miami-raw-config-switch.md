# 2026-08-17 — Miami switches from BLEND-only to RAW@0.10

## Decision
Miami's live config (`CITY_CONFIG["KMIA"]` in `scripts/live_trade.py`) switches
from BLEND-only (`edge_threshold=1.00` disabled, `blend_edge_threshold=0.10`)
to RAW-only at `edge_threshold=0.10`. Sizing unchanged (unit=500 contracts).

## Evidence for
Forward-test only (real-time logged `paper_trades` rows, excludes backfilled
history), 2026-06-03 → 2026-08-17, scored at 500 contracts/signal, 7% taker fee:

| Config | Trades | Win% | Net | Sharpe |
|--------|--------|------|-----|--------|
| BLEND-only@0.10 (prior live) | 12 | 83.3% | +$1,120 | 8.63 |
| RAW@0.25 | 30 | 66.7% | +$3,975 | 10.66 |
| Union (raw25 OR blend10) | 34 | 67.6% | +$4,015 | 9.75 |
| **RAW@0.10 (new live)** | **114** | **57.9%** | **+$7,415** | **5.70** |

RAW@0.10 split-half check (57 days each half): first half $2,955/114 trades,
51.8% win, Sharpe 4.66; second half $4,460, 63.8% win, Sharpe 6.59 —
**improving, not decaying**. Union was considered and rejected: blend
contributes only ~4 incremental trades beyond raw@0.25, not enough to justify
the added complexity over raw@0.10 alone, which nets more total profit than
either raw@0.25 or the union.

## Why this reverses the 2026-06-10 decision
Miami was moved to BLEND-only because RAW showed t=-0.49 over the 2026-06-04
lookback. That weak patch predates this forward window — every raw signal
logged since 2026-06-03 (real-time, not backfilled) shows raw solidly
profitable and stable across both halves of an 11-week window. BLEND-only was
capturing 12 trades of edge while raw was producing 114 profitable ones in
parallel, unflagged.

## Risk notes
- RAW@0.10 fires ~10x more often than BLEND-only did (~2/day vs ~1.3/week).
  Existing kill switches (`daily_loss_limit_dollars=150`,
  `cumulative_kill_dollars=500`) are unchanged — same per-trade stake (500
  contracts), so they still bound worst-case loss correctly, but a bad
  stretch will now consume that runway faster in wall-clock time. Watch the
  first 1-2 weeks closely.
- `smart_cross_edge_threshold` stays at 0.10 (unchanged) — since every RAW
  signal that fires already clears 10% by construction, this crosses every
  trade (no maker resting), same behavior as before, now applied to the
  larger raw set. Not retuned as part of this change; revisit if fill data
  suggests posting would save meaningfully on the wider raw edge
  distribution.
- Same caveat as everything else this quarter: ~11 weeks of forward data,
  not immune to the kind of decay Chicago and Dallas's UNION configs showed
  in this same analysis pass.

## Rollback
`touch halt/KMIA` stops trading immediately. To revert the config itself,
restore the prior block (BLEND-only, `edge_threshold=1.00`,
`blend_edge_threshold=0.10`, `use_blend=True`) via git.

## New Orleans (KMSY) — checked, not deployed
Same forward-test methodology applied to New Orleans as a candidate. Raw@0.25
(33 trades) looked promising in aggregate (+$2,020, Sharpe 5.18) but splits
badly: first half +$2,290/68.8% win/Sharpe 13.33, second half **-$270/35.3%
win/Sharpe -1.43** — the same shape that preceded Chicago's decay. Raw@0.15
is a better-behaved threshold (67 trades, +$4,480, Sharpe 5.12; both halves
positive: +$2,895 then +$1,585, declining but not negative) but still weaker
and shorter than Miami's picture, KMSY has no live `CITY_CONFIG` entry, no
decision-hour/kill-switch build, and no capacity/walk-book study. Left on
paper; revisit in a few more weeks once the second half either confirms or
fully breaks.
