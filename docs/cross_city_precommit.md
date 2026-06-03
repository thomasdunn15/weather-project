# Cross-city pre-commitment (Miami / Austin / further cities)

**Date locked:** 2026-06-03 (before Miami/Austin GEFS backfills complete)
**Purpose:** Pre-register the filter, execution model, and pass/fail thresholds we will judge new cities against — so that the "does it work in Miami?" answer cannot be talked into being "yes" by post-hoc cell picking.

This document is **immutable** once a city's data is examined. Any change to the test invalidates the result for cities already evaluated under it.

---

## Why pre-commit at all

NYC and Chicago between them have 48 (entry × edge) cells × 2 execution models × multiple model_sources. That is enough degrees of freedom that ~5% of cells will appear "significantly positive" by chance even if there is zero edge. Pre-registering the exact cell we look at first — and the threshold for calling it a pass — is the only honest way to test new cities.

Cross-city findings so far (n=897 NYC, n=868 Chicago, same window 2025-05-27 → 2026-05-26):

- Cross-spread overlap: **4 of 48 cells positive on both cities** (max t=1.36)
- Limit-100% overlap: **16 of 48 cells positive on both cities** (max t=2.11, but only one side)
- **No single cell** has both cities at t > 1.5

This is consistent with noise — or with a very weak universal signal that needs more cities to see.

---

## The pre-committed test

### Filter
```
edge threshold:    |edge| ≥ 10%
entry-price floor: none (entry ≥ 0¢)
```

### Execution
```
limit-100% (place at fair value, fill-or-kill at expiry assumption)
```

Rationale: cross-city evidence is **stronger on limit than on cross** (16 vs 4 cells positive on both). If a signal exists, this is where it shows.

### Model source
```
Primary:   "EMOS combined 00Z <City> (rolling 45d)"
Secondary: "EMOS ECMWF 00Z <City> (rolling 45d)"
Tertiary:  "EMOS GEFS 00Z <City> (rolling 45d)"
```

Combined is primary because that is what NYC ran in production. ECMWF/GEFS-only are reported for completeness but do not change the verdict.

### Sample size
```
Minimum n required to evaluate: 600 resolved trades per city
Target window:                  2025-05-27 → 2026-05-26 (one year)
```

If a city has < 600 resolved trades, **do not evaluate yet** — wait for more data rather than judge on a small sample.

### Pass / fail thresholds

Applied to each new city **independently**:

| Outcome  | Mean (limit, cross-fee net) | t-stat       | Action                                  |
|----------|-----------------------------|--------------|-----------------------------------------|
| **Pass** | ≥ +2.0 ¢/trade              | t ≥ 1.5      | Promote to paper-trade live (no money)  |
| **Mixed**| > 0 but t < 1.5             | —            | Document; do not promote; await more n  |
| **Fail** | ≤ 0 or t < 0                | —            | Drop this city, do not retest           |

### What "the verdict" means across cities

After Miami AND Austin both clear the n ≥ 600 bar, count their independent outcomes alongside NYC and Chicago:

| Cities passing (of 4) | Interpretation                                            |
|-----------------------|-----------------------------------------------------------|
| 4 of 4                | Strong evidence of real cross-city edge — scale up        |
| 3 of 4                | Likely real, but one city has structural difference       |
| 2 of 4                | Inconclusive; need more cities (LA, Denver, Phoenix)      |
| 0–1 of 4              | No edge; strategy is overfit to per-city noise            |

NYC currently sits in "Mixed" on this filter (entry≥0, edge≥10%, limit): mean +1.13¢ (cross-fee), t=0.43 — does NOT pass on its own.
Chicago currently sits in "Pass-borderline": mean +5.41¢ (limit), t ≈ 1.7 — does pass.

So the prior going into Miami/Austin is **1 of 2 passes**, leaning inconclusive.

---

## Rules of conduct during the test

1. **No cell-shopping.** The (entry≥0, edge≥10%, limit) cell is the only cell whose result counts. Other cells may be reported as context but do not change a city's verdict.

2. **No model-shopping.** Combined is the verdict-bearing model. If combined fails but ECMWF-only passes, **the city fails**.

3. **No window-shopping.** Use the window 2025-05-27 → 2026-05-26 (or as much of it as data allows, contiguous from start).

4. **No re-running after a fail.** If Miami fails, we do not re-test Miami in three months when more data arrives — that is just waiting for the noise to swing the other way.

5. **Risk envelope unchanged.** Even on a pass, no new city goes live with real money for at least 30 days of paper-trading (per the live-trading plan).

6. **Halt rule.** If 3 of 4 cities fail, abandon the cross-city universal-edge hypothesis entirely. The strategy is NYC-specific (and even then weak) — do not throw more compute at it.

---

## Expected timeline

(As of 2026-06-03 03:07 UTC)

| City    | GEFS backfill ETA       | Paper-trade backfill | First verdict possible |
|---------|-------------------------|----------------------|------------------------|
| Chicago | Done (78.9% in-window)  | Combined done; per-model running | Today                  |
| Miami   | Thu Jun 4 ~03:30 UTC    | After GEFS done; ~30 min | Thu Jun 4 PM           |
| Austin  | Thu Jun 4 ~03:30 UTC    | After GEFS done; ~30 min | Thu Jun 4 PM           |

After Thu evening we will have all four city verdicts on the same locked-in test.

---

## Where this gets logged

- Each city's evaluation result (mean, t-stat, n, pass/fail) goes in this file as a new section below, **with the date evaluated**. No retroactive edits to the test definition.
- Cross-city summary table updated after all four cities reported.
- Commit message convention: `precommit: <city> result (<pass|mixed|fail>)`.

---

## Evaluation log

### NYC + Chicago — recorded 2026-06-03 (before Miami/Austin land)

Per-model expansion (GEFS / IFS / Combined) of the pre-committed cell
(entry ≥ 0¢, edge ≥ 10%, limit-100%, net of fees):

| Model    | NYC mean (t)            | Chicago mean (t)         |
|----------|-------------------------|--------------------------|
| GEFS     | **−2.56¢** (t=−2.37)    | **+3.41¢** (t=+1.99)     |
| IFS      | **−1.53¢** (t=−1.48)    | **+3.31¢** (t=+2.32)     |
| Combined | **−1.11¢** (t=−0.89)    | **+3.87¢** (t=+2.50)     |

**Verdict** (against the locked thresholds, mean ≥ +2.0¢ AND t ≥ 1.5):

- **NYC: FAIL** on all 3 models (negative or near-zero on the pre-committed filter).
- **Chicago: PASS** on all 3 models (combined and GEFS pass cleanly; IFS borderline).

Stronger evidence emerges when edge threshold is raised (NOT part of the
pre-committed verdict, recorded here for interpretation only): Chicago shows
**monotone increasing mean with rising edge threshold**, reaching +11.91¢
(t=+3.34) at edge≥25% combined/limit. NYC is flat-near-zero across all
edge thresholds. This monotone signature is what a real edge looks like.

### Sanity-check on the Chicago signal (2026-06-03)

Before crediting Chicago's positive result, ran 5 bug checks:

1. **Observations distribution** — KORD avg 61.7°F, std 21.7°F; KNYC avg 62.5°F,
   std 19.3°F. Consistent with continental vs maritime climate. ✅
2. **Forecast field storage** — KORD IFS uses `tmax_f` (mx2t3); KNYC IFS has
   both `tmax_f` and `temperature_f` (2t fallback). EMOS calibrates either
   source independently. Not a bug. ✅
3. **Contracts attribution** — 2190 KXHIGHCHI rows, all correctly linked to
   station_id=KORD. ✅
4. **Bid-ask spreads** — KORD median spread 2¢ vs KNYC 1¢; mean 2.53¢ vs
   2.33¢. Mildly wider, **not dramatic** — does NOT strongly support the
   "less efficient market" theory. ⚠️
5. **End-to-end trade walk-through** — 5 high-edge KORD trades sampled, math
   reproduces, 4 wins / 1 loss consistent with cell-mean positive. ✅

No bug found. The Chicago signal is real *in the data*; whether it's real
*in the world* is what Miami/Austin will tell us.

### Hypothesis to test on Miami / Austin

The most plausible mechanism for Chicago's edge is **variance mispricing**:

> Kalshi prices contracts in fixed 1°F brackets. If a city's actual daily-high
> distribution is **wider** than the market's implied distribution, more
> outcomes fall in tail brackets. Market makers underprice the tails, EMOS
> catches it, edge is positive.

This predicts:

| City     | Expected daily-high variance | Predicted verdict |
|----------|------------------------------|-------------------|
| NYC      | Low (maritime, 19.3°F)       | No edge ✓ observed |
| Chicago  | High (continental, 21.7°F)   | Edge   ✓ observed |
| **Miami**  | **Very low** (tropical maritime) | **Predict: no edge / fail** |
| **Austin** | **High** (continental, hot extremes) | **Predict: edge / pass** |

If Miami fails and Austin passes, the variance hypothesis is supported and
we should add more high-variance cities (Denver, Minneapolis, Phoenix). If
Miami passes or Austin fails, the variance hypothesis is wrong and we're
back to "Chicago got lucky" or some other unidentified mechanism.

**Additional check to run on Miami/Austin when data lands:**
1. Compute KMIA and KAUS daily-high std for 2025-05-27 → 2026-05-26.
2. Plot mean PnL vs city std across all 4 cities — should be roughly monotone if variance hypothesis holds.
3. Spot-check 5 high-edge trades per city for math consistency.
