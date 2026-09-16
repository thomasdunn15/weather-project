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


def test_cde_rows_reads_top_level_funding_and_keeps_zero():
    """CDE (US-legal) carries funding at the TOP level; perpetual_details is empty.

    Regression guard for the bug where the collector read only the nested field and
    silently recorded nothing for the tradeable US leg. The "0" case is the important
    one: CDE BTC often prints 0, and a falsy 0.0 must not be dropped.
    """
    payload = {"products": [
        {"product_id": "BIP-20DEC30-CDE", "price": "76125",
         "future_product_details": {
             "contract_root_unit": "BTC", "funding_rate": "0",
             "funding_time": "2026-09-16T18:00:00Z", "funding_interval": "3600s",
             "perpetual_details": {"funding_rate": ""}}},          # nested is EMPTY
        {"product_id": "SHP-20DEC30-CDE", "price": "0.00001",
         "future_product_details": {
             "contract_root_unit": "SHIB", "funding_rate": "0.000013",
             "funding_time": "2026-09-16T18:00:00Z"}},             # SHIB -> kSHIB
        {"product_id": "BIT-26SEP26-CDE", "price": "76000",
         "future_product_details": {
             "contract_root_unit": "BTC", "funding_rate": "",
             "funding_time": ""}},                                 # dated future: no funding
        {"product_id": "AVE-20DEC30-CDE", "price": "300",
         "future_product_details": {
             "contract_root_unit": "AAVE", "funding_rate": "0.000022",
             "funding_time": "2026-09-16T18:00:00Z"}},             # untracked asset
    ]}
    rows = mod.cde_rows(payload)
    assert rows == [
        ("coinbase_cde", "BTC", "2026-09-16T18:00:00Z", 0.0, 76125.0),
        ("coinbase_cde", "kSHIB", "2026-09-16T18:00:00Z", 0.000013, 0.00001),
    ]


def test_cde_rows_never_uses_the_empty_nested_field():
    """A product with ONLY the nested field populated must not be read as CDE funding."""
    payload = {"products": [
        {"product_id": "BIP-20DEC30-CDE", "price": "1",
         "future_product_details": {
             "contract_root_unit": "BTC",
             "perpetual_details": {"funding_rate": "0.5", "funding_time": "2026-09-16T18:00:00Z"}}},
    ]}
    assert mod.cde_rows(payload) == []
