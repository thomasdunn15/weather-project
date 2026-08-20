"""Pure-function tests for the Polymarket live probe (no network, no DB)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "live_trade_polymarket",
    Path(__file__).resolve().parents[1] / "scripts" / "live_trade_polymarket.py",
)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def test_choose_signals_threshold_bounds_and_cap():
    qp = [
        {"ticker": "a", "bid": 20, "ask": 22, "p_model": 0.60},   # edge +0.39 -> BUY_LONG @22
        {"ticker": "b", "bid": 70, "ask": 74, "p_model": 0.10},   # edge -0.62 -> BUY_SHORT @30
        {"ticker": "c", "bid": 50, "ask": 52, "p_model": 0.60},   # edge +0.09 -> below threshold
        {"ticker": "d", "bid": 1, "ask": 3, "p_model": 0.90},     # entry 3 < ENTRY_MIN -> dropped
        {"ticker": "e", "bid": 40, "ask": 44, "p_model": 0.95},   # edge +0.53 -> BUY_LONG @44
    ]
    out = mod.choose_signals(qp)
    assert [s["ticker"] for s in out] == ["b", "e"]  # top-2 by |edge|, capped
    assert out[0]["intent"] == "ORDER_INTENT_BUY_SHORT" and out[0]["entry"] == 30
    assert out[1]["intent"] == "ORDER_INTENT_BUY_LONG" and out[1]["entry"] == 44


def test_parse_fills_handles_missing_and_averages():
    resp = {"id": "x", "executions": [
        {"quantity": 10, "price": {"value": "0.30", "currency": "USD"}},
        {"quantity": 15, "price": {"value": "0.32", "currency": "USD"}},
        {"quantity": 5},  # malformed -> ignored
    ]}
    fills, avg = mod.parse_fills(resp)
    assert fills == 25
    assert abs(avg - (10 * 30 + 15 * 32) / 25) < 1e-9
    assert mod.parse_fills({"id": "y"}) == (0.0, None)


def test_pm_taker_fee():
    assert abs(mod.pm_taker_fee_cents(50, 100) - 150.0) < 1e-9  # $1.50 per 100 @ 50c


def test_order_bound_adds_slippage_allowance_capped():
    assert mod.order_bound_cents(30) == 32
    assert mod.order_bound_cents(95) == 97   # ENTRY_MAX + 2
    assert mod.order_bound_cents(96) == 97   # never at/above par
