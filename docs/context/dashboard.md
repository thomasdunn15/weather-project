# Dashboard

> The agent-facing data contract for the dashboard. Audience: agents. Last verified: 2026-06-19. Stack details: [../reference/frontend-architecture.md](../reference/frontend-architecture.md).

## TL;DR
- Zero-build **vanilla JS + FastAPI** (Streamlit retired). Run: `uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000`, open http://localhost:8000.
- Two tabs: **Live Trading** (telemetry, polls `/api/live` every 2s) and **Backtest** (clickable US map → per-city sim, client-side recompute).
- Live position **marks** come from a read-only **Kalshi WebSocket** service (`dashboard/kalshi_ws.py`) → cent-accurate and continuous; falls back to the DB `prices` snapshot if the socket is down.
- **Invariant:** the JS sim (`static/app.js` `jsComputeSim`) and the Python reference (`dashboard/sim_python.py`) must stay in lockstep — `tests/test_sim_parity.py` enforces it. Edit both together.

## Files
| file | role |
|---|---|
| `dashboard/app.py` | FastAPI: endpoints + StaticFiles + lifespan (starts the WS service) |
| `dashboard/data_live.py` | builds the `/api/live` payload (`get_live_data`) |
| `dashboard/data_backtest.py` | builds `/api/backtest` payloads (`fetch_city_payload`, `list_cities`) |
| `dashboard/kalshi_ws.py` | read-only `KalshiLiveService` — live top-of-book marks for held tickers |
| `dashboard/sim_python.py` | Python reference P&L sim (parity target) |
| `dashboard/ttl_cache.py` | tiny in-process TTL cache (replaces `@st.cache_data`) |
| `dashboard/static/{index.html,style.css,app.js}` | the whole UI (3 files, no build) |

## API
| method · path | returns | cache |
|---|---|---|
| `GET /` | `static/index.html` | — |
| `GET /api/live` | live telemetry (below) | 2s |
| `GET /api/backtest/cities` | `[{code,label}]` for the dropdown/map | process-life |
| `GET /api/backtest?city=&date=&sizing=&amount=&depth=&edge=` | one city's backtest payload | 5min |

## `/api/live` payload → UI
`balance` (=cash+portfolio), `cashBalance`, `portfolioValue`; `today`/`cumulative` {total, realized, unrealized, returnPct, winRate, nSettled}; `positions[]` {ticker, bracket, side, qty, avg, mark, unreal, unrealPct, **live**}; `openOrdersTbl[]`, `orders[]`, `fills[]`, `signals[]`, `cities[]` (per-city cards + risk), `agg` (risk envelope), `series[]` (7-day P&L), `hrrr`, `nextCron`, `crons[]`, `alerts[]`, `killArmed`, and **`live`** {connected, ageMs, marks, source}. The topbar pill shows `ws · N live · Xs` (green) when connected, else `rest` (amber); live-marked positions get a green ●.

## `/api/backtest` payload → UI
`code`, `city`, `date`; ensemble (`members[]`, `nMembers`, `ensMean`, `ensSpread`, `emosMu`, `emosSigma`, `observed`); `brackets[]` {label, lo, hi, modelP, blendP, mktP, resolved}; `sim` {unit/amount/kelly/scaling}; `trades[]` (full history for client-side re-sim); `strat[]`; `blend` {alpha, betaModel, betaMarket, marketShare, nTrain}. Changing sizing/edge/execution recomputes **in the browser** via `jsComputeSim` (no round-trip); only city/date refetch. Clicking a city auto-loads its best params (`findBestParams`, by Sharpe ≥15 trades).

## Live marks service (`kalshi_ws.py`)
One authenticated WS (`wss://api.elections.kalshi.com/trade-api/ws/v2`, same RSA-PSS handshake as REST). Subscribes the `ticker` channel for currently-held tickers (from `live_trades`), keeps `marks[ticker]=(yes_bid¢,yes_ask¢,ts)`, auto-adds new positions every 15s, self-heals on disconnect. **Read-only** (never orders). `get_live_data` overlays these marks over the DB snapshot (fresher + never frozen). There is **no balance channel** — cash stays REST.

## Sources
- [dashboard/](../../dashboard/), [tests/test_sim_parity.py](../../tests/test_sim_parity.py)
- Stack/how-to-extend: [../reference/frontend-architecture.md](../reference/frontend-architecture.md)

## See also
[architecture.md](architecture.md) · [strategy.md](strategy.md) · [operations.md](operations.md)
