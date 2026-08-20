# Is Polymarket viable to add to the weather-trading pool alongside Kalshi?

*2026-06-29 · status: draft*

## Question

We run a same-day daily-high-temperature strategy on Kalshi. Live universe is
Chicago (KORD), Miami (KMIA), Dallas (KDFW); Seattle (KSEA) on watch. Deploy bar
is walk-forward **OOS Sharpe > 2.5 on realistic execution**. The prior
venue-expansion survey (2026-06-20) parked Polymarket at **"wait"** and found
ForecastEx's T+1 next-day settlement cut same-day Sharpe to ~0.4–0.6× — settlement
timing is a known dealbreaker. Standing thesis: **cheaper fees narrow the loss,
they do not create edge.** The open high-EV question was **cross-platform arb**.

This paper re-examines Polymarket specifically, nine days later, against seven
gating questions (access, coverage, settlement, fees, API, liquidity, arb), and
returns a GO / WAIT / NO with the single binding constraint named — distinguishing
"creates edge" from "just cheaper fees."

## TL;DR / Verdict

**WAIT — narrowing to NO for the live universe as currently defined.** Confidence:
**high** on the binding constraint, medium on the residual path.

Five of the seven gates are now **green** and several improved since 2026-06-20:
Polymarket US is a live CFTC-regulated venue with **fiat ACH funding (0% fee, no
crypto rails)**, a **full institutional order API** (REST + gRPC + FIX, Ed25519 —
we already authenticate its read endpoints), **taker fees ~30–40% below Kalshi
plus a maker *rebate***, and — critically — its weather markets are **same-day**
(today's high, traded intraday today), so the ForecastEx T+1 Sharpe-decay
**does not apply.**

The deal is killed by the two gates that stayed red, confirmed with live
read-only data today:

1. **Coverage.** Polymarket US lists weather for exactly **5 cities** — NYC,
   Miami, **Chicago-*Midway* (KMDW)**, LA, SF. **Dallas and Seattle do not exist
   there at all**, and Chicago settles on Midway, not our O'Hare (KORD). Of our
   four cities, **only Miami (KMIA) is cleanly tradable.**
2. **Liquidity at our size.** A live order-book pull shows body brackets (where
   our edge would trade) carry **single-digit share depth at the touch**; filling
   our **unit of 500 contracts costs +1.5¢ to +15.6¢ of slippage (median ≈ +11¢)**
   — an order of magnitude larger than the ≈0 gross edge *and* the ~0.75¢ fee
   saving.

Underneath both: **there is no edge to port.** The combined-00Z gross edge is
≈ 0; Polymarket's cheaper fees + maker rebate move Miami from "clearly losing" to
"breakeven at best," exactly as the thesis predicts. **Single binding constraint:
structural coverage + per-bracket liquidity at size — not access, timing, fees, or
API.**

## Methods & Data

**Internal (read-only; no `--live`, no DB writes).**
- `psql -d weather` SELECTs on `contracts`, `prices`, `orderbook_snapshots` —
  Polymarket row counts, station coverage, snapshot span, and Kalshi-vs-Polymarket
  bracket/price comparison for KMIA today.
- Code read: `src/weather_markets/polymarket.py` (Ed25519 client; `get_orderbook`,
  `get_bbo`), `scripts/snapshot_polymarket_prices.py`,
  `scripts/analysis/cross_platform_arb.py`, the production `kalshi_fee_cents`
  formula (`scripts/live_trade.py:370`).
- Ran `scripts/analysis/cross_platform_arb.py` (read-only) for the KORD↔KMDW basis.
- **Live read-only pull** (user-approved, no orders/writes) of the regulated US
  venue (`gateway.polymarket.us`) via the existing client: BBO + L2 order book +
  trade stats for today's KMDW and KMIA brackets, plus a book-walk to measure
  cost-to-fill 500 contracts. Scratch scripts only; nothing persisted.

**External (web search + fetch; each claim verified against a primary source).**
- Polymarket US legal/access status June 2026 (CFTC, QCEX, KYC, geoblock, state
  suits).
- Primary `docs.polymarket.us` pages: **fee schedule**, **weather FAQs**
  (settlement source + timing + city list), **API docs index** (order endpoints,
  auth, streaming), funding rails.

## Internal Findings

### 1. Coverage — Polymarket lists only 1 of our 4 cities

Polymarket contracts in our DB and confirmed against a live market pull today
(1,830 active climate markets enumerated):

| Our city (station) | On Kalshi? | On Polymarket US? | Same station? |
|---|---|---|---|
| **Miami (KMIA)** | ✅ 3,402 | ✅ 366 | **YES — fungible** |
| **Chicago (KORD, O'Hare)** | ✅ 3,402 | ❌ — lists **KMDW (Midway)** | **NO — wrong station** |
| **Dallas (KDFW)** | ✅ 1,218 | ❌ **not listed** | n/a |
| **Seattle (KSEA)** | ✅ 1,386 | ❌ **not listed** | n/a |

The complete Polymarket US weather city set is **5 stations only** — KNYC, KMIA,
**KMDW**, KLAX, KSFO (366 contracts each, target dates 2026-04-22 → 2026-06-29),
confirmed both in `contracts` and by enumerating live active climate slugs (no
`dfw`/`dallas`/`sea`/`seattle` keys exist). The primary `docs.polymarket.us`
weather FAQ lists the identical five. **Three of our four live cities cannot be
traded on Polymarket at all**, and the fourth (Chicago) is a different airport.

### 2. Settlement timing — same-day, *not* the ForecastEx problem

Today's KMDW/KMIA markets are for **today's** high and are **trading intraday
today** (last trades stamped 03:11 UTC on the event day). Per the primary weather
FAQ, settlement is the **NWS Daily Climate Report (CLI)** for the listed station,
occurring at **8:00 AM ET on the day following the contract date** (delayed to
11:00 AM ET if CLI and METAR disagree).

This is the **same information horizon as Kalshi**: we decide intraday on the
event day using late-morning observations + short-range HRRR, and the contract
resolves on the same NWS CLI. Unlike ForecastEx — whose *market* is for the
**next day's** high (forfeiting the same-day edge → ~0.4–0.6× Sharpe) — Polymarket
US lets us keep the full same-day edge. The only T+1 aspect is the **payout** (cash
released ~next morning), a negligible overnight capital-lock, not an
information-loss Sharpe decay. **Timing is green; the prior survey's dealbreaker
does not transfer to Polymarket US.**

### 3. Liquidity at size — the binding execution constraint

Live read-only L2 pull of today's body brackets (touch price 12–88¢, where edge
trades), walking the book to fill our **500-contract** unit:

| Station | Bracket | Touch bid¢ | Touch ask¢ | Buy-500 VWAP¢ | **Buy slippage¢** | Sell-500 slippage¢ |
|---|---|---|---|---|---|---|
| KMIA | 91–92 | 23 | 29 | 30.5 | **+1.5** | +8.9 |
| KMIA | 93–94 | 63 | 69 | 84.4 | **+15.4** | +3.4 |
| KMDW | 92–93 | 28 | 34 | 40.3 | **+6.3** | +3.6 |
| KMDW | 94–95 | 40 | 44 | 59.6 | **+15.6** | +5.6 |
| KMDW | 96–97 | 21 | 28 | 38.9 | **+10.9** | +1.9 |

Aggregate book characterization (today's 6 KMDW + 6 KMIA brackets):

| Metric | KMDW | KMIA |
|---|---|---|
| Median quoted spread | **4.0¢** (3–7) | **3.0¢** (1–6) |
| Median open interest | 287 sh | 778 sh |
| Total notional traded today | $42,947 | $79,358 |
| Median depth at touch (min of bid/ask side) | 4 sh | 6 sh |
| Brackets with ≥500 sh at **both** touches | **0 / 6** | **1 / 6** (deep tail only) |

The body brackets quote 3–7¢ wide (vs Kalshi KORD's typical **1¢**) and hold only
single-digit shares at the touch on the side you need. Per-bracket open interest
(~$150–400 at body prices) is the size of *one* of our units. Lifting 500
contracts costs **+1.5¢ to +15.6¢ (median ≈ +11¢)** of slippage — the deep-size
liquidity sits only in the dead ~1–4¢ tail brackets, which carry no edge. **At our
size, Polymarket US weather books cannot be taken without slippage that buries any
plausible edge.**

### 4. Fees — genuinely cheaper, but it doesn't matter

Authoritative US schedule (`docs.polymarket.us/fees`, exchange-wide eff.
2026-04-03): `Fee = Θ·C·p·(1−p)`, **taker Θ = 0.05**, **maker rebate Θ = −0.0125**
(maker is *paid*). This supersedes the international "weather 1.25%" figure the
prior survey flagged as uncertain. Per-contract cents vs the production Kalshi
formula (`max(1, ⌈0.07·p(1−p)·100⌉)` taker; ¼-rate maker, 1¢ floor):

| Entry p | Kalshi taker¢ | Kalshi maker¢ | **Poly taker¢** | **Poly maker¢ (rebate)** |
|---|---|---|---|---|
| 0.20 | 2 | 1 | 0.80 | −0.20 |
| 0.30 | 2 | 1 | 1.05 | −0.26 |
| 0.50 | 2 | 1 | 1.25 | −0.31 |
| 0.65 | 2 | 1 | 1.14 | −0.28 |
| 0.80 | 2 | 1 | 0.80 | −0.20 |

Polymarket US taker is **~0.75¢/contract cheaper** at mid-range; the maker side
swings **~1.3¢** (it *pays* you ~0.31¢ vs Kalshi *charging* 1¢). **Funding is fiat
— ACH/debit/wire/Apple Pay, 0% Polymarket fee, ACH withdrawal in 1–2 business days
via Plaid** — i.e. *no* crypto/gas/bridging friction (that is the international
platform only). So round-trip friction is **lower than Kalshi on every axis**.

Re-pricing the no-edge backtest (combined-00Z gross ≈ **−0.33¢/trade**) under each
venue confirms the thesis:

| Fee basis | Net P&L / trade |
|---|---|
| Kalshi taker (actual) | **−1.88¢** |
| Polymarket US taker | ≈ **−1.4¢** |
| Polymarket US **maker (rebate)**, idealized full-fill at mid | ≈ **−0.02¢ (breakeven)** |

Cheaper fees + the maker rebate take Miami from clearly-losing to **breakeven at
best** — and only under the unrealistic assumption of 100% maker fills at mid with
zero slippage. **The gross edge is still ≈ 0. Lower fees narrow the loss; they do
not manufacture edge.**

### 5. API — not a blocker (improved vs prior survey)

The regulated US venue exposes a **full institutional trading API**: REST +
**gRPC streaming** (market data *and* order-execution streams) + **FIX**.
Order endpoints exist — Create Order, Create Multiple (≤20), Cancel /
Cancel-Replace, Insert Order, Close Position, Get Open Orders — plus L2 order book
and BBO. Auth is Private-Key-JWT registration + **Ed25519 signing**, which our
`PolymarketClient` already implements (the snapshot cron authenticates read
endpoints daily; last snapshot 2026-06-29 03:17 UTC). A "place your first order in
5 minutes" quickstart and documented rate limits exist. Adding order placement is
a **code addition** to our existing client, not a new integration. This corrects
the prior survey's "no professional API" view (that described the old international
read surface).

### 6. Cross-platform arb — refuted concretely on the one fungible city

Miami (KMIA) is the **only** same-station match in our universe. Today's brackets
line up exactly across venues; latest quotes:

| Bracket | Kalshi bid/ask¢ | Poly bid/ask¢ | Kalshi mid | Poly mid | Mid gap |
|---|---|---|---|---|---|
| < 89 | 0 / 1 | 1 / 2 | 0.5 | 1.5 | −1.0 |
| 89–90 | 1 / 2 | 1 / 4 | 1.5 | 2.5 | −1.0 |
| 91–92 | 24 / 25 | 23 / 29 | 24.5 | 26.0 | −1.5 |
| 93–94 | 66 / 67 | 63 / 69 | 66.5 | 66.0 | +0.5 |
| 95–96 | 9 / 10 | 9 / 12 | 9.5 | 10.5 | −1.0 |

Mids agree within ~1–1.5¢ — but that gap is **not capturable**, because locking it
means crossing **both** spreads (Kalshi 1¢ + Polymarket 4–6¢). Worked example, the
91–92 bracket, the standard same-event lock (buy YES one venue + buy NO the other):

- Buy Kalshi YES @ 25¢ + buy Polymarket NO @ (100 − 23) = 77¢ → **102¢ > 100¢ →
  −2¢ before any fee.**
- Other direction: buy Poly YES @ 29¢ + buy Kalshi NO @ (100 − 24) = 76¢ → **105¢
  → −5¢.**

So there is **no riskless arb even at 1 contract**; at our 500-contract size the
Polymarket leg adds **+6 to +16¢** of slippage (Finding 3), burying it entirely.
The Chicago "arb" (Kalshi KORD vs Polymarket KMDW) is not arb at all but a
**basis trade across two airports** — corr 0.9978 but **1.3% of days diverge ≥ 5°F**
(7 of 543 days; largest +8°F), enough to flip a bracket. The cross-venue
mid-agreement is itself evidence the two books are already efficiently priced
against each other — consistent with the market-blend finding that the market
price carries 56–95% of predictive weight.

## External Context

- **Access is legal and live (medium-high confidence).** Polymarket acquired
  CFTC-licensed QCEX ($112M, July 2025); the CFTC granted an Amended Order of
  Designation (Nov 2025) enabling intermediated US access via FCMs; the **waitlist
  was dropped May 2026** [1][2][3]. KYC is mandatory (government ID, SSN, Plaid
  bank link, selfie) [4]. **Caveats to flag:** consumer access is **iOS-app-first**
  as of mid-2026 (Android/web "pending") — but the **partner/trader API path is
  operational** and is what we'd use [1][5]. The **international** platform stays
  geoblocked for US IPs under the 2022 CFTC $1.4M settlement [3]. **State-level
  legality is contested** — the CFTC is actively suing states (MN, CT, AZ, IL) that
  tried to restrict prediction markets; residency/state risk is real and worth
  monitoring [2].
- **Settlement source/timing** — NWS CLI per station; **8:00 AM ET T+1** (11:00 AM
  ET if METAR-inconsistent); if no data within a week, settles at last fair price
  [6]. City set = NYC/SF/Miami/Chicago-Midway/LA [6].
- **Fees** — `Fee = Θ·C·p(1−p)`, taker Θ=0.05 (max $1.25/100-lot), maker rebate
  Θ=−0.0125, exchange-wide since 2026-04-03; banker's-rounding to the cent [7].
- **API** — REST + gRPC + FIX; full order lifecycle; Ed25519 / Private-Key-JWT
  auth; documented rate limits [8].
- **Funding** — fiat: debit card, ACH, wire, Apple Pay; 0% Polymarket fee; ACH
  withdrawal to linked bank (Plaid) in 1–2 business days [9].
- **Liquidity (external corroboration)** — single daily-temperature city markets
  clear ~$300–400k/24h aggregate; Polymarket's own team caps the top-tier weather
  opportunity at ~$500k–2M/yr ("too low for a large fund") [10]. Consistent with
  our live read: ample for $250 notional in aggregate, **thin per-bracket at the
  touch**.

## Limitations & Threats to Validity

- **Single-day liquidity snapshot.** The slippage/depth numbers are one read on
  2026-06-29 (a Chicago/Miami heat regime). Depth varies by day, time-of-day, and
  volatility; a proper study needs multi-day order-book snapshots (we have **0**
  historical depth rows for Polymarket — only forward BBO). Direction is robust
  (single-digit touch depth, 3–7¢ spreads), magnitude is one draw.
- **Maker path unmeasured.** The "breakeven" maker case assumes full fills at mid.
  Real maker fill rate on Polymarket weather is unknown; posting forfeits fill
  certainty and re-introduces the same adverse-selection / timing questions we
  studied on Kalshi. The rebate is real; the fills are not yet demonstrated.
- **Gross edge ≈ 0 is the load-bearing assumption.** If true Miami gross edge is
  *negative*, no fee schedule or rebate rescues it. The fee re-pricing is
  necessary-not-sufficient.
- **Access caveats.** iOS-first consumer rollout and contested state legality could
  affect a programmatic/retail account; our read creds work today, but order-placement
  entitlement on the trading account is unconfirmed end-to-end (we did not place a test
  order — read-only by mandate).
- **Strike/station drift.** Today's KMIA brackets align with Kalshi's; this is not
  guaranteed every day, and only Miami aligns at all.
- **Config freeze (until 2026-07-10).** Everything below is a backlog *proposal*,
  not an action.

## Recommendation

**Verdict: WAIT (narrow), and NO for the live universe as defined.** Freeze-aware;
none of this touches trading config.

The binding constraint is **coverage + liquidity-at-size**, not the items the prior
survey worried about. Concretely:

1. **Do NOT add Polymarket for Dallas, Seattle, or Chicago-as-KORD.** Dallas and
   Seattle don't exist on Polymarket; Chicago is Midway, not O'Hare (a basis trade,
   not a venue swap). This is a hard NO regardless of fees.
2. **Do NOT pursue cross-platform arb as an EV thesis.** Refuted concretely on the
   only fungible city (Miami): the ~1–1.5¢ mid gap is smaller than the combined
   spreads, negative before fees, and obliterated by +6–16¢ slippage at size. Keep
   the existing read-only arb scan as opportunistic monitoring only.
3. **The single remaining "WAIT" path is Miami-only, maker-only, small-size — as a
   measurement pilot, not a deployment.** Polymarket US is now structurally
   attractive (same-day markets, fiat ACH, real API, taker −0.75¢ + maker rebate),
   so *if* a positive Miami gross edge is ever established, posting (not taking) to
   capture the −0.31¢ rebate while avoiding slippage is the only configuration that
   could clear our bar. It must still pass **walk-forward OOS Sharpe > 2.5 on
   realistic maker-fill-rate-adjusted execution** — and today's evidence says the
   gross edge it would need is ≈ 0.
4. **Before any of (3): start Polymarket order-book *depth* snapshots** (we have
   zero history) so the liquidity/maker-fill question can be answered on data, not
   a single read.

Distinguishing the two framings cleanly: Polymarket US **does not create edge** —
it is **cheaper and same-day**, which would *narrow the loss* on a Miami position
we already can't show is profitable. That is an improvement to the binding *fee*
constraint, against a strategy whose binding *edge* constraint remains unmet.

**Backlog entries appended** to `docs/backlog.md` (proposals only; respect CONFIG
FREEZE 2026-07-10).

## Sources

External (verified against source, accessed 2026-06-29):
1. Start Polymarket — *Is Polymarket Legal in the US? (Updated June 2026)* (waitlist dropped May 2026; iOS). https://startpolymarket.com/countries/united-states/
2. Cryptonews — *Is Polymarket Legal in the U.S. and Europe? June 2026 Guide* (CFTC state suits; status). https://cryptonews.com/cryptocurrency/is-polymarket-legal/
3. The Bulldog Law — *Polymarket Receives CFTC Approval to Resume US Operations* (QCEX; 2022 $1.4M settlement; geoblock). https://www.thebulldog.law/polymarket-receives-cftc-approval-to-resume-us-operations-after-years-offshore
4. CopyTradeInsider — *Polymarket KYC 2026* (gov ID, SSN, Plaid, selfie). https://www.copytradeinsider.com/blog/polymarket-kyc-requirements/
5. TradingVPS — *Polymarket US (2026 Complete Guide): Features, API Access*. https://tradingvps.io/polymarket-us-guide/
6. Polymarket US Docs — *Weather FAQs* (NWS CLI settlement source; 8 AM ET T+1 timing; 5-city station table). https://docs.polymarket.us/faqs/weather-faqs
7. Polymarket US Docs — *Fee Schedule* (Θ·C·p(1−p); taker 0.05 / maker rebate −0.0125; eff. 2026-04-03). https://docs.polymarket.us/fees
8. Polymarket US Docs — *Documentation index / API reference* (REST + gRPC + FIX; Create/Cancel/Insert Order; order book; Ed25519/JWT auth; rate limits). https://docs.polymarket.us/llms.txt
9. TradeTheOutcome — *How to Fund Polymarket Account (2026)* + Alphascope withdraw guide (debit/ACH/wire/Apple Pay; 0% fee; Plaid ACH 1–2 days). https://www.tradetheoutcome.com/fund-polymarket-account/
10. Laika Labs — *Polymarket Weather Markets: Trading Strategies Guide 2026* ($300–400k/24h; $500k–2M/yr cap). https://laikalabs.ai/prediction-markets/trade-polymarket-weather-markets

Internal (read-only; reproducible):
- `psql -d weather`: Polymarket coverage (5 stations × 366; KMIA both platforms, KORD≠KMDW, KDFW/KSEA Kalshi-only); price span (8.87M rows, 22 days, 2026-06-08→06-29); `orderbook_snapshots` (Kalshi only — **0** Polymarket depth rows); today's KMIA Kalshi-vs-Polymarket bracket/price table.
- Live read-only pull (`gateway.polymarket.us`, existing Ed25519 client): BBO + L2 book + stats for today's KMDW/KMIA brackets; book-walk cost-to-fill 500 (slippage +1.5↔+15.6¢; spreads KMDW 4¢/KMIA 3¢; 0–1 of 6 brackets hold 500 at both touches). Scratch scripts; nothing persisted.
- `scripts/analysis/cross_platform_arb.py` (read-only): KORD↔KMDW corr 0.9978, 1.3% days ≥5°F.
- Code: `src/weather_markets/polymarket.py`; `scripts/live_trade.py:370` (`kalshi_fee_cents`).
- Prior findings: venue survey 2026-06-20; no-edge backtest (combined-00Z gross ≈ −0.33¢, net −1.88¢); market-blend (56–95% market weight); per-city diagnostic (Miami robust).

## Evaluated and rejected

- **Trading Polymarket for Dallas / Seattle — rejected (impossible).** Neither city
  is listed on Polymarket US (5-city venue: NYC/Miami/Chicago-Midway/LA/SF).
- **Chicago venue-swap to Polymarket — rejected.** Polymarket Chicago = Midway
  (KMDW); our live edge settles on O'Hare (KORD). 1.3% of days diverge ≥5°F → a
  basis trade with tail risk, not a venue substitution.
- **Cross-platform arb as a strategy — rejected (refuted with numbers).** Only
  Miami is fungible; mid gaps (~1–1.5¢) < combined spreads; negative before fees;
  +6–16¢ slippage at 500. Keep read-only monitoring only.
- **Taking liquidity at unit 500 on Polymarket body brackets — rejected.** Median
  ≈ +11¢ slippage swamps edge and fee savings.
