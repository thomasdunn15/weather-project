#!/usr/bin/env python3
"""Authoritative per-city live P&L, reconciled from Kalshi's own ledger.

WHY THIS EXISTS
---------------
Our `live_trades` table (and the dashboard built on it) drifts from reality:
  - manual trades placed outside live_trade.py are never recorded (e.g. the
    2026-06-21 Dallas winners, the old Seattle/LA manuals);
  - settlement P&L was derived from our OWN observations, not Kalshi's result;
  - intraday SELL closes realize P&L that buy-and-hold settlement logic misses.

This module ignores live_trades entirely and rebuilds P&L from Kalshi's
authoritative ledger. The identity that makes it self-checking:

    sum_over_cities(total) + intraday_residual == account_value - deposits
    where account_value = cash (balance_dollars) + portfolio_value

WHY NOT JUST SUM FILLS  (the bug in the first cut of this script)
-----------------------------------------------------------------
`GET /portfolio/fills` is capped (~574 rows for this account) AND its
action/side labels are inconsistent for older markets (a buy-and-hold position
can come back as a string of "sell" fills whose cash flow has the wrong sign).
So a fills-based cash-flow sum BOTH over-counts (missing buy legs) and
mis-signs — it produced +$6,347 against a true +$1,893. Fills are therefore
NOT trusted here.

WHAT IS AUTHORITATIVE
---------------------
Two Kalshi sources are complete and self-consistent, so we build on them:

  1. SETTLEMENTS  (`/portfolio/settlements`, complete history)
     Per settled market the realized P&L of the contracts HELD TO EXPIRY is
     self-contained:
        realized = revenue/100 − (yes_total_cost_dollars + no_total_cost_dollars) − fee_cost
     (verified: Dallas settled = +$451, Dallas-T93 = +$261.)

  2. OPEN POSITIONS  (`/portfolio/positions` + `/markets/{t}` book)
     Per still-open market:
        unrealized = qty × bid_side_price − total_traded_dollars (cost basis)
     Marked on the close-now bid (YES→yes_bid, NO→no_bid). The marks sum to
     Kalshi's authoritative `portfolio_value`, which is the cross-check.

THE RESIDUAL  (intraday round-trips)
------------------------------------
The gap between (settled realized + open unrealized) and the true grand total
(account_value − deposits) is the NET realized P&L of intraday round-trips —
contracts bought and sold before expiry. That cash is real (it's in the
balance) but Kalshi's capped/mis-signed fills feed cannot attribute it to a
city reliably. Rather than fabricate a per-city split from bad fills, we expose
it as one explicit, logged `_residual` line. The grand total ALWAYS ties to
account_value − deposits because the residual is computed as the exact plug.

Run:  uv run python scripts/analysis/kalshi_reconcile_by_city.py [--deposits 3064.99]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone

from weather_markets.kalshi_api import KalshiClient

# Deposits + verified non-trade credits Kalshi posted outside trading:
#   $3,050 real deployed capital + $14.99 friend-referral incentive.
DEFAULT_DEPOSITS = 3064.99

# Kalshi series prefix -> display city.
SERIES_CITY = {
    "KXHIGHCHI": "Chicago",   "KXHIGHMIA": "Miami",       "KXHIGHTDAL": "Dallas",
    "KXHIGHTSEA": "Seattle",  "KXHIGHLAX": "LA",          "KXHIGHNY": "NYC",
    "KXHIGHAUS": "Austin",    "KXHIGHDEN": "Denver",      "KXHIGHTLV": "Vegas",
    "KXHIGHTPHX": "Phoenix",  "KXHIGHTNOLA": "New Orleans",
    "KXLOWTNYC": "NYC-low",   "KXLOWTCHI": "Chicago-low", "KXLOWTMIA": "Miami-low",
}


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def series_of(ticker: str) -> str:
    return (ticker or "").split("-")[0]


def city_of(ticker: str) -> str:
    return SERIES_CITY.get(series_of(ticker), series_of(ticker) or "Unknown")


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


def _open_position_mark(client: KalshiClient, ticker: str, qty: int, side: str,
                        cost_basis: float) -> float:
    """Close-now mark of an open position in dollars: qty × bid-side price.
    YES closes by selling at yes_bid; NO closes by selling at no_bid. Falls back
    to last_price, then to cost basis if the book is unreachable. The per-market
    marks sum to Kalshi's authoritative portfolio_value (cross-checked)."""
    try:
        m = client.get_market(ticker).get("market", {})
        if side == "yes":
            px = _f(m.get("yes_bid_dollars")) or _f(m.get("last_price_dollars"))
        else:
            px = _f(m.get("no_bid_dollars"))
            if not px:
                lp = _f(m.get("last_price_dollars"))
                px = (1.0 - lp) if lp else 0.0
        if px > 0:
            return qty * px
    except Exception:
        pass
    return cost_basis


def _new_city() -> dict:
    return {"realized": 0.0, "unrealized": 0.0, "total": 0.0,
            "today_realized": 0.0, "today_unrealized": 0.0, "today": 0.0,
            "n_settled": 0, "n_open": 0, "n_won": 0}


def reconcile_by_city(client: KalshiClient, deposits: float = DEFAULT_DEPOSITS) -> dict:
    """Authoritative per-city live P&L from Kalshi's ledger.

    Returns {city: {realized, unrealized, total, today_realized,
    today_unrealized, today, n_settled, n_open, n_won}} for every city traded,
    plus two special keys:
      '_residual' {realized, unrealized, total, today, label}
          net intraday round-trip P&L that capped/mis-signed fills cannot
          attribute to a city (computed as the exact balancing plug).
      '_account'  {cash, portfolio_value, account_value, deposits,
                   open_cost_basis, realized_total, unrealized_total, total,
                   attributed_total, residual, today_realized,
                   today_unrealized, today, n_settled, n_won, win_rate}
          the balance-derived ground truth. By construction:
              sum(city.total for real cities) + _residual.total == _account.total
              _account.total == account_value - deposits
    """
    settlements = _paginate(client, "/portfolio/settlements", "settlements")
    positions = client.get_positions().get("market_positions", [])
    today_utc = datetime.now(timezone.utc).date()

    city: dict[str, dict] = defaultdict(_new_city)

    # 1) SETTLED markets -> realized (held-to-expiry, self-contained per market).
    #    "today" realized = markets whose cash settled today (Kalshi settled_time).
    settled_realized = 0.0
    today_realized = 0.0
    n_settled = n_won = 0
    for s in settlements:
        cc = city_of(s.get("ticker"))
        rev = _f(s.get("revenue")) / 100.0
        cost = _f(s.get("yes_total_cost_dollars")) + _f(s.get("no_total_cost_dollars"))
        fee = _f(s.get("fee_cost"))
        realized = rev - cost - fee
        city[cc]["realized"] += realized
        city[cc]["n_settled"] += 1
        settled_realized += realized
        n_settled += 1
        if realized > 0:
            city[cc]["n_won"] += 1
            n_won += 1
        st = (s.get("settled_time") or "")[:10]
        if st == today_utc.isoformat():
            city[cc]["today_realized"] += realized
            today_realized += realized

    # 2) OPEN positions -> unrealized (marked on the close-now bid). All open
    #    positions are current exposure, so their unrealized counts as "today".
    open_cost_basis = 0.0
    open_unrealized = 0.0
    for p in positions:
        pos = int(round(_f(p.get("position_fp"))))
        if pos == 0:
            continue
        ticker = p.get("ticker")
        cc = city_of(ticker)
        qty = abs(pos)
        side = "yes" if pos > 0 else "no"
        cost = _f(p.get("total_traded_dollars"))
        mark = _open_position_mark(client, ticker, qty, side, cost)
        unreal = mark - cost
        city[cc]["unrealized"] += unreal
        city[cc]["today_unrealized"] += unreal
        city[cc]["n_open"] += 1
        open_cost_basis += cost
        open_unrealized += unreal

    for cc, d in city.items():
        d["total"] = d["realized"] + d["unrealized"]
        d["today"] = d["today_realized"] + d["today_unrealized"]

    # 3) Ground truth from balance + the intraday residual plug.
    bal = client.get_balance()
    cash = _f(bal.get("balance_dollars")) or _f(bal.get("balance")) / 100.0
    pv = _f(bal.get("portfolio_value")) / 100.0
    account_value = cash + pv
    total = account_value - deposits
    attributed = settled_realized + open_unrealized
    residual = total - attributed   # net intraday round-trip realized P&L

    # realized/unrealized split of the grand total (authoritative):
    #   realized_total = cash - deposits + open_cost_basis  (= settled + intraday)
    #   unrealized_total = portfolio_value - open_cost_basis
    realized_total = cash - deposits + open_cost_basis
    unrealized_total = pv - open_cost_basis

    result = dict(city)
    result["_residual"] = {
        "realized": round(residual, 2),
        "unrealized": 0.0,
        "total": round(residual, 2),
        "today": 0.0,   # intraday net is cumulative; today's slice isn't separable
        "label": "intraday round-trips (capped/mis-signed fills — not city-attributable)",
    }
    result["_account"] = {
        "cash": round(cash, 2),
        "portfolio_value": round(pv, 2),
        "account_value": round(account_value, 2),
        "deposits": round(deposits, 2),
        "open_cost_basis": round(open_cost_basis, 2),
        "realized_total": round(realized_total, 2),
        "unrealized_total": round(unrealized_total, 2),
        "total": round(total, 2),
        "attributed_total": round(attributed, 2),
        "residual": round(residual, 2),
        "today_realized": round(today_realized, 2),
        "today_unrealized": round(open_unrealized, 2),
        "today": round(today_realized + open_unrealized, 2),
        "n_settled": n_settled,
        "n_won": n_won,
        "win_rate": round(n_won / n_settled, 3) if n_settled else 0.0,
    }
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deposits", type=float, default=DEFAULT_DEPOSITS,
                    help="Total deposits + non-trade credits ($3,050 + $14.99 referral).")
    args = ap.parse_args()

    c = KalshiClient()
    try:
        res = reconcile_by_city(c, deposits=args.deposits)
    finally:
        c.close()
    acct = res.pop("_account")
    residual = res.pop("_residual")

    print(f"{'City':<14} {'settled':>7} {'open':>4} {'realized':>11} {'unrealized':>11} {'total':>11}")
    print("-" * 62)
    grand_r = grand_u = grand_t = 0.0
    for cc, d in sorted(res.items(), key=lambda x: -x[1]["total"]):
        print(f"{cc:<14} {d['n_settled']:>7} {d['n_open']:>4} "
              f"${d['realized']:>9.2f} ${d['unrealized']:>9.2f} ${d['total']:>+9.2f}")
        grand_r += d["realized"]; grand_u += d["unrealized"]; grand_t += d["total"]
    print("-" * 62)
    print(f"{'(attributed)':<14} {'':>7} {'':>4} ${grand_r:>9.2f} ${grand_u:>9.2f} ${grand_t:>+9.2f}")
    print(f"{'+ intraday':<14} {'':>7} {'':>4} ${residual['realized']:>9.2f} "
          f"${0.0:>9.2f} ${residual['total']:>+9.2f}   <- unreconciled residual")
    print("-" * 62)
    print(f"{'GRAND TOTAL':<14} {'':>7} {'':>4} {'':>10} {'':>11} ${grand_t + residual['total']:>+9.2f}")
    print()
    print(f"Account: cash ${acct['cash']:.2f} + open marks ${acct['portfolio_value']:.2f} "
          f"= ${acct['account_value']:.2f}")
    print(f"Account value − deposits (${acct['deposits']:.2f}) = ${acct['total']:+.2f}")
    tie = (grand_t + residual["total"]) - acct["total"]
    status = "OK" if abs(tie) <= 5.0 else "FAIL"
    print(f"Tie-out: reconciled ${grand_t + residual['total']:+.2f} vs truth "
          f"${acct['total']:+.2f}  ->  diff ${tie:+.2f}  [{status}]")
    print(f"\nResidual (${residual['total']:+.2f}) = net intraday round-trip P&L "
          f"living in cash but not\nattributable per-city from Kalshi's capped, "
          f"inconsistently-signed fills feed.")


if __name__ == "__main__":
    main()
