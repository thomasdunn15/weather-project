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

    def _request(self, method: str, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._auth_headers(method, path)
        if method == "GET":
            r = self._client.get(url, headers=headers, params=params)
        else:
            raise NotImplementedError(f"only GET supported in read-only client; got {method}")
        r.raise_for_status()
        return r.json()

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
