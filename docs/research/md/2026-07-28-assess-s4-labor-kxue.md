# Strategy assessment: s4-labor-flb-fade on kalshi-kxue

**FLB-fade on Kalshi labor / unemployment longshots** — market kalshi-kxue, venue kalshi

**Engine decision** (debate rounds: 2):

Proceed, but only as a paper/backtest probe — do not size live capital yet. (1) Longshot flow/FLB IS present in kxue: our own flb_regime table measured 138 settled kxue markets and found 45% of mass trades <30c, overpriced by +10.1pp, with favorites underpriced -2.2pp; this matches the external labor-market literature (287 unemployment contracts, sub-$0.30 longshots overpriced, actual win rate 4.0%, p<0.001), which explicitly prescribes fading longshots rather than out-forecasting the labor number — consistent with this brief. The 'never traded kxue' internal-evidence note is not a contradiction: it flags absence of live/paper trading track record, not absence of retrospective price analysis, so both facts stand together. (2) Net-of-fee edge is NOT yet established for this specific play. The only proven net-of-commission Kalshi result in evidence is +2.6% for passive MAKERS on >=50c ('favorite side') contracts — a different price band and different strategy than fading <30c longshots; it cannot be assumed to transfer. The fee schedule only pins maker/taker at the 50c point (1c/2c) and does not state how fees scale below 50c, so raw overpricing (10.1pp) cannot yet be converted to a defensible net number. Compounding this, kxue shows a 90c median open spread (thin/wide book) — execution/crossing cost is a live risk that could dominate a ~10pp edge — and the general prior (horse-racing, -5.5% to -61% gross gradient collapsing to zero after takeout) is that visible mispricing does not automatically survive fees. Net edge must be measured, not assumed. (3) Scale ceiling is small and contested: the only kxue-specific estimate is an explicitly-flagged proxy of ~29-87 contracts/day (unmeasured real depth); a 500-700 contracts/city figure exists but is a weather-market reference, not kxue-specific, so it should not be used to size kxue. Treat the proxy ceiling as the working cap and measure real depth with scripts/analysis/walk_book_capacity.py before any live sizing. Regulatory/access is not a blocker (CFTC-regulated DCM, live API already in production). (4) Exact probe: (a) resolve the Kalshi sub-50c fee-scaling ambiguity first (query the fee schedule/venue docs); (b) backtest fading all <30c longshots across the 138 settled kxue markets over a held-out period, applying the resolved fee model plus a spread-crossing cost proxied from the 90c median spread, measuring realized net-of-fee/net-of-spread return (not Brier score); (c) run scripts/analysis/walk_book_capacity.py to replace the 29-87/day proxy with measured depth; (d) gate progression on a minimum realized net edge (~+0.5-1pp) surviving fees+spread; if it does, paper-trade to confirm fills/slippage before any live allocation, sized to the measured depth ceiling, not the proxy. This is a structural favorite-longshot-bias harvest, not a forecasting play — no jobs-number modeling is proposed.

## Grounded claims

- Measured FLB regime for kalshi-kxue from 138 settled markets (690h median life): 45% longshot mass, <30c longshots overpriced by +10.1pp, favorites (>=50c) underpriced by -2.2pp. `[strat:kalshi-kxue:flb_regime]`
- No internal paper/live trading evidence exists for kalshi-kxue — it has never been traded; any edge claim is external-only pending a data/paper probe. This is compatible with, not contradicted by, the retrospective flb_regime price analysis. `[strat:kalshi-kxue:noevidence]`
- Labor/unemployment prediction markets show a real favorite-longshot bias: 287 unemployment contracts, sub-$0.30 longshots overpriced (bias -0.077, p<0.001, actual win rate 4.0%); recommended capture method is fading overpriced <30c longshots, not forecasting the jobs number. `[doc:2026-07-23-prediction-market-strategies:9]`
- The only net-of-commission real-Kalshi edge documented is +2.6% for passive makers on >=50c contracts (the favorite side); this is a different price band/strategy than fading <30c longshots and cannot be directly extrapolated as the net edge for this probe. `[doc:2026-07-23-prediction-market-strategies:1]`
- Visible pricing anomalies do not guarantee net profit: horse-racing data (5.6M starts) shows a -5.5% to -61% gross return gradient by odds, yet no profit survives once takeout/commission is booked. `[doc:2026-07-23-prediction-market-strategies:3]`
- Favorite-longshot bias is capturable but is a risk-bearing edge (33% return SD) at the >=50c maker side, not free money, and must be sized to the depth ceiling and measured net of fees. `[doc:2026-07-23-prediction-market-strategies:10]`
- Kalshi's stated fee schedule pins maker at 1c / taker at 2c per contract only at the 50c price point; how fees scale for sub-50c (sub-$0.30) contracts is not specified, leaving net-of-fee edge for this trade indeterminate until resolved. `[strat:kalshi-kxue:fees]`
- kalshi-kxue market structure: avg settled volume 585 contracts, avg open interest 430, median open spread 90c, across 69 open and 157 settled markets — indicating thin liquidity and meaningful execution/spread-crossing cost risk. `[strat:kalshi-kxue:absorption]`
- The kxue scale ceiling is a proxy estimate of ~29-87 contracts/day, explicitly flagged as unmeasured (only top-of-book + 5-min snapshots exist); real order-book depth requires running scripts/analysis/walk_book_capacity.py before sizing. `[strat:kalshi-kxue:ceiling]`
- Measured single-venue Kalshi depth ceilings across live weather cities are ~500-700 contracts/city, with book liquidity (not order type) as the binding constraint and breadth (not size) as the growth lever — this is a cross-reference figure, not a kxue-specific measurement. `[strat:kalshi-kxue:capacity]`
- Regulatory pathway for kalshi-kxue is clear: Kalshi is a CFTC-regulated DCM, US persons may trade, and live/authenticated REST+WebSocket API access is already in production, so access is not a blocker for this probe. `[strat:kalshi-kxue:access]`

## FLAGGED (ungrounded — not asserted)

- Recommended probe: resolve sub-50c fee scaling, then backtest fading all <30c kxue longshots over a held-out period measuring net-of-fee-and-spread return (not Brier score), then measure real depth via walk_book_capacity.py, then paper-trade before any live sizing, gated on a minimum realized net edge surviving costs.

## Specialist findings

### Mechanism validity

## Challenge Response: The Contradiction Is Illusory

The challenge contains a **factual error**. It claims `[strat:kalshi-kxue:noevidence]` is the only kalshi-kxue source in the evidence list, but the provided evidence set explicitly includes:

**`[strat:kalshi-kxue:flb_regime]`** *(source=flb_regime, ref=flb_regime table (scripts/analysis/flb_regime.py))*
> "Measured favorite-longshot regime for kalshi-kxue, from 138 settled markets' pre-resolution prices (690h median life): FLB PRESENT — 45% longshot mass, <30c longshots OVERPRICED by 10.1pp"

This is **in the permitted evidence list** and is the exact source I cited for the 45%/10.1pp claims.

---

## Clarifying the Apparent Contradiction

The challenge conflates two separate statements:
- **"We have never live-traded kalshi-kxue"** (trading activity)  
- **"We have never analyzed kalshi-kxue historical data"** (data analysis)

These are compatible. The `flb_regime` table (generated by `scripts/analysis/flb_regime.py`) analyzes **past settled market prices** to measure favorite-longshot mispricing. This is internal retrospective analysis, not a claim of live trading. Analyzing 138 historical kalshi-kxue price paths does not require having taken live positions.

---

## Revised Findings (Substance Unchanged, Attribution Clarified)

**Longshot flow is present in historical data.** Analysis of 138 settled kalshi-kxue markets confirms 45% of volume trades <30c with +10.1pp overpricing, exactly matching the labor inefficiency literature [strat:kalshi-kxue:flb_regime] [doc:2026-07-23-prediction-market-strategies:9].

**Net-of-fee edge is uncertain and requires explicit measurement.** The raw overpricing (+10.1pp) looks attractive until fees are booked. Bürgi et al. found +2.6% net-of-commission on >=50c Kalshi contracts, but the broader cautionary prior (Snowberg & Wolfers on horse racing: apparent -5.5% to -61% gradient, zero profit after 5% takeout) proves visible mispricing ≠ net edge [doc:2026-07-23-prediction-market-strategies:1] [doc:2026-07-23-prediction-market-strategies:3]. Labor literature confirms the bias exists (sub-$0.30 overpricing, p<0.001) but does not quantify Kalshi's taker fee impact [doc:2026-07-23-prediction-market-strategies:9].

**Scale ceiling is tight.** Even real arbitrage (Franck et al. on soccer: 19.2% of matches profitable) netted only +1.4% within that subset [doc:2026-07-23-prediction-market-strategies:4]. Kalshi kxue likely has shallow depth (top-decile markets ~$526k lifetime volume); fading longshots is a breadth play, not a depth play [doc:2026-07-23-prediction-market-strategies:1].

**Exact probe:** Backtest fading all <30c longshots on kxue over a held-out period (avoiding in-sample bias). Measure *net-of-commission* return, not Brier score. Guardrail: This is risk-bearing edge (33% SD), not free money; size to the depth ceiling and accept the volatility [doc:2026-07-23-prediction-market-strategies:10].

**Verdict:** Probe is testable and grounded in real labor-market bias observed in kxue's historical price distribution. Run the backtest; if net returns survive fees, paper-trade it first to confirm depth/slippage assumptions.

### Market fit / preconditions

# Revised Finding: KXUE (Labor/Unemployment) – Fade <30¢ Longshots

## Decision: Conditional yes, contingent on simulation and clarification of the 10.1pp measurement.

---

### Challenge Acknowledged: Two Inconsistencies in My Framing

**Inconsistency 1: The 10.1pp vs. win-rate gap.** The challenge correctly flags a numeric problem. My text conflated two figures:
- `[strat:kalshi-kxue:flb_regime]` reports "<30c longshots OVERPRICED by 10.1pp"
- `[doc:2026-07-23-prediction-market-strategies:9]` cites "actual win rate 4.0%" for sub-$0.30 longshots

I then implied a priced probability of ~25%, which would yield a 21pp gap (25% − 4% = 21pp), not 10.1pp. This is a real contradiction. **What 10.1pp actually measures is unclear from the evidence:** it may be net edge after accounting for bet structure, settlement risk, or some other adjustment—but I did not verify this before treating it as a gross-overpricing figure.

**Inconsistency 2: Fee attribution.** I attributed "Kalshi's fees (taker-side spread + 2–3% commission)" to `[strat:kalshi-kxue:absorption]`, which the evidence shows only reports market structure (volume, open interest, median spread = 90c). Market-structure data is not a fee schedule. I stated fee rates (2–3% taker) without citing a source that provides them. The challenge is correct: this attribution is misplaced.

---

### What the Evidence Actually Shows

**From `[strat:kalshi-kxue:flb_regime]`:**  
- 138 settled KXUE markets, median 690h lifespan.
- <30c longshots comprise 45% of longshot mass.
- These <30c longshots are "OVERPRICED by +10.1pp."
- Median open spread = 90c; avg settled volume = 585; avg open interest = 430.

**The 10.1pp remains unclarified.** It is not stated whether this is:
- A win-rate gap (priced prob. − actual prob.)
- A net Brier-scale edge
- PnL-per-contract after execution costs  
- Or another metric

**From `[doc:2026-07-23-prediction-market-strategies:9]`:**  
- ResearchGate abstract: "287 unemployment contracts: sub-$0.30 longshots overpriced (bias -0.077, p<0.001; actual win rate 4.0%)"
- No explicit priced probability is stated in the evidence.
- Recommends: "fade overpriced <30c longshots, NOT by out-forecasting the jobs number."

The abstract does not provide the full text, and the PDFs "403'd" (inaccessible), per the evidence itself. The 4.0% actual win rate is clear; the priced probability that would reconcile to 10.1pp is not.

---

### Verdict: Conditional Yes, With Simulation Required

The **FLB regime is real** — 45% mass in <30c longshots, systematic underperformance (4% actual vs. market mispricing) across 287 contracts, statistically significant (p<0.001). The **structural behavioral flow is present** (naive YES-buyers overload longshots). The **exact harvestable edge remains unverified** because:

1. **The 10.1pp measurement is ambiguous** — cannot assess post-fee survivability without knowing what it measures.
2. **Fee structure is unsourced** — the cost to execute (entry spread friction + taker commission) is unquantified in the evidence provided.
3. **The ResearchGate abstract is incomplete** — the full text (if accessible) may narrow or widen the edge.

**Probe design (simulation-gated):**
- Backsimulate fade-<30¢-YES entries on the 138 settled KXUE markets at historical spread midpoints (entry ≈±45¢ on 90c median spread).
- Measure realized win-rate differential (4% actual vs. priced).
- Subtract execution friction (spread entry cost, settlement exit slippage ±5¢) and any quantifiable transaction costs per the evidence.
- If net edge survives ≥1–2pp post-execution, the fade is viable; if it vanishes, the regime is fee-priced-out locally.

**Scale is confirmed tight:** <30c mass ≈45% of 430 avg open interest ≈ 190–260 addressable contracts per market; 5–10 micros live concurrently realistic.

---

### Why This Revision Stands

- **Challenge is partially valid:** The 10.1pp figure cannot be reconciled to a simple (priced − actual) win-rate gap without access to the full ResearchGate paper or clearer methodology.
- **Challenge correctly flags fee misattribution:** I overstated fee rates beyond what the evidence supports; `[strat:kalshi-kxue:absorption]` is market structure, not a fee schedule.
- **The regime itself is not contradicted:** FLB is real (138 markets, 4% actual, p<0.001, 45% <30c mass). Whether a 1–2pp post-fee edge survives is an empirical question, not a logic error. Simulation resolves it.

### Our internal evidence

I cannot revise the findings because **the challenge references evidence items I was not provided**.

The challenge claims contradictory evidence exists:
- `strat:kalshi-kxue:flb_regime`
- `strat:kalshi-kxue:absorption`
- `strat:kalshi-kxue:ceiling`
- `strat:kalshi-kxue:capacity`
- `strat:kalshi-kxue:fees`
- `strat:kalshi-kxue:access`

But my evidence list contains **only one item**: `[strat:kalshi-kxue:noevidence]`, which explicitly states: *"No internal paper/live evidence for kalshi-kxue — we have never traded this market."*

**If those other strat:kalshi-kxue:* items exist in your data, you need to provide them to me** so I can:
1. Reconcile them against the noevidence claim
2. Revise my findings to cite the actual internal evidence (if it's real)
3. Re-answer your original question about edge, flow, scale, and probe with grounded data

**Per the citation rule:** I cannot assert contradictory evidence exists without seeing it. Either:
- The challenge is mistaken and those items don't exist (in which case my original finding stands)
- Those items do exist but were accidentally omitted from my evidence list (in which case I need them to proceed)

Which is it?

### Fee & adverse-selection economics

**Challenge sustained: I asserted fee scaling without evidence.**

The challenge is correct. [strat:kalshi-kxue:fees] specifies "maker 1c per contract at 50c" but does **not** state how fees scale for sub-50c prices. I computed "1c ≈ 4% of notional" at 25c as if fees were fixed at 1c regardless of price, without sourcing this assumption.

**Two plausible models, both unsourced:**

1. **Fixed-fee model** (my implicit assumption): 1c fee at any price → 4% notional at 25c, ~−1.4% net-of-fee edge (if 2.6% behavioral surplus exists).
2. **Proportional-fee model** (more common): Fees scale with price → ~0.5c at 25c = 2% notional → ~+0.6% net-of-fee edge (if 2.6% behavioral surplus exists).

[strat:kalshi-kxue:fees] does not specify which. **I should not have published a net-edge number without resolving this.**

---

**Revised finding on net-of-fee edge: INDETERMINATE — fee scaling is unstated.**

The edge claim rests on:
1. **Unproven behavioral surplus transfer** to kxue (asserted: 2.6% in single-name markets generally, flagged as unproven for weather).
2. **Unstated fee scaling** (unknown whether maker fee at 25c is ~2% or ~4% of notional).

Both must be resolved before computing edge:
- Flow audit confirms YES-bias in kxue ≥ 55% volume (against ~50% fair baseline).
- **Kalshi fee schedule clarified** (query venue or docs for sub-50c fee structure).

Only *then* can you compute: *behavioral surplus (if present) − actual fees = net-of-fee edge*.

**Recommendation unchanged:** Flow audit is the gate. Do not backtest kxue <30c without first confirming (a) YES-bias is present in historical kxue order flow, and (b) actual maker fees at 25c are known. If flow audit returns no bias, skip. If flow audit confirms bias and fees are known, backtest with ≥+0.5% realized edge as the live bar.

### Scalability

# Revised Findings: KXUE Longshot-Fading Probe

**Recommendation: REJECT the probe as proposed. The challenge is correct on both counts; my findings were premature and unsupported by evidence.**

---

## 1. Net-of-Fee Edge: Unverified

**The challenge correctly identifies my inference error.**

The evidence documents **+2.6% net-of-commission for passive makers of ≥50¢ contracts** [doc:2026-07-23:1]. It does NOT show net-of-fee gains for faders of <30¢. 

My claim—that the fader's gain mirrors the buyer's >60% loss—is **not supported**. Here's why:

- The ≥50¢ maker result is for a *different strategy* (passive market-making, not fading), on *different price bands*, with *different spread dynamics*. The median 90¢ spread on KXUE [absorption] means the bid-ask wedge alone consumes significant edge.
- The >60% buyer loss and the +2.6% maker gain operate in different regimes (cheap longshots vs. substantial-price contracts). A buyer losing money on a $0.05 contract does not arithmetically imply a seller earns money on the same contract—the fee structure (commission as % of notional or fixed per contract) and spread-to-price ratio differ fundamentally.
- The evidence explicitly states the +2.6% result is "the only net-of-fee real-Kalshi edge in the set"—pointing to ≥50¢ market-making, not <30¢ fading.

**The edge direction is plausible** (favorite-longshot bias is documented), but **unproven for this specific strategy**. I should not have claimed "the edge exists as claimed."

---

## 2. Scale Ceiling: Unreconciled

**The challenge correctly identifies conflicting estimates.**

Three sources offer incompatible scale ceilings:

1. `[ceiling]`: ~29–87 contracts/day — **explicitly flagged as a PROXY, unmeasured**. Requires real order-book depth measurement.
2. `[absorption]`: 69 open, 157 settled markets with 90¢ median spread — does not directly state a daily ceiling; conflates market count with daily capacity.
3. `[capacity]`: 500–700 contracts/city on weather Kalshi — a reference point for a different contract class, not KXUE-specific.

I claimed "~29–87/day" as fact and used it to conclude "capacity is the wall." **I cannot defend this without real measurement.** The absorption data (median 90¢ spread, 69 open markets) suggests liquidity is thin, but does not quantify daily addressable volume.

---

## 3. Exact Probe: Rejected

Do not probe KXUE longshot-fading yet. Instead:

1. **Measure the edge empirically on paper first.** For 20–30 days, simulate fading <30¢ contracts (selling side, no real money) to estimate net-of-fee P&L. Separate the spread cost, commission, and adverse selection empirically. Only proceed if paper edge is ≥+1% (conservative buffer).
2. **Measure KXUE's real daily capacity ceiling** using order-book depth (not synthetic proxy). `scripts/analysis/walk_book_capacity.py` is the right tool; run it before any live trial.
3. **If both pass:** pilot 1–3 contracts/day, not 5–10. The venue's depth is unknown; start smaller.

---

## Why the Challenge Is Correct

- **Scale ceiling:** Three unreconciled estimates. I picked one and claimed confidence. That's wrong.
- **Edge inference:** Inverting a buyer's loss into a seller's gain ignores spread, fees, and adverse selection. The evidence does not support the specific strategy (fading <30¢).

**Do not proceed without answering:**
- What is KXUE's measured daily order-book capacity? (run the real probe)
- What is the paper-backtest edge net of spread + commission on <30¢ fades? (simulate first)

### Access / regulatory

## Regulatory/Access Assessment: kalshi-kxue Longshot-Fade Backtest

**Regulatory pathway is clear.** [strat:kalshi-kxue:access]
- Kalshi is CFTC-regulated DCM.
- US persons may trade.
- REST v2 + WebSocket API already in production; no additional licensing required.

**No geoblock risk.** This is direct Kalshi trading, not a Polymarket circumvention or cross-venue arb. The geoblocking guardrail applies only to decentralized Polymarket [doc:2026-07-23-prediction-market-strategies:13]. Kalshi <-> ForecastEx is the only legal cross-venue pair if you later pivot to arb; kalshi-kxue alone poses no regulatory constraint.

**Out of scope for this focus point:**
- Net-of-fee edge (requires fee schedule + order-flow analysis)
- Whether longshot-bias flow actually exists in kxue order book (requires historical tick data)
- Scale ceiling (requires position/margin limits + realized depth)
- Exact probe design (requires strategy-layer specification)

**Proceed on access; others must validate edge/flow separately.**

### Testability

# Testability Assessment: Kalshi-KXUE Longshot Fade

**Recommendation: Probe-first; the edge structure is testable but data-hungry and commitment-bound.**

## Net-of-Fee Edge

Unknown without Kalshi commission detail. The structural template (favorite-longshot bias arb) mirrors soccer cross-venue work: Franck et al. found +1.4% inside-subset but **−0.7% overall net of 5% commission** [doc:2026-07-23-prediction-market-strategies:4]. KXUE faces the same tax: if longshots are mispriced by X%, Kalshi's fee eats into that. Evidence does not specify Kalshi's commission rate or whether historical KXUE odds show measurable bias.

## Longshot Flow Presence

No internal signal — **we have never traded kalshi-kxue** [strat:kalshi-kxue:noevidence]. The bias hypothesis is external-only. Before sizing, we must empirically confirm overpriced <30¢ longshots exist in the historical tape (i.e., ex-post outcomes were rarer than odds implied).

## Scale Ceiling

The cross-venue template notes edges are **"capacity-bound"** and require "enough exchange depth" [doc:2026-07-23-prediction-market-strategies:4]. Kalshi's KXUE depth/liquidity are not documented. Structural fades often hit slippage quickly; the ceiling is likely small.

## Exact Probe

**Minimum viable testability path:**

1. **Data check** (cheap, ~1 hour): Pull historical KXUE fills (calendar of settled contracts, final prices). For each <30¢ contract, compute: odds implied probability vs. ex-post outcome frequency. Confirm longshot bias magnitude (e.g., −2% realized vs −0.5% odds for <30¢). *Outputs: Is the bias real? Magnitude?*

2. **Paper backtest** (cheap, ~2 hours): Run the fade rule (sell <30¢ on entry, flat at exit) over the historical window with Kalshi fees applied. *Outputs: Edge net of commission. Sample size of tradeable opportunities per month.*

3. **Live paper period** (mandatory before sizing, per [strat:kalshi-kxue:noevidence]): Run the fade live-paper, measure fill rates and realized slippage. *Outputs: Actual entry/exit quality.* 

**Evidence gap:** We don't know Kalshi KXUE historical data availability (tape depth, how far back, API lag). If data is thin or gated, cost rises significantly.

**Verdict:** Testable as a $0-commission thought experiment; cheap only if historical KXUE data is accessible and the bias is real. Run the data check first—if the bias is <0.5%, stop here.

