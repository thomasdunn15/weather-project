"""Authenticated Kalshi API client.

Kalshi uses RSA-PSS-signed request headers (not bearer tokens). Every
authenticated request needs three headers:
  KALSHI-ACCESS-KEY:       the public Key ID (UUID)
  KALSHI-ACCESS-TIMESTAMP: current Unix time in MILLISECONDS as a string
  KALSHI-ACCESS-SIGNATURE: base64 RSA-PSS signature of (timestamp + method + path)
                           where path is the URL path AFTER the host
                           (e.g. "/trade-api/v2/portfolio/balance")

Signature parameters: SHA-256 digest, MGF1-SHA-256, salt length = digest size (32).

This module is read-only by design (Phase 2). Order placement / cancellation
lives in a future kalshi_orders.py — separate file so Phase 2 acceptance
testing can never accidentally place a real-money order.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .config import settings


class KalshiAuthError(RuntimeError):
    """Raised when Kalshi returns 401/403 or signing fails locally."""


# ----- Kalshi response-parsing helpers ---------------------------------------
# Kalshi's portfolio endpoints encode numerics as strings with suffixes:
#   *_fp        — fixed-point decimal string (e.g. "-50.00" = 50 NO contracts)
#   *_dollars   — dollar amount string (e.g. "30.000000" = $30.00)
# The helpers below normalize these to int contracts / int cents respectively.

def parse_position(p: dict) -> int:
    """Signed contract count for a Kalshi position row.
    Positive = long YES, negative = long NO. Falls back to legacy 'position'."""
    raw = p.get("position_fp")
    if raw is None:
        raw = p.get("position", 0)
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return 0


def parse_count(o: dict, field: str = "remaining_count_fp") -> int:
    """Integer contract count from a *_fp string."""
    raw = o.get(field)
    if raw is None:
        # try without _fp suffix as fallback
        raw = o.get(field.replace("_fp", ""), 0)
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return 0


def parse_dollars_to_cents(o: dict, field: str) -> int:
    """Dollar amount string → integer cents."""
    raw = o.get(field, 0)
    try:
        return int(round(float(raw) * 100))
    except (TypeError, ValueError):
        return 0


class KalshiClient:
    """Authenticated client for Kalshi's REST API. Read-only methods only.

    Lifecycle: construct once per process, reuse across calls. Loads the RSA
    private key from disk at construction time so any key-file problems
    surface immediately rather than on the first request.
    """

    def __init__(
        self,
        key_id: str | None = None,
        key_path: Path | None = None,
        api_base: str | None = None,
        timeout: float = 30.0,
    ):
        self.key_id = key_id or settings.kalshi_key_id
        if not self.key_id:
            raise KalshiAuthError("KALSHI_KEY_ID not set (env or constructor arg)")

        kp = key_path or settings.kalshi_key_path
        if not kp:
            raise KalshiAuthError("KALSHI_KEY_PATH not set (env or constructor arg)")
        self.key_path = Path(kp).expanduser()
        if not self.key_path.is_file():
            raise KalshiAuthError(f"Kalshi private key file not found at {self.key_path}")

        # Load + parse the private key once.
        with self.key_path.open("rb") as f:
            self.private_key = serialization.load_pem_private_key(f.read(), password=None)

        self.api_base = (api_base or settings.kalshi_api_base).rstrip("/")
        self._http = httpx.Client(timeout=timeout)

    # ----- core auth + request helpers --------------------------------------

    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """Generate the KALSHI-ACCESS-SIGNATURE header value.

        path must be the FULL path AFTER the host (e.g. "/trade-api/v2/portfolio/balance").
        Kalshi rejects requests where path omits the API version prefix.
        """
        msg = (timestamp_ms + method + path).encode("utf-8")
        signature = self.private_key.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> dict:
        """Send an authenticated request. endpoint is the suffix after api_base
        (e.g. "/portfolio/balance"). Returns parsed JSON or raises."""
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = self.api_base + endpoint

        # Kalshi signs the FULL path including the /trade-api/v2 prefix that
        # lives inside api_base. Reconstruct it from the URL we're about to hit.
        from urllib.parse import urlparse
        full_path = urlparse(url).path

        timestamp_ms = str(int(time.time() * 1000))
        signature = self._sign(timestamp_ms, method.upper(), full_path)
        headers = {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        resp = self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code in (401, 403):
            raise KalshiAuthError(
                f"Kalshi auth rejected ({resp.status_code}) on {method} {endpoint}: {resp.text[:200]}"
            )
        resp.raise_for_status()
        return resp.json()

    # ----- read-only public methods -----------------------------------------

    def get_balance(self) -> dict:
        """Returns dict with 'balance' field in cents."""
        return self._request("GET", "/portfolio/balance")

    def get_positions(self, ticker: str | None = None) -> dict:
        """All current positions. Optionally filter to one ticker."""
        params = {"ticker": ticker} if ticker else None
        return self._request("GET", "/portfolio/positions", params=params)

    def get_orders(self, ticker: str | None = None, status: str | None = None,
                   limit: int = 100) -> dict:
        """Open + recent orders.

        status: 'resting' (open), 'canceled', 'executed', or None for all.
        """
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        return self._request("GET", "/portfolio/orders", params=params)

    def get_fills(self, ticker: str | None = None, min_ts: int | None = None,
                  limit: int = 100) -> dict:
        """Fill history. min_ts is a Unix-seconds lower bound."""
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if min_ts is not None:
            params["min_ts"] = min_ts
        return self._request("GET", "/portfolio/fills", params=params)

    def get_market(self, ticker: str) -> dict:
        """Fetch current market state (bid/ask/last) for a ticker. Public data
        but goes through the authenticated path for consistency."""
        return self._request("GET", f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 0) -> dict:
        """Fetch the full order book (all price levels with quantities).

        Kalshi convention: response.orderbook contains TWO bid arrays — yes
        and no. There are no separate ask arrays because in binary markets the
        YES ask at price X equals the NO bid at price (100−X). To get YES asks,
        invert the no bid array.

        Args:
            ticker: market ticker
            depth: max levels per side (0 = all). Default 0 — we want full depth
                   for the walk-book backtest.

        Returns:
            Kalshi response dict. The key data is at
            response["orderbook"]["yes"] and response["orderbook"]["no"], each
            being a list of [price_cents, qty] arrays sorted descending by price.
        """
        params = {"depth": depth} if depth > 0 else {}
        return self._request("GET", f"/markets/{ticker}/orderbook", params=params)

    # ----- order placement / cancellation (Phase 3+) ------------------------
    # These methods CAN move real money on production. Callers are responsible
    # for risk controls (size limits, kill switches, etc.) — those live in
    # scripts/live_trade.py, not here. This class is API-level only.

    def place_limit_order(
        self,
        ticker: str,
        side: str,                       # 'yes' or 'no'
        count: int,                      # number of contracts
        price_cents: int,                # limit price in cents (1-99)
        action: str = "buy",             # 'buy' or 'sell'; 'buy' is standard for our strategy
        post_only: bool = True,          # default True — refuse if it would cross
        client_order_id: str | None = None,  # optional idempotency key
    ) -> dict:
        """Place a single limit order. Returns Kalshi's order dict (includes order_id).

        post_only=True is the safe default for our limit-target strategy: Kalshi
        rejects the order if it would cross the spread (i.e. immediately execute
        against the book). Caller can override for cross-spread fallback later.

        side='yes' means buying a YES contract; price_cents is set as yes_price.
        side='no'  means buying a NO  contract; price_cents is set as no_price.
        """
        if side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
        if not 1 <= price_cents <= 99:
            raise ValueError(f"price_cents must be 1-99, got {price_cents}")
        if count < 1:
            raise ValueError(f"count must be >= 1, got {count}")

        body: dict[str, Any] = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": "limit",
            "post_only": post_only,
        }
        if side == "yes":
            body["yes_price"] = price_cents
        else:
            body["no_price"] = price_cents
        if client_order_id is not None:
            body["client_order_id"] = client_order_id

        return self._request("POST", "/portfolio/orders", json=body)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order by Kalshi order_id. Returns the updated order."""
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def get_order(self, order_id: str, ticker: str | None = None) -> dict:
        """Fetch a single order by id.

        Kalshi's elections API returns 404 on GET /portfolio/orders/{id} even
        for orders that exist (the cancel endpoint works on the same path, so
        this is just a routing quirk). Fallback: list recent orders (scoped to
        ticker if known) and filter client-side.
        """
        try:
            return self._request("GET", f"/portfolio/orders/{order_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

        params: dict[str, Any] = {"limit": 200}
        if ticker:
            params["ticker"] = ticker
        listing = self._request("GET", "/portfolio/orders", params=params)
        for o in listing.get("orders", []):
            if o.get("order_id") == order_id:
                return {"order": o}
        raise RuntimeError(f"order_id {order_id} not found in recent orders")

    # ----- session lifecycle ------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
