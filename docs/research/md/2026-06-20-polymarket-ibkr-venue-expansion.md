# Should Polymarket and Interactive Brokers join the venue scope? A profitability survey

*2026-06-20 · status: draft*

## Question

Kalshi is currently the only live trading venue for the daily-high-temperature
stack (Chicago/KORD + Miami/KMIA live; others paper). The user asks whether to
expand the **scope of predictive-markets venues** to include **Polymarket** and
**Interactive Brokers**, and whether doing so would be *profitable or worth it*.

Per the scope confirmation, "Interactive Brokers" is surveyed two ways —
(a) **IBKR ForecastEx** event contracts, and (b) **CME weather derivatives**
traded *through* IBKR as a broker — and each candidate venue is judged on two
lenses: **(1)** as a new home for the existing GEFS+ECMWF+blend edge, and
**(2)** as an **arbitrage** counterparty to Kalshi.

Why it matters now: the project's stated goal is *"prove positive edge after
fees"* (CLAUDE.md, capital base $3,050), and the most rigorous internal result
to date is that **fees are the binding constraint** — the gross edge is ≈ 0 and
the ~2¢ Kalshi fee tips it net-negative. Any venue with a materially lower fee
attacks that constraint directly, which is the lens this paper applies.

## TL;DR / Verdict

**Add IBKR ForecastEx to scope as a paper/ingest pilot — medium confidence it is
"worth it," low confidence it is independently profitable.** ForecastEx is the
best structural fit: CFTC-regulated, the *only* prediction market with a
professional trading API, a **flat ~1¢/contract fee (≈ half Kalshi's ~2¢ in the
mid-range)**, and **same-station fungibility with Kalshi on 5 of 6 of our cities**
(all but Chicago). Continue the **Polymarket US** snapshot track already running,
but **do not trade it yet** (13 days of data, unverified US weather fee, crypto
rails, Chicago = Midway ≠ our O'Hare). **Reject CME weather futures** for this
strategy (monthly HDD/CDD index aggregates, not daily-high binaries — instrument
mismatch). **Cross-venue arbitrage is marginal**, not a strategy.

**Two caveats that cap the ForecastEx upside.** First, lower fees *narrow the
loss, they do not manufacture an edge*: on the n=1007 backtest the gross edge is
already ≈ −0.33¢, so swapping Kalshi's fee for ForecastEx's only moves
combined-00Z from −1.88¢ to −0.83¢/trade — **still negative.** Second, ForecastEx
daily-high markets are for the **next day's** high (T+1), trading the day before
resolution, so the same-day 14:46Z information edge our strategy relies on is
*forfeited* — a prior internal note (backlog 2026-06-12) estimates this at
**~0.4–0.6× the same-day Sharpe.** A cheaper, lower-information venue makes a real
edge more capturable; it cannot create one that isn't there.

## Methods & Data

**Internal (read-only; no `--live`, no DB writes).**
- `psql -d weather` SELECTs on `contracts`, `prices`, `orderbook_snapshots`,
  `live_trades`, `paper_trades` (row counts, date ranges, per-city, P&L).
- Code read: `src/weather_markets/{polymarket,stations,kalshi,kalshi_api}.py`,
  `scripts/{snapshot_polymarket_prices,backfill_polymarket_contracts,
  live_trade}.py`, `scripts/analysis/cross_platform_arb.py`.
- Ran `uv run python scripts/analysis/cross_platform_arb.py` (confirmed
  read-only) for the KORD↔KMDW basis and today's bracket comparison.
- Docs/memory: `docs/backlog.md`, the market-blend, no-edge (n≈1007), and
  fill-rate findings.
- Fee arithmetic computed from the production `kalshi_fee_cents` formula
  (`live_trade.py:325`) and published venue fees.

**External (web search + fetch, each claim verified against its source).**
- Polymarket US regulatory status (QCEX/CFTC), fee schedule, weather-market
  coverage/liquidity, settlement.
- IBKR ForecastEx: contract details, 10-city station list, fee mechanics, API.
- CME weather product specifications (HDD/CDD/CAT, contract unit, coverage).

## Internal Findings

### 1. Baseline — the edge we'd be porting is fee-bound, not skill-bound

Live Kalshi trading is tiny and noisy; the rigorous signal is the year-long
backtest.

| Metric (Kalshi, live) | Value |
|---|---|
| Live orders all-time | 28 (2026-06-04 → 06-19) |
| Live cities | 2 (KORD, KMIA) |
| Contracts filled / requested | 10,891 / 14,373 (75.8%) |
| Realized P&L all-time | **+$100.04** (KORD −$123.83, KMIA +$223.87) |
| Entry fees paid | $23.30 |

Live n is far too small for a P&L conclusion. The **no-edge backtest** (evaluated
at the production |edge| ≥ 10% threshold, fees included) is the real evidence:

| Config | n | Win % | Gross/trade | Net/trade | t-stat |
|---|---|---|---|---|---|
| EMOS combined 00Z @14:45 | 897 | 32.9% | ≈ −0.33¢ | **−1.88¢** | −1.52 |
| EMOS ECMWF 00Z @14:45 | 1,007 | 29.7% | — | **−3.14¢** | −2.74 |
| EMOS GEFS 00Z @14:45 | 944 | 30.8% | — | −3.47¢ | −2.93 |
| EMOS combined 12Z @18:45 | 944 | 17.1% | — | −4.24¢ | −4.43 |

**Conclusion that drives this whole paper:** combined-00Z gross P&L is ≈ 0
(95% CI on net includes zero); the ~1.5–2¢/trade fee is what pushes it negative.
Fees are the binding constraint.

The blend finding reinforces *where* the signal lives: a Benter-style logit blend
beats the raw model by 11–43% test Brier, with the **market price carrying
56–95% of the predictive weight** (β_model is *negative* for KAUS and KLAX). So
"porting the edge" to a new venue mostly means blending against *that venue's*
market price — you inherit that venue's efficiency, you don't carry alpha over.

### 2. Fee schedule by venue — the core comparison

Per-contract fee in cents, by entry price `p`. Kalshi from the production formula
`max(1¢, ⌈0.07·p·(1−p)·100⌉)`, entry only. ForecastEx = its $0.01 Yes+No pair
spread (≈ 0.5¢ your side at open, ~1¢ round-trip, flat). Polymarket US = stated
0.30% taker of traded value; Polymarket *international* weather category ≈ 1.25%
(shown for contrast — see fee-uncertainty caveat).

| p | Kalshi ¢ | ForecastEx ¢ | Polymarket US ¢ | Poly intl (wx) ¢ |
|---|---|---|---|---|
| 0.10 | 1 | 0.50 | 0.03 | 0.13 |
| 0.20 | 2 | 0.50 | 0.06 | 0.25 |
| 0.30 | 2 | 0.50 | 0.09 | 0.38 |
| 0.40 | 2 | 0.50 | 0.12 | 0.50 |
| 0.50 | 2 | 0.50 | 0.15 | 0.63 |
| 0.60 | 2 | 0.50 | 0.18 | 0.75 |
| 0.80 | 2 | 0.50 | 0.24 | 1.00 |
| 0.90 | 1 | 0.50 | 0.27 | 1.13 |

**Kalshi is the most expensive venue across the entire mid-range** (the 20–80¢
band where almost all our trades sit). ForecastEx is ~half; Polymarket is
sub-cent to ~1¢ depending on which schedule applies.

**But the fee saving does not flip the sign.** Re-pricing the combined-00Z
backtest (gross ≈ −0.33¢/trade) under each venue's fee:

| Fee assumption | Net P&L / trade |
|---|---|
| Kalshi (avg ~1.55¢) | −1.88¢ (actual) |
| ForecastEx (~0.5¢) | **−0.83¢** |
| Polymarket US (~0.15¢ @ p≈0.5) | **−0.48¢** |

Cheaper fees take combined-00Z from clearly-losing to *almost* break-even — a
real improvement against the binding constraint — but it remains negative because
the gross edge itself is ≤ 0. This is the honest center of the verdict.

### 3. Station fungibility matrix — who settles on what

Whether a new venue can host the *same* contract (for venue choice or arb) hinges
on settling on the *same NWS station*. ForecastEx publishes its station keys
(IBKR Campus); Kalshi mapping from `stations.py`; Polymarket from
`backfill_polymarket_contracts.py` slug parsing.

| City | Kalshi | ForecastEx | Polymarket US | Same station? |
|---|---|---|---|---|
| New York | KNYC (Central Park) | Central Park | KNYC | **All 3 match** |
| Los Angeles | KLAX | KLAX (airport) | KLAX | **All 3 match** |
| Miami | KMIA | KMIA (airport) | KMIA | **All 3 match** |
| Austin | KAUS | KAUS | — (not listed) | Kalshi ↔ FEx |
| Denver | KDEN | KDEN | — (not listed) | Kalshi ↔ FEx |
| **Chicago** | **KORD (O'Hare)** | **KMDW (Midway)** | **KMDW (Midway)** | **FEx ↔ Poly only; NOT Kalshi** |
| San Francisco | — (not Kalshi-live) | (airport) | KSFO | FEx ↔ Poly |

ForecastEx uses each city's **main airport** station (NYC = Central Park the
exception) — which **matches Kalshi on 5 of our 6 live/paper cities**. The lone
mismatch is **Chicago**: Kalshi settles on **O'Hare (KORD)**, while *both*
ForecastEx and Polymarket settle on **Midway (KMDW)**. Empirically (n=535 common
days) KORD↔KMDW correlation is 0.9978, mean Δ −0.77°F, but **~1.3% of days
diverge ≥5°F** — enough basis risk to flip a 1°F bracket. So Chicago is *not*
fungible across the O'Hare/Midway split, while NYC/LA/Miami are fungible across
all three venues.

### 3b. Timing/horizon mismatch — ForecastEx daily-high markets are next-day

This was flagged before any venue survey: a backlog note (2026-06-12, *"IBKR
ForecastEx as second venue"*) records that ForecastEx is a **genuinely separate
order book** (unlike Robinhood, which routes into Kalshi's book) but that its
contracts are **T+1/T+2 — no same-day** — and therefore expects only
**~0.4–0.6× the same-day Sharpe.** The external IBKR description corroborates it:
ForecastEx "daily markets for the **next day's** high temperatures will reappear
once each day" [11]. Our production strategy decides intraday on the *same* day
(KORD 14:46Z, KMIA 15:30Z), exploiting late-morning observations and short-range
HRRR. Porting that to a next-day market forfeits roughly a full forecast cycle of
lead-time information. So even setting fees aside, the *gross* edge on ForecastEx
should be **weaker** than the (already ≈0) same-day Kalshi gross edge — compounding
the "cheaper fees don't create edge" conclusion. The prior note's build trigger
("only if walk-book shows Kalshi depth caps us") also still applies: at
500-contract orders, Kalshi depth is not currently the binding constraint.

### 4. Polymarket integration already exists (snapshot-only)

| Polymarket US data (as of 2026-06-20) | Value |
|---|---|
| Contracts ingested | 1,680 (`platform='polymarket'`) |
| Cities | KMDW, KNYC, KMIA, KLAX, KSFO (336 each) |
| Price snapshot rows | 4,580,479 |
| Forward-snapshot history | **13 days** (2026-06-08 → 06-20), ~285/day |
| Orderbook-depth snapshots | **0** |
| Fee/gas modeling in code | **none** |

A `get_candlesticks()` method exists (`POST /v1beta1/report/trades/stats`,
commented "Polymarket DOES have this") but is **not called by any script and is
unverified** — if real, it could backfill history faster than the 13-day forward
crawl. The arb script (`cross_platform_arb.py`) is read-only and today found only
**one** overlapping threshold (78°F) quoted on both Kalshi-KORD and Poly-KMDW,
gap −0.5% — and those two aren't even fungible.

### 5. Operational footprint

The box is 7.6 GB RAM, **no swap**, with a prior OOM that downed prod Postgres.
ForecastEx ingestion would add one more snapshot cron (cost similar to the
existing Kalshi/Polymarket snapshotters — modest), but each new venue stacks I/O,
storage, and process pressure. Polymarket already adds 4.58M price rows in 13
days; a third venue compounds that. Not a blocker, but a real reason to add
venues *one at a time* and watch memory.

## External Context

**Polymarket is now a CFTC-regulated US venue.** Polymarket acquired the
CFTC-licensed exchange/clearinghouse **QCEX for $112M** (closed July 21, 2025)
[1][2]; the CFTC granted relaunch clearance on Sept 3, 2025 [3], and issued an
**Amended Order of Designation on Nov 25, 2025** enabling *intermediated* US
access through FCMs and traditional custody/reporting [4]. So US trading is now
legal and the code already authenticates to `api.polymarket.us` /
`gateway.polymarket.us`.

**Polymarket fees — schedule ambiguity (flagged).** The regulated US exchange is
reported at a **flat 0.30% taker / 0.20% maker rebate** [5]; the *international*
platform charges per category, with **Weather at ~1.25%** effective and fees
peaking at the 50/50 price, shrinking toward the 1¢/99¢ extremes [6][7]. Which
schedule applies to weather contracts on `polymarket.us` specifically is **not
confirmed from a primary US source** — a required verification before any trade.
Either way it is below Kalshi's 2¢ mid-range.

**Polymarket weather liquidity is ample for our scale.** Single daily-temperature
markets for major cities clear **$300k–$400k in 24h volume**; ~297 active
temperature markets; aggregate ~$1.7M [8][9]. Polymarket's own team notes weather
liquidity is "too low for a large fund," capping the top-tier opportunity around
**$500k–$2M/yr** [8] — but our 500-contract (~$250) orders are trivially absorbed,
so liquidity is *not* a binding constraint here. Settlement is the official
station reading [8]. Rails are pUSD/USDC on Polygon: no Polymarket deposit/
withdraw fee for pUSD, but bridging/gas and intermediary (Coinbase/MoonPay) costs
can apply [10] — operational friction a brokerage venue avoids.

**IBKR ForecastEx is the strongest structural fit.** ForecastEx is a
**CFTC-regulated DCM + DCO operated by IBKR** [11][12]. In Nov 2025 it launched
**daily-high-temperature markets for an initial 10 US cities** [11], and
temperature is now "the most frequently traded" forecast contract [13]. Stations
are each city's **main airport** (NYC = Central Park) settling on NWS Daily
Climatological Reports, rounded to the nearest whole °F [11]; central strikes are
seeded from the NWS National Blend of Models [11]. Fee mechanics: **no IBKR
commission**; Yes + No sum to **$1.01**, so the exchange takes **$0.01 per
contract pair** built into the spread — "the cheapest per-contract fee" among
prediction markets, ~$10 per 1,000 contracts vs **$20–$40 on Kalshi** [12].
Critically for this automated stack, ForecastEx is described as **the only
prediction-market platform offering programmatic trading through a professional
API** (TWS/Web API) [12], and is US-available, intl-not [12].

**CME weather futures are the wrong instrument.** CME lists **HDD/CDD/CAT**
contracts — *monthly and seasonal* indices of how far **daily-average** temp
deviates from a 65°F base, **contract unit $20 × index**, across 13 US cities
[14][15]. These are aggregate temperature-risk hedges (energy/utility flow), not
daily-high binaries. Our edge is a next-day **high-temperature bracket**
probability; it does not map onto a monthly degree-day index, the contract sizes
are large relative to $3,050 capital, and retail daily liquidity is thin despite
CME's market-maker framing. Only relevant if the project ever pivots to monthly
temperature exposure.

## Limitations & Threats to Validity

- **Fee saving ≠ edge.** The headline number (cheaper venue → less-negative P&L)
  rests on the combined-00Z gross edge being ≈ 0. If the true gross edge is
  *negative* (ECMWF-00Z gross is worse), no fee schedule rescues it. Cheaper fees
  are necessary-not-sufficient.
- **Polymarket US weather fee unconfirmed.** The 0.30% figure is from secondary
  reporting on the regulated exchange; the help-center per-category (1.25% wx)
  describes the international platform. The real `polymarket.us` weather fee must
  be read from a primary source before sizing any net-edge claim.
- **ForecastEx horizon mismatch (next-day, not same-day).** Its daily-high
  markets resolve the *next* day, so the same-day intraday information our edge is
  built on is forfeited; the prior internal estimate is ~0.4–0.6× same-day Sharpe.
  A like-for-like venue comparison must trade ForecastEx on the *previous* day's
  decision, not the 14:46Z one — the paper compares fees, not yet equal horizons.
- **ForecastEx has zero internal data.** No ingestion exists; its liquidity,
  spread width, fill behavior, and strike alignment with our brackets are
  *unmeasured*. "Cheapest fee" is worthless if spreads are wide or books are thin
  (IBKR itself notes a "smaller retail user base").
- **Strike alignment for arb is unverified.** Kalshi brackets, ForecastEx
  NWS-seeded strikes, and Polymarket thresholds need not coincide; arb requires
  the *same* threshold quoted on both venues simultaneously, net of *both* fees +
  slippage. The internal arb scan already returns near-zero gaps.
- **13 days of Polymarket data, 0 depth snapshots.** Far too little for a basis
  or fill study; the candlestick backfill path is untested.
- **Live n=28 / backtest regime.** Live P&L is noise; the backtest is one year on
  Kalshi-KORD/KMIA — venue-specific microstructure (ForecastEx/Polymarket) could
  differ.
- **Config freeze (until 2026-07-10).** Everything below is a backlog *proposal*,
  not an action.

## Recommendation

Ranked, freeze-aware. None of these touch trading config; all are
ingest/measurement/proposal steps.

1. **ForecastEx — highest-value next step (paper/ingest pilot).** Build a
   read-only ForecastEx quote ingester (mirror the Kalshi/Polymarket snapshotters)
   for our 5 airport-fungible cities, tagged `platform='forecastex'`. Then measure,
   on real data, the two things that decide it: **(a)** does its ~1¢ flat fee move
   any of our configs from net-negative to break-even/positive once blended
   against the ForecastEx market price; **(b)** what is the live Kalshi↔ForecastEx
   basis and spread on the fungible cities. ForecastEx's **professional API +
   half-fee + 5/6 same-station fungibility** make it the most credible path to
   attacking the fee constraint — *if* a positive gross edge exists to capture.
   **Measure on the next-day (T+1) horizon**, not the same-day 14:46Z decision, so
   the test is honest — go in expecting ~0.4–0.6× same-day Sharpe, and build live
   only if the paper shows a positive *net* edge on that horizon.
2. **Polymarket US — continue snapshotting, do not trade yet.** Keep accumulating
   (target ≥ 60–90 days + start orderbook-depth snapshots), and **confirm the
   primary `polymarket.us` weather fee** before any net-edge work. Defer trading
   until data depth and fee certainty exist; the crypto rails add friction a
   brokerage venue avoids.
3. **Cross-venue arb — opportunistic monitoring only, not a strategy.** Extend the
   arb scan to the *fungible* pairs (NYC/LA/Miami three-way; Chicago-Midway
   FEx↔Poly) once ForecastEx is ingested. Treat any gap > combined fees + slippage
   as a rare bonus, not an EV thesis — current scans show near-zero gaps and
   strike alignment is unproven.
4. **CME weather futures — reject for this strategy.** Instrument mismatch
   (monthly degree-day index vs daily-high binary); revisit only if the project
   pivots to monthly temperature risk.

**Backlog entries appended** to `docs/backlog.md` for items 1–4 (proposals, not
actions; respect CONFIG FREEZE 2026-07-10).

## Sources

External (verified against source):
1. PR Newswire — *Polymarket Acquires CFTC-Licensed Exchange and Clearinghouse QCEX for $112 Million*. https://www.prnewswire.com/news-releases/polymarket-acquires-cftc-licensed-exchange-and-clearinghouse-qcex-for-112-million-302509626.html
2. Crypto Briefing — *Polymarket gains CFTC approval to launch regulated US prediction markets*. https://cryptobriefing.com/polymarket-secures-cftc-nod-us-market-qcx-llc-acquisition-2/
3. RareEvo — *Polymarket Secures CFTC Approval for Regulated U.S. Relaunch*. https://rareevo.io/rare-network-news/polymarket-cftc-approval-us-return
4. PR Newswire — *Polymarket Receives CFTC Approval of Amended Order of Designation (intermediated US access)*. https://www.prnewswire.com/news-releases/polymarket-receives-cftc-approval-of-amended-order-of-designation-enabling-intermediated-us-market-access-302625833.html
5. QuantVPS — *Polymarket Is Back: Prediction Market Re-Enters the U.S.* (US exchange 0.30% taker / 0.20% maker rebate). https://www.quantvps.com/blog/polymarket-back-prediction-market-us-four-year-hiatus
6. Polymarket Help Center — *Trading Fees* (per-category, peak at 50/50; geopolitics free). https://help.polymarket.com/en/articles/13364478-trading-fees
7. Market Math — *Polymarket Fees Explained: Per-Category Trading Fees* (Weather 1.25%). https://marketmath.io/blog/polymarket-fees-explained
8. Laika Labs — *Polymarket Weather Markets: Trading Strategies Guide 2026* ($300–400k/day; $500k–2M/yr cap). https://laikalabs.ai/prediction-markets/trade-polymarket-weather-markets
9. Polymarket — *Weather / Temperature predictions* (297 active markets; ~$1.7M aggregate). https://polymarket.com/weather
10. Polymarket Help Center — *Trading Fees* (pUSD deposit/withdraw, Polygon gas/bridging). https://help.polymarket.com/en/articles/13364478-trading-fees
11. Interactive Brokers Campus — *Daily High Temperature Markets at ForecastEx* (10 cities, station keys, NWS settlement, NBM strikes). https://www.interactivebrokers.com/campus/traders-insight/ibkr-climate-energy/daily-high-temperature-markets-at-forecastex/
12. Market Math — *ForecastEx (Interactive Brokers) Review 2026* (CFTC DCM/DCO; $0.01/contract; API; US-only; $10 vs $20–40/1,000 vs Kalshi). https://marketmath.io/platforms/forecastex
13. Artemis.bm — *Weather the most frequently traded forecast contracts at Interactive Brokers*. https://www.artemis.bm/news/weather-the-most-frequently-traded-forecast-contracts-at-interactive-brokers-founder/
14. CME Group — *Hedging Weather Risk / Overview of Weather Markets* (HDD/CDD/CAT, $20 × index, 18 cities). https://www.cmegroup.com/education/lessons/hedging-weather-risk.html
15. CME Group — *Weather Futures and Options fact card*. https://www.cmegroup.com/trading/weather/files/weather-fact-card.pdf

Internal (read-only; reproducible):
- `psql -d weather` SELECTs: `contracts` (platform split, 1,680 Polymarket / 29,051 Kalshi), `prices` (4.58M Poly snapshot rows, 13 days), `live_trades` (28 orders, +$100.04), `paper_trades` (21,734 rows).
- `uv run python scripts/analysis/cross_platform_arb.py` — KORD↔KMDW basis (corr 0.9978; 1.3% days ≥5°F) + today's bracket comparison.
- Code: `src/weather_markets/{polymarket,stations,kalshi,kalshi_api}.py`; `scripts/{snapshot_polymarket_prices,backfill_polymarket_contracts,live_trade}.py` (`kalshi_fee_cents` line 325).
- Findings: market-blend (11–43% Brier, 56–95% market weight), no-edge (n≈1007, fees binding), fill-rate (KORD 86.5% / KMIA 62.7%); `docs/backlog.md`.

## Evaluated and rejected

- **CME weather futures via IBKR — rejected.** Monthly/seasonal HDD/CDD/CAT index
  ($20 × index), not daily-high binaries. Instrument and horizon mismatch; large
  notional vs $3,050 capital; revisit only on a pivot to monthly temperature risk.
- **Treating cross-venue arb as a standalone strategy — rejected.** Fungible only
  on NYC/LA/Miami (+ Chicago-Midway FEx↔Poly); requires coincident strikes and
  gap > combined fees+slippage; internal scans show near-zero gaps. Keep as
  opportunistic monitoring, not an EV thesis.
- **Trading Polymarket now — rejected (premature).** 13 days of data, 0 depth
  snapshots, unconfirmed US weather fee, crypto-rail friction. Continue
  snapshotting first.
