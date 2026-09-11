# Polymarket Miami edge threshold: 0.25 -> 0.10

**Date:** 2026-09-11
**Status:** live (deploy: the live cron runs on Ashburn since the 2026-08-30 geo-block; pull there)
**Files:** `scripts/live_trade_polymarket.py`, `scripts/analysis/pm_edge_threshold_sweep.py`

## What changed

| | before | after |
|---|---|---|
| `EDGE_THRESHOLD` | 0.25 | **0.10** |
| max signals/day | 2 | 2 (unchanged, load-bearing — see below) |
| `CONTRACTS_PER_SIGNAL` | 150 | 150 (unchanged) |
| entry bound | 5–95c | unchanged |
| spend cap / kill | $300 / -$300 | unchanged (2 x 150 x 95c = $285 still fits) |

## Evidence

Forward PM paper log (`paper_trades`, model_source `... PM v2 ...`), which runs at
0.10 precisely to measure the band the live rail excluded. 302 signals, 5 cities,
2026-08-10..09-11, every row logged same-day. Settled with
`kalshi_equivalent_bracket` + `contract_resolved_yes`, crossing entry (YES at ask,
NO at 100-bid), taker fee 6·p·(1-p). Live rule applied: top-2 by |edge| per day,
entry 5–95c, 100 contracts. `uv run python scripts/analysis/pm_edge_threshold_sweep.py`.

Miami:

| threshold | trades | days | win | net/contract | total | daily Sharpe | t |
|---|---|---|---|---|---|---|---|
| 0.25 | 16 | 12 | 68.8% | +24.0c | +$383 | 6.0 | 1.31 |
| 0.15 | 29 | 16 | 72.4% | +20.5c | +$595 | 6.3 | 1.58 |
| **0.10** | **37** | **21** | **73.0%** | **+20.5c** | **+$759** | **6.2** | **1.79** |

Trades ADDED by 0.25 -> 0.10: 21, 76.2% win, +17.9c/contract, +$376, t 1.75.
Every Miami bucket from 0.10 up is positive; [0.10,0.15) is the weakest (60%,
+6c/contract, n=15). Both halves of the window positive at every threshold.

The gain is more trading days on the same edge (12 -> 21 of 22), not a better
per-contract number. Live venue truth at the time of the change: 13 settled
markets, 10 wins, +$357.00 realized at 0.25.

## Why the 2/day rail stays

Pooled across all five cities the >=0.25 bucket is flat (t -0.3) and the
[0.10,0.15) bucket is negative (t -2.0). A large |edge| is not itself a quality
signal. Ranking by |edge| inside a 2-per-day cap is what keeps the lower band
safe; lowering the threshold without the cap is a different, untested change.

This is Miami-only. KLAX loses at every threshold in the same log (0.25: 9.5%
win, -21c/contract, t -3.4); the 08-12 replay that showed KLAX positive was
under the pre-fix half-open bracket semantics. Do not port it.

## Risk accepted

- One month, t 1.75. Supportive, not proof.
- Fill rate on softer signals is unmodeled; live at 0.25 filled 8 of 10 orders.
  Softer signals sit closer to the market's own price, so spreads should be
  similar, but that is an assumption until the fill series says otherwise.
- More trading days means the -$300 kill is reached faster on a bad run. Accepted:
  the rail is armed and wired to reconciled fills.

## Revisit

After ~20 added-band trades (~3 weeks). Revert to 0.25 if the added band
(|edge| in [0.10, 0.25)) shows negative realized net over 15+ fills, or
immediately if cumulative realized approaches -$200.
