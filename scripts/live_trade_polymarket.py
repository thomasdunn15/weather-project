"""Polymarket US LIVE probe — Miami daily-high port. REAL MONEY.

Live-probe sizing of the validated replay config (docs: replay 06-30..08-06
PM +$12.80 vs Kalshi +$5.15 day-matched @0.25). Same signal path as
paper_trade_polymarket.py; orders are synchronous IOC marketable limits via
PolymarketClient.create_order — they fill at-or-better immediately or cancel,
and never rest on the book.

Hard rails (change deliberately, log in docs/decisions/):
  - 150 contracts/signal, max 2 signals/day (largest |edge| first)
  - entry bound 5..95 cents; edge threshold 0.10 (0.25 until 2026-09-11)
  - halt file halt/PMKMIA aborts every run (touch it to stop trading)
  - cumulative realized P&L < -$300 -> writes halt/PMKMIA itself and aborts
  - daily spend cap $300 notional
Settlement: each run first scores yesterday's unsettled rows from observations
(PM bracket semantics via kalshi_equivalent_bracket, PM taker fee 6bps formula)
so the cumulative kill switch sees current P&L. It depends on fill_count, which
scripts/reconcile_pm_trades.py writes at 13:05 and 20:05 — without that cron
every trade reads as a no-fill and the kill switch can never fire.

  uv run python scripts/live_trade_polymarket.py --live      # REAL ORDERS
  uv run python scripts/live_trade_polymarket.py             # dry-run (default)
"""
import argparse
import json
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather_markets.alerts import send_alert
from weather_markets.aggregation import compute_combined_daily_highs
from weather_markets.db import get_connection
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.evaluation import contract_resolved_yes, kalshi_equivalent_bracket
from weather_markets.polymarket import PolymarketClient

STATION = "KMIA"
MODELS = ["gefs", "ifs"]
INIT_HOUR = 0
WINDOW_DAYS = 45
EDGE_THRESHOLD = 0.10        # 2026-09-11: lowered from 0.25 on the forward PM v2 paper sweep
                             # (Miami 0.10-0.25 band: 21 trades, 76% win, +17.9c/contract).
                             # See docs/decisions/2026-09-11-pm-miami-threshold-010.md
# v2: inclusive-pair brackets (2026-08-23). Rows tagged with the old label
# were priced off P(low degree only) and may sit on the wrong side.
MODEL_SOURCE = "PM live probe Miami combined 00Z v2"
MAX_QUOTE_AGE_MIN = 30

CONTRACTS_PER_SIGNAL = 150   # 2026-08-21: raised from 100 on measured book depth
                             # (median 265 within +2c; 150 fully fillable on 75% of
                             # snapshot-days). See docs/decisions/2026-08-21-pm-size-150.md
                             # — that doc records the one contrary datapoint.
MAX_SIGNALS_PER_DAY = 2
ENTRY_MIN, ENTRY_MAX = 5, 95
SLIPPAGE_ALLOWANCE_CENTS = 2  # IOC bound = quoted entry + 2c: reaches the ~120-200
                              # contracts within 2c of touch (measured 2026-08-12)
                              # instead of only the ~30-55 at the very top level.
                              # Worst-case fill price is still hard-capped at +2c.
DAILY_SPEND_CAP_CENTS = 300 * 100   # 2 signals x 150 x <=95c
CUMULATIVE_KILL_CENTS = -300 * 100  # 30% of the $1k bankroll
HALT_FILE = Path(__file__).resolve().parents[1] / "halt" / "PMKMIA"


def order_bound_cents(entry: int) -> int:
    """IOC limit price actually sent: quoted entry + slippage allowance, capped
    below 100 so the order can never pay par."""
    return min(entry + SLIPPAGE_ALLOWANCE_CENTS, 97)


def pm_taker_fee_cents(price_cents: float, contracts: float) -> float:
    p = price_cents / 100.0
    return 6.0 * p * (1 - p) * contracts


def choose_signals(quotes_probs: list[dict]) -> list[dict]:
    """quotes_probs: [{ticker,bid,ask,p_model}] -> at most MAX_SIGNALS_PER_DAY
    orders sorted by |edge|, entry bounds + threshold applied. Pure function."""
    out = []
    for q in quotes_probs:
        mid = (q["bid"] + q["ask"]) / 200.0
        edge = q["p_model"] - mid
        if abs(edge) < EDGE_THRESHOLD:
            continue
        if edge > 0:
            intent, entry = "ORDER_INTENT_BUY_LONG", q["ask"]
        else:
            intent, entry = "ORDER_INTENT_BUY_SHORT", 100 - q["bid"]
        if not (ENTRY_MIN <= entry <= ENTRY_MAX):
            continue
        out.append({"ticker": q["ticker"], "intent": intent, "entry": entry,
                    "edge": edge, "p_model": q["p_model"], "mid": mid,
                    "snapshot_at": q.get("snapshot_at")})
    out.sort(key=lambda s: -abs(s["edge"]))
    return out[:MAX_SIGNALS_PER_DAY]


def settle_unsettled(conn, today: date) -> float:
    """Score past unsettled rows against observations; return cumulative realized."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.id, t.intent, t.fill_count, t.fill_avg_price_cents,
                   c.bracket_type, c.strike_low, c.strike_high, o.high_temp_f,
                   t.target_date
            FROM pm_live_trades t
            JOIN contracts c ON c.ticker = t.ticker
            LEFT JOIN observations o ON o.date = t.target_date AND o.station_id = %s
            WHERE t.settlement IS NULL AND t.target_date < %s""", (STATION, today))
        for tid, intent, fills, favg, bt, sl, sh, hf, td in cur.fetchall():
            if fills == 0:
                # fill_count is written by scripts/reconcile_pm_trades.py, not by
                # this script. A row it has not reached yet is indistinguishable
                # from a genuine no-fill, and zeroing it would hide a real filled
                # trade from the cumulative kill switch. Wait 2 days before
                # believing a zero; the reconciler runs twice daily.
                if (today - td).days >= 2:
                    cur.execute("UPDATE pm_live_trades SET settlement='no_fill', "
                                "realized_pnl_cents=0 WHERE id=%s", (tid,))
                continue
            if hf is None:
                continue  # obs not in yet; retry next run
            b = kalshi_equivalent_bracket("polymarket", bt, sl, sh)
            yes = contract_resolved_yes(int(round(hf)), b)
            won = yes if intent == "ORDER_INTENT_BUY_LONG" else not yes
            entry = favg
            pnl = ((100 - entry) if won else -entry) * fills - pm_taker_fee_cents(entry, fills)
            cur.execute("UPDATE pm_live_trades SET settlement=%s, realized_pnl_cents=%s WHERE id=%s",
                        ("win" if won else "loss", pnl, tid))
        cur.execute("SELECT COALESCE(sum(realized_pnl_cents),0) FROM pm_live_trades")
        cum = cur.fetchone()[0]
    conn.commit()
    return cum


def parse_fills(resp: dict) -> tuple[float, float | None]:
    """(filled_contracts, avg_price_cents) from a synchronous create_order response."""
    total = 0.0
    notional = 0.0
    for ex in resp.get("executions") or []:
        qty = float(ex.get("quantity") or ex.get("qty") or 0)
        px = ex.get("price") or {}
        val = float(px.get("value")) if isinstance(px, dict) and px.get("value") else None
        if val is None:
            continue
        total += qty
        notional += qty * val * 100
    return total, (notional / total if total else None)


def today_signals(conn, target: date, now: datetime) -> tuple[list[dict], str]:
    """The orders this script would place right now: ([], reason) if none.

    Lifted out of main() 2026-08-23 so scripts/live_signals_terminal.py can
    render exactly what would trade rather than reimplementing the signal path.
    Quote freshness is measured against `now`, so passing a later `now`
    re-prices against the current book instead of the cron's snapshot.
    """
    ensemble = compute_combined_daily_highs(
        datetime(target.year, target.month, target.day, INIT_HOUR, tzinfo=timezone.utc),
        target, conn, station_id=STATION, models=MODELS)
    if len(ensemble) < 2:
        return [], "no forecast"
    emos = fit_emos_rolling(target, conn, window_days=WINDOW_DAYS,
                            station_id=STATION, model="combined", init_hour=INIT_HOUR)
    if emos is None:
        return [], "EMOS unfittable"
    mean, std = statistics.mean(ensemble), statistics.stdev(ensemble)
    mu = emos["a"] + emos["b"] * mean
    var = emos["c"] + emos["d"] * std ** 2
    if var <= 0:
        return [], "bad EMOS variance"
    sigma = math.sqrt(var)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (p.ticker) p.ticker, c.bracket_type,
                   c.strike_low, c.strike_high, p.yes_bid, p.yes_ask, p.snapshot_at
            FROM prices p JOIN contracts c ON c.ticker = p.ticker
            WHERE c.platform='polymarket' AND c.station_id=%s AND c.target_date=%s
              AND p.snapshot_at >= %s AND p.yes_bid IS NOT NULL AND p.yes_ask IS NOT NULL
            ORDER BY p.ticker, p.snapshot_at DESC""",
            (STATION, target, now - timedelta(minutes=MAX_QUOTE_AGE_MIN)))
        quotes = cur.fetchall()
    if not quotes:
        return [], f"no PM quotes newer than {MAX_QUOTE_AGE_MIN}min"
    brackets = [kalshi_equivalent_bracket("polymarket", bt, sl, sh) | {"ticker": t}
                for t, bt, sl, sh, _, _, _ in quotes]
    probs = gaussian_to_bracket_probs(mu, sigma, brackets)
    signals = choose_signals([
        {"ticker": t, "bid": bid, "ask": ask, "p_model": probs[b["ticker"]],
         "snapshot_at": snap}
        for (t, _bt, _sl, _sh, bid, ask, snap), b in zip(quotes, brackets)])
    return signals, "" if signals else "no actionable signals"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="place REAL orders (default: dry-run)")
    args = parser.parse_args()
    now = datetime.now(tz=timezone.utc)
    target = now.date()
    tag = "LIVE" if args.live else "DRY"
    print(f"=== PM {tag} {STATION} {target} {now.isoformat(timespec='seconds')} ===")

    if HALT_FILE.exists():
        print(f"[CRITICAL] halt file present: {HALT_FILE.read_text().strip()} — NO ORDERS.")
        return 2

    conn = get_connection()
    try:
        cum = settle_unsettled(conn, target)
        print(f"  cumulative realized: ${cum/100:.2f}")
        if cum < CUMULATIVE_KILL_CENTS:
            HALT_FILE.parent.mkdir(exist_ok=True)
            HALT_FILE.write_text(f"{now.isoformat()}: PM cumulative ${cum/100:.2f} below ${CUMULATIVE_KILL_CENTS/100:.0f}\n")
            print("[CRITICAL] cumulative kill breached — halt file written. NO ORDERS.")
            return 2

        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(sum(count * limit_price_cents),0) FROM pm_live_trades WHERE target_date=%s", (target,))
            spent = cur.fetchone()[0]
        if spent >= DAILY_SPEND_CAP_CENTS:
            print(f"  daily spend cap reached (${spent/100:.2f}) — NO ORDERS.")
            return 0

        signals, note = today_signals(conn, target, now)
        if not signals:
            print(f"  {note}; clean exit.")
            return 0

        client = PolymarketClient() if args.live else None
        with conn.cursor() as cur:
            for s in signals:
                bound = order_bound_cents(s["entry"])
                print(f"  {tag} {s['ticker']} {s['intent']} {CONTRACTS_PER_SIGNAL}x "
                      f"quoted={s['entry']}c bound<={bound}c "
                      f"edge={s['edge']:+.3f} model={s['p_model']:.3f} mid={s['mid']:.3f}")
                if not args.live:
                    continue
                try:
                    resp = client.create_order(s["ticker"], s["intent"],
                                               bound / 100.0, CONTRACTS_PER_SIGNAL)
                except Exception as e:
                    # A rejected LIVE order is silent otherwise — one line in a
                    # log nobody reads. On 2026-08-30 Polymarket began geo-gating
                    # this server (Hetzner, Nuremberg) with 403 GEO_BLOCKED_STATE
                    # and the whole venue went offline with no notification; the
                    # operator found it by asking why nothing had fired.
                    print(f"    ORDER FAILED: {e}")
                    msg = str(e)
                    geo = "GEO_BLOCKED" in msg or "geogate" in msg
                    send_alert(
                        f"Polymarket LIVE order REJECTED for {s['ticker']} "
                        f"({s['intent']} {CONTRACTS_PER_SIGNAL}x @ {bound}c, "
                        f"edge {s['edge']:+.3f})"
                        + (" — VENUE GEO-BLOCKED, Polymarket trading is offline "
                           "until this host is in a permitted jurisdiction." if geo
                           else "") + f" {msg[:240]}",
                        severity="critical", source="live_trade_polymarket")
                    continue
                fills, favg = parse_fills(resp)
                cur.execute("""
                    INSERT INTO pm_live_trades (placed_at, target_date, ticker, intent, count,
                        limit_price_cents, model_source, model_prob_yes, market_mid_prob, edge,
                        pm_order_id, fill_count, fill_avg_price_cents, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (now, target, s["ticker"], s["intent"], CONTRACTS_PER_SIGNAL,
                     bound, MODEL_SOURCE, s["p_model"], s["mid"], s["edge"],
                     resp.get("id"), fills, favg, json.dumps(resp)[:1500]))
                print(f"    order {resp.get('id')}: filled {fills} @ {favg}")
        conn.commit()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
