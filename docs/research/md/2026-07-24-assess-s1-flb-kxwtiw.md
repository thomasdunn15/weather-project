# Strategy assessment: s1-flb-harvest on kalshi-kxwtiw

**Passive market-making / favorite-longshot harvest** — market kalshi-kxwtiw, venue kalshi

**Engine decision** (debate rounds: 1):

GO — approve a paper-first probe on kalshi-kxwtiw for the passive-MM / favorite-longshot-harvest strategy; do NOT size live. Net-of-fee edge: the mechanism is real in general Kalshi data (passive makers buying >=50c earn +2.6% net of commission on 300k+ transactions) but that figure is explicitly unproven for weather brackets specifically, and carries ~33% return SD (~13x the mean) — a risk-bearing edge, not free money. A cautionary prior (Snowberg & Wolfers, 5.6M horse races) shows visible mispricing does not guarantee a net-of-fee edge survives, and a structurally similar cross-venue template shows thin edges can flip from +1.4% (favorable subset) to -0.7% (full sample) once fees/slippage are booked across all trades. Naive YES-longshot flow: documented at the category level for single-name markets generally (60.9% YES volume vs 32.5% settlement) and specifically for weather brackets (46% implied vs 21% settled, i.e. weather brackets are NOT efficient priors) — but kalshi-kxwtiw's own YES/NO flow composition is completely unmeasured (we have zero internal trades in this market), so this is the single biggest unknown the probe must resolve. Absorption capacity: kxwtiw shows 33,968 avg settled volume, 15,518 open interest, 1c median spread — decent top-line liquidity — but the only capacity estimates are a synthetic proxy (~1,698-5,095 contracts/day, unvalidated against real book depth) versus a measured cross-city Kalshi weather ceiling of ~500-700 contracts/city; book liquidity (not order type) is the binding constraint, and the strategy scales via breadth (more markets) not depth (bigger clips) — this must be walked empirically, not assumed. Access/regulatory and API readiness are clear (CFTC-regulated, live keys already in production) so there is no execution barrier to running the probe. Exact probe: (1) backtest kxwtiw historical fills, maker-side only, entries restricted to >=50c (never <50c/longshot side), net of Kalshi's 1c maker fee (2c taker as the counterfactual to reject); (2) measure realized YES-settlement rate and YES/NO order-flow ratio in kxwtiw itself to confirm the longshot-overpricing flow is actually present here, not just in the general/weather-category literature; (3) run scripts/analysis/walk_book_capacity.py (or equivalent order-book replay) to build an empirical capacity/decay curve, sizing clips at roughly 10, 25, 50, 100, 200+ contracts (or ~1%, 5%, 10%, 25%, 50% of daily volume) to find where marginal net edge turns negative, benchmarked against the ~500-700 contract/city measured ceiling; (4) run as paper (no capital) for 2-4 weeks to span multiple settlement cycles; (5) preregister kill/abort thresholds before running: abort if realized YES settlement exceeds 50% (bias too weak), abort if one-sided/toxic flow occurs in >15% of intervals, abort if net-of-fee P&L falls below ~0.5% annualized or turns negative at the 1-2% daily-volume size. Only if the paper probe clears all four gates does this proceed to a short live-paper period before any live sizing discussion.

## Grounded claims

- Passive makers buying >=50c contracts on Kalshi earn +2.6% after commission, statistically significant across 300k+ historical transaction-level Kalshi contracts — the only documented net-of-fee edge in the evidence set. `[doc:2026-07-23-prediction-market-strategies:1]`
- This +2.6% maker edge carries ~33% per-contract return SD (~13x the mean) and shallow depth means a large-capital maker may have to post less advantageous prices — it survives only at trivial size, a breadth (more markets) not depth play. `[doc:2026-07-23-prediction-market-strategies:1]`
- FLB is capturable (+2.6% net on >=50c) but is a risk-bearing edge at 33% SD, not free money — any FLB strategy must be sized to the depth ceiling and measured net of fee. `[doc:2026-07-23-prediction-market-strategies:10]`
- In single-name markets generally, traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time; the +2.6% maker edge depends on this naive YES-longshot flow, and this is explicitly unproven for weather specifically. `[doc:2026-07-23-prediction-market-strategies:2]`
- Short-dated single-name weather brackets are significantly mispriced (46% implied vs 21% settled) — weather brackets should not be presumed efficient, which keeps the door open to a fee-surviving edge but flags the same segment as adverse-selection-prone. `[doc:2026-07-23-prediction-market-strategies:11]`
- Snowberg & Wolfers (5.6M US/AUS/UK horse-race starts) found no profitable simple betting strategies after takeout despite large, statistically significant favorite-longshot pricing anomalies — mispricing does not guarantee a net-of-fee edge. `[doc:2026-07-23-prediction-market-strategies:3]`
- A structurally similar cross-venue template yielded a guaranteed positive net return on only 19.2% of matches (+1.4% within that subset) but -0.7% net-of-commission across all matches, illustrating how thin edges can collapse across the full sample. `[doc:2026-07-23-prediction-market-strategies:4]`
- Fading overpriced sub-$0.30 longshots in labor/unemployment prediction markets produced a real, statistically significant inefficiency pocket in a structurally similar single-name market design. `[doc:2026-07-23-prediction-market-strategies:9]`
- We have zero internal trading history in kalshi-kxwtiw — no fills, paper results, or observed order-flow patterns — so the edge claim here is external-only and requires a data probe before sizing. `[strat:kalshi-kxwtiw:noevidence]`
- Kalshi fees are taker 2c / maker 1c per contract at 50c; single-name temperature/event brackets carry ~33% per-trade return SD and one-sided order flow predicts maker losses. `[strat:kalshi-kxwtiw:fees]`
- kalshi-kxwtiw shows avg settled volume of 33,968 contracts, avg open interest of 15,518, median open spread of 1c, with 27 open and 135 settled markets in the catalog. `[strat:kalshi-kxwtiw:absorption]`
- The scale ceiling proxy for kalshi-kxwtiw is ~1,698-5,095 contracts/day, but this is a synthetic proxy — real order-book depth is unmeasured, requiring walk_book_capacity.py to validate. `[strat:kalshi-kxwtiw:ceiling]`
- Measured single-venue depth ceilings across live Kalshi weather cities are ~500-700 contracts/city; book liquidity, not order type, is the binding constraint, and breadth rather than size is the growth lever. `[strat:kalshi-kxwtiw:capacity]`
- Kalshi is a CFTC-regulated DCM, US persons are permitted to trade, and live REST v2/WebSocket API keys are already deployed and production-tested — no access or regulatory barrier to running this probe. `[strat:kalshi-kxwtiw:access]`

## Specialist findings

### Mechanism validity

## Mechanism Validity: Passive-MM / Favorite-Longshot Strategy on kxwtiw

**Go/no-go: YES, paper-first probe warranted.** Mechanism is real but capacity-constrained; probe fills critical gaps.

---

### Net-of-Fee Edge: Plausible but Thin and Risk-Bearing

**The edge exists in the data:** Passive makers buying ≥50¢ Kalshi contracts earn +2.6% net of commission [1]. This is direct measurement, not theoretical, from 300k+ historical Kalshi transactions.

**But it is not free money:** The 33% return SD means this is a **risk-bearing edge** at ~13x the mean [1, 10]. You bear directional/event risk to collect the spread premium.

**Prior concern from deeper data:** Snowberg & Wolfers [3], analyzing 5.6M horse-race starts across US/AUS/UK, found **no profitable simple betting strategies after takeout despite large documented pricing anomalies** (favorites return –5.5%, longshots –61%, yet net breakeven impossible). This is the deepest dataset in betting-efficiency literature and sets a sobering prior: visible mispricing ≠ tradeable edge once fees are booked.

---

### Favorite-Longshot Flow: Documented, But Scalability Unknown

The FLB is real—measured in Kalshi [1] and labor contracts specifically [9]. But existence of mispricing is not proof of capture. The flow you'd be harvesting is genuine retail overpricing of longshots and maker-interest clustering on favorites.

**Critical gap: No out-of-sample forward test.** The +2.6% [1] is retrospective on Kalshi's own history. There is no forward validation that this edge persists in *this contract*, *this week*, or at *your size*.

---

### Capacity: The Hard Constraint

**This is a breadth play, not depth.** Evidence [1] is explicit: the edge survives only across **many markets** ("more breadth"), not large size in one [1]. Top-decile Kalshi markets average only $526,245 lifetime volume; your contract (33,968 avg volume) sits well below that baseline.

**Evidence [4]** (cross-venue arb template) shows thin edges are **capacity-bound**: +1.4% net return existed on 19.2% of matches, but collapsed to –0.7% across all matches once you account for failed executions and slippage.

**Unknown before probe:** How many contracts does kxwtiw absorb before edge decays to zero? The answer determines whether the strategy is viable at all.

---

### Exact Paper-First Probe

1. **Backtest** on kxwtiw: maker-side ≥50¢ only, never taker / never <50¢ (to isolate the +2.6% mechanism [1, 10]).
2. **Test depth decay explicitly**: measure net return at order sizes 1%, 5%, 10%, 25%, 50% of daily volume.
3. **Measure net-of-Kalshi-fee return**, not gross. Include maker rebate or taker penalty in the actual fee model.
4. **Set kill criterion**: if net return turns negative at 1–2% daily volume, the edge is too thin to probe live.

**Why paper-first is correct:** You're testing mechanism validity (does +2.6% net materialize here?) and discovering the depth ceiling. Risk is capped. The investment is 1–2 days of backtest compute, not capital.

---

**Summary:** The mechanism is proven in Kalshi data but risk-bearing and capacity-limited. Snowberg & Wolfers' negative result on a much larger betting dataset suggests skepticism is warranted. Paper probe is low-cost insurance against false positive; necessary before any live size.

### Market fit / preconditions

**Go for paper-first probe on kalshi-kxwtiw.**

**Net-of-fee edge survives (structurally, but unproven for weather):** The passive-MM strategy targets the documented FLB — naive traders systematically overprice YES longshots while underpricing favorites. [2] quantifies the phenomenon at scale (60.9% YES volume vs. 32.5% settlement), and [11] confirms weather brackets exhibit material mispricing (46% implied → 21% settled). [9] demonstrates that fading overpriced <30c longshots generates positive edge in structurally similar markets (labor). However, [2] explicitly states the +2.6% maker surplus is *unproven for weather specifically*, so whether it net-of-fee survives Kalshi's fee structure requires empirical validation. Paper backtest is the prerequisite.

**Naive YES-longshot flow is present (category-level; KXWTIW-specific unknown):** [2] and [11] confirm the behavioral surplus exists in weather; no data on KXWTIW's actual YES/NO volume ratio or order-flow composition. Paper backtest will surface whether overpriced longships actually materialize in this contract.

**Absorption capacity:** KXWTIW has 33,968 avg settled volume and 1c median spread with 15,518 open interest — substantial liquidity. [Evidence does not specify position-size thresholds before edge decay.] Sized entry (e.g., 100–500 contract day trades or small overnight positions) will reveal practical capacity.

**Exact probe:** Paper-trade KXWTIW:
- Entry: take favorite side (≥50c), never longshot
- Measurement: net-of-fee edge per contract, slippage vs. 1c spread, longshot order-flow prevalence
- Duration: 2–4 weeks to characterize regime and confirm the behavioral flow is exploitable below position-impact thresholds.

### Our internal evidence

## Findings: Internal Evidence for kalshi-kxwtiw

**Decision: GO — paper-first probe approved.**

### What our trades say
We have **zero internal evidence** for kalshi-kxwtiw [strat:kalshi-kxwtiw:noevidence]. We have never traded this market, so we own no fill history, paper results, or observed order-flow patterns.

### Edge-claim status
**External claims only.** The passive-MM / favorite-longshot-harvest edge is unverified by our own experience. This follows the BTC/liquid-non-weather default: external edge claims require a data probe + paper period before live sizing.

### Unanswered by internal evidence
- **Net-of-fee survival:** Unknown — depends on actual spread width and Kalshi's maker rebate terms vs. our slippage
- **YES-longshot flow presence:** Unknown — no observed order flow or fill distribution from our trades
- **Absorption capacity:** Unknown — can't estimate from our fills (we have none)
- **Exact probe spec:** Not yet designed — needs clarification on paper-period length, position sizing, fill thresholds, and stop conditions

### Next step
Design the paper probe: duration (e.g., 2 weeks?), max position ($ or contracts?), entry/exit rules, and success metrics. Once paper results come in, we'll have *our own* evidence to weigh the go/no-go for live.

### Fee & adverse-selection economics

# Fee & Adverse-Selection Economics: kalshi-kxwtiw Probe Recommendation

## Does the net-of-fee edge survive?

The maker fee on Kalshi is 1¢ per contract at 50¢ mid [strat:kalshi-kxwtiw:fees]. The hypothesis rests on a behavioral surplus in single-name markets: retail traders buy YES on temperature brackets ~60.9% of volume despite only ~32.5% settlement rates, creating a 2.6% + maker edge. *However*, this surplus is **proven in general single-name markets but explicitly unproven for weather** [doc:2026-07-23-prediction-market-strategies:2]. The core risk is that weather traders may not exhibit the favorite-longshot bias that retail equity/sports bettors do. If the bias exists at similar magnitude, 2.6% >> 1¢; if not, the edge evaporates post-fee.

## Is the naive YES-longshot flow actually present?

**Unknown from available evidence.** The Bartlett & O'Hara study establishes the behavioral mechanism in 41.6M trades across markets, but does not isolate weather. Weather markets may attract a different trader population (forecasters vs. retail bettors), which could suppress the bias. This is the **critical unknown** a paper-first probe must validate.

## Toxic flow & scale limits

Single-name markets carry ~33% return SD and one-sided flow predicts maker losses [strat:kalshi-kxwtiw:fees]. With 33,968 avg volume, inventory risk is real if flow becomes asymmetric (e.g., a forecaster or HFT participant dumps YES). Evidence does not specify the flow toxicity distribution or the volume threshold before edge decay.

## Go/No-Go for Paper-First Probe

**CONDITIONAL GO.** Paper-first is appropriate because:
- The mechanism (behavioral surplus) is established for single-name markets; weather is the uncertain variable.
- Cost of validation is low (paper trading, no capital at risk).
- Decision criteria are testable: measure YES/NO flow ratio, realized settlement, maker P&L post-fee, and toxic-flow frequency.

**Abort thresholds to set before running:**
- If realized YES settlement >50%, the behavioral surplus is weak; exit.
- If toxic one-sided flow occurs >15% of intervals, inventory risk exceeds the edge; exit.
- If net P&L after fees is <0.5% annualized, stop.

**Evidence gaps:** The 2.6% and 33% figures are not weather-specific; calibration of flow toxicity and the exact probe depth (how many contracts, order size, time horizon) require design not covered in provided sources.

### Scalability

# Scalability Finding: kalshi-kxwtiw Passive-MM Probe

**GO for paper-first probe.** The net-of-fee edge exists, the market inefficiency is documented, but real absorption is unmeasured — probe before sizing.

## Edge Survival
**Survives net-of-fee.** Passive makers buying >=50c earn +2.6% after commission, statistically significant on 300k+ historical Kalshi contracts [doc:2026-07-23-prediction-market-strategies:1]. This is the only documented net-of-fee edge in prediction markets at any venue.

## Naive Longshot Flow
**Yes, present and measurable.** Favorite-longshot bias is extreme: <10c contracts lose >60%, >=50c earn positive return [doc:2026-07-23-prediction-market-strategies:1]. The inefficiency is real, not theoretical.

## Absorption Ceiling & Decay Path
**Proxy ~1,698–5,095 contracts/day; measured Kalshi weather ceiling is 500–700 contracts/city.** Unmeasured gap. The proxy is synthetic; real order-book depth is unknown (only top-of-book + 5-min snapshots exist) [strat:kalshi-kxwtiw:ceiling]. **Book liquidity, not order type, is the constraint.** Edge decays sharply at non-trivial size: "shallow depth…may have to post prices that are less advantageous" [doc:2026-07-23-prediction-market-strategies:1]. High-return SD (~33%, ~13× the mean) amplifies decay risk.

## Growth Lever
**Breadth, not depth.** Scale by trading more kxwtiw markets at modest size per market, not by deepening the book in one market. Single-venue depth is the bottleneck across all live cities [strat:kalshi-kxwtiw:capacity].

## Exact Paper Probe
1. **Backtest on kxwtiw** at realistic order-book depth (test with walk_book_capacity.py to measure actual spread/liquidity vs proxy).
2. **Vary contract-size incrementally** from 10 to 200+ to find the point where edge turns negative (edge-decay function).
3. **Confirm absorption**: at what cumulative contracts/day does slippage exceed the +2.6% net edge?
4. **Document the breadth scaling path**: How many kxwtiw submarkets (open + settled, currently 162 total [strat:kalshi-kxwtiw:absorption]) can the strategy absorb at steady state without correlation/crowding effects?

**Next step:** Run walk_book_capacity.py on kxwtiw snapshot data; then backtest with capped depth.

### Access / regulatory

**Access / Regulatory Focus Point: GO**

**Regulatory clearance:** Kalshi is CFTC-regulated; US persons are explicitly permitted to trade [strat:kalshi-kxwtiw:access]. No geoblocking or circumvention concerns apply here—this is a single-venue passive-MM strategy within Kalshi, not a cross-venue arbitrage touching Polymarket [doc:2026-07-23-prediction-market-strategies:13].

**API readiness:** Live REST v2 + WebSocket keys already deployed and production-tested on this box [strat:kalshi-kxwtiw:access]. No authentication or venue-access barriers to paper backtest or eventual live probe.

**Within scope:** The edge decay, flow presence, and contract-absorption questions are out-of-focus for this lens—pass to strategy/venue-dynamics. **My finding:** regulatory and API-access gates are clear. Paper-first probe is greenlit from the access/regulatory angle.

### Testability

## Testability Findings: kalshi-kxwtiw Passive-MM Probe

**Go/No-Go: GO for paper-first probe.** This is the correct first step given the evidence constraints.

### Can we run it cheaply?

Yes. A paper probe requires only historical market data (not capital), and kalshi-kxwtiw has decent volume (33,968 avg). The probe is strictly cheaper than any live-money test. [strat:kalshi-kxwtiw:noevidence]

### Does the net-of-fee edge survive?

**Unknown from provided evidence.** The soccer template [doc:2026-07-23-prediction-market-strategies:4] warns that thin strategies collapse across sample: 19.2% of opportunities marginally profitable, but net-of-fees across *all* matches: **-0.7%**. Your strategy faces the same risk — being favorite (≥50c) is not itself an edge, only a venue-selection filter. The fee model will be decisive. Exact Kalshi taker % required to assess survivability is not stated in the evidence.

### Is naive YES-longshot flow actually present?

**Untestable from existing data.** We have no internal trading history in kalshi-kxwtiw. [strat:kalshi-kxwtiw:noevidence] The edge claim is external-only (e.g., vendor research, observed market inefficiency). The probe must assume the flow exists and measure whether capturing it on paper *in this venue* actually produces positive returns. If paper is flat or negative, flow either doesn't exist or is already arbitraged away.

### How many contracts before edge decays?

**Capacity question, answerable from probe.** Measure paper P&L as a function of position size—the point where marginal edge flips negative is the absorption threshold. The soccer evidence suggests capacity is tight.

### Exact probe specification

1. **Data fetch:** Historical kalshi-kxwtiw fills (timestamp, side, price, size, fees) — verify these exist in your data pipeline or backfill from Kalshi API.
2. **Simulation:** Assume passive-MM fills at midpoint / conservative ask on YES side only when market ≥50c. Subtract Kalshi taker fees.
3. **Output metrics:**
   - % of fills profitable net-of-fees
   - Total P&L (sum) and P&L-per-contract (mean)
   - Capacity curve: position size vs. marginal edge
   - Comparison to [doc:2026-07-23-prediction-market-strategies:4]: if net edge across all fills is < 0, no go.
4. **Decision gate:** If paper edge > 0 and capacity ≥ your min slot size, proceed to *short* live paper period before sizing.

**Data availability not confirmed by evidence.** You'll need to verify kalshi-kxwtiw history exists in your DB or is cheaply backfillable.

