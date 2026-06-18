# weather-project

A Kalshi prediction-market trading stack for daily high-temperature contracts.
EMOS-calibrated ensemble forecasts (GEFS + ECMWF + HRRR) are blended Benter-style
with the live market price, traded by cron jobs, and monitored through a dashboard.

## Dashboard

The dashboard is a **zero-build, vanilla-JS frontend served by FastAPI** (no
Node, npm, React, TypeScript, or bundler). Three static files
(`dashboard/static/{index.html,style.css,app.js}`) are served verbatim alongside
a small JSON API backed by the Python data layer.

```
dashboard/
├── app.py            # FastAPI: JSON API + StaticFiles mount + uvicorn entry
├── data_live.py      # live telemetry payload (Postgres + Kalshi API)
├── data_backtest.py  # per-city backtest payload (forecast + brackets + walk-forward blend)
├── sim_python.py     # reference P&L sim (parity-tested against the JS sim)
├── ttl_cache.py      # in-process TTL cache (live 15s, backtest 5min)
└── static/
    ├── index.html    # DOM shell: topbar, two tabs (Live Trading / Backtest)
    ├── style.css     # all styling — :root tokens, dark-only
    └── app.js        # all behavior: fetch, render fns, the backtest sim, polling
```

API:

| Method & path | Purpose |
|---|---|
| `GET /` | the SPA shell (`index.html`) |
| `GET /api/live` | live account/P&L/risk/cron telemetry (15s TTL) |
| `GET /api/backtest/cities` | `[{code,label}]` for the city dropdown |
| `GET /api/backtest?city=&date=&sizing=&amount=&depth=&edge=` | one city's backtest payload (5min TTL) |

The Live tab polls `/api/live` every 15s; the Backtest tab fetches a city's
payload on selection and recomputes the P&L simulation entirely client-side
(`jsComputeSim` in `app.js`) as you change sizing/edge/execution knobs.

## Setup

Prerequisites: Python 3.12, [`uv`](https://docs.astral.sh/uv/), and a
PostgreSQL/TimescaleDB instance reachable via `DATABASE_URL`.

```bash
uv sync                       # install dependencies
cp .env.example .env          # then fill in DATABASE_URL (+ Kalshi keys for live data)
```

## Run the dashboard

```bash
uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The dev loop is: edit `dashboard/static/*`, reload
the browser (bump the `?v=N` query string on the CSS/JS links to bust cache).
There is no build step.

## Tests

```bash
uv run pytest
```

`tests/test_sim_parity.py` runs the browser sim (`dashboard/static/app.js`) in a
real V8 engine (py_mini_racer) and asserts it matches the Python reference
(`dashboard/sim_python.py`) on shared fixtures, plus golden tests for the
JS-only strategy/risk features. There is no JS test framework.

## Adding a feature to the dashboard

- **New API field / panel data:** add it to the relevant payload in
  `dashboard/data_live.py` or `dashboard/data_backtest.py`, then read it in a
  render function in `app.js`. The data layer functions are plain Python (no
  Streamlit) — keep them that way so the FastAPI process never imports Streamlit.
- **New UI section:** write a render function in `app.js` that returns an HTML
  string and call it from `renderLive()` / `renderBacktest()`. Wrap every
  interpolated data string in `esc(...)` (the only XSS defense). Reuse the
  existing class taxonomy (`.panel`, `.hero`, `.city`, `table.dt`, etc.) and
  `:root` tokens in `style.css`.
- **Backtest sim changes:** edit `jsComputeSim` in `app.js` **and** keep
  `dashboard/sim_python.py` in sync — `test_sim_parity.py` enforces it.

The live-trading crons (`live_trade.py`, `paper_trade_log.py`, `monitor_fills.py`,
`reconcile_live_trades.py`) are independent of the dashboard and unchanged by it;
the dashboard is read-only telemetry.
