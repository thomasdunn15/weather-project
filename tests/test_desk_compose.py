"""The Desk composes three payloads it does not own. A field renamed upstream
must fail here, not on a phone screen at a decision time."""
from datetime import datetime, timezone

from dashboard.data_desk import compose

T_EARLY = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)   # before 14:47Z
T_LATE = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)    # after both decisions

LIVE = {
    "live": {"connected": True, "ageMs": 5_000},
    "killArmed": True,
    "balance": 2294.32,
    "openOrders": {"count": 2, "contracts": 1000},
    "alerts": [{"lvl": "warn", "msg": "Miami HALTED — FX_KMIA present: retired venue"}],
    "cities": [
        {"code": "KMIA", "venue": "PM", "status": "active", "realized": 94.38},
        {"code": "KMIA", "venue": "K", "status": "active", "realized": 3151.47,
         "unrealized": 12.5, "today": -316.61, "orders": 3,
         "risk": {"cumUsed": 0, "cumKill": 500, "todayUsed": 0, "todayKill": 150}},
    ],
}
FX = {
    "collector": {"staleMinutes": 4.0},
    "trading": {"available": True, "date": "2026-09-03",
                "cities": [{"code": "KLAX", "name": "Los Angeles", "decisionUtc": "14:45",
                            "state": "trade", "preview": False, "rhUrl": "https://x/",
                            "note": "mu=75", "capacity": 1325, "warning": None,
                            "picks": [{"ticker": "UHLAX_090326_76", "side": "no"}],
                            "ladder": [{"strike": 76}]}],
                "entries": [{"id": 1, "ticker": "UHLAX_090326_76"}]},
}
PM = {"probe": {"halted": False, "halt_text": None, "cumulative_realized_cents": 9438.31,
                "rails": {"contracts_per_signal": 150, "cumulative_kill_usd": -300.0}}}
ORDER = {"placedAt": "2026-09-03T14:47:02+00:00", "ticker": "tc-temp-miahigh-2026-09-03-gte91lt92f",
         "side": "YES", "count": 150.0, "limit": 43, "orderId": "C7RV22V00M9G",
         "filled": 0.0, "fillAvg": None, "settlement": None, "realizedCents": None}


def test_picks_and_entries_pass_through_without_the_ladder():
    d = compose(LIVE, FX, PM, [], now=T_LATE)
    c = d["picks"]["cities"][0]
    assert c["code"] == "KLAX" and c["picks"][0]["ticker"] == "UHLAX_090326_76"
    assert "ladder" not in c, "the Desk does not carry the ladder"
    assert d["entries"] == FX["trading"]["entries"]


def test_kalshi_block_takes_the_K_venue_row_not_the_PM_one():
    k = compose(LIVE, FX, PM, [], now=T_LATE)["kalshi"]
    assert k["realized"] == 3151.47 and k["today"] == -316.61
    assert k["openOrders"] == 2 and k["openContracts"] == 1000
    assert k["cumKill"] == 500 and k["balance"] == 2294.32


def test_polymarket_states():
    assert compose(LIVE, FX, PM, [], now=T_EARLY)["polymarket"]["state"] == "pending"
    assert compose(LIVE, FX, PM, [], now=T_LATE)["polymarket"]["state"] == "none"
    assert compose(LIVE, FX, PM, [ORDER], now=T_LATE)["polymarket"]["state"] == "placed"
    part = {**ORDER, "filled": 60.0}
    assert compose(LIVE, FX, PM, [part], now=T_LATE)["polymarket"]["state"] == "partial"
    full = {**ORDER, "filled": 150.0}
    assert compose(LIVE, FX, PM, [full], now=T_LATE)["polymarket"]["state"] == "filled"
    halted = {"probe": {**PM["probe"], "halted": True, "halt_text": "cum below -300"}}
    assert compose(LIVE, FX, halted, [full], now=T_LATE)["polymarket"]["state"] == "halted"


def test_health_is_ok_when_everything_is_and_ignores_retired_FX_holds():
    h = compose(LIVE, FX, PM, [], now=T_LATE)["health"]
    assert h["level"] == "ok"
    assert all(i["level"] == "ok" for i in h["items"])
    assert not any("FX_" in i["text"] for i in h["items"])


def test_health_worst_wins():
    down = {**LIVE, "live": {"connected": False}}
    assert compose(down, FX, PM, [], now=T_LATE)["health"]["level"] == "bad"
    disarmed = {**LIVE, "killArmed": False}
    assert compose(disarmed, FX, PM, [], now=T_LATE)["health"]["level"] == "bad"
    stale = {**FX, "collector": {"staleMinutes": 45}}
    h = compose(LIVE, stale, PM, [], now=T_LATE)["health"]
    assert h["level"] == "warn" and any("tape" in i["text"] for i in h["items"])
    crit = {**LIVE, "alerts": [{"lvl": "critical", "msg": "KMIA cumulative below kill"}]}
    assert compose(crit, FX, PM, [], now=T_LATE)["health"]["level"] == "bad"


def test_stale_marks_only_matter_with_open_contracts():
    idle = {**LIVE, "live": {"connected": True, "ageMs": 40 * 60_000}, "openOrders": {"count": 0, "contracts": 0}}
    assert compose(idle, FX, PM, [], now=T_LATE)["health"]["level"] == "ok"
    holding = {**idle, "openOrders": {"count": 1, "contracts": 500}}
    assert compose(holding, FX, PM, [], now=T_LATE)["health"]["level"] == "warn"


def test_missing_upstream_pieces_degrade_not_crash():
    d = compose({}, {}, {}, [], now=T_LATE)
    assert d["picks"]["available"] is False and d["entries"] == []
    assert d["kalshi"]["realized"] is None
    assert d["polymarket"]["state"] == "none"
    assert d["health"]["level"] in ("warn", "bad")
