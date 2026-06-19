# Data model

> The Postgres/TimescaleDB `weather` schema, ground-truthed from the live DB. Audience: agents. Last verified: 2026-06-19 via `psql -d weather`.

## TL;DR
- DB name `weather`; connect with `psql -d weather` (local peer auth, no password) or `weather_markets.db.get_connection()`.
- 7 tables. `* = TimescaleDB hypertable` (time-partitioned): **forecasts, observations, prices, orderbook_snapshots**. Plain tables: **contracts, paper_trades, live_trades**.
- **Units:** all market prices are **integer cents** (1–99). Temps are °F (double). Timestamps are **UTC** (`timestamptz`). Kalshi API raw fields elsewhere use `*_fp` (contract counts) / `*_dollars` (dollar strings) — see [glossary.md](glossary.md); the DB already stores normalized cents.
- Row counts at verify time: paper_trades ≈ 21,706; contracts ≈ 918; live_trades ≈ 26. Hypertable counts read 0 from `pg_stat_user_tables` (rows live in chunks) — not actually empty.

## Tables

### contracts — Kalshi market definitions (plain)
| column | type | notes |
|---|---|---|
| ticker | text | PK-ish, e.g. `KXHIGHCHI-26JUN15-B71.5` |
| series | text | e.g. `KXHIGHCHI` |
| station_id | text | e.g. `KORD` |
| target_date | date | event day (**from ticker**, not occurrence_datetime — see [glossary.md](glossary.md)) |
| strike_low / strike_high | double | bracket bounds (°F) |
| bracket_type | text | `greater_than` / `less_than` / `between` |
| expiration_time / last_trading_time | timestamptz | |
| raw_metadata | jsonb | raw Kalshi market JSON |
| discovered_at | timestamptz | |
| platform | text | `kalshi` (Polymarket research separate) |

### forecasts* — ensemble member values (hypertable on init_time/valid_time)
| column | type | notes |
|---|---|---|
| init_time | timestamptz | model run (00Z etc.) |
| valid_time | timestamptz | forecast valid time |
| station_id | text | |
| model | text | `gefs` / `ifs` / `hrrr` |
| member_id | int | ensemble member (gefs ~31, ifs ~50, hrrr 1) |
| temperature_f | double | hourly 2m temp |
| tmax_f | double | daily max where applicable |

### observations* — actual outcomes (hypertable)
| column | type | notes |
|---|---|---|
| date | date | |
| station_id | text | |
| high_temp_f | double | **resolution source** (NWS CF6, not raw ASOS) |
| low_temp_f | double | nullable |

### prices* — top-of-book snapshots (hypertable, written */5 min)
| column | type | notes |
|---|---|---|
| snapshot_at | timestamptz | |
| ticker | text | |
| yes_bid / yes_ask / no_bid / no_ask / last_price | int | **cents** |
| volume / volume_24h / open_interest | bigint | |
> ⚠️ Only `status=open` markets are snapshotted, so a ticker's marks **freeze after market close**. The dashboard now overlays live WS marks to fix this — see [dashboard.md](dashboard.md).

### orderbook_snapshots* — full-depth book (hypertable, */5 offset)
| column | type | notes |
|---|---|---|
| snapshot_at | timestamptz | |
| ticker | text | |
| side | text | `yes` / `no` |
| price_cents | int | level price |
| qty | int | size at level |
> Powers walk-the-book execution backtests.

### paper_trades — daily logged signals (plain, ~21.7k rows)
Key columns: `logged_at`, `target_date`, `ticker`, `model_source` (e.g. `EMOS combined 00Z Chicago (rolling 45d)`), `forecast_init_time`, `ensemble_mean`, `ensemble_std`, `emos_mu`, `emos_sigma`, `model_prob_yes`, `market_yes_bid`/`market_yes_ask` (cents), `market_mid_prob`, `market_snapshot_at`, `edge`, `edge_threshold`, `position` (`BUY_YES`/`BUY_NO`), `entry_price_cents`, `notes`. This is the backtest/blend training corpus.

### live_trades — real orders + outcomes (plain, ~26 rows)
Key columns: `id`, `placed_at`, `target_date`, `ticker`, `side`, `count`, `limit_price_cents`, `cross_price_cents`, `model_source`, `model_prob_yes`, `market_mid_prob`, `edge`, `kalshi_order_id`, `client_order_id`, `fill_status` (`pending`/`filled`/`partial`/`partial_resting`/...), `fill_price_cents`, `fill_count`, `fill_time`, `settlement`, `settlement_time`, `realized_pnl_cents`, `kalshi_fee_cents`, `notes`, `created_at`, `updated_at`.

## Key relationships
- `paper_trades.ticker` / `live_trades.ticker` → `contracts.ticker` (bracket metadata for resolution).
- Resolution: `observations(date=target_date, station_id)` → `evaluation.contract_resolved_yes(high, contract)`.
- A "city" = a `stations.Station` with a `kalshi_series`; trades join to it via `contracts.station_id`.

## Sources
- Live introspection: `psql -d weather` (`\dt`, `\d <table>`, `information_schema.columns`, `timescaledb_information.hypertables`).
- Writers: `src/weather_markets/{gefs,ecmwf,hrrr,observations,kalshi}.py`; `scripts/{snapshot_kalshi_prices,snapshot_kalshi_orderbook,paper_trade_log,live_trade,reconcile_live_trades}.py`.

## See also
[architecture.md](architecture.md) · [strategy.md](strategy.md) · [glossary.md](glossary.md)
