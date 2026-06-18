"""FastAPI backend for the weather-project dashboard.

Serves the zero-build static frontend (static/) plus a small JSON API backed by
the pure data functions in data_live / data_backtest. Replaces the former
Streamlit app (scripts/dashboard.py).

Endpoints:
    GET /                       -> static/index.html (the SPA shell)
    GET /api/live               -> live telemetry payload (15s TTL)
    GET /api/backtest/cities    -> [{code,label}] for the city dropdown
    GET /api/backtest?city=&date=&sizing=&amount=&depth=&edge=
                                -> one city's backtest payload (5min TTL)

Run:
    uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.data_live import get_live_data, _live_trade_config
from dashboard.data_backtest import fetch_city_payload, list_cities
from dashboard.ttl_cache import ttl_cache

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="weather-project dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _json(payload) -> Response:
    """JSON response that tolerates dates / numpy scalars via default=str —
    matching the old Streamlit renderer's json.dumps(..., default=str)."""
    return Response(json.dumps(payload, default=str), media_type="application/json")


@ttl_cache(15)
def _live_payload() -> dict:
    """Live telemetry, recomputed at most every 15s — matches the former
    @st.fragment(run_every=15s) cadence and is friendly to Kalshi rate limits."""
    return get_live_data(_live_trade_config())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/live")
def api_live() -> Response:
    return _json(_live_payload())


@app.get("/api/backtest/cities")
def api_backtest_cities() -> Response:
    return _json(list_cities())


@app.get("/api/backtest")
def api_backtest(
    city: str = Query(...),
    date_str: str = Query("", alias="date"),
    sizing: str = Query("unit"),
    amount: float = Query(500.0),
    depth: int = Query(500),
    edge: float = Query(0.10),
) -> Response:
    try:
        sel = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    except ValueError:
        sel = date.today()
    return _json(fetch_city_payload(city, sel, sizing, amount, depth, edge))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "dashboard.app:app",
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8000")),
    )
