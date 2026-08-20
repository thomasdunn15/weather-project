# Liquid-market expansion guardrails (learned 2026-07-27/28)

Guardrails distilled from our OWN empirical work this cycle — the 42-agent fast-market
research (0/12 survived), the daily-metals net-of-fee backtest, and the engine
assessments of labor-fade (S4) and cross-venue arb (S3). "reverified" points at that
work: a 'don't' rule earned by measurement, not by an outside paper we trusted.

## GUARDRAIL: fast-market direction/arb/MM/lead-lag edges are HFT/latency-gated
<!-- fp: mechanism.netfee, economics.adverse_selection | kind: guardrail | reverified: 2026-07-28 our fast-market research (0/12 sources survived, all killed 3/3) + our own intraday-latency probe / fair-value gate -->
Edges that live in fast (seconds-to-hourly) markets — cross-strike dutch-books, spot
lead-lag, settlement-window games, order-flow momentum — are REAL but captured in
milliseconds by colocated/MEV bots; in every measured case retail is the loss-donor
(Polymarket: top 0.1% capture 67% of winnings). The market reprices public info faster
than a retail trader can act, and the spread is compensation, not free money. Do NOT
propose fast-market direction/arb/MM/lead-lag plays as retail edges. FLB is the exception
(structural/behavioral, not a speed race) — but see the next guardrail.

## GUARDRAIL: liquid-market FLB is a premium/tail trade or an untradeable book
<!-- fp: mechanism.netfee, scalability.decay | kind: guardrail | reverified: 2026-07-28 our daily-metals net-of-fee backtest (flb_backtest.py) + KXUE labor-fade engine assessment -->
The favorite-longshot signal is measurable in liquid markets (daily metals +6-16pp, labor
+10pp) — but HARVESTING it is the problem, and a measured overpricing is NOT a harvestable
edge. Fading <30c longshots = selling far-OTM options: tiny wins, a rare CORRELATED tail
(threshold ladders cross en masse on a gap), and only ~5 event-days in our sample — cannot
be validated. On thin macro books (KXUE ~90c median spread) the crossing cost dwarfs the
10pp edge outright. Require: (a) net-of-fee AND net-of-spread P&L, (b) a tradeable book
(spread << edge), (c) enough independent event-days to observe the tail, before believing
any liquid FLB. Default: measured-mispricing != tradeable.

## GUARDRAIL: cross-venue arbitrage — commissions likely exceed the spread
<!-- fp: economics.fees, access.regulatory | kind: guardrail | reverified: 2026-07-28 our S3 engine assessment + fast-market research (2-4% gross deviation classified unenforceable; every measured pair is geoblocked Polymarket) -->
Cross-venue price deviations (2-4% gross) are largely unenforceable: multi-leg fills are
non-atomic, and commissions on BOTH legs typically exceed the observed spread. Every
published arb measures the CFTC-geoblocked Kalshi<->Polymarket pair, which is never to be
circumvented. The only legally-executable pair is Kalshi<->ForecastEx (genuine white
space, untested). Do NOT greenlight a cross-venue backtest until a settlement-equivalence
audit + a measured net-of-BOTH-commissions spread clears ~0.5-1%.

## Confirmed-but-unharvestable FLB signals (evidence, not a target)
<!-- fp: our_evidence.paper, market_fit.flow | kind: evidence -->
We measured (flb_regime table) robust FLB in two places: monthly one-touch crypto
(KXBTCMAXMON/SOL/XRP, <30c longshots overpriced +6-9pp — retail lottery flow on "will BTC
hit $X") and Kalshi labor/unemployment (KXUE +10.1pp, KXJOBLESSCLAIMS +9.4pp — the
documented labor inefficiency pocket). Both are REAL price patterns but blocked from
harvest by the premium/tail shape and thin/wide books (per the guardrails above). Note the
counterparty test: FLB pays only against NAIVE retail flow; commodity/macro books often
carry institutional/hedger flow, so an FLB-shaped price there may be a risk premium, not a
harvestable behavioral edge.
