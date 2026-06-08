"""Renders the redesigned Live Trading tab as a single HTML document for
Streamlit's components.html() embed.

Loads CSS + React component code from scripts/assets/live_dashboard/ and
injects a Python-built `window.DASH = {...}` payload that mirrors the
data.js mock shape — but with REAL data pulled from Postgres + Kalshi API.

Field shape (must match what live-tab.jsx reads):
  killArmed, asOf, balance,
  today      = { total, realized, unrealized, trades, open },
  cumulative = { total, realizedCum, unrealizedCum, returnPct, winRate, nSettled },
  openOrders = { count, contracts },
  hrrr       = { age, status },
  nextCron   = { label, at, inMin },
  series     = [{d, v}, ...]   # 7-day cumulative P&L points
  cities     = [{name, code, model, status, realized, unrealized, today,
                 orders, budget, contracts, [haltNote],
                 risk: {cumUsed, cumKill, todayUsed, todayKill},
                 edgeThresh, stake}],
  agg        = {cumPnl, cumKill, todayPnl, dailyKill, openContracts, contractCap},
  positions, signals, orders, openOrdersTbl, fills, crons, alerts
"""
from __future__ import annotations

import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any

import streamlit.components.v1 as st_components

from weather_markets.db import get_connection


ASSETS_DIR = Path(__file__).parent / "assets" / "live_dashboard"


def _load_asset(name: str) -> str:
    return (ASSETS_DIR / name).read_text(encoding="utf-8")


def _build_html(dash_payload: dict) -> str:
    """Wrap CSS + React components + DASH payload into a single HTML doc."""
    css = _load_asset("styles.css")
    components_js = _load_asset("components.jsx")
    live_tab_js = _load_asset("live-tab.jsx")
    # The countdown is computed in-browser per second. We pass nextCron.inMin
    # and let the React clock tick from there.
    # CRITICAL: all 3 babel scripts must be ONE script tag, because babel
    # transpiles each <script type="text/babel"> async and ordering isn't
    # guaranteed. Inlining sequentially in a single block guarantees the
    # components-then-live-tab-then-app order React needs.
    return f"""<!doctype html>
<html><head>
<meta charset="utf-8" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{css}
/* Streamlit embed tweak: kill the scroll on the outer body since
   components.html scrolls itself. */
html, body {{ overflow-x: hidden; min-height: 100vh; }}
/* Faint visible message while React loads, so we don't show a blank box */
#root:empty::before {{
  content: "Loading dashboard…";
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
window.DASH_DATA = {json.dumps(dash_payload, default=str)};
</script>
<script type="text/babel" data-presets="env,react">
// ===== components.jsx =====
{components_js}

// ===== live-tab.jsx =====
{live_tab_js}

// ===== App shell =====
const {{ useState: __useState, useEffect: __useEffect }} = React;
function App() {{
  const d = window.DASH_DATA;
  const [tick, setTick] = __useState(0);
  __useEffect(() => {{
    const t = setInterval(() => setTick(x => x + 1), 1000);
    return () => clearInterval(t);
  }}, []);
  function fmt() {{
    if (d.nextCron.inMin === null || d.nextCron.inMin === undefined) return "—";
    const totalSec = Math.max(0, d.nextCron.inMin * 60 - tick);
    const m = Math.floor(totalSec / 60), s = totalSec % 60;
    return m + "m " + String(s).padStart(2, "0") + "s";
  }}
  return <window.LiveTab d={{d}} countdown={{fmt()}} />;
}}
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
</script>
</body></html>
"""


# ----------------------------------------------------------------------
# Data adapters: real DB/API → DASH payload shape expected by the design
# ----------------------------------------------------------------------

def _get_live_data(cfg: dict) -> dict:
    """Build the DASH payload from live sources.

    cfg comes from dashboard's _live_trade_config() — provides CITY_CONFIG,
    AGG_DAILY_LOSS, AGG_CUM_KILL.
    """
    city_config = cfg.get("CITY_CONFIG", {})
    agg_daily_kill = cfg.get("AGG_DAILY_LOSS", 150.0)
    agg_cum_kill = cfg.get("AGG_CUM_KILL", 500.0)

    # Kalshi balance + open orders (best-effort: skip on auth error)
    balance = 0.0
    open_orders_count = 0
    open_orders_contracts = 0
    open_orders_rows = []
    try:
        from weather_markets.kalshi_api import KalshiClient, parse_position, parse_count
        client = KalshiClient()
        bal_resp = client.get_balance()
        balance = float(bal_resp.get("balance_dollars", bal_resp.get("balance", 0) / 100))
        orders_resp = client.get_orders(status="resting", limit=50)
        for o in orders_resp.get("orders", []):
            rem = parse_count(o, "remaining_count_fp")
            open_orders_count += 1
            open_orders_contracts += rem
            open_orders_rows.append({
                "ticker": _short_ticker(o.get("ticker", "")),
                "side": o.get("side", "").upper(),
                "qty": rem,
                "limit": int(round(float(o.get("yes_price_dollars") or o.get("no_price_dollars") or 0) * 100)),
                "age": _fmt_age(o.get("created_time")),
            })
    except Exception:
        pass

    today = date.today()
    with get_connection() as conn, conn.cursor() as cur:
        # Cumulative + today P&L (realized only — from live_trades)
        cur.execute("""
            SELECT
                COALESCE(SUM(realized_pnl_cents) FILTER (WHERE settlement IS NOT NULL), 0) AS cum_realized,
                COALESCE(SUM(realized_pnl_cents) FILTER (WHERE target_date = %s AND settlement IS NOT NULL), 0) AS today_realized,
                COUNT(*) FILTER (WHERE target_date = %s AND fill_status IN ('filled','partial')) AS today_trades,
                COUNT(*) FILTER (WHERE settlement IS NOT NULL) AS n_settled,
                COUNT(*) FILTER (WHERE settlement IS NOT NULL AND realized_pnl_cents > 0) AS n_won
            FROM live_trades
        """, (today, today))
        row = cur.fetchone()
        cum_realized_c, today_realized_c, today_trades, n_settled, n_won = row
        cum_realized = cum_realized_c / 100.0
        today_realized = today_realized_c / 100.0
        win_rate = (n_won / n_settled) if n_settled else 0.0

        # 7-day cumulative P&L series for the chart
        cur.execute("""
            SELECT target_date, COALESCE(SUM(realized_pnl_cents) FILTER (WHERE settlement IS NOT NULL), 0)::float / 100 AS pnl
            FROM live_trades
            WHERE target_date >= %s AND target_date <= %s
            GROUP BY target_date ORDER BY target_date
        """, (today - timedelta(days=7), today))
        daily = dict(cur.fetchall())

        # Per-city realized + today
        per_city_realized = {}
        per_city_today = {}
        cur.execute("""
            SELECT lt.model_source,
                   COALESCE(SUM(realized_pnl_cents) FILTER (WHERE settlement IS NOT NULL), 0)::float / 100,
                   COALESCE(SUM(realized_pnl_cents) FILTER (WHERE target_date = %s AND settlement IS NOT NULL), 0)::float / 100,
                   COUNT(*) FILTER (WHERE target_date = %s) AS today_orders
            FROM live_trades lt
            GROUP BY model_source
        """, (today, today))
        source_stats = {ms: (cum, td, tdo) for ms, cum, td, tdo in cur.fetchall()}

        # Today's filled orders
        cur.execute("""
            SELECT placed_at, ticker, side, count, limit_price_cents, fill_price_cents, fill_status
            FROM live_trades
            WHERE target_date = %s
            ORDER BY placed_at DESC LIMIT 50
        """, (today,))
        today_orders_rows = []
        for placed, ticker, side, cnt, limit, fill, status in cur.fetchall():
            today_orders_rows.append({
                "time": placed.strftime("%H:%M:%S"),
                "ticker": _short_ticker(ticker),
                "side": (side or "").upper(),
                "qty": cnt,
                "limit": limit,
                "fillPx": fill,
                "status": status,
            })

        # Recent 7-day fills
        cur.execute("""
            SELECT target_date, ticker, side, fill_count, fill_price_cents, realized_pnl_cents
            FROM live_trades
            WHERE target_date >= %s AND fill_status IN ('filled','partial')
            ORDER BY placed_at DESC LIMIT 50
        """, (today - timedelta(days=7),))
        fills_rows = []
        for d_, ticker, side, qty, px, pnl in cur.fetchall():
            fills_rows.append({
                "date": d_.strftime("%m-%d"),
                "ticker": _short_ticker(ticker),
                "side": (side or "").upper(),
                "qty": qty,
                "px": px,
                "pnl": (pnl / 100.0) if pnl is not None else None,
            })

    # Build 7-day series (zero-fill missing days)
    series = []
    cum = 0.0
    for i in range(8):
        d = today - timedelta(days=7 - i)
        cum += daily.get(d, 0.0)
        series.append({"d": i, "v": round(cum, 2)})

    # Per-city
    cities_payload = []
    halt_dir = Path(__file__).parent.parent / "halt"
    for city_code, ccfg in city_config.items():
        ms_tag = ccfg.get("live_model_source_tag", "")
        city_realized = 0.0
        city_today = 0.0
        city_today_orders = 0
        # Sum across all sources containing this city (handles model migrations)
        city_name = ccfg.get("city_name", city_code)
        for src, (cum_, td_, tdo) in source_stats.items():
            if city_name in src:
                city_realized += cum_
                city_today += td_
                city_today_orders += int(tdo)
        # Halt status
        halt_file = halt_dir / city_code
        agg_halt = halt_dir / "ALL"
        is_halted = halt_file.exists() or agg_halt.exists()
        halt_note = None
        if is_halted:
            if agg_halt.exists():
                halt_note = f"HALTED — halt/ALL present"
            else:
                halt_note = f"HALTED — halt/{city_code} present"

        sizing_label = "amount" if ccfg.get("sizing_mode") == "amount" else f"{ccfg.get('unit_contracts', '?')}u"
        stake_str = f"${ccfg['amount_dollars']:.0f}/trade" if ccfg.get("sizing_mode") == "amount" else sizing_label

        cities_payload.append({
            "name": city_name,
            "code": city_code,
            "model": ms_tag.replace(" [LIVE]", "").replace(" (rolling 45d)", " · rolling 45d"),
            "status": "halted" if is_halted else "active",
            "realized": round(city_realized, 2),
            "unrealized": 0.0,  # we don't track unrealized in DB yet — set 0
            "today": round(city_today, 2),
            "orders": city_today_orders,
            "budget": int(ccfg.get("daily_loss_limit_dollars", 0)),
            "contracts": ccfg.get("max_open_contracts", 0),
            "haltNote": halt_note,
            "risk": {
                "cumUsed": round(max(0, -city_realized), 2),
                "cumKill": int(ccfg.get("cumulative_kill_dollars", 500)),
                "todayUsed": round(max(0, -city_today), 2),
                "todayKill": int(ccfg.get("daily_loss_limit_dollars", 150)),
            },
            "edgeThresh": f"{int(ccfg.get('edge_threshold', 0.10) * 100)}%",
            "stake": stake_str,
        })

    # Aggregate
    agg = {
        "cumPnl": round(cum_realized, 2),
        "cumKill": int(agg_cum_kill),
        "todayPnl": round(today_realized, 2),
        "dailyKill": int(agg_daily_kill),
        "openContracts": open_orders_contracts,
        "contractCap": sum(c.get("max_open_contracts", 0) for c in city_config.values()),
    }

    # Today's signals (from paper_trades — most recent decision)
    signals_rows = _today_signals(city_config, today)

    # Next cron
    next_cron = _next_cron_info()

    # Cron health
    crons = [
        {"name": "live_trade", "status": "ok", "last": "—", "desc": "decision 14:46 UTC"},
        {"name": "paper_trade", "status": "ok", "last": "—", "desc": "signals logged"},
        {"name": "monitor_fills", "status": "ok", "last": "—", "desc": "every 30 min"},
        {"name": "reconcile", "status": "ok", "last": "—", "desc": "04:00 UTC nightly"},
    ]

    # Alerts: derive from halts + recent activity
    alerts = []
    for city in cities_payload:
        if city.get("haltNote"):
            alerts.append({"lvl": "warn", "ts": "now", "msg": f"{city['name']} {city['haltNote']}"})
    if not alerts:
        alerts.append({"lvl": "ok", "ts": datetime.now().strftime("%H:%M"), "msg": "All systems nominal."})

    # HRRR data freshness
    hrrr = _hrrr_freshness()

    return {
        "id": "live",
        "label": "Live",
        "env": "LIVE",
        "killArmed": cum_realized > -agg_cum_kill,
        "asOf": datetime.now().strftime("today %H:%M ET"),
        "balance": round(balance, 2),
        "today": {
            "total": round(today_realized, 2),
            "realized": round(today_realized, 2),
            "unrealized": 0.0,
            "trades": int(today_trades),
            "open": open_orders_count,
        },
        "cumulative": {
            "total": round(cum_realized, 2),
            "realizedCum": round(cum_realized, 2),
            "unrealizedCum": 0.0,
            "returnPct": round((cum_realized / 3050.0) * 100, 1),  # assumes $3050 starting
            "winRate": round(win_rate, 3),
            "nSettled": int(n_settled),
        },
        "openOrders": {"count": open_orders_count, "contracts": open_orders_contracts},
        "hrrr": hrrr,
        "nextCron": next_cron,
        "series": series,
        "cities": cities_payload,
        "agg": agg,
        "positions": [],  # TODO: pull from Kalshi positions API
        "signals": signals_rows,
        "orders": today_orders_rows,
        "openOrdersTbl": open_orders_rows,
        "fills": fills_rows,
        "crons": crons,
        "alerts": alerts,
    }


def _short_ticker(t: str) -> str:
    """Compress 'KXHIGHCHI-26JUN08-B89.5' -> '…CHI-B89.5' for table display."""
    if not t:
        return ""
    if t.startswith("KXHIGH"):
        parts = t.split("-", 2)
        if len(parts) >= 3:
            return f"…{parts[0][6:]}-{parts[2]}"
    return t


def _fmt_age(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - t).total_seconds()
        m = int(secs / 60)
        if m < 60:
            return f"{m}m"
        return f"{m // 60}h {m % 60}m"
    except Exception:
        return "—"


def _today_signals(city_config: dict, today: date) -> list[dict]:
    """Pull today's paper_trade signals for all live cities."""
    rows = []
    try:
        with get_connection() as conn, conn.cursor() as cur:
            for city_code, ccfg in city_config.items():
                ms = ccfg.get("paper_model_source", "")
                cur.execute("""
                    SELECT ticker, edge, market_mid_prob, model_prob_yes, position, entry_price_cents
                    FROM paper_trades
                    WHERE target_date = %s AND model_source = %s
                    ORDER BY ABS(edge) DESC LIMIT 10
                """, (today, ms))
                for ticker, edge, mkt, mp, pos, entry in cur.fetchall():
                    rows.append({
                        "ticker": _short_ticker(ticker),
                        "bracket": ticker.split("-")[-1] if "-" in ticker else ticker,
                        "modelP": float(mp),
                        "mktP": float(mkt),
                        "edge": float(edge),
                        "side": "YES" if pos == "BUY_YES" else "NO",
                        "placed": "placed" if abs(float(edge)) >= ccfg.get("edge_threshold", 0.10) else "skipped",
                        "fill": "—",
                        "pnl": None,
                    })
    except Exception:
        pass
    return rows


def _next_cron_info() -> dict:
    """Compute next cron fire time. Hardcoded to 14:46 UTC (KORD live)."""
    now = datetime.now(timezone.utc)
    fire = now.replace(hour=14, minute=46, second=0, microsecond=0)
    if fire <= now:
        fire = fire + timedelta(days=1)
    in_min = int((fire - now).total_seconds() / 60)
    return {"label": "live_trade", "at": fire.strftime("%H:%M UTC"), "inMin": in_min}


def _hrrr_freshness() -> dict:
    """Check HRRR forecast freshness for KORD today."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT MAX(init_time) FROM forecasts
                WHERE model='hrrr' AND station_id='KORD'
            """)
            last_init = cur.fetchone()[0]
        if last_init is None:
            return {"age": "—", "status": "warn"}
        age_h = (datetime.now(timezone.utc) - last_init).total_seconds() / 3600
        if age_h < 12:
            return {"age": f"{int(age_h * 60)}m" if age_h < 1 else f"{age_h:.1f}h", "status": "ok"}
        return {"age": f"{int(age_h)}h", "status": "warn"}
    except Exception:
        return {"age": "—", "status": "warn"}


# ----------------------------------------------------------------------
# Streamlit entry point
# ----------------------------------------------------------------------

def render_live_tab(cfg: dict, height: int = 2400):
    """Render the redesigned Live Trading tab into a Streamlit container."""
    payload = _get_live_data(cfg)
    html = _build_html(payload)
    st_components.html(html, height=height, scrolling=True)
