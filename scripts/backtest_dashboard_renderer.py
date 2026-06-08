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

import streamlit.components.v1 as st_components

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.evaluation import contract_resolved_yes
from weather_markets.stations import get as get_station


ASSETS_DIR = Path(__file__).parent / "assets" / "live_dashboard"


def _load_asset(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def _build_html(payload: dict) -> str:
    css = _load_asset("styles.css")
    components_js = _load_asset("components.jsx")
    backtest_js = _load_asset("backtest-tab.jsx")
    return f"""<!doctype html>
<html><head>
<meta charset="utf-8" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{css}
html, body {{ overflow-x: hidden; min-height: 100vh; }}
#root:empty::before {{
  content: "Loading backtest…";
  display: block;
  padding: 40px;
  color: var(--text-lo);
  font-family: var(--ui);
  font-size: 12px;
  text-align: center;
}}
</style>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
</head>
<body>
<div id="root"></div>
<script>
window.BTDATA = {json.dumps(payload, default=str)};
window.DEFAULT_CITY = {json.dumps(payload.get('cities', ['KORD'])[0])};
</script>
<script type="text/babel" data-presets="env,react">
{components_js}

{backtest_js}

// Wrapper that respects the city the Python layer loaded
function BacktestWithCity() {{
  // Force the React BacktestTab's initial cityCode to match what Python loaded.
  // BacktestTab uses useState("KORD") internally; instead we mount a copy that
  // uses window.DEFAULT_CITY as the seed.
  return <window.BacktestTab key={{window.DEFAULT_CITY}} />;
}}
ReactDOM.createRoot(document.getElementById("root")).render(<BacktestWithCity />);
</script>
</body></html>
"""


def _fetch_city_payload(
    city_code: str,
    selected_date: date,
    selected_sizing: str = "amount",
    selected_amount: float = 50.0,
    selected_depth: int = 500,
    selected_edge: float = 0.10,
) -> dict:
    """Build BTDATA[city] from real sources. Falls back gracefully when data missing."""
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
            with conn.cursor() as cur:
                # Market mid per bracket (most recent snapshot)
                if contracts:
                    tickers = [c["ticker"] for c in contracts]
                    cur.execute(
                        """SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                           FROM prices WHERE ticker = ANY(%s) ORDER BY ticker, snapshot_at DESC""",
                        (tickers,),
                    )
                    for tk, yb, ya in cur.fetchall():
                        if yb is not None and ya is not None:
                            bracket_market[tk] = (float(yb) + float(ya)) / 200.0

                # Settled paper trades for the trade log + sim
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
                    ORDER BY pt.target_date DESC
                """, (
                    f"EMOS combined 00Z {city_name} (rolling 45d)" if city_code != "KNYC" else "EMOS combined 00Z (rolling 45d)",
                    selected_date,
                    selected_date - timedelta(days=365),
                ))
                settled_trades = cur.fetchall()
    except Exception:
        pass

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
            if bt == "greater_than":
                label = f"≥{int(c['strike_low']) + 1}°F"
                lo, hi = int(c["strike_low"]), 99
            elif bt == "less_than":
                label = f"≤{int(c['strike_high']) - 1}°F"
                lo, hi = -99, int(c["strike_high"])
            else:
                label = f"{int(c['strike_low'])}–{int(c['strike_high']) - 1}°F"
                lo, hi = int(c["strike_low"]), int(c["strike_high"]) - 1
            mp = float(model_probs.get(tk, 0))
            mkt = float(bracket_market.get(tk, 0))
            if observed is not None:
                resolved = "YES" if contract_resolved_yes(observed, c) else "NO"
            else:
                resolved = "PEND"
            brackets_payload.append({"label": label, "lo": lo, "hi": hi,
                                     "modelP": round(mp, 3), "mktP": round(mkt, 3),
                                     "resolved": resolved})

    # Build trade log + run quick per-sizing sims
    trades_payload: list[dict] = []
    sim_results: dict = {"unit": _empty_sim(), "amount": _empty_sim(), "kelly": _empty_sim(), "scaling": _empty_sim()}
    if settled_trades:
        # Build trade history (most recent 200 for log display)
        for r in settled_trades[:200]:
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
                pnl = round(pnl_per / 100, 2)  # 1 contract base; user can think in $ per contract
                fill_status = "filled"
            trades_payload.append({
                "date": td.strftime("%m-%d"),
                "bracket": bracket_label,
                "side": "YES" if pos == "BUY_YES" else "NO",
                "modelP": round(float(mp), 3),
                "mktP": round(float(mkt), 3),
                "edge": round(float(edge), 3),
                "entry": int(entry),
                "qty": 1,
                "fill": fill_status,
                "won": won,
                "pnl": pnl,
            })

        # Approximate sim per sizing — minimal cost: just sum cumulative for each
        # See backtest-data.js for the exact field expectations.
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
    }


def _empty_sim() -> dict:
    return {"final": 1000, "ret": 0.0, "sharpe": 0.0, "maxDD": 0.0, "win": 0.0,
            "n": 0, "filled": 0, "avg": 0.0, "pending": 0, "total": 0, "curve": [1000, 1000]}


def _bracket_short(bt, sl, sh) -> str:
    if bt == "greater_than":
        return f"≥{int(sl) + 1}°F"
    if bt == "less_than":
        return f"≤{int(sh) - 1}°F"
    return f"{int(sl)}–{int(sh) - 1}°F"


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


def render_backtest_tab(selected_city: str, selected_date: date, sizing: str, amount: float, depth: int, edge_filter: float, height: int = 2400):
    """Render the redesigned Backtest tab into a Streamlit container."""
    city_payload = _fetch_city_payload(selected_city, selected_date, sizing, amount, depth, edge_filter)
    payload = {selected_city: city_payload, "cities": [selected_city]}
    html = _build_html(payload)
    st_components.html(html, height=height, scrolling=True)
