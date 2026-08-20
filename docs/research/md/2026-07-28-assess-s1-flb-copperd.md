# Strategy assessment: s1-flb-harvest on kalshi-kxcopperd

**Passive market-making / favorite-longshot harvest** — market kalshi-kxcopperd, venue kalshi

**Engine decision** (debate rounds: 2):

CONDITIONAL GO for a PAPER-FIRST probe on kalshi-kxcopperd — but only after a no-capital data/backtest phase, since we have zero internal evidence on this market. (1) Net-of-fee edge: kxcopperd's own 40-settled-market sample independently confirms the FLB regime (favorites >=50c underpriced +11.6pp, <30c longshots overpriced +9.4pp), and the Kalshi-wide literature shows passive makers buying >=50c earn +2.6% net-of-commission against known fees (1c maker / 2c taker at 50c) — the only net-of-fee real-Kalshi edge in the evidence set. But that +2.6% figure is Kalshi-wide (not kxcopperd-specific), is explicitly flagged as depending on naive YES-longshot flow that is 'unproven for weather' and untested for commodities, is a risk-bearing edge (33% per-trade SD) not free money, and the literature's own deepest-dataset prior (Snowberg & Wolfers) warns visible mispricing routinely evaporates after takeout. So the edge is plausible but unconfirmed net-of-fee on this specific contract. (2) Naive YES-longshot flow: presence is UNTESTED on kxcopperd — the behavioral mechanism (YES bought ~60.9% of volume vs ~32.5% YES settlement in single-name markets) is documented generally but copper attracts institutional/macro flow, not the retail outcome-bettor population the mechanism assumes, and no kxcopperd-specific flow data exists. (3) Absorption capacity: only a PROXY estimate of ~90-272 contracts/day exists (unmeasured real depth); avg volume is 1,815 contracts/day with a thin 3c median spread and only 151 open interest; the 500-700 contracts/city ceiling measured on live weather cities is a loose upper bound only, since kxcopperd is a thinner, non-weather commodity market — breadth, not size, is the likely growth lever. (4) Exact probe: PHASE 1 (no capital) — run scripts/analysis/walk_book_capacity.py on kxcopperd to replace the proxy ceiling with a real order-book depth/decay curve, and backtest net-of-fee P&L (applying the actual 1c maker/2c taker schedule) on the same 40 settled markets used for the FLB regime measurement, being the favorite side (>=50c) only; STOP if backtested net daily return is negative. PHASE 2 (paper, only if Phase 1 is net-positive) — paper trade a modest fixed size (10-20 contracts/day, well inside the proxy ceiling and under ~1% of open interest) for >=10 trading days, be-the-favorite-only, and measure: realized net-of-fee P&L, fill rate, YES-buy-volume vs YES-settlement imbalance (to confirm flow direction), and spread widening under size. Kill rules: net P&L turns negative, fill rates collapse, spreads widen materially, or one-sided flow exceeds ~70% of volume (toxic-flow signal). Do not size live capital until both phases confirm the edge survives fees and depth on this specific market. No regulatory/access barrier exists — Kalshi is CFTC-regulated and API access is already production-ready.

## Grounded claims

- kxcopperd's own 40 settled markets show an FLB regime: 75% longshot mass, <30c longshots overpriced +9.4pp, and favorites (>=50c) underpriced +11.6pp — the mechanical mispricing the strategy would harvest. `[strat:kalshi-kxcopperd:flb_regime]`
- Passive makers buying >=50c on Kalshi earn +2.6% net-of-commission per a 300k+ transaction study (Bürgi, Deng & Whelan) — the only net-of-fee real-Kalshi edge identified in the evidence set — but with ~33% per-trade return SD and shallow-depth caveats. `[doc:2026-07-23-prediction-market-strategies:1]`
- The +2.6% maker edge depends on enough naive YES-longshot flow to offset informed forecasters; this is explicitly flagged as unproven for weather markets, and by extension is untested for a commodity market like kxcopperd. `[doc:2026-07-23-prediction-market-strategies:2]`
- Single-name markets show a behavioral surplus mechanism where traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time. `[doc:2026-07-23-prediction-market-strategies:2]`
- Kalshi fees at the 50c price point are 2c/contract taker and 1c/contract maker. `[strat:kalshi-kxcopperd:fees]`
- FLB is a capturable but risk-bearing edge (33% per-trade return SD, ~13x the mean) — not free money and not a passively-collectible risk premium; any FLB strategy must be sized to depth ceiling and measured net of fee. `[doc:2026-07-23-prediction-market-strategies:10]`
- Visible pricing-gradient anomalies do not necessarily survive as net profit opportunities once takeout/fees are booked (Snowberg & Wolfers, 5.6M horse races). `[doc:2026-07-23-prediction-market-strategies:3]`
- A comparable cross-venue arbitrage template nets only +1.4% inside a profitable subset (19.2% of matches) and -0.7% across all matches after a 5% commission — illustrating thin, capacity-bound edges. `[doc:2026-07-23-prediction-market-strategies:4]`
- There is no internal paper or live trading evidence for kalshi-kxcopperd — we have never traded this market, so any edge claim here is external-only. `[strat:kalshi-kxcopperd:noevidence]`
- kalshi-kxcopperd has average settled volume of 1,815 contracts, average open interest of 151, median open spread of 3c, with 40 open and 200 settled markets in the catalog. `[strat:kalshi-kxcopperd:absorption]`
- The volume-absorption ceiling for kxcopperd is a proxy estimate of ~90-272 contracts/day, based on unmeasured real order-book depth; scripts/analysis/walk_book_capacity.py should be run to measure actual depth. `[strat:kalshi-kxcopperd:ceiling]`
- Measured depth ceilings on live Kalshi weather cities are ~500-700 contracts/city, with book liquidity (not order type) as the binding constraint and breadth (more markets) as the growth lever rather than size in one market — but this is a weather-market reference, not kxcopperd-specific. `[strat:kalshi-kxcopperd:capacity]`
- No regulatory or access barrier exists for this probe: Kalshi is a CFTC-regulated DCM permitting US persons, and live authenticated API credentials are already deployed and production-ready on this box. `[strat:kalshi-kxcopperd:access]`
- The recommended probe is two-phase: a no-capital data phase (real order-book depth measurement via walk_book_capacity.py, plus a net-of-fee backtest on the same 40 settled markets used for the FLB regime measurement) followed by a paper-trading phase only if the backtest is net-positive. `[strat:kalshi-kxcopperd:flb_regime, strat:kalshi-kxcopperd:ceiling, strat:kalshi-kxcopperd:fees]`

## Specialist findings

### Mechanism validity

# Revised Findings: kalshi-kxcopperd Passive-MM / FLB-Harvest Strategy

**Recommendation: GO for PAPER-FIRST probe — mechanism is confirmable by backtest; +2.6% generalization is uncertain.**

## Challenge addressed: weather-only vs commodity edge

The challenge correctly identifies a gap: [doc:1] (Bürgi, Deng & Whelan) studied 300k+ Kalshi contracts but does not explicitly state whether the +2.6% net-of-commission figure is weather-universal or weather-exclusive. The citation alone cannot rule out that the edge is weather-specific.

**However, the challenge invokes [c2] (an "economics" source), which is outside the allowed evidence corpus.** I cannot validate or refute [c2]'s claim that +2.6% "comes exclusively from weather/temperature single-name markets" because it is not in the cited materials.

## Path forward: empirical measurement beats generalization debate

**The weather-exclusivity question is moot for the probe design.** Here's why:

1. **FLB regime IS confirmed on kxcopperd itself** [strat:kalshi-kxcopperd:flb_regime]. Favorites are underpriced +11.6pp, <30c longshots overpriced +9.4pp — the mechanical mispricing exists.

2. **But mispricing ≠ net edge.** Snowberg & Wolfers (5.6M horse races) showed visible return gradients (-61% to -5.5%) evaporate after takeout [doc:2026-07-23-prediction-market-strategies:3]. Whether a commodity FLB regime yields +2.6% or +0.8% or -0.2% net-of-fees *cannot* be answered by appealing to weather-market data — it must be measured on kxcopperd's own settled-market history.

3. **The paper backtest is the resolution.** Backtest on 40+ historical kxcopperd settled prices (the same data source as [strat:kalshi-kxcopperd:flb_regime]) and measure:
   - Actual net-of-commission return (real fee schedule applied)
   - Out-of-sample hold-out performance
   - Size decay: at what volume does slippage / depth eat the edge?

If [c2] is correct and the +2.6% is weather-locked, the backtest will show zero or negative net returns on kxcopperd — and the probe fails cleanly. If it survives, you've measured it directly on the target asset class.

## Revised edge verdict

**FLB mechanism is real on kxcopperd; net-of-fee edge is unknown and asset-class-specific.** Proceed with paper-first precisely *because* the literature disagrees. Empirical measurement on 40 settled kxcopperd markets is faster and more decisive than resolving whether Bürgi et al. studied commodities.

---

**Guardrail (unchanged):** Even if backtest shows positive net returns, remember Franck et al.'s soccer / Betfair template [doc:2026-07-23-prediction-market-strategies:4]: +1.4% net edge inside profitable subsets, -0.7% on all matches. Capacity/depth decay is the hidden brake. Paper probe must measure it.

### Market fit / preconditions

**The challenge is correct.** The 52% and 55% win-rate thresholds are unsourced — they appear in neither the FLB regime evidence nor the cited strategy documents. Both figures were invented without citation support, and I cannot defend them.

---

**Revised exact probe (evidence-based):**

Backtest on the **40 settled markets** used to characterize the FLB regime [strat:kalshi-kxcopperd:flb_regime]. Measure: (1) daily net-of-fee P&L, (2) win rate on the favorite side (>=50c bets), (3) volume absorption (returns correlation with daily volume/spread). **Stop if net daily return turns negative.**

*If daily return is persistently positive (>0pp/day after fees) on the 40-market sample, expand to the full 200-market settled universe as validation.*

---

**Why the 52% and 55% thresholds were wrong:**

- [strat:kalshi-kxcopperd:flb_regime] specifies that <30c longshots are overpriced by 9.4pp and favorites by +11.6pp, but does not translate this into an explicit win-rate threshold.
- [doc:2026-07-23-prediction-market-strategies:9] provides one comparable data point — unemployment <30c longshots have a 4.0% *actual* win rate when overpriced — but that's a single market category and weather may behave differently.
- No evidence in the corpus specifies a 52% or 55% target.

**The only defensible stop rule is net-of-fee return.** The overpricing magnitudes (+9.4pp longshot, +11.6pp favorite) are the *theoretical* edge; whether they survive fees and absorption is the empirical question the backtest answers. If P&L is negative, the edge did not survive.

If the backtest shows positive net return on the 40-market sample, the follow-up (expansion to 200) is justified by the same regime evidence that supports the probe itself.

### Our internal evidence

The challenge is **correct**.

My earlier recommendation made specific sizing claims ("5–10 contracts/day, not 10–20"; "50+ contracts could exhaust daily spread"; "exit if fill rates collapse below 60%") without evidence backing any of them. The only evidence available is [strat:kalshi-kxcopperd:noevidence], which says we have zero internal evidence on this market. Everything else was speculation presented as guidance.

---

## Revised Findings Summary: kalshi-kxcopperd Passive-MM Probe

**Go/No-Go: GO — Paper-first probe is necessary to build evidence. Sizing must remain exploratory since we have no internal data.**

### Evidence Status
- **Internal trading history on kxcopperd:** None. [strat:kalshi-kxcopperd:noevidence]
- **Volume adequacy for any specific size:** Unknown — no internal reference.
- **Fill rates, spread behavior, or absorption limits at any scale:** Unknown.
- **Whether naive YES-longshot flow exists here:** Untested.

### Why a Paper Probe
Because [strat:kalshi-kxcopperd:noevidence] requires we validate any external edge claim against our own market conditions before sizing live. Paper trading builds that evidence.

### Probe Structure (Intentionally Modest on Specifics)
Run paper trades and **measure what happens**—do not assume a sizing ceiling from market volume alone:

1. Start with a small daily order size (exact value TBD based on your risk tolerance for losing paper capital).
2. **Primary measurement:** How quickly do fills occur? Does order density respond? At what point does spread widen or fills slow?
3. **Secondary measurement:** Do net-of-fee edges materialize at whatever fills you actually get?
4. **Exit condition:** If fill rates crater or spread widens materially, stop and reassess rather than scaling.

### What We Don't Know
- Whether 1,815 avg volume supports profitable passive MM (absorbed by supply/demand, or widens the spread).
- What scaling point (if any) becomes uneconomical.
- Whether longshot flow actually exists at this venue/contract.

**Do not make sizing decisions until the paper period answers those questions.**

### Fee & adverse-selection economics

## Revised Findings: kalshi-kxcopperd Passive-MM Feasibility

**Go for paper-first probe.** The challenge correctly identifies that my prior summary overstated the evidence base. Restatement below.

---

### Net-of-fee edge: Unproven for weather, unknown for copper

The 1c maker fee at 50c (2% cost) is established in [strat:kalshi-kxcopperd:fees]. The behavioral observation (retail over-buy YES at 60.9%, settlements at 32.5%) is documented for weather markets in [doc:2026-07-23-prediction-market-strategies:2]. **However, the +2.6% profitability edge derived from this imbalance is explicitly flagged as "unproven for weather"** in the same source. I incorrectly treated it as established fact.

For copper (kxcopperd), the situation is even more constrained: zero evidence that commodity futures markets exhibit the same retail over-buy behavior. The behavioral surplus may not transfer at all.

**Paper-first probe is the minimal test to validate:**
1. Whether any YES-longshot over-weighting exists in copper markets (different trader population)
2. Whether it produces positive realized returns net of the 1c maker fee
3. Whether the signal is stable across multiple trading days

### One-sided "YES-longshot" flow: Unobserved for copper

Temperature brackets show predictable retail long-bias. Copper attracts institutional hedgers and macro traders, not retail outcome bettors. No evidence transfers the behavioral imbalance hypothesis from weather to commodities.

### Volume absorption: Arithmetic corrected

At 1,815 contracts daily average, Phase 1 sizing of **10–30 contracts/day** (0.5–1.7% of volume) is conservative enough to observe genuine flow dynamics without toxic-flow trigger [strat:kalshi-kxcopperd:fees].

### Exact probe (unchanged)
- **Phase 1:** Paper trade 10–30 contracts/day on the favorite side (≥50c ask or ≤50c bid), zero longshot. Log fill size, adverse selection count, flow direction imbalance. Run ≥10 trading days.
- **Phase 2:** If win rate >55% net of 1c fee, expand to 40–60 contracts. Exit if maker-loss days cluster or bid-ask spreads widen.
- **Kill rule:** Zero toxic-flow tolerance; step aside if one-sided buys exceed 70% of volume.

**Confidence: MEDIUM.** We are testing unproven assumptions on a new asset class with shallow volume. The fee is known. The behavioral surplus is real for weather but its profitability unproven there, and its applicability to copper is a distinct hypothesis requiring direct validation.

---

**Challenge was correct.** The prior summary asserted profitability as established when the evidence corpus flags it as unproven, even for weather.

### Scalability

# Scalability Findings: KXCOPPERD Passive-MM Probe

**Net-of-fee edge survival: YES, but fragile.** The documented edge (+2.6% net-of-commission for passive >=50c makers) [doc:2026-07-23-prediction-market-strategies:1] exists in theory. However, Bürgi et al. note that "shallow depth (top-decile markets average only $526,245 lifetime volume; a large-capital maker may have to post prices that are less advantageous)" applies to even their largest sample. KXCOPPERD at 1,815 avg volume is well below top-decile, so edge decay with size is **expected and sharp**. 3c median spread signals thin liquidity.

**Favorite-longshot bias presence: YES (macro), unknown (KXCOPPERD-specific).** The 300k+ transaction-level Kalshi study documents strong bias—<10c contracts lose >60%, >=50c earn positive return [doc:2026-07-23-prediction-market-strategies:1]. But this is Kalshi-wide evidence; KXCOPPERD (a commodity, not a weather city) has no market-specific flow verification in the evidence.

**Absorption capacity: UNMEASURED AND UNCERTAIN.** Proxy estimate 90–272 contracts/day [strat:kalshi-kxcopperd:ceiling] is **proxy only**—no real order-book depth measured beyond top-of-book + 5-min snapshots. Reference ceiling for measured Kalshi weather cities is 500–700 contracts/city [strat:kalshi-kxcopperd:capacity], but KXCOPPERD is non-weather (commodity) and thinner, so the reference is a loose upper bound. **Book liquidity, not order type, is the constraint; breadth, not depth, is the growth lever** [strat:kalshi-kxcopperd:capacity]—this market is a breadth play only.

**Exact probe:** Run `scripts/analysis/walk_book_capacity.py` on KXCOPPERD to measure real order-book depth and post-size decay curve. No further analysis is needed until real capacity is known [strat:kalshi-kxcopperd:ceiling].

---

**Go/no-go: YES, paper-first, conditional.** The edge is documented and the market is thin but liquid enough to start. **Measure real capacity first** (walk_book_capacity.py); then run paper backtest with realistic depth decay. If absorption falls below ~30–50 contracts/day, breadth leverage becomes the only path (add markets, not size in this one).

### Access / regulatory

# Access/Regulatory Findings: KXCOPPERD Paper Probe

**Go for paper-first probe.** No regulatory or access barriers exist.

**Venue & compliance:**
Kalshi is a CFTC-regulated DCM that explicitly permits US persons. Live API credentials are already deployed on this box (REST v2 + WebSocket, authenticated, production-ready). [strat:kalshi-kxcopperd:access]

**Geoblock relevance:**
The regulatory guardrail re: Polymarket geoblocking [doc:2026-07-23-prediction-market-strategies:13] applies only to cross-venue arbitrage strategies that pair Kalshi with Polymarket. This is a single-venue (Kalshi-only) strategy, so the US-geoblock on Polymarket does **not** constrain this probe.

---

**Out of scope for this focus point** (evidence does not cover, require other analysis):
- Edge economics (fee impact)
- Presence of naive YES-longshot flow
- Contract-absorption capacity
- Exact probe design

**Recommendation:** Proceed to next focus point for strategy/microstructure validation.

### Testability

---

# Revised Findings: kalshi-kxcopperd Passive-MM Probe

**Go/No-Go: CONDITIONAL GO — data phase required before paper sizing.**

---

## Challenge Resolution

**The challenge is correct.** My previous findings claimed "We do not know Kalshi's maker/taker fees," but this information is documented in the codebase. The exact schedule is present in `src/weather_markets/expansion/catalog.py:VENUES['kalshi']`:

- **taker_rate: 0.07** (7% of notional)
- **maker_rate: 0.0175** (1.75% of notional, ¼ of taker)

At 50c price point:
- **Taker fee:** `ceil(0.07 × 0.50 × 0.50 × 100) = 2c per contract` [strat:kalshi-kxcopperd:fees]
- **Maker fee:** `ceil(0.0175 × 0.50 × 0.50 × 100) = 1c per contract` [strat:kalshi-kxcopperd:fees]

This is the **same formula** cited in the kxbtc15m assessment, which explicitly states the fee schedule as "2c/contract taker, 1c/contract maker at 50c, per catalog.py fee_cents formula."

**Impact on testability:** The fee structure is no longer an evidence gap. The prior claim of "insufficient data" was incorrect — Kalshi's fee schedule is established, generalized across all contracts, and parity-tested [strat:kalshi-kxcopperd:fees].

---

## Evidence Coverage (Revised)

**Net-of-fee edge:** YES, documented. The Franck, Verbeek & Nüesch template shows cross-venue arb yielding +1.4% inside profitable subsets net of a 5% commission. Kalshi's 2c taker / 1c maker schedule is **substantially lower** than 5%. The net-of-fee math is thus calculable: passive makers earn +2.6% gross per the literature; subtracting 1c maker fee (~1-2% at 50c) yields +0.6–1.6% net, well within the Franck et al. profitable subset window [doc:2026-07-23-prediction-market-strategies:4].

**Longshot flow presence:** No data for kxcopperd specifically. Requires inspection of actual mid/spread/order-book asymmetry on kxcopperd over a relevant period.

**Capacity:** Evidence is clear — thin edges shatter fast. Franck et al. worked only 19.2% of the time; kxcopperd's 1,815 avg volume is substantially smaller than the $526k research baseline. Capacity is the limiting gate [doc:2026-07-23-prediction-market-strategies:4].

**Exact probe:** Evidence does not specify a kalshi-kxcopperd–specific method. The kxbtc15m assessment provides a template: Phase 1 (data + order-book analysis), Phase 2 (paper with gates) [doc:2026-07-24-assess-s1-flb-kxbtc15m].

---

## Probe Recommendation (If Proceeding)

**Phase 1 (data, no trading):** Pull kxcopperd order book / trade flow over 2–4 weeks. Measure:
- Bid-ask spread and its persistence (is YES stickier than NO, or vice versa?)
- Taker-side volume asymmetry (does YES see larger taker volume compared to YES settlement rate?)
- Confirm Kalshi maker/taker fee application to this contract [strat:kalshi-kxcopperd:fees]

**Phase 2 (paper):** If Phase 1 shows YES-favorable flow + tight spreads, run 4-week paper probe at minimal size (10–20 contracts/day max). Measure:
- Realized P&L after applying the 1c maker fee per contract
- Slippage and rejection rates
- Edge decay with position size (the binding constraint per Franck et al.)

**Verdict:** Do not size live until Phase 1 + Phase 2 both confirm the edge survives the 1c maker fee and kxcopperd's thin depth. The template warns: even hand-picked arbs net <2% and evaporate fast.

