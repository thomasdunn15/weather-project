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
    GET /api/accounting         -> tax reserve / withdrawals payload (60s TTL)
    GET /api/digest             -> latest ops-copilot digest, read-only (5min TTL)

Run:
    uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from fastapi import Body, FastAPI, Query, Response
from fastapi.staticfiles import StaticFiles

from dashboard.data_live import get_live_data, _live_trade_config
from dashboard.data_backtest import fetch_city_payload, list_cities
from dashboard.data_accounting import get_accounting_data
from dashboard.data_digest import get_digest_data
from dashboard.kalshi_ws import service as live_service
from dashboard.ttl_cache import ttl_cache

STATIC_DIR = Path(__file__).resolve().parent / "static"


@contextlib.asynccontextmanager
async def lifespan(app: "FastAPI"):
    # Launch the read-only Kalshi WebSocket live-mark service. It self-heals and
    # degrades gracefully (no key / no socket → dashboard uses DB prices).
    task = asyncio.create_task(live_service.run())
    try:
        yield
    finally:
        live_service._stop = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


app = FastAPI(title="weather-project dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _json(payload) -> Response:
    """JSON response that tolerates dates / numpy scalars via default=str —
    matching the old Streamlit renderer's json.dumps(..., default=str)."""
    return Response(json.dumps(payload, default=str), media_type="application/json")


@ttl_cache(2)
def _live_payload() -> dict:
    """Live telemetry, recomputed at most every 2s. Marks come from the WS
    service (continuous, cent-accurate); cash/orders are live REST. The 2s cache
    bounds DB/REST work while the browser polls at the same cadence."""
    return get_live_data(_live_trade_config())


@app.get("/")
def index() -> Response:
    """index.html with every /static/ URL stamped from that file's mtime.

    The ?v=N strings in index.html used to be bumped BY HAND, and on 2026-08-31
    that failed the way hand-maintained cache keys always eventually do: a field
    was dropped from /api/forecastex, the JS that read it was updated, the
    version was not bumped — so browsers ran the previous app.js against the new
    payload and the tab died on `undefined.toLocaleString()`. Stamping from
    mtime makes the bump automatic and unforgettable.

    `Cache-Control: no-cache` is REQUIRED here, not belt-and-braces: it means
    "revalidate", not "do not store". Without it the browser reuses this HTML
    whenever index.html itself is unchanged — and then it never sees the new
    stamps for the assets that DID change, which is the whole bug again.
    """
    def stamp(m: re.Match) -> str:
        asset = STATIC_DIR / m.group(1).removeprefix("/static/")
        v = int(asset.stat().st_mtime) if asset.is_file() else 0
        return f'"{m.group(1)}?v={v}"'

    html = re.sub(r'"(/static/[^"?]+)(?:\?v=[^"]*)?"',
                  stamp, (STATIC_DIR / "index.html").read_text())
    return Response(html, media_type="text/html",
                    headers={"Cache-Control": "no-cache"})


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


@ttl_cache(60)
def _accounting_payload() -> dict:
    """Accounting: tax reserve + withdrawals + safe-to-withdraw from live Kalshi.
    60s TTL — funding/settlement data changes slowly and each build makes several
    read-only Kalshi REST calls."""
    return get_accounting_data()


@app.get("/api/accounting")
def api_accounting() -> Response:
    return _json(_accounting_payload())


@ttl_cache(60)
def _polymarket_payload() -> dict:
    """Polymarket tab: live-probe rails/trades + 5-city paper tracking.
    60s TTL — pure local DB reads, cache just bounds per-poll query cost."""
    from dashboard.data_polymarket import get_polymarket_data
    return get_polymarket_data()


@app.get("/api/polymarket")
def api_polymarket() -> Response:
    return _json(_polymarket_payload())


@ttl_cache(20)
def _forecastex_payload() -> dict:
    """ForecastEx tab: collector health + liquidity + the cached backtest.
    The backtest itself is NEVER computed here (it downloads settlement
    ladders) — data_forecastex reads data/forecastex_backtest.json and
    reports its age. 60s TTL bounds the per-poll DB cost."""
    from dashboard.data_forecastex import get_forecastex_data
    return get_forecastex_data()


@app.get("/api/forecastex")
def api_forecastex() -> Response:
    return _json(_forecastex_payload())


# --- the only write endpoints on this dashboard --------------------------------
# They exist because Robinhood publishes no API for event contracts, so nothing
# can read back what was traded there. The operator presses a button on the pick
# they just typed into the phone and the card is frozen as it read.
#
# Reachable only over the SSH tunnel: uvicorn binds 127.0.0.1 and there is no
# proxy in front of it. record_entry() still trusts nothing in the body beyond
# WHICH pick is meant — it re-derives every number server-side.
@app.post("/api/robinhood/entry")
def api_record_entry(body: dict = Body(...)) -> Response:
    from weather_markets.db import get_connection
    from dashboard.data_forecastex import record_entry
    conn = get_connection()
    try:
        out = record_entry(conn, body)
    except ValueError as e:
        return Response(json.dumps({"ok": False, "error": str(e)}),
                        status_code=400, media_type="application/json")
    finally:
        conn.close()
    _forecastex_payload.cache_clear()   # the tab must show it on the next poll
    return _json(out)


@app.delete("/api/robinhood/entry/{entry_id}")
def api_delete_entry(entry_id: int) -> Response:
    from weather_markets.db import get_connection
    from dashboard.data_forecastex import delete_entry
    conn = get_connection()
    try:
        out = delete_entry(conn, entry_id)
    finally:
        conn.close()
    _forecastex_payload.cache_clear()
    return _json(out)


@ttl_cache(300)
def _digest_payload() -> dict:
    """Ops-copilot digest: reads the latest cron-written file, no LLM call
    here. 5min TTL — it's just a file read, cached only to avoid re-parsing
    markdown on every poll."""
    return get_digest_data()


@app.get("/api/digest")
def api_digest() -> Response:
    return _json(_digest_payload())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "dashboard.app:app",
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DASHBOARD_PORT", "8000")),
    )
