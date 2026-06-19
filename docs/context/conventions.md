# Conventions

> The rules an agent must follow to work in this repo safely. Audience: agents. Last verified: 2026-06-19.

## TL;DR (hard rules)
- **Python via `uv run`** — never call `.venv/bin/python` directly. Mirror this in docstring examples.
- **Long jobs in `tmux`**, output line-buffered so they survive detach/reattach (cloud-server workflow).
- **Crontab:** edit `docs/crontab.txt`, then install with `crontab docs/crontab.txt`. Never edit the live crontab directly.
- **Config freeze 2026-06-12 → 2026-07-10:** only safety/correctness changes to trading params. New ideas → [../backlog.md](../backlog.md). Re-eval decides KMDW model, walk-book sizing, backlog.
- **Secrets:** `~/.kalshi/key.pem` and `.env` are never shared or committed (`.env` is gitignored, chmod 600). `DATABASE_URL` and `POLYMARKET_SECRET` are sensitive.
- **DB:** `psql -d weather` (local peer auth, no password sourcing needed).
- **Tests:** `uv run pytest` (109+ tests). The JS↔Python sim parity test must stay green.

## Working principles
- **Grow data coverage, not model sophistication.** The trading stack is near its linear ceiling; favor changes that add price coverage / sample size over model complexity. (memory `feedback_binding_constraint_principle`)
- **Risk envelope numbers are immutable during live trading** — don't tune kill/halt thresholds casually.
- **Pre-commit before live changes.** Strategy/city changes get a dated pre-registration in [../decisions/](../decisions/) (multiple degrees of freedom → ~5% false positives by chance; see `edge-test-protocol`).

## Code conventions
- Sim logic exists twice (JS `dashboard/static/app.js jsComputeSim` + Python `dashboard/sim_python.py`); **edit both together** — `tests/test_sim_parity.py` extracts the JS slice and runs it in V8 against the Python reference.
- Dashboard data functions must stay **Streamlit-free** (FastAPI imports them; never reintroduce `import streamlit`).
- Kalshi units: API `*_fp` = contract counts, `*_dollars` = dollar strings, prices = integer cents 1–99; the DB stores normalized cents. Contract `target_date` comes from the **ticker** (`kalshi.ticker_event_date`), not `occurrence_datetime`.
- Ingest writers use `ON CONFLICT DO NOTHING` (idempotent re-runs).

## Git
- Commit/push only when asked. End commit messages with the `Co-Authored-By: Claude` trailer.

## Sources
- memory: `feedback_uv_package_manager`, `feedback_crontab_workflow`, `user_cloud_tmux_workflow`, `feedback_binding_constraint_principle`, `project_config_freeze_2026-07-10`.
- [.env.example](../../.env.example), [../decisions/](../decisions/).

## See also
[operations.md](operations.md) · [strategy.md](strategy.md) · [../decisions/](../decisions/)
