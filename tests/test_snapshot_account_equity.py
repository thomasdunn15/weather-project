"""Offline test for the equity-snapshot compute (no DB, no network). Mirrors the
FakeClient pattern in test_accounting.py so the suite stays deterministic."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.snapshot_account_equity import build_snapshot_row  # noqa: E402
from dashboard.data_accounting import REFERRAL_CREDIT            # noqa: E402


class FakeClient:
    def __init__(self, cash, pv, deposits, withdrawals):
        self._cash, self._pv = cash, pv
        self._deposits, self._withdrawals = deposits, withdrawals

    def _request(self, method, endpoint, params=None):
        if endpoint == "/portfolio/deposits":
            return {"deposits": self._deposits, "cursor": None}
        if endpoint == "/portfolio/withdrawals":
            return {"withdrawals": self._withdrawals, "cursor": None}
        raise AssertionError(f"unexpected endpoint {endpoint}")

    def get_balance(self):
        return {"balance_dollars": f"{self._cash}", "portfolio_value": int(round(self._pv * 100))}

    def close(self):
        pass


def _applied(cents, tid="x"):
    return {"amount_cents": cents, "fee_cents": 0, "status": "applied", "type": "ach",
            "created_ts": 1780000000, "finalized_ts": 1780000000, "id": tid}


def test_identity_and_split_columns():
    # Real numbers from the 2026-07-18 verification: cash 4267.32, pv 361.29,
    # deposits 3050, withdrawals 1400 -> computed_pnl 2963.62.
    c = FakeClient(cash=4267.32, pv=361.29,
                   deposits=[_applied(305000)], withdrawals=[_applied(140000)])
    row = build_snapshot_row(c, "2026-07-18")
    assert row["cash_dollars"] == 4267.32
    assert row["portfolio_value_dollars"] == 361.29
    assert row["account_value_dollars"] == 4628.61
    assert row["deposits_dollars"] == 3050.0            # literal, credit NOT folded in
    assert row["referral_credit_dollars"] == REFERRAL_CREDIT
    assert row["withdrawals_dollars"] == 1400.0
    # computed_pnl = account_value - deposits - referral + withdrawals
    assert row["computed_pnl_dollars"] == round(4628.61 - 3050.0 - REFERRAL_CREDIT + 1400.0, 2)


def test_pending_transfers_excluded():
    c = FakeClient(cash=100.0, pv=0.0,
                   deposits=[_applied(100000),
                             {"amount_cents": 50000, "status": "pending", "type": "ach",
                              "created_ts": 1780000001, "finalized_ts": 0, "id": "p"}],
                   withdrawals=[])
    row = build_snapshot_row(c, "2026-07-18")
    assert row["deposits_dollars"] == 1000.0            # pending excluded
    assert row["withdrawals_dollars"] == 0.0
