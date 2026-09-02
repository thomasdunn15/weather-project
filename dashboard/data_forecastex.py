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
from weather_markets.forecastex import (FEE_CENTS_PER_CONTRACT as FEE_CENTS,
                                        PRODUCT_TO_STATION, RH_CITY_SLUG, rh_url)

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
    """Feed health. Every query here is bounded to RECENTLY LISTED contracts.

    The all-time form of this panel cost 9.7s per call and was the whole reason
    the tab felt broken: `prices` is a 20 GB hypertable, and joining it against
    20k forecastex tickers defeats both chunk exclusion and
    idx_prices_ticker_snapshot, so the planner seq-scans every chunk. Restricting
    to contracts listed in the last 3 days puts it back on the index — 61 ms,
    identical answer (measured 2026-08-31). "Is the collector alive" was always a
    recent-window question. The all-time price-row count was dropped with it: it
    was decorative, and it was the other half of the same scan.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT max(p.snapshot_at) FROM prices p
            WHERE p.ticker IN (SELECT ticker FROM contracts
                               WHERE platform='forecastex'
                                 AND target_date >= CURRENT_DATE - 3)
              AND p.snapshot_at >= now() - interval '3 days'""")
        last_tick = cur.fetchone()[0]
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


# --- Robinhood: today's actionable picks --------------------------------------
# Robinhood Derivatives routes its weather event contracts to ForecastEX, so the
# ladder on robinhood.com IS the ladder this repo already collects from
# forecastex.com — same >X strikes, same Weather Underground settlement. Prices
# were verified tick-for-tick against our own collector on 2026-08-31. That is
# why this module keeps its ForecastEx name while the tab is called Robinhood:
# ForecastEx is the exchange, Robinhood is only the broker we place through.

# Cities offered here. Deliberately NOT every configured city:
#   - KDFW uses the `blend` strategy, whose walk-forward fit takes ~10s cold —
#     far too slow for a web request, and its traded-strike capacity is 0.
#   - Everything else in CITY_CONFIG is `raw` and costs <0.3s.
ROBINHOOD_CITIES = ("KLAX", "KMIA")

# No API exists for Robinhood event contracts (see BROKER below), so the account
# size cannot be read and is stated here. $2,500 as of 2026-08-31.
ROBINHOOD_BANKROLL = 2500.0
# Ruin analysis 2026-08-31: at this bankroll 1,300 contracts/day carries a ~92%
# probability of ruin over a season; 200 is the size that survives the drawdown
# the LAX Sharpe CI [0.90, 8.12] admits. Split evenly across the day's picks,
# mirroring budget_counts()'s even-split choice.
MAX_CONTRACTS_PER_DAY = 200

BROKER = {
    "connected": False,
    "headline": "Balance and positions cannot be linked",
    "detail": ("Robinhood publishes no API for event contracts. The official "
               "programmatic surfaces — the Crypto Trading API and the Agentic "
               "Trading (MCP) endpoint — cover equities, options and crypto "
               "only; prediction markets are roadmap, not shipped. The "
               "community `robin_stocks` wrapper reverse-engineers the private "
               "app API and also has no event-contract support. So there is no "
               "read path for this balance, official or otherwise: the number "
               "below is the figure entered in ROBINHOOD_BANKROLL by hand."),
}


def _latest_book(conn, station: str, target_date) -> dict:
    """Newest Robinhood top-of-book per contract: ticker -> (yb, ya, nb, na, at).

    Separate query from _latest_prices because these are different KINDS of row:
    a trade is an event with the tape's timestamp, a quote is a snapshot with the
    poll's. They live in the same table only because `prices` already had the
    columns; nothing but the poll time links them.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (c.ticker) c.ticker, p.yes_bid, p.yes_ask,
                   p.no_bid, p.no_ask, p.snapshot_at
            FROM contracts c JOIN prices p ON p.ticker = c.ticker
            WHERE c.platform='forecastex' AND c.station_id=%s AND c.target_date=%s
              AND (p.yes_bid IS NOT NULL OR p.yes_ask IS NOT NULL)
            ORDER BY c.ticker, p.snapshot_at DESC""", (station, target_date))
        return {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()}


def tradeable(p_model: float, side: str, ask: int | None) -> float | None:
    """Edge against the price you can ACTUALLY pay, not the last print.

    The strategy prices every signal off `last_price`, and its own docs concede
    the spread is never charged. With a real book that stops being a caveat and
    becomes a number: on 2026-09-02 UHMIA_090226_89 last-traded at 45c against a
    51/59 market, so a "+25% edge" was +11% to anyone actually buying.
    """
    if ask is None:
        return None
    win = p_model if side == "yes" else 1.0 - p_model
    return win - ask / 100.0


def _latest_prices(conn, station: str, target_date) -> dict:
    """Newest print per contract, no decision-time cutoff — for mark-to-market."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (c.ticker) c.ticker, p.last_price, p.snapshot_at
            FROM contracts c JOIN prices p ON p.ticker = c.ticker
            WHERE c.platform='forecastex' AND c.station_id=%s AND c.target_date=%s
              AND p.last_price IS NOT NULL
            ORDER BY c.ticker, p.snapshot_at DESC""", (station, target_date))
        return {t: (int(px), snap) for t, px, snap in cur.fetchall()}


# (station, date) -> (mu, sigma). SAFE TO CACHE FOREVER, and only because both
# inputs are frozen for the day: the 00Z forecast is published and immutable,
# and the rolling EMOS trains on days strictly BEFORE today. Same reasoning as
# live_trade_forecastex.cached_blend. The fit is ~0.85s per city, which is fine
# once and not fine on a 30s poll.
_PREVIEW_CACHE: dict[tuple, tuple | None] = {}


def preview_fit(ptl, station: str, today, init_time, conn):
    key = (station, today)
    if key not in _PREVIEW_CACHE:
        mu, sg, _stats, _why = ptl.emos_mu_sigma(station, today, init_time, conn)
        _PREVIEW_CACHE[key] = None if mu is None else (mu, sg)
    return _PREVIEW_CACHE[key]


def record_entry(conn, payload: dict) -> dict:
    """Freeze one pick as taken. Validates against OUR OWN data, never the body.

    This is a write endpoint reached from a browser, so nothing in `payload` is
    trusted for anything but identifying the row: the contract must exist in
    `contracts` for today, and every number is re-read from the pick the server
    just computed rather than from what the page sent. A page that is a few
    seconds stale would otherwise write a price that was never on the tape.
    """
    ticker = str(payload.get("ticker") or "")
    side = str(payload.get("side") or "")
    if side not in ("yes", "no"):
        raise ValueError(f"side must be yes|no, got {side!r}")

    today = datetime.now(timezone.utc).date()
    with conn.cursor() as cur:
        cur.execute("""SELECT station_id, strike_low FROM contracts
                       WHERE ticker=%s AND platform='forecastex' AND target_date=%s""",
                    (ticker, today))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"no forecastex contract {ticker!r} for {today}")
    station, strike = row[0], float(row[1])

    # Re-derive the pick server-side; the browser only says WHICH one.
    # Capacity MUST come from the same place the tab's payload gets it. Passing
    # [] here recorded 66 contracts for a Miami pick the card showed as 50 —
    # the size cap silently absent from the only record of the position.
    live = _trading(conn, _capacity(_backtest()), with_entries=False)
    city = next((c for c in live["cities"] if c["code"] == station), None)
    pick = next((p for p in (city or {}).get("picks", [])
                 if p["ticker"] == ticker and p["side"] == side), None)
    if pick is None:
        raise ValueError(f"{ticker} {side} is not a current pick — it may have "
                         f"moved out of range since the page rendered")

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO rh_entries (target_date, station_id, fx_contract_id, side,
                strike, contracts, limit_price_cents, market_last_cents,
                model_prob_yes, edge, emos_mu, emos_sigma, provisional, note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (target_date, fx_contract_id, side) DO NOTHING
            RETURNING id""",
            (today, station, ticker, side, strike, pick["contracts"], pick["limit"],
             pick["lastPx"], pick["pModel"], pick["edge"], city["mu"], city["sigma"],
             bool(city["preview"]), (payload.get("note") or None)))
        r = cur.fetchone()
    conn.commit()
    return {"ok": True, "id": r[0] if r else None,
            "duplicate": r is None, "ticker": ticker, "side": side}


def delete_entry(conn, entry_id: int) -> dict:
    """Undo a mis-click. Today only — an old entry is a record, not a draft."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM rh_entries WHERE id=%s AND target_date=%s RETURNING id",
                    (entry_id, datetime.now(timezone.utc).date()))
        r = cur.fetchone()
    conn.commit()
    return {"ok": r is not None, "id": entry_id}


def _entries(conn, today) -> list[dict]:
    """Today's taken positions, newest first, with the CURRENT mark alongside."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.id, e.entered_at, e.station_id, e.fx_contract_id, e.side,
                   e.strike, e.contracts, e.limit_price_cents, e.market_last_cents,
                   e.model_prob_yes, e.edge, e.emos_mu, e.emos_sigma, e.provisional
            FROM rh_entries e WHERE e.target_date=%s ORDER BY e.entered_at DESC""",
            (today,))
        rows = cur.fetchall()
    if not rows:
        return []
    latest = {}
    for st in {r[2] for r in rows}:
        latest.update(_latest_prices(conn, st, today))
    out = []
    for (eid, at, st, tk, side, strike, n, lim, mkt, pm, edge, mu, sg, prov) in rows:
        cur_px, cur_at = latest.get(tk, (None, None))
        cur_entry = None if cur_px is None else (cur_px if side == "yes" else 100 - cur_px)
        # `limit` is already the price of the side taken — signals() derives it
        # from `entry`, which is px for a YES and 100-px for a NO.
        out.append({
            "id": eid, "enteredAt": at.isoformat(), "code": st, "name": CITY_NAMES.get(st, st),
            "ticker": tk, "side": side, "strike": strike, "contracts": n,
            "limit": lim, "lastPx": mkt, "pModel": pm, "edge": edge,
            "mu": mu, "sigma": sg, "provisional": prov,
            "costUsd": round(n * lim / 100.0, 2),
            "currentPx": cur_px, "currentEntry": cur_entry,
            "currentAt": cur_at.isoformat() if cur_at else None,
            "markUsd": None if cur_entry is None else round(n * (cur_entry - lim) / 100.0, 2),
        })
    return out


def pick_state(picks, now: datetime, decision: datetime) -> str:
    """Which KIND of nothing this is — "no trade" is a claim, not a fallback.

    signals() returns None for "could not evaluate" and [] for "evaluated and
    nothing qualified". Collapsing the two told the operator that nothing had
    cleared the edge threshold at 11:41Z, on a morning when the threshold had
    not been applied to anything: today's model does not exist until the paper
    cron fits it at the decision time. Same missing model AFTER that time is the
    opposite reading — a cron that failed.
    """
    if picks is None:
        return "pending" if now < decision else "error"
    return "trade" if picks else "no-trade"


def _trading(conn, capacity: list[dict], with_entries: bool = True) -> dict:
    """Today's picks per city, sized, with the full ladder behind them.

    Picks come from live_trade_forecastex.signals() — the same function the live
    cron calls — so what this tab shows and what the strategy would do cannot
    drift. The ladder is rebuilt from a second load_history() call rather than
    by re-deriving the pick maths here, for the same reason.
    """
    import sys
    sys.path.insert(0, str(_REPO / "scripts"))
    # data/ is gitignored, so a fresh clone has neither the spread table nor the
    # settlement cache and this whole block is unrunnable. Degrade the panel
    # instead of 500-ing the tab — that is exactly how the Ashburn box failed on
    # 2026-08-31, taking the working collector and backtest panels down with it.
    try:
        import live_trade_forecastex as fx
        import paper_trade_log as ptl
        today = datetime.now(timezone.utc).date()
        spreads = {c["station"]: c["median_c"]
                   for c in json.loads(fx.SPREAD_JSON.read_text())["cities"]}
        init_time = datetime(today.year, today.month, today.day, ptl.INIT_HOUR,
                             tzinfo=timezone.utc)
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}: {e}"}
    cap_by_code = {c["code"]: c["suggested"] for c in capacity}

    cities = []
    for station in ROBINHOOD_CITIES:
        cfg = fx.CITY_CONFIG.get(station)
        if not cfg:
            continue
        hh, mm = cfg["decision_utc"]
        row = {
            "code": station, "name": cfg["name"], "product": cfg["product"],
            "decisionUtc": f"{hh:02d}:{mm:02d}",
            "edgeThreshold": cfg["edge_threshold"],
            "rhUrl": rh_url(station, today),
            "capacity": cap_by_code.get(station),
            "spreadCents": spreads.get(station),
            "picks": [], "ladder": [], "note": None, "mu": None, "sigma": None,
            "state": "pending",
            # Miami is ALREADY traded live on Kalshi every day, so this is the
            # same forecast expressed twice — size for that. But it is NOT a
            # pure doubling: the two venues settle on DIFFERENT sources (WU here,
            # NWS CLI on Kalshi) and their Miami P&L correlates only r=+0.29.
            # Measured, splitting was the better risk: 500 a side returned the
            # same $14,880 as 1000 on Kalshi alone, worst day -$820 vs -$1,520,
            # Sharpe 7.77 vs 5.79.
            "warning": ("Miami trades live on Kalshi at 15:30Z too — same "
                        "forecast, sized twice. Not a pure doubling though: "
                        "different settlement source, P&L correlates r=+0.29, "
                        "and the two-venue split measured better than "
                        "concentrating (worst day −$820 vs −$1,520)."
                        if station == "KMIA" else None),
        }
        try:
            picks, note = fx.signals(conn, station, cfg, today, spreads[station])
        except Exception as e:
            row["note"] = f"signal error: {type(e).__name__}: {e}"
            row["state"] = "error"
            cities.append(row)
            continue
        row["note"] = note
        book = _latest_book(conn, station, today)
        decision = datetime(today.year, today.month, today.day, hh, mm,
                            tzinfo=timezone.utc)
        row["state"] = pick_state(picks, datetime.now(timezone.utc), decision)

        # PREVIEW. Before the paper cron runs there is no paper_trades row for
        # today, but everything needed to build one already exists: the 00Z
        # forecast landed this morning and the rolling EMOS trains only on days
        # BEFORE today. So the mu/sigma computed here is the same mu/sigma the
        # 14:45Z cron will write — only the market price moves in between. Run
        # the real signals() against it rather than showing an empty card for
        # the three hours when the operator is deciding whether to be at a desk.
        preview = None
        if row["state"] == "pending":
            fit = preview_fit(ptl, station, today, init_time, conn)
            if fit is not None:
                mu0, sg0 = fit
                try:
                    picks, note = fx.signals(conn, station, cfg, today,
                                             spreads[station], model_today=(mu0, sg0))
                except Exception as e:
                    picks, note = None, f"preview failed: {type(e).__name__}: {e}"
                if picks is not None:
                    preview = (mu0, sg0)
                    row["note"] = note
                    row["state"] = "preview" if picks else "preview-no-trade"
        # Provisional means THE DECISION TIME HAS NOT PASSED, not "we had to
        # synthesize the model". Miami's paper row exists from the 14:45Z cron
        # but its own decision is 15:30Z, so its picks can still change for
        # another 45 minutes — showing them as final would be the same lie in a
        # different place.
        row["preview"] = datetime.now(timezone.utc) < decision
        latest = _latest_prices(conn, station, today)

        # Ladder + mu/sigma: reload rather than re-derive, so the numbers shown
        # are the ones signals() actually used.
        try:
            model, settled, live, _src = fx.load_history(conn, station, cfg, today)
            if preview is not None:
                model = {**model, today: preview}
            mu_only = {d: m[0] for d, m in model.items()}
            off = fx.rolling_offset(today, settled, mu_only)
            if today in model and off is not None:
                mu, sg = model[today]
                mu += off
                row["mu"], row["sigma"], row["offset"] = round(mu, 2), round(sg, 2), round(off, 2)
                picked = {p["ticker"]: p["side"] for p in (picks or [])}
                for ticker, strike, px, snap in sorted(live, key=lambda r: r[1]):
                    pm = fx.prob_above(strike, mu, sg)
                    cur_px, cur_at = latest.get(ticker, (None, None))
                    lyb, lya, _lnb, _lna, _lat = book.get(ticker, (None,) * 5)
                    row["ladder"].append({
                        "bid": lyb, "ask": lya,
                        "ticker": ticker, "strike": strike, "decisionPx": px,
                        "currentPx": cur_px, "pModel": round(pm, 4),
                        "edge": round(pm - px / 100.0, 4),
                        "pick": picked.get(ticker),
                        "currentAt": cur_at.isoformat() if cur_at else None,
                    })
        except Exception as e:                  # ladder is a nicety, not the point
            row["ladderError"] = f"{type(e).__name__}: {e}"

        n = len(picks or [])
        for p in (picks or []):
            # Even dollar split of the day's contract budget, then bounded by the
            # traded-strike capacity the backtest measured for this city.
            count = MAX_CONTRACTS_PER_DAY // n if n else 0
            if row["capacity"]:
                count = min(count, row["capacity"])
            cur_px, cur_at = latest.get(p["ticker"], (None, None))
            yb, ya, nb, na, book_at = book.get(p["ticker"], (None, None, None, None, None))
            bid, ask = (yb, ya) if p["side"] == "yes" else (nb, na)
            # `entry` is what we pay for the side we take; on a NO that is
            # 100 - last. Mark it the same way so drift is comparable.
            cur_entry = None if cur_px is None else (cur_px if p["side"] == "yes" else 100 - cur_px)
            row["picks"].append({
                "ticker": p["ticker"], "strike": p["strike"], "side": p["side"],
                "lastPx": p["last_px"], "entry": p["entry"], "limit": p["limit"],
                "edge": round(p["edge"], 4), "pModel": round(p["p_model"], 4),
                "snapshotAt": p["snapshot_at"].isoformat() if p["snapshot_at"] else None,
                "contracts": count,
                # Priced at the LIMIT, not `entry`. entry is what crossing costs;
                # the card prints a limit next to these, and a resting order that
                # fills, fills there. Using entry overstated the cost by half a
                # spread against the number printed beside it.
                "costUsd": round(count * p["limit"] / 100.0, 2),
                "maxLossUsd": round(count * p["limit"] / 100.0, 2),
                "maxWinUsd": round(count * (100 - p["limit"]) / 100.0, 2)
                             - round(count * FEE_CENTS / 100.0, 2),
                "feeUsd": round(count * FEE_CENTS / 100.0, 2),
                "currentPx": cur_px, "currentEntry": cur_entry,
                "currentAt": cur_at.isoformat() if cur_at else None,
                "drift": None if cur_entry is None else cur_entry - p["entry"],
                # Robinhood's book for the side being bought.
                "bid": bid, "ask": ask,
                "bookAt": book_at.isoformat() if book_at else None,
                "askEdge": tradeable(p["p_model"], p["side"], ask),
                "askCostUsd": None if ask is None else round(count * ask / 100.0, 2),
            })
        cities.append(row)

    taken = {(e["ticker"], e["side"]) for e in _entries(conn, today)} if with_entries else set()
    for row in cities:
        for p in row["picks"]:
            p["taken"] = (p["ticker"], p["side"]) in taken

    return {"available": True, "date": today.isoformat(),
            "entries": _entries(conn, today) if with_entries else [],
            "bankroll": ROBINHOOD_BANKROLL, "maxContracts": MAX_CONTRACTS_PER_DAY,
            "feeCents": FEE_CENTS, "cities": cities,
            # From the Robinhood event page, 2026-08-31.
            "tradingHours": "24 hours a day, except Wednesday 3:00-3:15 AM ET",
            "webTradable": False}


def get_forecastex_data() -> dict:
    conn = get_connection()
    try:
        bt = _backtest()
        cap = _capacity(bt) if bt.get("available") else []
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "collector": _collector(conn),
            "capacity": cap,
            "backtest": bt,
            "basis": BASIS_NOTE,
            "trading": _trading(conn, cap),
            "broker": BROKER,
        }
    finally:
        conn.close()
