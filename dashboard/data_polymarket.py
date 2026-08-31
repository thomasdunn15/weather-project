"""Polymarket tab payload: live-probe status + 5-city paper tracking.

Read-only: DB + halt-file. Rails constants and the city list are imported from
the trading/logging scripts themselves (importlib, loaded once) so the display
cannot drift from what is actually enforced.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.evaluation import contract_resolved_yes, kalshi_equivalent_bracket

_REPO = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_LIVE = _load_script("live_trade_polymarket")
_PAPER = _load_script("paper_trade_polymarket")

CITY_NAMES = {"KMIA": "Miami", "KNYC": "NYC", "KLAX": "Los Angeles",
              "KSFO": "San Francisco", "KMDW": "Chicago (MDW)"}

# Polymarket account funding. Kept here rather than in account_equity_snapshots,
# which tracks the KALSHI account only (its referral_credit_dollars is Kalshi's
# $14.99, nothing to do with this).
#
# Why it is on screen at all: realized P&L is the trading result, but a promo
# credit absorbs part of a loss, so the two answer different questions. On
# 2026-08-25 realized read -$49.13 while the operator's own cash was down ~$40,
# and the $10 credit was the whole difference. Showing only realized invites
# exactly that confusion.
DEPOSIT_CENTS = 100_000          # operator's own cash
PROMO_CREDIT_CENTS = 1_000       # 2026-08-25: $10 free from Polymarket

# Day-matched replay 2026-06-30..08-11, PM-native brackets @0.25, 1 contract —
# static context row so the forward numbers are read against their prior.
REPLAY_REF = [
    {"city": "Miami", "n": 40, "win": 85, "cents_per_trade": 32.0},
    {"city": "Los Angeles", "n": 43, "win": 74, "cents_per_trade": 28.1},
    {"city": "San Francisco", "n": 23, "win": 74, "cents_per_trade": 22.9},
    {"city": "Chicago (MDW)", "n": 43, "win": 67, "cents_per_trade": 16.2},
    {"city": "NYC", "n": 22, "win": 68, "cents_per_trade": 16.6},
]


def _probe(conn) -> dict:
    halted = _LIVE.HALT_FILE.exists()
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(sum(realized_pnl_cents),0) FROM pm_live_trades")
        cum = float(cur.fetchone()[0])
        cur.execute("""
            SELECT placed_at, target_date, ticker, intent, count, limit_price_cents,
                   fill_count, fill_avg_price_cents, settlement, realized_pnl_cents
            FROM pm_live_trades ORDER BY placed_at DESC LIMIT 20""")
        trades = [{
            "placed_at": r[0].isoformat(), "target_date": r[1].isoformat(),
            "ticker": r[2], "side": "YES" if r[3] == "ORDER_INTENT_BUY_LONG" else "NO",
            "count": float(r[4]), "limit_cents": r[5], "fill_count": float(r[6]),
            "fill_avg_cents": float(r[7]) if r[7] is not None else None,
            "settlement": r[8], "realized_cents": float(r[9]) if r[9] is not None else None,
        } for r in cur.fetchall()]
    # Out-of-pocket = where the operator's OWN cash stands: venue balance minus
    # their own deposits. The promo credit is $10 of someone else's money that
    # sits in the balance whether the book wins or loses, so it is a flat add.
    #
    # An earlier min(PROMO, max(0, -cum)) capped the credit's benefit at the
    # size of the losses, which is right only while the book is underwater and
    # silently understated the account by $10 once it turned positive. The
    # operator's own read confirms the flat form: at cum = -$49.13 they said
    # "I am only down 40 dollars", and -49.13 + 10.00 = -39.13.
    credit_used = float(PROMO_CREDIT_CENTS)
    return {
        "halted": halted,
        "halt_text": _LIVE.HALT_FILE.read_text().strip() if halted else None,
        "cumulative_realized_cents": cum,
        "funding": {
            "deposit_cents": DEPOSIT_CENTS,
            "promo_credit_cents": PROMO_CREDIT_CENTS,
            "credit_used_cents": credit_used,
            "out_of_pocket_cents": cum + credit_used,
        },
        "trades": trades,
        "rails": {
            "contracts_per_signal": _LIVE.CONTRACTS_PER_SIGNAL,
            "max_signals_per_day": _LIVE.MAX_SIGNALS_PER_DAY,
            "edge_threshold": _LIVE.EDGE_THRESHOLD,
            "daily_spend_cap_usd": _LIVE.DAILY_SPEND_CAP_CENTS / 100,
            "cumulative_kill_usd": _LIVE.CUMULATIVE_KILL_CENTS / 100,
        },
    }


def _paper(conn) -> list[dict]:
    cut = date.today() - timedelta(days=14)
    out = []
    for station, ms in _PAPER.STATIONS.items():
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pt.target_date, pt.position, pt.market_yes_bid, pt.market_yes_ask,
                       c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f
                FROM paper_trades pt
                JOIN contracts c ON c.ticker = pt.ticker
                LEFT JOIN observations o ON o.date = pt.target_date AND o.station_id = %s
                WHERE pt.model_source = %s AND pt.target_date >= %s""", (station, ms, cut))
            rows = cur.fetchall()
        n = len(rows)
        settled = wins = 0
        net = 0.0
        last_sig = None
        for td, pos, bid, ask, bt, sl, sh, hf in rows:
            last_sig = max(last_sig, td) if last_sig else td
            if hf is None:
                continue
            buy_yes = pos == "BUY_YES"
            entry = int(ask) if buy_yes else 100 - int(bid)
            if entry <= 0 or entry >= 100:
                continue
            yes = contract_resolved_yes(int(round(hf)),
                                        kalshi_equivalent_bracket("polymarket", bt, sl, sh))
            won = yes if buy_yes else not yes
            p = entry / 100.0
            net += ((100 - entry) if won else -entry) - 6.0 * p * (1 - p)
            settled += 1
            wins += won
        out.append({
            "station": station, "city": CITY_NAMES.get(station, station),
            "signals_14d": n, "last_signal": last_sig.isoformat() if last_sig else None,
            "settled": settled, "wins": wins, "net_cents": round(net, 1),
        })
    return out


def get_polymarket_data() -> dict:
    conn = get_connection()
    try:
        return {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "probe": _probe(conn),
            "paper": _paper(conn),
            "replay": REPLAY_REF,
        }
    finally:
        conn.close()
