"""Verify the IBKR Client Portal Gateway and map a ForecastEx product's ladder.

Read-only: this never places an order. Run it after starting and logging into
the gateway, before wiring anything to live_trade.

The discovery response shapes for DAILY weather contracts are not documented
(IBKR's published examples are all monthly/quarterly products), so this dumps
enough raw structure to confirm how expiries are exposed before we depend on it.

  uv run python scripts/check_ibkr.py                    # LAX, today
  uv run python scripts/check_ibkr.py --product UHMIA --date 2026-08-21
"""
import argparse
import json
from datetime import date, datetime

from weather_markets.ibkr import IBKRClient, IBKRError
from weather_markets.forecastex import PRODUCT_TO_STATION


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", default="UHLAX", choices=sorted(PRODUCT_TO_STATION))
    ap.add_argument("--date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=date.today())
    ap.add_argument("--strike", type=float, help="resolve just this strike")
    a = ap.parse_args()

    c = IBKRClient()
    print(f"gateway: {c.base_url}")

    try:
        st = c.auth_status()
    except IBKRError as e:
        print(f"\nFAIL: {e}\n\nStart the gateway, then log in at "
              f"https://localhost:5000 before re-running.")
        return 1
    print(f"authenticated={st.get('authenticated')} connected={st.get('connected')} "
          f"competing={st.get('competing')}")
    if not st.get("authenticated"):
        print("\nSession is not authenticated — log in at https://localhost:5000")
        return 1
    print(f"account: {c.account_id or 'IBKR_ACCOUNT_ID NOT SET'}")

    print(f"\n--- {a.product} ({PRODUCT_TO_STATION[a.product]}) ---")
    idx = c.underlier(a.product)
    print(f"underlier conid={idx['conid']}  {idx.get('companyHeader')}")
    expiries = [e for e in (idx.get("opt") or "").split(";") if e]
    print(f"expiries: {len(expiries)} listed, first 6 {expiries[:6]}")

    target = f"{a.date:%Y%m%d}"
    print(f"{target} {'IS' if target in expiries else 'is NOT'} in the expiry list")

    month = f"{a.date:%b%y}".upper()
    strikes = c.strikes(idx["conid"], month)
    print(f"\nstrikes for {month}: {len(strikes)} -> {strikes[:12]}"
          f"{' ...' if len(strikes) > 12 else ''}")
    if not strikes:
        print("no strikes returned — check the month format and that the product trades")
        return 1

    probe = a.strike if a.strike is not None else strikes[len(strikes) // 2]
    recs = c.contracts_at_strike(idx["conid"], month, probe)
    print(f"\nrecords at strike {probe:g}: {len(recs)}")
    for r in recs[:4]:
        print("   " + json.dumps({k: r.get(k) for k in
              ("conid", "right", "strike", "maturityDate", "expiry",
               "lastTradingDay", "desc2", "exchange")}))
    if len(recs) > 4:
        print(f"   ... {len(recs) - 4} more")

    # The whole point: does one (product, date, strike) resolve to a YES/NO pair?
    try:
        pair = c.resolve(a.product, a.date, probe)
        print(f"\nresolved {a.product} {a.date} strike {probe:g}: {pair}")
        snap = c.snapshot(list(pair.values()))
        print("snapshot (call twice if sparse — IBKR primes on first request):")
        for row in snap:
            print("   " + json.dumps({k: row.get(k) for k in
                  ("conid", "31", "84", "86", "85", "88")}))
    except IBKRError as e:
        print(f"\nresolve failed: {e}")
        print("The records above show which field actually carries the daily "
              "expiry — adjust IBKRClient.resolve to match.")
        return 1

    print("\nOK — discovery and market data work. Orders are still gated behind "
          "confirm=True and nothing has been placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
