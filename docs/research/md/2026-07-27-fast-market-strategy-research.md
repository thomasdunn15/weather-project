# Fast-Market Prediction-Market Strategy Research

**Scope:** Which FAST-resolving (15-minute to daily) prediction-market edges are worth backtesting on Kalshi by a *retail* quant.
**House view (adversarial):** markets are efficient, thin, and fee-eaten. The slow structural edges already in our corpus — favorite-longshot bias, Benter-style model+market blend, cross-venue arbitrage — do **not** transfer to fast markets. This survey looked specifically for edges that *live inside* fast markets.
**Date:** 2026-07-27 · **Corpus scanned:** 12 candidate sources across 4 families.

---

## Bottom line

**0 of 12 survive** as concrete, net-of-fee, retail-reachable, *persistent* fast-market edges. The fast-market literature cleanly bifurcates, and both halves are dead for us:

- **Real but HFT/latency-gated** — the edge exists and is realized on-chain, but capture is a sub-second latency race requiring bot/MEV/colocation infrastructure retail cannot reach: cross-strike dutch-books, spot lead-lag, settlement-window "banging the close." In every measured case *retail is the loss-donor, not the capturer.*
- **Real but not-a-trade / not-net** — the phenomenon is genuine but nets zero or negative for a taker, or is a forecasting result with no P&L: minute-level underreaction eaten entirely by the spread, volatility forecasting, and market-making theory with no fees modeled.

This is the same wall our own Kalshi research keeps hitting (intraday fair-value gate, latency probe, skill≠edge): **the market reprices public information faster than we can act, and the spread is compensation, not free money.** The fast-market space does not overturn that — it confirms it in four independent literatures.

**Practical consequence:** no deployable fast-market edge to backtest today. Two near-free *probes* are worth running because the measurement is cheap and Kalshi (unlike Polymarket) has exact, model-able fees on both legs — see [Open Questions](#open-questions--probes).

---

## Family 1 — Market-making / liquidity provision

**Family verdict:** The maker side "wins" only as the accounting mirror of a near-zero-fee zero-sum venue, and the winnings concentrate in a professional elite; a retail maker joins as the adverse-selection victim. The theory papers model risk, not profit, and skip fees entirely. *No edge — retail is the funding flow.*

### 1.1 Who Wins and Who Loses in Prediction Markets? (Akey, Grégoire, Harvie, Martineau)
- **Link:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103
- **Method/claim:** Ex-post attribution over 588M Polymarket trades / $67B. Winners *post* limit orders that resolve favorably; losers *take* with market orders. Frequent traders and longshot bettors lose.
- **Net-of-fee:** Moot — Polymarket ~zero trading fees, so gross≈net, but this is realized-PnL accounting, not a forward-tested return.
- **Retail-realistic:** **NO.** Top 1% of positive-PnL users capture 76.5% (top 0.1% capture 67%); ~1,700M users lost $650M. Retail is the loss-donor that funds a professional cohort.
- **Verdict:** An autopsy of who-won ("limit orders that resolve favorably relative to *realized outcomes*" — hindsight), not a rule. Authors disown persistence as possibly "sample selection rather than skill." The reframed edge "buy 30¢ when fair is 45¢" is just superior forecasting, which is the whole problem, not a solution.

### 1.2 Optimal Market Making in Prediction Markets
- **Link:** https://arxiv.org/abs/2607.17991
- **Method/claim:** Avellaneda-Stoikov analog for binary-settlement LOB contracts via HJB stochastic control; optimal spread/skew depends on price, inventory, time-to-resolution; inventory risk vanishes as price → 0/1.
- **Net-of-fee:** **NO** — zero fees modeled. Kalshi taker fee (~7%·p·(1−p)) would swamp the thin margins.
- **Retail-realistic:** **NO / HFT-lineage.** Continuous two-sided requoting with queue priority.
- **Verdict:** By construction a *risk-management* result (cuts downside PnL at a small *cost* in expected profit vs a myopic quoter) — earns *less*, not more. Theory + Monte Carlo on a latent-belief diffusion; no positive net edge demonstrated. Structural takeaway (skew by price/inventory/time) is a design note, not a P&L.

### 1.3 Volatility in Prediction Markets: A Structural Approach (Xi, Moallemi, Pai, Wang — Columbia)
- **Link:** https://arxiv.org/abs/2607.08199
- **Method/claim:** Wright-Fisher deadline-resolution channel + Glosten-Milgrom order-flow channel (spread+volume) beats ARCH/GARCH out-of-sample across ~880k hourly Kalshi forecasts; +residual GARCH best. Order-flow carries short-horizon signal — for **volatility, not direction.**
- **Net-of-fee:** **NO** — no fee accounting, no trade anywhere. Metric is Winkler interval score, not P&L.
- **Retail-realistic:** **NO** — value realizable only as a market-making quote-timing/vol input; the model's own Glosten-Milgrom channel *is* informed flow picking off makers exactly when the signal fires.
- **Verdict:** A better-than-GARCH vol forecast is skill, not edge (no Sharpe, no P&L, zero fees). Usable only *conditional on already running a maker* — which the rest of this family says not to.

---

## Family 2 — Cross-strike / intra-event no-arbitrage

**Family verdict:** Dutch-books and monotonicity violations are **real and net-of-fee on Polymarket** (zero fees) — but they are the single most densely hunted inefficiency in electronic markets, captured in milliseconds by co-located/MEV bots, and economically tiny. Every paper's own data shows retail loses the latency race, and multi-leg fills are non-atomic (get legged, not arbed). *Real, net, HFT-only, transient.*

### 2.1 Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets (Saguillo, Suarez, Kieffer, Ghafouri — AFT 2025)
- **Link:** https://arxiv.org/abs/2508.03474
- **Method/claim:** Intra-event dutch-books on Polymarket (single-market YES+NO; combinatorial across related markets). ~$39.6M *estimated* extracted across 86M wagers Apr-2024→Apr-2025; detected opportunities show ~40¢/$ gross mispricing.
- **Net-of-fee:** **Aggregate-real but not a clean net figure** — the $40M is a detection estimate ("assuming ε=$1 profit per trade") over block-level prices, not netted for slippage/gas/failed-leg. Zero *trading* fee ≠ net.
- **Retail-realistic:** **NO — HFT/MEV.** Flashbots-funded; paper states arbitrage "requires cross-market, fast execution," happens "during periods of volatility," and is extracted by "very big players with bot-like behaviour" (top wallet $2.0M over 4,049 txns). Explicitly "disadvantages retail traders who cannot compete on speed." Footnote 11: multi-leg placement is non-atomic.
- **Verdict:** Genuine on-chain arb, captured by a handful of automated wallets and competed away sub-second. The claim's own caveat concedes retail-reachability is "doubtful." **HFT-only.**

### 2.2 Arbitrage Analysis in Polymarket NBA Markets
- **Link:** https://arxiv.org/abs/2605.00864
- **Method/claim:** Combinatorial intra-game arb (moneyline/spread/total consistency). 290 executable episodes over 173 games, median 101 bps/execution, overwhelmingly in final live minutes. Single-market YES+NO violations essentially absent (7 episodes, median 3.6s).
- **Net-of-fee:** ~Net on *fees* (zero-fee venue) but **not net-of-execution** — 101 bps is a theoretical top-of-book snapshot spread, no execution/latency/fill simulation.
- **Retail-realistic:** **NO.** Concentrated in the final live minutes; median lifetimes ≈ the 3.6–5.5s polling floor (censored below observability); non-atomic two-leg fills across separate books mid-scoring-event; Polymarket imposes a 250ms taker delay on sports specifically to defeat latency arb.
- **Verdict:** Real but **economically null and latency-gated** — $559.59 total capped profit across all 173 games (~$3.23/game), 76.9% of ops capped at ~14.8 shares, risk-free "Middle" never materialized. Paper's own thesis is "profound microstructural efficiency."

### 2.3 Statistical Arbitrage in Binary Prediction Markets (Nunes, 2026)
- **Link:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6446502
- **Method/claim:** Three fee-aware screens on Kalshi-style crypto ladders — DEP_GRAPH (strike-ladder monotonicity/stochastic-dominance violations), CROSS_MARKET (mutually-exclusive YES sum > $1), SPREAD_FADE (maker edge only when spread > 2× taker fee; net-of-fee-gated by construction).
- **Net-of-fee:** SPREAD_FADE is fee-gated by design — but these are *screens on displayed quotes*, not realized returns. Evidence is closed-form conditions + "50-cycle synthetic simulations"; **full paper Cloudflare-paywalled (HTTP 403), realized magnitude/Sharpe/frequency unverifiable.**
- **Retail-realistic:** **NO.** Riskless arb = speed race; paper includes an explicit "latency sub-strategy" firing when the reference asset moves faster than the market reprices. On a home connection you get legged and pay Kalshi fee on both legs.
- **Verdict:** Screens ≠ realized edges; paywalled; SPREAD_FADE is mislabeled "riskless" — it's passive MM exposed to adverse selection (the spread is *wide because* informed/fast flow is present). **Source too weak + latency-gated.** *(The read-only monotonicity/dutch-book screen on Kalshi's own ladders is the one cheap probe worth running — see Open Questions.)*

---

## Family 3 — Underlying spot lead-lag / latency

**Family verdict:** The crypto lead-lag is either **sub-second (inside HFT/colocation latency)** or **slow (multi-hour) + cross-venue (needs an options account)** — never the fast-and-retail-reachable middle. Neither tests a net-of-fee retail strategy. *Wrong shape on both ends.*

### 3.1 Do Prediction Markets Match Option Prices? BTC Threshold Evidence (Binance/Polymarket, 2026)
- **Link:** https://arxiv.org/abs/2606.19517
- **Method/claim:** Polymarket BTC-threshold YES vs discounted risk-neutral binary implied by a listed Binance/Deribit call (same underlying/strike/maturity). Mean gap 5.6pp (n=214, t=6.46), 6.3pp pooled, 11pp on Deribit; AR(1) half-life ~4h, mean-reverting; largest at low implied-prob / long maturity.
- **Net-of-fee:** **Weak** — a delta-hedged *proxy* "profitable after conservative transaction costs, though with marginal statistical precision." Not a demonstrated realized P&L; strong t is on the raw gap, not net P&L.
- **Retail-realistic:** **NO.** Requires a Binance/Deribit crypto-options account (largely closed to US retail) + continuous delta hedging — not a prediction-market click. Source's own retail flag: no.
- **Verdict:** **SLOW** (hourly, 4h half-life — authors attribute it to "slow information transmission between segmented venues") **and cross-venue.** Wedge is widest in the thinnest/most gamma-intensive corner. Wrong fit for fast/retail; reject.

### 3.2 Price Discovery in Cryptocurrency Markets (Plazuelo Pascual et al., 2025)
- **Link:** https://arxiv.org/abs/2506.08718
- **Method/claim:** Tick-by-tick, CME BTC futures lead Binance spot on 4/5 event dates (Hasbrouck info share 0.52–0.56); Hayashi-Yoshida lead-lag **0.055–0.15 seconds**; CEX leads DEX (Uniswap).
- **Net-of-fee:** **NO** — gross microstructure statistics only, no strategy, no P&L, no fees.
- **Retail-realistic:** **NO — HFT/colocation.** 0.055–0.15s is inside the HFT reaction window; retail RTT is hundreds of ms to seconds.
- **Verdict:** Directly answers our question — "capturable at retail latency? **essentially no.**" Info share barely above the 0.50 coin-flip; classic already-arbed HFT effect.

---

## Family 4 — Order-flow / microstructure

**Family verdict:** Two of the four are **adversarial nulls that kill naive order-flow angles** (public-feed signed flow is ~coin-flip noise; you can't even *measure* a retail LP edge from public data). One is real but is *market manipulation* captured by capitalized/fast actors (and being remediated). One is a genuine underreaction that **nets negative** for a taker. *Nothing tradeable; two are useful cautions.*

### 4.1 Fill-Side Non-Retail Trading on Polymarket (Behavioral Tiers & Microstructure Signatures)
- **Link:** https://arxiv.org/abs/2605.11640
- **Method/claim:** A dedicated attempt to characterize passive-LP profitability from public fills that **withdraws** its posted-spread / quote-lifecycle / reward-timing analyses ("G-QUOTE-LIFE universal fail") because quotes can't be attributed off-chain. Confirms LP cost = adverse selection from informed flow; fill-MM concentrates in one-sided markets (ρ=−0.37); profitable participants are whale/HFT tiers (81.4% of notional, 12.6% of addresses).
- **Net-of-fee:** Unknown — profitability analyses retracted.
- **Retail-realistic:** **NO** (stated).
- **Verdict:** Adversarial null — you **cannot cleanly measure a retail LP edge**, and its one durable finding (LP cost = adverse selection) is a *cost that makes retail lose.* Useful as a caution, not an edge.

### 4.2 Settlement Manipulation in Prediction Markets (Dai, Jia, Yu — Stanford/SMU, Jun 2026)
- **Link:** https://arxiv.org/abs/2606.31675
- **Method/claim:** Polymarket's 5-min BTC up/down contract is exploited by settlement-window "banging the close": net Binance spot flow in the final ~10s spikes ~50%, pushes the Chainlink oracle across the strike (finishes same side ~85%), reverts within 10s. A >90%-priced side is overturned ~1/3 of the time in still-live cycles. ~$8.2M transferred over two months, **mostly from retail.** Absent at the 15-min horizon.
- **Net-of-fee:** The $8.2M is manipulation P&L, not a passive-signal net return.
- **Retail-realistic:** **NO — capital + last-seconds HFT execution + it's manipulation.** Retail is the loss-donor. Being remediated (lengthening to 15-min removes it).
- **Verdict:** A *real* fast edge — and it is settlement manipulation captured by capitalized/fast actors, legally fraught, non-persistent (design fix kills it). **Defensive relevance only:** confirm our configs never make *us* the loss-donor on short-window oracle-settled contracts.

### 4.3 The Anatomy of a Decentralized Prediction Market (Dubach)
- **Link:** https://arxiv.org/abs/2604.24366
- **Method/claim:** Trade-direction inferred from Polymarket's public WebSocket feed agrees with on-chain truth only ~59% (panel mean 0.615, 95% CI [0.58,0.65]) — barely above coin-flip. Effective half-spread flips sign vs truth on 67% of top-100 markets, Kyle's λ flips on 60%; remove sign errors and the apparent adverse-selection spread **collapses to ~0.** Also: longshot spread premium; depth-decay-near-resolution slope 0.55 on log seconds-to-close (t=3.85, but vanishes under duration/price/volume controls).
- **Net-of-fee:** Unknown — descriptive, no backtest.
- **Retail-realistic:** **NO** — correctly-signed flow needs an on-chain OrderFilled join ("infra most retail lacks").
- **Verdict:** **The most valuable caution in the corpus.** OFI / VPIN / effective-spread / price-impact signals built off a public feed are *noise*. Directly tells us **not** to build a public-feed order-flow signal.

### 4.4 When Do Markets Fully Process Public Information? (Angelini & De Angelis, 2026)
- **Link:** https://arxiv.org/abs/2606.07811
- **Method/claim:** On Kalshi **live NBA** win contracts (minute-level), prices *underreact* to public play-by-play — a 1-min benchmark win-prob change produces only ~0.64-for-one contemporaneous midpoint move; the residual "updating gap" predictably drives 5–15 min drift, strongest in thin/illiquid contracts.
- **Net-of-fee:** **NO.** The authors' *own* executable backtest (buy-at-ask / sell-at-bid, Table 11) yields **negative** returns at every gap threshold — the drift is entirely absorbed by the bid-ask spread. They conclude it "should not be interpreted as a frictionless arbitrage opportunity."
- **Retail-realistic:** The one untested residual is a **passive maker** resting a limit order in the drift direction (Kalshi charges makers no fee) to capture drift + half-spread — but the paper does **not** test it, and it's economically suspect: the drift is public, so a resting order is filled via adverse selection precisely when value moves against it, and the signal is strongest exactly where fill rates are lowest (thin contracts).
- **Verdict:** Real underreaction, **but taker returns are negative and the maker version is untested + self-defeating in thin books.** This is the *closest thing to a retail probe* in the entire corpus — and it's on our own venue — but the prior is bad.

---

## Shortlist — most worth ingesting

**No source clears the bar for live trading. The deployable shortlist is empty.** What follows is ranked *ingestion* value for an adversarial corpus — as methodological cautions and probe seeds, **not** deployable edges. Retail-realistic + closest-to-testable first.

| Rank | Source | Why ingest | Ingest as |
|---|---|---|---|
| 1 | **4.4 Angelini & De Angelis** (Kalshi live NBA underreaction) | Only residual with an untested retail-maker angle, on *our own venue*. Bad prior, cheap to paper-test. | **Probe seed** |
| 2 | **4.3 Dubach** (anatomy / ~59% signed-flow) | Kills the naive public-feed order-flow build before we waste effort on it. Saves money by *not* building. | **Methodological caution** |
| 3 | **4.1 Fill-Side Non-Retail** | Reinforces: can't measure a retail LP edge from public data; LP cost = adverse selection. | **Methodological caution** |
| 4 | **2.3 Nunes** (DEP_GRAPH / CROSS_MARKET) | Names concrete cross-strike screens runnable read-only against Kalshi ladder snapshots we already collect. | **Probe seed (cheap measurement)** |
| 5 | **1.1 Who Wins/Loses** | The who-funds-whom map — retail is the loss-donor. Framing/discipline value. | **Framing reference** |

Everything else (2.1, 2.2, 3.1, 3.2, 4.2, and the theory papers 1.2/1.3) is **document-and-do-not-pursue**: Polymarket/crypto/HFT/manipulation-specific, or fee-free theory — low transfer value to a Kalshi retail book.

---

## Killed claims

All 12, ranked by residual probe-closeness (closest first). See the family sections above for full detail.

| # | Title | Family | Killed because |
|---|---|---|---|
| 4.4 | When Do Markets Fully Process Public Info? (Angelini & De Angelis) | microstructure | Authors' own taker backtest is **negative** — drift eaten by spread; maker version untested and adversely-selected in the thin books where the signal is strongest. |
| 2.3 | Statistical Arbitrage in Binary PM (Nunes) | cross-strike | Screens ≠ realized returns; **paywalled** (unverifiable); riskless arb + explicit latency sub-strategy = speed race; SPREAD_FADE is MM mislabeled "riskless." |
| 4.3 | Anatomy of a Decentralized PM (Dubach) | microstructure | Adversarial null — public-feed signed flow ~59% (coin-flip); adverse-selection spread collapses to ~0; correct signing needs on-chain infra retail lacks. No positive edge. |
| 4.1 | Fill-Side Non-Retail Trading | microstructure | Adversarial null — withdraws its own LP-profitability analyses; you can't measure a retail LP edge; LP cost = adverse selection (a *cost*). |
| 1.1 | Who Wins and Who Loses (Akey et al.) | market-making | Ex-post autopsy, not a forward rule; top 1% capture 76.5%; retail is loss-donor; persistence disowned as sample selection. |
| 1.3 | Volatility: A Structural Approach (Xi et al.) | market-making | Vol-forecasting only — no direction, no Sharpe, no P&L, **zero fees**; skill ≠ edge; realizable only as MM quote-timing input. |
| 1.2 | Optimal Market Making in PM | market-making | Risk-management result (earns *less* than myopic quoter); **no fees modeled**; theory + Monte Carlo only; HFT-lineage continuous requoting. |
| 2.1 | Unravelling the Probabilistic Forest (Saguillo et al.) | cross-strike | Real on-chain dutch-books but **HFT/MEV** — bot latency race; retail "lost to bots"; $40M is a detection estimate, non-atomic legs, transient. |
| 2.2 | Arbitrage in Polymarket NBA Markets | cross-strike | Theoretical snapshot spread, latency-gated (final live minutes, sub-3.6s, 250ms sports delay), **economically null** ($559 total / 173 games). |
| 3.1 | Do PM Match Option Prices? (BTC threshold) | spot-lead-lag | **SLOW** (4h half-life) + cross-venue (needs Binance/Deribit options account, US-retail-blocked); net-of-fee proxy only "marginal statistical precision." |
| 3.2 | Price Discovery in Crypto Markets (Plazuelo Pascual et al.) | spot-lead-lag | Lead-lag is **0.055–0.15s** — inside HFT/colocation latency; gross stats only, no strategy/fees. "Capturable at retail latency? essentially no." |
| 4.2 | Settlement Manipulation in PM (Dai, Jia, Yu) | microstructure | Real fast edge but it's **manipulation** ("banging the close") needing capital + last-seconds spot; retail is loss-donor; being remediated (15-min horizon kills it). |

---

## Open questions / probes

Ranked by cheapness-to-run. All have a **bad prior** — run only because the measurement is nearly free and Kalshi's exact two-leg fees are model-able (unlike Polymarket's zero-fee blur).

1. **Cross-strike monotonicity / dutch-book screen on Kalshi's *own* hourly crypto ladders** (from Nunes DEP_GRAPH / CROSS_MARKET). *Do violations appear on a retail API poll with capturable size, or are they stale quotes about to be pulled?* Cheapest probe — read-only screen over ladder snapshots we already collect; measure violation frequency, size, and lifetime, then net Kalshi's ~7%·p·(1−p) on **both** legs. **Prior:** HFT-gated / stale, but the measurement costs almost nothing and definitively settles it for our venue.

2. **The untested passive-maker version of the Angelini underreaction** on Kalshi live NBA. *Can a resting limit order in the drift direction capture drift + half-spread net of adverse selection?* Paper-log resting-maker fills in live NBA contracts; measure fill-conditional P&L and fill rate. **Prior (strong):** NO — our own corpus (intraday fair-value gate, requote validation, market-out-predicts-us) says the spread is compensation and the signal is strongest exactly where fills are worst. This is the single residual the literature leaves untested, so it earns one honest paper-test — but do not pre-commit capital.

3. **Defensive audit (not an edge):** does any Kalshi contract we trade resemble a short-window oracle/settlement-window product (5–15 min, single reference price)? Confirm our configs never place *us* as the settlement-manipulation loss-donor (Dai/Jia/Yu). One-time check.

4. **Volatility quote-timing (conditional, low priority):** *only if* we ever build a Kalshi maker — does a Wright-Fisher + Glosten-Milgrom vol forecast (Xi et al.) beat GARCH enough to time quote-widening? Deprioritize: it's contingent on building a maker at all, which the market-making family says not to do.

**Honest thin-evidence flags:**
- **Kalshi-specific fast-market evidence is thin.** Only 2 of 12 sources touch Kalshi directly (Angelini live NBA; Xi vol). The other 10 are Polymarket/crypto — transfer to a Kalshi retail book is an *assumption*, and Kalshi's non-zero two-leg fees make most of them *worse* on Kalshi than the (zero-fee) Polymarket numbers suggest.
- **Nunes (2.3) is paywalled** — realized magnitude/Sharpe/frequency never independently verified.
- **The two "real" fast edges (2.1, 4.2) are both explicitly HFT/capital-gated and retail is measured as the loss-donor** — this is the strongest single data point for the house view.

---

## Sources table

| # | Title | Family | Venue | Net-of-fee? | Retail? | Verdict | Link |
|---|---|---|---|---|---|---|---|
| 1.1 | Who Wins and Who Loses in PM | market-making | Polymarket | moot (~0 fee) | **NO** (top 1% = 76.5%) | Ex-post autopsy; retail is loss-donor | [ssrn 6443103](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103) |
| 1.2 | Optimal Market Making in PM | market-making | theory | **NO** (no fees) | **NO** (HFT requote) | Risk mgmt, not profit; theory only | [arXiv 2607.17991](https://arxiv.org/abs/2607.17991) |
| 1.3 | Volatility: A Structural Approach | market-making | Kalshi | **NO** (no fees) | **NO** (MM input) | Vol forecast; skill ≠ edge | [arXiv 2607.08199](https://arxiv.org/abs/2607.08199) |
| 2.1 | Unravelling the Probabilistic Forest | cross-strike | Polymarket | ~real aggregate | **NO — HFT/MEV** | Real on-chain, bot latency race | [arXiv 2508.03474](https://arxiv.org/abs/2508.03474) |
| 2.2 | Arbitrage in Polymarket NBA | cross-strike | Polymarket | ~net, not net-of-exec | **NO** (sub-3.6s) | Real but null ($559/173 games) | [arXiv 2605.00864](https://arxiv.org/abs/2605.00864) |
| 2.3 | Statistical Arbitrage in Binary PM | cross-strike | Kalshi-style | gated-by-screen | **NO** (latency) | Screens ≠ edges; paywalled | [ssrn 6446502](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6446502) |
| 3.1 | Do PM Match Option Prices? (BTC) | spot-lead-lag | Polymarket/Binance | marginal | **NO** (options acct) | Slow (4h) + cross-venue | [arXiv 2606.19517](https://arxiv.org/abs/2606.19517) |
| 3.2 | Price Discovery in Crypto | spot-lead-lag | CME/Binance | **NO** (gross) | **NO — 0.055–0.15s** | Sub-second; HFT-only | [arXiv 2506.08718](https://arxiv.org/abs/2506.08718) |
| 4.1 | Fill-Side Non-Retail Trading | microstructure | Polymarket | unknown | **NO** | Null; can't measure LP edge | [arXiv 2605.11640](https://arxiv.org/abs/2605.11640) |
| 4.2 | Settlement Manipulation in PM | microstructure | Polymarket | manip. P&L | **NO** (loss-donor) | Manipulation; being remediated | [arXiv 2606.31675](https://arxiv.org/abs/2606.31675) |
| 4.3 | Anatomy of a Decentralized PM | microstructure | Polymarket | unknown | **NO** (on-chain infra) | Null; public-feed flow = noise | [arXiv 2604.24366](https://arxiv.org/abs/2604.24366) |
| 4.4 | When Do Markets Process Public Info? | microstructure | Kalshi (NBA) | **NO** (taker negative) | maker untested | Drift eaten by spread; probe seed | [arXiv 2606.07811](https://arxiv.org/abs/2606.07811) |

---

*Adversarial survey, 2026-07-27. Twelve candidate fast-market edges across four families; zero survive as retail-reachable, net-of-fee, persistent edges. Fast markets are efficient, thin, and fee-eaten in exactly the way the house view predicts — the two genuinely real fast edges are HFT/MEV latency races in which retail is the measured loss-donor. Consistent with our own Kalshi findings: the market reprices public information faster than we can act, and the spread is compensation, not free money.*
