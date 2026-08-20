# Weather-Trading Project — Portable Context Brief

*A self-contained summary to paste into a fresh AI assistant that has no access to this
codebase. No secrets included. Current as of 2026-07-18.*

---

## 1. What this is

A **quantitative trading system for weather prediction markets**. It forecasts the **daily
high temperature** for specific U.S. cities, converts those forecasts into probabilities for
each temperature "bracket" contract on **Kalshi** (a CFTC-regulated prediction-market
exchange), compares them to the live market price, and **places real-money orders** when it
sees an edge. It runs autonomously via cron jobs on a cloud Linux server and is monitored
through a web dashboard.

- **Operator:** a solo quant (based in Miami, FL). This is a real-money system, small size.
- **Goal:** prove a positive, repeatable edge *after fees*. There is no fixed return/Sharpe
  target — the bar is "is there real edge, and can it scale."
- **Capital:** ~$3,050 deposited (+$14.99 referral credit), ~$1,530 realized P&L to date,
  $1,400 recently withdrawn; account value ~$4,570.

## 2. The core idea / strategy

1. **Ensemble weather forecasts.** Ingest numerical weather prediction (NWP) ensembles:
   - **GEFS** (NOAA Global Ensemble Forecast System, ~31 members)
   - **ECMWF / IFS** (European model, ~50 members, "open data" feed)
   - **HRRR** (NOAA High-Resolution Rapid Refresh, 1 deterministic run)
   Data is pulled as GRIB files (via the `herbie` Python library) for the grid point nearest
   each city's official weather station.

2. **EMOS calibration.** Raw ensembles are biased and mis-dispersed, so they're calibrated
   with **EMOS** (Ensemble Model Output Statistics — non-homogeneous Gaussian regression)
   over a **rolling 45-day training window**. Output: a calibrated Gaussian (mean μ, sigma σ)
   for tomorrow's high. Model variants: `combined` = GEFS+IFS; `combined_hrrr` = +HRRR.

3. **Bracket probabilities.** Kalshi lists daily-high contracts as temperature **brackets**
   (e.g. "88–89°F", "≥95°F"). The calibrated Gaussian is integrated over each bracket to get
   the model's probability that the day's high lands there.

4. **Benter-style market blend.** The model probability is blended (logistic/Benter-style)
   with the **market-implied probability** (from the Kalshi mid price). This consistently
   beats the raw model — the market does most of the predictive work.

5. **Edge → trade.** Compute edge = (model or blended prob) − (market prob). Fire when
   |edge| ≥ a per-city threshold. Buying "NO" is the same as shorting "YES."

6. **Execution.** Orders are limit orders. A per-city "smart" rule decides whether to **post**
   inside the spread (maker, cheaper fee, may not fill) or **cross** the spread (taker, fills
   now, pays up). Risk controls: per-city daily-loss limit, cumulative-drawdown kill switch,
   max open contracts, and a spread-regime guard.

**The single most important empirical finding:** the market is **highly efficient**. The edge
is a thin margin layered on top of an already-good market price, not a large mispricing.
"Forecast skill ≠ trading edge" — being more accurate than a competing model does not imply
beating the *market's* price. Multiple attempts to find a bigger edge by being "smarter,
bigger, or faster" all failed (see §6). The realistic lever for growth is **breadth** (more
cities, more venues), not a cleverer model.

## 3. Tech stack

- **Language:** Python, run via **`uv`** (the package manager — always `uv run python ...`,
  never call the venv Python directly).
- **Database:** Postgres / TimescaleDB, database name `weather`. Local peer auth (`psql -d
  weather`, no password). Core tables: `forecasts`, `observations`, `contracts`, `prices`,
  `orderbook_snapshots`, `live_trades`, `paper_trades`, `account_equity_snapshots`,
  `polymarket_orderbook_snapshots`.
- **Market API:** Kalshi REST v2 (portfolio/balance, positions, orders, fills, settlements,
  deposits, withdrawals; market orderbooks; order placement). A WebSocket feed provides live
  top-of-book marks.
- **Dashboard:** FastAPI backend + **vanilla JavaScript** frontend (no framework). Three tabs:
  Live, Backtest, Accounting. Served by uvicorn.
- **Ops:** Cron-driven on a cloud Linux box with **7.6 GB RAM and NO swap** (memory pressure
  is a real constraint — multiple heavy processes can OOM-kill Postgres). Long jobs run in
  `tmux`. All times in the system are **UTC**.

## 4. Architecture / daily pipeline

Cron entrypoints (in `scripts/`) run through the day (all UTC):
- **Ingest:** GEFS / ECMWF / HRRR forecast ingests (several runs/day with retries), plus NWS
  daily observations (the ground-truth highs/lows used to settle and to calibrate).
- **Discovery:** pull the day's live Kalshi contracts.
- **Snapshots:** Kalshi price + full orderbook depth every 5 min (and a parallel Polymarket
  orderbook snapshotter, read-only, for future venue comparison).
- **Paper trading:** `paper_trade_log.py` logs the signal for every city every day (including
  cities not traded live) — this is the research/backtest record.
- **Live trading:** `live_trade.py --city <X> --live` places real orders per city at that
  city's decision time. Config lives in a `CITY_CONFIG` dict (per-city models, thresholds,
  sizing, risk limits, decision time, active flag).
- **Fill monitoring & reconciliation:** `monitor_fills.py` tracks/cancels resting orders;
  `reconcile_live_trades.py` pulls settlements and computes realized P&L.
- **Health checks** and GRIB cache cleanup (disk fills fast).

Library code lives in `src/weather_markets/` (ingest, emos, aggregation, blend, evaluation,
kalshi API client, stations, db). The dashboard is in `dashboard/`.

## 5. Current live state (2026-07-18)

- **Live cities:** Chicago (KORD), Miami (KMIA), Dallas (KDFW), Phoenix (KPHX).
- **The deploy bar:** a city goes live only if it clears **walk-forward out-of-sample
  Sharpe > 2.5** on realistic execution. Chicago + Miami cleared a robustness screen.
  **Dallas (2026-06-22) and Phoenix (2026-07-10) are explicit *operator overrides*** of that
  bar — live on real money despite not clearing it, to gather live-fill data at small size.
- **Config style:** Chicago/Dallas use a UNION rule (raw edge ≥ 25% OR blended edge ≥ 10%);
  Miami is blend-only ≥ 10%; Phoenix is raw-only ≥ 20% and currently **post-only**.
- Seattle is watch/paper-only (below the bar); LA and Vegas were rejected.

## 6. What's been tried (so the new assistant doesn't re-suggest dead ends)

All of these were tested and came back **negative** — the market is efficient and the edge is
thin:
- **Bigger size / capacity:** book depth caps out ~500–700 contracts per city; can't scale by
  size alone.
- **Re-quoting** unfilled maker orders: hurts (chases adverse selection).
- **Entering earlier** in the day: edge doesn't decay into the decision, so no gain.
- **Intraday fair-value / cash-outs:** our fair value does not beat the market intraday.
- **Speed / latency edge:** the market reprices public model releases essentially instantly.
- **Foundation time-series models (TimesFM, Kronos):** worse than NWP+EMOS on short-range
  temperature — skip.
- **Execution mode (post vs cross):** *unresolved* — the historical fill model couldn't be
  trusted (it never correctly predicted a non-fill), so no config change was justified.

**Open leads / roadmap:** grow via **breadth** — additional venues (ForecastEx looks best:
½ the Kalshi fee, real API, trades through resolution day; Polymarket is geoblocked for U.S.
persons under CFTC rules and was NOT circumvented) and additional cities. A structural
"favorite-longshot bias" (passive market-making on ≥50¢ contracts) is a noted lead.

## 7. The dashboard (3 tabs)

- **Live:** per-city cards (realized/unrealized/today P&L + risk dials), a cumulative-P&L hero,
  current positions, today's signals→fills, open orders, recent fills, cron health, and a
  **rolling cumulative-P&L chart** sourced from Kalshi settlements (the authoritative ledger).
- **Backtest:** interactive strategy simulator. The JS sim and a Python sim
  (`sim_python.py`) are kept **byte-for-byte in parity** by a test — any change to one must
  change the other.
- **Accounting:** tax + capital-flow view (Miami/FL operator). Pulls **live** deposits and
  withdrawals from Kalshi (no hard-coding). Shows: capital flow (all money in/out → "net
  external capital"), YTD realized P&L (net of fees), an estimated **tax reserve** (Florida
  state = $0; user-adjustable federal rate; prediction-market federal treatment is legally
  unsettled, shown as an estimate with a disclaimer), and "**safe to withdraw now**" =
  cash − tax reserve − open-order margin. A daily equity-snapshot table feeds a forward
  equity curve.

## 8. Domain gotchas worth knowing (these are non-obvious and have caused bugs)

- **Price convention:** Kalshi prices are cents 0–100; YES + NO = 100. The **cost of a NO
  contract = 100 − (YES price)**. Internally the code often stores a "YES-equivalent" price
  for consistency, so a NO position bought at 77¢ may be recorded/displayed as 23¢ YES-eq.
- **Kalshi fills semantics:** a **NO position's opening fills are reported with
  `action="sell"`** (buying NO is mechanically shorting YES on the YES-denominated book).
  Naively assuming "buy = open" for both sides is wrong and silently zeroes NO positions.
- **Two ledgers don't match:** the Kalshi `fills` feed is capped/mis-signed for this account;
  the **`settlements` feed is authoritative** for realized P&L. Use settlements, not fills,
  for P&L history.
- **Reconciliation identity:** `account_value = (deposits + credits) − withdrawals + P&L`.
  Withdrawing money is **not** a P&L event — omitting the withdrawal term makes P&L look worse
  by the withdrawn amount.
- **Settlement timing:** contracts settle the *day after* the trade day, so "today's realized
  P&L" is really yesterday's trades settling.
- **Taxes:** withdrawing from a taxable account is not itself a taxable event; realized gains
  are taxed in the year realized regardless of withdrawal. Florida has no state income tax.

## 9. Conventions / hard rules (if the assistant will touch the code)

- Run Python via **`uv run`** (never the venv binary directly).
- **Live trading is real money** — `live_trade.py --live` places orders; treat with care.
- **Secrets** (Kalshi private key, DB URL, API secrets) live in gitignored files and are
  **never committed or shared**.
- **Crontab** is edited via a tracked `docs/crontab.txt` file, then installed — never edit the
  live crontab directly.
- The **JS↔Python backtest sim must stay in parity** (enforced by a test).
- **Commit only when explicitly asked.**
- Long-running jobs go in `tmux`, line-buffered. Mind the **no-swap 7.6 GB box** — don't leave
  multiple heavy dev servers running.

---

*This brief is intentionally free of credentials, keys, and account identifiers. It describes
the system's design and current state so an external assistant can reason about strategy,
math, code, weather modeling, Kalshi mechanics, or tax questions without repo access.*
