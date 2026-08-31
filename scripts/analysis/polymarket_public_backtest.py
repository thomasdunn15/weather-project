"""Backtest our daily-high strategy on PUBLIC Polymarket (polymarket.com).

This is a DIFFERENT venue from the api.polymarket.us client in the codebase.
Public Polymarket runs the Gamma/CLOB stack, lists 11 US cities, and settles on
Weather Underground. Getting any of those three wrong invents edge, so:

1. GROUND TRUTH is the market's own resolution, not our observations table.
   These settle on Wunderground; `observations` holds the NWS CLI high, and the
   measured CLI->WU gap runs to -2.4F on some stations. We read which bracket
   resolved to $1 (outcomePrices == ["1","0"]) — that IS the WU answer, exact
   and free, so no scraping and no basis contamination.

2. STATION must match ours or the forecast is for a different airport. Five
   cities port exactly (Miami/Chicago-ORD/LA/Austin/Seattle). Four do NOT and
   are excluded, loudly: Dallas is LOVE FIELD not DFW, NYC is LAGUARDIA not
   Central Park, Denver is BUCKLEY SFB not DEN, Houston is HOBBY not IAH.

3. FEES are the venue's real schedule, from docs.polymarket.com/trading/fees:
   fee = C * feeRate * p * (1-p), weather feeRate = 0.05 for TAKERS and
   **0 for makers**. Posting on this venue is fee-free, which is why POST and
   CROSS are reported separately — the gap is the whole decision.

Prices come from the CLOB prices-history endpoint at the city's decision time,
never the close.

  uv run python scripts/analysis/polymarket_public_backtest.py --harvest
  uv run python scripts/analysis/polymarket_public_backtest.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from weather_markets.db import get_connection

_REPO = Path(__file__).resolve().parents[2]
EVENTS = _REPO / "data" / "pm_public_events.json"
PRICES = _REPO / "data" / "pm_public_prices.json"

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

WEATHER_TAKER_FEE = 0.05        # docs.polymarket.com/trading/fees
WEATHER_MAKER_FEE = 0.0         # makers are never charged

# Only cities whose Polymarket station is the SAME airport our forecasts use.
CITY_STATION = {"Miami": "KMIA", "Chicago": "KORD", "Los Angeles": "KLAX",
                "Austin": "KAUS", "Seattle": "KSEA", "San Francisco": "KSFO"}
# Listed but NOT portable — different airport from ours. Kept for the report.
MISMATCH = {"Dallas": "KDAL vs our KDFW (Love Field, not DFW)",
            "NYC": "KLGA vs our KNYC (LaGuardia, not Central Park)",
            "Denver": "KBKF vs our KDEN (Buckley SFB, not Denver Intl)",
            "Houston": "KHOU (Hobby) — no forecast pipeline",
            "Atlanta": "KATL — no forecast pipeline"}

DECISION_UTC = {"KMIA": (15, 30), "KORD": (15, 15), "KLAX": (15, 30),
                "KAUS": (17, 32), "KSEA": (15, 30), "KSFO": (15, 30)}

TITLE = re.compile(r"Highest temperature in ([\w .'-]+?) on (\w+) (\d+)\?", re.I)
MONTH = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
# "89F or below" / "90-91F" / "90–91F" (en dash) / "108F or higher"
BAND_LO = re.compile(r"^(-?\d+)\s*°?F?\s*or\s*below", re.I)
BAND_HI = re.compile(r"^(-?\d+)\s*°?F?\s*or\s*(?:higher|above)", re.I)
BAND_MID = re.compile(r"^(-?\d+)\s*[-–—]\s*(-?\d+)\s*°?F?$", re.I)


def norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def band(label: str) -> tuple[float, float] | None:
    """Bracket label -> (lo, hi) inclusive in F; +/-inf for the tails."""
    s = (label or "").replace("°", "°").strip()
    m = BAND_MID.match(s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = BAND_LO.match(s)
    if m:
        return float("-inf"), float(m.group(1))
    m = BAND_HI.match(s)
    if m:
        return float(m.group(1)), float("inf")
    return None


def model_p(lo: float, hi: float, mu: float, sigma: float) -> float:
    """P(high lands in [lo, hi]) under N(mu, sigma), integer-rounded highs."""
    above_lo = 1.0 if lo == float("-inf") else norm_sf((lo - 0.5 - mu) / sigma)
    above_hi = 0.0 if hi == float("inf") else norm_sf((hi + 0.5 - mu) / sigma)
    return max(0.0, above_lo - above_hi)


def harvest(since: str = "2025-06-01", until: str = "2026-08-19") -> None:
    """Pull every resolved US temperature event + its resolution into a cache.

    By SLUG, not pagination: /events caps at offset 2100 and /events/keyset does
    not document its cursor parameter, so both silently truncate history to
    whatever slice they land on — an earlier pass lost the entire recent window
    that way. Slugs are deterministic, so enumerating them is exact.

    Two slug shapes exist: markets through Feb 2026 omit the year
    (`...-on-december-4`), March 2026 onward include it (`...-on-march-1-2026`).
    Both are tried; the API silently drops slugs that do not exist.
    """
    h = httpx.Client(timeout=40.0, headers=UA)
    d0, d1 = date.fromisoformat(since), date.fromisoformat(until)
    names = {c: c.lower().replace(" ", "-") for c in CITY_STATION}

    wanted = []
    d = d0
    while d <= d1:
        stem = f"{d:%B}".lower() + f"-{d.day}"
        for city, slugname in names.items():
            wanted.append((city, d, f"highest-temperature-in-{slugname}-on-{stem}"))
            wanted.append((city, d, f"highest-temperature-in-{slugname}-on-{stem}-{d.year}"))
        d = date.fromordinal(d.toordinal() + 1)

    by_slug = {sl: (c, dt) for c, dt, sl in wanted}
    seen, batch = {}, 40
    for i in range(0, len(wanted), batch):
        chunk = [sl for _, _, sl in wanted[i:i + batch]]
        try:
            # limit is REQUIRED: gamma defaults to 20 and silently truncates a
            # 40-slug batch, which reads as "that city has no markets".
            r = h.get(f"{GAMMA}/events", params=[("slug", s) for s in chunk]
                      + [("limit", str(batch * 2))]).json()
        except Exception as e:
            print(f"  slug batch {i} failed: {str(e)[:70]}", flush=True)
            continue
        for e in (r if isinstance(r, list) else []):
            seen[e.get("slug")] = e
        if (i // batch) % 25 == 0:
            print(f"  {i}/{len(wanted)} slugs probed, {len(seen)} events found",
                  flush=True)
        time.sleep(0.08)

    out = []
    for slug, e in seen.items():
        meta = by_slug.get(slug)
        if not meta:
            continue
        city, td = meta
        brackets, resolved = [], False
        for k in (e.get("markets") or []):
            bd = band(k.get("groupItemTitle", ""))
            toks = k.get("clobTokenIds")
            if not bd or not toks:
                continue
            try:
                tok = json.loads(toks)[0] if isinstance(toks, str) else toks[0]
                px = json.loads(k["outcomePrices"]) if isinstance(
                    k.get("outcomePrices"), str) else k.get("outcomePrices")
            except (json.JSONDecodeError, KeyError, TypeError, IndexError):
                continue
            if not px:
                continue
            won = str(px[0]) in ("1", "1.0")
            resolved = resolved or won
            brackets.append({"label": k.get("groupItemTitle"), "lo": bd[0],
                             "hi": bd[1], "token": tok, "won": won})
        if resolved and len(brackets) >= 3:
            out.append({"city": city, "station": CITY_STATION[city],
                        "date": td.isoformat(), "brackets": brackets})

    out.sort(key=lambda x: (x["city"], x["date"]))
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text(json.dumps(out, indent=1))
    per = defaultdict(list)
    for e in out:
        per[e["city"]].append(e["date"])
    print(f"\ncached {len(out)} resolved, station-matched events -> {EVENTS}")
    for c in sorted(per):
        ds = sorted(per[c])
        print(f"  {c:<15} {len(ds):4d} days   {ds[0]} .. {ds[-1]}")


def fetch_prices(max_brackets: int = 5) -> None:
    """Decision-time price for the brackets our model could plausibly trade."""
    events = json.loads(EVENTS.read_text())
    cache = json.loads(PRICES.read_text()) if PRICES.exists() else {}
    h = httpx.Client(timeout=40.0, headers=UA)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (c.station_id, pt.target_date)
                       c.station_id, pt.target_date, pt.emos_mu, pt.emos_sigma
                FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
                WHERE pt.emos_mu IS NOT NULL AND pt.emos_sigma IS NOT NULL
                  AND pt.model_source LIKE 'EMOS combined 00Z%'
                  -- FORWARD-LOGGED ONLY. paper_trades mixes real-time rows with
                  -- rows reconstructed later from stored forecasts; the
                  -- backfilled ones encode hindsight, and on the Kalshi
                  -- scorecard this same filter moved total P&L from +$13,010 to
                  -- -$810. A mu that was never actually available at the
                  -- decision time is not a mu we could have traded.
                  AND (pt.logged_at::date - pt.target_date) <= 1
                ORDER BY c.station_id, pt.target_date, pt.logged_at""")
            model = {(s, d): (mu, sg) for s, d, mu, sg in cur.fetchall()}
    finally:
        conn.close()

    todo, n = [], 0
    for e in events:
        td = date.fromisoformat(e["date"])
        key = (e["station"], td)
        if key not in model:
            continue
        mu, sigma = model[key]
        hh, mm = DECISION_UTC.get(e["station"], (15, 30))
        ts = int(datetime(td.year, td.month, td.day, hh, mm,
                          tzinfo=timezone.utc).timestamp())
        # brackets closest to our mu — the only ones a signal can come from
        near = sorted(e["brackets"],
                      key=lambda b: abs(((b["lo"] if b["lo"] != float("-inf") else b["hi"])
                                         + (b["hi"] if b["hi"] != float("inf") else b["lo"])) / 2 - mu))
        for b in near[:max_brackets]:
            if b["token"] in cache:
                continue
            todo.append((b["token"], ts))
    print(f"{len(todo)} bracket price series to fetch "
          f"({len(cache)} already cached)", flush=True)

    for tok, ts in todo:
        try:
            r = h.get(f"{CLOB}/prices-history", params={
                "market": tok, "startTs": ts - 5400, "endTs": ts + 300,
                "fidelity": 5})
            pts = r.json().get("history") or []
            at = [p for p in pts if p.get("t", 0) <= ts]
            cache[tok] = {"p": at[-1]["p"], "t": at[-1]["t"]} if at else None
        except Exception as e:
            cache[tok] = None
            print(f"  {tok[:14]}… failed: {str(e)[:60]}", flush=True)
        n += 1
        if n % 100 == 0:
            PRICES.write_text(json.dumps(cache))
            print(f"  {n}/{len(todo)}", flush=True)
        time.sleep(0.08)
    PRICES.write_text(json.dumps(cache))
    got = sum(1 for v in cache.values() if v)
    print(f"cached {got}/{len(cache)} price points -> {PRICES}")


def measure_spreads() -> dict:
    """Per-city median quoted spread on OPEN markets, near the money.

    The price-history endpoint gives a single series, not a book, so the spread
    has to come from live quotes. Junk brackets (a tenth of a cent bid against
    nothing) are excluded — they would report a 0.1c spread we could never
    trade, and drag the median toward a fiction.
    """
    h = httpx.Client(timeout=40.0, headers=UA)
    per = defaultdict(list)
    for off in range(0, 400, 100):
        try:
            b = h.get(f"{GAMMA}/events", params={
                "closed": "false", "limit": 100, "offset": off,
                "tag_slug": "weather"}).json()
        except Exception:
            break
        if not isinstance(b, list) or not b:
            break
        for e in b:
            m = TITLE.search(e.get("title", ""))
            if not m or m.group(1).strip() not in CITY_STATION:
                continue
            for k in (e.get("markets") or []):
                bid, ask, sp = k.get("bestBid"), k.get("bestAsk"), k.get("spread")
                if bid is None or ask is None or sp is None:
                    continue
                if not (0.05 <= float(bid) <= 0.95):
                    continue
                per[m.group(1).strip()].append(float(sp))
        time.sleep(0.15)
    return {c: statistics.median(v) for c, v in per.items() if v}


def _stats(daily: list[float]) -> tuple[float, float | None, float | None]:
    tot = sum(daily)
    if len(daily) < 3:
        return tot, None, None
    sd = statistics.pstdev(daily)
    if sd == 0:
        return tot, None, None
    sh = statistics.fmean(daily) / sd
    return tot, sh, sh * math.sqrt(len(daily))


def score(threshold: float, contracts: int, min_px: float,
          picks: int, spreads: dict) -> None:
    events = json.loads(EVENTS.read_text())
    prices = json.loads(PRICES.read_text()) if PRICES.exists() else {}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (c.station_id, pt.target_date)
                       c.station_id, pt.target_date, pt.emos_mu, pt.emos_sigma
                FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
                WHERE pt.emos_mu IS NOT NULL AND pt.emos_sigma IS NOT NULL
                  AND pt.model_source LIKE 'EMOS combined 00Z%'
                  -- FORWARD-LOGGED ONLY. paper_trades mixes real-time rows with
                  -- rows reconstructed later from stored forecasts; the
                  -- backfilled ones encode hindsight, and on the Kalshi
                  -- scorecard this same filter moved total P&L from +$13,010 to
                  -- -$810. A mu that was never actually available at the
                  -- decision time is not a mu we could have traded.
                  AND (pt.logged_at::date - pt.target_date) <= 1
                ORDER BY c.station_id, pt.target_date, pt.logged_at""")
            model = {(s, d): (mu, sg) for s, d, mu, sg in cur.fetchall()}
    finally:
        conn.close()

    daily = {"post": defaultdict(lambda: defaultdict(float)),
             "cross": defaultdict(lambda: defaultdict(float))}
    ntr = defaultdict(int)
    skipped_no_price = 0

    for e in sorted(events, key=lambda x: x["date"]):
        td = date.fromisoformat(e["date"])
        key = (e["station"], td)
        if key not in model:
            continue
        mu, sigma = model[key]
        half = spreads.get(e["city"], 0.03) * 100.0 / 2.0

        cands = []
        for b in e["brackets"]:
            if b["token"] not in prices:
                continue          # never fetched (only the near-mu ladder is)
            q = prices[b["token"]]
            if not q:
                skipped_no_price += 1   # fetched, but genuinely no print
                continue
            mkt = float(q["p"])
            if not (min_px / 100.0 <= mkt <= 1 - min_px / 100.0):
                continue
            ours = model_p(b["lo"], b["hi"], mu, sigma)
            # buy YES at mkt, or buy NO at 1-mkt; edge is signed the same way
            if ours - mkt >= threshold:
                cands.append((ours - mkt, "yes", mkt * 100.0, b["won"]))
            elif mkt - ours >= threshold:
                cands.append((mkt - ours, "no", (1 - mkt) * 100.0, not b["won"]))

        for edge, side, mid_c, won in sorted(cands, reverse=True)[:picks]:
            ntr[e["city"]] += 1
            for mode in ("post", "cross"):
                entry = mid_c + half if mode == "cross" else mid_c - half
                entry = min(99.0, max(1.0, entry))
                p = entry / 100.0
                fee = (WEATHER_TAKER_FEE if mode == "cross" else WEATHER_MAKER_FEE) \
                    * p * (1 - p) * 100.0
                pnl = ((100.0 - entry) if won else -entry) - fee
                daily[mode][e["city"]][td] += pnl * contracts / 100.0

    print(f"\n{'='*84}")
    print(f"PUBLIC POLYMARKET (polymarket.com) — edge>={threshold:.2f}, "
          f"{contracts} contracts, minPx {min_px:.0f}c, top {picks}/day")
    print(f"settles on Wunderground (market's own resolution) | "
          f"taker fee {WEATHER_TAKER_FEE}*p*(1-p), maker fee 0")
    print("=" * 84)
    print(f"{'city':<15}{'days':>5}{'trd':>5}{'spr':>6}"
          f"{'POST net':>11}{'t':>7}{'CROSS net':>12}{'t':>7}  halves")

    rows = []
    for city in sorted(set(daily["post"]) | set(daily["cross"])):
        dp = daily["post"][city]
        dc = daily["cross"][city]
        days = sorted(dp)
        if not days:
            continue
        vp = [dp[d] for d in days]
        vc = [dc[d] for d in days]
        tp, _, t_p = _stats(vp)
        tc, _, t_c = _stats(vc)
        mid = len(vp) // 2
        h1, h2 = sum(vp[:mid]), sum(vp[mid:])
        both = "yes" if (h1 > 0 and h2 > 0) else "NO"
        sp = spreads.get(city, 0.03) * 100
        rows.append((tp, city, len(days), ntr[city], sp, tp, t_p, tc, t_c, both))

    for _, city, nd, nt, sp, tp, t_p, tc, t_c, both in sorted(rows, reverse=True):
        print(f"{city:<15}{nd:5d}{nt:5d}{sp:5.1f}c"
              f"{'$%10s' % f'{tp:,.0f}'}{(f'{t_p:6.2f}' if t_p else '     —')}"
              f"{'$%11s' % f'{tc:,.0f}'}{(f'{t_c:6.2f}' if t_c else '     —')}"
              f"  {both}")
    if not rows:
        print("  no scoreable city — run --harvest and --prices first")
    if skipped_no_price:
        print(f"\n  ({skipped_no_price} of the near-money bracket-days we "
              f"priced had no print at the decision time and were skipped, "
              f"not assumed fillable)")
    print("\nNOT PORTABLE — Polymarket uses a different station than our model:")
    for c, why in MISMATCH.items():
        print(f"  {c:<15} {why}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harvest", action="store_true", help="refresh event cache")
    ap.add_argument("--since", default="2025-06-01")
    ap.add_argument("--prices", action="store_true", help="refresh price cache")
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--contracts", type=int, default=500)
    ap.add_argument("--min-px", type=float, default=3.0)
    ap.add_argument("--picks", type=int, default=1)
    ap.add_argument("--spread", type=float, default=None,
                    help="override measured spread, in cents, for every city")
    a = ap.parse_args()

    if a.harvest:
        harvest(since=a.since)
    if a.prices:
        fetch_prices()
    if not EVENTS.exists():
        print("no event cache — run with --harvest first")
        return 1
    if a.spread is not None:
        sp = {c: a.spread / 100.0 for c in CITY_STATION}
        print(f"spread OVERRIDDEN to {a.spread:.1f}c for every city")
    else:
        sp = measure_spreads()
        print("measured spreads (median, near-money, open markets):",
              {c: f"{v*100:.1f}c" for c, v in sorted(sp.items())})
        print("  NOTE: this is a snapshot of whatever is open right now, so it "
              "moves with time of day. Stress it with --spread.")
    score(a.threshold, a.contracts, a.min_px, a.picks, sp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
