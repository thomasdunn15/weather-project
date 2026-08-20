"""FLB-regime metric: are a series' longshots actually overpriced?

The strategy-assess engine can't tell a favorite/longshot market (harvestable by
FLB) from a near-coin-flip (no longshot regime) because collect_metrics only has
volume/OI/spread — no price distribution. This computes the missing signal.

For each settled market in a series we pull Kalshi candlesticks, take a
PRE-RESOLUTION implied price, bucket by price, and compare the implied price to
the realized YES-settlement rate:

    FLB present (harvestable)  = <30c longshots are OVERPRICED (implied > actual YES rate)
    No longshot regime         = almost no <30c mass (e.g. 15-min up/down ~ 50c)

Pre-resolution price = MEAN implied price over a MATURE WINDOW of the market's
life ([WINDOW_LO, WINDOW_HI] = 50-85% by default). Late enough that a multi-
bracket range market's eventual winner has separated from the genuine longshots
(a first-half mean mislabels the not-yet-separated winner as an underpriced
longshot -> spurious "inverse FLB"), but early enough to precede the settlement
convergence to 0/100. Works from 15-minute to monthly markets. Implied price per
candle = traded mean if present, else bid/ask mid.

    uv run python scripts/analysis/flb_regime.py KXWTIW KXBTC15M KXBTCMAXMON
    uv run python scripts/analysis/flb_regime.py KXWTIW --limit 60
"""
from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from weather_markets.db import get_connection
from weather_markets.expansion.candlesticks import (  # noqa: F401 (re-exported for tests)
    WINDOW_HI,
    WINDOW_LO,
    _implied_p,
    _period_interval,
    market_pre_price,
    settled_markets as _settled_markets,
)


@dataclass
class RegimeBucket:
    label: str
    n: int
    mean_implied: float
    yes_rate: float

    @property
    def overpricing(self) -> float:
        # +ve = market prices these ABOVE their realized win rate (FLB signal)
        return self.mean_implied - self.yes_rate


_BUCKETS = [("<30c longshot", 0.0, 0.30), ("30-50c", 0.30, 0.50), (">=50c favorite", 0.50, 1.01)]


def bucketize(obs: list[tuple[float, int]]) -> list[RegimeBucket]:
    out = []
    for label, lo, hi in _BUCKETS:
        sel = [(p, y) for p, y in obs if lo <= p < hi]
        if sel:
            out.append(RegimeBucket(label, len(sel),
                                    statistics.mean(p for p, _ in sel),
                                    statistics.mean(y for _, y in sel)))
    return out


def compute_regime(conn, series: str, limit: int = 120, throttle: float = 0.15,
                   win_lo: float = WINDOW_LO, win_hi: float = WINDOW_HI):
    """Returns (observations[(implied_p, outcome)], n_attempted, median_life_hours)."""
    rows = _settled_markets(conn, series, limit)
    obs: list[tuple[float, int]] = []
    durs: list[float] = []
    for ticker, open_ts, close_ts, result in rows:
        time.sleep(throttle)
        try:
            p = market_pre_price(series, ticker, int(open_ts), int(close_ts), win_lo, win_hi)
        except Exception:
            p = None
        if p is not None:
            obs.append((p, 1 if result == "yes" else 0))
            durs.append((int(close_ts) - int(open_ts)) / 3600.0)
    return obs, len(rows), (statistics.median(durs) if durs else None)


def summarize(series: str, obs: list[tuple[float, int]], median_hours: float | None) -> dict:
    """Storable per-series summary (the row written to flb_regime)."""
    buckets = bucketize(obs)
    bd = {b.label: {"n": b.n, "mean_implied": round(b.mean_implied, 4),
                    "yes_rate": round(b.yes_rate, 4),
                    "overpricing_pp": round(b.overpricing * 100, 2)} for b in buckets}
    ls = next((b for b in buckets if b.label.startswith("<30")), None)
    fav = next((b for b in buckets if b.label.startswith(">=50")), None)
    return {
        "series_ticker": series,
        "n_markets": len(obs),
        "longshot_mass": round(sum(p < 0.30 for p, _ in obs) / len(obs), 4) if obs else None,
        "longshot_overpricing_pp": round(ls.overpricing * 100, 2) if ls else None,
        "favorite_underpricing_pp": round(-fav.overpricing * 100, 2) if fav else None,
        "resolution_hours": round(median_hours, 2) if median_hours else None,
        "verdict": verdict(obs),
        "buckets": bd,
    }


def write_regime(conn, s: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flb_regime (series_ticker, n_markets, longshot_mass,
                longshot_overpricing_pp, favorite_underpricing_pp, resolution_hours,
                verdict, buckets, computed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
            ON CONFLICT (series_ticker) DO UPDATE SET
                n_markets=EXCLUDED.n_markets, longshot_mass=EXCLUDED.longshot_mass,
                longshot_overpricing_pp=EXCLUDED.longshot_overpricing_pp,
                favorite_underpricing_pp=EXCLUDED.favorite_underpricing_pp,
                resolution_hours=EXCLUDED.resolution_hours, verdict=EXCLUDED.verdict,
                buckets=EXCLUDED.buckets, computed_at=now()
            """,
            (s["series_ticker"], s["n_markets"], s["longshot_mass"],
             s["longshot_overpricing_pp"], s["favorite_underpricing_pp"],
             s["resolution_hours"], s["verdict"], Jsonb(s["buckets"])),
        )
    conn.commit()


def verdict(obs: list[tuple[float, int]]) -> str:
    if len(obs) < 10:
        return "INSUFFICIENT DATA (too few settled markets with candlesticks)"
    longshot_mass = sum(p < 0.30 for p, _ in obs) / len(obs)
    if longshot_mass < 0.10:
        return (f"NO LONGSHOT REGIME — only {longshot_mass:.0%} of markets priced <30c "
                "(near coin-flip); FLB has nothing to harvest here")
    ls = [(p, y) for p, y in obs if p < 0.30]
    op = statistics.mean(p for p, _ in ls) - statistics.mean(y for _, y in ls)
    if op > 0.05:
        return (f"FLB PRESENT — {longshot_mass:.0%} longshot mass, <30c longshots OVERPRICED "
                f"by {op*100:.1f}pp (harvestable: fade longshots / be the favorite side)")
    if op < -0.05:
        return (f"INVERSE FLB — <30c longshots UNDERPRICED by {-op*100:.1f}pp (do not fade)")
    return (f"FLB WEAK — {longshot_mass:.0%} longshot mass but longshots fairly priced "
            f"(overpricing {op*100:+.1f}pp)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("series", nargs="+", help="series tickers, e.g. KXWTIW KXBTC15M")
    ap.add_argument("--limit", type=int, default=120, help="most-recent settled markets per series")
    ap.add_argument("--write", action="store_true", help="store results in the flb_regime table")
    ap.add_argument("--win-lo", type=float, default=WINDOW_LO, help="mature-window start (fraction of life)")
    ap.add_argument("--win-hi", type=float, default=WINDOW_HI, help="mature-window end (fraction of life)")
    args = ap.parse_args()

    conn = get_connection()
    try:
        for series in args.series:
            obs, n_attempt, median_hours = compute_regime(
                conn, series, limit=args.limit, win_lo=args.win_lo, win_hi=args.win_hi)
            speed = f"{median_hours:.1f}h life" if median_hours else "life ?"
            print(f"\n=== {series} — {len(obs)}/{n_attempt} priced · median {speed} ===")
            for b in bucketize(obs):
                print(f"  {b.label:16s} n={b.n:4d}  mean implied {b.mean_implied*100:5.1f}c  "
                      f"actual YES {b.yes_rate*100:5.1f}%  overpricing {b.overpricing*100:+5.1f}pp")
            print(f"  VERDICT: {verdict(obs)}")
            if args.write:
                write_regime(conn, summarize(series, obs, median_hours))
                print("  [written to flb_regime]")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
