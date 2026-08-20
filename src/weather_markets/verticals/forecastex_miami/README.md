# Vertical: forecastex-miami

Scaffolded by `scripts/expansion_scout.py bootstrap forecastex-miami` — **paper-only**.
Venue: forecastex | kind: venue-port | station: KMIA | underlying: daily_high_temp

Exact station port (same KMIA settlement). Trades through resolution day, ~1/2 Kalshi fee. Open Qs: morning depth, rulebook PDF, account access.

## Validation path (in order — do not skip)

1. `pipeline.py` TODOs: ingest coverage, blend wiring, paper logging.
2. Accumulate >= 90 days of paper_trades rows for this vertical.
3. `backtest_walkforward.py`: walk-forward OOS Sharpe on realistic execution.
   The 2.5 bar gates any promotion proposal.
4. Promotion to live = manual operator decision, minimal size, halt file wired,
   pre-commit doc in docs/decisions/precommits/. Nothing here automates it.
