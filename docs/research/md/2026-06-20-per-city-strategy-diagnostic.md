# Per-City Strategy Diagnostic: Best Profit, Sharpe, and Profit/Drawdown — and the Truly Best Parameters

*2026-06-20 · status: draft*

## Question

Across every city we have data for, what is the best achievable **profit**, **Sharpe ratio**, and **profit-to-max-drawdown ratio**, and — reconciling all three — what strategy parameters are *truly* the best for each city? "Truly best" means parameters that survive out-of-sample, not parameters that merely look good after searching the history.

Scope confirmed with the operator: rank the winner per city by **composite rank** across the three metrics; cover **all 11 high-temp city series equally** (thin-data series flagged); judge integrity with **walk-forward plus in-sample**.

## TL;DR / Verdict

- **At the production-like baseline (|edge| ≥ 0.10, both sides, all prices), the 11-city portfolio loses money net of fees: −$149.38 over 8,453 settled trades, annualized Sharpe −2.62, profit/DD −1.00, 34% win.** The edge is **not** broad. This corroborates the prior "no edge after fees" findings.
- **The edge is concentrated in three cities — Chicago, Miami, and (weakly) Seattle.** They are the only cities that are profitable at baseline, profitable in **both** halves of history, **and** profitable out-of-sample in walk-forward. Trading just those three at baseline returns **+$46.51, Sharpe 2.37, profit/DD 3.50**. Independent corroboration: **Chicago and Miami are exactly the two cities already promoted to live trading** (per `CLAUDE.md`) — this study supplies the data-driven reason the repo previously listed as "inferred only."
- **Per-city parameter optimization is mostly overfitting.** Every one of the 11 cities has an in-sample-profitable parameter combo, but 6 of 11 flip negative out-of-sample. The "best model family" differs arbitrarily by city (combined-EW, combined+HRRR, ECMWF, GEFS, combined) with no physical rationale — a fingerprint of selection bias over ~360 configs/city.
- **The only parameter sets that are *truly* best (composite-best **and** walk-forward-confirmed) belong to Chicago, Miami, and Seattle.** For New York, Denver, Austin, New Orleans, Las Vegas, and Phoenix, **no parameter set generalizes** — the honest "best parameter" is *don't trade*.
- **Live-money tension:** in 2 weeks of real fills, Miami agrees with the paper edge (+$223.87, 5 fills) but **Chicago disagrees (−$123.83, 17 fills)**. Sample is far too small to overturn 929 Chicago signals, but it blocks scaling Chicago until explained.
- **Confidence: moderate** for "edge is concentrated, not broad" (three independent lenses agree); **low** for any single city's precise optimal parameters (small OOS samples, decaying edge, multiple-testing inflation). All recommendations are **backlog proposals** under the config freeze.

## Methods & Data

**Data.** 21,734 logged signals in `paper_trades` (2024-05-27 → 2026-06-19), joined to `contracts` (strikes, `bracket_type`, station) and `observations` (actual daily high). `paper_trades` is a **full signal log**, not just trades taken: signed `edge` spans −0.99→+0.99 and 11,305/21,734 rows sit below the 0.10 threshold, so any threshold/side/model subset can be re-simulated. The low-temp series `KXLOWTNYC` (416 rows) was **excluded** — it settles on the daily *low* but this dataset settles on the daily *high*; including it produced a spurious 14.7-Sharpe artifact. Analysis covers **21,318 signals across 11 high-temp city series** (New York includes the legacy `HIGHNY` ticker format, same station).

**Settlement** uses the project's own rule (`evaluation.contract_resolved_yes`): `greater_than → high > strike_low`; `less_than → high < strike_high`; `between → strike_low ≤ high ≤ strike_high`. Observed highs are integers (0 non-integers in 18,276 rows). Settlement is 100% computable (all 21,734 rows join to an observation).

**P&L** mirrors the code exactly (`reconcile_live_trades.py`, `kalshi_fee_cents`): per contract, `gross = (100 − entry) if won else −entry`; `fee = max(1, ceil(0.07·p·(1−p)·100))` cents; `net = gross − fee`. Side ↔ edge sign is 100% consistent (BUY_YES⟺edge>0), so a threshold sweep is exactly `|edge| ≥ T` with the side fixed by sign. **Sizing = 1 contract per signal.** Sharpe is computed on the **daily** net-P&L series (days with ≥1 trade) and annualized by √(trading-days-per-year) inferred from each strategy's own trade frequency. Max drawdown is peak-to-trough of the daily cumulative equity; **profit/DD = total net ÷ max drawdown** (a MAR-style ratio).

**Parameter grid (per city):** model family ∈ {GEFS, ECMWF, combined, combined+HRRR, combined-EW} × threshold ∈ {0.05…0.30} (8 levels) × side ∈ {both, yes, no} × price band ∈ {all, 3–97¢, 10–90¢} ≈ **360 configs/city**. Combos require n ≥ 40 & ≥ 20 trading days (data-rich) or n ≥ 20 & ≥ 10 (thin) to rank. **Composite rank** = average of the three per-metric ranks; lowest wins. **Walk-forward** = pick the composite-best combo on the first 70% of each city's dates, measure it on the last 30%. **Stability** = baseline profit in the first vs second half of each city's history.

Reproducible script: `scripts/analysis/diagnostic_city_params.py` (stdlib only); per-trade export via a single `psql \copy` (settlement + fee computed in SQL). Full results: `/tmp/diag.json`.

## Internal Findings

### 1. Baseline diagnostic — current-style config (|edge| ≥ 0.10, both sides, dominant family)

| City | Family | n | Net profit | Max DD | Profit/DD | Sharpe (ann.) | Win% |
|---|---|--:|--:|--:|--:|--:|--:|
| New York | combined | 2676 | **−$66.10** | $68.41 | −0.97 | −2.36 | 29% |
| Chicago | ECMWF | 929 | **+$21.22** | $9.22 | 2.30 | 1.70 | 38% |
| Los Angeles | GEFS | 970 | −$38.16 | $42.15 | −0.91 | −3.89 | 32% |
| Denver | GEFS | 790 | −$31.15 | $33.88 | −0.92 | −3.13 | 36% |
| Miami | GEFS | 649 | **+$21.27** | $9.49 | 2.24 | 1.84 | 48% |
| Austin | GEFS | 774 | −$28.71 | $33.64 | −0.85 | −2.74 | 36% |
| New Orleans | combined | 425 | −$10.74 | $13.78 | −0.78 | −2.33 | 29% |
| Seattle | combined | 400 | **+$4.02** | $5.79 | 0.69 | 0.72 | 36% |
| Dallas | combined | 353 | −$7.18 | $7.18 | −1.00 | −1.93 | 29% |
| Las Vegas | combined | 310 | −$11.80 | $12.62 | −0.94 | −2.07 | 36% |
| Phoenix | combined | 177 | −$2.05 | $8.53 | −0.24 | −0.48 | 41% |
| **Portfolio (all 11)** | — | **8453** | **−$149.38** | $150.13 | −1.00 | **−2.62** | 34% |
| **Portfolio (Chi+Mia+Sea only)** | — | **1978** | **+$46.51** | $13.29 | **3.50** | **2.37** | 41% |

Only **Chicago, Miami, Seattle** are positive. The all-city portfolio is a steady bleed (profit/DD −1.00 means it ended near its worst point).

### 2. Best achievable per metric (in-sample, full history) — *optimistic ceilings*

These are the literal answers to "best profit / Sharpe / profit-DD per city," but they are **selected over ~360 configs** and should be read as ceilings, not expectations.

| City | Max-Profit combo | Max-Sharpe combo | Max-Profit/DD combo |
|---|---|---|---|
| New York | combined-EW, T0.15, yes, 10–90 → **+$2.36**, Sh 0.58 | same | ECMWF, T0.30, yes, 3–97 → P/DD 0.77 |
| Chicago | combined+HRRR, T0.15, both, all → **+$36.95**, Sh 3.22 | GEFS, T0.30, both → Sh 4.03 | combined+HRRR, T0.25, both → **P/DD 12.09** |
| Los Angeles | ECMWF, T0.15, yes, 10–90 → +$6.24, Sh 1.69 | same | same (P/DD 3.85) |
| Denver | ECMWF, T0.20, yes, all → +$4.47, Sh 1.16 | same | same (P/DD 1.85) |
| Miami | GEFS, T0.15, both, 10–90 → **+$31.18**, Sh 3.26 | same | GEFS, T0.15, yes, 10–90 → P/DD 10.41 |
| Austin | combined+HRRR, T0.05, both, 10–90 → +$10.88, Sh 2.07 | combined+HRRR, T0.12, yes → Sh 2.16 | same as max-profit (P/DD 3.35) |
| New Orleans | combined, T0.20, yes, 10–90 → **−$0.45** | combined, T0.20, no → Sh −0.27 | best is still **negative** |
| Seattle | combined, T0.15, both, 10–90 → +$6.51, Sh 1.52 | combined, T0.20, yes → Sh 2.20 | same (P/DD 2.33) |
| Dallas | combined, T0.25, both, 10–90 → +$9.40, Sh 3.91 | same | combined, T0.30, no → P/DD 4.57 |
| Las Vegas | combined, T0.25, both, 10–90 → +$6.10, Sh 1.77 | combined, T0.20, yes → Sh 2.06 | same (P/DD 3.67) |
| Phoenix | combined, T0.20, both, 3–97 → +$5.27, Sh 2.12 | combined, T0.20, no → Sh 2.38 | same (P/DD 2.24) |

Note New Orleans cannot clear zero on **any** config. Note also that the in-sample maxima imply a *different* winning model family for nearly every city — strong evidence these are fitted to noise.

### 3. The integrity tests — stability and walk-forward

**Baseline stability** (dominant family, T0.10, both; profit in first vs second half of each city's dates):

| City | H1 profit | H2 profit | Verdict |
|---|--:|--:|:--|
| Chicago | +$18.98 | +$2.24 | **STABLE +** |
| Miami | +$20.37 | +$0.90 | **STABLE +** |
| Seattle | +$3.58 | +$0.44 | **STABLE +** |
| New York | −$10.05 | −$56.05 | stable − |
| Los Angeles | −$18.30 | −$19.86 | stable − |
| Denver | −$9.01 | −$22.14 | stable − |
| Austin | −$23.63 | −$5.08 | stable − |
| New Orleans | −$5.00 | −$5.74 | stable − |
| Dallas | −$6.80 | −$0.38 | stable − |
| Las Vegas | −$7.96 | −$3.84 | stable − |
| Phoenix | −$0.26 | −$1.79 | stable − |

Only Chicago/Miami/Seattle are positive in both halves — but note **H2 ≪ H1 for all three: the edge is decaying** as the markets get more efficient.

**Walk-forward** (composite-best params chosen on first 70%, measured on last 30%):

| City | Train-selected params | In-sample profit | **OOS profit** | OOS n | OOS ¢/trade | OOS Sharpe |
|---|---|--:|--:|--:|--:|--:|
| Chicago | combined+HRRR, T0.25, both, all | +$30.59 | **+$3.02** | 69 | +4.38¢ | 1.58 |
| Miami | GEFS, T0.15, both, 10–90 | +$28.52 | **+$2.66** | 102 | +2.61¢ | 1.00 |
| Seattle | combined, T0.15, both, 10–90 | +$4.47 | **+$2.04** | 56 | +3.64¢ | 1.76 |
| Los Angeles | ECMWF, T0.15, yes, 10–90 | +$3.93 | +$2.31 | 22 | +10.50¢ | 2.33 |
| Dallas | combined, T0.25, both, 10–90 | +$6.23 | +$3.17 | 27 | +11.74¢ | 4.52 |
| New York | combined-EW, T0.12, both, 10–90 | +$10.46 | **−$14.43** | 282 | −5.12¢ | −3.15 |
| Denver | ECMWF, T0.25, yes, all | +$3.57 | −$1.42 | 21 | −6.76¢ | −2.33 |
| Austin | GEFS, T0.30, yes, 3–97 | +$0.54 | −$0.69 | 15 | −4.60¢ | −1.54 |
| New Orleans | combined, T0.12, both, 10–90 | +$5.62 | **−$8.64** | 65 | −13.29¢ | −9.43 |
| Las Vegas | combined, T0.30, both, 10–90 | +$5.91 | −$2.22 | 26 | −8.54¢ | −2.65 |
| Phoenix | combined, T0.20, both, 3–97 | +$6.62 | −$1.35 | 17 | −7.94¢ | −2.28 |

**Crucial confirmation:** for Chicago, Miami, and Seattle the walk-forward-*selected* params are the **same** as the full-history composite-best params, and all three stay positive OOS. For everyone else the in-sample profit is an illusion. Los Angeles and Dallas are OOS-positive but only on **n = 22 and 27** with a *tuned* family that loses at baseline — almost certainly noise, not edge.

### 4. Reconciled per-city verdict and "truly best" parameters

| City | Baseline | Both halves + | Walk-fwd OOS | **Verdict** | **Truly-best params** |
|---|:--:|:--:|:--:|:--|:--|
| **Chicago** | ✅ | ✅ | ✅ (n69) | **Robust edge** | combined+HRRR, \|edge\|≥0.25, both sides, all prices |
| **Miami** | ✅ | ✅ | ✅ (n102) | **Robust edge** | GEFS, \|edge\|≥0.15, both sides, 10–90¢ band |
| **Seattle** | ✅ | ✅ | ✅ (n56) | **Edge, thin/decaying** | combined, \|edge\|≥0.15, both sides, 10–90¢ band — *monitor* |
| Los Angeles | ❌ | ❌ | ➖ (n22) | No reliable edge | — (tuned OOS blip, not trustworthy) |
| Dallas | ❌ | ❌ | ➖ (n27) | No reliable edge | — (tuned OOS blip, not trustworthy) |
| New York | ❌ | ❌ | ❌ | **No edge (worst)** | — do not trade |
| Denver | ❌ | ❌ | ❌ | No edge | — do not trade |
| Austin | ❌ | ❌ | ❌ | No edge | — do not trade |
| New Orleans | ❌ | ❌ | ❌ | No edge | — do not trade |
| Las Vegas | ❌ | ❌ | ❌ | No edge | — do not trade |
| Phoenix | ❌ | ❌ | ❌ | No edge | — do not trade |

### 5. Live-money reality check (real fills, real fees)

| Series | Trades | Filled | Realized P&L | Window |
|---|--:|--:|--:|---|
| Chicago `KXHIGHCHI` | 19 | 17 | **−$123.83** | Jun 4–19, 2026 |
| Miami `KXHIGHMIA` | 9 | 5 | **+$223.87** | Jun 4–17, 2026 |
| **Net** | 28 | 22 | **+$100.04** | — |

Miami's live result corroborates its paper edge; Chicago's contradicts it. With only 17 Chicago fills over two weeks this is statistically weak, but it is a **live red flag** that must be explained (fills/slippage/partial fills vs variance) before Chicago is scaled.

## External Context

- **Kalshi fee formula confirmed.** Kalshi's general trading fee is `round_up(0.07 · C · P · (1−P))` dollars (C = contracts, P = price in dollars), peaking at ~1.75¢/contract near 50¢ and shrinking toward both ends [1][2]. This matches the project's `kalshi_fee_cents`. The code rounds **per contract** (and floors at 1¢) where Kalshi rounds **per order**, making our P&L marginally *conservative* on fees at 1-contract sizing — the safe direction.
- **Profit/drawdown ratio = MAR/Calmar family.** Dividing return by maximum drawdown is the MAR ratio (CAGR ÷ max DD) / Calmar ratio (Young, 1991, *Futures*); higher is better risk-adjusted performance [3][4]. Our "profit/DD" uses total net profit over a fixed horizon rather than annualized CAGR, so it is monotonic in MAR within a city but **not comparable in absolute terms across cities with different horizons**.
- **Overfitting from parameter selection is the central threat.** Searching many parameter combinations and reporting the best inflates in-sample Sharpe; out-of-sample performance regresses to the mean. Bailey & López de Prado's *Deflated Sharpe Ratio* (2014) shows the correction must account for the **number of trials** [5][6]. We evaluated ~360 configs/city (~3,960 total), so the in-sample maxima in §2 are exactly the quantity that needs deflating — which is why the verdict rests on walk-forward + stability, not on the in-sample optimum.

## Limitations & Threats to Validity

- **Paper-sim ≠ execution.** P&L assumes a fill of 1 contract at the logged entry price with no slippage or partial fills. The live data shows execution matters (Chicago). Real fill rates/slippage will lower every paper number.
- **Multiple testing.** ~360 configs/city inflate the in-sample best; treat §2 as ceilings. The verdict deliberately leans on out-of-sample and split-half agreement instead.
- **Single walk-forward fold + small OOS n.** 70/30 is one split; thin cities have OOS n of 15–27, where a few trades swing the sign (this is why LA/Dallas are not promoted).
- **Decaying edge.** Even robust cities show H2 ≪ H1; a parameter set fit on history may already be weaker today. Markets are getting more efficient (consistent with the binding-constraint view).
- **Model-family heterogeneity.** `model_source` mixes city-tagged and city-agnostic EMOS variants; family normalization may group slightly different fits under one label.
- **Settlement edge cases.** Uses `round(high_temp_f)`; Kalshi settles on the official NWS daily high. These should agree but rare rounding disagreements are possible. Low-temp markets were excluded entirely (wrong settlement variable).
- **Sizing/Sharpe convention.** Equal-1-contract sizing and daily-frequency annualization are defensible but not unique; ROI-weighted or Kelly sizing would change Sharpe magnitudes (not the cross-city ordering).

## Recommendation

**All items below are backlog proposals — no action is taken under the config freeze (until 2026-07-10).**

1. **At re-eval, narrow live trading to demonstrated-edge cities, not all 11.** The all-city portfolio loses (−$149, Sharpe −2.62); the Chicago+Miami(+Seattle) subset is the only profitable, walk-forward-confirmed slice (+$46.51, Sharpe 2.37, profit/DD 3.50).
2. **Adopt the walk-forward-confirmed per-city params** for those cities: **Chicago** = combined+HRRR, |edge| ≥ 0.25, both sides, all prices; **Miami** = GEFS, |edge| ≥ 0.15, both sides, 10–90¢; **Seattle** = combined, |edge| ≥ 0.15, both sides, 10–90¢ (watchlist only — thin, decaying).
3. **Do not per-city-tune the no-edge cities** (NY, DEN, AUS, NOLA, LV, PHX) — and do not be tempted by LA/Dallas's thin OOS blips. Their in-sample optima are overfitting artifacts; the correct parameter is *flat*.
4. **Resolve the Chicago paper-vs-live contradiction before scaling Chicago.** 17 fills at −$124 vs 929 paper signals at +$21 — diagnose whether it's fills/slippage or variance (ties into the ongoing `cross_at_ask` fill-rate forward test).
5. **Re-examine why the edge decays (H2 ≪ H1)** and whether a shorter rolling re-fit or a market-blend overlay restores H2 — the broader strategy lever is data/efficiency, not more parameter search.

Backlog entry appended to `docs/backlog.md`.

## Sources

**Internal (reproducible):**
1. `psql -d weather` — `paper_trades` ⋈ `contracts` ⋈ `observations`; per-trade export via `\copy (… settlement + fee in SQL …) TO '/tmp/pt_dataset.csv'` (21,734 rows).
2. `scripts/analysis/diagnostic_city_params.py` (this study) → console tables + `/tmp/diag.json`.
3. `src/weather_markets/evaluation.py::contract_resolved_yes` (settlement rule).
4. `scripts/reconcile_live_trades.py`, `scripts/live_trade.py::kalshi_fee_cents` (fee + P&L convention).
5. `live_trades` table — realized P&L by city series.

**External:**
1. Kalshi Fee Schedule (Feb 2026) — https://kalshi.com/docs/kalshi-fee-schedule.pdf
2. Market Math, "Kalshi Fees Explained (2026)" — https://marketmath.io/blog/kalshi-fees-guide-2026
3. Wikipedia, "Calmar ratio" — https://en.wikipedia.org/wiki/Calmar_ratio
4. QuantifiedStrategies, "Calmar Ratio: Definition, Formula" — https://www.quantifiedstrategies.com/calmar-ratio/
5. Bailey & López de Prado, "The Deflated Sharpe Ratio" (SSRN 2460551) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
6. Wikipedia, "Deflated Sharpe ratio" — https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
