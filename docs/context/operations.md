# Operations

> Cron schedule, trading-day timeline, kill switches, and how to run things. Audience: agents. Last verified: 2026-06-19. Source of truth: [../crontab.txt](../crontab.txt).

## TL;DR
- Everything runs from cron on the cloud server, all times **UTC**. Adding a city to `stations.STATIONS` auto-cascades to the ingest crons (no per-city lines).
- Workflow rule: **edit `docs/crontab.txt`, then `crontab docs/crontab.txt`** to install — never edit the live crontab directly.
- Logs in `/var/log/weather/*.log`. GRIB caches under `/home/tdunn/data/{gefs,hrrr,ifs}` are purged hourly (disk-full once crashed Postgres — safety-critical).
- Kill switches are filesystem flags: `touch halt/KORD`, `halt/KMIA`, or `halt/ALL`.

## Trading-day timeline (UTC)
| time | job | what |
|---|---|---|
| 00/06/12/18 +6h (`15 6,12,18,0`) | `ingest_gefs_run.py` | GEFS forecasts, all stations |
| 03:30, 13:45 | `ingest_hrrr_daily.py` | HRRR 00Z (retry 1h before KORD) |
| 06/12/18 | `ingest_observations_daily.py` | NWS CF6 actual highs |
| 07:00, 13:00 | `ingest_ecmwf_daily.py --run-hour 0` | ECMWF/IFS 00Z (+retry) |
| 18:30 | `ingest_ecmwf_daily.py` | ECMWF 12Z |
| 04:00 | `reconcile_live_trades.py` | settle yesterday's fills → realized P&L |
| 14:30 | `discover_kalshi_contracts.py` | new daily-high contracts |
| */5 | `snapshot_kalshi_prices.py` | top-of-book → `prices` (open markets only) |
| */5 (offset +1) | `snapshot_kalshi_orderbook.py` | full depth → `orderbook_snapshots` |
| */5 (offset +2) | `snapshot_polymarket_prices.py` | Polymarket research snapshots |
| 13:46, 14:30 | GEFS/IFS/HRRR re-ingest | pre-trade data verification (recover silent failures) |
| 14:45 | `paper_trade_log.py` | log the day's signals (all cities) |
| **14:46** | `live_trade.py --city KORD --live` | **Chicago live order** |
| **15:30** | `live_trade.py --city KMIA --live` | **Miami live order** |
| 14:45→19:55 (tmux loop, self-healing every 5m) | `monitor_fills.py --loop 15` | 15s fill polling |
| :00/:30 of 15–19 | `monitor_fills.py` | 30-min safety-net fill check |
| 20:00 | `monitor_fills.py --cancel-unfilled` | cancel still-pending orders (no overnight carry) |
| 16:00 | `check_pipeline_health.py` | alert on silent data failures |
| hourly | `find .../{gefs,hrrr,ifs} -mmin +180 -delete` | GRIB cache purge |

## Risk gating (in `live_trade.py`)
Every live order is gated by: halt files, data-completeness (HALTS if a required model is missing), daily-loss limit, cumulative kill, contract cap, spread-regime. `live_trade.py --live` is the only real-money path; without `--live` it's a dry run.

## Run the dashboard
```bash
uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000   # add --reload while editing
```
Long-lived: run inside `tmux` (e.g. `tmux new -s dash '...'`). Open via the VS Code Ports panel (port 8000) → localhost:8000.

## Backfills
`scripts/backfill_*.py` for historical data; `scripts/run_backfills.sh` orchestrates with bounded concurrency; `scripts/disk_guard.sh` aborts if free disk drops too low. Run long jobs in tmux, line-buffered, so they survive detach/reattach.

## Sources
- [../crontab.txt](../crontab.txt) (authoritative), [scripts/](../../scripts/), `halt/` dir, `/var/log/weather/`.

## See also
[architecture.md](architecture.md) · [conventions.md](conventions.md) · [dashboard.md](dashboard.md)
