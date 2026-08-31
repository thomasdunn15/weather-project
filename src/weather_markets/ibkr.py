"""IBKR Client Portal Web API client — ForecastEx event-contract execution only.

MARKET DATA DOES NOT COME FROM HERE. ForecastEx publishes prices, tick prints and
settlements publicly with no auth (see weather_markets.forecastex), and that is
what the models and backtests run on. This module exists purely to place and
track orders, which is the one thing the public API cannot do.

Auth: the Client Portal Gateway is a local Java daemon that holds the session;
every request goes to it, not to IBKR directly, and it must be re-authenticated
daily. `IBKR_API_BASE` points at it (default https://localhost:5000/v1/api, self-
signed cert hence verify=False). Switching to hosted OAuth later means changing
that one setting to https://api.ibkr.com/v1/api and adding request signing.

CONTRACT MODEL — IBKR models ForecastEx instruments as OPTIONS:
    right="C" (Call) == YES contract      right="P" (Put) == NO contract
    strike            == the temperature threshold
    month             == MMMYY, e.g. "AUG26"
Discovery is a three-hop walk (search -> strikes -> info) and costs one request
PER STRIKE, so conids are cached to disk. IBKR states conids are persistent for
the life of an instrument, so the cache never needs invalidating.

*** ForecastEx contracts CANNOT BE SOLD, ONLY BOUGHT. ***
You exit a position by buying the opposing contract; IBKR nets the pair
automatically. There is no unwind-at-market. place_order() refuses sells rather
than letting the exchange reject them mid-session.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from .config import settings

# ForecastEx charges a flat $0.01 per contract per side — NOT Kalshi's
# 7%*p*(1-p). Cheap enough that it barely moves sizing, but it is per side, so a
# position that is opened and closed pays it twice.
FEE_CENTS_PER_CONTRACT = 1.0

_CONID_CACHE = Path(__file__).resolve().parents[2] / "data" / "ibkr_conids.json"


class IBKRError(RuntimeError):
    """Gateway unreachable, session dead, or IBKR returned an error payload."""


class IBKRClient:
    def __init__(self, base_url: str | None = None, account_id: str | None = None,
                 timeout: float = 30.0):
        self.base_url = (base_url or settings.ibkr_api_base).rstrip("/")
        self.account_id = account_id or settings.ibkr_account_id
        # The gateway serves a self-signed cert on localhost. verify=False is
        # correct for a loopback daemon and wrong for anything else, so only
        # disable it when we are actually talking to localhost.
        local = "localhost" in self.base_url or "127.0.0.1" in self.base_url
        self._client = httpx.Client(timeout=timeout, verify=not local)

    def _request(self, method: str, path: str, **kw) -> Any:
        try:
            r = self._client.request(method, f"{self.base_url}{path}", **kw)
        except httpx.RequestError as e:
            # RequestError, not ConnectError: a WEDGED gateway accepts the socket
            # and then never answers, which raises ReadTimeout. Catching only
            # ConnectError let that escape as an unhandled traceback, so the one
            # job of ibkr_keepalive.py -- make a dead session loud -- silently
            # failed for exactly the failure mode a keepalive exists to catch.
            raise IBKRError(
                f"cannot reach the Client Portal Gateway at {self.base_url}. "
                f"Is it running and authenticated? ({type(e).__name__}: {e})") from e
        if r.is_error:
            raise IBKRError(f"{r.status_code} {method} {path}: {r.text[:300]}")
        return r.json()

    # ----- session ----------------------------------------------------------
    def auth_status(self) -> dict:
        """Gateway session state. `authenticated` false means re-login is needed."""
        return self._request("POST", "/iserver/auth/status")

    def tickle(self) -> dict:
        """Keepalive. The session times out after ~5 idle minutes."""
        return self._request("POST", "/tickle")

    def ssodh_init(self) -> dict:
        """Establish the BROKERAGE session on top of an existing SSO login.

        These are two separate handshakes and the difference is invisible on the
        gateway's web page: after a browser/2FA login `/sso/validate` returns
        RESULT true while `/iserver/auth/status` still says authenticated=false,
        because nothing has opened the brokerage session yet. Every /iserver/*
        call — quotes, orders, positions — fails until this runs.
        """
        return self._request("POST", "/iserver/auth/ssodh/init",
                             json={"publish": True, "compete": True})

    def require_session(self, autoinit: bool = True) -> None:
        st = self.auth_status()
        if not st.get("authenticated") and autoinit:
            # A valid SSO login that simply never opened its brokerage session
            # is recoverable without a human; a genuinely expired one is not.
            # Trying costs one call and turns the common case into a no-op.
            try:
                self.ssodh_init()
            except IBKRError:
                pass
            else:
                st = self.auth_status()
        if not st.get("authenticated"):
            raise IBKRError(f"gateway session not authenticated: {st}")

    # ----- discovery --------------------------------------------------------
    def underlier(self, product: str) -> dict:
        """Resolve a ForecastEx product code (e.g. 'UHLAX') to its index record.

        Returns the record carrying `conid` and `opt` (a semicolon-separated
        list of YYYYMMDD expiries). Results are not unique, so filter to the
        FORECASTX listing rather than trusting position 0.
        """
        rows = self._request("GET", "/iserver/secdef/search", params={"symbol": product})
        for row in rows:
            if "FORECASTX" in (row.get("description") or "").upper():
                return row
        raise IBKRError(f"no FORECASTX index record for {product!r}; got "
                        f"{[r.get('description') for r in rows]}")

    def strikes(self, conid: str, month: str) -> list[float]:
        """Valid strikes for one contract month. Calls and puts always match, so
        the two lists IBKR returns are collapsed into one."""
        r = self._request("GET", "/iserver/secdef/strikes",
                          params={"conid": conid, "exchange": "FORECASTX",
                                  "sectype": "OPT", "month": month})
        return sorted({*(r.get("call") or []), *(r.get("put") or [])})

    def contracts_at_strike(self, conid: str, month: str, strike: float) -> list[dict]:
        """Instrument records for one (month, strike). Empty when nothing trades
        there. Returns a Call (YES) / Put (NO) pair per expiry — weather products
        expire DAILY, so a month can hold many pairs at the same strike and
        callers must match on maturityDate."""
        return self._request("GET", "/iserver/secdef/info",
                             params={"conid": conid, "exchange": "FORECASTX",
                                     "sectype": "OPT", "month": month,
                                     "strike": strike}) or []

    def resolve(self, product: str, event: date, strike: float) -> dict[str, int]:
        """(product, EVENT date, strike) -> {'yes': conid, 'no': conid}, disk-cached.

        `event` is the day the temperature is measured — the same value as our
        contracts.target_date and ForecastEx's own contract id (UHLAX_082026_80).

        *** IBKR's maturityDate IS the event date. No off-by-one. ***
        Measured live 2026-08-23 16:10Z on UHMIA strike 92, quoting both
        candidate maturities side by side:

            maturity 20260822  YES bid None ask None last C0.98   <- SETTLED
            maturity 20260823  YES bid 0.60 ask 0.73  last 0.66   <- LIVE

        20260823 was that day's event and it was the one trading. The ladder
        offered maturities 20260814..20260823 and NO 20260824 at all, so the
        event+1 rule this docstring used to assert resolved to a date that does
        not exist and returned {} for every strike — every ForecastEx order on
        2026-08-23 failed with "could not resolve both legs".

        That earlier rule came from seeing 0.98/0.02 and concluding we were
        being handed a settled contract. We were, but because of a STALE CONID
        CACHE, not a date offset; clearing the cache was the real fix and the
        +1 was a misdiagnosis layered on top. If settled-looking quotes appear
        again, suspect the cache below before touching this arithmetic.

        Discovery costs one request per strike, so a full ladder is ~30 calls.
        Conids never change, so a cache hit is always safe to trust.
        """
        key = f"{product}_{event:%Y%m%d}_{strike:g}"
        cache = json.loads(_CONID_CACHE.read_text()) if _CONID_CACHE.exists() else {}
        if key in cache:
            return cache[key]

        idx = self.underlier(product)
        month = f"{event:%b%y}".upper()
        pair: dict[str, int] = {}
        for rec in self.contracts_at_strike(idx["conid"], month, strike):
            if str(rec.get("maturityDate", "")) != f"{event:%Y%m%d}":
                continue
            pair["yes" if rec.get("right") == "C" else "no"] = int(rec["conid"])
        if len(pair) != 2:
            raise IBKRError(
                f"could not resolve both legs for {key} "
                f"(looked for maturityDate {event:%Y%m%d}): {pair}")

        cache[key] = pair
        _CONID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CONID_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
        return pair

    # ----- market data ------------------------------------------------------
    def snapshot(self, conids: list[int], fields: str = "31,84,85,86,88") -> list[dict]:
        """Quote snapshot. 31=last, 84=bid, 85=ask size, 86=ask, 88=bid size.

        IBKR primes the subscription on first call and often returns a sparse
        row; callers that need a filled quote should call twice.
        """
        return self._request("GET", "/iserver/marketdata/snapshot",
                             params={"conids": ",".join(map(str, conids)),
                                     "fields": fields})

    # ----- orders -----------------------------------------------------------
    def place_order(self, conid: int, quantity: int, price: float,
                    order_type: str = "LMT", tif: str = "DAY",
                    confirm: bool = False) -> Any:
        """Buy `quantity` contracts of `conid` at limit `price` (dollars, 0-1).

        `confirm` must be passed explicitly — this moves real money, and a
        default-on order path is how test runs become live trades.

        IBKR frequently answers with a list of confirmation prompts instead of
        an order ack; those are returned as-is for the caller to reply to via
        /iserver/reply/{id} rather than being auto-accepted here.
        """
        if not confirm:
            raise IBKRError("refusing to place a live order without confirm=True")
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        if not 0 < price < 1:
            raise ValueError(f"price is in dollars per contract (0-1), got {price}")
        if not self.account_id:
            raise IBKRError("IBKR_ACCOUNT_ID is not set")

        return self._request(
            "POST", f"/iserver/account/{self.account_id}/orders",
            json={"orders": [{
                "conid": int(conid),
                "orderType": order_type,
                # ForecastEx forbids selling; exiting means buying the other leg.
                "side": "BUY",
                "quantity": int(quantity),
                "price": round(float(price), 2),
                "tif": tif,
            }]})

    def reply(self, reply_id: str, confirmed: bool = True) -> Any:
        """Answer one IBKR confirmation prompt."""
        return self._request("POST", f"/iserver/reply/{reply_id}",
                             json={"confirmed": bool(confirmed)})

    @staticmethod
    def _is_prompt(resp: Any) -> dict | None:
        """A confirmation prompt looks like [{'id': <uuid>, 'message': [...]}]."""
        if isinstance(resp, list) and resp and isinstance(resp[0], dict):
            if "id" in resp[0] and "message" in resp[0]:
                return resp[0]
        return None

    def submit_order(self, conid: int, quantity: int, price: float,
                     order_type: str = "LMT", tif: str = "DAY",
                     confirm: bool = False, max_replies: int = 5) -> tuple[Any, list[str]]:
        """place_order, then WALK IBKR's confirmation chain to an actual ack.

        place_order alone does not place anything when IBKR raises a warning: it
        returns [{'id': <replyId>, 'message': [...]}] and the order sits in limbo
        until /iserver/reply/{id} is answered. Nothing in this repo answered it,
        so every ForecastEx order ever "placed" was a prompt nobody replied to —
        on 2026-08-23 three Miami orders reported success with 0 orders on the
        book. Confirming is what places the order, so it belongs on this path.

        Returns (final_response, prompts_agreed_to). The prompts are returned so
        the caller can LOG what it just agreed to; silently accepting warnings
        about size, price or margin is how an automated path gets expensive.
        """
        resp = self.place_order(conid, quantity, price, order_type, tif, confirm)
        prompts: list[str] = []
        for _ in range(max_replies):
            p = self._is_prompt(resp)
            if p is None:
                return resp, prompts
            prompts.extend(str(m) for m in (p.get("message") or []))
            resp = self.reply(p["id"], confirmed=True)
        raise IBKRError(
            f"IBKR kept prompting after {max_replies} confirmations; "
            f"order NOT confirmed. Prompts: {prompts}")

    def live_orders(self) -> Any:
        return self._request("GET", "/iserver/account/orders")

    def positions(self) -> Any:
        return self._request("GET", f"/portfolio/{self.account_id}/positions/0")

    def sso_age_hours(self) -> float | None:
        """Hours since the underlying SSO login, or None if there is no session.

        A brokerage session cannot be opened from an SSO that is merely still
        "valid" — IBKR wants a recent authentication. So the age is the number
        that distinguishes "needs a tickle" from "needs a human at a browser",
        and neither auth_status nor the gateway's own web page reports it.
        """
        try:
            v = self._request("GET", "/sso/validate")
        except IBKRError:
            return None
        at = (v or {}).get("AUTH_TIME")
        if not at:
            return None
        from datetime import datetime, timezone
        return (datetime.now(timezone.utc)
                - datetime.fromtimestamp(at / 1000, timezone.utc)).total_seconds() / 3600

    def net_liquidation(self) -> float:
        """Account net liquidation value in USD.

        This is the base IBKR applies its retail event-contract limit to (2% of
        account value as of 2026-08-24). Read it rather than hardcoding a cap:
        the limit moves with the account, so a constant would silently under- or
        over-size the moment the balance changes.
        """
        d = self._request("GET", f"/portfolio/{self.account_id}/summary")
        try:
            return float(d["netliquidation"]["amount"])
        except (KeyError, TypeError, ValueError) as e:
            raise IBKRError(f"could not read netliquidation from summary: {e}") from e
