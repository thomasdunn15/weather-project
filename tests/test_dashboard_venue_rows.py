"""Ticker/bracket rendering for the multi-venue live tables.

Covers the only real branching added for the Kalshi + Polymarket + ForecastEx
union: the per-venue ticker shapes. The SQL union itself is exercised by the
live payload smoke test in test_stray_dashboard_check.py.
"""
from dashboard.data_live import _bracket_label, _short_ticker


def test_bracket_label():
    # gteXltY is an INCLUSIVE pair on Polymarket (92 or 93), not half-open.
    assert _bracket_label("gte92lt93f") == "92–93"
    assert _bracket_label("gte104f") == "≥104"
    assert _bracket_label("lt61f") == "<61"
    assert _bracket_label("B89.5") == "B89.5"      # Kalshi suffix passes through


def test_short_ticker_per_venue():
    assert _short_ticker("KXHIGHCHI-26JUN08-B89.5") == "…CHI-B89.5"
    assert _short_ticker("tc-temp-miahigh-2026-08-24-gte92lt93f") == "…MIA-92–93"
    assert _short_ticker("tc-temp-miahigh-2026-08-24-lt90f") == "…MIA-<90"
    assert _short_ticker("UHMIA_082426_90") == "…MIA->90"
    assert _short_ticker("") == ""
    assert _short_ticker("SOMETHING-ELSE") == "SOMETHING-ELSE"


def test_venue_city_cards_match_their_traders():
    """The PM/FX cards must read their dials from the trading scripts, not from
    numbers restated in the dashboard — a drifting card is a lying kill switch."""
    import sys
    sys.path.insert(0, "scripts")
    import live_trade_forecastex as fx
    from dashboard.data_live import _venue_city_cards
    from dashboard.data_polymarket import _LIVE as pm

    cards = {(c["venue"], c["code"]): c for c in _venue_city_cards({})}
    assert set(cards) == {("PM", pm.STATION)} | {("FX", c) for c in fx.CITY_CONFIG}

    p = cards[("PM", pm.STATION)]
    assert p["risk"]["cumKill"] == int(abs(pm.CUMULATIVE_KILL_CENTS) / 100)
    assert p["risk"]["todayKill"] == int(pm.DAILY_SPEND_CAP_CENTS / 100)
    assert p["risk"]["todayLabel"] == "Today spend"   # a SPEND cap, not a loss limit
    assert p["edgeThresh"] == f"{int(pm.EDGE_THRESHOLD * 100)}%"

    for code, cfg in fx.CITY_CONFIG.items():
        c = cards[("FX", code)]
        assert c["risk"]["cumKill"] == int(fx.CUMULATIVE_KILL_DOLLARS)
        assert c["risk"]["todayKill"] == int(cfg["daily_loss_limit_dollars"])
        assert c["edgeThresh"] == f"{int(cfg['edge_threshold'] * 100)}%"


def test_retired_kalshi_cities_get_no_card():
    from dashboard.data_live import _live_trade_config
    cfg = _live_trade_config()["CITY_CONFIG"]
    retired = [k for k, c in cfg.items() if not c.get("is_active", True)]
    assert retired, "expected some retired cities in live_trade.CITY_CONFIG"

    from dashboard.data_live import get_live_data
    carded = {(c["venue"], c["code"]) for c in get_live_data(_live_trade_config())["cities"]}
    assert not [k for k in retired if ("K", k) in carded]


def _payload():
    from dashboard.data_live import get_live_data, _live_trade_config
    return get_live_data(_live_trade_config())


def test_unrealized_tracks_live_positions_not_cached_recon():
    """Unrealized must be marked off the live positions, NOT copied from
    _kalshi_reconciliation — that call is cached 60s, so taking its number froze
    this column for a minute at a time while the positions table ticked live."""
    d = _payload()
    live_unreal = round(sum(p["unreal"] for p in d["positions"]), 2)
    t, c = d["today"], d["cumulative"]
    assert t["unrealized"] == live_unreal
    assert c["unrealizedCum"] == live_unreal
    # totals must be built from the same unrealized they display
    assert round(t["total"], 2) == round(t["realized"] + live_unreal, 2)
    assert round(c["total"], 2) == round(c["realizedCum"] + live_unreal, 2)


def test_city_card_unrealized_matches_its_positions():
    d = _payload()
    per_city = {}
    for p in d["positions"]:
        per_city[p["city"]] = per_city.get(p["city"], 0.0) + p["unreal"]
    for c in d["cities"]:
        if c["venue"] == "K":
            assert c["unrealized"] == round(per_city.get(c["code"], 0.0), 2), c["code"]


def test_venue_balances_degrade_per_venue():
    """One unreachable venue must not blank the panel or fail the poll."""
    from dashboard.data_live import _venue_balances
    b = _venue_balances(100.0, 25.0)
    assert {v["venue"] for v in b["venues"]} == {"K", "PM", "FX"}
    k = next(v for v in b["venues"] if v["venue"] == "K")
    assert (k["cash"], k["positions"], k["total"]) == (100.0, 25.0, 125.0)
    for v in b["venues"]:
        assert v["total"] is not None or v["error"], f"{v['venue']} silently blank"
    # the total may omit an unreachable venue — `complete` is what says so
    assert b["complete"] == all(v["total"] is not None for v in b["venues"])
