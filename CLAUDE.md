# weather-project — agent guide

A Kalshi prediction-market trading stack for **daily high-temperature** contracts. EMOS-calibrated
ensemble forecasts (GEFS + ECMWF/IFS + HRRR) are blended Benter-style with the live market price,
traded by cron jobs (Chicago/KORD + Miami/KMIA live; others paper/backtest), and monitored via a
FastAPI + vanilla-JS dashboard. Postgres/TimescaleDB `weather` holds all data.

**New here? Read [docs/README.md](docs/README.md), then the onboarding set in [docs/context/](docs/context/).**

## Repo map
- `src/weather_markets/` — library: ingest (`gefs/ecmwf/hrrr/observations`), `aggregation`, `emos`,
  `blend`, `evaluation`, `kalshi`/`kalshi_api`, `stations`, `db`, `config`.
- `scripts/` — cron entrypoints (`live_trade`, `paper_trade_log`, `monitor_fills`,
  `reconcile_live_trades`, `ingest_*`, `snapshot_*`), backfills (`backfill_*`, `run_backfills.sh`),
  analysis (`scripts/analysis/`).
- `dashboard/` — FastAPI app + `data_live`/`data_backtest` + `kalshi_ws` (live marks) + `static/` UI.
- `docs/` — see [docs/README.md](docs/README.md). `tests/` — `uv run pytest`.

## Context files (authored from code + live DB)
- [docs/context/architecture.md](docs/context/architecture.md) — pipeline + module/scripts map
- [docs/context/data-model.md](docs/context/data-model.md) — the `weather` schema (7 tables, units)
- [docs/context/strategy.md](docs/context/strategy.md) — EMOS → edge → blend → sizing/risk; CITY_CONFIG
- [docs/context/dashboard.md](docs/context/dashboard.md) — API payload→UI contract, live WS, sim parity
- [docs/context/operations.md](docs/context/operations.md) — crons, trading-day timeline, kill switches
- [docs/context/conventions.md](docs/context/conventions.md) — the hard rules (also below)
- [docs/context/glossary.md](docs/context/glossary.md) — domain terms

## Hard rules (do not violate)
- **Python via `uv run`** — never `.venv/bin/python` directly.
- **Long jobs in `tmux`**, line-buffered (cloud-server workflow).
- **Crontab:** edit `docs/crontab.txt`, then `crontab docs/crontab.txt`. Never edit the live crontab directly.
- **CONFIG FREEZE 2026-06-12 → 2026-07-10:** only safety/correctness changes to trading params; new
  ideas go to [docs/backlog.md](docs/backlog.md). Risk-envelope numbers are immutable during live trading.
- **Secrets never shared/committed:** `~/.kalshi/key.pem`, `.env` (chmod 600, gitignored), `DATABASE_URL`,
  `POLYMARKET_SECRET`. `Research.md` is gitignored (local-only).
- **DB:** `psql -d weather` (local peer auth, no password).
- **Tests:** `uv run pytest`. The JS↔Python sim must stay in parity (`tests/test_sim_parity.py`) — edit
  `dashboard/static/app.js` and `dashboard/sim_python.py` together.
- **Live trading is real money.** `scripts/live_trade.py --live` places orders; treat it with care.
- Commit/push only when asked; end commit messages with the `Co-Authored-By: Claude` trailer.

## Open questions (NOT yet documented — to fill in together)
These are real gaps; don't invent answers — ask the user:
- **Deployment / prod:** where do the crons actually run, how is the box provisioned, how does the live
  env reach Postgres, backup/restore, log rotation, what runs the dashboard in prod.
- **Decision rationale:** *why* GEFS+ECMWF+HRRR (not GFS/NAM/RAP)? Why Kalshi over Polymarket
  (`src/weather_markets/polymarket.py` exists but isn't traded)?
- **Goals / metrics / capital:** the real account capital base (the dashboard hardcodes 3050 for
  returnPct), target return/Sharpe, drawdown tolerance, city-expansion criteria.
- **Failure runbook:** recovery steps for common incidents (missing model run, Kalshi auth/rate-limit,
  disk-full, stuck fills, settlement mismatch). `scripts/check_pipeline_health.py` + `alerts.py` exist
  but the response playbook isn't written.
