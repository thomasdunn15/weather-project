"""Guards on the IBKR order path that must hold without a live gateway."""
import ssl

import httpx
import pytest

from weather_markets.ibkr import IBKRClient, IBKRError


@pytest.fixture
def client():
    return IBKRClient(base_url="https://localhost:5000/v1/api", account_id="U123")


def test_order_requires_explicit_confirm(client):
    """A default-on order path is how a test run becomes a live trade."""
    with pytest.raises(IBKRError, match="confirm=True"):
        client.place_order(conid=1, quantity=10, price=0.40)


def test_price_must_be_dollars_not_cents(client):
    """40 (cents) instead of 0.40 (dollars) would be a 100x overpay, and IBKR
    would happily accept it as a limit."""
    for bad in (40, 1.0, 0.0, -0.1):
        with pytest.raises(ValueError, match="dollars"):
            client.place_order(conid=1, quantity=10, price=bad, confirm=True)


def test_quantity_must_be_positive(client):
    """ForecastEx cannot be sold, so a negative quantity is never a short —
    it is a bug."""
    with pytest.raises(ValueError, match="positive"):
        client.place_order(conid=1, quantity=-5, price=0.40, confirm=True)


def test_missing_account_id_is_caught_before_the_wire(monkeypatch):
    """account_id=None falls back to settings, so blank the setting too —
    otherwise this passes only on machines that never configured .env."""
    from weather_markets import ibkr
    monkeypatch.setattr(ibkr.settings, "ibkr_account_id", None)
    c = IBKRClient(base_url="https://localhost:5000/v1/api", account_id=None)
    with pytest.raises(IBKRError, match="IBKR_ACCOUNT_ID"):
        c.place_order(conid=1, quantity=10, price=0.40, confirm=True)


def test_unreachable_gateway_says_so():
    """A dead gateway must name itself, not surface a bare ConnectError.

    Uses a port nothing binds — 5000 is the real gateway and may be running.
    """
    dead = IBKRClient(base_url="https://127.0.0.1:59999/v1/api", account_id="U1")
    with pytest.raises(IBKRError, match="Client Portal Gateway"):
        dead.auth_status()


def test_hung_gateway_is_an_ibkr_error_not_a_traceback(monkeypatch):
    """A WEDGED gateway (accepts the socket, never answers) must be caught too.

    This is the failure mode that actually bit us: ibkr_keepalive.py catches
    IBKRError, so a ReadTimeout escaping as an unhandled traceback meant the
    session-death alert never fired for a hung gateway -- the exact case a
    keepalive exists to catch.
    """
    client = IBKRClient(base_url="https://127.0.0.1:59999/v1/api", account_id="U1")

    def _boom(*a, **kw):
        raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(client._client, "request", _boom)
    with pytest.raises(IBKRError, match="ReadTimeout"):
        client.auth_status()


def test_localhost_skips_cert_verification_but_remote_does_not():
    """The gateway serves a self-signed cert on loopback, so verification is off
    there. If we ever point this at hosted OAuth, TLS must come back on — this
    fails loudly if the localhost check is ever loosened to match everything."""
    ctx = lambda url: IBKRClient(base_url=url)._client._transport._pool._ssl_context
    assert ctx("https://localhost:5000/v1/api").verify_mode == ssl.CERT_NONE
    assert ctx("https://api.ibkr.com/v1/api").verify_mode == ssl.CERT_REQUIRED


def test_resolve_targets_the_EVENT_date(tmp_path, monkeypatch):
    """IBKR's maturityDate IS the event date — there is no T+1 offset.

    RETIRED ASSERTION (was `test_resolve_targets_the_settlement_date...`):
    this test used to require the event+1 pair and reject the event-dated one.
    That was backwards. Measured live 2026-08-23 on UHMIA strike 92:

        maturity 20260822  YES bid None ask None last C0.98   <- settled
        maturity 20260823  YES bid 0.60 ask 0.73  last 0.66   <- live

    and the ladder offered no 20260824 at all, so event+1 resolved to a
    nonexistent date and every ForecastEx order that day failed to place.
    """
    import json
    from datetime import date
    from weather_markets import ibkr

    monkeypatch.setattr(ibkr, "_CONID_CACHE", tmp_path / "conids.json")
    c = IBKRClient(base_url="https://localhost:5000/v1/api", account_id="U1")
    monkeypatch.setattr(c, "underlier", lambda p: {"conid": "999"})
    asked = {}

    def fake_info(conid, month, strike):
        asked["month"] = month
        return [{"conid": 333, "right": "C", "maturityDate": "20260820"},
                {"conid": 444, "right": "P", "maturityDate": "20260820"},
                # the PREVIOUS day's pair is the settled one — never pick it
                {"conid": 111, "right": "C", "maturityDate": "20260819"},
                {"conid": 222, "right": "P", "maturityDate": "20260819"}]

    monkeypatch.setattr(c, "contracts_at_strike", fake_info)
    got = c.resolve("UHLAX", date(2026, 8, 20), 80.0)
    assert got == {"yes": 333, "no": 444}, "must pick the EVENT-dated contract"
    assert asked["month"] == "AUG26"
    assert "UHLAX_20260820_80" in json.loads((tmp_path / "conids.json").read_text())


def test_resolve_uses_the_event_month_at_month_end(tmp_path, monkeypatch):
    """An event on the 31st stays in that month — it does not roll to the next.

    Under the retired event+1 rule this asserted SEP26 for an Aug 31 event.
    With maturityDate == event date it must stay AUG26, or month-end events
    silently query the wrong month and resolve nothing.
    """
    from datetime import date
    from weather_markets import ibkr

    monkeypatch.setattr(ibkr, "_CONID_CACHE", tmp_path / "conids.json")
    c = IBKRClient(base_url="https://localhost:5000/v1/api", account_id="U1")
    monkeypatch.setattr(c, "underlier", lambda p: {"conid": "999"})
    asked = {}

    def fake_info(conid, month, strike):
        asked["month"] = month
        return [{"conid": 1, "right": "C", "maturityDate": "20260831"},
                {"conid": 2, "right": "P", "maturityDate": "20260831"}]

    monkeypatch.setattr(c, "contracts_at_strike", fake_info)
    assert c.resolve("UHLAX", date(2026, 8, 31), 80.0) == {"yes": 1, "no": 2}
    assert asked["month"] == "AUG26", "month follows the EVENT date"


def test_require_session_opens_a_brokerage_session_before_giving_up(monkeypatch):
    """A valid SSO login with no brokerage session must self-heal, not alert.

    This is the state a 2FA login actually leaves behind: /sso/validate says
    RESULT true, /iserver/auth/status says authenticated false, and the gateway
    web page looks fine. Requiring a human for that handshake wastes a morning.
    """
    client = IBKRClient(base_url="https://127.0.0.1:59999/v1/api", account_id="U1")
    calls = {"status": 0, "init": 0}

    def fake_status():
        calls["status"] += 1
        return {"authenticated": calls["init"] > 0}

    def fake_init():
        calls["init"] += 1
        return {"passed": True}

    monkeypatch.setattr(client, "auth_status", fake_status)
    monkeypatch.setattr(client, "ssodh_init", fake_init)
    client.require_session()                 # must NOT raise
    assert calls["init"] == 1


def test_require_session_still_raises_when_init_cannot_help(monkeypatch):
    """A genuinely expired SSO must still be loud — autoinit is not a mute button."""
    client = IBKRClient(base_url="https://127.0.0.1:59999/v1/api", account_id="U1")
    monkeypatch.setattr(client, "auth_status", lambda: {"authenticated": False})
    monkeypatch.setattr(client, "ssodh_init", lambda: {"passed": False})
    with pytest.raises(IBKRError, match="not authenticated"):
        client.require_session()
