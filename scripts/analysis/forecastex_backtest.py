"""Backtest our daily-high strategies on ForecastEx prices.

Honest-by-construction in three ways the naive version would get wrong:

1. GROUND TRUTH. ForecastEx settles on **Weather Underground's** station high,
   not the NWS CLI high in our `observations` table (measured -0.71 F mean,
   never above, over 63 Miami events). Scoring against our own observations
   would silently invent edge. We recover ForecastEx's OWN settled high from
   the settled strike ladder instead (forecastex.implied_settlement_highs).

2. DECISION-TIME PRICING. We price each trade off the last TICK at or before
   the city's live decision time, not the daily close — ForecastEx trades
   nearly 24h, so the close is a different market than the one we'd trade.

3. LIQUIDITY. Only contracts that actually printed are tradeable. We report
   how many candidate signals had no print in the window rather than assuming
   a fill at an untraded price.

Two model variants are reported side by side:
  naive     — our EMOS mu as-is (what a blind venue port would do; the WU/CLI
              basis shows up as a real cost)
  debiased  — mu shifted by the measured per-station CLI->WU offset (what a
              recalibrated model could do). Offset is fit on the FIRST half of
              events and applied to the SECOND half, so it is not in-sample.

  uv run python scripts/analysis/forecastex_backtest.py --station KMIA
"""
import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.forecastex import (
    ForecastExClient, implied_settlement_highs, parse_contract_id,
)

_REPO = Path(__file__).resolve().parents[2]
# Persistent (data/ is gitignored). Settlement ladders never change once an
# event has expired, so this only ever grows — the dashboard reads the derived
# backtest JSON, never re-downloads.
CACHE = _REPO / "data" / "forecastex_settlements.json"
BACKTEST_JSON = _REPO / "data" / "forecastex_backtest.json"
STATION_PRODUCT = {"KMIA": "UHMIA", "KMSY": "UHMSY", "KDFW": "UHDFW", "KPHX": "UHPHX",
                   "KMDW": "UHMDW", "KLAX": "UHLAX", "KSFO": "UHSFO", "KSEA": "UHSEA",
                   "KAUS": "UHAUS", "KLAS": "UHLAS"}
# live decision times (UTC) from live_trade.CITY_CONFIG; others use the paper cron
DECISION_UTC = {"KMIA": (15, 30), "KMSY": (14, 58), "KDFW": (17, 32), "KPHX": (14, 52)}
PAPER_MS = {
    "KMIA": "EMOS combined 00Z Miami (rolling 45d)",
    "KMSY": "EMOS combined 00Z New Orleans (rolling 45d)",
    "KDFW": "EMOS combined 00Z Dallas (rolling 45d)",
    "KPHX": "EMOS combined 00Z Phoenix (rolling 45d)",
    "KMDW": "EMOS combined 00Z Chicago (rolling 45d)",
    "KLAX": "EMOS combined 00Z Los Angeles (rolling 45d)",
    "KSFO": "EMOS combined 00Z San Francisco (rolling 45d)",
    "KSEA": "EMOS combined 00Z Seattle (rolling 45d)",
    "KAUS": "EMOS combined 00Z Austin (rolling 45d)",
    "KLAS": "EMOS combined 00Z Las Vegas (rolling 45d)",
}
# ForecastEx/IBKR fee: $0.01 per contract per side, flat (vs Kalshi's 7%*p*(1-p)).
FEE_CENTS_PER_CONTRACT = 1.0


def norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def settlement_map(product: str, days: list[date]) -> dict[str, int]:
    """Settled highs per event date, cached on disk.

    Each daily CSV holds every product, so a cache miss extracts ALL mapped
    products from that one download — otherwise a 10-city run would re-fetch
    the same ~190 files ten times.
    """
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    fetched = set(cache.get("_days", []))
    # Fetch the whole contiguous span, not just this station's model days: a
    # neighbouring day's file can still carry THIS product's settlement, so
    # fetching only per-station days made results depend on run order (KAUS
    # saw 120 events alone vs 142 after other cities had warmed the cache).
    span = [days[0] + timedelta(days=i) for i in range((days[-1] - days[0]).days + 1)]
    missing = [d for d in span if d.isoformat() not in fetched]
    if missing:
        with ForecastExClient() as c:
            for d in missing:
                rows = c.prices(d)
                fetched.add(d.isoformat())
                if not rows:
                    continue
                for prod in STATION_PRODUCT.values():
                    got = implied_settlement_highs(rows, d, prod)
                    if got:
                        bucket = cache.setdefault(prod, {})
                        for ev, high in got.items():
                            bucket[ev.isoformat()] = high
        cache["_days"] = sorted(fetched)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return cache.get(product, {})


def _tstat(sharpe: float | None, ndays: int) -> float | None:
    """Annualized Sharpe flatters a short window. t = Sharpe * sqrt(days/252) is
    the number that says whether the edge is distinguishable from luck."""
    if sharpe is None or ndays < 2:
        return None
    return round(sharpe * math.sqrt(ndays / 252.0), 2)


def _series(vals: list[float], contracts: int) -> dict:
    if len(vals) < 2:
        return {"net_usd": round(sum(vals) / 100, 2), "days": len(vals),
                "sharpe": None, "tstat": None}
    sd = statistics.stdev(vals)
    sharpe = (statistics.mean(vals) / sd) * (252 ** 0.5) if sd > 0 else None
    return {"net_usd": round(sum(vals) / 100, 2), "days": len(vals),
            "sharpe": round(sharpe, 2) if sharpe else None,
            "tstat": _tstat(sharpe, len(vals))}


def _detail(roll_daily: dict, roll_trades: list, vols_by_pick: list,
            contracts: int, results: dict) -> dict | None:
    """Robustness view of the rolling45 variant — the one we would actually trade."""
    if not roll_daily or len(roll_daily) < 4:
        return None
    days = sorted(roll_daily)
    vals = [roll_daily[d] for d in days]
    total = sum(vals)

    # Does it hold in BOTH halves of the held-out window? A decayed edge shows
    # up here long before it shows up in the headline number.
    mid = days[len(days) // 2]
    halves = []
    for label, sel in (("first half", [d for d in days if d < mid]),
                       ("second half", [d for d in days if d >= mid])):
        h = _series([roll_daily[d] for d in sel], contracts)
        h.update({"label": label, "from": sel[0].isoformat(), "to": sel[-1].isoformat()})
        halves.append(h)

    ranked = sorted(vals, reverse=True)
    share = lambda k: round(100 * sum(ranked[:k]) / total, 1) if total else None
    concentration = {
        "top1": share(1), "top3": share(3), "top5": share(5), "top10": share(10),
        "positiveDays": sum(1 for v in vals if v > 0), "days": len(vals),
    }

    # Which entry prices carry the edge? A strategy whose P&L lives in one price
    # band is a much smaller effective sample than its trade count suggests.
    buckets = []
    for lo, hi in ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100)):
        sel = [t for t in roll_trades if lo <= t[1] < hi]
        if not sel:
            continue
        per = [((100 - e) if w else -e) - FEE_CENTS_PER_CONTRACT for _, e, w in sel]
        buckets.append({
            "band": f"{lo}-{hi}¢", "n": len(sel),
            "win_pct": round(100 * sum(1 for _, _, w in sel if w) / len(sel), 1),
            "avg_cents": round(statistics.mean(per), 1),
            "net_usd": round(sum(per) * contracts / 100, 2),
            "share_pct": round(100 * sum(per) * contracts / total, 1) if total else None,
        })

    # If the money days are the thin ones, the capacity headline is a mirage.
    money = set(sorted(roll_daily, key=lambda d: -roll_daily[d])[:10])
    hot = sorted(v for (d, _, _), v in zip(roll_trades, vols_by_pick) if d in money)
    cold = sorted(v for (d, _, _), v in zip(roll_trades, vols_by_pick) if d not in money)
    med = lambda x: x[len(x) // 2] if x else None

    # Where the edge comes from: for most cities the CLI->WU correction IS the
    # edge; where naive already matches rolling45, we do not know the mechanism.
    nn = (results.get("naive") or (0, 0, 0.0))[2]
    rr = (results.get("rolling45") or (0, 0, 0.0))[2]
    if abs(rr - nn) < abs(nn) * 0.15:
        debias = "irrelevant"
    elif rr > nn:
        debias = "adds"
    else:
        debias = "hurts"

    overall = _series(vals, contracts)
    return {"overall": overall, "halves": halves, "concentration": concentration,
            "buckets": buckets, "debias": debias,
            "moneyDayVol": med(hot), "otherDayVol": med(cold)}


def run(station: str, threshold: float, contracts: int) -> None:
    product = STATION_PRODUCT[station]
    hh, mm = DECISION_UTC.get(station, (14, 45))
    conn = get_connection()
    cur = conn.cursor()

    # our model's daily mu/sigma, straight from the production paper log
    cur.execute("""
        SELECT DISTINCT ON (pt.target_date) pt.target_date, pt.emos_mu, pt.emos_sigma
        FROM paper_trades pt JOIN contracts c ON c.ticker = pt.ticker
        WHERE c.station_id=%s AND c.platform='kalshi' AND pt.model_source=%s
          AND pt.emos_mu IS NOT NULL AND pt.emos_sigma IS NOT NULL
        ORDER BY pt.target_date, pt.logged_at
    """, (station, PAPER_MS[station]))
    model = {r[0]: (float(r[1]), float(r[2])) for r in cur.fetchall()}
    if not model:
        print(f"{station}: no EMOS rows in paper_trades — nothing to backtest.")
        return

    days = sorted(model)
    settle = settlement_map(product, days)

    # last ForecastEx tick at/before decision time, per contract per event date
    cur.execute("""
        SELECT c.target_date, c.ticker, c.strike_low, p.last_price, p.snapshot_at
        FROM contracts c JOIN prices p ON p.ticker = c.ticker
        WHERE c.platform='forecastex' AND c.station_id=%s AND p.last_price IS NOT NULL
        ORDER BY c.target_date, c.ticker, p.snapshot_at
    """, (station,))
    last_px: dict[tuple, tuple] = {}
    for td, ticker, strike, px, snap in cur.fetchall():
        cutoff = datetime.combine(td, datetime.min.time(), tzinfo=timezone.utc).replace(hour=hh, minute=mm)
        if snap <= cutoff:
            last_px[(td, ticker)] = (float(strike), int(px), snap)
    conn.close()

    by_date: dict[date, list] = defaultdict(list)
    for (td, ticker), (strike, px, snap) in last_px.items():
        by_date[td].append((ticker, strike, px, snap))

    # out-of-sample debias: fit offset on first half of settled events, apply to second
    common = [d for d in days if d.isoformat() in settle]
    if len(common) < 8:
        print(f"{station}: only {len(common)} settled events — too few to backtest.")
        return
    half = common[len(common) // 2]
    fit = [settle[d.isoformat()] - model[d][0] for d in common if d < half]
    offset = statistics.mean(fit) if fit else 0.0

    # ROLLING offset: the CLI->WU gap is a CONSTANT in shape (offset vs mu has
    # |r|<=0.25, and a linear fit is worse OOS) but NOT stationary — LA drifts
    # -0.89 -> -0.24 between halves while Miami holds -0.82 -> -1.00. A fixed
    # offset fit on old data therefore OVER-corrects the cities that drift
    # toward zero. This uses only settled events strictly BEFORE each decision
    # day (settlement is known next morning), mirroring EMOS's own rolling 45d.
    def rolling_offset(d: date, window: int = 45, min_n: int = 10) -> float | None:
        past = [settle[x.isoformat()] - model[x][0]
                for x in common if x < d and (d - x).days <= window]
        return statistics.mean(past) if len(past) >= min_n else None

    picked_tickers: list[tuple] = []   # (event_date, ticker) actually traded by rolling45
    roll_trades: list[tuple] = []      # (event_date, entry_cents, won) for rolling45
    # Per-pick rows for staleness analysis. A separate list because roll_trades
    # and picked_tickers are destructured as fixed-width tuples further down.
    pick_rows: list[dict] = []
    roll_daily: dict = {}              # event_date -> P&L cents, rolling45 only
    results = {}
    for variant in ("naive", "debiased", "rolling45"):
        pnl = 0.0
        n = wins = no_print = 0
        daily = defaultdict(float)
        for d in common:
            if d < half:
                continue                      # score only the held-out second half
            mu, sigma = model[d]
            if variant == "debiased":
                mu += offset
            elif variant == "rolling45":
                roll = rolling_offset(d)
                if roll is None:
                    continue          # not enough history yet — sit the day out
                mu += roll
            high = settle[d.isoformat()]
            cands = by_date.get(d, [])
            if not cands:
                no_print += 1
                continue
            picks = []
            for ticker, strike, px, snap in cands:
                p_yes = norm_sf((strike + 0.5 - mu) / sigma)   # P(high > strike)
                edge = p_yes - px / 100.0
                if abs(edge) >= threshold and 5 <= px <= 95:
                    picks.append((abs(edge), edge, ticker, strike, px, snap))
            picks.sort(reverse=True)
            for _, edge, ticker, strike, px, snap in picks[:2]:
                entry = px if edge > 0 else 100 - px
                won = (high > strike) if edge > 0 else not (high > strike)
                trade = ((100 - entry) if won else -entry) * contracts
                trade -= FEE_CENTS_PER_CONTRACT * contracts
                pnl += trade
                daily[d] += trade
                n += 1
                wins += 1 if won else 0
                pick_rows.append({"variant": variant, "mu": round(mu, 3),
                                  "sigma": round(sigma, 3), "date": d.isoformat(),
                                  "ticker": ticker, "px": px, "entry": entry,
                                  "won": bool(won), "edge": round(edge, 4),
                                  "strike": strike, "snap": snap.isoformat()})
                if variant == "rolling45":
                    picked_tickers.append((d, ticker))
                    roll_trades.append((d, entry, won))
        if variant == "rolling45":
            roll_daily = dict(daily)
        ds = list(daily.values())
        sharpe = (statistics.mean(ds) / statistics.stdev(ds)) * (252 ** 0.5) if len(ds) >= 2 and statistics.stdev(ds) > 0 else None
        results[variant] = (n, wins, pnl, sharpe, len(daily), no_print)

    print(f"\n=== {station} ({product}) on ForecastEx — OOS half from {half} ===")
    print(f"  settled events: {len(common)}  |  decision {hh:02d}:{mm:02d} UTC  |  "
          f"edge>={threshold:.0%}  |  {contracts} contracts  |  fee 1c/contract")
    print(f"  measured CLI->WU offset (fit on first half): {offset:+.2f} F")
    for variant, (n, wins, pnl, sharpe, ndays, no_print) in results.items():
        if n == 0:
            print(f"  {variant:9} no qualifying trades")
            continue
        sh = f"{sharpe:.2f}" if sharpe is not None else "n/a"
        print(f"  {variant:9} n={n:3d} win={100*wins/n:5.1f}% net=${pnl/100:9.2f} "
              f"avg=${pnl/n/100:7.2f} sharpe={sh:>6} days={ndays:3d} no-print-days={no_print}")

    # --- CAPACITY, measured on the strikes we actually pick -------------------
    # City-wide volume is misleading: it aggregates ~30 strikes, but a signal is
    # ONE contract. Miami's city median is ~2,100/2h yet the median on the strike
    # we trade is only ~390 — a 500-lot would be >100% of that strike's entire
    # window volume. ForecastEx publishes no book, so realized volume is the only
    # observable; it is a LOWER bound on liquidity but the best we have.
    cap = None
    vols_by_pick: list[int] = []
    if picked_tickers:
        conn2 = get_connection()
        vols = []
        with conn2.cursor() as c2:
            for d, ticker in picked_tickers:
                c2.execute("""
                    SELECT coalesce(sum(volume),0) FROM prices
                    WHERE ticker=%s
                      AND snapshot_at <= (%s::date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
                      AND snapshot_at >= (%s::date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
                                          - interval '2 hours'""",
                    (ticker, d, hh, mm, d, hh, mm))
                vols.append(int(c2.fetchone()[0]))
        conn2.close()
        vols_by_pick = list(vols)      # order matches picked_tickers / roll_trades
        vols.sort()
        pick = lambda p: vols[min(len(vols) - 1, int(p * len(vols)))]
        med, p25 = pick(0.50), pick(0.25)
        # Size to the THIN day, not the median, and take a fraction of it: an IOC
        # taker consuming most of a strike's volume moves the price against itself.
        suggested = int(max(0, round(p25 * 0.5 / 25.0) * 25))
        cap = {"picks": len(vols), "medianVol": med, "p25Vol": p25, "p10Vol": pick(0.10),
               "zeroVolPicks": sum(1 for v in vols if v == 0),
               "suggestedContracts": suggested,
               "backtestContracts": contracts,
               "oversizedBy": round(contracts / suggested, 1) if suggested else None}

    return {
        "capacity": cap,
        "pick_rows": pick_rows,
        "detail": _detail(roll_daily, roll_trades, vols_by_pick, contracts, results),
        "station": station, "product": product, "settled_events": len(common),
        "window_start": common[0].isoformat(), "window_end": common[-1].isoformat(),
        "oos_from": half.isoformat(), "decision_utc": f"{hh:02d}:{mm:02d}",
        "threshold": threshold, "contracts": contracts, "offset_f": round(offset, 2),
        "variants": {
            v: {"n": n, "win_pct": round(100 * wins / n, 1) if n else None,
                "net_usd": round(pnl / 100, 2),
                "avg_usd": round(pnl / n / 100, 2) if n else None,
                "sharpe": round(sharpe, 2) if sharpe is not None else None,
                "days": ndays, "no_print_days": no_print}
            for v, (n, wins, pnl, sharpe, ndays, no_print) in results.items()
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station", default="KMIA", choices=sorted(STATION_PRODUCT))
    ap.add_argument("--threshold", type=float, default=0.10)
    ap.add_argument("--contracts", type=int, default=500)
    ap.add_argument("--all", action="store_true", help="every mapped station")
    ap.add_argument("--json", action="store_true",
                    help=f"also write {BACKTEST_JSON} for the dashboard tab")
    a = ap.parse_args()
    out = []
    for st in (sorted(STATION_PRODUCT) if a.all else [a.station]):
        try:
            got = run(st, a.threshold, a.contracts)
            if got:
                out.append(got)
        except Exception as e:
            print(f"{st}: FAILED {type(e).__name__}: {e}")
    if a.json:
        BACKTEST_JSON.parent.mkdir(parents=True, exist_ok=True)
        BACKTEST_JSON.write_text(json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "cities": out}, indent=1))
        print(f"\nwrote {BACKTEST_JSON} ({len(out)} cities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
