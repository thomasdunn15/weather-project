"""Desk — the five things the operator acts on, composed from payloads that
already exist. No new queries except today's Polymarket orders, which the
Polymarket tab's payload does not carry an order id for.

    1. today's Robinhood picks, with the book price actually payable
    2. taken positions and their mark
    3. did the Polymarket order place, and did it fill
    4. Kalshi Miami today
    5. one line of health

compose() is pure — three payload dicts and one list of rows in, one dict out —
so a renamed field upstream fails tests/test_desk_compose.py rather than a
phone screen. The route in app.py does the wiring.
"""
from __future__ import annotations

from datetime import datetime, timezone

PM_DECISION_UTC = "14:47"     # scripts/live_trade_polymarket.py cron
K_DECISION_UTC = "15:30"      # scripts/live_trade.py --city KMIA cron


def pm_today_orders(conn, today) -> list[dict]:
    """Today's Polymarket live orders straight from the table: the tab payload
    omits pm_order_id, and 'placed' vs 'never sent' is the whole question."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT placed_at, ticker, intent, count, limit_price_cents, pm_order_id,
                   fill_count, fill_avg_price_cents, settlement, realized_pnl_cents
            FROM pm_live_trades WHERE target_date=%s ORDER BY placed_at""", (today,))
        rows = cur.fetchall()
    return [{"placedAt": r[0].isoformat(), "ticker": r[1],
             "side": "YES" if "LONG" in (r[2] or "") else "NO",
             "count": float(r[3]), "limit": r[4], "orderId": r[5],
             "filled": float(r[6] or 0), "fillAvg": r[7],
             "settlement": r[8], "realizedCents": r[9]} for r in rows]


def _before(hhmm: str, now: datetime) -> bool:
    h, m = (int(x) for x in hhmm.split(":"))
    return (now.hour, now.minute) < (h, m)


def _pm_block(pm: dict, orders: list[dict], now: datetime) -> dict:
    probe = pm.get("probe") or {}
    rails = probe.get("rails") or {}
    cum = (probe.get("cumulative_realized_cents") or 0) / 100.0
    if probe.get("halted"):
        state = "halted"
    elif orders:
        filled = sum(o["filled"] for o in orders)
        wanted = sum(o["count"] for o in orders)
        state = "filled" if filled >= wanted - 1e-9 else "partial" if filled > 0 else "placed"
    else:
        state = "pending" if _before(PM_DECISION_UTC, now) else "none"
    return {"state": state, "orders": orders, "decisionUtc": PM_DECISION_UTC,
            "haltText": probe.get("halt_text"),
            "cumulativeUsd": round(cum, 2),
            "killUsd": rails.get("cumulative_kill_usd"),
            "contractsPerSignal": rails.get("contracts_per_signal")}


def _kalshi_block(live: dict) -> dict:
    mia = next((c for c in live.get("cities") or []
                if c.get("code") == "KMIA" and (c.get("venue") or "K") == "K"), None) or {}
    risk = mia.get("risk") or {}
    oo = live.get("openOrders") or {}
    return {"status": mia.get("status"), "haltNote": mia.get("haltNote"),
            "realized": mia.get("realized"), "unrealized": mia.get("unrealized"),
            "today": mia.get("today"), "ordersToday": mia.get("orders"),
            "openOrders": oo.get("count"), "openContracts": oo.get("contracts"),
            "balance": live.get("balance"), "decisionUtc": K_DECISION_UTC,
            "cumUsed": risk.get("cumUsed"), "cumKill": risk.get("cumKill"),
            "todayUsed": risk.get("todayUsed"), "todayKill": risk.get("todayKill")}


def _health(live: dict, fx: dict, pm: dict, kalshi: dict, pmb: dict) -> dict:
    """Worst thing wins. FX_* halt alerts are filtered: ForecastEx-via-IBKR was
    retired on 2026-08-31 and its holds are history, not a warning."""
    items: list[dict] = []
    feed = live.get("live") or {}
    if not feed.get("connected"):
        items.append({"level": "bad", "text": "Kalshi feed down"})
    elif (feed.get("ageMs") or 0) > 15 * 60_000 and (kalshi.get("openContracts") or 0) > 0:
        items.append({"level": "warn", "text": f"marks {int(feed['ageMs'] / 60_000)}m stale"})
    else:
        items.append({"level": "ok", "text": "feed live"})
    if not live.get("killArmed", True):
        items.append({"level": "bad", "text": "kill switch DISARMED"})
    if kalshi.get("status") and kalshi["status"] != "active":
        items.append({"level": "warn", "text": f"Miami {kalshi['status']}"})
    if pmb["state"] == "halted":
        items.append({"level": "bad", "text": "Polymarket halted"})
    col = (fx.get("collector") or {})
    if col.get("staleMinutes") is None or col["staleMinutes"] > 30:
        items.append({"level": "warn", "text": "ForecastEx tape stale"})
    for a in live.get("alerts") or []:
        if "FX_" in (a.get("msg") or ""):
            continue
        items.append({"level": "bad" if a.get("lvl") == "critical" else "warn",
                      "text": (a.get("msg") or "").split("\n")[0][:80]})
    rank = {"ok": 0, "warn": 1, "bad": 2}
    level = max((i["level"] for i in items), key=rank.get, default="ok")
    if level == "ok":
        items = [{"level": "ok", "text": "feed live"},
                 {"level": "ok", "text": "nothing halted"},
                 {"level": "ok", "text": "kill switches armed"}]
    return {"level": level, "items": items}


def compose(live: dict, fx: dict, pm: dict, pm_orders: list[dict],
            now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tr = fx.get("trading") or {}
    cities = [{k: c.get(k) for k in ("code", "name", "decisionUtc", "state", "preview",
                                     "rhUrl", "note", "capacity", "picks", "warning")}
              for c in tr.get("cities") or []]
    kalshi = _kalshi_block(live)
    pmb = _pm_block(pm, pm_orders, now)
    return {
        "asOf": now.isoformat(timespec="seconds"),
        "health": _health(live, fx, pm, kalshi, pmb),
        "picks": {"available": tr.get("available", False), "date": tr.get("date"),
                  "error": tr.get("error"), "cities": cities},
        "entries": tr.get("entries") or [],
        "polymarket": pmb,
        "kalshi": kalshi,
    }
