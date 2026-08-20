"""ForecastEx tab payload: collector health + basis diagnostics + backtests.

Read-only. Two sources, deliberately split by cost:
  - LIVE DB   — collector freshness, contract/tick counts, per-city liquidity.
                Cheap, always current.
  - ARTIFACT  — data/forecastex_backtest.json, written by
                `scripts/analysis/forecastex_backtest.py --all --json`.
                The backtest downloads settlement ladders, so it must NEVER run
                inside a web request; the tab reads the last generated result
                and shows its age.

The station->product map is imported from weather_markets.forecastex so the tab
cannot drift from what the ingester actually collects.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.forecastex import PRODUCT_TO_STATION

_REPO = Path(__file__).resolve().parents[1]
BACKTEST_JSON = _REPO / "data" / "forecastex_backtest.json"

CITY_NAMES = {"KMIA": "Miami", "KMSY": "New Orleans", "KDFW": "Dallas",
              "KPHX": "Phoenix", "KMDW": "Chicago (MDW)", "KLAX": "Los Angeles",
              "KSFO": "San Francisco", "KSEA": "Seattle", "KAUS": "Austin",
              "KLAS": "Las Vegas"}
STATION_PRODUCT = {v: k for k, v in PRODUCT_TO_STATION.items()}

# Decision times used by the backtest (live CITY_CONFIG where one exists).
DECISION_UTC = {"KMIA": (15, 30), "KMSY": (14, 58), "KDFW": (17, 32), "KPHX": (14, 52)}


def _collector(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT max(p.snapshot_at), count(*)
            FROM prices p JOIN contracts c ON c.ticker = p.ticker
            WHERE c.platform = 'forecastex'""")
        last_tick, rows = cur.fetchone()
        cur.execute("""
            SELECT count(DISTINCT ticker), min(target_date), max(target_date)
            FROM contracts WHERE platform = 'forecastex'""")
        n_contracts, first_day, last_day = cur.fetchone()
        cur.execute("""
            SELECT count(*) FROM prices p JOIN contracts c ON c.ticker = p.ticker
            WHERE c.platform='forecastex' AND p.snapshot_at >= now() - interval '24 hours'""")
        ticks_24h = cur.fetchone()[0]
    stale_min = None
    if last_tick:
        stale_min = round((datetime.now(timezone.utc) - last_tick).total_seconds() / 60, 1)
    return {
        "lastTickAt": last_tick.isoformat() if last_tick else None,
        "staleMinutes": stale_min,
        "priceRows": int(rows or 0),
        "contracts": int(n_contracts or 0),
        "ticks24h": int(ticks_24h or 0),
        "firstDay": first_day.isoformat() if first_day else None,
        "lastDay": last_day.isoformat() if last_day else None,
        "cities": len(PRODUCT_TO_STATION),
    }


def _capacity(backtest: dict) -> list[dict]:
    """Per-STRIKE capacity on the contracts the strategy actually picks.

    An earlier version of this panel reported CITY-WIDE volume and was
    materially misleading: Miami's city median is ~2,100 contracts per 2h
    window, but that aggregates ~30 strikes. A signal is ONE strike, and the
    median volume on the strike we actually trade is ~240 — so the 500-lot the
    backtest assumes is ~10x too large for Miami, while LA (median ~4,400 on the
    traded strike) is genuinely deep. Numbers come from the backtest artifact,
    which knows which contracts were picked.
    """
    out = []
    for c in backtest.get("cities", []):
        cap = c.get("capacity")
        if not cap:
            continue
        med = cap.get("medianVol") or 0
        sug = cap.get("suggestedContracts") or 0
        out.append({
            "code": c["station"], "name": CITY_NAMES.get(c["station"], c["station"]),
            "product": c["product"], "decisionUtc": c.get("decision_utc", "–"),
            "picks": cap.get("picks", 0), "medianVol": med,
            "p25Vol": cap.get("p25Vol", 0), "p10Vol": cap.get("p10Vol", 0),
            "zeroVolPicks": cap.get("zeroVolPicks", 0),
            "suggested": sug,
            "backtestContracts": cap.get("backtestContracts"),
            "oversizedBy": cap.get("oversizedBy"),
        })
    out.sort(key=lambda r: -r["suggested"])
    return out


def _backtest() -> dict:
    if not BACKTEST_JSON.exists():
        return {"available": False, "note":
                "run: uv run python scripts/analysis/forecastex_backtest.py --all --json"}
    raw = json.loads(BACKTEST_JSON.read_text())
    gen = raw.get("generated_at")
    age_h = None
    if gen:
        try:
            age_h = round((datetime.now(timezone.utc)
                           - datetime.fromisoformat(gen)).total_seconds() / 3600, 1)
        except ValueError:
            pass
    cities = []
    for c in raw.get("cities", []):
        c = dict(c)
        c["name"] = CITY_NAMES.get(c["station"], c["station"])
        best = c.get("variants", {}).get("rolling45") or {}
        c["sortKey"] = best.get("net_usd") if best.get("net_usd") is not None else -1e9
        cities.append(c)
    cities.sort(key=lambda c: -c["sortKey"])
    return {"available": True, "generatedAt": gen, "ageHours": age_h, "cities": cities}


# The finding that gates every ForecastEx number — surfaced in the UI so nobody
# reads the backtest without it.
BASIS_NOTE = {
    "headline": "ForecastEx settles on Weather Underground, not NWS CLI",
    "detail": ("Kalshi and Polymarket both settle Miami on the NWS Climatological "
               "Report; ForecastEx uses Weather Underground for the same KMIA "
               "station. Over 63 settled Miami events the FX high was NEVER above "
               "our CLI high (41% equal, 46% one lower, 13% two lower). Scoring FX "
               "against our observations invents edge — the backtest below instead "
               "recovers FX's own settled value from the strike ladder."),
    "offsets": [
        {"code": "KSFO", "offset": -2.43}, {"code": "KAUS", "offset": -1.51},
        {"code": "KPHX", "offset": -0.95}, {"code": "KLAX", "offset": -0.89},
        {"code": "KMIA", "offset": -0.82}, {"code": "KDFW", "offset": -0.73},
        {"code": "KSEA", "offset": -0.65}, {"code": "KLAS", "offset": -0.61},
        {"code": "KMSY", "offset": +0.09},
    ],
    "correlation": ("Because the settlement source differs, Kalshi and ForecastEx "
                    "Miami P&L correlate only r=+0.29 (same direction 71% of days). "
                    "500 on each venue returned the same $14,880 as 1000 on Kalshi "
                    "alone, but with worst-day -$820 vs -$1,520 and Sharpe 7.77 vs 5.79."),
}


def get_forecastex_data() -> dict:
    conn = get_connection()
    try:
        bt = _backtest()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "collector": _collector(conn),
            "capacity": _capacity(bt) if bt.get("available") else [],
            "backtest": bt,
            "basis": BASIS_NOTE,
        }
    finally:
        conn.close()
