# Strategy assessment: s1-flb-harvest on kalshi-kxbtc15m

**Passive market-making / favorite-longshot harvest** — market kalshi-kxbtc15m, venue kalshi

**Engine decision** (debate rounds: 2):

GO — but only as a paper-first probe, not a backtest-to-live jump. The literature-documented edge (passive makers earn +2.6% net-of-commission on >=50c Kalshi contracts, the only net-of-fee real edge found across all reviewed studies) and the underlying favorite-longshot mispricing are real, and kxbtc15m has no access/regulatory blockers and is already API-ready. But three things are unverified for this specific market and must be measured before any capital is risked: (1) we have zero internal trading history on kalshi-kxbtc15m, so the edge is currently an external-only claim; (2) the behavioral 'naive YES-longshot' flow that funds the edge is proven in cross-market and weather/labor single-name data but is explicitly unproven for crypto-direction markets, and a separate guardrail states forecasting skill does not travel to BTC direction (though the FLB mechanism is structural, not forecasting-based, so it is not disqualified by that guardrail); (3) kxbtc15m's 1.67M avg contract volume cannot be directly compared to the literature's $526,245 dollar-denominated depth baseline — this is a unit mismatch, not evidence of superior or inferior depth — so absorption capacity is genuinely unmeasured (proxy estimate of 83,857–251,573 contracts/day exists but is explicitly flagged as synthetic/unverified, versus a measured ~500-700 contracts/city reference from weather). Exact probe: run a 10-20 trading day paper-only test on kalshi-kxbtc15m, buying only the favorite side (>=50c), passive/maker orders where possible. Track three gates in sequence: (a) FLOW GATE — compare YES-volume share vs YES-settlement rate; if they converge (no behavioral surplus), stop. (b) NET-EDGE GATE — apply Kalshi's actual fee schedule (2c/contract taker, 1c/contract maker at 50c, per catalog.py fee_cents formula) to realized fills; if median net P&L per contract is <=0, stop. (c) CAPACITY GATE — ramp paper position size in steps (10 → 50 → 100 → 500 → 1,000+ contracts) and measure marginal P&L decay; also run scripts/analysis/walk_book_capacity.py to replace the synthetic depth proxy with a measured order-book ceiling. If all three gates pass, escalate to a small live trial (single-digit-to-low-double-digit contracts, tight stop-loss); if the edge decays steeply before meaningful size, treat kxbtc15m as a breadth-not-depth play consistent with the wider FLB literature and prioritize adding markets rather than deepening this one.

## Grounded claims

- Passive makers buying >=50c Kalshi contracts earn +2.6% after commission (per-contract, high-price side only); this is the only net-of-fee real edge identified across the literature reviewed. `[doc:2026-07-23-prediction-market-strategies:1]`
- Strong favorite-longshot bias is documented in Kalshi data: <10c contracts lose >60%, >=50c contracts earn a small statistically-significant positive return, and the all-contract average return is ~-20%. `[doc:2026-07-23-prediction-market-strategies:1]`
- The +2.6% maker edge carries ~33% return SD (~13x the mean) and survives only at trivial size because top-decile Kalshi markets average only $526,245 in lifetime dollar volume — a large-capital maker may have to post less advantageous prices; the edge is a breadth (more markets), not depth (size), play. `[doc:2026-07-23-prediction-market-strategies:1, doc:2026-07-23-prediction-market-strategies:10]`
- kalshi-kxbtc15m has avg settled volume of 1,677,156 contracts, avg open interest 262,418, and median open spread 1c, with 1 open and 200 settled markets in the catalog. `[strat:kalshi-kxbtc15m:absorption]`
- There is no internal paper or live trading evidence for kalshi-kxbtc15m — the venue has never been traded internally, so any edge claim is external-only and must be validated via a data/paper probe before sizing. `[strat:kalshi-kxbtc15m:noevidence]`
- Kalshi fees are 2c taker / 1c maker per contract at a 50c price point; single-name event brackets carry adverse selection of ~33% per-trade return SD (~13x the mean), and one-sided order flow predicts maker losses, warranting size-down or step-aside discipline on toxic flow. `[strat:kalshi-kxbtc15m:fees]`
- In single-name markets generally, traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time, creating a behavioral surplus that funds maker profits; this surplus is proven cross-market but explicitly unproven for weather single-name brackets, and by extension untested for crypto-direction contracts like kxbtc15m. `[doc:2026-07-23-prediction-market-strategies:2]`
- A guardrail states that Benter/EMOS-style forecasting-model edges do not travel to BTC/crypto direction (near-random to ML at 0.539 accuracy; 6 frontier models lost money live on Kalshi crypto), but the structural favorite-longshot-bias edge (not forecasting) is what travels to liquid markets — relevant because this strategy is explicitly structural FLB, not model-based forecasting. `[doc:2026-07-23-prediction-market-strategies:12]`
- The scale ceiling for kalshi-kxbtc15m is only a synthetic proxy estimate of ~83,857–251,573 contracts/day; real order-book depth is unmeasured (only top-of-book plus 5-minute snapshots exist), and the measured Kalshi weather reference ceiling is ~500-700 contracts/city, which may not transfer to 15-minute crypto contracts. `[strat:kalshi-kxbtc15m:ceiling]`
- Measured single-venue depth ceilings on Kalshi from prior capacity studies show ~500-700 contracts/city across all live cities, with book liquidity (not order type) as the binding constraint, establishing breadth rather than size as the growth lever. `[strat:kalshi-kxbtc15m:capacity]`
- Kalshi kxbtc15m is a CFTC-regulated DCM open to US persons, with full REST v2 + WebSocket API already authenticated and in production on this box — no access or regulatory barriers to a paper-first probe. `[strat:kalshi-kxbtc15m:access]`
- FLB is capturable but is a risk-bearing edge (33% SD), not free money or a passively-collectible risk premium; any FLB strategy must be sized to its depth ceiling and measured net of fees. `[doc:2026-07-23-prediction-market-strategies:10]`
- Short-dated single-name markets (the same structural category as 15-minute BTC contracts) have been shown to be significantly mispriced (46% implied vs 21% settled), so short-dated single-name brackets should not be presumed efficient — though this evidence is drawn from weather, not crypto. `[doc:2026-07-23-prediction-market-strategies:11]`

## FLAGGED (ungrounded — not asserted)

- kxbtc15m's contract-count volume (1.67M contracts) cannot be directly compared to the literature's dollar-denominated depth baseline ($526,245 lifetime volume) without a price/notional conversion, which is not present in the evidence — depth adequacy for kxbtc15m is therefore unverified, not confirmed.

## Specialist findings

### Mechanism validity

Let me address this directly. The challenge correctly identifies a unit-mismatch error in my original findings. Here's the revised assessment:

---

# Mechanism Validity Assessment: Kalshi-kxbtc15m Passive-MM / FLB Strategy
## REVISED — Challenge Addressed

**Recommendation: GO for paper-first probe**, with explicit capacity guards and revised depth analysis.

---

## Challenge & Correction

**The challenge is correct:** I compared contract volume (1.67M contracts) directly against dollar-denominated lifetime volume ($526k) without unit reconciliation. These are incommensurate, so my "kxbtc15m has superior depth" conclusion was invalid.

**Revised depth assessment:**

The evidence [1] reports only the dollar baseline: "top-decile markets average $526,245 lifetime volume." Without Kalshi's contract price distribution and the notional value of 1.67M contracts on kxbtc15m, I cannot infer whether kxbtc15m's depth is above or below the research baseline. This is an empirical gap, not a deduction.

**What this means for the probe:**

The binding constraint remains **depth uncertainty, not depth sufficiency**. The backtest must explicitly measure it:

1. **Quantify kxbtc15m's depth empirically** — obtain order-book snapshots from Kalshi's historical data (if available) or live feeds. Derive the aggregate notional volume available at >=50c side, then compare it to the $526k research baseline in dollar terms.
2. **Size the backtest position conservatively** — until you have the depth data, assume depth is the research baseline (~$526k notional). Cap your position to 25–50% of that, then run paper. If paper shows positive returns at this capped size, depth was sufficient for this test.
3. **Do NOT infer depth from contract count alone** — trading volume in contracts is necessary but not sufficient to determine book depth.

---

## Findings (Reaffirmed)

**Edge survives net of fees: YES** [1]  
Bürgi et al. (2025/26) documents passive makers earning **+2.6% net of commission on >=50c contracts**—the only net-of-fee real edge in the literature. This applies directly to your strategy.

**Longshot flow is real: YES** [1]  
Strong favorite-longshot bias is empirically proven: <10c contracts lose >60%, >=50c earn positive returns. The naive YES-longshot demand exists.

**Depth ceiling is the binding constraint—and depth must be measured** [1]  
The research baseline is $526k lifetime notional volume on high-decile markets. kxbtc15m's 1.67M contracts is a necessary but not sufficient signal for depth. You must empirically measure kxbtc15m's notional book depth before sizing the backtest position.

**Exact probe design (revised):**
1. Measure kxbtc15m's order-book depth in dollar terms (notional, not contracts). Compare to $526k baseline.
2. Cap backtest position to 25–50% of measured depth to account for latency and volatility.
3. Run paper; measure **net-of-fee returns, Sharpe, max drawdown**. Do NOT report gross returns or Brier-only.
4. If paper succeeds at the capped size, replicate on 3–5 other >=50c contracts to validate breadth scalability.

**Risk guardrail:** +2.6% mean with 33% SD means large drawdowns. This is a risk-bearing edge, not free money [1][10].

---

**Go/no-go: GO for paper-first**, conditional on step 1 (depth measurement). The mechanism is real; the market's ability to absorb size is unknown and must be measured before committing to the probe.

### Market fit / preconditions

**CONDITIONAL GO for paper probe; insufficient evidence to commit to backtest/live.**

The strategy targets structural FLB (naive YES-longshot overbuy), not forecasting skill—it avoids the crypto guardrail [doc:2026-07-23-prediction-market-strategies:12], which only kills model-based edges. FLB is confirmed as a real mechanism in weather single-name markets [doc:2026-07-23-prediction-market-strategies:2, :11] and labor brackets [doc:2026-07-23-prediction-market-strategies:9], establishing that the behavioral mispricing basis exists.

**Critical unknowns the evidence does not cover:**

1. **Does FLB exist on crypto binaries?** Bartlett & O'Hara's adverse-selection finding applies to weather and labor; KXBTC15M's market microstructure (informed/naive trader mix, volatility regime, settlement finality) may differ fundamentally. Evidence gap.

2. **Kalshi fee structure.** No taker/maker fees specified in evidence. 1c median spread [strat:kalshi-kxbtc15m:absorption] may be grossed by execution cost, eliminating edge entirely.

3. **Flow absorption and decay rate.** 1.6M settled volume [strat:kalshi-kxbtc15m:absorption] is substantial; unknown whether overpriced YES-longshot flow persists under size or decays due to informed traders repositioning.

**Exact paper probe (10 trading days):**
- Target: 50–100 contracts/day, buy at ≥50c only
- Measure: (a) actual realized fill vs theoretical best-bid/ask, (b) net daily P&L after all Kalshi fees, (c) whether edge deteriorates after 50+ contracts or flow tightens
- Gate: If net P&L > 0 *and* flow concentrates at YES-longshot prices, proceed to backtest sizing. Else, deprioritize vs confirmed-FLB venues (weather, labor).

### Our internal evidence

## Findings: kalshi-kxbtc15m paper-first probe assessment

**Recommendation: YES — proceed with paper-first probe. This is mandatory due to absence of internal evidence.**

---

**What we don't know:**

- **Net-of-fee edge survival:** Unknown. We have zero internal evidence for kalshi-kxbtc15m. [strat:kalshi-kxbtc15m:noevidence] Any edge claim is external-only; we cannot validate it against our own fills, slippage, or latency.
- **YES-longshot flow presence:** Unknown. The strategy assumes naive flow on the longshot side (< 50¢). This requires observing actual order-book / trade flow; we have no prior verdicts.
- **Contract absorption capacity:** Unknown. Liquidity depth and market depth at our typical entry sizes is unprobed.

---

**Exact probe:**
1. **Backtest window:** 2–4 weeks of paper trades, sampling across market hours and vol regimes
2. **Success criteria:**
   - Realized P&L net-of-fees is positive (even if small)
   - Favorable/YES-side (≥50¢) fill rates ≥80% (confirms passive-MM positioning works)
   - Position lifecycle: entry→fill→exit latency and slippage measured
3. **Stop criteria:**
   - Net P&L trend is negative despite taking 100+ paper fills
   - Mark spreads widen beyond model assumptions (edge thesis invalidated)

**Why now:** BTC contracts are liquid and non-weather; volume (1.67M avg) is high enough that a paper probe is fast and cheap. External edge claims lack our own reconciliation—run the probe to decide sizing.

---

**Evidence coverage:** 
- [strat:kalshi-kxbtc15m:noevidence] confirms zero internal history. No other sources available to this focus point.

### Fee & adverse-selection economics

I need to acknowledge that the challenge is **substantially correct** — my previous response conflated kalshi-kxbtcmaxmon (a separate assessment) with the actual question about kalshi-kxbtc15m. Let me write a revised findings using only the evidence provided to me now.

---

# **Revised Findings: Fee & Adverse-Selection Economics on kalshi-kxbtc15m**

**Recommendation: CONDITIONAL GO for paper-first probe.**

---

## Does the net-of-fee edge survive?

**Unknown on kxbtc15m specifically.** The evidence base confirms that Kalshi single-name markets carry a **1c maker / 2c taker fee**, and historical fills show ~33% per-trade return standard deviation (≈13× the mean)—signaling high adverse-selection toxicity [strat:kalshi-kxbtc15m:fees]. 

However, I have **no evidence that documents a positive net-of-fee edge on kxbtc15m itself.** The prior findings' claim of a "+2.6% net edge" attributed it to Bürgi et al., but that study is not in the evidence base provided. This is the critical gap: **paper backtest is the only way to measure whether passive market-making survives fees on this contract.**

---

## Is naive YES-longshot flow actually present?

**The behavioral bias is cross-market proven, but weather-specific application is contradicted.** 

Bartlett & O'Hara (41.6M trades, 478k markets) document the bias directly: traders buy YES ~60.9% of volume, but markets settle YES only ~32.5% of the time [doc:2026-07-23-prediction-market-strategies:2]. This behavioral surplus underpins profitable market-making in single-name markets.

**However, the evidence explicitly flags weather's weakness:** The citation notes that "the likely reason weather MM would underperform the cross-market average" is that weather brackets are single-name markets where the behavioral bias may be weaker or absent—forecasters actively trade weather direction, flattening naive flow [doc:2026-07-23-prediction-market-strategies:2].

**For kxbtc15m (Bitcoin direction), the evidence is silent.** Crypto-direction betting may attract informed traders (like weather) or gamblers (like sports). Paper data is required to measure whether kxbtc15m's order flow exhibits the 60.9% YES-volume bias.

---

## How many contracts can it absorb before edge decays?

**No ceiling is documented.** The evidence prescribes general discipline: "size down or step aside on toxic one-sided flow" [strat:kalshi-kxbtc15m:fees]—but no quantified absorption threshold is given for any single contract.

kxbtc15m runs 1,677,156 avg daily volume, substantially deeper than weather contracts. Depth alone does not guarantee edge scalability; adverse selection still applies. Paper ramp testing is required to identify the saturation point.

---

## Exact probe:

1. **Backtest kalshi-kxbtc15m historical data:**
   - Simulate passive limit orders on the favorite side (≥50c) at realistic size increments (100 → 500 → 1,000 → 5,000 contracts).
   - Measure realized P&L net of Kalshi's 1c maker fee [strat:kalshi-kxbtc15m:fees].
   - Track fill rates and slippage vs. mid.

2. **Test the flow hypothesis:**
   - Measure YES-volume % vs. YES-settlement % over the backtest window.
   - If YES volume ≈ YES settlement (e.g., both ~50%), the behavioral surplus is absent and edge collapses below fees → **no-go**.
   - If YES volume >> YES settlement, the bias holds → proceed to paper.

3. **Measure toxicity decay:**
   - Ramp order size in paper and measure P&L degradation per contract.
   - Stop when adverse-selection losses exceed 50% of gross edge (if any edge exists).
   - Identifies whether the strategy has meaningful capacity.

4. **No-go triggers:**
   - Net P&L is zero or negative after fees.
   - YES-volume share ≈ YES-settlement rate (behavioral surplus absent).
   - Edge decays below 500-contract absorption (capacity too shallow for meaningful position).

---

## Why proceed (cautiously):

- **Adverse selection is documented:** ~33% per-trade return SD on Kalshi single-name markets confirms toxicity risk [strat:kalshi-kxbtc15m:fees].
- **Behavioral flow bias is proven cross-market:** Bartlett & O'Hara's 60.9%/32.5% pattern is robust [doc:2026-07-23-prediction-market-strategies:2].
- **Crypto-direction unknown:** Weather MM underperforms due to informed participation; crypto may not. Paper directly answers this.
- **No net-of-fee evidence on kxbtc15m itself:** Backtest is the evidence.

**Proceed with paper probe. The outcome hinges on empirical testing, not theory.**

### Scalability

# Scalability Finding: KXBTC15M Passive-MM Probe

## Go/No-Go: **GO (PAPER-FIRST PROBE)**

The net-of-fee edge is documented real. The strategy is viable *in principle* at trivial scale. Scalability path is unmeasured and becomes the probe's central question.

### Edge viability
**Yes, the edge survives net-of-fee.** Passive makers on >=50¢ contracts earn +2.6% after commission across 300k+ Kalshi transactions [doc:2026-07-23-prediction-market-strategies:1]. The favorite-longshot bias is strong: <10¢ contracts lose >60%, >=50¢ earn statistically-significant positive return [doc:2026-07-23-prediction-market-strategies:1].

### Flow presence
**Yes, the naive YES-longshot mispricing is documented.** All-contract average return is ~-20%, driven by retail longshot bias [doc:2026-07-23-prediction-market-strategies:1]. The 1.67M average settled volume in KXBTC15M confirms liquidity exists to exploit [strat:kalshi-kxbtc15m:absorption].

### Absorption & decay
**Absorption is the probe's core unknown.** Three constraints collide:

1. **Edge fragility:** 33% return SD (~13× the mean) means the edge is shallow [doc:2026-07-23-prediction-market-strategies:1]. Large-capital makers "may have to post less advantageous prices" when depth is shallow [doc:2026-07-23-prediction-market-strategies:1].

2. **Measured vs. proxy ceiling:** Real order-book depth for KXBTC15M is **unmeasured** (only top-of-book + 5-min snapshots exist) [strat:kalshi-kxbtc15m:ceiling]. Proxy ceiling is 83k–251k contracts/day [strat:kalshi-kxbtc15m:ceiling], but measured Kalshi weather reference is ~500–700 contracts/city [strat:kalshi-kxbtc15m:capacity]. **These likely don't transfer:** 15-min crypto contracts ≠ daily weather markets.

3. **Breadth, not depth, is the path.** Research confirms: the only net-of-fee real edge scales via **breadth (more markets), not depth (size)**—a high-SD, low-absorption play [doc:2026-07-23-prediction-market-strategies:1].

### Exact probe
1. **Run paper simulation** on KXBTC15M: passive-MM strategy (buy >=50¢, never sell) for 5–10 paper trading days.
2. **Measure real order-book depth** (`scripts/analysis/walk_book_capacity.py`) to replace the synthetic proxy ceiling.
3. **Quantify decay:** How does the +2.6% edge degrade as notional size increases? At what size does favorable pricing disappear?
4. **Verify flow:** Confirm >=50¢ side receives more retail buying (YES-longshot bias) than <10¢ side in 15-min crypto contracts—different asset class than the weather research.

**If paper shows +2.6% survives at 50–100 contract sizes and order-book depth permits, proceed to live sizing. If decay is steep (edge evaporates >500 contracts), KXBTC15M is a breadth play: add more markets instead of deepening this one.**

### Access / regulatory

# Findings: Access / Regulatory

**GO for paper-first probe** — no access or regulatory barriers.

**Venue access:** Kalshi KXBTC15M is CFTC-regulated, US persons are permitted, and full REST v2 + WebSocket API is already in production on this box with live keys available. [strat:kalshi-kxbtc15m:access]

**Regulatory constraint (applied if strategy evolves):** If this favorite-longshot harvest strategy later becomes a cross-venue arbitrage (Kalshi ↔ another venue), the second leg cannot be Polymarket—it is geoblocked for US persons and must never be circumvented. The only legally-executable cross-venue pair is Kalshi ↔ ForecastEx. [doc:2026-07-23-prediction-market-strategies:13] For this single-venue Kalshi probe, this constraint does not apply.

**Operational readiness:** API authentication, WebSocket connectivity, and order infrastructure are already live. No additional licensing or geoblock concerns.

---

**Out of scope for this focus point:** The substantive strategy questions—edge survival after fees, naive YES-longshot flow presence, contract absorption capacity, and exact probe design—require trading/quantitative assessment, not regulatory clearance. Recommend routing those to strategy review.

### Testability

Perfect. I found the evidence. The Kalshi fee structure is defined in the codebase at `src/weather_markets/expansion/catalog.py:42-52` with `taker_rate=0.07` and `maker_rate=0.0175`. The `fee_cents()` function at line 84 computes this as `rate * p * (1-p)` per contract, where `p` is the price as a fraction (e.g., 0.50 for 50¢).

Let me compute the 50¢ fee and write the revised findings:

At 50¢ (p=0.50):
- **Taker fee**: 0.07 × 0.50 × 0.50 = 0.0175 = 1.75¢ (rounds to 2¢)
- **Maker fee**: 0.0175 × 0.50 × 0.50 = 0.004375 = 0.4375¢ (rounds to 1¢)

Now I can address the challenge properly:

---

## Revised Findings: Passive-MM / Favorite-Longshot-Harvest on KXBTC15M

**Go/No-Go: PAPER-FIRST PROBE — proceed, but with structural risk flagged.**

### Net-of-Fee Edge Survives (Just)

[strat:kalshi-kxbtc15m:fees] (source=src/weather_markets/expansion/catalog.py:84–94) Kalshi taker fee at 50¢ is **~2¢ per contract** (0.07 × 0.50 × 0.50 = 1.75¢, ceiled); maker fee **~1¢** (0.0175 × 0.50 × 0.50 = 0.44¢, ceiled). [doc:2026-07-23-prediction-market-strategies:4] The Franck et al. soccer-arb template nets **+1.4% inside the 19.2% of arbitrage-eligible matches** after a 5% commission—far thinner than Kalshi's 2% taker drag at midprice. A passive-MM harvest edge on binary favorites (YES ≥50¢) must clear ~2¢ to break even; any structural edge here is **sub-percent and capacity-constrained** before fees consume it.

### Probe Design

**Three-part paper backtest**, run in sequence:

1. **Does naive YES-longshot flow exist?**  
   Backtest KXBTC15M on 30–60 trading days (2–3 months of history, if available). Track:
   - Fraction of contracts where YES trade above 50¢ midprice (candidate "favorite side").
   - Average midprice at entry vs. settlement (edge direction).
   - Win rate of YES ≥50¢ bets at settlement (oracle ground truth).
   - **Gate:** If win rate ≤52% or trades ≤50% above 50¢, the longshot flow is not present or is noise. Stop.

2. **Net-edge survival after fees:**  
   For the subset of YES ≥50¢ trades, apply Kalshi's 2¢ taker fee in both directions (entry + exit/close). Compute:
   - Average P&L per contract (final price – entry – 2×fee).
   - Win rate net of fees (settlement > entry + 2¢).
   - **Gate:** If net P&L ≤ 0.1¢ median per contract, edge is margin-noise. Stop.

3. **Capacity frontier:**  
   If gates 1–2 pass, run cumulative sizing: start with 10-contract stacks, scale to 50, then 100+. Track:
   - Bid–ask depth at entry (can we scale size without crossing the spread?).
   - Correlation of entry price to settlement (does size drain edge?).
   - Marginal P&L per contract as size grows.
   - **Gate:** If marginal return drops >50% from 10→50 contracts, edge is too shallow for meaningful capital.

**Exact paper probe:** Use `scripts/paper_trade_log.py` or inline backtest simulator (matching `dashboard/sim_python.py` parity rules) on KXBTC15M tick data (if available in weather DB; otherwise fetch Kalshi snapshots retroactively). Log entry–exit–fee–settlement for each trade; report summary stats per gate.

### Testability: Yes, Low Cost

The probe is **fully testable without live capital.** KXBTC15M is a liquid, well-documented Kalshi series (avg volume 1.6M contracts). Historical depth/price data can be backfilled from Kalshi's public API or existing snapshots. The three gates are binary pass/fail, deterministic, and require no external oracle beyond final settlement (known post-close).

**Decision:** Run the paper probe. If gates 1–2 pass, escalate to a small live trial (≤5–10 contracts, tight loss stop at −5¢/contract). Do not size below the capacity frontier identified in gate 3.

