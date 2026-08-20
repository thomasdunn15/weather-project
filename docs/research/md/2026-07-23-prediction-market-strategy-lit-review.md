# Prediction-Market Strategy Literature Review

*Machine-generated discovery pass (deep-research harness: 5 search angles → 19 sources
fetched → 90 claims extracted → 25 adversarially verified, 20 confirmed / 5 killed).
Generated 2026-07-23. Adversarial lens applied throughout: binary markets like Kalshi are
efficient; forecast skill ≠ trading edge; thin books cap size; breadth (venues, underlyings),
not a cleverer model, is the growth lever. Favor net-of-fee, out-of-sample results; flag
gross/in-sample ones.*

## Executive summary

The literature **ratifies** the "efficient, thin, fee-eaten, breadth-is-the-lever" stance
rather than overturning it, and hands two concrete probes rather than a turnkey strategy:
(a) does the +2.6% passive market-making favorite-longshot edge survive on our weather
single-name books, and (b) can the Benter blend clear net-of-Kalshi-fee, not just Brier.
**No paper isolates the one venue pair we can legally trade — Kalshi ↔ ForecastEx** — every
cross-venue result leans on the CFTC-geoblocked Polymarket leg.

---

## Area 1 — Market-making / favorite-longshot bias

### Bürgi, Deng & Whelan — "Makers and Takers: The Economics of the Kalshi Prediction Market" (2025/26)
- **Link:** https://www.karlwhelan.com/Papers/Kalshi.pdf (also SSRN 5502658 / UCD WP2025_19 / MPRA 126350)
- **Method/claim:** 300k+ transaction-level contracts. Strong FLB — <10¢ contracts lose
  >60%, ≥50¢ earn a small statistically-significant positive return, all-contract average
  ≈ −20%. Passive **Makers buying ≥50¢ earn +2.6% after commission** (per-contract, not
  annualized, high-price side only); takers lose.
- **Requires:** ability to post limit orders and get filled as maker on high-priced
  contracts; tolerance for a 33% return SD (~13× the mean); shallow depth (top-decile
  markets average only $526,245 lifetime volume; paper notes a large-capital maker "may have
  to post prices that are less advantageous").
- **Verdict:** the single most Kalshi-native, net-of-fee, real-edge result in the set — but
  +2.6% at 33% SD survives only at trivial size, exactly our depth ceiling. A **breadth**
  (more markets) not depth play. Confidence: HIGH (3-0). **TOP PRIORITY.**

### Bartlett & O'Hara — "Adverse Selection in Prediction Markets: Evidence from Kalshi" (2026)
- **Link:** https://ssrn.com/abstract=6615739 · https://law.stanford.edu/2026/04/21/adverse-selection-in-prediction-markets-evidence-from-kalshi/
- **Method/claim:** Stanford Law / Cornell; 41.6M trades, 478,167 markets. Single-name
  markets show greater informed price impact (Kyle's λ, Glosten-Harris) than broad-based
  ones. Makers still profit via a **behavioral surplus**: in single-name markets traders buy
  YES ~60.9% of volume but those markets settle YES only ~32.5% of the time, so over-bought
  losing YES bets offset the sharp NO money (makers netted $29,274 on the Bezos market).
- **Requires:** a segment with heavy uninformed YES-longshot flow to cross-subsidize; a
  λ/Glosten-Harris decomposition to measure per-market toxicity.
- **Verdict:** load-bearing caution — **a city's temperature bracket IS a single-name
  market**, the high-adverse-selection segment; the +2.6% maker edge depends on enough naive
  YES-longshot flow to offset informed forecasters, unproven for weather and the likely
  reason weather MM would underperform the paper's cross-market average. Confidence: HIGH.
  (A stronger sibling claim — "spreads only modestly wider, makers earn 2× per contract" —
  was REFUTED 1-2; see Killed claims.)

### Whelan (2024) — "Risk aversion and favourite-longshot bias in a competitive fixed-odds betting market"
- **Link:** https://onlinelibrary.wiley.com/doi/10.1111/ecca.12500 (Economica 91(361):188–209, peer-reviewed)
- **Method/claim:** All 56,004 ATP/WTA tennis matches since 2011; average payout rises with
  market-implied probability → FLB is a general **fixed-odds** phenomenon, not a pari-mutuel
  artifact.
- **Requires:** fixed-odds/exchange quotes; descriptive/theoretical, no net-of-fee strategy.
- **Verdict:** establishes FLB exists in exchange-style (Kalshi-like) microstructure, but as
  risk compensation, not free money — context, not a strategy. Confidence: HIGH.

### Snowberg & Wolfers — "Explaining the Favorite-Longshot Bias" (NBER w15923 / JPE 2010)
- **Link:** https://www.nber.org/system/files/working_papers/w15923/w15923.pdf
- **Method/claim:** 5.6M US horse starts 1992–2001 + AUS/UK. Return gradient −61% (100/1+)
  to −5.5% (favorites), yet "**despite significant anomalies in the pricing of bets, there
  are no profit opportunities from simple betting strategies**" once takeout is booked
  (mirrors Levitt 2004; rejects Thaler-Ziemba's positive-favorite claim).
- **Verdict:** our "skill ≠ net edge / mispricing ≠ net edge" thesis proven in the deepest
  dataset in the literature; argues AGAINST porting the stack to sports FLB, and sets the
  prior that a visible calibration gap need not survive fees. Confidence: HIGH.

---

## Area 2 — Cross-venue arbitrage

### Franck, Verbeek & Nüesch — "Inter-market Arbitrage in Betting" (Economica 2013)
- **Link:** https://www.researchgate.net/publication/228309038_Inter-Market_Arbitrage_in_Betting
- **Method/claim:** 11,933 top-5-league soccer matches. Bookmaker + offsetting Betfair
  (short-position) hedge yields a **guaranteed positive return on 19.2% of matches net of a
  5% commission**, but only +1.4% inside that subset and −0.7% across all matches.
- **Requires:** simultaneous fills at two venues with different mechanics; a commission
  model; enough exchange depth.
- **Verdict:** a clean net-of-fee two-venue **template** to adapt for Kalshi ↔ ForecastEx,
  honest about thin edge and capacity — proof of concept, not evidence the edge scales.
  Confidence: HIGH.

### Gebele & Matthes — "Semantic Non-Fungibility and Violations of the Law of One Price in Prediction Markets" (arXiv 2601.01706, 2026)
- **Link:** https://arxiv.org/abs/2601.01706 (corroborated by arXiv 2508.03474, IMDEA/AFT 2025)
- **Method/claim:** TU Munich; 100k+ events, 10 venues, 2018–2025, ~6% concurrently
  cross-listed. Persistent **2–4% execution-aware price deviations** violating the Law of One
  Price, driven by structural frictions (fragmented liquidity, no shared event identity,
  capital-intensive/"unenforceable" arb) rather than informational disagreement. The IMDEA
  companion: ~$40M extracted from Polymarket via execution speed, not predictive accuracy.
- **Requires:** a semantic-matching layer to identify truly-equivalent contracts across
  venues; two-legged capital and speed.
- **Verdict:** the 2–4% is a GROSS execution-aware gap the authors call unenforceable and
  partly attributable to differing resolution semantics (settlement/basis risk); much of the
  cross-listing is Polymarket. Gives the semantic-matching + settlement-risk framework needed
  before any Kalshi ↔ ForecastEx probe. Confidence: MEDIUM (single preprint; one sub-claim 2-1).

### Krause — "From Forecasting Tool to Financial Asset: Evidence of Persistent Arbitrage in Prediction Markets" (SSRN 6905683, 2026)
- **Link:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6905683
- **Method/claim:** 4.87% mean after-fee arb on the Digital Asset Clarity Act event, 89.1%
  of trading days exploitable, framed as "statistically significant persistent arbitrage."
- **Verdict:** SKIM ONLY. Non-peer-reviewed single-author working paper; n=2 events with the
  4.87% from one hand-picked event; the measured leg is **decentralized Polymarket**, which
  is CFTC-geoblocked for US persons (the new "Polymarket US"/QCX is a separate orderbook), so
  the edge is legally unreachable as reported and likely shrinks once settlement/gas/depth are
  booked. Confidence: MEDIUM (headline 2-1; venue framing 3-0).

---

## Area 3 — Calibrated forecasting → market edge

### Sung & Johnson (2007) — "Comparing One- and Two-Step Conditional Logit Models" (J. Prediction Markets 1(1):43–59)
- **Link:** https://www.ubplj.org/index.php/jpm/article/download/419/450/1317
- **Method/claim:** A **two-step conditional logit** (fundamental probability, then a second
  logit combining it with the market-odds probability) returns **+17.53% out-of-sample under
  Kelly vs only +0.96%** for a one-step model with the same variables. Genuinely OOS (fit on
  1,110 races 1995–98, simulated on a disjoint 565-race 1998–2000 holdout, combination
  weights learned on different races); ROI on post-takeout tote odds (net-of-cost).
- **Requires:** a fundamental model, normalized market-odds probabilities, a two-stage
  estimation split, Kelly staking.
- **Verdict:** the archetypal Benter architecture and the cleanest OOS + net-of-takeout
  blending result in the set — direct corroboration of our market-blend edge. Treat +17.53%
  as method validation, not a transferable magnitude (single ~1,000-race parimutuel study).
  Confidence: HIGH.

### AIA Forecaster Technical Report (Bridgewater, arXiv 2511.07678, 2025)
- **Link:** https://arxiv.org/pdf/2511.07678
- **Method/claim:** MarketLiquid benchmark, 1,610 politics/economics/AI questions resolving
  after model cutoffs. The standalone model **underperforms** the market (Brier 0.126 vs
  0.111), yet a simplex-constrained (convex) ~⅓-model/⅔-market ensemble **beats both**
  out-of-sample (LOO Brier 0.106 vs market 0.111); model weight 0.33 [0.12, 0.47] excludes zero.
- **Requires:** a market-price stream per contract, a model probability, a fitted convex
  blend weight; metric is Brier only.
- **Verdict:** strongest independent corroboration of our market-blend finding (model ~⅓,
  market ~⅔ of the work) and of blending being additive even when the model is
  anti-informative — BUT footnote 8 disclaims trading realism ("ignoring transaction costs,
  margin…"), so it proves Brier improvement, never a net-of-Kalshi-fee return, in an
  LLM-judgmental domain distinct from EMOS/NWP. Confidence: HIGH.

---

## Area 4 — New underlyings (macro / elections / sports)

### Macro efficiency — "Information Efficiency Across Macroeconomic Prediction Markets: Evidence from Kalshi" + NBER w34702
- **Link:** https://www.researchgate.net/publication/409472804 · https://www.nber.org/system/files/working_papers/w34702/w34702.pdf
- **Method/claim:** 2,668 contracts, Jul-2021→Jun-2026. **Fed/interest-rate contracts are
  near-perfectly calibrated (Fed Funds Brier ~0.0001) with no significant FLB**, driven by
  ~$450M open interest and HFT/hedge-fund arbitrage. Triangulated with NBER w34702 and Whelan.
- **Verdict:** the macro category a forecasting stack would most naturally port to offers
  essentially no exploitable calibration or FLB edge. Confidence: HIGH for the Fed/rate point
  (corroborated across NBER + Whelan + a Fed paper). NOTE: companion claims that macro is
  efficient IN AGGREGATE and that labor/unemployment is the exploitable soft spot were BOTH
  REFUTED 0-3 — labor is **not** a validated target.

---

## Killed claims — independently re-verified 2026-07-23 (2 overturned, 2 upheld, 1 mixed)

The harness refuted these 5 claims; an independent re-check against the primary sources
**overturned two of them.** This matters: had we ingested the harness's raw kills as engine
guardrails, we'd have fed the engine two FALSE "don't" rules (single-name MM; labor). The
corrected net-of-fee conclusions:

**Overturned — now TARGETS, not guardrails:**
1. **Claim 1 — KILL_WRONG.** "Single-name makers earn ~2× per contract, spreads only modestly
   wider" is the Bartlett & O'Hara abstract almost verbatim: passive MM profits *on average*
   in single-name markets because retail overbets YES (a behavioral surplus cross-subsidizes
   adverse selection). Caveat: one-sided order flow predicts maker losses — size down / step
   aside on toxic one-sided flow. → **Strengthens probe (a): weather single-name MM may work.**
4. **Claim 4 — KILL_WRONG (with mechanism correction).** A dedicated companion paper ("Market
   Efficiency and the Favorite-Longshot Bias in Unemployment Prediction Markets," ResearchGate
   409238145) documents inefficiency concentrated in labor: 287 unemployment contracts, sub-$0.30
   longshots overpriced (bias −0.077, p<0.001; actual win rate 4.0%), UR bias −0.0891, favorites
   well-calibrated. Labor/unemployment IS a real inefficiency pocket — but capture it by **fading
   overpriced <30¢ longshots, NOT by out-forecasting the jobs number** (labor is the hardest to
   forecast — forecasting skill is scarcest exactly there).

**Upheld — genuine guardrails:**
2. **Claim 2 — KILL_CORRECT.** FLB is NOT un-capturable: Makers-and-Takers shows makers capture
   +2.6% net of commission on ≥50¢ contracts. A risk-bearing edge (make the favorite side), not
   an un-capturable risk premium.
5. **Claim 5 — KILL_CORRECT.** "Short-dated ≈ efficient" does NOT generalize to same-day weather
   brackets — Bartlett & O'Hara show short-dated single-name markets are significantly mispriced
   (46% implied → 21% settled). **Do NOT presume weather brackets are efficient** (cuts in our favor).

**Mixed:**
3. **Claim 3 — UNCERTAIN.** The aggregate macro Brier 0.0987 (60.5% better than random) is real,
   but "efficient in aggregate" masks the labor pocket — the number is accurate, not tradeable;
   the money is in the pockets (labor), not the aggregate.

*Sourcing caveat: the two ResearchGate macro papers and some PDFs returned HTTP 403 to direct
fetch, so the labor-FLB figures come from abstracts, not full-text tables — worth confirming
against full text before sizing anything.*

---

## Shortlist — most worth ingesting (ranked)

1. Bürgi, Deng & Whelan, *Makers and Takers* — the only net-of-commission real-Kalshi edge. **TOP.**
2. Bartlett & O'Hara, *Adverse Selection… Kalshi* — why the maker edge persists; why single-name is riskier.
3. Sung & Johnson (2007), *Two-step conditional logit* — cleanest OOS + net-of-takeout Benter validation.
4. AIA Forecaster (arXiv 2511.07678) — modern confirmation the convex model+market blend beats the market.
5. Snowberg & Wolfers (NBER w15923) — the definitive "anomaly ≠ net edge" benchmark.
6. Franck et al. (Economica 2013) — clean net-of-commission two-venue arb template for Kalshi ↔ ForecastEx.
7. Gebele & Matthes (arXiv 2601.01706) — semantic-matching + settlement-risk framework before any arb.
8. Macro-efficiency (ResearchGate 409472804) + NBER w34702 — rule out Fed/rate; frame where macro edge might remain.

*(Krause SSRN 6905683 — skim only; weakest source, legally unusable as reported.)*

---

## Open questions / concrete probes

1. Does any study isolate net-of-fee arbitrage on the one legally-executable pair —
   **Kalshi ↔ ForecastEx** (half fees) — rather than the geoblocked Kalshi ↔ Polymarket pair?
   (None found — genuine white space.)
2. Does the **+2.6% passive-MM FLB edge survive on weather single-name contracts**, given
   they carry higher adverse selection and the edge needs naive YES-longshot flow?
3. Can the **Benter/two-step blend clear net-of-Kalshi-fee** (not just Brier) in liquid
   non-weather categories — i.e. does our market-blend edge beat 1–2¢ fees where the book is
   deep enough?
4. Outside the confirmed-efficient Fed/rate category, which specific Kalshi macro/sports/
   crypto underlyings show a fee-surviving FLB or calibration gap (labor refuted), and is
   there per-category maker fill-rate data to know whether depth allows breadth there?

---

## Caveats

- **Metric mismatch (dominant):** the only genuinely net-of-fee/commission results are
  Whelan's +2.6% Kalshi maker edge, Franck's soccer arb, Snowberg-Wolfers' (negative) horse
  returns, and Sung-Johnson's parimutuel ROI. The forecasting-edge results (AIA, blend logic)
  are Brier-only or gross Kelly — none proves a net-of-Kalshi-fee return.
- **Source quality:** Krause (SSRN 6905683), Gebele-Matthes (arXiv preprint), and the
  macro-efficiency ResearchGate paper are non-peer-reviewed; down-weight accordingly.
- **Venue/legal:** every cross-venue arb paper measures Kalshi ↔ Polymarket; the
  decentralized Polymarket is CFTC-geoblocked for US persons and must never be circumvented.
- **Transfer risk:** FLB/blend magnitudes come from horse racing, tennis, and soccer
  microstructure, which differ from Kalshi binary contracts — transferability is assumed, not
  demonstrated.

## Sources (19 fetched)

| URL | quality | angle |
|---|---|---|
| karlwhelan.com/Papers/Kalshi.pdf | primary | MM / FLB |
| law.stanford.edu/2026/04/21/adverse-selection-in-prediction-markets-evidence-from-kalshi | primary | MM / FLB |
| onlinelibrary.wiley.com/doi/10.1111/ecca.12500 | primary | MM / FLB |
| nber.org/…/w15923.pdf | primary | MM / FLB |
| whirligigbear.substack.com/p/makertaker-math-on-kalshi | blog | MM / FLB (Kalshi fee formula) |
| quantpedia.com/systematic-edges-in-prediction-markets | secondary | MM / FLB |
| papers.ssrn.com/…abstract_id=6905683 | primary | cross-venue arb |
| arxiv.org/abs/2601.01706 | primary | cross-venue arb |
| researchgate.net/…/228309038 (Franck et al.) | primary | cross-venue arb |
| ahasignals.com/research/prediction-market-arbitrage-strategies | blog | cross-venue arb |
| researchgate.net/…/409472804 (macro efficiency) | primary | calibration / macro |
| actamachina.com/posts/annotated-benter-paper | secondary | calibration (Benter) |
| arxiv.org/pdf/2511.07678 (AIA Forecaster) | primary | calibration |
| ubplj.org/…/419 (Sung & Johnson) | primary | calibration |
| researchgate.net/…/256060818 (well-calibrated forecasts?) | primary | calibration |
| nber.org/…/w34702.pdf (Kalshi macro markets) | primary | new underlyings |
| arxiv.org/abs/2604.24366 | primary | new underlyings |
| arxiv.org/pdf/2605.16066 | primary | new underlyings |
| doi.org/10.3390/info17010056 | primary | new underlyings |
