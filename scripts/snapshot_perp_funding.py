"""Collect perp funding rates for the Kalshi<->Coinbase funding-spread study.

Feeds perp_funding_snapshots (migration 009) with the two legs of the s5
cross-venue funding-spread candidate (docs/strategies/assessments/
2026-08-05-s5-perp-xvenue-funding.md):

  kalshi   — finalized 8h rates from the PUBLIC history endpoint. Re-pulled with
             a lookback each run, so gaps self-heal after cron outages.
  coinbase — hourly point-in-time snapshot of the public Advanced Trade products
             endpoint (funding_rate is the current 1h rate). Coinbase publishes
             NO history for these, so a missed hour is lost — that's fine, the
             study needs the regime, not every window.

Run hourly via cron:

  uv run python scripts/snapshot_perp_funding.py
"""
from datetime import datetime, timedelta, timezone

import httpx

from weather_markets.db import get_connection

KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2/margin/funding_rates/historical"
COINBASE_URL = (
    "https://api.coinbase.com/api/v3/brokerage/market/products"
    "?product_type=FUTURE&contract_expiry_type=PERPETUAL"
)
# Coinbase Derivatives Exchange (cde) -- the US-LEGAL leg. The INTX products above are
# Coinbase International (offshore, not tradeable by US persons). CDE's perp-style
# contracts are classified EXPIRING (expiry 2030/2089) and carry funding at the TOP
# level of future_product_details, NOT in perpetual_details (which is empty for them).
COINBASE_CDE_URL = (
    "https://api.coinbase.com/api/v3/brokerage/market/products"
    "?product_type=FUTURE&contract_expiry_type=EXPIRING"
)

# Kalshi ticker -> normalized symbol (the 13 assets live on both venues).
KALSHI_SYMBOLS = {
    "KXBTCPERP": "BTC", "KXETHPERP": "ETH", "KXSOLPERP": "SOL", "KXXRPPERP": "XRP",
    "KXDOGEPERP": "DOGE", "KXLTCPERP": "LTC", "KXBCHPERP": "BCH", "KXLINKPERP": "LINK",
    "KXNEARPERP": "NEAR", "KXSUIPERP": "SUI", "KXZECPERP": "ZEC", "KXHYPEPERP": "HYPE",
    "KXKSHIBPERP": "kSHIB",
}
# Coinbase product id -> normalized symbol. GOLD included for the coming
# Kalshi metals perps (CFTC filing mid-July 2026).
COINBASE_SYMBOLS = {f"{s}-PERP-INTX": s for s in KALSHI_SYMBOLS.values() if s != "kSHIB"}
COINBASE_SYMBOLS["1000SHIB-PERP-INTX"] = "kSHIB"
COINBASE_SYMBOLS["GOLD-PERP-INTX"] = "GOLD"
CDE_ROOT_TO_SYMBOL = {s: s for s in KALSHI_SYMBOLS.values() if s != "kSHIB"}
CDE_ROOT_TO_SYMBOL["SHIB"] = "kSHIB"

INSERT_SQL = """
INSERT INTO perp_funding_snapshots (venue, symbol, funding_time, funding_rate, mark_price)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (venue, symbol, funding_time) DO NOTHING
"""


def kalshi_rows(payload: dict) -> list[tuple]:
    """One history-page payload -> insert rows (finalized rates only)."""
    rows = []
    for r in payload.get("funding_rates", []):
        sym = KALSHI_SYMBOLS.get(r["market_ticker"])
        if sym is None:
            continue  # future listings we don't track yet
        mark = float(r["mark_price"]) if r.get("mark_price") else None
        rows.append(("kalshi", sym, r["funding_time"], float(r["funding_rate"]), mark))
    return rows


def coinbase_rows(payload: dict) -> list[tuple]:
    """Products payload -> insert rows for tracked perp products."""
    rows = []
    for p in payload.get("products", []):
        sym = COINBASE_SYMBOLS.get(p.get("product_id"))
        if sym is None:
            continue
        det = (p.get("future_product_details") or {}).get("perpetual_details") or {}
        rate, ftime = det.get("funding_rate"), det.get("funding_time")
        if not rate or not ftime:
            continue
        price = float(p["price"]) if p.get("price") else None
        rows.append(("coinbase", sym, ftime, float(rate), price))
    return rows


def cde_rows(payload: dict) -> list[tuple]:
    """US-legal CDE perp-style products -> insert rows, venue 'coinbase_cde'.

    Reads the TOP-LEVEL funding_rate. Checks the raw string, never the float: CDE BTC
    often prints "0", and a falsy 0.0 must not be dropped -- it is the reading that
    matters most when Kalshi BTC is paying double-digit carry.
    """
    rows = []
    for p in payload.get("products", []):
        fpd = p.get("future_product_details") or {}
        sym = CDE_ROOT_TO_SYMBOL.get(fpd.get("contract_root_unit"))
        rate, ftime = fpd.get("funding_rate"), fpd.get("funding_time")
        if sym is None or rate in (None, "") or not ftime:
            continue
        price = float(p["price"]) if p.get("price") else None
        rows.append(("coinbase_cde", sym, ftime, float(rate), price))
    return rows


def main() -> int:
    inserted = {"kalshi": 0, "coinbase": 0, "coinbase_cde": 0}
    with httpx.Client(timeout=30.0, headers={"User-Agent": "weather-project/1.0"}) as http:
        # Kalshi: 3-day lookback re-pull (9 windows/market); ON CONFLICT dedupes.
        min_ts = int((datetime.now(timezone.utc) - timedelta(days=3)).timestamp())
        rows, cursor = [], None
        while True:
            params = {"limit": 1000, "min_ts": min_ts}
            if cursor:
                params["cursor"] = cursor
            payload = http.get(KALSHI_URL, params=params).raise_for_status().json()
            rows.extend(kalshi_rows(payload))
            cursor = payload.get("cursor")
            if not cursor or not payload.get("funding_rates"):
                break
        cb_rows = coinbase_rows(http.get(COINBASE_URL).raise_for_status().json())
        cde_rows_ = cde_rows(http.get(COINBASE_CDE_URL).raise_for_status().json())

    with get_connection() as conn, conn.cursor() as cur:
        for venue, batch in (("kalshi", rows), ("coinbase", cb_rows),
                             ("coinbase_cde", cde_rows_)):
            for row in batch:
                cur.execute(INSERT_SQL, row)
                inserted[venue] += cur.rowcount
        conn.commit()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{now} perp funding: kalshi +{inserted['kalshi']} (of {len(rows)} pulled), "
          f"coinbase(INTX) +{inserted['coinbase']} (of {len(cb_rows)}), "
          f"coinbase_cde +{inserted['coinbase_cde']} (of {len(cde_rows_)} "
          f"of {len(CDE_ROOT_TO_SYMBOL)} tracked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
