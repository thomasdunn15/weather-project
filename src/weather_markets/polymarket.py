"""Minimal Polymarket US API client.

Auth: Ed25519-signed REST requests per docs.polymarket.us.
  Headers required:
    X-PM-Access-Key:  the key_id string
    X-PM-Timestamp:   current ms since epoch (must be within 30s of server time)
    X-PM-Signature:   base64(ed25519_sign(secret, f"{timestamp}{method}{path}"))

Credentials come from env: POLYMARKET_KEY_ID, POLYMARKET_SECRET (base64-encoded).

This is a thin read-mostly client. Order placement intentionally NOT included
in this first cut — we want to validate market data + account access before
adding write surface.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519


# Polymarket US has two host conventions in the docs:
#   - api.polymarket.us — used in api-reference/portfolio/* examples
#   - api.prod.polymarketexchange.com — used in environments.md as "Production"
# Per testing 2026-06-08: portfolio paths are on api.polymarket.us. Other paths
# may live elsewhere. Adjust per call as needed.
PROD_BASE_URL = "https://api.polymarket.us"
EXCHANGE_BASE_URL = "https://api.prod.polymarketexchange.com"
DEV_BASE_URL = "https://api.dev01.polymarketexchange.com"
PREPROD_BASE_URL = "https://api.preprod.polymarketexchange.com"


class PolymarketAuthError(RuntimeError):
    pass


@dataclass
class PolymarketCreds:
    key_id: str
    secret_b64: str

    @classmethod
    def from_env(cls) -> "PolymarketCreds":
        # Use the project's Settings (pydantic-settings) which auto-loads .env.
        # Falls back to os.environ if Settings isn't importable for any reason.
        try:
            from weather_markets.config import settings
            key_id = settings.polymarket_key_id
            secret = settings.polymarket_secret
        except Exception:
            key_id = os.environ.get("POLYMARKET_KEY_ID")
            secret = os.environ.get("POLYMARKET_SECRET")
        if not key_id or not secret:
            raise PolymarketAuthError(
                "POLYMARKET_KEY_ID and POLYMARKET_SECRET must be set in .env "
                "(or as environment variables)"
            )
        return cls(key_id=key_id, secret_b64=secret)


class PolymarketClient:
    def __init__(self, creds: PolymarketCreds | None = None, base_url: str = PROD_BASE_URL):
        self.creds = creds or PolymarketCreds.from_env()
        self.base_url = base_url.rstrip("/")
        # Decode the secret to raw 32-byte Ed25519 private key
        raw = base64.b64decode(self.creds.secret_b64)
        if len(raw) < 32:
            raise PolymarketAuthError(f"decoded secret is {len(raw)} bytes, expected 32+")
        self._private_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32])
        self._client = httpx.Client(timeout=30.0)

    def _sign(self, method: str, path: str, timestamp_ms: str) -> str:
        """Sign `{timestamp}{method}{path}` with Ed25519 → base64."""
        message = f"{timestamp_ms}{method}{path}".encode()
        sig_bytes = self._private_key.sign(message)
        return base64.b64encode(sig_bytes).decode()

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        return {
            "X-PM-Access-Key": self.creds.key_id,
            "X-PM-Timestamp": ts,
            "X-PM-Signature": self._sign(method, path, ts),
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: dict | None = None,
                 json_body: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._auth_headers(method, path)
        if method == "GET":
            r = self._client.get(url, headers=headers, params=params)
        elif method == "POST":
            r = self._client.post(url, headers=headers, params=params, json=json_body)
        else:
            raise NotImplementedError(f"unsupported method: {method}")
        if r.is_error:
            raise RuntimeError(f"{r.status_code} {r.reason_phrase} for {url}: {r.text}")
        return r.json()

    # === Historical price data (Polymarket DOES have this) ===

    def get_candlesticks(self, slug: str, start: str, end: str, interval: str = "5m") -> dict:
        """POST /v1beta1/report/trades/stats — server-aggregated OHLCV candles.

        Args:
            slug: market slug (e.g., 'tc-temp-mdwhigh-2026-06-08-gte80lt81f')
            start: ISO 8601 UTC start timestamp
            end:   ISO 8601 UTC end timestamp
            interval: '1m', '5m', '15m', '1h', '4h', '1d'

        Returns dict with candles list: {interval_start, interval_end,
        open, high, low, close, volume, notional}
        """
        body = {"symbol": slug, "start_time": start, "end_time": end, "interval": interval}
        return self._request("POST", "/v1beta1/report/trades/stats", json_body=body)

    # === Public-ish market data (still authed via headers) ===

    def list_markets(self, limit: int = 50, **filters) -> dict:
        """GET /v1/markets — list all markets with optional filtering."""
        params = {"limit": limit, **filters}
        return self._request("GET", "/v1/markets", params=params)

    def get_market_by_slug(self, slug: str) -> dict:
        """GET /v1/market/slug/{slug} — market details."""
        return self._request("GET", f"/v1/market/slug/{slug}")

    def get_orderbook(self, slug: str) -> dict:
        """GET /v1/markets/{slug}/book — full order book + stats."""
        return self._request("GET", f"/v1/markets/{slug}/book")

    def get_bbo(self, slug: str) -> dict:
        """GET /v1/markets/{slug}/bbo — best bid/offer (lightweight)."""
        return self._request("GET", f"/v1/markets/{slug}/bbo")

    # === Account ===

    def create_order(self, slug: str, intent: str, price_usd: float, quantity: float,
                     tif: str = "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
                     max_block_secs: int = 10) -> dict:
        """POST /v1/orders — synchronous IOC marketable limit by default.

        IOC + limit means: fill at or better than price_usd immediately, cancel
        the rest — the order NEVER rests on the book. intent is one of
        ORDER_INTENT_BUY_LONG (buy YES) / ORDER_INTENT_BUY_SHORT (buy NO).
        `price_usd` is the bound for the side BEING BOUGHT — a YES price for
        LONG, a NO price for SHORT. Response includes `executions`.

        WIRE PRICE IS ALWAYS THE YES LEG. A BUY_SHORT is submitted as
        ORDER_SIDE_SELL of YES, so the venue reads `price` as a YES-side floor
        ("sell YES at >= p"), never as the NO price. Passing the NO bound
        straight through inverts the protection:

          2026-08-22: NO bound 64c sent as 0.64 => "sell YES at >= 0.64" while
          the YES bid was 0.38-0.43. Not marketable, IOC cancelled untouched,
          cumQuantity 0 of 150 — a signal that should have filled and did not.

        It also silently voids the price cap on orders that DO fill: a low NO
        bound becomes a low YES floor, which any bid clears, so we could pay far
        more for NO than the bound allowed (2026-08-23 took an execution at NO
        43c against a 42c bound). Converting here rather than at the call site
        keeps every caller honest.
        """
        if not 0.0 <= price_usd <= 1.0:
            raise ValueError(f"price_usd must be a probability in [0,1], got {price_usd}")
        wire_price = (1.0 - price_usd
                      if intent == "ORDER_INTENT_BUY_SHORT" else price_usd)
        body = {
            "marketSlug": slug,
            "type": "ORDER_TYPE_LIMIT",
            "price": {"value": f"{wire_price:.2f}", "currency": "USD"},
            "quantity": quantity,
            "tif": tif,
            "intent": intent,
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
            "synchronousExecution": True,
            "maxBlockTime": str(max_block_secs),
        }
        return self._request("POST", "/v1/orders", json_body=body)

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v1/orders/{order_id}")

    def get_balance(self) -> dict:
        """GET /v1/account/balances — account balance."""
        return self._request("GET", "/v1/account/balances")

    def get_positions(self) -> dict:
        """GET /v1/portfolio/positions — current positions."""
        return self._request("GET", "/v1/portfolio/positions")

    def get_activities(self) -> dict:
        """GET /v1/portfolio/activities — trading activity history."""
        return self._request("GET", "/v1/portfolio/activities")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PolymarketClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
