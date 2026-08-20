# Strategy assessment: s1-flb-harvest on kalshi-kxsilverd

**Passive market-making / favorite-longshot harvest** — market kalshi-kxsilverd, venue kalshi

**Engine decision** (debate rounds: 2):

CONDITIONAL GO — run the paper-first probe on kxsilverd, but treat it as a depth-discovery exercise, not a scaling decision. (1) Net-of-fee edge: plausible and directionally confirmed. The internal flb_regime measurement on kxsilverd itself (40 settled markets) shows favorites >=50c underpriced by -12.8pp and <30c longshots overpriced by 8.4pp — the same sign as the external Kalshi-wide finding that passive makers buying >=50c earn +2.6% net-of-commission. But that external edge carries ~33% return SD and was measured on top-decile markets averaging $526k lifetime volume; kxsilverd's 2,447 avg settled volume and 152 avg open interest are far below that, and mispricing has been shown elsewhere not to survive takeout (horse-racing takeout study). We have zero internal P&L history on kxsilverd, so fee-survival here is unproven, not disproven. (2) Naive longshot flow: likely present but not settlement-confirmed for this specific market. The 8.4pp longshot overpricing measured directly on kxsilverd is consistent with the general single-name Kalshi pattern (YES bought ~60.9% of volume, settles YES only ~32.5%). The 'unproven for weather' caveat in the adverse-selection literature is specifically about informed forecasters offsetting behavioral surplus; kxsilverd is being approached as a structural-FLB harvest (not a forecasting play), so that specific caveat is less applicable here, though commodity-specific informed flow (hedgers/specs) is unaddressed by any cited evidence and remains a real unknown. (3) Absorption capacity: unmeasured. Only a proxy ceiling (~122-366 contracts/day) exists from synthetic top-of-book snapshots; true depth has never been walked. The only measured Kalshi depth reference (~500-700 contracts/city) comes from live weather cities, a different market family, so it is context, not a kxsilverd number. Real depth must be measured before any size decision. (4) Exact probe: paper-only, maker-only limit orders on the favorite side (>=50c) exclusively, never taking the longshot side and never crossing the spread; size 10-20 contracts/day, well under the unmeasured proxy ceiling; run scripts/analysis/walk_book_capacity.py against kxsilverd in parallel to replace the proxy ceiling with a real number; duration >=3-4 weeks / ~15-20 settled cycles (a handful of cycles is not enough draws against a 33% SD); instrument net-of-fee P&L (1c maker fee), fill rate, realized counterparty flow composition (confirm <30c longshot buy pressure is actually landing), and contracts absorbed/day before the favorite-side underpricing compresses. Kill the probe on cumulative negative net-of-fee P&L after the minimum sample, on persistent one-sided flow against the maker quote (size down/step aside per venue fee guidance), or if measured depth comes in below roughly 50-100 contracts/day. Only advance past paper to live sizing if net-of-fee return is positive and consistent with the -12.8pp/+2.6% signal, within the measured (not proxy) absorption ceiling. Regulatory/access is not a blocker: Kalshi is a CFTC-regulated DCM with existing production API keys covering this single-venue strategy.

## Grounded claims

- Internal measurement across 40 settled kxsilverd markets shows FLB is present: 40% of volume mass is priced <30c and overpriced by 8.4pp, while favorites (>=50c) are underpriced by -12.8pp. `[strat:kalshi-kxsilverd:flb_regime]`
- Kalshi-wide, passive makers buying >=50c contracts earn +2.6% net-of-commission per contract, but the edge carries ~33% return SD and top-decile markets average only $526,245 lifetime volume, so it survives only at small size. `[doc:2026-07-23-prediction-market-strategies:1]`
- kxsilverd fee schedule is 1c maker / 2c taker at 50c; single-name temperature/event bracket markets carry adverse selection (~33% per-trade return SD), and one-sided order flow predicts maker losses. `[strat:kalshi-kxsilverd:fees]`
- The deepest empirical dataset in the literature (5.6M horse-race starts) found no profit from simple betting strategies once takeout is booked, despite a visible favorite-longshot calibration gap — mispricing does not automatically imply net edge. `[doc:2026-07-23-prediction-market-strategies:3]`
- Capturing FLB by being the favorite side is a risk-bearing edge (33% SD), not free/passive money, and must be sized to the depth ceiling and measured net of fee. `[doc:2026-07-23-prediction-market-strategies:10]`
- kxsilverd averages 2,447 settled-contract volume, 152 average open interest, and a 2c median open spread, across a catalog of 40 open and 200 settled markets. `[strat:kalshi-kxsilverd:absorption]`
- No internal paper or live trading history exists for kxsilverd — any edge claim is currently external-only, and a data probe should precede sizing. `[strat:kalshi-kxsilverd:noevidence]`
- The kxsilverd scale ceiling of ~122-366 contracts/day is a proxy from synthetic top-of-book snapshots; real order-book depth is unmeasured and requires running scripts/analysis/walk_book_capacity.py. `[strat:kalshi-kxsilverd:ceiling]`
- Measured (non-proxy) Kalshi depth ceilings run ~500-700 contracts/city on live weather cities, with book liquidity as the binding constraint and breadth rather than per-market size as the scaling lever; this reference is from weather markets, not kxsilverd. `[strat:kalshi-kxsilverd:capacity]`
- Across single-name Kalshi markets generally, traders buy YES ~60.9% of volume but those markets settle YES only ~32.5% of the time, a structural naive-longshot pattern the maker edge depends on; this is flagged as unproven specifically for weather due to informed-forecaster counterparties. `[doc:2026-07-23-prediction-market-strategies:2]`
- The edge that travels to liquid markets without a proprietary forecasting model is structural FLB, not forecasting skill — relevant to approaching kxsilverd as a structural-harvest play rather than a directional-forecast play. `[doc:2026-07-23-prediction-market-strategies:12]`
- Kalshi is a CFTC-regulated designated contract market on which US persons may trade, with production API keys (REST v2 + WebSocket) already available on this box. `[strat:kalshi-kxsilverd:access]`

## Specialist findings

### Mechanism validity

Looking at your evidence list, the challenge is **incorrect based on the sources provided**.

## Analysis of the "33% return SD" attribution

**My original finding correctly cited [c1]:**
In my summary, I wrote: "the edge carries **33% return SD** (not passive income)... [c1]"

[c1] is [doc:2026-07-23-prediction-market-strategies:1], which explicitly attributes "33% return SD" to the **external Bürgi, Deng & Whelan study** across 300k+ Kalshi contracts:

> "**Passive makers buying >=50c earn +2.6% after commission** (per-contract, high-price side only)... **But 33% return SD (~13x the mean)**"

**The internal kxsilverd evidence does NOT provide a return SD:**
[strat:kalshi-kxsilverd:flb_regime], the only internal kxsilverd source in the evidence list, reports:
- 40% of volume priced <30c
- <30c longshots overpriced by 8.4pp
- Favorites underpriced by -12.8pp

It contains **zero mention of "33% return SD"** or any volatility metric.

## The discrepancy

The challenge cites **[strat:kalshi-kxsilverd:fees]**, but this source is **not in the evidence list provided**. Either:
1. This source exists but wasn't included in the evidence I'm allowed to use, or
2. The challenge refers to evidence that contradicts what I see in [strat:kalshi-kxsilverd:flb_regime]

If [strat:kalshi-kxsilverd:fees] exists and claims "~33% return SD" for kxsilverd specifically, then **the challenge is valid** — a single statistic cannot origin from both the external Kalshi-wide study AND a single-market internal dataset without one misattributing. But I cannot verify this against the evidence provided.

**Request:** Provide the full [strat:kalshi-kxsilverd:fees] source (or clarify if it's the same as [strat:kalshi-kxsilverd:flb_regime]) so I can assess whether one report has indeed misattributed the SD figure.

### Market fit / preconditions

**Challenge is incorrectly stated.** The evidence provided explicitly includes [strat:kalshi-kxsilverd:flb_regime], which contains the internal kxsilverd data I cited. There is no contradiction.

---

## Response to Challenge

The evidence base provided includes [strat:kalshi-kxsilverd:flb_regime] (source=flb_regime, ref=flb_regime table (scripts/analysis/flb_regime.py)). This is a direct measurement of kxsilverd FLB regime statistics derived from **40 settled markets**:

- Longshot mass: 40% (share priced <30c)
- <30c longshots: **OVERPRICED by 8.4pp** (harvestable)
- Favorites ≥50c: underpriced by -12.8pp

This data source exists, is cited correctly, and is the only empirical evidence available for kxsilverd FLB regime assessment. The reference to "flb_regime table (scripts/analysis/flb_regime.py)" is a direct pointer to an internal computation, not an external claim.

The challenge's assertion that the evidence "claims no internal kxsilverd data exists" does not appear in the evidence list provided (the only sources I may use). [strat:kalshi-kxsilverd:flb_regime] **is** internal kxsilverd data, properly sourced.

**Conclusion unchanged:** GO for PAPER-FIRST probe. The regime evidence is sound.

### Our internal evidence

Let me request that permission:

Based on my investigation, **the challenge is correct — there is a fundamental contradiction in the cited evidence tags.**

## Revised Findings Summary

**Finding: The contradiction is real, and internal data likely exists but is unlabeled or not integrated into the claim-citation pipeline.**

### What I verified does NOT exist in the repo:

1. **No kxsilverd references** anywhere in `/docs/research/md/`, `/docs/strategies/`, `/docs/expansion/`.
2. **No grep matches** for "silver", "SILVER", "8.4pp", "2,447", or the specific figures cited in the challenge (40% volume <30c, -12.8pp favorite underpricing, 122–366 contracts/day ceiling, 1c/2c fee schedule).
3. **The fast-market research (2026-07-27)** mentions kxbtc15m, kxbtcmaxmon, kxwtiw (crypto contracts), but **no silver contracts**.
4. **The BTC assessment (2026-07-24-assess-s1-flb-kxbtc15m.md)** uses the same FLB strategy framework but does not cite kxsilverd as a comparable case.

### Diagnosis:

The cited tags (`[strat:kalshi-kxsilverd:flb_regime]`, `[strat:kalshi-kxsilverd:absorption]`, etc.) follow the citation format of my earlier evidence system but **the data they reference does not exist in accessible form** in the repo. Either:

1. **The data was generated but not committed** (e.g., a paper-trade log, a market-scan output, or a notebook-generated analysis not yet in docs/).
2. **The tags were asserted in conversation without being grounded in a written record** (retroactive citation without a source doc).
3. **The data lives in the database** (e.g., `paper_trades` table has kxsilverd entries, or a live Kalshi API scan captured the quoted figures) but was never extracted to a research document.

### Revised Recommendation:

**GO for paper-first probe — but with an explicit precondition:**

The challenge correctly points out that we **cannot determine whether internal evidence exists without checking the database and unpublished analysis outputs**. The recommendation changes from:

- **OLD:** "zero internal evidence → external edge only → must probe"

To:

- **REVISED:** "Internal evidence status unknown pending DB/unpublished-output audit → if evidence exists, cite it; if not, probe with high confidence (the structure is sound). If evidence does exist and contradicts the zero-internal claim, integrate it into the sizing decision."

**Exact revised probe remains unchanged** (3+ trading cycles, measure fill rate, net fees, flow imbalance, absorption ceiling), but the finding should read:

---

## Revised Finding: kalshi-kxsilverd — Evidence Status Unclear

**Finding:** Evidence status for kalshi-kxsilverd is contradictory. The claim "[strat:kalshi-kxsilverd:noevidence]" (zero internal paper/live history) conflicts with detailed tags in the challenge ([strat:kalshi-kxsilverd:flb_regime], [strat:kalshi-kxsilverd:absorption], etc.) that cite specific microstructure facts (40% volume <30c, 8.4pp overpricing, 2,447 avg volume, 122–366 contracts/day ceiling). **The specific figures are not present in committed research docs or grep-accessible code; they either exist in the database or in unpublished work.**

**Resolution required:**
1. Audit the `weather` database (`paper_trades`, `kalshi_*` tables) for any kxsilverd trading history or scan output.
2. Check `/tmp`, script logs, or recent NotebookLM artifacts for unpublished kxsilverd analysis.
3. If internal evidence is found: integrate it, cite it formally, and revise the absorption/capacity gates based on measured data.
4. If no internal evidence is found: the cited tags are unverified assertions; proceed with paper-first probe as originally stated.

**Until resolved: GO for paper-first probe**, with the explicit understanding that capacity gates and flow models may need revision if internal evidence surfaces. The strategy mechanism (FLB, passive-MM, net-of-fee edge on >=50c) is sound; the market-specific unknowns (depth, flow pattern, absorption) remain unchanged regardless of whether internal evidence exists.

---

**This is the only intellectually honest answer the evidence allows.** I cannot cite data I cannot find, and I cannot deny data the challenge claims exists without auditing the database.

### Fee & adverse-selection economics

## Revised Finding: Challenge is Valid

The challenge is **correct**. I misapplied weather-specific adverse-selection evidence to a commodity market.

**The error:**

[strat:kalshi-kxsilverd:fees] and [doc:2026-07-23-prediction-market-strategies:2] both explicitly describe adverse selection in **temperature/event brackets**, not commodities:

- [strat:kalshi-kxsilverd:fees]: "Single-name **temperature/event brackets** carry adverse selection (~33% per-trade return SD)"
- [doc:2026-07-23-prediction-market-strategies:2]: "**A city's temperature bracket IS a single-name market**" — framing it as the high-adverse-selection segment. Critically, the same source notes this pattern is "**unproven for weather**" itself.

kxsilverd is a **silver commodity market**, not a temperature bracket. Commodity markets attract hedgers and specs; weather brackets attract retail YES-bias. The behavioral surplus mechanism (naive YES-longshot flow) is not proven to exist in commodities, so I cannot cite the 33% figure as evidence against kxsilverd's edge.

---

## Revised Recommendation: CONDITIONAL PAPER PROBE

**Decision:** **Upgrade to PAPER-FIRST**, with strict commodity-specific success criteria.

**Rationale:**
The fee structure (1c maker / 2c taker per [strat:kalshi-kxsilverd:fees]) favors makers generally. Without commodity adverse-selection data, I cannot claim the edge is insufficient. The question is empirical: does passive MM on the tight-spread side generate positive Sharpe in a commodity single-name?

**Exact probe:**
- **Duration:** ≥30 days (multi-regime: trending, mean-reverting, vol spikes)
- **Rule:** Limit-order passive MM on the **tight-spread side only** (not directional betting on "favorite")
- **Size:** 10–20 contracts/day
- **Exit criterion:** Negative Sharpe OR persistent spread widening = refuted
- **Success bar:** After-fee Sharpe >1.0 *or* profit factor >1.3

**What success means:** Passive MM is viable in *commodity* single-names. **Not** proof of weather-bracket edge; distinct microstructure.

**On citations:** Evidence :5 and :8 (law-of-one-price violations; Fed macro efficiency) are not relevant to this probe. Removed.

### Scalability

The challenge is **correct**. My findings conflated proxy measurements with real evidence about KXSILVERD, violating the citation rules.

---

## Revised findings

**Go/No-Go:** **CONDITIONAL GO** — paper-test, but with immediate depth measurement as prerequisite.

### Edge survival at this market

The +2.6% net-of-fee edge is validated for Kalshi >=50c contracts broadly [doc:2026-07-23-prediction-market-strategies:1], but that study's top-decile markets average only $526k lifetime volume. KXSILVERD's 2,447 avg settled volume [strat:kalshi-kxsilverd:absorption] is well below top-decile, and the doc explicitly warns: "shallow depth means a large-capital maker may have to post prices that are less advantageous" [doc:2026-07-23-prediction-market-strategies:1]. **Edge persistence at KXSILVERD scale is untested** — the prior work did not isolate sub-top-decile markets.

### Absorption capacity (unmeasured)

The evidence explicitly states "**no internal data** — probe before sizing" for KXSILVERD [strat:kalshi-kxsilverd:ceiling]. The ~122–366 contracts/day proxy is **unmeasured** (only synthetic depth and top-of-book snapshots exist). The 500–700 contracts/city reference [strat:kalshi-kxsilverd:capacity] comes from **measured depths on live weather cities** — a different market set, not KXSILVERD. **Real KXSILVERD order-book depth is unknown.**

### Scaling path constraint

The evidence confirms "breadth, not size, is the growth lever" [strat:kalshi-kxsilverd:capacity], but KXSILVERD's own depth is unmeasured.

---

## Exact probe

1. **Prerequisite:** Run `scripts/analysis/walk_book_capacity.py` on KXSILVERD to measure real order-book depth (no proxy).
2. **Paper-trade test:** 50–100 contract/day entry sizes; monitor realized edge, bid-ask slippage, and fill frequency.
3. **Go/no-go decision:** If measured depth supports >100 contracts without >30% edge decay, advance to scaling study. If depth <50 contracts or edge <1.5% realized, reject.

**The only missing piece is real depth data for KXSILVERD itself** — the proxy and weather-city references do not apply directly.

### Access / regulatory

# Access / Regulatory Assessment: Kalshi KXSILVERD Passive MM

**GO for regulatory/access — this is not a blocker.**

## Findings

**Venue access & US-person trading:** KXSILVERD is live on Kalshi, a CFTC-regulated DCM that explicitly permits US-person trading [strat:kalshi-kxsilverd:access]. You have production API keys on this box already.

**API coverage:** Full REST v2 + WebSocket authentication [strat:kalshi-kxsilverd:access] — sufficient for order placement, cancellation, fills, and live orderbook streaming needed for passive MM.

**Geoblock/cross-venue risk:** Not applicable here. This is a **single-venue strategy (Kalshi-only)**, not a cross-venue arbitrage. The guardrail against geoblocked Polymarket [doc:2026-07-23-prediction-market-strategies:13] does not constrain a Kalshi-native strategy.

## Out of Scope (Regulatory Cleared)

The remaining questions — edge survival after fees, longshot flow detection, contract-absorption capacity, and probe design — are strategy/backtest questions, not regulatory/access ones. They belong to the strategy and execution focus points.

**Decision:** Proceed to backtest phase. Regulatory/access is cleared.

### Testability

You're right on both counts. Let me revise with evidence discipline.

## Challenge Resolution

The original findings contradict themselves and misframe the question:

1. **Evidence contradiction:** I correctly cited `[strat:kalshi-kxsilverd:noevidence]` (zero internal history), then implicitly acted as if substantial internal evidence existed (detailed flb_regime / capacity numbers). The evidence statement I was given lists only two sources; those detailed metrics do not appear in either. I should not have included analysis of capacity/ceiling/fees without citing where those came from.

2. **Question reframe:** The question explicitly asks to "Decide go/no-go for a **PAPER-FIRST probe**." I answered "backtest first, paper only if backtest clears" — a different sequencing proposal that doesn't address the actual decision asked for.

---

## Revised Finding: kalshi-kxsilverd Favorite-Longshot-Harvest Probe

**Go / No-Go Decision on Paper-First Probe: Conditional Go — if liquidity and feed stability support live testing.**

### What the evidence actually says

- **Internal evidence:** `[strat:kalshi-kxsilverd:noevidence]` — we have never traded kxsilverd. This is a cold-start probe.
- **Commission risk template:** `[doc:2026-07-23-prediction-market-strategies:4]` — passive two-sided strategies collapse under commission. Soccer example: +19.2% win rate → −0.7% net overall. **For a single-venue passive favorite-harvest on Kalshi, commissions will likely dominate.**

### Paper probe go/no-go

**Go, with constraints:**
- Kalshi's feed stability and order-flow observability must support real-time fill detection (can we reliably see longshot volume?).
- **Pass/fail bar:** Positive P&L net of Kalshi fees in the first 2 weeks; if negative, kill it.
- Start small (10–20 contracts/day) to answer: (1) does live flow actually skew longshot? (2) does edge survive their fee structure?

**No-go only if:** feed/fill latency is too high for passive MM, or Kalshi's liquidity on kxsilverd drops below 500 contracts/day during paper period.

### Exact probe

- Duration: 2–4 weeks, live Kalshi feeds, passive limit orders on favorite side only.
- Measure: P&L after taker fees, fill rate, mid-price movement against position.
- Stop rule: Exit if cumulative loss exceeds 2% of probe capital, or if 10 consecutive days show zero edge.

---

**Summary:** The evidence warns that thin edges vanish under commission. A paper-first probe is justified to answer whether this edge survives Kalshi's fee load *before* sizing live; it is not justified *instead of* backtest, but as a reality-check after data review shows the hypothesis is plausible.

