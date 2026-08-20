"""Pure-function tests for the perp funding snapshotter (no network, no DB)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "snapshot_perp_funding",
    Path(__file__).resolve().parents[1] / "scripts" / "snapshot_perp_funding.py",
)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def test_kalshi_rows_maps_and_filters():
    payload = {"funding_rates": [
        {"market_ticker": "KXBTCPERP", "funding_time": "2026-08-05T12:00:00Z",
         "funding_rate": 0.0001, "mark_price": "6.4028"},
        {"market_ticker": "KXNEWCOINPERP", "funding_time": "2026-08-05T12:00:00Z",
         "funding_rate": 0.0, "mark_price": "1.0"},  # untracked -> dropped
    ]}
    rows = mod.kalshi_rows(payload)
    assert rows == [("kalshi", "BTC", "2026-08-05T12:00:00Z", 0.0001, 6.4028)]


def test_coinbase_rows_maps_shib_and_skips_missing_funding():
    payload = {"products": [
        {"product_id": "1000SHIB-PERP-INTX", "price": "4.9",
         "future_product_details": {"perpetual_details": {
             "funding_rate": "-0.000003", "funding_time": "2026-08-05T16:00:00Z"}}},
        {"product_id": "BTC-PERP-INTX", "price": "64372.2",
         "future_product_details": {"perpetual_details": {}}},  # no rate -> dropped
        {"product_id": "PUMP-PERP-INTX", "price": "1.0",
         "future_product_details": {"perpetual_details": {
             "funding_rate": "0.1", "funding_time": "2026-08-05T16:00:00Z"}}},  # untracked
    ]}
    rows = mod.coinbase_rows(payload)
    assert rows == [("coinbase", "kSHIB", "2026-08-05T16:00:00Z", -0.000003, 4.9)]
