"""Accounting tab data — tax reserve, withdrawals, and safe-to-withdraw, built
from LIVE Kalshi sources. Nothing is hardcoded except one audited, non-API
referral credit; every other dollar traces to a live endpoint.

Sources (all read-only):
  GET /portfolio/deposits      → capital in (ACH/debit)
  GET /portfolio/withdrawals   → capital out  ← the term the old reconciliation omitted
  GET /portfolio/balance       → cash + portfolio_value
  GET /portfolio/positions     → open cost basis
  GET /portfolio/settlements   → realized P&L (per tax year), gross + fees
  GET /portfolio/orders        → resting-BUY collateral (cash committed)

The federal tax RATE is NOT applied here: the payload ships the taxable base and
the UI computes reserve + safe-to-withdraw client-side from a user-adjustable
rate, so moving the slider never triggers a refetch. Florida has no state income
tax. Prediction-market federal treatment is unsettled — this is an estimate, not
advice (the UI carries the disclaimer).
"""
from __future__ import annotations

from datetime import datetime, timezone

from weather_markets.kalshi_api import KalshiClient

# One-time friend-referral promo credit Kalshi posted outside trading (verified in
# the 2026-06-21 account audit). It is NOT an ACH/debit deposit, and Kalshi exposes
# no promo/credit endpoint, so it is a documented constant — the ONLY non-live
# figure in this module. Mirrors dashboard.data_live.KALSHI_NON_TRADE_CREDITS.
REFERRAL_CREDIT = 14.99


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _paginate(client: KalshiClient, endpoint: str, key: str, max_pages: int = 80) -> list[dict]:
    out: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = client._request("GET", endpoint, params=params)
        rows = r.get(key, [])
        out += rows
        cursor = r.get("cursor")
        if not cursor or not rows:
            break
    return out


def fetch_transfers(client: KalshiClient) -> dict:
    """Live deposits + withdrawals (status 'applied' only), amounts in dollars,
    newest first. Reused by data_live to correct the reconciliation basis so the
    live hero stops understating P&L by the withdrawn amount."""
    def rows(endpoint: str, key: str) -> list[dict]:
        out = []
        for r in _paginate(client, endpoint, key):
            if r.get("status") != "applied":
                continue
            ts = int(r.get("finalized_ts") or r.get("created_ts") or 0)
            out.append({
                "amount": round(_f(r.get("amount_cents")) / 100.0, 2),
                "fee": round(_f(r.get("fee_cents")) / 100.0, 2),
                "type": r.get("type", ""),
                "ts": ts,
                "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else "",
                "id": r.get("id", ""),
            })
        out.sort(key=lambda x: x["ts"], reverse=True)
        return out

    deposits = rows("/portfolio/deposits", "deposits")
    withdrawals = rows("/portfolio/withdrawals", "withdrawals")
    return {
        "deposits": deposits,
        "withdrawals": withdrawals,
        "deposits_total": round(sum(d["amount"] for d in deposits), 2),
        "withdrawals_total": round(sum(w["amount"] for w in withdrawals), 2),
    }


def _open_order_margin(client: KalshiClient) -> float:
    """Cash committed to resting BUY orders = remaining_count × limit price.
    Sell orders reserve a held position, not cash, so they are excluded. Kalshi's
    `balance` includes this committed cash (the reconciliation ties out with it),
    so it must be subtracted to get truly-free withdrawable cash."""
    orders = client.get_orders(status="resting", limit=200).get("orders", [])
    margin = 0.0
    for o in orders:
        if (o.get("action") or "").lower() != "buy":
            continue
        rem = _f(o.get("remaining_count_fp")) or _f(o.get("remaining_count"))
        outcome = (o.get("outcome_side") or o.get("side") or "").lower()
        px = _f(o.get("yes_price_dollars")) if outcome == "yes" else _f(o.get("no_price_dollars"))
        if not px:
            px = _f(o.get("yes_price_dollars")) or _f(o.get("no_price_dollars"))
        margin += rem * px
    return round(margin, 2)


def get_accounting_data() -> dict:
    """Build the /api/accounting payload from live Kalshi. Raises on API failure
    (the UI shows a load error, like the backtest tab)."""
    tax_year = datetime.now(timezone.utc).year
    client = KalshiClient()
    try:
        transfers = fetch_transfers(client)
        dep_total = transfers["deposits_total"]
        wd_total = transfers["withdrawals_total"]

        bal = client.get_balance()
        cash = _f(bal.get("balance_dollars")) or _f(bal.get("balance")) / 100.0
        pv = _f(bal.get("portfolio_value")) / 100.0
        account_value = round(cash + pv, 2)

        # Open cost basis from positions; unrealized = Kalshi's authoritative
        # portfolio_value (its mark of all open positions) minus that basis.
        positions = client.get_positions().get("market_positions", [])
        open_cost = 0.0
        for p in positions:
            if int(round(_f(p.get("position_fp")))) != 0:
                open_cost += _f(p.get("total_traded_dollars"))
        open_cost = round(open_cost, 2)
        open_unreal = round(pv - open_cost, 2)

        # Settlements → realized P&L, split by tax year, gross vs fees.
        setts = _paginate(client, "/portfolio/settlements", "settlements")
        alltime_net = 0.0
        ytd_gross = ytd_fees = ytd_net = 0.0
        n_ytd = 0
        for s in setts:
            rev = _f(s.get("revenue")) / 100.0
            cost = _f(s.get("yes_total_cost_dollars")) + _f(s.get("no_total_cost_dollars"))
            fee = _f(s.get("fee_cost"))
            alltime_net += rev - cost - fee
            if (s.get("settled_time") or "")[:4] == str(tax_year):
                ytd_gross += rev - cost
                ytd_fees += fee
                ytd_net += rev - cost - fee
                n_ytd += 1

        # Corrected reconciliation identity (same one the live hero must use):
        #   account_value = (deposits + credit) − withdrawals + net_pnl
        basis_in = round(dep_total + REFERRAL_CREDIT, 2)          # capital in (non-trading)
        net_external = round(basis_in - wd_total, 2)              # in − withdrawals
        cumulative_pnl = round(account_value - net_external, 2)   # realized + unrealized
        total_realized = round(cumulative_pnl - open_unreal, 2)

        # Intraday round-trips: realized cash NOT in the settlements feed (Kalshi's
        # fills are capped/mis-signed, so this is derived as the exact plug). Every
        # deposit + settlement on this account is in the current tax year, so this
        # realized cash is current-year too.
        intraday_realized = round(total_realized - alltime_net, 2)

        # Taxable base = ALL realized net gains for the year (settled + intraday),
        # net of fees. Open positions + withdrawals are NOT taxable events.
        realized_net_taxable = round(ytd_net + intraday_realized, 2)

        margin = _open_order_margin(client)
    finally:
        client.close()

    return {
        "asOf": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "taxYear": tax_year,
        # live balances
        "cash": round(cash, 2),
        "portfolioValue": pv,
        "accountValue": account_value,
        "openCostBasis": open_cost,
        "openUnrealized": open_unreal,
        "openOrderMargin": margin,
        # capital in / out (live) + one audited non-API credit
        "deposits": {"total": dep_total, "rows": transfers["deposits"]},
        "withdrawals": {"total": wd_total, "rows": transfers["withdrawals"]},
        "referralCredit": REFERRAL_CREDIT,
        "netExternalCapital": net_external,
        # corrected P&L (now includes the withdrawal term)
        "cumulativePnl": cumulative_pnl,
        "totalRealized": total_realized,
        # tax view — base only; the UI applies a user-adjustable federal rate
        "tax": {
            "year": tax_year,
            "settledGross": round(ytd_gross, 2),
            "settledFees": round(ytd_fees, 2),
            "settledNet": round(ytd_net, 2),
            "nSettled": n_ytd,
            "intradayRealized": intraday_realized,
            "realizedNetTaxable": realized_net_taxable,
            "stateName": "Florida",
            "stateRate": 0.0,
            "stateTax": 0.0,
            "fedRateDefault": 0.24,
            "fedRatePresets": [
                {"label": "Ordinary 24%", "rate": 0.24},
                {"label": "Ordinary 32%", "rate": 0.32},
                {"label": "Ordinary 37%", "rate": 0.37},
                {"label": "§1256 60/40 ≈ 26.8%", "rate": 0.268},
            ],
        },
    }
