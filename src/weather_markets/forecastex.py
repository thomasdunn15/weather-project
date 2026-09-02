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


# ---------------------------------------------------------------------------
# Signal primitives shared by the backtest sweep and the live trader.
#
# These live here, not in either caller, because a live path and a backtest that
# each keep their own copy of the blend fit drift apart silently — and the first
# symptom is live trades that do not match anything you validated.
# ---------------------------------------------------------------------------
import math as _math
import statistics as _stats
from datetime import date as _date

FEE_CENTS_PER_CONTRACT = 1.0        # ForecastEx: flat $0.01/contract/side

RH_CITY_SLUG = {"KLAX": "los-angeles", "KMIA": "miami", "KDFW": "dallas",
                "KSFO": "san-francisco", "KMDW": "chicago", "KAUS": "austin",
                "KPHX": "phoenix", "KSEA": "seattle", "KLAS": "las-vegas",
                "KMSY": "new-orleans"}

# Built by hand rather than strftime("%B"): %B is locale-dependent, and a locale
# surprise here would silently emit a 404 link instead of failing loudly.
_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")

# Robinhood's weather markets are view-only on the web and tradeable only in the
# mobile app, so this link is for checking the book, not for placing the order.
def rh_url(station: str, d) -> str | None:
    """Deep link to the Robinhood event page for one city-day.

    Slug verified 2026-08-31 across LA/Miami/Chicago/Dallas/SF. Note the two
    date halves are formatted DIFFERENTLY — the long half does not zero-pad the
    day (`september-1-2026`) while the short half does (`sep-01-2026`). The
    zero-padded long form 404s.
    """
    slug = RH_CITY_SLUG.get(station)
    if not slug:
        return None
    mon = _MONTHS[d.month - 1]
    return ("https://robinhood.com/us/en/prediction-markets/climate/events/"
            f"{slug}-daily-temperature-high-{mon}-{d.day}-{d.year}"
            f"-{mon[:3]}-{d.day:02d}-{d.year}/")



def norm_sf(x: float) -> float:
    """P(Z > x) for a standard normal."""
    return 0.5 * _math.erfc(x / _math.sqrt(2.0))


def prob_above(strike: float, mu: float, sigma: float) -> float:
    """P(high > strike). The +0.5 is the integer-rounding correction: a reported
    high of 81 means the true high fell in [80.5, 81.5)."""
    return norm_sf((strike + 0.5 - mu) / sigma)


def clip(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


def logit(p: float) -> float:
    c = clip(p)
    return _math.log(c / (1 - c))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + _math.exp(-max(-500.0, min(500.0, x))))


def rolling_offset(day: _date, settled: dict, model_mu: dict,
                   window: int = 45, min_n: int = 10) -> float | None:
    """Mean (ForecastEx settled high - our model mu) over recent settled days.

    ForecastEx settles on Weather Underground, not the NWS CLI our models are
    trained against, and that gap is constant in shape but NOT stationary — so a
    fixed offset over-corrects cities that drift. Uses only days strictly before
    `day`, since settlement is not known until the next morning.
    """
    past = [settled[d] - model_mu[d] for d in settled
            if d in model_mu and d < day and (day - d).days <= window]
    return _stats.mean(past) if len(past) >= min_n else None


def _solve3(A, b):
    """Gaussian elimination for the 3x3 Newton step."""
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            raise ZeroDivisionError("singular normal matrix")
        M[i], M[piv] = M[piv], M[i]
        for r in range(3):
            if r == i:
                continue
            f = M[r][i] / M[i][i]
            for c in range(i, 4):
                M[r][c] -= f * M[i][c]
    return [M[i][3] / M[i][i] for i in range(3)]


def fit_blend(history: list[tuple], min_obs: int = 60) -> tuple | None:
    """Benter-style logit blend: logit(y) ~ a + b*logit(p_model) + c*logit(p_market).

    `history` is [(p_model, p_market, won_yes), ...] and must contain only
    observations from BEFORE the day being scored — this function does not
    enforce that, callers do.

    Returns None below `min_obs`. A blend fit on thin history is just a noisier
    copy of the model, and letting it trade anyway is how a 'blend' strategy
    posts good backtest numbers without meaning anything.
    """
    if len(history) < min_obs:
        return None
    X = [(1.0, logit(pm), logit(pk)) for pm, pk, _ in history]
    y = [float(o) for _, _, o in history]
    beta = [0.0, 1.0, 0.0]
    for _ in range(25):
        g = [0.0] * 3
        H = [[0.0] * 3 for _ in range(3)]
        for xi, yi in zip(X, y):
            p = sigmoid(sum(b * x for b, x in zip(beta, xi)))
            w = max(p * (1 - p), 1e-9)
            for a in range(3):
                g[a] += (yi - p) * xi[a]
                for b_ in range(3):
                    H[a][b_] += w * xi[a] * xi[b_]
        for a in range(3):          # ridge: p_model and p_market are collinear
            H[a][a] += 1e-4
        try:
            step = _solve3(H, g)
        except ZeroDivisionError:
            return None
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return tuple(beta)


def blend_prob(fit: tuple, p_model: float, p_market: float) -> float:
    return sigmoid(fit[0] + fit[1] * logit(p_model) + fit[2] * logit(p_market))
