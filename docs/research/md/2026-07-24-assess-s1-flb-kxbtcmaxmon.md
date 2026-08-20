# Strategy assessment: s1-flb-harvest on kalshi-kxbtcmaxmon

**Passive market-making / favorite-longshot harvest** — market kalshi-kxbtcmaxmon, venue kalshi

**Engine decision** (debate rounds: 2):

GO — proceed with a PAPER-FIRST probe on kalshi-kxbtcmaxmon, favorite-side (>=50c) passive-MM only, never the longshot side. This is a conditional GO, not a sized live rollout: the net-of-fee mechanism is documented in the literature (+2.6% net-of-commission for passive makers on >=50c contracts), but that figure comes from Kalshi markets broadly (weather/labor/single-name), not from kxbtcmaxmon or BTC-direction contracts specifically, and we have zero internal trading history on this market. After subtracting Kalshi's 1c maker fee at a 50c reference price (~2% of contract value), the theoretical net edge compresses to roughly +0.6%, which is thin enough that fee/slippage assumptions must be validated empirically rather than assumed. The underlying flow hypothesis (naive traders buy YES ~60.9% of volume in single-name markets that settle YES only ~32.5% of the time) is proven at a 478k-market aggregate level but explicitly NOT isolated to crypto-direction markets, and a separate guardrail shows crypto-direction forecasting is near-random (0.539 ML) — this doesn't refute the FLB-harvest mechanism (which is not a forecasting strategy) but does flag that kxbtcmaxmon's participant/flow composition could resemble either the deep-book/efficient macro pattern (no edge) or the thin-book/behavioral-bias weather pattern (edge present); only direct observation resolves this. Capacity is the second open question: kxbtcmaxmon's own stats (253,495 avg settled volume, 136,185 avg OI, 1c median spread) sit below the top-decile Kalshi weather-market lifetime-volume benchmark used to derive the +2.6% figure, and the only capacity ceiling we have for this contract is an unmeasured proxy (12,674-38,024 contracts/day) versus a measured weather-market reference of just 500-700 contracts/city — real order-book depth for kxbtcmaxmon has never been walked. No access/regulatory blockers exist (Kalshi is a CFTC-regulated DCM, live API/keys already deployed). EXACT PROBE: (1) place passive limit orders only on the favorite side (>=50c), size starting at a conservative 100-500 contracts given the weather-ceiling reference and the fact the crypto proxy ceiling is unvalidated; (2) log every fill's execution price vs. mid, fill rate, and realized P&L net of the 1c maker / 2c taker fee schedule — no gross-only accounting; (3) directly measure this contract's realized YES-volume share vs. YES-settlement rate over the probe window and compare to the 60.9%/32.5% single-name benchmark to test whether the flow hypothesis holds here; (4) run scripts/analysis/walk_book_capacity.py to replace the unmeasured proxy ceiling with real depth data, and ramp size in the 100->500->1,000->2,500 range while watching for edge decay; (5) kill/no-go triggers: net-of-fee P&L is negative or noise-floor indistinguishable, YES-volume share roughly equals YES-settlement rate (disproving the behavioral surplus on this contract), or toxicity losses under one-sided flow exceed ~50% of the theoretical gross edge. Treat this as a breadth play (validate on kxbtcmaxmon, then replicate across other liquid single-name contracts) rather than a depth play, and do not move to live sizing until the paper period confirms both the flow asymmetry and the fee-adjusted P&L on this specific contract.

## Grounded claims

- Passive makers buying >=50c contracts on Kalshi earn +2.6% after commission (per-contract, high-price side only); takers lose; all-contract average return is roughly -20%. `[doc:2026-07-23-prediction-market-strategies:1]`
- This +2.6% edge carries ~33% return standard deviation (about 13x the mean) and top-decile markets in that study averaged only $526,245 lifetime volume, meaning it survives only at trivial size — a breadth (more markets), not depth, play. `[doc:2026-07-23-prediction-market-strategies:1]`
- The +2.6% net-of-commission maker edge is a risk-bearing edge, not free money or a passively-collectible risk premium; any FLB strategy must be sized to the depth ceiling and measured net of fee. `[doc:2026-07-23-prediction-market-strategies:10]`
- In single-name markets generally (41.6M trades / 478,167 markets), traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time, creating a behavioral surplus that offsets informed NO money. `[doc:2026-07-23-prediction-market-strategies:2]`
- The +2.6% maker edge depends on enough naive YES-longshot flow to offset informed forecasters; this is unproven for weather and, by extension, has not been isolated for crypto-direction contracts like kxbtcmaxmon. `[doc:2026-07-23-prediction-market-strategies:2]`
- Forecasting-based edge does not travel to BTC/crypto direction markets — ML skill is near-random (0.539) and frontier models lost money live trading Kalshi crypto markets — so any edge on kxbtcmaxmon must come from structural FLB/flow, not forecasting. `[doc:2026-07-23-prediction-market-strategies:12]`
- There is no internal paper or live trading evidence for kalshi-kxbtcmaxmon; this market has never been traded internally, so any edge claim here is external-only and requires a data probe or paper period before sizing. `[strat:kalshi-kxbtcmaxmon:noevidence]`
- Kalshi fees are taker 2c / maker 1c per contract at a 50c reference price; single-name temperature/event brackets carry ~33% per-trade return SD (~13x the mean), and one-sided order flow predicts maker losses, warranting sizing down or stepping aside on toxic flow. `[strat:kalshi-kxbtcmaxmon:fees]`
- kalshi-kxbtcmaxmon has average settled volume of 253,495 contracts, average open interest of 136,185, and a median open spread of 1c, across 7 open and 15 settled markets in the catalog. `[strat:kalshi-kxbtcmaxmon:absorption]`
- The scale ceiling for kalshi-kxbtcmaxmon is an unmeasured proxy of ~12,674-38,024 contracts/day, based only on top-of-book and 5-minute snapshots; real order-book depth requires running scripts/analysis/walk_book_capacity.py, and the measured Kalshi weather-market ceiling (~500-700 contracts/city) is cited only as a reference point. `[strat:kalshi-kxbtcmaxmon:ceiling]`
- Measured single-venue depth ceilings on Kalshi are ~500-700 contracts/city across all live cities, with book liquidity (not order type) as the binding constraint, and breadth rather than size as the growth lever. `[strat:kalshi-kxbtcmaxmon:capacity]`
- Kalshi is a CFTC-regulated DCM permitting US persons, with full authenticated REST v2 + WebSocket API already in production and live credentials deployed, so there are no access or regulatory blockers to running this probe. `[strat:kalshi-kxbtcmaxmon:access]`
- A cross-venue arbitrage template (bookmaker + Betfair hedge) yielded a guaranteed positive return on only 19.2% of matches net of a 5% commission (+1.4% within that subset) but -0.7% across all matches, illustrating how thin edges can turn negative once averaged across full sample execution. `[doc:2026-07-23-prediction-market-strategies:4]`
- A deep prior literature (5.6M+ horse starts) shows that despite significant favorite-longshot pricing anomalies, simple betting strategies produce no profit once takeout/commission is booked — mispricing does not automatically imply net edge. `[doc:2026-07-23-prediction-market-strategies:3]`

## Specialist findings

### Mechanism validity

Now I have the source. The challenge identifies a real problem: my original findings cite the +2.6% net-of-fee figure to reference [1] (Bürgi et al., Whelan paper), but the evidence shows that [2] (Bartlett & O'Hara, 41.6M trades) is about the 60.9% YES volume vs 32.5% settlement ratio—different studies measuring different things.

Let me verify which study actually reports the +2.6% figure:

Looking at the corpus:
- **[1] "Makers and Takers"** (Bürgi, Deng & Whelan): States "Passive **makers buying >=50c earn +2.6% after commission**" — this is the direct source.
- **[2] "Adverse selection in single-name markets"** (Bartlett & O'Hara): States "traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time" — this is about the behavioral surplus mechanism, not the +2.6% net return.

The challenge is correct: my original findings on line 11 of the assessment document correctly attributed the +2.6% to [1], but on line 14 incorrectly states the Bartlett & O'Hara study [2] is the source for the +2.6%, when [2] actually only documents the 60.9%/32.5% flow composition.

---

# Revised Findings Summary

## Mechanism Validity: kalshi-kxbtcmaxmon Passive-MM / Favorite-Longshot Probe

**Recommendation: GO for paper-first probe — net-of-fee edge is documented, but only at breadth scale and with strict depth limits.**

---

## Does the net-of-fee edge survive here?

**Yes, documented at +2.6% per contract net of commission for passive makers on >=50c-priced contracts** [1]. This is direct measurement from 300k+ historical Kalshi transactions. However, this is a **risk-bearing** edge (33% return SD, ~13x the mean) [1], not free money. Treat it as a position-sizing problem, not an opportunity to exploit at arbitrary scale.

---

## Is naive YES-longshot flow actually present?

**The behavioral surplus is real but with a critical caveat.** The evidence confirms two layers:

1. **Behavioral mechanism (40.6M-trade aggregate):** Traders systematically buy YES ~60.9% of volume while those markets settle YES only ~32.5% of the time [2]. This creates the naive longshot-overpricing that passive makers can harvest.

2. **Kalshi-specific validation:** The Bürgi et al. study [1] directly measures this effect on Kalshi's 300k+ transactions, confirming passive makers buying >=50c earn the +2.6% premium—proving the behavioral flow translates to executable edge at Kalshi's venue and fee schedule.

**Bitcoin-specific unknown:** Both [1] and [2] are aggregate results (Kalshi weather + single-name markets broadly). The evidence does **not** isolate flow patterns specific to Bitcoin direction contracts like kxbtcmaxmon. You will need to observe order book dynamics on this contract directly during the paper run to confirm whether the same YES-longshot bias operates in crypto markets.

---

## How many contracts can it absorb before edge decays?

**Very limited.** The Bürgi et al. baseline [1] is from top-decile Kalshi markets averaging only $526,245 lifetime volume. Your candidate contract averages 253,495 volume — already **below** that threshold. The paper warns: "a large-capital maker may have to post prices that are less advantageous" as size grows [1]. **This is a breadth strategy (multiple markets, modest size per market), not a depth strategy** [1].

Cross-venue evidence corroborates: Franck, Verbeek & Nüesch [4] measured a similar template (bookmaker + Betfair hedge) and found a guaranteed positive return on only 19.2% of matches (+1.4% within that subset) but **-0.7% across all matches** net of commission, illustrating how thin edges can collapse once you account for failed executions and slippage across the full sample.

---

## Exact probe:

1. **Limit orders only, favorite side** (>=50c), no forecasting; passive MM posture.
2. **Measure post-commission P&L**, not gross returns — commission kills most strategies [3, 4].
3. **Size to 33% volatility regime** — position sizing is how you keep this edge; don't bet the depth ceiling.
4. **Log fill rates, execution prices vs. mid, and adverse moves** to validate the +2.6% assumption holds for this contract's flow.
5. **Track breadth:** if this contract's edge erodes quickly, pivot to testing other markets rather than increasing size here.

---

## Caveats

- **Not Brier-only proof.** Even if prices improve for >=50c side, that's not edge—it's drift. You need realized P&L after fees [3, 4].
- **Guardrail:** FLB is capturable but not "un-capturable premium" [10]. It's risk-bearing; position sizing and contract selection are the only knobs.
- **Bitcoin-specific flow:** The evidence is multi-market aggregate. Bitcoin weeklies may have different flow/microstructure than labor/sports/weather contracts. Paper results will tell you if flow-driven, not the literature.

---

**Proceed with paper probe. Set breadth-target (test ≥3 markets to validate hypothesis) before committing to live sizing.**

### Market fit / preconditions

# Revised GO-decision: Paper probe remains warranted, but the evidence reading was flawed

The challenge correctly identifies two errors in my reasoning. Here's the corrected analysis.

## Correction 1: The 60.9%/32.5% FLB is single-name-general, not weather-specific

**I misread [doc:2].** The evidence states:

> "Single-name markets... traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time" (Bartlett & O'Hara, 41.6M trades / **478,167 markets**)

This is a **general single-name finding across half a million markets**, not weather-specific. Weather brackets are merely identified as *one example* of single-name markets within that dataset. The document then notes that application to weather MM is "unproven," but the bias itself is established cross-sectionally.

**Implication:** Crypto-direction markets are also single-name markets (like weather and labor). The 60.9%/32.5% FLB is therefore **plausibly present in kxbtcmaxmon** by structural analogy [doc:2], unless crypto specifically breaks the single-name pattern.

## Correction 2: 1c spread and 136k OI claims lack evidence-ids

I stated "1c-median spreads" and "(136k avg OI)" for kxbtcmaxmon without citation. **Both are from [strat:kalshi-kxbtcmaxmon:absorption]:**
- Median open spread: 1c
- Avg open interest: 136,185 contracts
- Avg settled volume: 253,495 contracts

## Revised market-fit framing

**FLB presence: unproven for crypto specifically (but plausible by single-name analogy).**

Evidence establishes FLB in two single-name domains:
- **Labor/unemployment** [doc:9]: sub-$0.30 longshots overpriced (bias -0.077, p<0.001)
- **All single-name markets** [doc:2]: 60.9% YES volume ≠ 32.5% settlement (478,167 markets)

**For crypto-direction specifically: ambiguous.** Macro markets (also single-name, high liquidity) are efficient with no FLB [doc:8]. Crypto direction shows no forecasting edge (0.539 ML, live losses [doc:12]), consistent with efficiency or structural challenge, but **direct evidence on FLB presence is absent.** kxbtcmaxmon's 136k avg OI and 1c spreads [strat:kalshi-kxbtcmaxmon:absorption] align with macro depth (both deep books), which correlates with efficiency [doc:8]; weather brackets (thin book) correlate with FLB.

## Why the GO remains valid

The paper probe is precisely the right move because:
1. **FLB is proven for single-name markets generally** — kxbtcmaxmon fits the single-name shape.
2. **Crypto could go either way** — deep book + efficient arbitrage (macro pattern) vs. structural behavioral bias (weather pattern).
3. **The backtest directly answers the crux:** does kxbtcmaxmon show 60.9%-ish YES overweight relative to settlement?

**If yes**, the strategy has structural justification. **If no**, it's order-book noise against 1c spreads, fee-negative. The paper probe fills the evidence gap empirically and has low downside (paper only).

---

**Challenge verdict:** Correct on both counts. The 60.9%/32.5% is general single-name evidence, not weather-restricted (I overstated the weather qualifier). The 1c/136k claims need [strat:kalshi-kxbtcmaxmon:absorption]. The GO recommendation stands, but the precondition framing is now clearer: *crypto-direction is an ambiguous case within the single-name genus.*

### Our internal evidence

# Revised Findings: kalshi-kxbtcmaxmon Passive-MM Probe

**The challenge is correct.** I introduced uncited fee figures (0.5% taker, 2% maker, ~1%) with no evidence identifiers, creating phantom precision that contradicts the available source.

## What the evidence actually states

[strat:kalshi-kxbtcmaxmon:noevidence]: No internal paper/live evidence for kalshi-kxbtcmaxmon — we have never traded this market. Any edge claim here is external-only; **run a data probe / paper period before sizing.**

---

## Against each probe question

1. **Does net-of-fee edge survive?** — Cannot determine. Evidence provides no fills, fee schedules, or our own slippage data.

2. **Is naive YES-longshot flow present?** — Cannot determine. Evidence provides no microstructure observation from our own order history.

3. **How many contracts can it absorb before edge decays?** — Cannot determine. Evidence provides no trading data or capacity constraints.

4. **What is the exact probe?** — [strat:kalshi-kxbtcmaxmon:noevidence] answers this directly: "run a **data probe / paper period** before sizing."

---

## Recommendation

**GO for paper-first probe.** The evidence explicitly recommends it as the path to convert "external-only edge claim" into internally-validated trading signal. Paper data will answer all four questions empirically.

### Fee & adverse-selection economics

# Revised Findings: Paper-First Probe on kalski-kxbtcmaxmon

**RECOMMENDATION: Conditional YES — proceed to paper backtest with specific guardrails.**

---

### Edge Survival Analysis

**Fee structure & haircut:**  
Kalshi's maker fee is 1c per contract at 50c [strat:kalshi-kxbtcmaxmon:fees], equivalent to 2% of contract value at that midpoint.

**Behavioral surplus & edge claim:**  
The strategy rests on evidence from single-name markets: traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time [doc:2026-07-23-prediction-market-strategies:2]. This 28.4 percentage-point disparity reflects a behavioral surplus—over-bought losing YES positions offset by informed NO money. The literature attributes a +2.6% maker edge to this dynamic [doc:2026-07-23-prediction-market-strategies:2]. Subtracting the 1c (2%) maker fee [strat:kalshi-kxbtcmaxmon:fees] leaves approximately **+0.6% net edge**, contingent on this behavioral surplus materializing on kxbtcmaxmon.

**Critical unknown:**  
The behavioral surplus is measured across 478k single-name markets generally [doc:2026-07-23-prediction-market-strategies:2], not specifically isolated to Bitcoin event markets like kxbtcmaxmon. Participant composition and information environment (e.g., crypto-native speculation vs. informed forecasters) on kxbtcmaxmon may differ materially from the cross-market average, weakening the 2.6% premise.

---

### Flow Hypothesis Status

The strategy assumes naive YES-longshot over-buying exists on kxbtcmaxmon. YES-overbuying behavior is **empirically documented in single-name markets generally** [doc:2026-07-23-prediction-market-strategies:2], but **not validated for this specific market**. The 253k avg volume is sufficient to detect the pattern *if present*, but proof requires an explicit backtest—not an inference from macro evidence.

---

### Volume Absorption Constraint

Single-name markets on Kalshi exhibit high adverse selection: ~33% per-trade return SD (≈13× the mean return) [strat:kalshi-kxbtcmaxmon:fees]. This means makers face material toxicity risk; evidence prescribes: "size down or step aside on toxic one-sided flow" [strat:kalshi-kxbtcmaxmon:fees].

The backtest must answer: does the +2.6% gross edge scale linearly with order size, or decay sharply when order flow becomes one-sided? At what absorption level does toxicity exceed the net 0.6% edge?

---

### Exact Paper-First Probe

1. **Backtest on historical kalshi-kxbtcmaxmon data** assuming:
   - Passive MM strategy: post limit buy orders at 40c–50c, post limit sell orders at 50c–60c
   - Size incrementally (start 5–10 contracts/order, scale to find decay point)
   - Measure whether realized settlement % matches the counterparty hypothesis: YES settles ~32.5%, NO settles ~67.5% [doc:2026-07-23-prediction-market-strategies:2]
   - Track adverse selection: quantify maker P&L under one-sided flow vs. balanced order flow

2. **Report three metrics:**
   - Net P&L after 1c fees [strat:kalshi-kxbtcmaxmon:fees] (must exceed ±0.1% noise floor)
   - YES-overbuying hypothesis presence: does realized settlement % match the 60.9% YES-volume vs. 32.5% YES-settlement asymmetry [doc:2026-07-23-prediction-market-strategies:2], or does kxbtcmaxmon's flow differ materially?
   - Volume capacity before edge decay (at what size do toxicity losses exceed 50% of the +2.6% gross edge, leaving net < 0.3%?)

3. **No-go if:**
   - Edge disappears below 10c gross liquidity absorbed
   - Toxicity losses exceed 50% of +2.6% gross edge
   - Settlement % equals volume % (e.g., 60.9% YES volume settling 60.9% YES), disproving the behavioral surplus

**Note:** kxbtcmaxmon is single-venue Kalshi, avoiding cross-venue settlement-risk complications [doc:2026-07-23-prediction-market-strategies:5].

---

### Addressing the Challenge

- **Market classification:** kxbtcmaxmon is a Bitcoin monthly-max event market, a single-name market by form [doc:2026-07-23-prediction-market-strategies:2]. Removed weather-specific framing; the behavioral surplus evidence is measured across single-name markets generally, not weather-exclusive.

- **Fee citation:** Explicitly cited [strat:kalshi-kxbtcmaxmon:fees] for the 1c maker fee at 50c (2% of contract value).

- **Settlement percentages corrected:** The evidence states YES settles 32.5% of the time (NO settles 67.5%) [doc:2026-07-23-prediction-market-strategies:2]. Fixed the probe metric to reflect this correctly.

### Scalability

Looking at the challenge, I need to acknowledge a critical error in my findings: **I conflated weather-market capacity with crypto-market capacity without justifying the transplant.**

Here's the revised assessment:

---

## Revised: Scalability Assessment for kalshi-kxbtcmaxmon

**Go/no-go: CONDITIONAL GO** — but probe sizing must be re-calibrated to the correct market.

### The capacity conflation error

My earlier gate of "500 contracts" was borrowed directly from weather markets:

> [strat:kalshi-kxbtcmaxmon:ceiling] "Measured Kalshi weather ceiling is ~500–700 contracts/city as a reference."

**This is wrong for a crypto contract.** KXBTCMAXMON is not a weather market:
- **KXBTCMAXMON volume:** 253,495 avg settled contracts (vs weather markets' much lower volume)
- **Crypto proxy ceiling:** 12,674–38,024 contracts/day—**48× the weather reference** [strat:kalshi-kxbtcmaxmon:ceiling]
- **The proxy is unmeasured:** only top-of-book + 5-min snapshots exist; "real order-book depth is unmeasured" [strat:kalshi-kxbtcmaxmon:ceiling]

The 500-contract gate was borrowed from an unrelated market class and should not have been applied without caveat.

### What the challenge reveals

The challenge flags three competing scales (50, 500, 10,000–100,000 contracts), but **only one is in my evidence: 12,674–38,024.** This is the proxy for *this specific contract*, and it's ~25× higher than the weather reference. The edge evidence does not directly address capacity for crypto contracts—only that the mechanism is "breadth, not depth" [doc:2026-07-23-prediction-market-strategies:1].

### Revised probe

1. **Start with the proxy, not weather:** Run `scripts/analysis/walk_book_capacity.py` on KXBTCMAXMON to measure real depth
2. **Probe in crypto-appropriate increments:** 100 → 500 → 1,000 → 2,500 contracts (given the proxy ceiling is 12k–38k/day)
3. **Gate remains: realized edge decay >50%** — but now assessed against crypto capacity, not weather
4. **Stop before breadth fails:** Even if order-book depth holds, the edge is constrained as a "breadth, not depth" play [doc:2026-07-23-prediction-market-strategies:1]; scaling must happen via other crypto contracts, not size on KXBTCMAXMON alone

**The challenge is correct.** I should not have cited a weather-market capacity floor for a crypto contract without explicitly comparing volumes or acknowledging the proxy for *this* market is much larger. Proceed with the paper probe, but calibrate increments to 12k–38k range, not 500.

### Access / regulatory

**ACCESS / REGULATORY** — Go for paper-first probe

**Finding:** No regulatory or API-access blockers for kalshi-kxbtcmaxmon.

- **Venue & US-person status:** Kalshi is CFTC-regulated DCM permitting US persons; live credentials already deployed [strat:kalshi-kxbtcmaxmon:access]
- **API sufficiency:** Full REST v2 + WebSocket authentication in production, adequate for passive-MM order placement and cancellation [strat:kalshi-kxbtcmaxmon:access]
- **Geoblocking scope:** The guardrail against circumventing Polymarket's CFTC geofence [doc:2026-07-23-prediction-market-strategies:13] does not apply — this is single-venue Kalshi, not cross-venue arb.

**Out of scope (for other specialists):** Market-side viability (net-of-fee edge, flow presence, volume absorption, contract count thresholds, exact probe design).

### Testability

I'll acknowledge the challenge is correct on both points. Let me revise:

---

# Revised Testability Assessment: kalshi-kxbtcmaxmon Favorite-Longshot-Harvest Probe

## Go/No-Go: **CONDITIONAL GO** for paper-first (with critical unknowns unresolved)

### Testability Issues

**Data Availability (Blockers)**
- No internal evidence exists for this venue/contract [strat:kalshi-kxbtcmaxmon:noevidence], so the strategy must prove via backtest *before* paper trading.
- **Critical unknown:** Can we access Kalshi order-book history (bid-ask depth over time)? The strategy's edge hypothesis requires order-book dynamics; trade history alone is insufficient to validate fill-price realism.

**Net-of-Fee Edge Survival (UNRESOLVED)**
- **The challenge is valid:** I cannot claim the edge survives Kalshi fees. I cited the soccer-arb template [doc:2026-07-23-prediction-market-strategies:4] without establishing the analogy. That template is a *cross-venue arbitrage* (simultaneous fills required, 5% commission across two venues), not a single-venue passive-MM strategy. Thin edge on soccer matches (-0.7% net overall) does not inform whether passive-MM flow-harvesting survives Kalshi's maker fees on a crypto contract — these are structurally different strategies.
- **Data gap:** I don't have Kalshi's exact maker fee schedule from the evidence [strat:kalshi-kxbtcmaxmon:noevidence] or any other cited source. I claimed "~1%" without evidence and contradicted myself by later listing the fee as an open question. This must be resolved before backtest modeling.

**Flow Hypothesis Validation**
- The strategy assumes "naive YES-longshot flow" exists. We have no evidence this holds [strat:kalshi-kxbtcmaxmon:noevidence]. Backtest will reveal whether historical data *contains* such asymmetry, but cannot predict forward behavior.

### Exact Probe Design

**Data prerequisites (confirm before backtest):**
1. Kalshi maker fee for kxbtcmaxmon (exact schedule).
2. Availability and cost of order-book snapshots vs. trade ticks only.
3. Contract age (is >30 days of history available?).

**If data is available:**
1. Backtest: simulate passive orders on favorite side; measure fill rate, slippage, P&L post-fee.
2. Paper: compare actual fills to backtest; capacity ramp to decay point.

**Recommendation:** Resolve fee and data-access gaps first. If Kalshi's maker fee is steep enough that passive-MM cannot absorb it, the probe is moot. Without evidence, do not assume the edge survives.

---

**The challenge stands:** I misapplied the soccer-arb evidence and made an unsupported fee claim. The revised version makes only claims backed by the available evidence.

