# Runbook (failure recovery)

> What fails, what self-heals, and what a human must do. Audience: agents/operator. Last verified: 2026-06-19.

## TL;DR
- Lots is **auto-handled**: trading halts on risk breach or missing data, the fill monitor self-heals, a daily health check flags silent failures, and `alerts.py` drops a critical marker.
- The big **human-only** risks are **DB restore (no backups exist)**, **log/disk management (no rotation)**, and **dashboard/reboot recovery (not a service)** — see [deployment.md](deployment.md).
- Trading is gated in `scripts/live_trade.py`; the kill switch is filesystem files: `touch halt/ALL` (or `halt/KORD` / `halt/KMIA`).

## Auto-handled (no human needed)
| Mechanism | Where | What it does |
|---|---|---|
| Halt files | `live_trade.py` | `halt/ALL` or `halt/<city>` present → no orders for that scope |
| Daily-loss / cumulative kill | `live_trade.py` CITY_CONFIG + aggregate | halts the day / kills the city on P&L breach ([goals-metrics.md](goals-metrics.md)) |
| **Data-completeness HALT** (2026-06-11) | `live_trade.py` | refuses to trade if any required model (gefs/ifs/hrrr) is missing at decision time |
| Spread-regime filter | `live_trade.py` | skips when the 4-week avg spread > 5¢ |
| Pre-trade ingest retries | crons 13:46 / 14:30Z | re-ingest GEFS/IFS/HRRR 1h before each city's trade (recovers silent ingest failures); idempotent |
| Fill-monitor self-heal | `monitor_fills.py` + cron | 15s loop in a tmux session **re-spawned every 5 min** 14:45–19:55Z; idempotent (no-op if alive, resurrect if crashed) |
| EOD cancel | `monitor_fills.py --cancel-unfilled` 20:00Z | cancels still-resting orders (no overnight carry) |
| Reconcile | `reconcile_live_trades.py` 04:00Z | settles yesterday's fills → realized P&L; idempotent (`settlement IS NULL` only) |
| Health check | `check_pipeline_health.py` 16:00Z | alerts if paper cron didn't fire, today's 00Z ECMWF missing, obs >2d stale, or last price snapshot >30 min old |
| Alerting | `src/weather_markets/alerts.py` | appends to `/var/log/weather/alerts.log`, stderr, and writes critical marker `~/.kalshi/alert_critical` |

## Human-only — incident playbook
- **Halt / resume trading:** `touch halt/ALL` (or per-city) to stop immediately. Resume is a deliberate act — per convention it goes through a dated precommit + git ([../decisions/](../decisions/)); don't resume casually during the config freeze.
- **Disk-full** (precedent **2026-05-30**: crashed Postgres, locked SSH): free space first (the hourly GRIB purge + `disk_guard.sh` 6 GB floor should prevent it; if it recurs, `find /home/tdunn/data/{gefs,hrrr,ifs} -type f -delete` and trim `/var/log/weather/*.log`). Then restart Postgres. **Root gap:** no log rotation — see [deployment.md](deployment.md).
- **Silent model-ingest failure** (precedent **2026-06-10**: GEFS 00Z failed on a DB blip → live cron ran a partial model mix): now auto-mitigated by the data-completeness HALT + 13:46/14:30Z retries. To recover data manually: re-run `uv run python scripts/ingest_gefs_run.py` (or `ingest_ecmwf_daily.py --run-hour 0` / `ingest_hrrr_daily.py`); all idempotent (`ON CONFLICT DO NOTHING`). Check `check_pipeline_health` log.
- **Kalshi auth / rate-limit:** auth errors raise `KalshiAuthError` (live_trade/monitor exit non-zero; check `~/.kalshi/key.pem` + `KALSHI_KEY_ID`/`KALSHI_API_BASE`). Rate-limit = HTTP 429 with no Retry-After → back off; the dashboard WS exists partly to avoid REST polling.
- **Stuck / zero fills** (precedent **2026-06-10**: an 88.7%-edge trade got 0 fills on a 2¢ spread under post_inside_spread): execution is now "smart" — cross at ask for |edge| ≥ the per-city `smart_cross_edge_threshold` (KORD 0.40), post inside otherwise. If fills look wrong, check the order's `fill_status` in `live_trades` and the execution mode.
- **Settlement mismatch:** `reconcile_live_trades.py` resolves against `observations` (CF6). If P&L looks wrong, confirm the observed high landed for that `(date, station_id)` and that `contract_resolved_yes` matches the bracket; re-run reconcile (idempotent).
- **Postgres restore:** ⚠ **no backup exists** — currently unrecoverable beyond what's on disk. Highest-priority gap; see [deployment.md](deployment.md) Recommendations.
- **Dashboard down:** not a managed service — restart manually (`uv run uvicorn dashboard.app:app --port 8000`, ideally in tmux). It degrades gracefully if the Kalshi WS can't connect (falls back to DB prices).
- **After a reboot:** cron resumes automatically; **manually restart the dashboard** (and confirm the `monitor_loop` tmux session re-spawns on its next 5-min cron tick during the trading window).

## Sources
- [scripts/live_trade.py](../../scripts/live_trade.py), [scripts/monitor_fills.py](../../scripts/monitor_fills.py), [scripts/reconcile_live_trades.py](../../scripts/reconcile_live_trades.py), [scripts/check_pipeline_health.py](../../scripts/check_pipeline_health.py), [src/weather_markets/alerts.py](../../src/weather_markets/alerts.py), [../crontab.txt](../crontab.txt), [../decisions/halt-2026-06-06.md](../decisions/halt-2026-06-06.md).

## See also
[deployment.md](deployment.md) · [operations.md](operations.md) · [goals-metrics.md](goals-metrics.md)
