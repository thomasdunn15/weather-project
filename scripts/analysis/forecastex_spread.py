"""Recover ForecastEx's bid-ask spread from trade prints alone.

Why this exists: every ForecastEx backtest priced entries at the last trade,
i.e. assumed a ZERO spread. The live LAX ladder on 2026-08-20 showed 3-10c
(mean 5.5c), which is large enough to halve the measured edge — so the spread
has to be measured, not assumed. But no channel publishes it:
  - the public API has never carried a book (yes_bid/yes_ask are always NULL)
  - IBKR's snapshot omits fields 84/86 for these contracts, and its field 31
    is a derived mid whose YES and NO legs sum to exactly 1.00
  - the ForecastTrader UI shows a real book, but only to a human

What we DO have is every trade print since February. A market maker quoting
bid B and ask A produces prints that bounce between the two, and that bounce
shows up as NEGATIVE serial covariance in price changes. Roll (1984):

    spread = 2 * sqrt(-cov(dP_t, dP_t-1))     when the covariance is negative

Roll's assumptions (no drift in true value, no order-flow autocorrelation) do
not hold cleanly over a session where the forecast genuinely moves. Measured
against the hand-read ladder below it came out at 6.6c vs 5.5c actual — close
on the city average but SLIGHTLY HIGH, and it does not track per-strike
variation (the UI's 10c at strike 79 reads as 6.4c). So: trust it as a
city-level average, not as a per-strike number, and expect ~1c of overshoot.

A positive covariance means drift dominated the bounce; those contracts are
reported as unmeasurable rather than silently counted as zero-spread, which
would flatter the strategy.

Validation anchor: the LAX ladder was read by hand off ForecastTrader at
2026-08-20 ~14:00 UTC and averaged 5.5c across strikes 76-82. `--validate`
scores that same day against it.

  uv run python scripts/analysis/forecastex_spread.py --station KMIA
  uv run python scripts/analysis/forecastex_spread.py --all --validate
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.forecastex import PRODUCT_TO_STATION

_REPO = Path(__file__).resolve().parents[2]
OUT_JSON = _REPO / "data" / "forecastex_spread.json"
STATION_PRODUCT = {v: k for k, v in PRODUCT_TO_STATION.items()}

# Hand-read off the ForecastTrader UI, 2026-08-20 ~14:00 UTC, UHLAX Aug20 event.
# YES bid = 1 - (Buy Now No); spread = (Buy Now Yes) - that bid.
UI_ANCHOR = {"station": "KLAX", "date": date(2026, 8, 20),
             "spreads_c": {76: 3, 78: 4, 79: 10, 80: 6, 81: 5, 82: 5}}

MIN_PRINTS = 12          # Roll is noise below this
MIN_MOVES = 6            # need real changes, not a flat tape


def roll_spread_cents(prints: list[int]) -> float | None:
    """Roll's estimator over one contract's trade prints, in cents.

    Returns None when the covariance is non-negative (drift dominated the
    bounce) — that is 'unmeasurable', NOT 'no spread'. Collapsing those to zero
    is what would make the whole exercise flatter the strategy.
    """
    # Collapse repeats: consecutive identical prints carry no bounce information
    # and only dilute the covariance toward zero.
    seq = [p for i, p in enumerate(prints) if i == 0 or p != prints[i - 1]]
    if len(seq) < MIN_MOVES + 2:
        return None
    d = [b - a for a, b in zip(seq, seq[1:])]
    if len(d) < MIN_MOVES:
        return None
    pairs = list(zip(d, d[1:]))
    md, ml = statistics.mean(x for x, _ in pairs), statistics.mean(y for _, y in pairs)
    cov = sum((x - md) * (y - ml) for x, y in pairs) / len(pairs)
    if cov >= 0:
        return None
    return 2.0 * (-cov) ** 0.5


def per_contract(conn, station: str, day_from: date | None) -> dict:
    """ticker -> (event_date, strike, spread_cents or None, n_prints)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.ticker, c.target_date, c.strike_low, p.last_price
            FROM contracts c JOIN prices p ON p.ticker = c.ticker
            WHERE c.platform='forecastex' AND c.station_id=%s
              AND p.last_price IS NOT NULL
              AND (%s::date IS NULL OR c.target_date >= %s::date)
            ORDER BY c.ticker, p.snapshot_at""",
            (station, day_from, day_from))
        rows = cur.fetchall()
    series: dict[tuple, list] = defaultdict(list)
    for ticker, td, strike, px in rows:
        series[(ticker, td, float(strike))].append(int(px))
    out = {}
    for (ticker, td, strike), prints in series.items():
        if len(prints) < MIN_PRINTS:
            continue
        out[ticker] = (td, strike, roll_spread_cents(prints), len(prints))
    return out


def summarize(station: str, contracts: dict) -> dict | None:
    got = [s for (_, _, s, _) in contracts.values() if s is not None]
    if not got:
        return None
    got.sort()
    q = lambda p: got[min(len(got) - 1, int(p * len(got)))]
    days = {td for (td, _, _, _) in contracts.values()}
    return {"station": station, "product": STATION_PRODUCT.get(station),
            "contracts": len(contracts), "measured": len(got), "days": len(days),
            "unmeasurable": len(contracts) - len(got),
            "median_c": round(q(0.50), 2), "p25_c": round(q(0.25), 2),
            "p75_c": round(q(0.75), 2), "mean_c": round(statistics.mean(got), 2)}


def validate(conn) -> None:
    """Score the estimator against the one ladder we read by hand."""
    a = UI_ANCHOR
    contracts = per_contract(conn, a["station"], a["date"])
    same_day = {tk: v for tk, v in contracts.items() if v[0] == a["date"]}
    ui_mean = statistics.mean(a["spreads_c"].values())
    print(f"\n=== validation: {a['station']} {a['date']} vs the hand-read ladder ===")
    print(f"{'strike':>7}{'UI (c)':>9}{'Roll (c)':>10}{'prints':>8}")
    rows = []
    for _, (td, strike, sp, n) in sorted(same_day.items(), key=lambda kv: kv[1][1]):
        ui = a["spreads_c"].get(int(strike))
        if ui is None:
            continue
        rows.append((strike, ui, sp))
        print(f"{strike:7.0f}{ui:9d}{'–' if sp is None else f'{sp:9.1f}':>10}{n:8d}")
    got = [(u, s) for _, u, s in rows if s is not None]
    if got:
        rm = statistics.mean(s for _, s in got)
        print(f"\n  UI mean {ui_mean:.1f}c over {len(a['spreads_c'])} strikes")
        print(f"  Roll mean {rm:.1f}c over {len(got)} strikes -> "
              f"{'FLOOR holds' if rm <= ui_mean * 1.25 else 'OVERSHOOTS — investigate'}")
    else:
        print("  no strike overlapped — cannot validate")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", default="KMIA", choices=sorted(STATION_PRODUCT))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--since", type=date.fromisoformat, default=None)
    ap.add_argument("--validate", action="store_true", help="score against the UI anchor")
    ap.add_argument("--json", action="store_true", help=f"write {OUT_JSON}")
    a = ap.parse_args()

    conn = get_connection()
    try:
        stations = sorted(STATION_PRODUCT) if a.all else [a.station]
        results = []
        print(f"{'city':6}{'product':9}{'ctrs':>6}{'meas':>6}{'days':>6}"
              f"{'p25':>7}{'median':>8}{'p75':>7}{'mean':>7}")
        for st in stations:
            s = summarize(st, per_contract(conn, st, a.since))
            if not s:
                print(f"{st:6}{STATION_PRODUCT.get(st,''):9}  no measurable contracts")
                continue
            results.append(s)
            print(f"{s['station']:6}{s['product']:9}{s['contracts']:6d}{s['measured']:6d}"
                  f"{s['days']:6d}{s['p25_c']:7.1f}{s['median_c']:8.1f}"
                  f"{s['p75_c']:7.1f}{s['mean_c']:7.1f}")
        if a.validate:
            validate(conn)
        if a.json and results:
            OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
            OUT_JSON.write_text(json.dumps(
                {"note": "Roll (1984) spread from trade prints; a FLOOR, not a point "
                         "estimate — drift biases it downward.",
                 "cities": results}, indent=1))
            print(f"\nwrote {OUT_JSON}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
