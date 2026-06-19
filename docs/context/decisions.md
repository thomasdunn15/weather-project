# Decisions & rationale

> Why the project is built the way it is. Audience: agents. Last verified: 2026-06-19. Items marked *(inferred)* are not written down anywhere — confirm with the user before relying on them.

## TL;DR
- Models: GEFS + ECMWF/IFS for breadth (81 members), **HRRR added per-city only where it backtests better** (Chicago yes, NYC no). 00Z init (12Z tested → no edge).
- Venue: **Kalshi** (CFTC-regulated, resolves on CF6, live-traded). **Polymarket is research/dashboard-only** (not fungible with Kalshi, no historical-price API).
- Method: **EMOS** (raw ensembles are biased/under-dispersed) + **Benter blend** (the single biggest win).
- Product: **daily-HIGH** temp contracts (lows tested → "decisively negative"); resolution source is **CF6** (not ASOS).

## Weather models
| Model | Members | Why |
|---|---|---|
| GEFS | ~31 | Free NOAA operational ensemble (Herbie/S3); the baseline. |
| ECMWF / IFS | ~50 | "Generally the most accurate operational model"; combining models beats any single one → 81-member multi-model ensemble for EMOS. |
| HRRR | 1 (deterministic) | Added **per-city by backtest**: Chicago combined→combined_hrrr gave **+$11.12/trade (+43%, p 0.013→0.003)**; for NYC it was noise. So Chicago=`combined_hrrr`, Miami/others=`combined`. |
- **00Z init:** standard, gives lead time before the trade window; **12Z was tested and showed no edge after fees**, so the project pivoted to 00Z.
- **Why not GFS / NAM / RAP** — *(inferred)* never evaluated/recorded; GFS is redundant with GEFS, NAM/RAP are short-range mesoscale. Not documented as rejected.

## Trading venue: Kalshi vs Polymarket
- **Kalshi (live):** CFTC-regulated event exchange; daily-high contracts resolve on the **NWS CF6** report (matches our observation source exactly).
- **Polymarket (research-only):** client + snapshot/backfill scripts + `scripts/analysis/cross_platform_arb.py` exist, but it is **not traded**. Reasons in-repo: its Chicago market is **KMDW (Midway), not KORD (O'Hare)** — ~14 mi apart, highs differ 1–3°F, so contracts are **not fungible**; and Polymarket has **no historical-price endpoint** (only forward snapshots), which hurts backtest realism.
- **Why Kalshi was chosen over Polymarket for live** — *(inferred)*: regulatory clarity + CF6 resolution match + Kalshi came first (Polymarket integration landed 2026-06-08, after live trading was already on Kalshi). Not explicitly stated.

## Method: EMOS + Benter blend
- **EMOS** (rolling 45-day non-homogeneous Gaussian regression): raw ensembles are biased and under-dispersed; EMOS corrects mean + spread. Window 45d chosen empirically (30–90d sweep didn't change annual CRPS — not load-bearing).
- **Benter blend** (logistic blend of model_P and market_P): the **single biggest improvement** — 11–43% test-Brier gain across cities; the **market carries 56–95%** of the weight; **β_model is negative for KAUS/KLAX** (model anti-informative there). Named after Bill Benter's racing model. See [strategy.md](strategy.md) and memory `project_market_blend_finding`.

## Product choices
- **Daily HIGH** contracts (not lows): a lows experiment was **"decisively negative"** and removed; precipitation not tested.
- **CF6, not ASOS/METAR**, as the observation/resolution source: Kalshi resolves on CF6, and a **0.3°F** discrepancy at a **2°F** bin boundary flips resolution — training on a different source would make backtested edge fictional.
- **Why Chicago & Miami first** — *(inferred)*: geographic-regime diversity + major long-history stations + Kalshi availability; the actual selection reason isn't documented.

## Sources
- [Research.md](../../Research.md) (root, local-only), [../reference/roadmap.md](../reference/roadmap.md), [../reference/investor-overview.md](../reference/investor-overview.md), [../decisions/](../decisions/), `git log` (e.g. HRRR switch in `scripts/live_trade.py` CITY_CONFIG comments; Polymarket integration commit 2026-06-08), [src/weather_markets/polymarket.py](../../src/weather_markets/polymarket.py).

## See also
[strategy.md](strategy.md) · [goals-metrics.md](goals-metrics.md) · [../reference/investor-overview.md](../reference/investor-overview.md)
