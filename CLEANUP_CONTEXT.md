# Cleanup Context: scripts/ directory review

## What this repo is
Quantitative trading system for Kalshi weather prediction markets (NYC daily high temperature). Python 3.12, PostgreSQL + TimescaleDB, GEFS + ECMWF ensemble forecasts.

## What you're doing
Reviewing every file in `scripts/` to determine if it's still needed. Many are one-off backfill, comparison, or debugging scripts written during weeks 1-3 of development. The project is now in steady-state daily operation.

## Scripts that are DEFINITELY in use (do not touch)
These are cron entry points or active tools:
- `ingest_gefs_run.py` — GEFS cron entry
- `ingest_ecmwf_daily.py` — ECMWF cron entry
- `ingest_observations_daily.py` — observations cron entry
- `discover_kalshi_contracts.py` — Kalshi contract discovery cron
- `snapshot_kalshi_prices.py` — Kalshi price snapshot cron (runs every 5 min)
- `dashboard.py` — Streamlit dashboard (two tabs: Analysis + Trading)

## Scripts that are PROBABLY one-offs
Anything with `backfill_`, `compare_`, `test_`, or `debug_` in the name was likely a one-time task. But don't assume — ask me if unclear.

## What to produce
For each file in `scripts/`, give:
1. Filename
2. One-line summary of what it does
3. Recommendation: KEEP / ARCHIVE / UNCLEAR
4. Brief reason

Do NOT delete or modify any files. Just produce the list.

## Key context for judging
- Backfill scripts that filled historical data are done — the data is in the DB. But I might want to keep them if I expand to new stations later.
- Comparison/analysis scripts that produced one-time results are candidates for archiving.
- Anything that the dashboard or cron jobs import from is a dependency — check before recommending archive.

## What "archive" means
Move to a `scripts/archive/` directory. Still in the repo, just out of the active path.
