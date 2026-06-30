# ForecastEx daily-high contracts: do they trade INTO their resolution day?

**Date:** 2026-06-30
**Branch:** `research/forecastex-resolution-day`
**Scope:** One decisive question — does an IBKR ForecastEx daily-high-temperature
contract for calendar day D keep trading (with a live order book) *during* day D
(its resolution day), or does trading close before D begins (forcing a T-1 commit)?
**Method:** Read-only web research against official IBKR Campus / ForecastEx /
ForecastEx regulatory sources. No IB Gateway, no orders, no account actions.

---

## BINARY VERDICT

> **CASE A — ForecastEx daily-high contracts trade THROUGH their entire resolution
> day, right up to 11:59 PM local time on day D. The "next-day / T+1" label in our
> prior survey was WRONG about the trading window: it conflated T+1 *settlement*
> (cash payout) with the *trading* window. Same-day intraday trading IS available,
> and IBKR's own docs say "much of the trading action" happens on the resolution day.**
>
> **Confidence: HIGH** for the trading-window question (contract spec is explicit).
> **Confidence: MEDIUM** for resolution-day-morning *liquidity/depth* at our specific
> stations (docs confirm a live order book exists and that resolution-day is the
> high-volume day, but actual morning depth per station is not observable from public
> docs — see "What's still unverified").

**Single best citation:** ForecastEx **DH (Daily High) Contract Terms & Conditions**
(regulatory filing): *"Last Trading Time is 11:59 PM local time on the date listed
in the Contract"* and *"Expiration Time is the same as Resolution Time … the time
the Climatological Report (Daily) is released."*
→ https://data.forecastex.com/regulatory/DHTermsandConditions.pdf
Corroborated by IBKR Campus: *"On the day of expiration, when much of the trading
action will occur …"*
→ https://www.interactivebrokers.com/campus/traders-insight/ibkr-climate-energy/daily-high-temperature-markets-at-forecastex/

**Bottom line for strategy:** The horizon-mismatch caveat that capped ForecastEx at
~0.4–0.6× same-day Sharpe in the 2026-06-20 survey **does not hold.** ForecastEx
supports the same same-day intraday window Kalshi does. Combined with its real
professional API, ~half Kalshi's fee, and 5/6 same-station match, ForecastEx is a
credible same-day venue — promote it from "next-day pilot" to "same-day candidate."

---

## Q1. Contract lifecycle (listing / last-trading-time / where it falls)

| Element | Finding | Source |
| --- | --- | --- |
| **(a) When listed** | The market for day D's high is (re)listed ~the day before. IBKR: *"ForecastEx daily markets for the next day's high temperatures will reappear once each day."* This is a **listing/seeding** statement (tomorrow's contract appears, gets a central strike + seed probabilities), **not** a trading-window restriction. | IBKR Campus [11] |
| **(b) Last trading time / expiration** | **Last Trading Time = 11:59 PM *local* time on the date listed in the contract (= day D).** Expiration Time = Resolution Time = when the NWS Daily Climatological Report for day D is released. | ForecastEx DH Terms & Conditions; Trading Schedule |
| **(c) Is last-trading-time DURING day D?** | **YES — explicitly.** Trading runs the full length of day D up to 23:59 local. The settlement read itself is the *"daily maximum of [the] 5-minute moving average between 00:00 and 23:59 local time"* — so the outcome is not even determined until the end of day D, which by construction requires the contract to remain tradeable through day D. | ForecastEx DH Terms; IBKR Campus "Contract Details" |

**Why the prior survey got this wrong:** It read *"daily markets for the next day's
high … will reappear once each day"* as "you can only trade the day before resolution."
In fact that sentence describes *what the contract is about* (tomorrow's high, listed
today) — and the contract then continues trading all the way through that target day.
IBKR's "Considerations" section removes all doubt: *"On the day of expiration, when
much of the trading action will occur, forecasting the high … involves observing how
the atmosphere is changing relative to [the models'] most recent runs"* — i.e. the
exact same-day, short-lead, intraday read our edge is built on, on ForecastEx itself.

## Q2. Resolution-day liquidity (is there a live book on the resolution morning?)

- **A live order book exists.** ForecastEx is an order-driven binary market: traders
  post Yes/No limit orders (Day / IOC / GTC), with bid/ask and an order ticket showing
  limit price + size; positions are opened/closed by buying Yes or No. (IBKR trading
  lesson; ForecastTrader UI.)
- **Resolution-day is the *high-volume* day per IBKR:** *"On the day of expiration …
  much of the trading action will occur."* So liquidity is, if anything, concentrated
  exactly when we want it.
- **Trading is ~24/7:** Trading Schedule = 12:00am–12:00am CT all seven days (only a
  ~15-min Wednesday 2:00–2:15am CT maintenance gap) — so the resolution-day morning is
  unambiguously inside trading hours.
- **CAVEAT (the honest gap):** Public docs confirm a book *exists* and that resolution-day
  is the active day, but they do **not** show actual **depth at our specific stations on
  the resolution-day morning.** ForecastEx is young (launched Nov 2025) and retail; book
  could be thin or "open but empty" at, say, 14:46Z for KMDW. **This is the one thing
  that needs live data** — resolve it with the read-only snapshotter (see next steps),
  NOT by assuming. Classify current state: **resolution-day-morning depth = UNKNOWN,
  needs live feed.** (Window availability itself = KNOWN-GOOD.)

## Q3. Settlement vs trading timing (the conflation the prior survey made)

- **Trading window:** through 11:59 PM local on day D (above).
- **Settlement (cash payout):** per ForecastEx Rule 603(b)(3) — settles **1:00 PM CT on
  the resolution day** if the Resolution Time is before 12:00 PM CT, otherwise **1:00 PM
  CT the following day.** For daily-high contracts the Daily Climatological Report for
  day D posts after the day ends, so the cash typically lands **T+1**.
- **Resolution:** at release of the NWS Daily Climatological Report for day D.

**So the "T+1" in the prior survey is the SETTLEMENT (cash) timing, which is real — but
it does NOT restrict when you can trade.** You buy/sell during day D at the sharpest-forecast
window; the contract resolves on the official report and the cash nets out ~T+1. This is
operationally identical to how a same-day Kalshi position settles after the day's high prints.
The survey's mistake was treating "settles next day" as "can't trade same day."

## Q4. Station keys (5/6 match + Chicago = Midway)

Full ForecastEx station table (verbatim from IBKR Campus "Contract Details"):

| City | ForecastEx NWS Station Key | Our Kalshi station | Match? |
| --- | --- | --- | --- |
| Austin | **KAUS** | KAUS | ✅ |
| Chicago | **KMDW (Midway)** | **KORD (O'Hare)** | ❌ (the 1 mismatch) |
| Dallas | **KDFW** | KDFW | ✅ |
| Denver | KDEN | (not in our live universe) | — |
| Houston | KHOU | (not traded) | — |
| Los Angeles | **KLAX** | KLAX | ✅ |
| Miami | **KMIA** | KMIA | ✅ |
| New York City | **KNYC (Central Park)** | KNYC | ✅ |
| San Francisco | **KSFO** | KSFO | ✅ |
| Seattle | KSEA | (monitor only) | — |

- **Chicago = KMDW (Midway), NOT KORD (O'Hare) — CONFIRMED** (lat/lon 41.78417, -87.75528 = Midway).
  This is the single station mismatch vs our Kalshi book (we trade Chicago on KORD).
- **5/6 same-station match confirmed:** of our six cities (KORD/KMIA/KNYC/KLAX/KSFO + Dallas/KDFW),
  five settle on the identical NWS key on ForecastEx (KMIA, KNYC, KLAX, KSFO, KDFW); only Chicago differs.
- Note NYC = Central Park (KNYC), as on Kalshi — matches.

---

## What's still unverified (be explicit)

1. **Resolution-day-morning order-book depth at our stations.** The decisive remaining
   unknown. Docs prove the window + that a book exists + that resolution-day is the active
   day; they don't prove there's tradeable size at ~14:46Z / 15:30Z for KMDW/KMIA/etc.
   **Resolve with the planned read-only ForecastEx snapshotter** (mirror the Kalshi/Polymarket
   snapshotters), tagged `platform='forecastex'`, sampling the resolution-day morning for our
   cities for ~2–3 weeks. Until then, treat depth as unknown, not as a "yes."
2. **DH Terms PDF rendered 404 through the fetch tool but is real** — its exact text
   ("Last Trading Time is 11:59 PM local time on the date listed in the Contract";
   "Expiration Time is the same as Resolution time"; Rule 603(b)(3) settlement) was
   captured via web search of the official `data.forecastex.com/regulatory/` filing.
   A human should open the PDF once to eyeball the spec table verbatim before any build.
3. **API access from this box (Germany).** ForecastEx is US-only; live ingestion will need
   a US-eligible account/connection. Window/spec facts above stand regardless of geo.

## Sources (official / primary)

- ForecastEx **DH Contract Terms & Conditions** (Last Trading Time, Expiration=Resolution):
  https://data.forecastex.com/regulatory/DHTermsandConditions.pdf
- ForecastEx **Trading Schedule** (~24/7 CT): https://www.forecastex.com/schedules
- IBKR Campus — **Daily High Temperature Markets at ForecastEx** (station table, "day of
  expiration … much of the trading action", 5-min-max 00:00–23:59 local settlement, NBM strikes):
  https://www.interactivebrokers.com/campus/traders-insight/ibkr-climate-energy/daily-high-temperature-markets-at-forecastex/
- IBKR Campus — **Trading ForecastEx Event Contracts** (order ticket: limit price, size,
  Day/IOC/GTC; "last time and date for trading … listed clearly"):
  https://www.interactivebrokers.com/campus/trading-lessons/trading-forecast-ex-event-contracts/
- ForecastEx — How Forecast Contracts Work / FAQ (Yes+No=$1.01, settle $1/$0):
  https://forecastex.com/about/how-forecast-contracts-work · https://forecastex.com/faq
- Market Math — ForecastEx review (CFTC DCM/DCO; $0.01/contract; professional API; US-only):
  https://marketmath.io/platforms/forecastex
- Prior survey being corrected: `docs/research/md/2026-06-20-polymarket-ibkr-venue-expansion.md` §3b.
