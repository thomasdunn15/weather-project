# Polymarket bracket semantics corrected — v1 and v2 series merged, not replaced

**Date:** 2026-08-23
**Status:** applied
**Preserved:** `docs/analysis-snapshots/2026-08-23-pre-bracket-fix/` (112 + 4 rows, checksummed)

## What changed

`evaluation.kalshi_equivalent_bracket` mapped a Polymarket `between` bracket to
`a..b-1`, reading `gte92lt93` as "92 only". It is an inclusive pair, "92 to 93",
identical to Kalshi. The `-1` is removed. Tails (`gte{a}`, `lt{b}`) were already
correct and are unchanged.

Proofs are recorded in the snapshot README: the ladders step by 2 on every
station (so odd degrees would belong to no contract), and the venue's own market
description reads "be **between** 92F and 93F".

## Nothing was rewritten

`paper_trades` is keyed `(target_date, ticker, model_source)`. Corrected rows
were INSERTed under a `... PM v2 ...` label; no `UPDATE` or `DELETE` ran against
any historical row. Both series are queryable side by side, as
`combined` / `combined_hrrr` / `combined+blend` already coexist for Chicago.

The rebuild (`scripts/analysis/rebuild_pm_paper_v2.py`) re-reads the **full
ladder** from `prices` rather than recomputing the old rows, because
`paper_trades` only ever held contracts that passed the *buggy* filter —
rescoring just those would have inherited its selection bias. Inputs are the
`emos_mu`/`emos_sigma` logged that day and quotes at or before that day's
logging time: deterministic, no new forecast data, no hindsight.

## The bug was a systematic short bias, not noise

| series | signals | BUY_YES | BUY_NO | avg model_p | avg abs edge |
|---|---|---|---|---|---|
| v1 (half-open) | 112 | 10 | **102** | 0.172 | 0.267 |
| v2 (pairs) | 116 | 51 | 65 | 0.276 | 0.205 |

Halving `model_prob_yes` made almost everything look overpriced: **91% of v1
signals were short.** v2 is near balanced.

Contract-level diff over the 2026-08-10 → 08-23 window:

| | n |
|---|---|
| in both series | 71 |
| **side flipped** | **4** |
| v1 only (taken, shouldn't have been) | 41 |
| v2 only (missed) | 45 |

The dominant effect is signal *selection*, not side inversion.

## Live impact

One open position was placed on v1 logic: 2026-08-23 KMIA `gte92lt93`, BUY_NO
150 @ ~40c, order `C1ZGRKBCEDKA`, filled.

Under corrected brackets `mu=92.96, sigma=0.82` gives P(92 or 93) = **0.7097**
against a 0.610 market — edge **+0.0997**, which is *below* the 0.10 threshold.
So the correct action was **no trade**, not a reversed one. EV of the open
position by the corrected model is `0.29*60 - 0.71*40` = **-11c/contract ~
-$16.50**.

Settled PM P&L needs no restatement: both closed trades (08-20, 08-21) resolve
identically under either reading, verified degree by degree in the snapshot
README. Cumulative realized `+$63.01` stands.

## Guard against recurrence

`tests/test_bracket_normalize.py` keeps the retired assertion visible in its
docstring and adds `test_a_real_pm_ladder_tiles_every_degree_exactly_once`,
which walks real KMIA and KLAX ladders and asserts every degree matches exactly
one contract. This is the same off-by-one class as the earlier Kalshi
exclusive-upper misread noted in `contract_resolved_yes`; the tiling invariant
is what makes a third occurrence fail loudly.

## Open

- Today's 150-lot is still open. Exit or hold is the operator's call.
- `PolymarketClient.get_order` 404s on every id (wrong path); unused, undecided.
