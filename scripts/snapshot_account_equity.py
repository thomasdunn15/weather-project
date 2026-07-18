# scripts/snapshot_account_equity.py
"""Daily account-equity snapshot -> account_equity_snapshots (one row per UTC day).

Records TRUE equity (cash + open-position mark-to-market) and the reconciliation
P&L so the live-tab cumulative-P&L graph can overlay realized-plus-open equity
going forward.

Balance-based, from live Kalshi: get_balance() + applied deposits/withdrawals via
dashboard.data_accounting.fetch_transfers (the same live withdrawals source the
Accounting tab uses). This is a SEPARATE series from
dashboard.data_live._daily_realized_series (settlements-only realized): the two
are distinct measurements and must be rendered as two lines, NEVER summed. This
script reads no settlements, so there is no double-count in collection.

Idempotent: re-running the same day upserts (latest equity wins). Read-only
against Kalshi; the only write is this one DB row.

Run:  uv run python scripts/snapshot_account_equity.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# repo root on path so `dashboard` imports when launched as `python scripts/...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weather_markets.db import get_connection            # noqa: E402
from weather_markets.kalshi_api import KalshiClient       # noqa: E402
from dashboard.data_accounting import fetch_transfers, REFERRAL_CREDIT  # noqa: E402


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def build_snapshot_row(client: KalshiClient, day: str) -> dict:
    """Pure compute (no DB): live balance + applied transfers -> one snapshot row.

    computed_pnl = account_value - deposits - referral + withdrawals
    (capital-in is not P&L; withdrawals are money out, added back).
    """
    tr = fetch_transfers(client)
    deposits = round(tr["deposits_total"], 2)
    withdrawals = round(tr["withdrawals_total"], 2)

    bal = client.get_balance()
    cash = _f(bal.get("balance_dollars")) or _f(bal.get("balance")) / 100.0
    pv = _f(bal.get("portfolio_value")) / 100.0
    account_value = round(cash + pv, 2)

    computed_pnl = round(account_value - deposits - REFERRAL_CREDIT + withdrawals, 2)
    return {
        "snapshot_date": day,
        "cash_dollars": round(cash, 2),
        "portfolio_value_dollars": round(pv, 2),
        "account_value_dollars": account_value,
        "deposits_dollars": deposits,
        "referral_credit_dollars": round(REFERRAL_CREDIT, 2),
        "withdrawals_dollars": withdrawals,
        "computed_pnl_dollars": computed_pnl,
    }


def upsert_row(conn, row: dict) -> None:
    """Idempotent daily upsert. created_at keeps its original insert time."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO account_equity_snapshots (
                snapshot_date, cash_dollars, portfolio_value_dollars,
                account_value_dollars, deposits_dollars, referral_credit_dollars,
                withdrawals_dollars, computed_pnl_dollars
            ) VALUES (
                %(snapshot_date)s, %(cash_dollars)s, %(portfolio_value_dollars)s,
                %(account_value_dollars)s, %(deposits_dollars)s, %(referral_credit_dollars)s,
                %(withdrawals_dollars)s, %(computed_pnl_dollars)s
            )
            ON CONFLICT (snapshot_date) DO UPDATE SET
                cash_dollars            = EXCLUDED.cash_dollars,
                portfolio_value_dollars = EXCLUDED.portfolio_value_dollars,
                account_value_dollars   = EXCLUDED.account_value_dollars,
                deposits_dollars        = EXCLUDED.deposits_dollars,
                referral_credit_dollars = EXCLUDED.referral_credit_dollars,
                withdrawals_dollars     = EXCLUDED.withdrawals_dollars,
                computed_pnl_dollars    = EXCLUDED.computed_pnl_dollars
            """,
            row,
        )
    conn.commit()


def main() -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = KalshiClient()
    try:
        row = build_snapshot_row(client, day)
    finally:
        client.close()
    with get_connection() as conn:
        upsert_row(conn, row)
    print(
        f"account_equity_snapshots upsert {day}: "
        f"acct=${row['account_value_dollars']:.2f} pnl=${row['computed_pnl_dollars']:+.2f} "
        f"(cash=${row['cash_dollars']:.2f} pv=${row['portfolio_value_dollars']:.2f} "
        f"dep=${row['deposits_dollars']:.2f} cred=${row['referral_credit_dollars']:.2f} "
        f"wd=${row['withdrawals_dollars']:.2f})",
        flush=True,
    )


if __name__ == "__main__":
    main()
