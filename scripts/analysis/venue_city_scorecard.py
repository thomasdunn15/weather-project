"""Every city on every venue, scored on the same realistic basis.

Three things make naive city comparisons wrong, and this corrects all three:

1. BACKFILLED ROWS. paper_trades holds both rows logged in real time and rows
   reconstructed later from stored forecasts. Backfilled rows silently encode
   hindsight. Only rows where (logged_at::date - target_date) <= 1 are real
   forward evidence, and that single filter previously flipped total P&L from
   +$13,010 to -$810.

2. SPREAD. Kalshi and Polymarket publish a book, so the spread is read straight
   off the quote we logged. Every result is reported twice: POSTING (pay half
   the spread) and CROSSING (pay all of it). For ForecastEx that gap was the
   difference between t=1.84 and t=3.77, so a single number would be a lie.

3. FEES. Kalshi 7%*p*(1-p) taker, Polymarket 6%*p*(1-p), ForecastEx 1c flat.
   These differ enough to reorder cities on their own.

ForecastEx numbers come from forecastex_variants.py rather than being recomputed
here: it settles on Weather Underground, not the NWS CLI our observations carry,
so it cannot share this scoring path.

  uv run python scripts/analysis/venue_city_scorecard.py
  uv run python scripts/analysis/venue_city_scorecard.py --contracts 250
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from weather_markets.db import get_connection

_REPO = Path(__file__).resolve().parents[2]
FX_VARIANTS = _REPO / "data" / "forecastex_variants.json"

CITY = {"KORD": "Chicago", "KMIA": "Miami", "KDFW": "Dallas", "KPHX": "Phoenix",
        "KLAX": "Los Angeles", "KSEA": "Seattle", "KDEN": "Denver",
        "KAUS": "Austin", "KLAS": "Las Vegas", "KMSY": "New Orleans",
        "KSFO": "San Francisco", "KNYC": "New York", "KMDW": "Chicago (MDW)"}

FEE_RATE = {"kalshi": 0.07, "polymarket": 0.06}
MIN_DAYS = 20            # below this, a Sharpe is decoration


def fee_cents(price_c: float, platform: str) -> float:
    p = price_c / 100.0
    return FEE_RATE.get(platform, 0.0) * p * (1 - p) * 100.0


def load(conn, platform: str):
    """Forward-logged signals with their quoted spread and realized outcome."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.station_id, pt.target_date, pt.position, pt.entry_price_cents,
                   pt.market_yes_bid, pt.market_yes_ask, pt.edge,
                   c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            JOIN observations o ON o.date = pt.target_date AND o.station_id = c.station_id
            WHERE c.platform = %s
              AND pt.model_source LIKE 'EMOS combined 00Z%%'
              AND (pt.logged_at::date - pt.target_date) <= 1
              AND pt.market_yes_bid IS NOT NULL AND pt.market_yes_ask IS NOT NULL
            ORDER BY c.station_id, pt.target_date""", (platform,))
        rows = cur.fetchall()

    by_city = defaultdict(lambda: defaultdict(list))
    for (st, td, pos, entry, bid, ask, edge, btype, lo, hi, obs) in rows:
        spread = max(0, int(ask) - int(bid))
        if btype == "between":
            won_yes = lo is not None and hi is not None and lo <= obs <= hi
        elif btype == "greater_than":
            won_yes = lo is not None and obs > lo
        elif btype == "less_than":
            won_yes = hi is not None and obs < hi
        else:
            continue
        won = won_yes if pos == "BUY_YES" else not won_yes
        by_city[st][td].append({"entry": int(entry), "spread": spread, "won": won})
    return by_city


def score(days: dict, platform: str, spread_mult: float, contracts: int):
    daily = {}
    n = 0
    for td, trades in days.items():
        tot = 0.0
        for t in trades:
            # Posting pays half the quoted spread, crossing pays all of it.
            entry = t["entry"] + t["spread"] * spread_mult
            if not 1 <= entry <= 99:
                continue
            gross = (100 - entry) if t["won"] else -entry
            tot += gross - fee_cents(entry, platform)
            n += 1
        if n:
            daily[td] = tot * contracts
    if len(daily) < MIN_DAYS:
        return None
    v = list(daily.values())
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    sharpe = (statistics.mean(v) / sd) * (252 ** 0.5) if sd > 0 else None
    ds = sorted(daily)
    mid = ds[len(ds) // 2]
    h1 = sum(daily[d] for d in ds if d < mid)
    h2 = sum(daily[d] for d in ds if d >= mid)
    return {"net": sum(v) / 100, "days": len(v), "trades": n,
            "sharpe": round(sharpe, 2) if sharpe else None,
            "tstat": round(sharpe * math.sqrt(len(v) / 252), 2) if sharpe else None,
            "both": h1 > 0 and h2 > 0,
            "spread": round(statistics.mean(t["spread"] for ts in days.values()
                                            for t in ts), 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contracts", type=int, default=500)
    a = ap.parse_args()

    conn = get_connection()
    try:
        out = {}
        for platform in ("kalshi", "polymarket"):
            cities = load(conn, platform)
            rows = []
            for st, days in cities.items():
                post = score(days, platform, 0.5, a.contracts)
                cross = score(days, platform, 1.0, a.contracts)
                if post:
                    rows.append((st, post, cross))
            rows.sort(key=lambda r: -(r[1]["tstat"] or -9))
            out[platform] = rows

            print(f"\n{'='*80}\n{platform.upper()} — forward-logged only, "
                  f"{a.contracts} contracts, net of fee AND spread\n{'='*80}")
            if not rows:
                print(f"  no city has >= {MIN_DAYS} forward days yet")
                continue
            print(f"{'city':16}{'days':>6}{'trd':>6}{'spr':>6}"
                  f"{'POST net':>11}{'t':>6}   {'CROSS net':>11}{'t':>6}  halves")
            for st, p, c in rows:
                cn = f"${c['net']:9,.0f}" if c else "        –"
                ct = f"{c['tstat']:5.2f}" if c and c["tstat"] else "    –"
                print(f"{CITY.get(st, st):16}{p['days']:6d}{p['trades']:6d}"
                      f"{p['spread']:5.1f}c${p['net']:10,.0f}{p['tstat'] or 0:6.2f}   "
                      f"{cn}{ct}  {'yes' if p['both'] else 'NO'}")

        if FX_VARIANTS.exists():
            fx = json.loads(FX_VARIANTS.read_text())
            print(f"\n{'='*80}\nFORECASTEX — from forecastex_variants.py "
                  f"(settles on Weather Underground, separate scoring path)\n{'='*80}")
            best = fx.get("uniform", [])[:1]
            if best:
                b = best[0]
                print(f"  best UNIFORM config across 9 cities: {b['strategy']} "
                      f"edge>={b['edge']:.2f} minPx={b['min_entry']} picks={b['picks']} "
                      f"-> ${b['total_net']:,} ({b['cities_positive']}/{b['n_cities']} "
                      f"cities positive)")
            print("  per-city detail: uv run python scripts/analysis/forecastex_variants.py --all")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
