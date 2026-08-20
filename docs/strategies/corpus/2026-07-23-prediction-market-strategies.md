# Prediction-market strategy corpus (ingested 2026-07-23)

Explicit-tagged evidence for the strategy-assess engine, seeded from
docs/research/md/2026-07-23-prediction-market-strategy-lit-review.md. Every `##`
section carries an `fp:` tag; `kind: guardrail` sections carry a re-verification
verdict (a 'don't' rule only enters after independent re-check — the step that
overturned 2 of the harness's 5 kills). See lint_strategy_corpus.

## Makers and Takers: passive MM nets +2.6% net-of-commission on >=50c contracts
<!-- fp: mechanism.netfee, scalability.decay | kind: evidence -->
Bürgi, Deng & Whelan (2025/26), 300k+ transaction-level Kalshi contracts
(karlwhelan.com/Papers/Kalshi.pdf). Strong favorite-longshot bias: <10c
contracts lose >60%, >=50c earn a small statistically-significant positive
return, all-contract average ~ -20%. Passive **makers buying >=50c earn +2.6%
after commission** (per-contract, high-price side only); takers lose. But 33%
return SD (~13x the mean) and shallow depth (top-decile markets average only
$526,245 lifetime volume; a large-capital maker "may have to post prices that
are less advantageous") mean it survives only at trivial size — a **breadth**
(more markets), not depth, play. The only net-of-fee real-Kalshi edge in the set.

## Adverse selection in single-name markets: makers profit via behavioral surplus
<!-- fp: economics.adverse_selection, market_fit.flow | kind: evidence -->
Bartlett & O'Hara (2026), 41.6M trades / 478,167 markets (Stanford Law/Cornell,
ssrn.com/abstract=6615739). Single-name markets show greater informed price
impact (Kyle's λ) than broad-based ones. Makers still profit via a behavioral
surplus: in single-name markets traders buy YES ~60.9% of volume but those
markets settle YES only ~32.5% of the time, so over-bought losing YES bets
offset the sharp NO money. **A city's temperature bracket IS a single-name
market** — the high-adverse-selection segment. The +2.6% maker edge depends on
enough naive YES-longshot flow to offset informed forecasters — unproven for
weather, and the likely reason weather MM would underperform the cross-market average.

## Anomaly != net edge: no profit from simple strategies after takeout
<!-- fp: mechanism.netfee, mechanism.oos | kind: evidence -->
Snowberg & Wolfers (NBER w15923 / JPE 2010), 5.6M US horse starts + AUS/UK.
Return gradient runs -61% (100/1+ longshots) to -5.5% (favorites), yet "despite
significant anomalies in the pricing of bets, there are no profit opportunities
from simple betting strategies" once takeout is booked (mirrors Levitt 2004).
The deepest dataset in the literature proving skill != net edge / mispricing !=
net edge. Sets the prior: a visible calibration gap need not survive fees.

## Cross-venue arb template: net-of-commission, thin, capacity-bound
<!-- fp: mechanism.netfee, testability.probe | kind: evidence -->
Franck, Verbeek & Nüesch (Economica 2013), 11,933 top-5-league soccer matches.
A bookmaker + offsetting Betfair hedge yields a guaranteed positive return on
**19.2% of matches net of a 5% commission**, but only +1.4% inside that subset
and -0.7% across all matches. A clean net-of-fee two-venue template to adapt for
Kalshi <-> ForecastEx — honest about thin edge and capacity; proof of concept,
not evidence the edge scales. Requires simultaneous fills at two venues, a
commission model, and enough exchange depth.

## Law-of-one-price violations are gross and settlement-risk-laden
<!-- fp: market_fit.preconditions, economics.fees | kind: evidence -->
Gebele & Matthes (arXiv 2601.01706, 2026), 100k+ events / 10 venues, ~6%
concurrently cross-listed. Persistent 2-4% execution-aware price deviations, but
the authors call them "unenforceable" — driven by fragmented liquidity, no shared
event identity, and differing resolution semantics (settlement/basis risk), not
informational disagreement. The 2-4% is GROSS; much of the cross-listing is
Polymarket. Gives the semantic-matching + settlement-risk framework needed before
any Kalshi <-> ForecastEx probe. Single preprint (MEDIUM confidence).

## Benter two-step logit: +17.53% out-of-sample, net of takeout
<!-- fp: mechanism.oos, mechanism.netfee | kind: evidence -->
Sung & Johnson (2007), J. Prediction Markets 1(1). A two-step conditional logit
(fundamental probability, then a second logit combining it with the market-odds
probability) returns **+17.53% out-of-sample under Kelly vs only +0.96%** for a
one-step model with the same variables. Genuinely OOS (fit on 1,110 races, tested
on a disjoint 565-race holdout; weights learned on different races) and net of
takeout. The archetypal Benter architecture — method validation for our
market-blend, not a transferable magnitude (single ~1,000-race parimutuel study).

## Convex model+market blend beats the market (Brier-only)
<!-- fp: mechanism.oos, market_fit.preconditions | kind: evidence -->
AIA Forecaster (Bridgewater, arXiv 2511.07678, 2025), MarketLiquid benchmark of
1,610 questions resolving after model cutoffs. The standalone model underperforms
the market (Brier 0.126 vs 0.111), yet a convex ~1/3-model / 2/3-market ensemble
beats both out-of-sample (LOO Brier 0.106 vs 0.111); model weight 0.33 [0.12,
0.47] excludes zero. Corroborates market ~2/3 / model ~1/3, and that blending is
additive even when the model is anti-informative — BUT it is Brier-only (footnote
8 disclaims transaction costs/margin), so it never proves a net-of-fee return.

## Fed/rate macro markets are efficient — no exploitable FLB
<!-- fp: market_fit.preconditions, economics.adverse_selection | kind: evidence -->
Macro-efficiency study (ResearchGate 409472804) + NBER w34702, 2,668 contracts
Jul-2021→Jun-2026. Fed/interest-rate contracts are near-perfectly calibrated (Fed
Funds Brier ~0.0001) with no significant FLB, driven by ~$450M open interest and
HFT/hedge-fund arbitrage. The macro category a forecasting stack would most
naturally port to offers essentially no calibration or FLB edge. Deep book +
efficient = the no-edge+deep quadrant: avoid.

## Labor/unemployment is a real FLB pocket — fade longshots, don't forecast
<!-- fp: market_fit.preconditions, mechanism.netfee | kind: evidence -->
"Market Efficiency and the Favorite-Longshot Bias in Unemployment Prediction
Markets" (ResearchGate 409238145). 287 unemployment contracts: sub-$0.30
longshots overpriced (bias -0.077, p<0.001; actual win rate 4.0%), UR bias
-0.0891, favorites well-calibrated. Labor IS a real inefficiency pocket — but
capture it by **fading overpriced <30c longshots, NOT by out-forecasting the jobs
number** (labor is hardest to forecast; forecasting skill is scarcest exactly
there). Basis for strategy S4. (Figures from abstracts — the ResearchGate PDFs
403'd; confirm against full text before sizing.)

## GUARDRAIL: favorite-longshot bias is capturable but NOT free money
<!-- fp: mechanism.netfee | kind: guardrail | reverified: 2026-07-23 KILL_CORRECT (Whelan Makers-and-Takers: +2.6% net on >=50c is a risk-bearing edge at 33% SD, not an un-capturable premium) -->
FLB is not un-capturable — makers capture +2.6% net of commission on >=50c
contracts. But it is a **risk-bearing** edge (make the favorite side, bear 33%
SD), not free money and not a risk premium you can collect passively at size. Any
FLB strategy must be sized to the depth ceiling and measured net of fee.

## GUARDRAIL: do NOT presume weather brackets are efficient
<!-- fp: market_fit.preconditions | kind: guardrail | reverified: 2026-07-23 KILL_CORRECT (Bartlett & O'Hara: short-dated single-name markets significantly mispriced, 46% implied → 21% settled) -->
"Short-dated ≈ efficient" does NOT generalize to same-day weather brackets.
Short-dated single-name markets are significantly mispriced (46% implied → 21%
settled). Do not treat weather brackets as efficient priors — this cuts in our
favor and keeps the door open to a fee-surviving edge, but the mispricing is the
adverse-selection segment, so pair it with the single-name-toxicity guardrail.

## GUARDRAIL: forecasting edge does NOT travel to crypto direction
<!-- fp: market_fit.preconditions | kind: guardrail | reverified: 2026-07-07 our finding (foundation-models: BTC binary movement near-random to ML, 0.539; 6 frontier models lost money live on Kalshi crypto) -->
Benter/EMOS-style forecasting needs a model that beats the naive prior. That
holds in weather (real NWP skill) but NOT in BTC/crypto direction, which is
near-random to ML (0.539 coin-flip) — the edge there is exogenous to any model we
can build. Strategy S2 (Benter blend) should be judged NO on crypto-direction
markets. The edge that travels to liquid markets is structural FLB (S1/S4), not forecasting.

## GUARDRAIL: cross-venue arb evidence measures geoblocked Polymarket
<!-- fp: access.regulatory | kind: guardrail | reverified: 2026-07-23 KILL/venue-framing 3-0 (Krause 4.87% and every cross-venue result lean on the CFTC-geoblocked Polymarket leg) -->
Every cross-venue arbitrage result in the literature measures Kalshi <->
Polymarket, and the decentralized Polymarket is CFTC-geoblocked for US persons —
never to be circumvented. The only legally-executable pair is **Kalshi <->
ForecastEx** (no paper isolates it — genuine white space). Any arb assessment
must use ForecastEx as the second leg, not Polymarket.
