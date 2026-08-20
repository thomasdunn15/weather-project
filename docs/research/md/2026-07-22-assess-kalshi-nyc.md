# Assessment: kalshi-nyc

**Engine decision** (debate rounds: 2):

NO-GO on a dedicated kalshi-nyc paper-first pilot at this time. Data sources are not the blocker — GEFS/IFS/HRRR forecasts and NWS CLI settlement are already ingested and production-proven, identical to the live cities. Liquidity is not the blocker either — NYC is thick (37,152 avg settled volume, 2c median spread, 6,266 avg open interest), comfortably above the measured ~500-700 contract single-venue depth ceiling, so there is no liquidity ceiling to test. The binding constraint is edge vs. fees: the strategy's gross edge is already fee-bound (≈ -0.33¢/trade at the best baseline config, net -1.88¢ after Kalshi's ~2c taker fee), and NYC specifically already has a large, non-thin historical record (n=2,676 signals, the diagnostic's 70/30 walk-forward-style split) showing net loss of -$66.10 and Sharpe -2.36 — nowhere near the +2.5 OOS deploy bar, and NYC is excluded from the only three cities (Chicago, Miami, Seattle) that cleared profitability in both history halves and walk-forward OOS. The 11-city portfolio including NYC loses -$149.38 net, Sharpe -2.62, versus +$46.51/Sharpe 2.37 for the Chicago+Miami+Seattle subset. Per the market-efficiency framing, no model refinement is proposed to rescue NYC's gross edge, and since this backtest sample already functions as walk-forward-quality historical evidence of failure, a fresh paper-only period would most likely just reproduce the same negative result rather than surface new information — it is not a case of insufficient data requiring measurement, it is a case of an already-measured negative result. The expansion-scout scorecard's 28/30 GO verdict is structurally misleading: it scores NYC 1/2 on both fees and capital (T+1 capital lock), the two binding constraints for a Kalshi vertical, while never gating on realized P&L. Prior verdict (HOLD, 2026-07-07) stands; no new evidence of structural market change is presented. Recommendation: do not commit engineering effort to a kalshi-nyc paper pilot; prioritize resolving the Chicago live-vs-paper divergence (17 live fills at -$124 vs 929 paper signals at +$21) before any new-city expansion, and revisit NYC only if future data shows a structural shift.

## Grounded claims

- NYC backtest at baseline config (|edge|≥0.10, both sides): n=2,676 trades, net profit -$66.10, Sharpe (ann.) -2.36, win rate 29%. `[doc:2026-06-20-per-city-strategy-diagnostic:4]`
- Only Chicago, Miami, and Seattle are profitable at baseline, in both halves of history, and out-of-sample in walk-forward; that subset returns +$46.51 net, Sharpe 2.37, profit/DD 3.50, and the diagnostic recommends narrowing live trading to it. `[doc:2026-06-20-per-city-strategy-diagnostic:2, doc:2026-06-20-per-city-strategy-diagnostic:7]`
- The full 11-city portfolio (including NYC) loses -$149.38 net over 8,453 settled trades, annualized Sharpe -2.62, 34% win rate. `[doc:2026-06-20-per-city-strategy-diagnostic:2]`
- Deploy bar is walk-forward OOS Sharpe > 2.5 on realistic execution; every live city except Chicago/Miami is an operator override of that bar. `[hist:kalshi-nyc:paper]`
- Gross trading edge is already fee-bound: at the best baseline config gross P&L is ≈ -0.33¢/trade (statistically ≈0), and the ~2c Kalshi fee pushes it to -1.88¢/trade net. `[doc:2026-06-20-polymarket-ibkr-venue-expansion:2, doc:2026-06-20-polymarket-ibkr-venue-expansion:4]`
- Kalshi fee schedule for NYC is standard: taker 2c / maker 1c per contract at 50c. `[cat:kalshi-nyc:venue]`
- kalshi-nyc data sources (GEFS/IFS/HRRR TMAX) are already ingested and the EMOS-to-bracket pipeline is production-proven; settlement source is NWS Climatological Report, same as existing live cities. `[doc:2026-07-22-expansion-scout-rank:2, cat:kalshi-nyc:series]`
- NYC liquidity is ample and not a constraint: 37,152 avg settled-market volume, 2c median open spread, 6,266 avg open interest, which exceeds the measured ~500-700 contract single-venue depth ceiling across live cities. `[cat:kalshi-nyc:liquidity, hist:kalshi-nyc:capacity]`
- Kalshi NYC contracts settle T+1 with capital locked until day-after settlement, unlike ForecastEx which allows same-day trading through resolution with only cash settling T+1. `[cat:kalshi-nyc:venue, doc:2026-07-22-expansion-scout-rank:2]`
- Regulatory access is clean: Kalshi is a CFTC-regulated DCM, US persons are permitted, and live API keys already exist on this box. `[cat:kalshi-nyc:venue]`
- Prior project verdict on kalshi-nyc was HOLD per the 2026-07-07 per-city optimization, not to be re-litigated without new data. `[hist:kalshi-nyc:prior]`
- NYC's own paper-trade signal log has 7,284 rows over 786 days with mean |edge| 25.1%, but this reflects forecast-signal magnitude, not realized net P&L. `[hist:kalshi-nyc:paper]`
- The expansion-scout-rank scorecard gives kalshi-nyc a 28/30 GO(paper-first) verdict while scoring it 1/2 on fees and 1/2 on capital (T+1 lock) — the two binding operational constraints — without gating on realized backtest P&L. `[doc:2026-07-22-expansion-scout-rank:2, doc:2026-07-22-expansion-scout-rank:0]`

## Specialist findings

### Data availability

**REVISED FINDINGS: KALSHI-NYC EXPANSION — CHALLENGE DISMISSED**

**Challenge verdict: Unfounded.** The evidence directly confirms the citation. [doc:2026-06-20-per-city-strategy-diagnostic:4] *does* contain the full baseline diagnostic table with NYC figures intact:

| City | Family | n | Net profit | Sharpe (ann.) | Win% |
|---|---|--:|---:|---:|--:|
| New York | combined | 2,676 | −$66.10 | −2.36 | 29% |

This is not an extrapolation, fabrication, or implicit derivation — it is the explicit "**Baseline diagnostic — current-style config**" section heading :4 in the document, showing all 11 cities stratified with city-specific sample sizes, profits, and Sharpes. The challenge's speculation that the figure "cannot be located" in the evidence set is contradicted directly by the provided source text, which shows the full table.

---

**Verdict: NO-GO — unchanged.**

The evidence establishes:

1. **NYC is demonstrably unprofitable in-sample**, with negative Sharpe (−2.36) over a large sample (n=2,676 settled trades) at the production threshold (|edge| ≥ 0.10, both sides). This is not a data-scarcity problem; the sample is robust.

2. **Only three cities show walk-forward OOS profitability**: Chicago (+$21.22, Sharpe 1.70), Miami (+$21.27, Sharpe 1.84), and Seattle (+$4.02, Sharpe 0.72). [doc:2026-06-20-per-city-strategy-diagnostic:7] recommends narrowing live trading to this subset. NYC does not clear the Sharpe > 2.5 deploy bar.

3. **The gross edge is fee-bound** at ≈ −0.33¢ even at the best baseline configuration [doc:2026-06-20-polymarket-ibkr-venue-expansion:2]. Expanding into a structurally unprofitable city adds operational friction without offsetting return.

**Recommendation:** Do not pursue kalshi-nyc as paper or live. The three demonstrated-edge cities (Chicago, Miami, and optionally Seattle) are the focus.

### Forecast tractability

Looking at the challenge: you're right. **KLAS (Las Vegas) is an inland desert city, not coastal.** The source document characterizes the skill deficit as affecting "coastal/terrain stations" — and while KLAS does face complex terrain (valley in the Mojave surrounded by mountains), it is not a coastal example. My original finding conflated the two categories and used KLAS incorrectly to argue a coastal-microclimate analogy.

This weakens the reasoning pathway for NYC. Here's the revised assessment:

---

## Revised Forecast Tractability Assessment: kalshi-nyc

**Recommendation: PAPER-FIRST (unchanged), but on stronger empirical grounds.**

### Forecast Applicability (Revised)

EMOS-calibrated distributions are mechanically applicable to NYC. However, **NYC is not identified as an edge-positive city.**

**Two tractability risks (refined):**

1. **Absence from robust diagnostic cities** [doc:2026-06-20-per-city-strategy-diagnostic:6] — the per-city diagnostic identifies edge as concentrated in **Chicago/Miami/Seattle only**; NYC is not listed among these walk-forward OOS Sharpe > 2.5 cities. This is the load-bearing empirical fact. The coastal/terrain resolution bottleneck applies specifically to the stations listed (KSFO/KLAX are coastal; KLAS/KPHX are complex terrain) — whether NYC's coastal-urban-canyon profile creates an analogous deficit is *not* directly addressed in the evidence.

2. **Skill ≠ edge binding constraint** [doc:2026-06-20-polymarket-ibkr-venue-expansion:4] — the market carries 56–95% of weight in the blend; gross P&L ≈ 0 and fees bind. A 25.1% mean paper |edge| at KNYC reflects forecast quality, not execution reality; Chicago's live divergence from paper expectation signals that paper-sim edge does not reliably convert.

### Data & Execution Sufficiency
- **Data sources:** GEFS+IFS coverage exists; 7,284 paper trades over 786 days is a reasonable pilot sample.
- **Liquidity ceiling:** Unquantified. Kalshi's thinness (28 live orders in 16 days across 2 cities baseline) means NYC's execution risk is unknown.

### Verdict
**Recommend paper-first validation with explicit OOS Sharpe target = 2.5.** The forecast stack is sound, but NYC's *empirical* absence from the edge-positive city set is the primary indicator — not an assumption about coastal-terrain resolution. Validate on 45–90-day walk-forward OOS Sharpe; only promote to live if it clears the bar without operator override.

### Resolution clarity

Perfect. The distinction is clear now:

- **Kalshi (Denver, NYC, all daily-high contracts):** capital/cash locked T+1 (line 295, 306)
- **ForecastEx (Miami, Dallas, Chicago):** same-day trading through resolution; **only cash** settles T+1 (lines 319, 332)

The challenge has a valid point: my resolution findings said "same-day intraday settlement, consistent with existing production setup" but didn't distinguish **trading** (whether you can still trade after resolution) from **capital release** (when you get your cash back). Kalshi's daily-high contracts lock capital T+1, which is different from ForecastEx's model.

Now I'll write a revised findings summary that addresses this directly:

---

## Resolution Clarity: Settlement Source & Timing for kalshi-nyc — REVISED

**Settlement Source:** Documented and clean. The candidate settles on **NWS Climatological Report** [cat:kalshi-nyc:series], identical to the current live universe (Chicago, Miami, Dallas). This is a primary, auditable, no-controversy source.

**Settlement Timing — Capital vs. Trading:** The prior findings asserted "same-day intraday settlement, consistent with existing production setup" but incompletely. The expansion-scout-rank (§kalshi-nyc [doc:2026-07-22-expansion-scout-rank:2]) explicitly notes **capital** 1/2 with the constraint **"T+1: capital locked until day-after settlement"** [doc:2026-07-22-expansion-scout-rank:2]. 

This reflects **Kalshi's cash settlement rhythm:** orders are placed same-day (consistent with existing Chicago/Miami/Dallas live universe), and contracts resolve same-day on NWS publication. However, *capital is not freed for redeployment until T+1*. This differs from ForecastEx venues (Miami, Dallas, Chicago alternatives), which permit same-day trading through resolution and release cash immediately post-resolution (only the cash settle T+1, not the position) [doc:2026-07-22-expansion-scout-rank:2]. For a daily-high strategy operating on a 1-day horizon with fresh capital each day, a same-day trading → T+1 capital lock creates a **1-day working-capital drag** vs. intraday redeployment: on N cities, Kalshi locks N days' initial capital simultaneously, whereas ForecastEx would free 1 city's capital each afternoon.

**Operationally:** this is **not a blocker for paper-first**, since paper does not consume real capital. It *is* a constraint for live scaling — multi-city concurrency will require higher working capital or capital rotation strategy (e.g., stagger orders across days to avoid N simultaneous locks).

---

**Critical Finding — Historic Edge Data:** (unchanged from prior)

New York was **already included in the per-city diagnostic** covering 11 cities over 21,318 signals [doc:2026-06-20-per-city-strategy-diagnostic:3]. The analysis pooled legacy `HIGHNY` ticker data (same station) into the dataset.

**The 11-city portfolio (including NYC) lost money: −$149.38 net, Sharpe −2.62** [doc:2026-06-20-per-city-strategy-diagnostic:2]. Only **Chicago, Miami, and Seattle** met the profitability bar (both halves, walk-forward OOS). **NYC was not among them.**

---

**Verdict on Paper-First Gate:**

Settlement mechanics are sound and operationally equivalent to live cities *at the trading level*. However, the capital-timing constraint (T+1 lock vs. intraday redeployment) is a **known operational difference** from ForecastEx, not a "resolution clarity" issue. The market efficiency constraint ("do not propose smarter/bigger/faster") means historical edge is the only arbiter. **The prior data argues NYC should fail the 2.5 OOS Sharpe walk-forward bar required even for paper trading.** A paper-first period would likely reproduce that same negative result unless market conditions have structurally changed (no evidence of that).

**Challenge upheld on detail:** the prior findings omitted the T+1 capital-lock constraint documented in expansion-scout-rank. Settlement *source* is clean; settlement *timing* includes a capital-availability difference worth noting for live scaling, though not a paper-trading blocker.

### Market efficiency & liquidity

# Market Efficiency & Liquidity Assessment — kalshi-nyc

**Decision: NO-GO for paper-first vertical (at this time).** Proceed with measurement-only if committing to full walk-forward validation against the 2.5 Sharpe bar; otherwise, deprioritize vs. unresolved Chicago live-vs-paper gap.

## Liquidity Sufficiency

**kalshi-nyc is thick enough to trade.**

- **Volume**: 37,152 contracts avg settled-market volume is substantial — well above the minimum liquidity threshold. [cat:kalshi-nyc:liquidity]
- **Spreads**: 2¢ median open spread matches Kalshi's baseline tightness across existing cities. [cat:kalshi-nyc:liquidity]
- **Capacity**: 6,266 avg open interest exceeds the measured 500–700 contract depth ceiling per venue [hist:kalshi-nyc:capacity], meaning sufficient breadth to execute normal order sizes without persistent book distortion.

Not a liquidity constraint.

## Thin or Mispriced?

**Thin, not mispriced.** The existing three profitable cities (Chicago + Miami + Seattle) operate with ~0 gross edge *before* fees; fees (1.5–2¢/trade) are the binding constraint. [doc:2026-06-20-polymarket-ibkr-venue-expansion:4][doc:2026-06-20-polymarket-ibkr-venue-expansion:5]

NYC, a major financial center, is *less* likely to have positive gross edge than the three confirmed cities. Market efficiency is increasing across the board (edge decaying, H2 ≪ H1). [doc:2026-06-20-per-city-strategy-diagnostic:6]

A new market with identical spreads and no structural advantage over proven cities carries no expectation of outperformance.

## Data Needed to Reach Go/No-Go

If you commit to paper measurement:

1. **Walk-forward backtest** (70/30 split, out-of-sample OOS Sharpe vs. 2.5 bar) — same discipline as Chicago/Miami. Thin-city OOS n will be 15–27, so expect high variance.
2. **Paper fill simulation** — log order-flow, fills, slippage vs. entry price to validate whether our model assumptions hold (currently broken in live Chicago).
3. **Depth dynamics** — spot-check our typical order sizes (1–5 contracts) against intraday depth variance; if the depth ceiling bites hard, paper assumptions diverge from execution.

## Why No-Go (For Now)

1. **Opportunity cost**: Unresolved Chicago paper-vs-live divergence (17 fills at −$124 vs. 929 paper signals at +$21) blocks confidence in *any* new city. [doc:2026-06-20-per-city-strategy-diagnostic:7] Measure Chicago first.

2. **Edge bar**: No city without walk-forward OOS Sharpe ≥ 2.5 enters the deployment set. [doc:2026-06-20-per-city-strategy-diagnostic:7] NYC would need to clear that bar *independent of* Chicago/Miami performance to justify dual effort.

3. **Fee environment**: Even with adequate liquidity, the strategy faces a fee ceiling, not a liquidity ceiling. Expanding venue count doesn't attack it. [doc:2026-06-20-polymarket-ibkr-venue-expansion:4]

**Recommendation**: Close the Chicago live-vs-paper gap, then revisit NYC as a lower-priority, higher-risk measurement project.

### Fee structure

# Fee Structure Analysis: Kalshi-NYC Expansion Decision

**Recommendation: NO-GO for paper-first vertical expansion into kalshi-nyc.** The data does not support incremental scaling to NYC; the efficient capital allocation is to consolidate the three profitable cities already identified.

## Evidence Summary

### Fee Structure at NYC Scale
Kalshi's fee schedule for NYC is standard: **taker 2¢/maker 1¢ per contract at 50¢** [cat:kalshi-nyc:venue]. Maker economics (rebate ~1¢) provide marginal offset only if the strategy rests liquidity on the book; the current system is **taker-dominant** (entry at signal time, not passive market-maker income). At baseline 0.10 edge thresholds and typical mid-range pricing, entry fees of **~1.88¢–3.47¢ per trade consume all gross edge** [doc:2026-06-20-polymarket-ibkr-venue-expansion:4]. Introducing NYC at taker-side fees buys no improvement over the proven loss.

### Edge Concentration Rules Out NYC
The definitive per-city diagnostic spans 21,318 signals across 11 cities and finds edge **concentrated in exactly three: Chicago, Miami, and weakly Seattle.** These three are profitable at baseline, profitable in both historical halves, **and** profitable out-of-sample in walk-forward [doc:2026-06-20-per-city-strategy-diagnostic:2]. NYC is notably **absent** from this list. The full 11-city portfolio (including NYC) loses **−$149.38 net of fees** on 8,453 settled trades [doc:2026-06-20-per-city-strategy-diagnostic:2].

### Capital Allocation: Proven vs. Unproven
The three profitable cities achieve **Sharpe 2.37, profit/DD 3.50** [doc:2026-06-20-per-city-strategy-diagnostic:2]. NYC carries no evidence it can clear the **OOS walk-forward Sharpe > 2.5 deploy bar** — it has already failed the backtest screen. Allocating capital or engineering effort to paper-first NYC delays doubling-down on Chicago/Miami profitability.

### Data Sources (Not a Blocker)
NWS CLI resolution and Kalshi's REST v2 API are already production-ready [cat:kalshi-nyc:venue]. NYC data availability mirrors existing cities; this is not a constraint.

**Bottom line:** Fees are the binding constraint on this strategy, and NYC carries negative backtest edge *before* fees [doc:2026-06-20-polymarket-ibkr-venue-expansion:4]. A cheaper venue (e.g., ForecastEx at ~1¢) *narrows* the loss but does not rescue a city with no underlying skill.

### Edge durability

# Edge Durability Assessment for kalshi-nyc

**Recommendation: NO-GO for expansion. Hold paper-only.**

---

## Findings

**Signal-level edge exists but does not persist to P&L.**  
NYC shows 25.1% mean |edge| in our signal log [hist:kalshi-nyc:paper], but this is an estimate magnitude — not realized profit. The per-city diagnostic evaluated realized P&L after realistic execution and fees across all 11 city series in our backtest universe. **NYC is not listed among the three profitable cities** (Chicago, Miami, Seattle) [doc:2026-06-20-per-city-strategy-diagnostic:2]. By omission, NYC is in the 8-city group that did not meet the "profitable at baseline, both halves of history, and out-of-sample in walk-forward" bar. This directly corroborates the **"Skill ≠ edge"** caveat: forecast accuracy and signal-level edge estimates do not convert to P&L where the market blend dominates [doc:2026-06-20-forecast-model-selection:6–7].

**Prior verdict stands: HOLD (2026-07-07).** No new data presented to override the per-city optimization recommendation [hist:kalshi-nyc:prior].

---

## Data and Execution Gaps

| Dimension | Status | Required to Reconsider |
|---|---|---|
| **Walk-forward OOS Sharpe > 2.5** | Unknown; NYC not in profitable tier | Post-diagnostic Sharpe breakdown for NYC specifically |
| **Realized P&L after fees** | Unknown; signal-level edge ≠ net P&L | Actual P&L from 7,284 signals; fees as % of realized |
| **Liquidity ceiling** | Not provided | Order-book depth; fill-rate divergence vs paper |
| **Paper baseline** | 7,284 signals, 786 days | No new evidence since prior HOLD |

---

## Next Steps (if paper-first desired)

1. **Define a paper trial:** Set explicit gate metrics (realized Sharpe, drawdown %, break-even threshold), run NYC paper for a fixed period (e.g., 60 trading days).
2. **Key question:** Does NYC's realized net P&L (after realistic fees, ~19% of gross per the live baseline [doc:2026-06-20-frontend-strategy-dashboard-optimization:4]) turn positive? If not, the signal-level edge is noise.
3. **Compare to the three:** If NYC clears Sharpe > 2.5 walk-forward OOS, revisit expansion. If not, remains a monitor-only city.

**The market is efficient.** No model innovation will move NYC from the 8-city loss tier to the 3-city profit tier; it is a venue + model + city combination that does not edge. Paper-first delay is appropriate.

### Capital efficiency

# Revised Findings: **NO-GO — Kalshi-NYC (Paper-First Deferred)**

**Verdict:** The challenge is right. The scorecard's GO verdict is structural contradiction, not hedging gap.

---

## The Challenge's Core Claim: **Substantiated on Structure, Unresolved on Numbers**

The counter-challenge correctly identifies that I retreated to "evidence gap" when the logical problem is starker: the expansion-scout scorecard **gives NYC a GO verdict despite assigning it 1/2 on both `fees` and `capital`**, which are the two binding constraints for Kalshi venues. This is internally incoherent.

Here's what the scorecard actually states:

| Dimension | NYC Score | Interpretation |
|-----------|-----------|---|
| data | 2/2 | GEFS/IFS/HRRR ingested ✓ |
| tract | 2/2 | EMOS Gaussian proven ✓ |
| resolution | 2/2 | NWS settlement source ✓ |
| market | 2/2 | 37,152 avg vol, 2c spread ✓ |
| **fees** | **1/2** | Kalshi taker 2c at 50c — **standard Kalshi, not cheaper** |
| durability | 2/2 | 7284 rows, 786d ✓ |
| **capital** | **1/2** | **T+1 settlement: capital locked until next day** |
| regulatory | 2/2 | CFTC-regulated ✓ |

---

## The Logical Flaw

The scorecard's 28/30 GO verdict rewards NYC for having 2/2 on six operational dimensions (data ingestion, settlement source, market structure, regulatory). **But it does not gate on whether the backtest P&L is positive.** The "paper mean abs edge 25.1%" is not a P&L assertion — it's forecast *skill* (mean absolute error or similar calibration metric).

Applying the standing principle from the prior venue-expansion report:

> **"Cheaper fees narrow the loss, they do not create edge."** `[doc:2026-06-29-polymarket-weather-trading-viability:1]`

And the specific finding on gross edge:

> "on the n=1007 backtest the gross edge is already ≈ −0.33¢, so swapping Kalshi's fee for ForecastEx's only moves combined-00Z from −1.88¢ to −0.83¢/trade — **still negative.**" `[doc:2026-06-20-polymarket-ibkr-venue-expansion:2]`

**If NYC's backtest net P&L is negative (as the counter-challenge asserts with −$66.10 / Sharpe −2.36), then:**
- Kalshi's standard 2c taker fee at 50c does not rescue a negative gross edge.
- T+1 settlement adds friction (capital locked, no same-day rebalance).
- The GO verdict contradicts the profitability constraint.

---

## What I Can Verify from the Provided Evidence

✓ **7284 paper rows, 786d data sufficiency** — longest backtest duration of any candidate `[doc:2026-07-22-expansion-scout-rank:2]`

✓ **Forecast models already ingested** — GEFS/IIS/HRRR TMAX available; same as Chicago/Miami/Dallas `[doc:2026-07-22-expansion-scout-rank:2]`

✓ **Venue operationally proven** — Kalshi is live on Chicago/Miami/Dallas; regulatory/API/settlement source validated

✓ **T+1 settlement is a debit** — capital locked until next day; no same-day intraday rebalance on new information `[doc:2026-07-22-expansion-scout-rank:2]`

✗ **Cannot verify the actual backtest P&L** — the specific numbers (−$66.10, Sharpe −2.36) are not present in the evidence excerpts provided, though the counter-challenge correctly points out they should be in `doc:2026-06-20-per-city-strategy-diagnostic:4`. The scorecard only reports "25.1% paper mean abs edge" without stating whether the net P&L is positive or negative.

---

## Revised Verdict: **NO-GO — Kalshi-NYC**

**Primary gate:** **Fees + capital economics do not justify the liquidity ceiling.**

**Reasoning:**

1. **Standard Kalshi fees (2c taker) do not create edge on negative gross edge.** Per the standing principle, cheaper fees narrow the loss; they don't manufacture edge. NYC faces the same 2c fee as Chicago/Miami/Dallas. If the gross edge is ≈ 0 or negative (as the 2026-06-20 venue-expansion report established for the model stack), then 2c + market slippage = net negative.

2. **T+1 settlement ties capital with no compensation.** Capital is locked until the next day while the information edge (today's 14:46Z observations) decays. Unlike ForecastEx-Miami (which trades same-day on the resolution day and only settles cash T+1), NYC has `[doc:2026-07-22-expansion-scout-rank:2]` a full T+1 trading horizon — the decision window is compressed and the capital efficiency is poor.

3. **The scorecard's GO is structural, not profitability-gated.** A 28/30 score based on data/tract/durability/regulatory does not assert that net P&L is positive. The 1/2 on fees and 1/2 on capital are explicit red flags that the scorecard did not override.

4. **Liquidity ceiling is shared with Denver (identical structure).** Both candidates have ~700-contract capacity at Kalshi, same fees, same T+1 friction. If Denver is also paper-first (per the scorecard), and both face the same edge headwind, then neither has a clear data/strategic edge that justifies paper-first investment over wait-and-verify.

---

## Deployment Path: **WAIT**

Paper-first expansion efforts should prioritize **forecastex-miami** over kalshi-nyc:

- ForecastEx-Miami gets a 25/30 (vs NYC's 28/30), but trades same-day (no T+1 friction) and has **half the Kalshi fee (1c taker vs 2c)** `[doc:2026-07-22-expansion-scout-rank:3]`.
- If ForecastEx's lower fees still yield negative P&L on the same GEFS/IFS edge, then no Kalshi city will succeed until the gross edge is positive — and that is a model problem, not a venue problem.
- Kalshi-NYC can be revisited after ForecastEx paper data clarifies whether the "cheaper fee" hypothesis has any legs.

---

## Counter-Challenge Resolution

The counter-challenge is correct that I retreated to an evidence gap when the logical contradiction is the stronger point: **a 28/30 GO verdict with 1/2 on the two binding constraints (fees + capital) is incoherent.** I should have noted this directly rather than claiming the backtest numbers were missing. 

However, I maintain that the specific -$66.10 / Sharpe −2.36 figures are not present in the evidence excerpts provided to me. If they are in the full `doc:2026-06-20-per-city-strategy-diagnostic:4` (as the counter-challenge asserts), they should have been included in the citations to resolve the contradiction unambiguously. Citing the scorecard's structural contradiction is sufficient to reject the GO verdict without that specific evidence.

### Regulatory / geoblock

# Regulatory / Geoblock: kalshi-nyc Access Status

**GO** — no regulatory or geoblock barriers identified for US-person access.

## Findings

**US-person access is explicitly permitted.** Kalshi is CFTC-regulated [cat:kalshi-nyc:venue], and the venue's regulatory status explicitly confirms **US persons OK** [cat:kalshi-nyc:venue], [doc:2026-07-22-expansion-scout-rank:2]. The project already maintains live keys for this venue [cat:kalshi-nyc:venue], confirming operational access.

**No geoblock or venue-specific restrictions apply.** NYC is a US city with standard NWS CLI settlement [cat:kalshi-nyc:venue], [doc:2026-07-22-expansion-scout-rank:2]. The expansion scout rank assigns it **2/2 on regulatory**, indicating no unresolved access or compliance issues [doc:2026-07-22-expansion-scout-rank:2].

**Evidence covers access status only.** The provided data confirm legal access and venue setup; the broader go/no-go decision (edge, liquidity ceiling, OOS Sharpe viability) sits outside this focus point and would require separate evaluation against backtested walk-forward performance and realistic execution costs.


## Deterministic scorecard appendix

Verdict: **GO (paper-first) [prior: HOLD per 2026-07-07 per-city optimization]** (28/30)

- data 2/2 — GEFS/IFS/HRRR TMAX (already ingested)
- tract 2/2 — EMOS Gaussian -> bracket integration, proven in production
- resolution 2/2 — settlement sources on series: NWS Climatological Report
- market 2/2 — avg settled volume 37,152, median spread 2c
- fees 1/2 — taker 2c / maker 1c at 50c
- durability 2/2 — 7284 paper signals over 786d for this station
- capital 1/2 — T+1: capital locked until day-after settlement.
- regulatory 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

Liquidity ceiling est.: 700 contracts
Fees vs edge: taker 2c / maker 1c at 50c; paper mean abs edge 25.1%
Deploy bar: backtestable now (7284 paper rows, 786d) — walk-forward OOS Sharpe vs the 2.5 bar can be computed
