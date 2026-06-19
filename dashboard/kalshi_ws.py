"""Read-only Kalshi WebSocket live-state service for the dashboard.

Maintains a continuously-updated, cent-accurate cache of live MARKS:

    marks[ticker] = (yes_bid_cents, yes_ask_cents, ts)   # live top-of-book

so the dashboard's mark-to-market (positions[].mark, unrealized, portfolioValue,
balance) is computed from a live feed instead of the `prices` table — which is a
5-minute REST cron that only snapshots status=open markets, so marks otherwise
FREEZE for hours after a market closes (until nightly settlement). Cash/orders
stay on the existing live REST path; this service only fixes the stale marks.

STRICTLY READ-ONLY: it subscribes to the `ticker` data channel; it never places
or cancels orders. It degrades gracefully — if the Kalshi key is missing or the
socket can't connect, it stays `connected=False` and get_live_data falls back to
the DB `prices` snapshot exactly as before.

Source: Kalshi WS v2 (wss://.../trade-api/ws/v2), same RSA-PSS handshake auth as
the REST client (reused via KalshiClient._sign). `websockets` is already present
(transitive via uvicorn[standard]; also pinned explicitly in pyproject).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from typing import Optional

import websockets

from weather_markets.db import get_connection
from weather_markets.kalshi_api import KalshiClient

log = logging.getLogger("dashboard.kalshi_ws")


def _cents(dollar_str) -> Optional[int]:
    """Kalshi WS prices are dollar fixed-point strings ('0.0200' = 2¢)."""
    if dollar_str is None:
        return None
    try:
        return int(round(float(dollar_str) * 100))
    except (TypeError, ValueError):
        return None


class KalshiLiveService:
    REFRESH_SUBS_EVERY = 15.0   # seconds between held-ticker subscription refresh

    def __init__(self) -> None:
        self._client: Optional[KalshiClient] = None
        self._lock = threading.Lock()
        self.marks: dict[str, tuple[int, int, float]] = {}   # ticker -> (yes_bid¢, yes_ask¢, ts)
        self.connected = False
        self.last_msg_ts = 0.0
        self.started_at = time.time()
        self._subscribed: set[str] = set()
        self._next_id = 10
        self._stop = False

    # ---- public read API (called from the sync /api/live path) -------------
    def snapshot(self) -> dict:
        with self._lock:
            marks = dict(self.marks)
            last = self.last_msg_ts
            connected = self.connected
        return {
            "connected": connected,
            "marks": marks,
            "last_msg_ts": last,
            "age_ms": int((time.time() - last) * 1000) if last else None,
        }

    # ---- helpers ----------------------------------------------------------
    def _held_tickers(self) -> set[str]:
        """Tickers we currently hold (open, unsettled) — the markets to mark live."""
        out: set[str] = set()
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT DISTINCT ticker FROM live_trades
                       WHERE fill_status IN ('filled','partial','partial_resting')
                         AND fill_count IS NOT NULL AND fill_count > 0
                         AND settlement IS NULL
                         AND target_date >= (CURRENT_DATE - INTERVAL '3 days')"""
                )
                out = {r[0] for r in cur.fetchall()}
        except Exception as e:  # pragma: no cover - best effort
            log.debug("held_tickers query failed: %s", e)
        return out

    def _ws_url(self) -> str:
        return (self._client.api_base
                .replace("https://", "wss://").replace("http://", "ws://")
                .replace("/trade-api/v2", "/trade-api/ws/v2"))

    def _headers(self) -> dict:
        ts = str(int(time.time() * 1000))
        sig = self._client._sign(ts, "GET", "/trade-api/ws/v2")
        return {
            "KALSHI-ACCESS-KEY": self._client.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    async def _subscribe_ticker(self, ws, tickers) -> None:
        if not tickers:
            return
        self._next_id += 1
        await ws.send(json.dumps({
            "id": self._next_id, "cmd": "subscribe",
            "params": {"channels": ["ticker"],
                       "market_tickers": list(tickers),
                       "send_initial_snapshot": True},
        }))

    # ---- run loop ---------------------------------------------------------
    async def run(self) -> None:
        """Connect-and-stream forever with backoff. Safe to launch as a task."""
        try:
            self._client = KalshiClient()
        except Exception as e:
            log.warning("Kalshi live service disabled (client unavailable): %s", e)
            return
        backoff = 1.0
        while not self._stop:
            try:
                await self._session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                with self._lock:
                    self.connected = False
                log.warning("Kalshi WS session ended (%s); reconnecting in %.0fs",
                            type(e).__name__, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        with self._lock:
            self.connected = False

    async def _session(self) -> None:
        loop = asyncio.get_event_loop()
        url = self._ws_url()
        async with websockets.connect(
            url, additional_headers=self._headers(),
            open_timeout=15, ping_interval=15, ping_timeout=20, close_timeout=5,
        ) as ws:
            with self._lock:
                self.connected = True
                self.last_msg_ts = time.time()
            self._subscribed = set()
            held = await loop.run_in_executor(None, self._held_tickers)
            await self._subscribe_ticker(ws, held)
            self._subscribed = set(held)
            log.info("Kalshi WS connected; live marks for %d held tickers", len(held))

            reader = asyncio.create_task(self._reader(ws))
            keeper = asyncio.create_task(self._keeper(ws))
            try:
                done, _ = await asyncio.wait({reader, keeper}, return_when=asyncio.FIRST_EXCEPTION)
                for t in done:
                    t.result()  # re-raise the failure that ended the session
            finally:
                for t in (reader, keeper):
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await t
                with self._lock:
                    self.connected = False

    async def _reader(self, ws) -> None:
        async for raw in ws:
            try:
                self._handle(json.loads(raw))
            except Exception as e:  # pragma: no cover - never let one bad msg kill the stream
                log.debug("bad WS message: %s", e)

    def _handle(self, m: dict) -> None:
        now = time.time()
        with self._lock:
            self.last_msg_ts = now
        if m.get("type") == "ticker":
            msg = m.get("msg", {})
            tk = msg.get("market_ticker")
            yb = _cents(msg.get("yes_bid_dollars"))
            ya = _cents(msg.get("yes_ask_dollars"))
            if tk and yb is not None and ya is not None:
                with self._lock:
                    self.marks[tk] = (yb, ya, now)

    async def _keeper(self, ws) -> None:
        """Periodically add live subscriptions for newly-held tickers."""
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(self.REFRESH_SUBS_EVERY)
            held = await loop.run_in_executor(None, self._held_tickers)
            new = held - self._subscribed
            if new:
                await self._subscribe_ticker(ws, new)
                self._subscribed |= new
                log.info("Kalshi WS: added live marks for %d new ticker(s)", len(new))


# Module-level singleton — started by the FastAPI lifespan, read by get_live_data.
service = KalshiLiveService()


def live_snapshot() -> dict:
    return service.snapshot()
