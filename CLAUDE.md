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
- [docs/context/decisions.md](docs/context/decisions.md) — why these models/venue/method (rationale)
- [docs/context/goals-metrics.md](docs/context/goals-metrics.md) — capital ($3,050), risk limits, expansion bar
- [docs/context/dashboard.md](docs/context/dashboard.md) — API payload→UI contract, live WS, sim parity
- [docs/context/operations.md](docs/context/operations.md) — crons, trading-day timeline, kill switches
- [docs/context/deployment.md](docs/context/deployment.md) — host/cron/Postgres prod reality + ops gaps
- [docs/context/runbook.md](docs/context/runbook.md) — failure recovery: auto-handled vs human
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
- **Capital base:** $3,050 deployed starting capital (the dashboard returnPct denominator) — see [docs/context/goals-metrics.md](docs/context/goals-metrics.md). Goal = prove positive edge after fees (no fixed return/Sharpe target).
- **Tests:** `uv run pytest`. The JS↔Python sim must stay in parity (`tests/test_sim_parity.py`) — edit
  `dashboard/static/app.js` and `dashboard/sim_python.py` together.
- **Live trading is real money.** `scripts/live_trade.py --live` places orders; treat it with care.
- Commit/push only when asked; end commit messages with the `Co-Authored-By: Claude` trailer.

## Still unconfirmed (minor — inferred only)
The former gaps are now documented: deployment/prod → [docs/context/deployment.md](docs/context/deployment.md),
failure recovery → [docs/context/runbook.md](docs/context/runbook.md), rationale →
[docs/context/decisions.md](docs/context/decisions.md), goals/capital →
[docs/context/goals-metrics.md](docs/context/goals-metrics.md). A few rationale points remain
*inferred only* (not written down) — confirm with the user before relying on them:
- Why GFS/NAM/RAP were never evaluated (only GEFS + ECMWF/IFS + HRRR).
- The explicit reason Kalshi was chosen over Polymarket for live trading (regulatory + CF6 + first-mover — inferred).
- Why Chicago & Miami were the first live cities (geographic diversity — inferred).

Operational note: deployment.md flags real gaps with no current solution — **no DB backups, no WAL, no
log rotation, no persistent dashboard service**. Address before scaling.
