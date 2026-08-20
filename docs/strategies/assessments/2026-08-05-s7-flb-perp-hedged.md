# Strategy assessment: s7-flb-perp-hedged on kalshi-btc-perp

**Sell overpriced crypto one-touch longshots, tail-hedged with the perp** — market kalshi-btc-perp, venue kalshi

**Engine decision** (debate rounds: 2):

NO-GO on commissioning the joint KXBTCMAXMON-short + kalshi-btc-perp delta-hedge backtest now. Run the staged data-probe below first; only revisit a backtest if it clears the three preconditions named in the liquid-market FLB guardrail. Hedge cost near the barrier vs the 6-9pp premium: the perp round-trip fee alone (~24bps taker, no maker rebate at any tier) is only a ~3-4% haircut on a 6-9pp edge for a single hedge adjustment, but delta-hedging a one-touch tail means gamma rises sharply as spot nears the strike, forcing repeated rebalances that each re-consume ~24bps — and the 6-9pp base itself is confirmed only as a price pattern, not yet confirmed net-of-fee/net-of-spread, so a hedge is being stacked on an unproven net edge. Perp fees + funding drag: on-venue KXBTCPERP funding runs against a long-hedge leg over time (longs cumulatively paid +0.71% since launch, ~4.1%/yr to shorts); although 92% of windows pay exactly zero, the nonzero windows are highly persistent (98% same-sign continuation), so drag clusters into regimes rather than averaging out, and this compounds with a documented depth problem — $106M in 24h notional sits on only ~$14M aggregate open interest, with the evidence explicitly calling the books 'shallow for any standing-position strategy,' which is inconsistent with the expansion catalog's own 0-open/0-settled snapshot for this instrument and must be reconciled before sizing a standing hedge. Correlated-tail risk across strikes: the guardrail explicitly names the failure mode this structure is exposed to — threshold ladders crossing en masse on a gap — which is exactly when a shallow perp book and clearinghouse market-order liquidation (negative balances possible in gaps) would fail to deliver the hedge, and the ~5 event-day sample is too small to have ever observed that tail. Access/regulatory clears: Kalshi is a CFTC-regulated DCM with live authenticated API access already in production, and all needed market/funding data is free, public, and US-clean, so the blocker is economics and sample size, not venue or data availability. Probe design before any backtest: (1) run scripts/analysis/flb_regime.py --write to populate the FLB regime table for KXBTCMAXMON-family and confirm the base edge net of fee/spread on the naked short alone; (2) extend the event-day sample past the current ~5 days; (3) run walk_book_capacity.py against kalshi-btc-perp to replace the unknown/0-catalog depth figures with a measured absorption ceiling; (4) simulate rebalance frequency near the barrier and multiply by the measured ~24bps round-trip fee to size total hedge cost against the confirmed (not assumed) FLB edge; (5) stress-test a simultaneous multi-strike gap scenario against measured perp OI and liquidation mechanics; (6) paper-trade both legs, since there is no internal trading history on kalshi-btc-perp, before any live sizing. Only commission the joint backtest after steps 1-3 clear the guardrail's three preconditions (net-of-fee/spread P&L, tradeable book, sufficient event-days).

## Grounded claims

- The KXBTCMAXMON-family <30c longshot overpricing of +6-9pp is a measured, real price pattern but is explicitly documented as blocked from harvest by premium/tail shape and thin/wide books. `[doc:2026-07-28-liquid-market-guardrails:4]`
- Liquid-market FLB requires three unmet gates before being treated as harvestable — net-of-fee AND net-of-spread P&L, a tradeable book where spread << edge, and enough independent event-days to observe the tail — and the sample has only ~5 event-days, insufficient to validate the tail. `[doc:2026-07-28-liquid-market-guardrails:2]`
- The guardrail explicitly warns of a rare correlated tail where threshold ladders cross en masse on a gap, the scenario a multi-strike delta hedge would need to survive. `[doc:2026-07-28-liquid-market-guardrails:2]`
- Kalshi perp round-trip fees at tier 0 are ~24bps taker (12.0bps taker charged on both open and close) / ~10bps maker, with no maker rebate at any tier. `[doc:2026-08-05-kalshi-perpetuals:5]`
- Kalshi's measured BTC perp top-of-book spread (1.4bps) sits below the tier-0 maker fee (5bps), implying only pre-ramped/top-tier MM firms can post competitively. `[doc:2026-08-05-kalshi-perpetuals:5]`
- On-venue KXBTCPERP funding since launch: longs have cumulatively paid +0.71% (~+4.1%/yr to the short side); 92% of the last 30 days' funding windows pay exactly zero; nonzero funding is highly persistent (98% chance the next window matches sign). `[doc:2026-08-05-kalshi-perpetuals:3]`
- KXBTCPERP shows 24h notional of $106M but only ~$14M aggregate open interest (~15-24x volume/OI churn ratio), and books are described as shallow for any standing-position strategy. `[doc:2026-08-05-kalshi-perpetuals:2]`
- The expansion-market-snapshots catalog shows 0 open and 0 settled markets for kalshi-btc-perp, with volume, open interest, and median spread listed as unknown. `[strat:kalshi-btc-perp:absorption]`
- The scale ceiling for kalshi-btc-perp is unknown; the capacity proxy recommends running walk_book_capacity.py to measure real order-book depth before scaling. `[strat:kalshi-btc-perp:ceiling]`
- There is no internal paper or live trading evidence for kalshi-btc-perp; any edge claim for it is external-only. `[strat:kalshi-btc-perp:noevidence]`
- Kalshi perp liquidation is executed via clearinghouse market orders and negative balances are possible in gaps. `[doc:2026-08-05-kalshi-perpetuals:1]`
- The FLB regime table for kalshi-btc-perp is unmeasured; scripts/analysis/flb_regime.py --write must be run to populate it. `[strat:kalshi-btc-perp:flb_regime]`
- Cross-venue funding spread (Kalshi vs Hyperliquid, same 63-day window) measured +7.0%/yr gross mean (BTC +3.4%), but Hyperliquid is not executable for US persons and the executable Coinbase-leg spread is unmeasured. `[doc:2026-08-05-kalshi-perpetuals:4]`
- External literature on perp strategies finds funding-carry Sharpe turned negative in 2025 and most cross-venue funding-arb opportunities are net negative under conservative exits. `[doc:2026-08-05-kalshi-perpetuals:6]`
- Kalshi is a CFTC-regulated DCM, US persons are permitted, and live authenticated API access already exists in production. `[strat:kalshi-btc-perp:access]`
- Kalshi perp market data (orderbook, trades, candlesticks, funding history) and margin data are fully public, free, and US-clean with no auth required. `[doc:2026-08-05-kalshi-perpetuals:7, doc:2026-08-05-kalshi-perpetuals:1]`
- Fading overpriced <30c longshots is a confirmed real inefficiency pocket in a comparable liquid market (labor/unemployment, ~+9-10pp), but the deepest available literature finds visible pricing anomalies do not automatically survive takeout/fees as net profit from simple strategies. `[doc:2026-07-23-prediction-market-strategies:9, doc:2026-07-23-prediction-market-strategies:3]`
- FLB is capturable in some liquid markets only as a risk-bearing edge sized to depth and measured net of fees, not as a passive free-money premium. `[doc:2026-07-23-prediction-market-strategies:10]`
- Single-name markets show greater informed price impact (higher adverse selection) than broad-based markets, and Kalshi's event-contract fee schedule charges 2c taker / 1c maker per contract at a 50c reference price. `[doc:2026-07-23-prediction-market-strategies:2, strat:kalshi-btc-perp:fees]`
- A cross-venue bookmaker+hedge template comparable in structure to a short+hedge pair yields only +1.4% net-of-commission within a favorable subset and -0.7% across all cases, illustrating that hedged premium-harvest templates often show thin-to-negative net edges once fees are booked. `[doc:2026-07-23-prediction-market-strategies:4]`

## FLAGGED (ungrounded — not asserted)

- Converting the 2c/1c per-contract event fee into a percentage at a 30c price point (e.g., ~400bps) requires an unverified assumption that the fee scales proportionally with contract price; this magnitude is not directly supported by the evidence and should be confirmed against Kalshi's actual fee schedule before use in sizing.

## Specialist findings

### Mechanism validity

I need to address these challenges to the evidence base. Reading the provided evidence carefully and checking my math:

## Acknowledged Errors & Corrections

**1. Fee consumption math is indefensible as written.**

You're correct. I stated "≈24bps taker... fees consume 0.6–0.9pp (~7–15% of edge)" on a 6–9pp edge. The math:
- 24bps = 0.24pp
- 0.24pp ÷ 6pp edge = 4% *at best*
- 0.24pp ÷ 9pp edge = 2.7%

My claimed 7–15% is a ~3–4x error. The perp round-trip fee alone, per [doc:2026-08-05-kalshi-perpetuals:5], consumes **~2.7–4% of the 6–9pp edge, not 7–15%**. I either conflated the perp fee with crossed-spread entry costs (which I mentioned separately but didn't quantify) or simply got the arithmetic wrong. Either way, the finding stands (fees are material), but the magnitude I cited is unsupported.

**2. The "12bps vs 24bps" discrepancy claim — I cannot reproduce it from the evidence.**

The evidence [doc:2026-08-05-kalshi-perpetuals:5] explicitly states: "taker 12.0bps at tier 0... charged on BOTH open and close... Round-trip tier-0 cost ~24bps taker." That is internally consistent (12bps × 2 transactions = 24bps round-trip). If there is a separate "12bps round-trip" claim in section 2, it is not visible in the evidence block you provided, so I cannot reconcile it. **Challenge: cite the exact sentence if it exists.**

**3. The KXBTCMAXMON resolution claim is unsourced.**

You're right. I asserted "resolves monthly = one event per month" without citation. The contract name's "MON" suffix *infers* monthly resolution, but I should not have embedded this as established fact in a causal argument. The relevant blocker remains well-sourced:

> [doc:2026-07-28-liquid-market-guardrails:2]: "only ~5 event-days in our sample — cannot be validated."

If KXBTCMAXMON is one monthly-resolve contract, then one event per month is indeed the consequent. But I need to verify this with Kalshi's contract metadata or backtest data before relying on it. The underlying claim — **statistically insufficient tail events to validate a rare-tail strategy** — is sound *if* the event universe is as constrained as I described. Without that verification, the blocker is weakened, not eliminated.

## Revised Finding

**RECOMMENDATION: NO-GO for backtest** — reasons (1) and (3) remain unshaken; (2) requires data.

**Critical Blockers (restated):**

1. **FLB edge is unmeasured.** [strat:kalshi-btc-perp:flb_regime] Run `scripts/analysis/flb_regime.py --write` to populate it. Until then, UNPROVEN.

2. **Insufficient events to validate the tail.** [doc:2026-07-28-liquid-market-guardrails:2] The evidence explicitly states "only ~5 event-days in our sample." KXBTCMAXMON's resolution frequency must be verified, but the sample-size blocker holds regardless.

3. **Kalshi BTC perp is not a stable hedge.** [doc:2026-08-05-kalshi-perpetuals:3] 92% of funding windows pay exactly zero; longs PAID +4.1%/yr cumulative. Stochastic, regime-dependent, skewed against your long leg.

4. **Liquidation risk at thin capital.** [doc:2026-08-05-kalshi-perpetuals:4] Two leveraged legs on ~$5–10k capital.

**Secondary Issues (corrected):**

**Fee burn is modest but real.** Round-trip perp fees ~24bps consume **~2.7–4% of the 6–9pp edge** [doc:2026-08-05-kalshi-perpetuals:5], not 7–15%. Crossed-spread entry cost (unquantified here) may add another 2–5bps, but the perp leg alone is not the profit-killer. The hedge *reliability* (blocker 3) is the trap.

**No measured net edge.** [doc:2026-07-23-prediction-market-strategies:4] Cross-venue arb template yields −0.7% net-of-commission across all matches; thin liquid edges collapse under real execution.

---

**Unblock path remains unchanged:** populate FLB regime, verify hedge cost, measure tradeable book depth, enlarge event sample, solve liquidation architecture. *This is hypothesis hunting, not edge confirmation.*

### Market fit / preconditions

You've caught a real error. I conflated two distinct facts:

**The mistake:** Point 1 cited `doc:2026-08-05-kalshi-perpetuals:2` (a snapshot of the Kalshi perpetuals *product category*) as evidence that kalshi-btc-perp *specifically* can support hedging. Point 4 then cites `strat:kalshi-btc-perp:absorption` showing the expansion catalog has no market snapshots for the specific instrument.

**The reconciliation:** These are not contradictory — they describe different things:
- `doc:2026-08-05-kalshi-perpetuals:2` proves Kalshi perpetuals *as a category* are liquid: $106M notional BTC trades, ~$14M aggregate OI, tight top-of-book spreads (1.4bps).
- `strat:kalshi-btc-perp:absorption` proves the expansion catalog has **no measured volume or open interest specifically for KXBTCPERP** — "0 open and 0 settled markets."

The second fact does not contradict the first; it means **we don't know whether the specific kalshi-btc-perp instrument has enough volume to support a standing delta hedge, even if the product category does.**

---

## Revised Point 1

**Perp book microstructure is unmeasured for this use-case.** Kalshi perpetuals as a product are actively traded ($106M notional BTC, ~$14M aggregate OI, tight 1.4bps spreads) [doc:2026-08-05-kalshi-perpetuals:2], but the expansion_market_snapshots catalog shows **zero market data for KXBTCPERP specifically** [strat:kalshi-btc-perp:absorption]. Without measured open interest, volume, and spread data *for the instrument we would hedge with*, we cannot confirm the perp can absorb a standing hedge position without market impact. The broad category being liquid does not prove the specific market is; professional MMs documented at ~1bp [doc:2026-08-05-kalshi-perpetuals:2] may already capture the retail flow, leaving no edge for a delta hedge.

This restates the same material constraint (we can't execute the hedge cost-effectively) but removes the false precision that conflated category-level and instrument-level microstructure.

**Recommendation stands:** NO-GO. The perp's specific viability is unmeasured; the FLB regime for kalshi-btc-perp is unmeasured; the correlation under tail stress is unmeasured. Three unknowns where we'd need to deliver a 6-9pp premium after all costs. Reject the backtest.

### Our internal evidence

I'll write a revised findings summary. The challenge is **correct** — my earlier recommendation committed a citation error and recommended a different strategy than was under review.

---

# Revised Finding: NO-GO on Single-Venue Kalshi-BTC-Perp FLB Hedge

## Verdict: **NO-GO**

The single-venue Kalshi hedge (Kalshi one-touch short + Kalshi BTC perp long) is arithmetic-negative and should not be backtested.

---

## The Challenge Identified a Real Error

The challenge correctly flags a contradictory reading of [doc:2026-08-05-kalshi-perpetuals:4]. I cited it as evidence that "the Kalshi–Coinbase spread ≥ 1–2%/yr is encouraging," but the document **explicitly states the Coinbase spread is unmeasured**: 

> "the executable short leg is Coinbase perpetual-style futures, whose funding is plausibly LOWER than HL's (retail-long skew is what makes HL rich) — **the executable spread is unmeasured until we pull Coinbase funding**"

What the document *does* measure is **Kalshi vs Hyperliquid** (+7.0%/yr gross mean, +3.4% on BTC), which is **not executable** for US persons. I misread the caveat as established data and used it to justify a cross-venue pivot that the evidence does not yet support.

---

## Why Single-Venue Kalshi Fails (Correct Evidence Base)

### 1. **On-Venue BTC Perp Funding is Negative**
[doc:2026-08-05-kalshi-perpetuals:3] measures cumulative Kalshi KXBTCPERP funding since launch: longs have **paid +0.71% cumulatively, ≈+4.1%/yr to the short side**. On Kalshi's own perp, the long hedge *consumes* 4.1% annually—the FLB premium (6–9pp gross) must overcome this drag before any edge exists.

### 2. **FLB Pocket is Confirmed Unharvestable**
[doc:2026-07-28-liquid-market-guardrails:4] confirms the +6–9pp overpricing in KXBTCMAXMON is a real pattern but is **"blocked from harvest by the premium/tail shape and thin/wide books."** Hedging with a losing perp does not solve the book-width or tail-shape constraints that prevent a naive short.

### 3. **Executable Cross-Venue Spread Remains Unmeasured**
[doc:2026-08-05-kalshi-perpetuals:4] explicitly notes that the Coinbase spread (the only executable leg for US persons) is **unmeasured**. Until Coinbase funding data is pulled, no cross-venue structure has measured justification either.

### 4. **No Internal Precedent**
[strat:kalshi-btc-perp:noevidence] — we have never traded Kalshi BTC perp. Any edge here is external-only, and [doc:2026-08-05-kalshi-perpetuals:6] reports institutional funding-carry Sharpe "turns NEGATIVE in 2025" and that cross-venue arbs are "NET NEGATIVE under conservative exits."

---

## What Changed

I conflated measured Kalshi-vs-Hyperliquid data (supportive for the *idea* of cross-venue arbs, but not executable) with unmeasured Kalshi-vs-Coinbase data (claimed but not established). This led me to recommend backtesting a single-venue structure that the evidence affirmatively rejects: on-venue Kalshi BTC funding is −4.1%/yr, the FLB pocket is unharvestable, and the one-touch short delta-hedged by a losing perp long is negative carry before the backtest runs.

---

## Recommendation

**Do not backtest.** The FLB premium (6–9%) is real but does not survive the Kalshi perp hedge cost (−4.1%/yr). If you want to explore delta-hedged FLB, the next step is to pull Coinbase funding history and measure the *executable* Kalshi–Coinbase spread [doc:2026-08-05-kalshi-perpetuals:4, caveat (a)]. That is a data probe, not a backtest, and only justifies a backtest if the Coinbase spread is positive and survives fees.

### Fee & adverse-selection economics

I need to acknowledge the challenge correctly identifies a unit-conversion error in my fee calculation.

---

## CRITICAL CORRECTION: Fee arithmetic — final reconciliation

**The challenge is correct.** My "40bps" conversion is arithmetically indefensible; I conflated two different unit bases.

### Resolving the bps ambiguity

From [doc:2026-08-05-kalshi-perpetuals:5]: **"Bps on FULL notional (including leverage)…taker 12.0bps"** — this establishes the convention: bps = basis points on dollar notional. So 12bps = 0.12% of notional, or equivalently 1c ≈ 100bps per dollar of notional.

From [strat:kalshi-btc-perp:fees]: **"taker 2c / maker 1c per contract at 50c"** — this states an *absolute* fee (in cents) per contract, not a percentage.

At a 50c bracket:
- Taker fee = 2c per contract
- Cost as % of notional = 2c ÷ 50c notional = **4% = 400bps**

At a 30c bracket (if the fee scales proportionally):
- Taker fee = 2c × (30c ÷ 50c) = 1.2c per contract
- Cost as % of notional = 1.2c ÷ 30c notional = **4% = 400bps**

**Corrected total round-trip fees:**
- Perp hedge: 24bps [doc:2026-08-05-kalshi-perpetuals:5]
- FLB sale (taker): ~400bps [strat:kalshi-btc-perp:fees, converted]
- **Total: ~424bps**

Against a 600–900bp edge:
- **47–71% of edge consumed by fees alone**

---

## Revised NO-GO decision: Strengthened, not weakened

**The corrected fee barrier is actually more damning than my original claim.**

The three independent barriers now stand as:

1. **FLB + perp fees consume 47–71% of the purported 6–9pp edge** — a material headwind that leaves only ~2–4pp net edge before adverse selection, gamma whipsaw, or spread reversal.

2. **Perp shallow books + gamma convexity at the barrier** [doc:2026-08-05-kalshi-perpetuals:2]: "books are shallow for any standing-position strategy"; rebalancing a delta-hedged tail bracket into the barrier will incur repeated 24bps round-trip costs. With only 2–4pp net edge remaining after baseline fees, even one intraday rebalance wipes breakeven.

3. **Informed-flow reversal risk in single-name tail markets** [doc:2026-07-23-prediction-market-strategies:2] + [doc:2026-08-05-kalshi-perpetuals:2]: a 6–9pp FLB is an anomaly that signals either miscalibration or retail mispricing. Once observed by informed sellers (or repricing MMs), bid-side liquidity collapses precisely when you need to rebalance. This is not theoretical — [doc:2026-07-28-liquid-market-guardrails:1] documents that "retail is the loss-donor" in fast tail-market repricing.

**Bottom line: NO-GO reaffirmed, with corrected and stronger arithmetic.** Do not backtest. The fee structure alone kills the trade; the microstructure risks compound it.

### Scalability

**NO-GO** for the backtest as proposed. The decision rests on three independent blockers:

## 1. **Hedge instrument is unmeasured and likely illiquid**

Kalshi BTC perpetuals show **zero market depth**: 0 open markets, 0 settled volume in the catalog [strat:kalshi-btc-perp:absorption]. You cannot execute a delta hedge on an unmeasured market. The capacity proxy recommends running `walk_book_capacity.py` first [strat:kalshi-btc-perp:ceiling], but this is a prerequisite gate—without knowing bid/ask depth and slippage, you cannot estimate hedge cost against your 6-9pp FLB premium. Reference Kalshi weather markets (weather-only comparable) show ~500-700 contracts/city ceiling [strat:kalshi-btc-perp:capacity], but crypto perps are a different asset class with unknown absorption.

## 2. **The FLB edge itself is not yet harvestable**

The guardrail [doc:2026-07-28-liquid-market-guardrails:2] directly contradicts the premise: *"measured overpricing is NOT a harvestable edge"* for <30c longshots. Fading far-OTM options yields "tiny wins" with only ~5 event-days in the sample—insufficient to validate. The document requires three gates: (a) net-of-fee AND net-of-spread P&L, (b) tradeable book (spread << edge), (c) enough independent event-days. You have not yet passed (a) or (c) in isolation, before compounding with a hedge.

## 3. **Perp hedge economics are historically negative**

Kalshi BTC perp funding baseline is 8–12% gross, single-digit net, with negative carry clustering during selloffs [doc:2026-08-05-kalshi-perpetuals:6]. Cross-venue funding arbitrage is documented as "mostly NET NEGATIVE under conservative exits" in peer-reviewed 2025 analysis. Critically, the US-legal Kalshi↔Coinbase pair **has NO published measurement**—you would be harvesting a 6-9pp edge by paying unknown perp fees and funding drag.

## 4. **Correlated tail risk is unhedgeable**

The guardrail warns: "a rare CORRELATED tail (threshold ladders cross en masse on a gap)"—all your <30c strikes breach simultaneously on a gap, and the perp hedge unwinds against you precisely when you most need it. Gamma/whipsaw near the barrier becomes a loss multiplier on the tail event you were selling.

---

**Sequence instead:** (1) Run `walk_book_capacity.py` on Kalshi BTC perp; if depth is < 100 contracts, stop. (2) If liquid, backtest perp-only funding carry economics separately (single-leg, no FLB). (3) Only if (1) and (2) both pass, revisit the FLB+perp compound backtest *and* validate FLB alone first against the guardrail's three gates.

### Access / regulatory

# Access/Regulatory Findings: Kalshi-BTC Perp Hedge Backtest

**GO for backtest** — regulatory access is clear.

**Confirmed:**
- Kalshi is CFTC-regulated DCM; US persons approved, API live (REST v2 + WebSocket) [strat:kalshi-btc-perp:access]
- Perp data pipeline is US-clean and free (margin endpoints, no auth required) [doc:2026-08-05-kalshi-perpetuals:7]
- Single-venue design (Kalshi only) — no Polymarket geoblock risk, no cross-venue commission trap [doc:2026-07-23, doc:2026-07-28]

**Not covered by evidence:**
- Whether crypto binary options (KXBTCMAXMON-family) are explicitly tradeable under US Kalshi account (likely yes, but verify product whitelist in your account/API spec)

**Out-of-scope for this focus point** (defer to economics/risk review):
- Hedge cost vs. 6–9pp premium, gamma/whipsaw at the barrier
- Perp funding drag vs. premium capture  
- Correlated-tail risk across strikes
- Probe instrumentation design

**Bottom line:** Access/regulatory clears. Advance to design and economics review for viability.

### Testability

The challenge conflates two distinct claims. My finding stands; the challenge misapplies the evidence.

## The distinction
- **[strat:kalshi-btc-perp:noevidence]** states: your *portfolio* has no internal edge evidence for this strategy — you've never traded it. ✓ True and important.
- **The challenge claims** this means the perp market itself has "0 open markets, 0 settled volume" — i.e., the data doesn't exist. ✗ This is a category error.

## Evidence directly contradicts the challenge
**[doc:2026-08-05-kalshi-perpetuals:1]** explicitly lists the Kalshi perp market state as of 2026-08-05:
> "16 markets (13 active): BTC, ETH, SOL, XRP, DOGE, LTC, BCH, LINK, NEAR, SUI, ZEC, HYPE, kSHIB (DOT/HBAR/XLM listed, zero volume)."

BTC is listed as **active** (not "zero volume"). The evidence documents that these 13 markets have live orderbook, 1-min candlesticks, trade history, and funding-rate data available via public REST endpoints.

**[doc:2026-08-05-kalshi-perpetuals:7]** confirms the data is "free, US-clean... funding since 06-03, orderbook, 1-min candles, trades, no auth."

## What the challenge *should* say
The real risk is **not** that data is unavailable — it is that:
1. You have zero internal evidence this delta-hedge strategy is profitable for you (per [strat:kalshi-btc-perp:noevidence]).
2. A 2-month perp history is short; funding regimes could shift.
3. Paper trading is non-negotiable before live sizing (which I already recommended).

**My recommendation stands**: data probe → 2-week paper trade → 1-month backtest. The data is there; the edge claim is unproven.

