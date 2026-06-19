# Architecture

> System map for weather-project: how a forecast becomes a trade. Audience: agents. Last verified: 2026-06-19.

## TL;DR
- A pipeline turns ensemble weather forecasts into calibrated daily-high probabilities, compares them to Kalshi market prices, and trades the edge.
- Stages: **ingest** forecasts/observations → **aggregate** ensemble daily highs → **EMOS** calibration → **bracket probabilities** → **edge vs market** (+ Benter **blend**) → **paper/live trade** → **reconcile** settlements → **dashboard**.
- Code lives in three places: `src/weather_markets/` (library), `scripts/` (cron entrypoints + backfills + analysis), `dashboard/` (FastAPI + vanilla-JS UI). Data is in Postgres/TimescaleDB `weather`.
- Everything is driven by cron (see [operations.md](operations.md)); the dashboard is read-only telemetry.

## End-to-end flow
```
NOAA/ECMWF/AWS GRIB ──ingest──► forecasts (gefs/ifs/hrrr members)
NWS CF6            ──ingest──► observations (actual daily highs)
Kalshi API         ──ingest──► contracts + prices (+ orderbook_snapshots)
        │
        ▼  aggregation.compute_combined_daily_highs(init, date, conn, station, models)
   ensemble member daily highs  ──► emos.fit_emos_rolling(...)  ──► (μ, σ)
        │
        ▼  emos.gaussian_to_bracket_probs(μ, σ, contracts)
   per-bracket model_P  ──► edge = model_P − market_mid  ──► blend.apply_blend(fit, model_P, market_P)
        │
        ▼  scripts/paper_trade_log.py (daily, all cities)  +  scripts/live_trade.py (KORD 14:46Z, KMIA 15:30Z)
   paper_trades / live_trades rows  ──► Kalshi orders (live only, risk-gated)
        │
        ▼  scripts/monitor_fills.py (15s loop)  ──► fill_status/fill_count
        ▼  scripts/reconcile_live_trades.py (04:00Z)  ──► settlement, realized_pnl_cents
        │
        ▼  dashboard/ (FastAPI /api/live, /api/backtest) ──► static/app.js
```

## `src/weather_markets/` module reference
| Module | Purpose | Key functions / classes |
|---|---|---|
| `db.py` | Postgres connection | `get_connection()` |
| `config.py` | env/.env settings (pydantic) | `class Settings` (`database_url`, `kalshi_key_id`, `kalshi_key_path`, `kalshi_api_base`, `log_level`) |
| `stations.py` | station registry (cities) | `class Station`, `get(code)`, `all_stations()` |
| `gefs.py` | GEFS ensemble ingest (31 members) | `download_member`, `extract_temperatures`, `insert_forecasts`, `ingest_gefs_run` |
| `ecmwf.py` | ECMWF/IFS ingest (50 members) | `ingest_ecmwf_run`, `_extract_temps` |
| `hrrr.py` | HRRR ingest (1 member) | `ingest_hrrr_run`, `_nearest_yx` |
| `observations.py` | NWS CF6 actual highs | `fetch_cf6_year`, `parse_observations`, `insert_observations`, `ingest_observations` |
| `aggregation.py` | ensemble → daily highs + helpers | `compute_daily_highs`, `compute_combined_daily_highs`, `compute_ensemble_probabilities`, `fetch_contracts_for_date`, `fetch_observed_high`, `class NoForecastDataError` |
| `emos.py` | EMOS calibration + bracket probs | `fit_emos`, `fit_emos_rolling` (45d), `gaussian_to_bracket_probs`, `crps_gaussian` |
| `blend.py` | Benter market blend (logistic) | `class BlendFit`, `fit_blend`, `get_blend` (cached), `walkforward_blends` (no-lookahead), `apply_blend` |
| `evaluation.py` | scoring + resolution | `contract_resolved_yes`, `brier_score`, `evaluate_predictions`, `calibration_bins` |
| `kalshi.py` | public Kalshi data + ticker parsing | `ticker_event_date` (date-bug fix), `fetch_markets`, `parse_contracts`, `insert_contracts`, `parse_prices`, `insert_prices`, `discover_kalshi_contracts` |
| `kalshi_api.py` | authenticated Kalshi REST client | `class KalshiClient` (`get_balance/positions/orders/fills/market/orderbook`, `place_limit_order`, `cancel_order`), `parse_position/parse_count/parse_dollars_to_cents`, `class KalshiAuthError` |
| `polymarket.py` | Polymarket client (research only) | `class PolymarketClient`, `class PolymarketCreds`, `class PolymarketAuthError` |
| `backtesting.py` | backtest helpers | `backtest_day`, `backtest_range` |
| `alerts.py` | pipeline-health alerting | `send_alert`, `has_critical_alert`, `clear_critical_marker` |

## `scripts/` by role
- **Forecast/obs ingest (cron):** `ingest_gefs_run.py`, `ingest_ecmwf_daily.py`, `ingest_hrrr_daily.py`, `ingest_observations_daily.py`.
- **Backfill (one-shot/historical):** `backfill_gefs_runs.py`, `backfill_ecmwf_runs.py`, `backfill_hrrr_runs.py`, `backfill_kalshi_contracts.py`, `backfill_kalshi_prices.py`, `backfill_paper_trades.py` (+ `_lows`, `_equal_weight`), `backfill_polymarket_contracts.py`, `run_backfills.sh` (bounded-concurrency orchestrator).
- **Trading (cron):** `paper_trade_log.py` (daily signals), `live_trade.py` (real orders, risk-gated, `--city --live`), `monitor_fills.py` (fill status; `--loop 15`, `--cancel-unfilled`), `reconcile_live_trades.py` (settlements + realized P&L).
- **Market data (cron):** `discover_kalshi_contracts.py`, `snapshot_kalshi_prices.py` (*/5), `snapshot_kalshi_orderbook.py` (*/5 offset), `snapshot_polymarket_prices.py`.
- **Ops/health:** `check_pipeline_health.py`, `check_kalshi_api.py`, `disk_guard.sh`.
- **Analysis / research (`scripts/analysis/`):** `best_time_of_day.py`, `blend_logistic.py`, `backtest_with_blend.py`, `kelly_with_blend.py`, `multibracket_portfolio.py`, `emos_features.py`, `walk_book_synthetic.py`, `cross_platform_arb.py`. Plus top-level `run_backtest.py`, `backtest_forecast_only.py`, `backtest_multimodel.py`, `sweep_emos_window.py`, `show_probabilities.py`.

## `dashboard/` (see [dashboard.md](dashboard.md))
FastAPI app (`app.py`) serving a zero-build vanilla-JS UI (`static/`) + JSON API backed by `data_live.py` / `data_backtest.py`, with `sim_python.py` (parity reference), `ttl_cache.py`, and `kalshi_ws.py` (read-only live-mark WebSocket service).

## Sources
- Code: [src/weather_markets/](../../src/weather_markets/), [scripts/](../../scripts/), [dashboard/](../../dashboard/)
- Pipeline detail: [data-model.md](data-model.md), [strategy.md](strategy.md), [operations.md](operations.md)

## See also
[data-model.md](data-model.md) · [strategy.md](strategy.md) · [dashboard.md](dashboard.md) · [operations.md](operations.md) · [glossary.md](glossary.md)
