"""Guards on the IBKR order path that must hold without a live gateway."""
import ssl

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


def test_localhost_skips_cert_verification_but_remote_does_not():
    """The gateway serves a self-signed cert on loopback, so verification is off
    there. If we ever point this at hosted OAuth, TLS must come back on — this
    fails loudly if the localhost check is ever loosened to match everything."""
    ctx = lambda url: IBKRClient(base_url=url)._client._transport._pool._ssl_context
    assert ctx("https://localhost:5000/v1/api").verify_mode == ssl.CERT_NONE
    assert ctx("https://api.ibkr.com/v1/api").verify_mode == ssl.CERT_REQUIRED


def test_resolve_targets_the_settlement_date_not_the_event_date(tmp_path, monkeypatch):
    """ForecastEx settles T+1 and IBKR labels contracts by SETTLEMENT date.

    Resolving on the event date silently returns YESTERDAY'S contract — which
    is already settled, so every price looks like 0.02/0.98 and any order would
    trade a known outcome. Caught live on 2026-08-20; this pins it.
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
        return [{"conid": 111, "right": "C", "maturityDate": "20260821"},
                {"conid": 222, "right": "P", "maturityDate": "20260821"},
                # the event-dated pair must NOT be chosen
                {"conid": 333, "right": "C", "maturityDate": "20260820"},
                {"conid": 444, "right": "P", "maturityDate": "20260820"}]

    monkeypatch.setattr(c, "contracts_at_strike", fake_info)
    got = c.resolve("UHLAX", date(2026, 8, 20), 80.0)
    assert got == {"yes": 111, "no": 222}, "picked the event-dated (settled) contract"
    assert asked["month"] == "AUG26"
    # cached under the EVENT date, which is what callers pass
    assert "UHLAX_20260820_80" in json.loads((tmp_path / "conids.json").read_text())


def test_resolve_rolls_the_month_when_settlement_crosses_month_end(tmp_path, monkeypatch):
    """An event on the 31st settles on the 1st, so the MMMYY month must roll too."""
    from datetime import date
    from weather_markets import ibkr

    monkeypatch.setattr(ibkr, "_CONID_CACHE", tmp_path / "conids.json")
    c = IBKRClient(base_url="https://localhost:5000/v1/api", account_id="U1")
    monkeypatch.setattr(c, "underlier", lambda p: {"conid": "999"})
    asked = {}

    def fake_info(conid, month, strike):
        asked["month"] = month
        return [{"conid": 1, "right": "C", "maturityDate": "20260901"},
                {"conid": 2, "right": "P", "maturityDate": "20260901"}]

    monkeypatch.setattr(c, "contracts_at_strike", fake_info)
    assert c.resolve("UHLAX", date(2026, 8, 31), 80.0) == {"yes": 1, "no": 2}
    assert asked["month"] == "SEP26", "month must follow settlement, not the event"
