# Kalshi perpetual futures — first-party probe + research (2026-08-05)

Kalshi launched CFTC-regulated crypto perpetual futures ("perps"/"margin") 2026-05-29
(BTCPERP live 06-03) — a leveraged, no-expiry product entirely separate from the binary
event contracts our stack trades. "Measured/probe" sections are OUR OWN pulls of the
live public API on 2026-08-05; external claims carry source names.

## Kalshi perps: product + API facts (first-party, verified against live API)
<!-- fp: market_fit.preconditions, testability.probe | kind: evidence -->
REST base `https://external-api.kalshi.com/trade-api/v2/margin/` (demo:
`external-api.demo.kalshi.co`) — same RSA auth as the event API. MARKET DATA IS FULLY
PUBLIC (no auth, live-verified): /margin/markets, /margin/trades, /margin/orderbook,
/margin/markets/{ticker}/candlesticks (1/60/1440-min only), and
/margin/funding_rates/historical — the COMPLETE funding history for all markets since
launch, free. 16 markets (13 active): BTC, ETH, SOL, XRP, DOGE, LTC, BCH, LINK, NEAR,
SUI, ZEC, HYPE, kSHIB (DOT/HBAR/XLM listed, zero volume). Tiny retail contract units
(0.0001 BTC ≈ $6.5). Index = CF Benchmarks real-time (BRTI, 1s updates). Funding every
8h (04/12/20 UTC): TWAP of 1-min premium candles, cap ±2%/window, DOCUMENTED
zero-threshold |rate|<0.01% → 0 (help.kalshi.com/15357613); peer-to-peer, no venue
cut. Margin: isolated in apps, PORTFOLIO margin via API; collateral earns ~3.25% APY
at the clearinghouse; liquidation = clearinghouse market orders, negative balances
possible in gaps. Trading 24/7 (Thu ~3-5am ET maintenance). WebSocket + FIX exist;
order-groups give kill-switch semantics; 63 subaccounts. Demo mirrors prod (free
paper-testing) and already lists commodity perps (Aluminum, with market hours) —
Kalshi filed with the CFTC for gold/metals perps mid-July (45-day clock).
ACCESS GATES: perps require a separate APPLICATION + approval (experience
questionnaire + tutorial; not all approved), a separate margin account via Kinetics
FCM, and API production access is "rolling out member by member". REGULATORY RISK IS
LIVE: CME is suing the CFTC (June 2026) to void the perp approval as illegal swaps —
the whole product line could be forced off the board.

## Measured microstructure 2026-08-05: churny retail volume, tight pro spreads, no standing OI
<!-- fp: market_fit.flow, economics.adverse_selection | kind: evidence -->
Our probe of /margin/markets + 5,000 public trades: 24h notional — BTC $106M, ETH
$58M, HYPE $9.2M, tail $1-6M; ramp was $5.5B in the first 2 weeks (Bloomberg), $16.1B
cumulative by mid-July with "institutional investors accounting for the bulk of
activity" (cryptobriefing). But aggregate OI is only ~$14M (BTC $6.9-7.4M) — a
volume/OI churn ratio of ~15-24x: flow is overwhelmingly intraday/MM, almost nobody
HOLDS positions (Hyperliquid/Binance BTC OI is in the billions). Top-of-book spreads
are TIGHT: BTC 1.4bps, ETH 1.1bps, SUI 0.3bps, worst (kSHIB) 11bps. Trade flow is
retail-sized by count: median trade ≈ $103 notional, p10 ≈ $6, p90 ≈ $6.4k, ~5,000
BTC trades in 46 min. Wintermute publicly confirms two-sided liquidity on Kalshi;
Jump, Susquehanna, Galaxy are confirmed Kalshi MMs (perps-desk attribution unconfirmed).
Read: the naive-flow loss-donor IS present, but professional MMs already stand between
us and it at ~1bp — and books are shallow for any standing-position strategy.

## Measured funding regime 2026-08-05: zero-threshold, persistent, BTC-short/alt-long asymmetry
<!-- fp: our_evidence.paper, mechanism.netfee | kind: evidence -->
Full funding history (2026-06-03 → 2026-08-05, 189 windows/market, our own pull):
(1) The documented 0.01% zero-threshold makes 70-95% of windows pay EXACTLY nothing
(last 30d: 92% of 1,196 records zero) — vs Binance/Hyperliquid where funding is
essentially always nonzero (~1bp/8h baseline). Kalshi funding has NO interest-rate
baseline component: it is pure quantized premium TWAP. (2) When nonzero, funding is
HIGHLY persistent: P(next nonzero same sign)=0.98 — regimes, not noise. (3)
Cumulative since launch: KXBTCPERP longs PAID +0.71% (≈+4.1%/yr to the short side);
EVERY alt negative — longs RECEIVED, best KXBCHPERP ≈6.0%/yr, kSHIB 4.8%, ZEC 4.6%,
SUI 4.0%, LTC 3.7%, ETH 2.1% (persistent small discount to BRTI; Kalshi retail skews
net-short alts / net-long BTC). (4) Tails small: worst window ±0.10-0.12%/8h.
Implications: on-venue BTC cash-and-carry is DEAD BY ARITHMETIC (+4.1%/yr gross <
T-bills, and the 3.25% collateral yield doesn't rescue the un-yielding spot leg).
The live question is CROSS-VENUE: Kalshi alt funding is negative (longs receive)
while incumbent alt funding typically embeds the +10.95%/yr interest baseline (shorts
receive) — long-Kalshi-alt + short-same-alt-elsewhere would collect both legs,
market-neutral. Needs same-window incumbent data + both venues' fees + funding-flip
risk before believing it.

## MEASURED cross-venue funding spread: Kalshi vs Hyperliquid, same 63-day window
<!-- fp: our_evidence.paper, mechanism.netfee, economics.fees | kind: evidence -->
Our own pull 2026-08-05 (Kalshi /margin funding history × Hyperliquid hourly funding,
identical window 2026-06-03→08-05, 1,504 hourly HL rows/coin): the short-incumbent +
long-Kalshi funding spread is POSITIVE ON ALL 13 MATCHED ASSETS — mean +7.0%/yr
gross, range +3.0% (kSHIB) to +12.2% (NEAR); NEAR/HYPE/SUI/LTC all >10%/yr; BTC
+3.4%, ETH +8.5%. Round-trip fees ≈ 0.19% (Kalshi maker 2×5bps + incumbent-leg
~2×4.5bps) — negligible against a months-long hold. CAVEATS: (a) Hyperliquid is the
MEASUREMENT reference only — US persons cannot trade it; the executable short leg is
Coinbase perpetual-style futures, whose funding is plausibly LOWER than HL's
(retail-long skew is what makes HL rich) — the executable spread is unmeasured until
we pull Coinbase funding; (b) 63 days = one calm summer regime, funding flips cluster
in selloffs; (c) two leveraged legs = liquidation/margin management on both sides;
(d) at our capital (~$5-10k) the absolute dollars are modest (~10-14%/yr on capital
at 2-3x). The dislocation is real and consistent in direction; execution legality and
regime persistence are the open questions.

## Kalshi perp fees and venue economics (self-certified 6/24/26, effective 7/8/26)
<!-- fp: economics.fees, mechanism.netfee | kind: evidence -->
Bps on FULL notional (including leverage), charged on BOTH open and close: taker
12.0bps at tier 0 ramping to 2.6bps; maker 5.0bps ramping to 0.6bps; top tier needs
≥$3B 30-day volume; NO maker rebate at any tier (kalshi.com/docs/kalshi-fee-schedule.pdf).
Compare Binance ~5bps / Hyperliquid ~4.5bps taker. Decisive cross with our probe:
measured BTC spread (1.4bps) is BELOW the tier-0 maker fee (5bps) — incumbent MMs
must be top-tier firms quoting at 0.6bps cost; a tier-0 solo operator CANNOT post
competitively even in principle. Retail takers pay 12bps — that flow is being
harvested, but only by pre-ramped MM firms. Round-trip tier-0 cost ~24bps taker /
~10bps maker also sets the moat: cross-venue dislocations smaller than that persist
because outsiders can't close them.

## Perp strategy evidence digest (external literature, 2024-2026 regime)
<!-- fp: our_evidence.paper, scalability.decay, economics.adverse_selection | kind: evidence -->
(1) FUNDING CARRY is a compressed institutional trade: 2024 mean BTC funding
0.0173%/8h (~19% APR gross) but Borri et al. (arXiv 2510.14435) find carry Sharpe
turns NEGATIVE in 2025; Ethena's $7.8B delta-neutral float mechanically caps funding
spikes (BitMEX Q3-2025); realistic baseline ~8-12% gross, single-digit net, negative
weeks cluster in selloffs. (2) CROSS-VENUE FUNDING ARB: peer-reviewed 2025 study
(Blockchain: Research & Applications) finds most funding-arb opportunities NET
NEGATIVE under conservative exits (costs + spread reversal); vendor content claiming
3-12% APR majors / 20-60% long-tail (NeuralArb) is promotional — distrust. Structural
precedents are real though: Hyperliquid's retail skew has produced persistent funding
divergence vs Binance for 3 YEARS; Binance pins BNB funding at 0% by policy
(persistent by construction). The US-legal executable pair (Kalshi<->Coinbase) has NO
published measurement. (3) NEW-VENUE PRECEDENT: CME Dec-2017 futures ran 10-20%
premium for WEEKS-MONTHS (borrow constraints kept arbs out); peer-reviewed work finds
retail activity DEGRADES new-venue price discovery. Windows last weeks-months and
close as MM capital ramps — Kraken/Robinhood/Gemini entries are the decay clock.
(4) MM on a globally-priced asset is latency-gated: the "informed flow" is the global
BTC price, visible to every arb before a slow quoter — the structural INVERSE of our
weather books where WE hold the exogenous information. No rebate + 5bps maker cost +
Wintermute/Jump/SIG presence seals it. (5) LIQUIDATION-CASCADE capture: zero
published non-HFT net-profitable evidence; Kalshi's ~6x cap + isolated margin shrinks
on-venue cascade fuel anyway. (6) FUNDING AS DIRECTIONAL SIGNAL: no net-of-fee OOS
backtest in the literature; academic cross-sections find predictability in
price/volume factors, not funding. (7) Adjacent academic traction: arXiv 2605.10400
designs resolution-aware perps ON binary prediction markets — perp-as-hedge-leg for
event contracts is a recognized construction.

## Perp data pipelines: what is free and US-clean (verified 2026-08-05)
<!-- fp: testability.probe, access.regulatory | kind: evidence -->
US-CLEAN AND FREE, both verified live from our server: (a) Kalshi /margin endpoints —
funding since 06-03, orderbook, 1-min candles, trades, no auth; (b) Hyperliquid
`POST https://api.hyperliquid.xyz/info` — HOURLY funding + premium back to 2023-05-12,
no auth, 500 rows/call, ~1200 weight/min; US persons are barred from TRADING
Hyperliquid but public read-only data carries no stated restriction (data-only use).
Coin Metrics Community API (free, no key) exposes last-24h funding across venues incl.
Binance via a LICENSED collector — usable as a forward-collector for venues we cannot
touch directly. Coinbase perpetual-style futures (CFM, CFTC-regulated, funding accrues
hourly) are the US-legal TRADEABLE second venue; Advanced Trade API, public market
data, but no clean public funding-history endpoint — needs probing. RESTRICTED — do
NOT pull directly even for data: Binance (US = Restricted Location, incl. data
endpoints), Bybit, OKX (public-endpoint scraping expressly prohibited), Deribit
(US excluded), dYdX (US ToS + anti-VPN). CoinGlass has no free API tier ($29/mo
hobbyist covers cross-venue funding incl. a KALSHI page); loris.tools tracks Kalshi
perps free on the web. CME: free daily settlements only (dated futures, basis
reference).
