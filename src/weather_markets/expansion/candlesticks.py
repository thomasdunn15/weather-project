"""Kalshi candlestick fetch + settled-market helpers.

Shared by scripts/analysis/flb_regime.py (measures the favorite-longshot regime)
and flb_backtest.py (net-of-fee P&L of harvesting it). IO only — no strategy
logic here. Public read endpoint, no auth (same host the live client uses).
"""

from __future__ import annotations

import statistics

import httpx

CANDLE_URL = (
    "https://api.elections.kalshi.com/trade-api/v2/series/{series}"
    "/markets/{ticker}/candlesticks"
)
WINDOW_LO = 0.50  # mature-window start: skip the diffuse early phase where a range
WINDOW_HI = 0.85  # market's brackets all look like longshots (winner not yet
# separated), and stop before the last ~15% settles toward 0/100.


def _period_interval(duration_s: int) -> int:
    """Candle granularity that keeps the count well under API caps across the
    15-min-to-monthly range."""
    if duration_s <= 6 * 3600:
        return 1          # intraday: 1-minute candles
    if duration_s <= 10 * 86400:
        return 60         # up to ~10 days: hourly
    return 1440           # longer: daily


def _implied_p(candle: dict) -> float | None:
    """Market-implied YES probability [0,1] for one candle: traded mean if the
    candle had trades, else the bid/ask midpoint."""
    price = candle.get("price") or {}
    if price.get("mean_dollars") not in (None, ""):
        return float(price["mean_dollars"])
    bid = (candle.get("yes_bid") or {}).get("close_dollars")
    ask = (candle.get("yes_ask") or {}).get("close_dollars")
    vals = [float(x) for x in (bid, ask) if x not in (None, "")]
    return sum(vals) / len(vals) if vals else None


def _cents(candle: dict, side: str) -> int | None:
    """Close price (cents) of a candle's yes_bid / yes_ask side."""
    v = (candle.get(side) or {}).get("close_dollars")
    return round(float(v) * 100) if v not in (None, "") else None


def _fetch_candles(series: str, ticker: str, start_ts: int, end_ts: int, interval: int) -> list[dict]:
    r = httpx.get(
        CANDLE_URL.format(series=series, ticker=ticker),
        params={"start_ts": start_ts, "end_ts": end_ts, "period_interval": interval},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json().get("candlesticks", [])


def market_pre_price(series: str, ticker: str, open_ts: int, close_ts: int,
                     win_lo: float = WINDOW_LO, win_hi: float = WINDOW_HI) -> float | None:
    """Mean implied price over the [win_lo, win_hi] mature window of the market's life."""
    dur = close_ts - open_ts
    if dur <= 0:
        return None
    lo = open_ts + win_lo * dur
    hi = open_ts + win_hi * dur
    candles = _fetch_candles(series, ticker, open_ts, close_ts, _period_interval(dur))
    ps = [
        p
        for c in candles
        if lo <= c.get("end_period_ts", close_ts) <= hi
        for p in (_implied_p(c),)
        if p is not None
    ]
    return statistics.mean(ps) if ps else None


def entry_quote(series: str, ticker: str, open_ts: int, close_ts: int,
                entry_frac: float = 0.6) -> tuple[int, int] | None:
    """The (yes_bid, yes_ask) cents from the candle nearest `entry_frac` of the
    market's life — the realistic quote a trader would face at entry."""
    dur = close_ts - open_ts
    if dur <= 0:
        return None
    target = open_ts + entry_frac * dur
    candles = _fetch_candles(series, ticker, open_ts, close_ts, _period_interval(dur))
    best, best_d = None, None
    for c in candles:
        t = c.get("end_period_ts")
        if t is None:
            continue
        d = abs(t - target)
        if best_d is None or d < best_d:
            best_d, best = d, c
    if best is None:
        return None
    bid, ask = _cents(best, "yes_bid"), _cents(best, "yes_ask")
    return None if (bid is None or ask is None) else (bid, ask)


def settled_markets(conn, series: str, limit: int) -> list[tuple]:
    """Most-recent `limit` settled markets for a series: (ticker, open_ts, close_ts, result)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT market_ticker, open_ts, close_ts, result FROM (
                SELECT DISTINCT ON (market_ticker) market_ticker,
                       extract(epoch from open_time)::bigint AS open_ts,
                       extract(epoch from close_time)::bigint AS close_ts,
                       result, close_time
                FROM expansion_market_snapshots
                WHERE series_ticker = %s AND status = 'settled' AND result IN ('yes','no')
                  AND open_time IS NOT NULL AND close_time IS NOT NULL
                ORDER BY market_ticker, snapshot_at DESC
            ) t ORDER BY close_time DESC LIMIT %s
            """,
            (series, limit),
        )
        return cur.fetchall()
