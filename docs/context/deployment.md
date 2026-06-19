# Deployment & prod

> How/where the system actually runs in production, and the ops gaps. Audience: agents. Last verified: 2026-06-19 (from the live host + repo).

## TL;DR
- Single cloud box. Everything runs from the **user `tdunn` crontab**; there is **no systemd, Docker, or `deploy/` dir**. Logs → `/var/log/weather/*.log`.
- **Postgres is local** (v17.9 + TimescaleDB) on the same box; reached via `DATABASE_URL` or `psql -d weather`.
- The **dashboard is launched ad-hoc** (`uvicorn`), not a managed service — it does **not** survive a reboot.
- **Known ops gaps (none set up): no DB backups, no WAL/PITR, no log rotation, no dashboard service.** See Recommendations.

## How the crons run
- Installed in the live crontab for user `tdunn`; the file of record is [../crontab.txt](../crontab.txt) (edit there → `crontab docs/crontab.txt`).
- Entry pattern: `cd /home/tdunn/weather-project && /home/tdunn/.local/bin/uv run python scripts/<x>.py >> /var/log/weather/<x>.log 2>&1`. All times **UTC**.
- Adding a city to `stations.STATIONS` auto-cascades to the ingest crons (no per-city lines). Full schedule + timeline: [operations.md](operations.md).
- No process supervisor: if the box reboots, **cron resumes on schedule** but the ad-hoc dashboard and any tmux loops do **not** restart themselves (the `monitor_fills` loop is re-spawned by its own 5-min cron during the window, so it self-heals; the dashboard does not).

## Database
- **Local PostgreSQL 17.9 + TimescaleDB** (extension confirmed) on the same host.
- Connection: `DATABASE_URL=postgresql://tdunn:<redacted>@localhost:5432/weather` (in `.env`, loaded by `weather_markets.config.Settings`); interactive access via `psql -d weather` (local peer auth, no password needed).
- Schema/units: [data-model.md](data-model.md). Hypertables (forecasts, observations, prices, orderbook_snapshots) are time-partitioned.

## Disk management
- `scripts/disk_guard.sh` — run in tmux during backfills; aborts backfill processes if free space on `/home/tdunn` drops below **6 GB** (a backfill can churn >50 GB/day).
- Hourly cron purges Herbie GRIB caches older than 180 min under `/home/tdunn/data/{gefs,hrrr,ifs}`.
- Background: a disk-full event on **2026-05-30** crashed Postgres and locked SSH — hence the aggressive cleanup (see [runbook.md](runbook.md)).

## Dashboard in prod
- Started manually: `uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000` (often inside tmux). Bound to loopback; accessed via the VS Code Ports tunnel.
- On startup it opens the read-only Kalshi WS live-mark service ([dashboard.md](dashboard.md)). **Not** auto-started; **not** restarted on crash/reboot.

## Ops gaps + recommendations (none of these exist yet — confirmed with the user)
| Gap | Risk | Recommendation |
|---|---|---|
| **No DB backups** | A disk-full/corruption loses the `weather` DB (21k+ paper_trades, all forecasts/prices). 2026-05-30 already crashed PG. | Nightly `pg_dump weather` to an off-box location (e.g. `pg_dump -Fc` → cloud bucket), cron'd; test a restore. |
| **No WAL/PITR** | Can't recover to a point in time after corruption. | Enable WAL archiving / `archive_command` if RPO matters (lower priority than a basic dump). |
| **No log rotation** | `/var/log/weather` grows unbounded (`gefs.log` ~62 MB); can fill disk → repeat of 2026-05-30. | Add `/etc/logrotate.d/weather` (daily, compress, keep ~14d) for `/var/log/weather/*.log`. |
| **Dashboard not a service** | Dies on reboot/crash; no telemetry until manually restarted. | A `systemd` unit (or a tmux-respawn cron like `monitor_loop`) running uvicorn, if always-on telemetry is wanted. |

## Sources
- Live host: `crontab -l`, `psql` (`SELECT version()`, `pg_extension`), `/var/log/weather/`, `/etc/systemd`, `/etc/logrotate.d`.
- Repo: [../crontab.txt](../crontab.txt), [scripts/disk_guard.sh](../../scripts/disk_guard.sh), [src/weather_markets/config.py](../../src/weather_markets/config.py), [src/weather_markets/db.py](../../src/weather_markets/db.py).

## See also
[operations.md](operations.md) · [runbook.md](runbook.md) · [data-model.md](data-model.md)
