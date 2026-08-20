"""Catalog adapters: normalize venue market catalogs into expansion_* tables.

Kalshi uses the existing public-data client (weather_markets.kalshi — the same
module the live discovery/snapshot crons use). ForecastEx is a stub until its
three open questions close (see VENUES['forecastex'].open_questions).
Official APIs + legal data only.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from psycopg.types.json import Jsonb

from weather_markets.kalshi import dollars_to_cents, fetch_markets, fetch_series_list


# ----- venue facts ------------------------------------------------------------
# Static, cited facts used by the scorecard and emitted as evidence chunks.
# Sources: docs/research/md/2026-06-20-polymarket-ibkr-venue-expansion.md and
# 2026-06-30-forecastex-resolution-day-trading.md.

@dataclass(frozen=True)
class VenueFacts:
    key: str
    name: str
    taker_rate: float                 # fee = rate * p * (1-p), per contract
    maker_rate: float
    api: str
    regulatory: str
    resolution: str
    capital_cycle: str
    status: str
    open_questions: tuple[str, ...] = field(default_factory=tuple)


VENUES: dict[str, VenueFacts] = {
    "kalshi": VenueFacts(
        key="kalshi",
        name="Kalshi",
        taker_rate=0.07,
        maker_rate=0.0175,  # ¼ taker — parity with live_trade/sim_python fee model
        api="Full REST v2 + WebSocket, authenticated, already in production here.",
        regulatory="CFTC-regulated DCM; US persons OK; live keys on this box.",
        resolution="NWS CLI report authoritative for temperature; settles T+1.",
        capital_cycle="T+1: capital locked until day-after settlement.",
        status="incumbent venue (live trading)",
    ),
    "forecastex": VenueFacts(
        key="forecastex",
        name="ForecastEx (IBKR)",
        taker_rate=0.035,   # ≈ ½ Kalshi per 2026-06-20 venue survey
        maker_rate=0.00875,
        api="Real API via IBKR; adapter not built yet (stub).",
        regulatory="CFTC-regulated DCM via IBKR; US persons OK pending account-access check.",
        resolution="DH contracts trade THROUGH resolution day (last trade 11:59pm local); "
                   "cash settles T+1. 5/6 station match; Chicago = KMDW, not KORD.",
        capital_cycle="Same-day trading through resolution; only cash settles T+1.",
        status="best-on-paper candidate venue — stub adapter only",
        open_questions=(
            "morning depth unknown (needs a snapshotter before sizing)",
            "primary-source rulebook PDF 404'd — eyeball it before relying on settlement terms",
            "Germany/US-only account access unresolved — do not circumvent",
        ),
    ),
    "polymarket_us": VenueFacts(
        key="polymarket_us",
        name="Polymarket US",
        taker_rate=0.0,
        maker_rate=0.0,
        api="Read-only depth snapshotter running (polymarket_orderbook_snapshots).",
        regulatory="GEOBLOCKED for US persons under CFTC rules — NOT to be circumvented.",
        resolution="Chicago weather settles on KMDW.",
        capital_cycle="n/a",
        status="rejected for trading; data-only",
    ),
}


def fee_cents(price_cents: int, venue: str = "kalshi", maker: bool = False) -> int:
    """Per-contract fee estimate in cents. Same formula as live_trade/sim_python
    kalshi_fee_cents (parity-tested there); venue rate table generalizes it."""
    if price_cents <= 0 or price_cents >= 100:
        return 0
    v = VENUES[venue]
    rate = v.maker_rate if maker else v.taker_rate
    if rate == 0:
        return 0
    p = price_cents / 100.0
    return max(1, math.ceil(rate * p * (1.0 - p) * 100))


# ----- Kalshi catalog sync ----------------------------------------------------

def _cents(m: dict, base: str) -> int | None:
    """Tolerate both int-cents and *_dollars string encodings."""
    if m.get(f"{base}_dollars") is not None:
        return dollars_to_cents(m[f"{base}_dollars"])
    v = m.get(base)
    return int(v) if v is not None else None


def _count(m: dict, base: str) -> int | None:
    raw = m.get(f"{base}_fp", m.get(base))
    if raw is None:
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def _polite(fn, *args, **kwargs):
    """Throttled fetch with 429 backoff — Kalshi rate-limits unpaced bursts."""
    for attempt in range(5):
        time.sleep(0.5)
        try:
            return fn(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < 4:
                try:
                    wait = float(e.response.headers.get("retry-after", ""))
                except ValueError:
                    wait = float(2 ** (attempt + 1))
                time.sleep(min(wait, 30))
                continue
            raise


def _market_row(venue: str, m: dict, snapshot_at: datetime) -> tuple:
    status = m.get("status", "")
    return (
        venue,
        m["ticker"],
        m.get("event_ticker", m["ticker"]).split("-")[0],
        snapshot_at,
        "settled" if status == "finalized" else status,  # normalize Kalshi's name
        _cents(m, "yes_bid"),
        _cents(m, "yes_ask"),
        _cents(m, "last_price"),
        _count(m, "volume"),
        _count(m, "volume_24h"),
        _count(m, "open_interest"),
        m.get("open_time"),
        m.get("close_time"),
        m.get("result", ""),
    )


_INSERT_SNAPSHOT = """
    INSERT INTO expansion_market_snapshots (
        venue, market_ticker, series_ticker, snapshot_at, status,
        yes_bid, yes_ask, last_price, volume, volume_24h, open_interest,
        open_time, close_time, result
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (venue, market_ticker, snapshot_at) DO UPDATE SET
        status = EXCLUDED.status, result = EXCLUDED.result
"""


def sync_kalshi_catalog(
    conn,
    categories: list[str],
    settled_pages: int = 3,
    series_like: str | None = None,
    log=print,
) -> dict:
    """Pull series + markets for Kalshi categories into expansion_* tables.

    settled_pages caps settlement-history depth at 200*pages markets per series
    (logged, not silent). series_like optionally filters series tickers by
    substring. Sequential HTTP — safe for the no-swap box.
    """
    now = datetime.now(timezone.utc)
    n_series = n_open = n_settled = 0
    for category in categories:
        series = _polite(fetch_series_list, category)
        if series_like:
            series = [s for s in series if series_like.upper() in s.get("ticker", "").upper()]
        log(f"[sync] category={category!r}: {len(series)} series")
        with conn.cursor() as cur:
            for s in series:
                cur.execute(
                    """
                    INSERT INTO expansion_series (venue, series_ticker, category, title,
                                                  frequency, payload, first_seen, last_seen)
                    VALUES ('kalshi', %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (venue, series_ticker) DO UPDATE SET
                        category = EXCLUDED.category, title = EXCLUDED.title,
                        frequency = EXCLUDED.frequency, payload = EXCLUDED.payload,
                        last_seen = EXCLUDED.last_seen
                    """,
                    (s["ticker"], category, s.get("title"), s.get("frequency"),
                     Jsonb(s), now, now),
                )
                n_series += 1
        for s in series:
            ticker = s["ticker"]
            open_markets = _polite(fetch_markets, ticker, status="open")
            settled = _polite(fetch_markets, ticker, status="settled", max_pages=settled_pages)
            if len(settled) == settled_pages * 200:
                log(f"[sync] {ticker}: settled history CAPPED at {len(settled)} markets "
                    f"(--settled-pages to deepen)")
            rows = [_market_row("kalshi", m, now) for m in open_markets]
            rows += [
                _market_row("kalshi", m, m.get("close_time") or now) for m in settled
            ]
            with conn.cursor() as cur:
                cur.executemany(_INSERT_SNAPSHOT, rows)
            conn.commit()
            n_open += len(open_markets)
            n_settled += len(settled)
            log(f"[sync] {ticker}: {len(open_markets)} open, {len(settled)} settled")
    conn.commit()
    return {"series": n_series, "open_markets": n_open, "settled_markets": n_settled}


class ForecastExCatalog:
    """Adapter stub. Interface mirrors sync_kalshi_catalog so it drops in;
    intentionally unimplemented until the open questions close (see
    VENUES['forecastex'].open_questions). No scraping, no workarounds."""

    def sync(self, conn) -> dict:
        raise NotImplementedError(
            "ForecastEx adapter blocked on: "
            + "; ".join(VENUES["forecastex"].open_questions)
        )
