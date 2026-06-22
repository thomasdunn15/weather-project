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


from weather_markets.db import get_connection

import sys as _sys
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS)



# Kalshi series prefix → display city, for the "Other Cities" rollup sublabel.
SERIES_CITY = {
    "KXHIGHLAX": "LA", "KXHIGHTSEA": "Seattle", "KXHIGHNY": "New York",
    "KXHIGHAUS": "Austin", "KXHIGHDEN": "Denver", "KXHIGHTDAL": "Dallas",
    "KXHIGHTLV": "Las Vegas", "KXHIGHTNOLA": "New Orleans", "KXHIGHTPHX": "Phoenix",
}

# Cities deployed with capital — the dashboard's returnPct + reconciliation base.
STARTING_CAPITAL = 3050.0

# Verified non-trade credits Kalshi posted to the account outside of trading
# (2026-06-21 audit): a $14.99 friend-referral incentive. Deposits ($3,050) +
# realized trading P&L + this credit reconcile to account equity to the cent.
KALSHI_NON_TRADE_CREDITS = 14.99


# ----------------------------------------------------------------------
# Data adapters: real DB/API → DASH payload shape expected by the design
# ----------------------------------------------------------------------

def get_live_data(cfg: dict) -> dict:
    """Build the DASH payload from live sources.

    cfg comes from dashboard's _live_trade_config() — provides CITY_CONFIG,
    AGG_DAILY_LOSS, AGG_CUM_KILL.
    """
    city_config = cfg.get("CITY_CONFIG", {})
    agg_daily_kill = cfg.get("AGG_DAILY_LOSS", 150.0)
    agg_cum_kill = cfg.get("AGG_CUM_KILL", 500.0)

    # Live WS marks (cent-accurate top-of-book for held tickers). Empty/degraded
    # snapshot → mark-to-market falls back to the DB prices snapshot transparently.
    try:
        from dashboard.kalshi_ws import live_snapshot
        live = live_snapshot()
    except Exception:
        live = {"connected": False, "marks": {}, "age_ms": None}
    live_marks = live.get("marks", {})

    # Kalshi balance + open orders (best-effort: skip on auth error)
    balance = 0.0
    kalshi_portfolio_value = None   # Kalshi's authoritative mark of ALL open positions
    open_orders_count = 0
    open_orders_contracts = 0
    open_orders_collateral = 0.0   # cash locked in resting orders (qty × limit)
    open_orders_rows = []
    try:
        from weather_markets.kalshi_api import KalshiClient, parse_position, parse_count
        client = KalshiClient()
        bal_resp = client.get_balance()
        balance = float(bal_resp.get("balance_dollars", bal_resp.get("balance", 0) / 100))
        if "portfolio_value" in bal_resp:
            # cents → dollars; covers bot + manual positions across all markets
            kalshi_portfolio_value = float(bal_resp.get("portfolio_value") or 0) / 100.0
        orders_resp = client.get_orders(status="resting", limit=50)
        for o in orders_resp.get("orders", []):
            rem = parse_count(o, "remaining_count_fp")
            limit_cents = int(round(float(o.get("yes_price_dollars") or o.get("no_price_dollars") or 0) * 100))
            open_orders_count += 1
            open_orders_contracts += rem
            open_orders_collateral += rem * limit_cents / 100.0
            open_orders_rows.append({
                "ticker": _short_ticker(o.get("ticker", "")),
                "side": o.get("side", "").upper(),
                "qty": rem,
                "limit": limit_cents,
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

        # "Other Cities" bucket: every Kalshi series EXCEPT Chicago/Miami rolled
        # into one card. Aggregates by ticker series prefix (robust vs the
        # model_source matching used for the two live cities) so manually-traded
        # / reconciled markets (LA, Seattle, New York, …) surface on the dashboard.
        cur.execute("""
            SELECT COALESCE(SUM(realized_pnl_cents) FILTER (WHERE settlement IS NOT NULL), 0)::float / 100,
                   COALESCE(SUM(realized_pnl_cents) FILTER (WHERE target_date = %s AND settlement IS NOT NULL), 0)::float / 100,
                   COUNT(*) FILTER (WHERE settlement IS NOT NULL),
                   ARRAY_AGG(DISTINCT split_part(ticker, '-', 1)) FILTER (WHERE settlement IS NOT NULL)
            FROM live_trades
            WHERE split_part(ticker, '-', 1) NOT IN ('KXHIGHCHI', 'KXHIGHMIA')
        """, (today,))
        oc_realized, oc_today_realized, oc_n_settled, oc_series = cur.fetchone()

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

        # Recent 7-day fills — include partial_resting so today's open partials show
        cur.execute("""
            SELECT target_date, ticker, side, fill_count, fill_price_cents, realized_pnl_cents
            FROM live_trades
            WHERE target_date >= %s
              AND fill_status IN ('filled','partial','partial_resting')
              AND fill_count > 0
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

    # Open positions (filled + partial_resting trades for today, marked to
    # market). Used by both the per-city cards AND the bottom Positions panel.
    # Must be computed BEFORE cities_payload since cities use the per-city
    # rollup for the unrealized column.
    positions_rows = _open_positions(today, live_marks=live_marks)

    # Per-city: aggregate position-level unrealized into per-city totals.
    per_city_unreal = {}
    for p in positions_rows:
        per_city_unreal[p["city"]] = per_city_unreal.get(p["city"], 0) + p["unreal"]

    # "Other Cities" card: everything that isn't Chicago (KORD) or Miami (KMIA).
    # Unrealized = open-position marks for non-CHI/MIA stations (0 when flat).
    oc_unreal = round(sum(p["unreal"] for p in positions_rows
                          if p["city"] not in ("KORD", "KMIA")), 2)
    other_cities = None
    if (oc_n_settled or 0) > 0 or oc_unreal:
        labels = ", ".join(SERIES_CITY.get(s, (s or "").replace("KXHIGH", ""))
                           for s in sorted(oc_series or []))
        other_cities = {
            "name": "Other Cities",
            "code": f"{len(oc_series or [])} series",
            "model": "manual · reconciled",
            "sub": labels,
            "realized": round(oc_realized, 2),
            "unrealized": oc_unreal,
            "today": round(oc_today_realized + oc_unreal, 2),
            "n": int(oc_n_settled or 0),
        }

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
        city_unrealized = round(per_city_unreal.get(city_code, 0.0), 2)
        # Halt status — three layers: explicit is_active=False in config,
        # halt file present, or aggregate halt
        halt_file = halt_dir / city_code
        agg_halt = halt_dir / "ALL"
        is_config_halted = ccfg.get("is_active", True) is False
        is_halted = is_config_halted or halt_file.exists() or agg_halt.exists()
        halt_note = None
        if is_halted:
            if agg_halt.exists():
                halt_note = f"HALTED — halt/ALL present"
            elif halt_file.exists():
                halt_note = f"HALTED — halt/{city_code} present"
            elif is_config_halted:
                halt_note = f"HALTED — cron disabled in live_trade.py CITY_CONFIG"

        sizing_label = "amount" if ccfg.get("sizing_mode") == "amount" else f"{ccfg.get('unit_contracts', '?')}u"
        stake_str = f"${ccfg['amount_dollars']:.0f}/trade" if ccfg.get("sizing_mode") == "amount" else sizing_label

        cities_payload.append({
            "name": city_name,
            "code": city_code,
            "model": ms_tag.replace(" [LIVE]", "").replace(" (rolling 45d)", " · rolling 45d"),
            "status": "halted" if is_halted else "active",
            "realized": round(city_realized, 2),
            "unrealized": city_unrealized,
            "today": round(city_today + city_unrealized, 2),
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

    # (positions_rows already computed earlier — needed by per-city loop.)

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

    # Mark-to-market unrealized PnL across all open positions today.
    # _open_positions uses the latest bid-side snapshot for the mark.
    today_unrealized = sum(p["unreal"] for p in positions_rows)
    n_open_contracts = sum(p["qty"] for p in positions_rows)

    # Account portfolio value. PREFER Kalshi's authoritative portfolio_value
    # (get_balance) — it marks EVERY open position, including manual trades made
    # outside the bot (e.g. cities the cron doesn't run). Computing it from
    # live_trades alone undercounts the real account whenever you hold positions
    # the bot didn't place. Fall back to the bot-position sum only if Kalshi
    # didn't return the field.
    bot_portfolio_value = 0.0
    for p in positions_rows:
        if p["side"] == "YES":
            # mark = yes_bid → position close value = qty × yes_bid / 100
            bot_portfolio_value += p["qty"] * p["mark"] / 100.0
        else:
            # mark stored is yes_ask (YES-eq mark); NO close value = qty × (100 - yes_ask) / 100
            bot_portfolio_value += p["qty"] * (100 - p["mark"]) / 100.0
    portfolio_value = round(kalshi_portfolio_value if kalshi_portfolio_value is not None
                            else bot_portfolio_value, 2)
    total_account_value = round(balance + portfolio_value, 2)

    # Balance reconciliation (verified 2026-06-21 against Kalshi, account flat):
    #   $3,050 deposits + settled trading P&L + $14.99 referral = account equity.
    # `reconciledEquity` is that flat-state identity; `balance` is live equity
    # (cash + open-position marks) and differs intraday by whatever capital is
    # currently deployed in open positions / resting orders. The gap is live
    # exposure, not an error — a *persistent* gap when flat flags untracked P&L.
    reconcile = {
        "deposits": STARTING_CAPITAL,
        "realized": round(cum_realized, 2),
        "credit": KALSHI_NON_TRADE_CREDITS,
        "reconciledEquity": round(STARTING_CAPITAL + cum_realized
                                  + KALSHI_NON_TRADE_CREDITS, 2),
        "balance": total_account_value,
        "deployed": round(portfolio_value + open_orders_collateral, 2),
    }

    return {
        "id": "live",
        "label": "Live",
        "env": "LIVE",
        "killArmed": cum_realized > -agg_cum_kill,
        "asOf": datetime.now().strftime("today %H:%M ET"),
        "live": {
            "connected": bool(live.get("connected")),
            "ageMs": live.get("age_ms"),
            "marks": len(live_marks),
            "source": "websocket" if live.get("connected") else "rest",
        },
        "balance": total_account_value,         # NOW total = cash + portfolio
        "cashBalance": round(balance, 2),       # cash component (free / settled)
        "portfolioValue": portfolio_value,      # mark-to-market position value
        "today": {
            "total": round(today_realized + today_unrealized, 2),
            "realized": round(today_realized, 2),
            "unrealized": round(today_unrealized, 2),
            "trades": int(today_trades),
            "open": n_open_contracts,
        },
        "cumulative": {
            "total": round(cum_realized + today_unrealized, 2),
            "realizedCum": round(cum_realized, 2),
            "unrealizedCum": round(today_unrealized, 2),
            "returnPct": round(((cum_realized + today_unrealized) / 3050.0) * 100, 1),
            "winRate": round(win_rate, 3),
            "nSettled": int(n_settled),
        },
        "openOrders": {"count": open_orders_count, "contracts": open_orders_contracts},
        "hrrr": hrrr,
        "nextCron": next_cron,
        "series": series,
        "cities": cities_payload,
        "otherCities": other_cities,
        "reconcile": reconcile,
        "agg": agg,
        "positions": positions_rows,
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


def _vwap_entry_yes(fills: list[dict], side: str) -> int | None:
    """Actual average ENTRY price in YES-equivalent cents, from Kalshi fills for
    one (ticker, side). Net of any partial closes (buys − sells on the held
    side). Returns None if no net opening volume. This reflects real fills, so it
    updates as you cross for better prices — unlike the bot's stored limit."""
    price_key = "yes_price_dollars" if side == "yes" else "no_price_dollars"
    net_c = 0.0
    net_cost = 0.0
    for f in fills:
        if f.get("side") != side:
            continue
        cnt = float(f.get("count_fp", f.get("count", 0)) or 0)
        price = float(f.get(price_key, 0) or 0)
        sgn = 1.0 if f.get("action") == "buy" else -1.0
        net_c += sgn * cnt
        net_cost += sgn * cnt * price
    if net_c <= 0:
        return None
    vwap_side = (net_cost / net_c) * 100.0          # cents on the side held
    return int(round(vwap_side if side == "yes" else 100.0 - vwap_side))


def _open_positions(today: date, live_marks: dict | None = None) -> list[dict]:
    """Open positions sourced LIVE from the Kalshi API (authoritative): every
    held market — bot AND manual trades in cities the cron never runs — with the
    real fill-VWAP entry, not the bot's limit price. Marks to market via the WS
    feed, falling back to the DB price snapshot. Bracket/city metadata comes from
    the `contracts` table. Falls back to the live_trades view if Kalshi is
    unreachable. Returns {ticker, city, bracket, side, qty, avg, mark, unreal,
    unrealPct, live}."""
    live_marks = live_marks or {}
    try:
        from weather_markets.kalshi_api import KalshiClient
        client = KalshiClient()
        try:
            pos_resp = client.get_positions()
            held = []
            for p in pos_resp.get("market_positions", []):
                qty_signed = int(round(float(p.get("position_fp", p.get("position", 0)) or 0)))
                if qty_signed != 0:
                    held.append((p["ticker"], qty_signed))
            if not held:
                return []
            fills_by: dict = {}
            for f in client.get_fills(limit=200).get("fills", []):
                fills_by.setdefault(f.get("ticker"), []).append(f)
        finally:
            client.close()

        tickers = [t for t, _ in held]
        meta: dict = {}
        db_marks: dict = {}
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT ticker, station_id, bracket_type, strike_low, strike_high
                           FROM contracts WHERE ticker = ANY(%s)""", (tickers,))
            for tk, st, bt, sl, sh in cur.fetchall():
                meta[tk] = (st, bt, sl, sh)
            cur.execute("""SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                           FROM prices WHERE ticker = ANY(%s)
                           ORDER BY ticker, snapshot_at DESC""", (tickers,))
            for tk, yb, ya in cur.fetchall():
                if yb is not None and ya is not None:
                    db_marks[tk] = (int(yb), int(ya))

        rows = []
        for ticker, qty_signed in held:
            side = "yes" if qty_signed > 0 else "no"
            qty = abs(qty_signed)
            avg_yes = _vwap_entry_yes(fills_by.get(ticker, []), side)
            live_used = ticker in live_marks
            if live_used:
                yb, ya, _ts = live_marks[ticker]
                mark = (int(yb), int(ya))
            else:
                mark = db_marks.get(ticker)
            unreal_cents = 0
            unreal_pct = 0
            display_mark_yes_eq = avg_yes or 0
            if avg_yes is not None and mark is not None:
                yes_bid, yes_ask = mark
                if side == "yes":
                    per_contract = yes_bid - avg_yes
                    cost_basis = avg_yes
                    display_mark_yes_eq = yes_bid
                else:
                    per_contract = avg_yes - yes_ask
                    cost_basis = 100 - avg_yes
                    display_mark_yes_eq = yes_ask
                unreal_cents = per_contract * qty
                unreal_pct = (per_contract / cost_basis * 100) if cost_basis else 0
            st, bt, sl, sh = meta.get(ticker, (ticker.split("-")[0], "", None, None))
            if bt == "greater_than" and sl is not None:
                bracket_lbl = f"≥{int(sl)+1}°F"
            elif bt == "less_than" and sh is not None:
                bracket_lbl = f"≤{int(sh)-1}°F"
            elif sl is not None and sh is not None:
                bracket_lbl = f"{int(sl)}–{int(sh)}°F" if int(sl) != int(sh) else f"{int(sl)}°F"
            else:
                bracket_lbl = ticker.split("-")[-1]
            rows.append({
                "ticker": _short_ticker(ticker),
                "city": st,
                "bracket": bracket_lbl,
                "side": side.upper(),
                "qty": qty,
                "avg": avg_yes if avg_yes is not None else 0,
                "mark": int(display_mark_yes_eq),
                "unreal": round(unreal_cents / 100.0, 2),
                "unrealPct": round(unreal_pct, 1),
                "live": live_used,
            })
        rows.sort(key=lambda r: r["ticker"])
        return rows
    except Exception:
        # Kalshi unreachable → fall back to the bot's DB view of open positions.
        return _open_positions_from_db(today, live_marks=live_marks)


def _open_positions_from_db(today: date, live_marks: dict | None = None) -> list[dict]:
    """Fallback: open positions = filled or partial_resting trades for today that
    haven't settled yet (bot only). Marks to market using the live WS feed when
    available, else the latest DB price snapshot.
    Aggregates multiple orders on the same (ticker, side) into one position
    (weighted-average entry price).
    Returns list of {ticker, city, bracket, side, qty, avg, mark, unreal, unrealPct, live}.

    live_marks: optional {ticker: (yes_bid_cents, yes_ask_cents, ts)} from the
    Kalshi WebSocket service. When present for a ticker it OVERRIDES the DB
    snapshot — the DB `prices` table is a 5-min cron that freezes after a market
    closes, so the WS mark is both fresher and cent-accurate.
    """
    rows = []
    live_marks = live_marks or {}
    try:
        with get_connection() as conn, conn.cursor() as cur:
            # Aggregate by (ticker, side): SUM fill_count, weighted avg fill_price
            cur.execute("""
                SELECT lt.ticker, lt.side,
                       SUM(lt.fill_count)::int AS total_qty,
                       (SUM(lt.fill_count::numeric * lt.fill_price_cents) / NULLIF(SUM(lt.fill_count), 0))::int AS avg_fill_cents,
                       c.station_id, c.bracket_type, c.strike_low, c.strike_high
                FROM live_trades lt
                JOIN contracts c ON c.ticker = lt.ticker
                WHERE lt.target_date = %s
                  AND lt.fill_status IN ('filled','partial','partial_resting')
                  AND lt.fill_count IS NOT NULL AND lt.fill_count > 0
                  AND lt.settlement IS NULL
                GROUP BY lt.ticker, lt.side, c.station_id, c.bracket_type, c.strike_low, c.strike_high
                ORDER BY lt.ticker""", (today,))
            trade_rows = cur.fetchall()

            # Latest market snapshot per ticker for mark-to-market.
            # We store BID and ASK separately because closing a position requires
            # CROSSING the spread:
            #   YES position: close by SELLING YES → hit YES bid (lower price)
            #   NO position:  close by SELLING NO  → hit NO bid = (100 − YES ask)
            # Using yes-mid overstates value on wide-spread illiquid books.
            tickers = list({r[0] for r in trade_rows})
            marks: dict = {}   # ticker -> (yes_bid, yes_ask) in cents
            if tickers:
                cur.execute("""
                    SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                    FROM prices WHERE ticker = ANY(%s)
                    ORDER BY ticker, snapshot_at DESC""", (tickers,))
                for tk, yb, ya in cur.fetchall():
                    if yb is not None and ya is not None:
                        marks[tk] = (int(yb), int(ya))

        # Overlay LIVE WS marks (cent-accurate, never frozen) over the DB snapshot.
        live_used = set()
        for tk, (yb, ya, _ts) in live_marks.items():
            marks[tk] = (int(yb), int(ya))
            live_used.add(tk)

        for ticker, side, qty, fill_px_yes_eq, station_id, bt, sl, sh in trade_rows:
            qty = int(qty)
            avg_yes = int(fill_px_yes_eq) if fill_px_yes_eq is not None else None
            mark = marks.get(ticker)
            # PnL per contract (in cents, YES-eq) — conservative "close it now"
            # mark using the side-appropriate bid.
            unreal_cents = 0
            unreal_pct = 0
            display_mark_yes_eq = 0
            if avg_yes is not None and mark is not None:
                yes_bid, yes_ask = mark
                if side == "yes":
                    # Close by SELLING YES at yes_bid
                    per_contract = yes_bid - avg_yes
                    cost_basis = avg_yes
                    display_mark_yes_eq = yes_bid
                else:
                    # Close by SELLING NO. NO bid = 100 − YES ask.
                    # avg_yes is YES-eq cost (= 100 − NO entry). So NO entry cost
                    # was (100 − avg_yes). Sell NO at NO bid = (100 − YES ask).
                    # Profit per contract = (100 − yes_ask) − (100 − avg_yes)
                    #                     = avg_yes − yes_ask
                    per_contract = avg_yes - yes_ask
                    cost_basis = 100 - avg_yes
                    # Display mark in YES-eq for consistency
                    display_mark_yes_eq = yes_ask
                unreal_cents = per_contract * qty
                unreal_pct = (per_contract / cost_basis * 100) if cost_basis else 0
            else:
                # Fallback display when no live mark
                display_mark_yes_eq = avg_yes if avg_yes is not None else 0
            # Bracket label (short)
            if bt == "greater_than":
                bracket_lbl = f"≥{int(sl)+1}°F"
            elif bt == "less_than":
                bracket_lbl = f"≤{int(sh)-1}°F"
            else:
                bracket_lbl = f"{int(sl)}–{int(sh)}°F" if int(sl) != int(sh) else f"{int(sl)}°F"
            rows.append({
                "ticker": _short_ticker(ticker),
                "city": station_id,
                "bracket": bracket_lbl,
                "side": side.upper(),
                "qty": qty,
                "avg": avg_yes if avg_yes is not None else 0,
                "mark": int(display_mark_yes_eq),
                "unreal": round(unreal_cents / 100.0, 2),
                "unrealPct": round(unreal_pct, 1),
                "live": ticker in live_used,
            })
    except Exception:
        pass
    return rows


def _today_signals(city_config: dict, today: date) -> list[dict]:
    """Pull today's paper_trade signals for the LIVE cities only.

    Skips cities where is_active=False (e.g., Miami) so the dashboard
    doesn't surface paper signals for halted markets.
    """
    rows = []
    try:
        with get_connection() as conn, conn.cursor() as cur:
            for city_code, ccfg in city_config.items():
                if not ccfg.get("is_active", True):
                    continue   # halted city — skip its paper signals
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



def _live_trade_config() -> dict:
    """CITY_CONFIG + aggregate risk limits from live_trade.py, kept in sync with
    the cron. scripts/ is on sys.path via the import-time bootstrap above."""
    import live_trade as _lt
    return {
        "CITY_CONFIG": _lt.CITY_CONFIG,
        "AGG_DAILY_LOSS": _lt.AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS,
        "AGG_CUM_KILL": _lt.AGGREGATE_CUMULATIVE_KILL_DOLLARS,
    }
