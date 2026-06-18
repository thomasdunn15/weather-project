"""Renders the redesigned Backtest tab as a Streamlit components.html embed.

Pulls live forecast + paper-trade data, runs the P&L sim using the existing
simulate_pnl() helper from dashboard.py, and ships it to the React BacktestTab
prototype as window.BTDATA.

Shape (must match backtest-data.js contract):
  BTDATA[cityCode] = {
    code, city, date,
    members: list[float],            # ensemble member highs
    nMembers, ensMean, ensSpread, emosMu, emosSigma,
    observed: int|None,              # actual high (None if not yet resolved)
    brackets: [{label, lo, hi, modelP, mktP, resolved: "YES"|"NO"|"PEND"}],
    sim: { unit, amount, kelly, scaling: {final, ret, sharpe, maxDD, win, n, filled, avg, pending, total, curve} },
    trades: [{date, bracket, side, modelP, mktP, edge, entry, qty, fill, won, pnl}],
    strat:  [{name, final, ret, sharpe, maxDD, win, brier, n, chosen}],
  }
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime, timezone, timedelta
from pathlib import Path


from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.evaluation import contract_resolved_yes
from weather_markets.stations import get as get_station, all_stations

import sys as _sys
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS)

from dashboard.ttl_cache import ttl_cache



@ttl_cache(300)
def fetch_city_payload(
    city_code: str,
    selected_date: date,
    selected_sizing: str = "amount",
    selected_amount: float = 50.0,
    selected_depth: int = 500,
    selected_edge: float = 0.10,
) -> dict:
    """Build BTDATA[city] from real sources. Falls back gracefully when data missing.

    @ttl_cache(300): 5-min TTL. Repeat (city, date, ...) is instant — only hits
    DB on first call per cache key. Live prices update every 5 min anyway, so
    this matches the natural data cadence.
    """
    try:
        station = get_station(city_code)
        city_name = station.city
    except KeyError:
        city_name = city_code

    init_time = datetime(selected_date.year, selected_date.month, selected_date.day, 0, 0, tzinfo=timezone.utc)
    members: list[float] = []
    ens_mean = ens_spread = emos_mu = emos_sigma = 0.0
    observed: int | None = None
    contracts: list[dict] = []
    paper_rows: list = []
    bracket_market: dict = {}
    settled_trades: list = []

    try:
        with get_connection() as conn:
            # Ensemble members + EMOS fit
            try:
                ensemble_values = compute_combined_daily_highs(
                    init_time, selected_date, conn, station_id=city_code, models=["gefs", "ifs"],
                )
                members = [round(float(v), 1) for v in ensemble_values]
                if len(members) >= 2:
                    ens_mean = round(statistics.mean(members), 2)
                    ens_spread = round(statistics.stdev(members), 2)
                emos = fit_emos_rolling(selected_date, conn, window_days=45, station_id=city_code,
                                        model="combined", init_hour=0)
                if emos is not None and ens_mean:
                    emos_mu = round(emos["a"] + emos["b"] * ens_mean, 2)
                    emos_var = emos["c"] + emos["d"] * (ens_spread ** 2)
                    if emos_var > 0:
                        emos_sigma = round(math.sqrt(emos_var), 2)
            except Exception:
                pass

            # Observed high (None if not yet resolved)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT high_temp_f FROM observations WHERE date=%s AND station_id=%s",
                    (selected_date, city_code),
                )
                row = cur.fetchone()
                if row:
                    observed = int(row[0])

            # Contracts + paper-trade snapshot for this date
            contracts = fetch_contracts_for_date(selected_date, conn, station_id=city_code, series=station.kalshi_series)
            ms_for_city = _paper_source_for(city_code, city_name)
            # Cron decision time for this city — drives the Edge-by-bracket
            # snapshot cutoff. Edge MUST reflect prices AS-OF the cron fire
            # time, never after-the-fact market drift or settlement.
            cron_dt = _city_cron_datetime(city_code, selected_date)
            with conn.cursor() as cur:
                if contracts:
                    tickers = [c["ticker"] for c in contracts]
                    # Pull most-recent snapshot AT OR BEFORE cron time for
                    # EVERY contract. This is the authoritative "Market P at
                    # decision time" and works for halted cities, days where
                    # the cron didn't fire, and tickers the cron didn't log.
                    cur.execute(
                        """SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
                           FROM prices
                           WHERE ticker = ANY(%s) AND snapshot_at <= %s
                           ORDER BY ticker, snapshot_at DESC""",
                        (tickers, cron_dt),
                    )
                    for tk, yb, ya, _ in cur.fetchall():
                        if yb is not None and ya is not None:
                            bracket_market[tk] = (float(yb) + float(ya)) / 200.0
                    # For today specifically: if cron hasn't fired yet (current
                    # time before cron_dt), there's no AT-cron-time snapshot to
                    # use → fall back to latest. Detected here by tickers that
                    # still have no entry after the above query.
                    missing = [c["ticker"] for c in contracts if c["ticker"] not in bracket_market]
                    if missing and selected_date >= datetime.now(timezone.utc).date():
                        cur.execute(
                            """SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                               FROM prices WHERE ticker = ANY(%s)
                               ORDER BY ticker, snapshot_at DESC""",
                            (missing,),
                        )
                        for tk, yb, ya in cur.fetchall():
                            if yb is not None and ya is not None:
                                bracket_market[tk] = (float(yb) + float(ya)) / 200.0

                # Settled paper trades for the trade log + sim.
                # ASCENDING by date — required so the balance chart's x-axis
                # walks chronologically left→right (oldest to newest). The
                # React trade-by-trade table reverses this for display so
                # the user sees newest-on-top.
                cur.execute("""
                    SELECT pt.target_date, pt.ticker, pt.position, pt.entry_price_cents, pt.edge,
                           pt.model_prob_yes, pt.market_mid_prob,
                           pt.market_yes_bid, pt.market_yes_ask,
                           c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
                    FROM paper_trades pt
                    JOIN contracts c ON c.ticker = pt.ticker
                    LEFT JOIN LATERAL (SELECT high_temp_f FROM observations
                      WHERE date = pt.target_date AND station_id = c.station_id LIMIT 1) o ON TRUE
                    WHERE pt.model_source = %s
                      AND pt.target_date <= %s
                      AND pt.target_date >= %s
                    ORDER BY pt.target_date ASC, pt.logged_at ASC
                """, (
                    _paper_source_for(city_code, city_name),
                    selected_date,
                    selected_date - timedelta(days=365),
                ))
                settled_trades = cur.fetchall()
    except Exception:
        pass

    # WALK-FORWARD blend (no lookahead): each trade is scored by a blend fit
    # trained ONLY on settled data before that trade's date. Fitting on the full
    # history and scoring it on that same history (the old behavior) inflated
    # blend/union backtests by ~30-50%. `wf_blends[date]` is the fit to use for
    # trades on that date; None until MIN_N_FIT prior samples exist.
    from weather_markets.blend import walkforward_blends as _wf_blends
    ms = _paper_source_for(city_code, city_name)
    wf_blends = _wf_blends(city_code, city_name, paper_model_source=ms) if station.kalshi_series else {}

    def _blend_for(d) -> "object | None":
        """Blend fit to use for a trade/display on date d: the fit trained on
        data strictly before d. Falls back to the latest fit at/before d."""
        if not wf_blends:
            return None
        f = wf_blends.get(d)
        if f is not None:
            return f
        prior = [bf for dd, bf in wf_blends.items() if dd <= d and bf is not None]
        return prior[-1] if prior else None

    # Blend fit for the SELECTED date's bracket table (also no lookahead).
    blend_fit = _blend_for(selected_date)

    # Build bracket table for the Edge by bracket display
    brackets_payload: list[dict] = []
    if emos_sigma > 0 and contracts:
        try:
            model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)
        except Exception:
            model_probs = {}
        for c in sorted(contracts, key=lambda x: (x.get("strike_low") if x.get("strike_low") is not None else (x.get("strike_high") or 0) - 1000)):
            tk = c["ticker"]
            bt = c.get("bracket_type")
            # Kalshi convention: between [low, high] inclusive (e.g., B78.5 covers 78–79).
            # greater_than: > low → low+1 and above. less_than: < high → high-1 and below.
            if bt == "greater_than":
                label = f"≥{int(c['strike_low']) + 1}°F"
                lo, hi = int(c["strike_low"]), 99
            elif bt == "less_than":
                label = f"≤{int(c['strike_high']) - 1}°F"
                lo, hi = -99, int(c["strike_high"])
            else:
                # Both strikes inclusive — show full range
                if int(c["strike_low"]) == int(c["strike_high"]):
                    label = f"{int(c['strike_low'])}°F"
                else:
                    label = f"{int(c['strike_low'])}–{int(c['strike_high'])}°F"
                lo, hi = int(c["strike_low"]), int(c["strike_high"])
            mp = float(model_probs.get(tk, 0))
            mkt = float(bracket_market.get(tk, 0))
            if observed is not None:
                resolved = "YES" if contract_resolved_yes(observed, c) else "NO"
            else:
                resolved = "PEND"
            bp = blend_fit.predict(mp, mkt) if (blend_fit and mkt > 0) else None
            brackets_payload.append({"label": label, "lo": lo, "hi": hi,
                                     "modelP": round(mp, 3),
                                     "blendP": round(float(bp), 3) if bp is not None else None,
                                     "mktP": round(mkt, 3),
                                     "resolved": resolved})

    # Build trade log + run quick per-sizing sims
    trades_payload: list[dict] = []
    sim_results: dict = {"unit": _empty_sim(), "amount": _empty_sim(), "kelly": _empty_sim(), "scaling": _empty_sim()}
    if settled_trades:
        # Full trade history — passed to JS sim, so include EVERY field needed
        # for re-running the sim client-side. JS recomputes when user changes
        # sizing / edge / depth / amount / bankroll without a Python round-trip.
        for r in settled_trades:
            (td, ticker, pos, entry, edge, mp, mkt, bid, ask, bt, sl, sh, high) = r
            bracket_label = _bracket_short(bt, sl, sh)
            if high is None:
                won = None
                pnl = 0.0
                fill_status = "pending"
            else:
                yes_won = contract_resolved_yes(int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh})
                won = bool(yes_won) if pos == "BUY_YES" else not bool(yes_won)
                pnl_per = (100 - int(entry)) if won else -int(entry)
                pnl = round(pnl_per / 100, 2)
                fill_status = "filled"
            # Blend probability for the YES side, using the WALK-FORWARD fit for
            # THIS trade's date (trained only on prior data — no lookahead). The
            # React-side JS sim flips it for BUY_NO via 1 - blendP when needed.
            _bf = _blend_for(td)
            blend_p_yes = (float(_bf.predict(float(mp), float(mkt)))
                           if _bf and mkt > 0 else None)
            trades_payload.append({
                "date": td.strftime("%Y-%m-%d"),
                "bracket": bracket_label,
                "side": "YES" if pos == "BUY_YES" else "NO",
                "pos": pos,                                  # raw position string for JS Kelly calc
                "modelP": round(float(mp), 4),
                "blendP": round(blend_p_yes, 4) if blend_p_yes is not None else None,
                "mktP": round(float(mkt), 4),
                "edge": round(float(edge), 4),
                "entry": int(entry),
                "marketYesBid": int(bid) if bid is not None else None,
                "marketYesAsk": int(ask) if ask is not None else None,
                "qty": 1,
                "fill": fill_status,
                "won": won,
                "pnl": pnl,
            })
        sim_results = _compute_sims(settled_trades, selected_edge, selected_amount, selected_depth)

    # Strategy comparison (current single-variant only; multi-variant requires more data)
    strat_payload = [
        {"name": "Combined (GEFS+IFS)", "final": sim_results.get(selected_sizing, _empty_sim())["final"],
         "ret": sim_results.get(selected_sizing, _empty_sim())["ret"],
         "sharpe": sim_results.get(selected_sizing, _empty_sim())["sharpe"],
         "maxDD": sim_results.get(selected_sizing, _empty_sim())["maxDD"],
         "win": sim_results.get(selected_sizing, _empty_sim())["win"],
         "brier": 0.20,
         "n": sim_results.get(selected_sizing, _empty_sim())["n"],
         "chosen": True},
    ]

    return {
        "code": city_code,
        "city": city_name,
        "date": selected_date.strftime("%Y-%m-%d"),
        "members": members,
        "nMembers": len(members),
        "ensMean": ens_mean,
        "ensSpread": ens_spread,
        "emosMu": emos_mu,
        "emosSigma": emos_sigma,
        "observed": observed if observed is not None else (int(ens_mean) if ens_mean else 0),
        "brackets": brackets_payload,
        "sim": sim_results,
        "trades": trades_payload,
        "strat": strat_payload,
        "blend": ({
            "alpha": round(blend_fit.alpha, 3),
            "betaModel": round(blend_fit.beta_model, 3),
            "betaMarket": round(blend_fit.beta_market, 3),
            "marketShare": round(blend_fit.market_share(), 2),
            "nTrain": blend_fit.n_train,
        } if blend_fit else None),
    }


def _paper_source_for(city_code: str, city_name: str) -> str:
    """The paper_trades model_source for backtest analysis.

    Defaults to "EMOS combined 00Z {city} (rolling 45d)" (GEFS+IFS only).
    For cities where the LIVE cron uses a different EMOS variant (e.g.,
    KORD uses combined_hrrr with HRRR added), read that from CITY_CONFIG
    so the backtest reflects what live trading actually does.
    """
    try:
        import live_trade
        cfg = live_trade.CITY_CONFIG.get(city_code, {})
        if "paper_model_source" in cfg:
            return cfg["paper_model_source"]
    except Exception:
        pass
    # Default fallback
    if city_code == "KNYC":
        return "EMOS combined 00Z (rolling 45d)"
    return f"EMOS combined 00Z {city_name} (rolling 45d)"


# Backtest decision time (UTC) for cities not in the live CITY_CONFIG. These
# are backtest-only candidate cities (not live-traded); 17:00 UTC ≈ late
# morning local for the western/central US cities, when the daily-high
# contracts are listed and liquid but the market hasn't converged. Must match
# the decision time used when their paper_trades were backfilled.
_BACKTEST_DECISION_UTC = {
    "KPHX": (17, 0), "KLAS": (17, 0), "KSEA": (17, 0),
    "KDFW": (17, 0), "KMSY": (17, 0),
}


def _city_cron_datetime(city_code: str, target_date: date) -> datetime:
    """The UTC datetime the live_trade cron fires for this city on target_date.

    Reads decision_hour/decision_minute from CITY_CONFIG in live_trade.py so
    the Edge-by-bracket panel's Market P is pinned to the precise moment that
    city's strategy makes its trade decision. For backtest-only candidate
    cities (not in CITY_CONFIG) uses _BACKTEST_DECISION_UTC; falls back to
    14:46 UTC (KORD default).
    """
    try:
        import live_trade
        cfg = live_trade.CITY_CONFIG.get(city_code, {})
    except Exception:
        cfg = {}
    if "decision_hour" in cfg:
        hour, minute = cfg["decision_hour"], cfg.get("decision_minute", 46)
    else:
        hour, minute = _BACKTEST_DECISION_UTC.get(city_code, (14, 46))
    return datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=timezone.utc)


def _empty_sim() -> dict:
    return {"final": 1000, "ret": 0.0, "sharpe": 0.0, "maxDD": 0.0, "win": 0.0,
            "n": 0, "filled": 0, "avg": 0.0, "pending": 0, "total": 0, "curve": [1000, 1000]}


def _bracket_short(bt, sl, sh) -> str:
    """Inclusive-inclusive convention: between [low, high] = both bounds win."""
    if bt == "greater_than":
        return f"≥{int(sl) + 1}°F"
    if bt == "less_than":
        return f"≤{int(sh) - 1}°F"
    if int(sl) == int(sh):
        return f"{int(sl)}°F"
    return f"{int(sl)}–{int(sh)}°F"


def _compute_sims(rows: list, edge_filter: float, amount_dollars: float, depth_cap: int) -> dict:
    """Run a minimal P&L simulation for each sizing mode."""
    starting = 1000.0
    out = {}
    for sizing in ("unit", "amount", "kelly", "scaling"):
        balance = starting
        peak = starting
        max_dd = 0.0
        n_filled = 0
        n_pending = 0
        n_won = 0
        n_total = 0
        pnls = []
        curve = [starting]
        for r in rows:
            (td, ticker, pos, entry, edge, mp, mkt, bid, ask, bt, sl, sh, high) = r
            n_total += 1
            if abs(float(edge)) < edge_filter:
                continue
            if high is None:
                n_pending += 1
                continue
            yes_won = contract_resolved_yes(int(high), {"bracket_type": bt, "strike_low": sl, "strike_high": sh})
            won = bool(yes_won) if pos == "BUY_YES" else not bool(yes_won)
            e = int(entry)
            # contracts per sizing
            if sizing == "unit":
                contracts_n = 100
            elif sizing == "amount":
                contracts_n = min(depth_cap, int((amount_dollars * 100) / max(e, 1)))
            elif sizing == "kelly":
                p = float(mp) if pos == "BUY_YES" else (1 - float(mp))
                q = 1 - p
                b = (100 - e) / max(e, 1)
                f = (p * b - q) / max(b, 1e-9)
                f = max(0, min(f * 0.5, 0.05))
                stake_dollars = balance * f
                contracts_n = min(depth_cap, int((stake_dollars * 100) / max(e, 1)))
            else:  # scaling
                contracts_n = min(depth_cap, int((balance * 0.02 * 100) / max(e, 1)))
            if contracts_n < 1:
                continue
            n_filled += 1
            n_won += int(won)
            pnl_per = (100 - e) if won else -e
            trade_pnl = (pnl_per / 100.0) * contracts_n
            pnls.append(trade_pnl)
            balance += trade_pnl
            curve.append(round(balance, 2))
            peak = max(peak, balance)
            dd = (balance - peak) / peak * 100
            max_dd = min(max_dd, dd)
        ret = ((balance - starting) / starting) * 100 if starting else 0
        win = (n_won / n_filled) if n_filled else 0
        # Annualized Sharpe approximation (assume 252 trading days)
        if len(pnls) > 1:
            m = statistics.mean(pnls)
            sd = statistics.stdev(pnls)
            sharpe = (m / sd) * math.sqrt(252) if sd > 0 else 0
        else:
            sharpe = 0
        out[sizing] = {
            "final": round(balance, 2),
            "ret": round(ret, 1),
            "sharpe": round(sharpe, 2),
            "maxDD": round(max_dd, 1),
            "win": round(win, 3),
            "n": n_filled,
            "filled": n_filled,
            "avg": round(statistics.mean(pnls), 2) if pnls else 0,
            "pending": n_pending,
            "total": n_total,
            "curve": curve if len(curve) > 1 else [starting, starting],
        }
    return out



def list_cities() -> list[dict]:
    """Code + label + lat/lon for every Kalshi-series station. Drives both the
    dropdown and the clickable US map in the backtest tab."""
    return [{"code": s.station_id, "label": s.city,
             "lat": s.latitude, "lon": s.longitude}
            for s in all_stations() if s.kalshi_series]
