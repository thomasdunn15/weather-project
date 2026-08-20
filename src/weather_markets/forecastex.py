"""ForecastEx public market-data client (NO auth, NO IBKR account needed).

ForecastEx publishes everything we need over plain public HTTP:
  - /api/download?type=prices&date=YYYYMMDD   daily OHLC + settlement + OI per contract
  - /api/download?type=pairs&date=YYYYMMDD    TICK-LEVEL trade prints w/ timestamps
                                              (refreshed ~every 10 min intraday)
  - /api/download?type=summary&date=YYYYMMDD  per-product name/category/total pairs
  - /api/products?category=...&page=N         product specs (settlement source!)
History starts 2025-01-01; the daily city-temperature products (UH*/UL*) list
from ~2026-02-01. Today's file appears only after close — poll `pairs` intraday.

CONTRACT SEMANTICS (verified 2026-08-17 against 63 settled Miami events):
  contract_id = "UHMIA_081326_94"  ->  product UHMIA, event 2026-08-13, strike 94
  Question is "will the high EXCEED {strike} F", i.e. YES iff high > strike.
  That is EXACTLY our Kalshi `greater_than` + `strike_low` convention, so these
  contracts need NO normalization via kalshi_equivalent_bracket.

*** BASIS WARNING — read before trading or backtesting ***
UHMIA settles on **Weather Underground's** KMIA daily high, NOT the NWS CLI
value our EMOS models are trained and settled against. Same station, different
source. Measured over 63 events (2026-06-14..08-15): the ForecastEx settlement
high is NEVER above our CLI high — 41% equal, 46% one degree lower, 13% two
degrees lower (mean -0.71 F). Treating our CLI observations as ForecastEx
ground truth biases every probability. Use `implied_settlement_highs()` to
recover ForecastEx's own settled value from the strike ladder instead.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Iterator

import httpx

BASE_URL = "https://www.forecastex.com"

# ForecastEx daily-high product -> our station_id. Only products whose spec
# names the same airport station we already ingest. Deliberately EXCLUDES:
#   UHLGA (LaGuardia) — our KNYC is Central Park, a different station.
#   Chicago — ForecastEx lists MDW only, never ORD.
# Every mapping here still carries the Weather-Underground basis caveat above.
PRODUCT_TO_STATION = {
    "UHMIA": "KMIA", "UHMSY": "KMSY", "UHDFW": "KDFW", "UHPHX": "KPHX",
    "UHMDW": "KMDW", "UHLAX": "KLAX", "UHSFO": "KSFO", "UHSEA": "KSEA",
    "UHAUS": "KAUS", "UHLAS": "KLAS",
}


class ForecastExClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 60.0):
        self.base_url = base_url
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def _csv(self, kind: str, day: date) -> list[dict]:
        """Download one daily CSV. Returns [] when the file isn't published yet
        (404 — normal for today before close, and for some holidays)."""
        r = self._client.get(f"{self.base_url}/api/download",
                             params={"type": kind, "date": day.strftime("%Y%m%d")})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return list(csv.DictReader(io.StringIO(r.text)))

    def prices(self, day: date) -> list[dict]:
        """Daily OHLC/settlement/OI rows (one per contract per side)."""
        return self._csv("prices", day)

    def pairs(self, day: date) -> list[dict]:
        """Tick-level trade prints: quantity, yes_price, no_price, pair_time."""
        return self._csv("pairs", day)

    def summary(self, day: date) -> list[dict]:
        return self._csv("summary", day)

    def products(self, category: str | None = None, max_pages: int = 200) -> list[dict]:
        """Product specs, paged 8 at a time (page= is the only working param).
        Includes `description`/`source_agency` — how we found the WU basis."""
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            params = {"page": page}
            if category:
                params["category"] = category
            r = self._client.get(f"{self.base_url}/api/products", params=params)
            r.raise_for_status()
            body = r.json().get("body", {}).get("data")
            rows = __import__("json").loads(body) if isinstance(body, str) else (body or [])
            if not rows:
                break
            out.extend(rows)
            if len(rows) < 8:
                break
        return out

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ForecastExClient":
        return self

    def __exit__(self, *a) -> None:
        self.close()


def parse_contract_id(contract_id: str) -> tuple[str, date, float] | None:
    """"UHMIA_081326_94" -> ("UHMIA", date(2026,8,13), 94.0). None if unparseable."""
    parts = contract_id.split("_")
    if len(parts) != 3:
        return None
    product, mmddyy, strike = parts
    try:
        event = datetime.strptime(mmddyy, "%m%d%y").date()
        return product, event, float(strike)
    except ValueError:
        return None


def weather_rows(rows: list[dict]) -> Iterator[tuple[str, str, date, float, dict]]:
    """Filter a prices/pairs CSV down to mapped daily-high contracts.

    Yields (contract_id, station_id, event_date, strike, raw_row)."""
    key = "event_contract" if rows and "event_contract" in rows[0] else "event_contract"
    for row in rows:
        cid = row.get(key) or ""
        parsed = parse_contract_id(cid)
        if not parsed:
            continue
        product, event, strike = parsed
        station = PRODUCT_TO_STATION.get(product)
        if station:
            yield cid, station, event, strike, row


def implied_settlement_highs(price_rows: list[dict], file_day: date,
                             product: str) -> dict[date, int]:
    """Recover ForecastEx's OWN settled high per event date from the strike ladder.

    Because YES pays iff high > strike, the smallest strike that settled NO is
    exactly the settled high. This is the correct ground truth for backtesting
    ForecastEx (our NWS CLI observations are a DIFFERENT number — see the module
    docstring). Only reads contracts that have expired on/before `file_day`, and
    skips any non-monotonic ladder.
    """
    ladders: dict[date, dict[float, float]] = {}
    for row in price_rows:
        if row.get("subtype") != "YES":
            continue
        cid = row.get("event_contract") or ""
        parsed = parse_contract_id(cid)
        if not parsed or parsed[0] != product:
            continue
        _, event, strike = parsed
        exp = (row.get("expiration_date") or "")[:10]
        if not exp or exp > file_day.isoformat():
            continue  # not yet expired -> settlement_price is just a last price
        try:
            settle = float(row.get("settlement_price"))
        except (TypeError, ValueError):
            continue
        if settle not in (0.0, 1.0):
            continue
        ladders.setdefault(event, {})[strike] = settle

    out: dict[date, int] = {}
    for event, ladder in ladders.items():
        yes = [k for k, v in ladder.items() if v == 1.0]
        no = [k for k, v in ladder.items() if v == 0.0]
        if not yes or not no or max(yes) >= min(no):
            continue  # incomplete or non-monotonic ladder -> unusable
        out[event] = int(min(no))
    return out
