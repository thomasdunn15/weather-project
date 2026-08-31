"""The BUY_SHORT wire price must be the YES leg, not the NO bound.

Regression for 2026-08-22: a NO bound of 64c went out as "sell YES at >= 0.64"
against a 0.38-0.43 YES bid. The IOC cancelled with cumQuantity 0 of 150 and the
signal was simply missed. The same inversion also voids the price cap in the
other direction, so both are asserted.
"""
import base64

import pytest

from weather_markets.polymarket import PolymarketClient, PolymarketCreds


@pytest.fixture
def sent(monkeypatch):
    """Capture the body create_order would put on the wire."""
    c = PolymarketClient(creds=PolymarketCreds(key_id="k",
                          secret_b64=base64.b64encode(b"\0" * 32).decode()))
    box = {}

    def fake(method, path, json_body=None, **kw):
        box["body"] = json_body
        return {"id": "TEST", "executions": []}

    monkeypatch.setattr(c, "_request", fake)
    return c, box


def price_of(box):
    return float(box["body"]["price"]["value"])


def test_buy_short_sends_the_complement(sent):
    c, box = sent
    c.create_order("slug", "ORDER_INTENT_BUY_SHORT", 0.64, 150)
    # "pay at most 64c for NO" == "sell YES at 36c or better"
    assert price_of(box) == pytest.approx(0.36)


def test_buy_long_is_sent_unchanged(sent):
    c, box = sent
    c.create_order("slug", "ORDER_INTENT_BUY_LONG", 0.64, 150)
    assert price_of(box) == pytest.approx(0.64)


def test_the_2026_08_22_order_would_have_been_marketable(sent):
    """The concrete miss: YES bid was 0.38-0.43, so the floor must sit under it."""
    c, box = sent
    c.create_order("tc-temp-miahigh-2026-08-22-gte92lt93f",
                   "ORDER_INTENT_BUY_SHORT", 0.64, 150)
    assert price_of(box) <= 0.38, "must be marketable against a 0.38 YES bid"


def test_cheap_no_bound_does_not_become_a_permissive_floor(sent):
    """A 10c NO bound must be a 0.90 YES floor, not a 0.10 one anything clears."""
    c, box = sent
    c.create_order("slug", "ORDER_INTENT_BUY_SHORT", 0.10, 150)
    assert price_of(box) == pytest.approx(0.90)


@pytest.mark.parametrize("bad", [-0.01, 1.5, 64])
def test_price_must_be_a_probability(sent, bad):
    """64 (cents) instead of 0.64 must raise, not quietly ship a nonsense limit."""
    c, _ = sent
    with pytest.raises(ValueError):
        c.create_order("slug", "ORDER_INTENT_BUY_SHORT", bad, 150)
