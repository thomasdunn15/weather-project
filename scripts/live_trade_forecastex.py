"""ForecastEx (IBKR) live trader — deliberately a PROBE, not a P&L play.

Miami's ForecastEx depth supports ~50 contracts, so even a perfect year is worth
a few hundred dollars. The reason to run this is the one number no backtest and
no spread estimator can produce: whether our orders actually fill when POSTED
rather than crossed. That single fact decides whether ForecastEx is worth
scaling at all, because the strategy's significance depends entirely on it:

    execution           KMIA t    KLAX t    KDFW t
    always post           3.77      3.27      4.09
    half the spread       2.81      2.66      3.54
    always cross          1.84      2.03      2.98

So this posts by default. An unfilled order is a RESULT here, not a failure.

Configs come from scripts/analysis/forecastex_variants.py, scored net of each
city's measured spread. Signal maths is imported from weather_markets.forecastex
so this and the backtest cannot drift apart.

  uv run python scripts/live_trade_forecastex.py                 # dry run, all cities
  uv run python scripts/live_trade_forecastex.py --city KMIA --live
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from weather_markets.db import get_connection
from weather_markets.forecastex import (FEE_CENTS_PER_CONTRACT, PRODUCT_TO_STATION,
                                        blend_prob, fit_blend, prob_above,
                                        rolling_offset)
from weather_markets.ibkr import IBKRClient, IBKRError

_REPO = Path(__file__).resolve().parent.parent
SETTLE_CACHE = _REPO / "data" / "forecastex_settlements.json"
SPREAD_JSON = _REPO / "data" / "forecastex_spread.json"
HALT_DIR = _REPO / "halt"
STATION_PRODUCT = {v: k for k, v in PRODUCT_TO_STATION.items()}

# Validated 2026-08-20 on the held-out half, net of measured spread. Each city's
# entry is the config that won ITS sweep, so treat these as forward-test
# candidates rather than settled truth — they are the best of ~120 draws each.
CITY_CONFIG = {
    "KMIA": {
        "name": "Miami", "product": "UHMIA", "model_city": "Miami",
        "strategy": "raw",          # blend adds nothing here; union == raw exactly
        "edge_threshold": 0.10,     # 0.15 sheds more edge than it saves (t 1.84 -> lower)
        "min_entry_cents": 10,      # a fixed ~8c spread is fatal to cheap contracts
        "max_picks": 3,
        "contracts": 25,            # probe size; measured depth supports ~50
        "decision_utc": (15, 30),
        "daily_loss_limit_dollars": 60.0,
    },
    "KDFW": {
        "name": "Dallas", "product": "UHDFW", "model_city": "Dallas",
        "strategy": "blend",        # Dallas is the one city where blend wins
        "edge_threshold": 0.15,
        "min_entry_cents": 0,
        "max_picks": 2,
        "contracts": 25,
        "decision_utc": (17, 32),
        "daily_loss_limit_dollars": 60.0,
    },
}
CUMULATIVE_KILL_DOLLARS = 200.0     # whole-probe stop; this is not a P&L play


def halted(city: str) -> str | None:
    for f in (HALT_DIR / "ALL", HALT_DIR / city, HALT_DIR / f"FX_{city}"):
        if f.exists():
            return f"{f.name} present: {f.read_text().strip()[:120]}"
    return None


def load_history(conn, station: str, cfg: dict, today: date):
    """Model mu/sigma per day, ForecastEx settled highs, and today's live prints.

    Returns (model, settled, today_contracts). today_contracts carries the last
    print at or before the decision time — ForecastEx publishes no book, so the
    last trade is the only price signal available.
    """
    hh, mm = cfg["decision_utc"]
    src = f"EMOS combined 00Z {cfg['model_city']} (rolling 45d)"
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (pt.target_date) pt.target_date, pt.emos_mu, pt.emos_sigma
            FROM paper_trades pt JOIN contracts c ON c.ticker=pt.ticker
            WHERE c.station_id=%s AND c.platform='kalshi' AND pt.model_source=%s
              AND pt.emos_mu IS NOT NULL ORDER BY pt.target_date, pt.logged_at""",
            (station, src))
        model = {r[0]: (float(r[1]), float(r[2])) for r in cur.fetchall()}
        cur.execute("""SELECT DISTINCT ON (c.ticker) c.ticker, c.strike_low, p.last_price
            FROM contracts c JOIN prices p ON p.ticker=c.ticker
            WHERE c.platform='forecastex' AND c.station_id=%s AND c.target_date=%s
              AND p.last_price IS NOT NULL
              AND p.snapshot_at <= (%s::date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
            ORDER BY c.ticker, p.snapshot_at DESC""",
            (station, today, today, hh, mm))
        live = [(t, float(s), int(px)) for t, s, px in cur.fetchall()]
    settled = {date.fromisoformat(k): v for k, v
               in json.loads(SETTLE_CACHE.read_text()).get(cfg["product"], {}).items()}
    return model, settled, live, src


def build_blend_history(model, settled, conn, station, cfg, before: date):
    """Walk-forward blend history: (p_model, p_market, won) from settled days only."""
    hh, mm = cfg["decision_utc"]
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (c.ticker) c.target_date, c.strike_low, p.last_price
            FROM contracts c JOIN prices p ON p.ticker=c.ticker
            WHERE c.platform='forecastex' AND c.station_id=%s AND c.target_date < %s
              AND p.last_price IS NOT NULL
              AND p.snapshot_at <= (c.target_date + make_time(%s,%s,0)) AT TIME ZONE 'UTC'
            ORDER BY c.ticker, p.snapshot_at DESC""", (station, before, hh, mm))
        rows = cur.fetchall()
    mu_only = {d: m[0] for d, m in model.items()}
    hist = []
    for td, strike, px in rows:
        if td not in model or td not in settled or not 5 <= px <= 95:
            continue
        off = rolling_offset(td, settled, mu_only)
        if off is None:
            continue
        mu, sg = model[td]
        hist.append((prob_above(float(strike), mu + off, sg), int(px) / 100.0,
                     settled[td] > float(strike)))
    return hist


def signals(conn, station: str, cfg: dict, today: date, spread_c: float):
    model, settled, live, src = load_history(conn, station, cfg, today)
    if today not in model:
        return None, f"no EMOS row for {today} (model source {src!r}) — paper cron not run?"
    if not live:
        return None, "no ForecastEx prints at or before the decision time"
    mu_only = {d: m[0] for d, m in model.items()}
    off = rolling_offset(today, settled, mu_only)
    if off is None:
        return None, "not enough settled ForecastEx history for the rolling debias"

    mu, sg = model[today]
    mu += off
    fit = None
    if cfg["strategy"] in ("blend", "union"):
        fit = fit_blend(build_blend_history(model, settled, conn, station, cfg, today))
        if fit is None and cfg["strategy"] == "blend":
            return None, "blend configured but history too thin to fit (<60 obs)"

    picks = []
    for ticker, strike, px in live:
        if not 5 <= px <= 95:
            continue
        p_model = prob_above(strike, mu, sg)
        edges = []
        if cfg["strategy"] in ("raw", "union"):
            edges.append(p_model - px / 100.0)
        if fit is not None:
            edges.append(blend_prob(fit, p_model, px / 100.0) - px / 100.0)
        e = max(edges, key=abs)
        if abs(e) < cfg["edge_threshold"]:
            continue
        side = "yes" if e > 0 else "no"
        entry = px if e > 0 else 100 - px
        if entry < cfg["min_entry_cents"]:
            continue
        # POST: sit below the ask by half the measured spread instead of paying
        # it. Whether this fills is the entire point of the probe.
        limit = max(1, min(99, entry - round(spread_c / 2)))
        picks.append({"ticker": ticker, "strike": strike, "side": side,
                      "last_px": px, "entry": entry, "limit": limit,
                      "edge": e, "p_model": p_model})
    picks.sort(key=lambda p: -abs(p["edge"]))
    return picks[:cfg["max_picks"]], f"mu={mu:.2f} (offset {off:+.2f}) sigma={sg:.2f}"


def realized_to_date(conn) -> float:
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(sum(realized_pnl_cents),0)/100.0 FROM fx_live_trades")
        return float(cur.fetchone()[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", choices=sorted(CITY_CONFIG), action="append")
    ap.add_argument("--live", action="store_true", help="actually place orders")
    ap.add_argument("--date", type=date.fromisoformat, default=None)
    ap.add_argument("--contracts", type=int, default=None, help="override probe size")
    a = ap.parse_args()

    today = a.date or datetime.now(timezone.utc).date()
    cities = a.city or sorted(CITY_CONFIG)
    spreads = {c["station"]: c["median_c"]
               for c in json.loads(SPREAD_JSON.read_text())["cities"]}

    print(f"=== ForecastEx {'LIVE' if a.live else 'DRY RUN'} — {today} ===")
    conn = get_connection()
    client = None
    try:
        cum = realized_to_date(conn)
        print(f"probe realized to date: ${cum:+,.2f} (kill at −${CUMULATIVE_KILL_DOLLARS:.0f})")
        if cum <= -CUMULATIVE_KILL_DOLLARS:
            print("CUMULATIVE KILL BREACHED — not trading"); return 1

        if a.live:
            client = IBKRClient()
            try:
                client.require_session()
            except IBKRError as e:
                print(f"ABORT: {e}\nRe-login at https://localhost:5000 via an SSH tunnel.")
                return 1

        for city in cities:
            cfg = dict(CITY_CONFIG[city])
            if a.contracts:
                cfg["contracts"] = a.contracts
            print(f"\n--- {city} ({cfg['name']}) {cfg['strategy']} "
                  f"edge>={cfg['edge_threshold']:.0%} minPx={cfg['min_entry_cents']}c "
                  f"picks<={cfg['max_picks']} size={cfg['contracts']} ---")
            reason = halted(city)
            if reason:
                print(f"  HALTED — {reason}"); continue
            sp = spreads.get(city)
            if sp is None:
                print("  no measured spread — run forecastex_spread.py"); continue

            picks, note = signals(conn, city, cfg, today, sp)
            if picks is None:
                print(f"  no signal: {note}"); continue
            print(f"  {note} | spread {sp:.1f}c")
            if not picks:
                print("  no contract cleared the threshold"); continue

            for p in picks:
                print(f"  {p['side'].upper():3} strike {p['strike']:.0f}  last {p['last_px']}c  "
                      f"entry {p['entry']}c  POST @{p['limit']}c  edge {p['edge']:+.1%}  "
                      f"p_model {p['p_model']:.3f}")
                if not a.live:
                    continue
                try:
                    pair = client.resolve(cfg["product"], today, p["strike"])
                    conid = pair[p["side"]]
                    r = client.place_order(conid, cfg["contracts"], p["limit"] / 100.0,
                                           tif="DAY", confirm=True)
                    oid = (r.get("order") if isinstance(r, dict) else None) or r
                    oid = oid.get("order_id") if isinstance(oid, dict) else str(oid)[:80]
                except IBKRError as e:
                    print(f"    ORDER FAILED: {str(e)[:160]}"); continue
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO fx_live_trades (placed_at,target_date,station_id,
                          fx_contract_id,conid,side,strike,count,limit_price_cents,posted,
                          strategy,model_source,model_prob_yes,market_last_prob,
                          assumed_spread_cents,edge,ibkr_order_id,notes)
                        VALUES (now(),%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (target_date, fx_contract_id, side) DO NOTHING""",
                        (today, city, p["ticker"], conid, p["side"], p["strike"],
                         cfg["contracts"], p["limit"], cfg["strategy"],
                         f"EMOS combined 00Z {cfg['model_city']} (rolling 45d) [FX PROBE]",
                         p["p_model"], p["last_px"] / 100.0, sp, p["edge"], oid,
                         f"posted {round(sp/2)}c inside the last print; "
                         f"fill/no-fill is the probe's actual result"))
                    conn.commit()
                print(f"    placed order {oid}")
    finally:
        conn.close()
    if not a.live:
        print("\nDRY RUN — nothing placed. Add --live to trade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
