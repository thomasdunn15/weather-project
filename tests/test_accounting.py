"""Offline tests for the accounting data layer: the withdrawal reconciliation
fix + the tax-base identity. Uses a fake Kalshi client (no network, no real
account) so the suite stays deterministic."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# make scripts/analysis importable the same way data_live does
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analysis.kalshi_reconcile_by_city import reconcile_by_city
from dashboard import data_accounting


class FakeClient:
    """Minimal stand-in for KalshiClient returning canned ledger data."""
    def __init__(self, cash, pv, settlements=None, positions=None,
                 deposits=None, withdrawals=None, orders=None):
        self._cash = cash
        self._pv = pv
        self._settlements = settlements or []
        self._positions = positions or []
        self._deposits = deposits or []
        self._withdrawals = withdrawals or []
        self._orders = orders or []

    def _request(self, method, endpoint, params=None):
        if endpoint == "/portfolio/settlements":
            return {"settlements": self._settlements, "cursor": None}
        if endpoint == "/portfolio/deposits":
            return {"deposits": self._deposits, "cursor": None}
        if endpoint == "/portfolio/withdrawals":
            return {"withdrawals": self._withdrawals, "cursor": None}
        raise AssertionError(f"unexpected endpoint {endpoint}")

    def get_balance(self):
        return {"balance_dollars": f"{self._cash}", "portfolio_value": int(round(self._pv * 100))}

    def get_positions(self, ticker=None):
        return {"market_positions": self._positions}

    def get_orders(self, status=None, limit=100):
        return {"orders": self._orders}

    def close(self):
        pass


def _settlement(net, year, ticker="KXHIGHMIA-X"):
    """A settlement with a chosen realized net (revenue − cost − fee) in `year`."""
    return {"ticker": ticker, "revenue": (net + 1.0) * 100, "yes_total_cost_dollars": 1.0,
            "no_total_cost_dollars": 0.0, "fee_cost": 0.0,
            "settled_time": f"{year}-03-01T00:00:00Z"}


def test_reconcile_adds_withdrawal_term():
    # account_value 1600; deposits 1000; withdrawals 400.
    # net P&L must be 1600 - 1000 + 400 = 1000 (not 600).
    c = FakeClient(cash=1600.0, pv=0.0, settlements=[])
    r = reconcile_by_city(c, deposits=1000.0, withdrawals=400.0)
    assert r["_account"]["total"] == 1000.0
    assert r["_account"]["withdrawals"] == 400.0
    assert r["_account"]["account_value"] == 1600.0


def test_reconcile_backward_compatible_default():
    # withdrawals defaults to 0 → old identity total = account_value - deposits.
    c = FakeClient(cash=1600.0, pv=0.0, settlements=[])
    r = reconcile_by_city(c, deposits=1000.0)
    assert r["_account"]["total"] == 600.0
    assert r["_account"]["withdrawals"] == 0.0


def test_reconcile_exposes_settled_gross_and_fees():
    s = {"ticker": "KXHIGHMIA-X", "revenue": 300.0, "yes_total_cost_dollars": 1.0,
         "no_total_cost_dollars": 0.0, "fee_cost": 0.5, "settled_time": "2026-03-01T00:00:00Z"}
    c = FakeClient(cash=1000.0, pv=0.0, settlements=[s])
    r = reconcile_by_city(c, deposits=1000.0)
    acct = r["_account"]
    assert acct["settled_gross"] == 2.0        # 3.00 revenue - 1.00 cost
    assert acct["settled_fees"] == 0.5
    assert acct["settled_net"] == 1.5          # gross - fee


def test_fetch_transfers_filters_to_applied_only():
    deps = [
        {"amount_cents": 100000, "fee_cents": 0, "status": "applied", "type": "ach",
         "created_ts": 1780358465, "finalized_ts": 1780358465, "id": "a"},
        {"amount_cents": 50000, "fee_cents": 0, "status": "pending", "type": "ach",
         "created_ts": 1780358466, "finalized_ts": 0, "id": "b"},
    ]
    wds = [{"amount_cents": 140000, "fee_cents": 0, "status": "applied", "type": "ach",
            "created_ts": 1783717120, "finalized_ts": 1783717120, "id": "w"}]
    c = FakeClient(cash=0, pv=0, deposits=deps, withdrawals=wds)
    t = data_accounting.fetch_transfers(c)
    assert t["deposits_total"] == 1000.0          # pending one excluded
    assert t["withdrawals_total"] == 1400.0
    assert len(t["deposits"]) == 1


def test_open_order_margin_counts_buys_only():
    orders = [
        {"action": "buy", "outcome_side": "yes", "remaining_count_fp": "100",
         "yes_price_dollars": "0.05", "no_price_dollars": "0.95"},
        {"action": "sell", "outcome_side": "no", "remaining_count_fp": "100",
         "yes_price_dollars": "0.37", "no_price_dollars": "0.63"},  # sell → no cash locked
    ]
    c = FakeClient(cash=0, pv=0, orders=orders)
    assert data_accounting._open_order_margin(c) == 5.0   # 100 * 0.05


def test_accounting_identity_end_to_end(monkeypatch):
    yr = datetime.now(timezone.utc).year
    fake = FakeClient(
        cash=1600.0, pv=0.0,
        settlements=[_settlement(200.0, yr), _settlement(-50.0, yr)],  # settled net = 150
        deposits=[{"amount_cents": 100000, "fee_cents": 0, "status": "applied", "type": "ach",
                   "created_ts": 1780358465, "finalized_ts": 1780358465, "id": "d"}],
        withdrawals=[{"amount_cents": 40000, "fee_cents": 0, "status": "applied", "type": "ach",
                      "created_ts": 1783717120, "finalized_ts": 1783717120, "id": "w"}],
        orders=[],
    )
    monkeypatch.setattr(data_accounting, "KalshiClient", lambda: fake)
    d = data_accounting.get_accounting_data()

    # basis: deposits 1000 + referral 14.99 = 1014.99; net external = 1014.99 - 400 = 614.99
    assert d["netExternalCapital"] == round(1000.0 + data_accounting.REFERRAL_CREDIT - 400.0, 2)
    # cumulative P&L = account_value - net external = 1600 - 614.99
    assert d["cumulativePnl"] == round(1600.0 - d["netExternalCapital"], 2)
    # taxable base = settled net (150) + intraday residual
    tax = d["tax"]
    assert tax["settledNet"] == 150.0
    assert tax["realizedNetTaxable"] == round(tax["settledNet"] + tax["intradayRealized"], 2)
    # FL is explicit zero
    assert tax["stateTax"] == 0.0 and tax["stateName"] == "Florida"
