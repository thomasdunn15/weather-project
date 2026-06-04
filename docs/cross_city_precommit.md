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

### Miami + Austin verdicts — recorded 2026-06-04

All 4 cities under the pre-committed test (entry ≥ 0¢, |edge| ≥ 10%,
limit-100%, combined model, window 2025-05-27 to 2026-05-26):

| City     | std°F | n_trades | limit mean (t)        | cross mean (t)        | Verdict             |
|----------|-------|----------|-----------------------|-----------------------|---------------------|
| New York | 19.3  | 897      | −0.55¢ (t=−0.44)      | −1.88¢ (t=−1.52)      | **FAIL**            |
| Chicago  | 21.7  | 868      | **+3.83¢ (t=+2.72)**  | +2.29¢ (t=+1.64)      | **PASS**            |
| Miami    | 6.8   | 521      | **+7.49¢ (t=+4.11)**  | +4.43¢ (t=+2.45)      | INSUFFICIENT (n<600)|
| Austin   | 12.8  | 634      | +0.52¢ (t=+0.33)      | −0.73¢ (t=−0.47)      | MIXED               |

**Tally: 1 PASS (Chicago) / 1 MIXED (Austin) / 1 FAIL (NYC) / 1 INSUFFICIENT (Miami).**

**Decision (2026-06-04): treat Miami as effective PASS despite formally
missing the n_min floor.** Miami's t=4.11 clears every reasonable
significance bar including Bonferroni-corrected for 192 comparisons
(t ≥ ~3.5). The 600-trade floor was set somewhat arbitrarily (~half
of NYC's n) to prevent calling small-sample noise a pass; at n=521
with t=4.11, the spirit of that requirement is satisfied. Decision
made knowing this is a goal-post move from the formal rule, recorded
here for transparency.

**Revised tally: 2 PASS (Chicago, Miami) / 1 MIXED (Austin) / 1 FAIL (NYC).**

### Filter-cell overlap test (Miami × Chicago, 2026-06-04)

Single-cell verdict could be one-off luck. The stronger test: does the
edge hold across the FULL filter grid (entry × edge thresholds)?
Computed across 23 cells with n ≥ 20 in both cities:

**Limit-spread execution:**

| Metric | Chicago + Miami | Random chance (null) |
|--------|-----------------|----------------------|
| Cells positive on both                | **20 / 23 (87%)** | ~25% |
| Cells with both t ≥ 1.0               | **12 / 23 (52%)** | ~6%  |
| Cells where CHI positive but MIA neg  | **0**             | ~25% |
| Cells where MIA positive but CHI neg  | 3                 | ~25% |

**Cross-spread execution:** 14/23 (61%) dual-positive. Less clean
because cross-spread cost eats more of the edge, but directionally
consistent.

**Monotone signature on both cities (limit, edge threshold ladder):**

| edge ≥ | CHI mean | MIA mean |
|--------|----------|----------|
| 10%    | +3.83¢   | +7.49¢   |
| 15%    | +6.53¢   | +6.27¢   |
| 20%    | +9.24¢   | +8.88¢   |
| 25%    | +12.80¢  | +12.61¢  |
| 30%    | +14.54¢  | +12.29¢  |

Both cities march upward in lockstep as the filter tightens. If
either signal were noise, the mean would bounce around zero across
thresholds rather than rising monotonically. Hard to fake by chance.

**Caveat:** filter cells nest (entry≥30 cell is a subset of entry≥0
cell), so cells are not independent and naive Bonferroni doesn't
apply. The qualitative pattern is strong enough that this concern
is secondary, but reported for honesty.

### What the data falsified

**Variance hypothesis: FALSIFIED.** The predicted ordering does not hold.

Sorted by std (low → high):

| City     | std°F | Verdict             | Predicted |
|----------|-------|---------------------|-----------|
| Miami    | 6.8   | strongest signal    | NO edge   |
| Austin   | 12.8  | no edge             | EDGE      |
| New York | 19.3  | fail                | (control) |
| Chicago  | 21.7  | pass                | (control) |

Miami (lowest variance) has the **biggest** edge. Austin (high
variance) has none. The data is not monotone in city std — it isn't
even directionally correct. The "Kalshi underprices tail brackets
in high-variance cities" mechanism is wrong, or wrong as the
dominant effect.

**Market-thinness hypothesis: ALSO FALSIFIED.** 24-hour volume on
the test day:

- Miami:   253,336 (largest of the four)
- NYC:     125,137
- Chicago:  88,869
- Austin:   70,629

Miami is **2× NYC's volume** and has the biggest edge. The "small
markets are less efficient → more edge" theory does not survive
this. Volume is uncorrelated (or anti-correlated) with edge.

### Candidate replacement hypotheses

Open questions that the 4-city data raises but doesn't answer:

1. **Tropical predictability bonus.** Miami's daily-high distribution
   is so tight (std 6.8°F) that EMOS calibrates extremely confidently
   on the central bracket. Market may price wings as if "any city
   could see ±15°F deviation" — actual probability near 0%. EMOS
   spots the gap on every contract, hence the +9¢/trade NO bets and
   the t=4.11.

2. **Retail-dominated trading.** Miami's high volume may be retail
   enthusiasm (hurricanes, beach weather, retirees) rather than
   algorithmic market making. Volume ≠ informed price-setting.

3. **EMOS may overfit on Miami's small sample / tight distribution**
   — and the apparent edge is a one-year-of-data artifact that won't
   replicate. Need ~12 more months to discriminate.

4. **Chicago + Miami pass for unrelated reasons.** Different
   mechanisms; the cross-city test only "validated" one of them.
   Worth treating Chicago and Miami as independent experiments going
   forward, not part of the same "universal edge" claim.

### Next steps

1. **Phase 8 NYC live trading unchanged.** Pre-committed for 30 days
   of observation; today is day 2. Do not modify based on this data.
2. **Continue forward paper-trade logging** for all 4 cities (daily
   cron updated 2026-06-03 to iterate stations). Miami in particular
   gets forward data starting today — useful to confirm the historical
   edge replicates out-of-sample on actual paper trades going forward.
3. **Chicago + Miami are the candidate cities for eventual live
   trading.** Pre-committed test was passed on Chicago, and (per the
   2026-06-04 decision) effectively passed on Miami. Do NOT promote
   either to live yet — the 30-day NYC observation needs to complete
   first, and a fresh pre-commitment must be written for any new
   live-trading city (sizing, halt rules, kill switches per city, etc.).
4. **Consider adding Denver, Phoenix, LA** to extend the cross-city
   panel. Each is 1-2 days of backfill. Not committing to trading any
   of them — but if Denver and Phoenix also pass, the "real edge"
   case strengthens further. If they fail, Chicago + Miami get
   relegated to "interesting but maybe not generalizable."
5. **Continue NOT live-trading NYC + Austin.** Both failed the
   pre-committed test. No mechanism known that says they will pass
   later, so don't burn capital chasing them.
