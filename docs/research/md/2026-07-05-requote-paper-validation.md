# 45-min maker re-quote — paper validation (VERDICT: keep OFF)

**Date:** 2026-07-05 · **Branch:** research/requote-validation · **Script:** scripts/analysis/requote_validation.py
**Scope:** READ-ONLY. No config change, re-quote NOT enabled. Closes the "merged but never paper-validated" gap
for `monitor_fills.py --requote`.

## VERDICT
**Keep the re-quote OFF for all three live cities (KORD, KMIA, KDFW).** It does not help; where it acts it
imports adverse selection and destroys net edge.

| city | addressable pop. | baseline netP&L | requote netP&L | Δ P&L | Δ Sharpe | re-quoted-fill edge |
|------|-----------------:|----------------:|---------------:|------:|---------:|--------------------:|
| KORD | small (5–10 sigs)| +$108           | −$446          | **−$554** | −0.28 | **−11.1¢/ct** (vs +12.3¢ first-window) |
| KMIA | **0 (structural)** | — | — | **0** | — | n/a |
| KDFW | small (6–8 sigs) | −$78            | −$911          | **−$833** | −0.08 | **−23.8¢/ct** (vs −40.3¢ first-window) |

(book window 2026-06-10..2026-07-05, unit=500, conservative `join` fill model; the `inside` fill model gives the
same verdict: KORD Δ −$458, KDFW Δ −$842, re-quoted edge −18.3¢/−33.7¢.)

## Why
1. **KMIA — 0 addressable, structural.** `smart_cross_edge_threshold` (0.10) equals KMIA's only entry filter
   (`blend_edge ≥ 0.10`), so **every fired KMIA order crosses at placement**. There are no resting maker orders for
   the re-quote to touch. Confirmed in reconstruction (17 fired, 17 cross, 0 maker) and in live_trades (all 25 KMIA
   orders crossed; the 4 fully-unfilled ones were crosses that found *no* ask liquidity — the adverse case).
2. **KORD / KDFW — the re-quote fires prematurely and adversely.** A maker order is only re-quoted if it is
   **fully unfilled at 45 min** (the `skip_partial` double-fill guard means partials are never re-quoted). The
   validation gate shows maker fill is low at 45 min (2–10%) but reaches **79–100% over the full day** — reproducing
   the live ~90% KORD fill anchor. So the unfilled-at-45-min orders **would have filled as makers later**; the
   re-quote instead crosses them *now* at the ask (taker fee = 4× maker) into a market that has repriced away from
   our resting bid. Those crossed fills settle at **negative per-contract edge** in both cities and both fill models.
3. **Live reality agrees.** Over the full live month, KORD and KDFW had **zero** fully-unfilled resting orders
   (every placed order filled ≥ partially; the 2 KORD zero-fill rows were `rejected`/never-rested). The re-quote
   would essentially never have fired for them; where it fires it only hurts.

## Adverse-selection result (the deciding number)
Re-quoted fills (market did NOT come to us in 45 min → we chase by crossing) have **negative** net per-contract
edge — KORD −11.1¢/ct vs +12.3¢/ct for first-window fills; KDFW −23.8¢/ct. Win-rate is not lower, but the price
paid (ask + taker fee) is: the fills you must chase are the adversely-selected ones.

## Caveats
- **Short book history:** orderbook_snapshots span only 2026-06-10..2026-07-05 (26 days, ~5-min cadence); the
  addressable population is a handful of signals per city. Directionally decisive, not high-N.
- **Baseline is pessimistic** (models maker fill only in the first 45 min, remainder expires at 0). A realistic
  baseline lets the maker keep resting and fill later at the good price, which makes the re-quote look *worse* still.
- Fill inference is churn-suppressed bid-ladder depletion (no trade tape), reused from the validated
  miami_fill_rate / walk_book_miami prior art. Sensitivity across `join`/`inside` fill models does not change the verdict.
- **Deploy bar:** the re-quote moves no city toward OOS Sharpe > 2.5 — every Δ Sharpe is negative.

## Reproduce
```
uv run python scripts/analysis/requote_validation.py                 # join (conservative)
uv run python scripts/analysis/requote_validation.py --fill-model inside
```
