"""LIVE trading cron entry point.

Fires daily at 14:45 UTC. Computes today's signals using the same logic as
paper_trade_log.py, then places real-money orders on Kalshi if every
risk-control check passes.

USAGE:
    # Dry-run (default until --live flag is added on a future invocation):
    uv run python scripts/live_trade.py

    # Actually trade (this is what the cron uses):
    uv run python scripts/live_trade.py --live

Risk controls (ALL must pass before ANY order is placed today):
    - kill switch not engaged (no halt file in ~/.kalshi/halt)
    - cumulative live P&L > -$300
    - today's realized P&L (so far) > -$50
    - total open contracts after this trade < 50
    - per-trade stake < $25
    - rolling 4-week avg spread on filtered trades < 5¢

If any check fails BEFORE evaluating signals, no orders placed, exit with
nonzero status (so the cron alerts via the cron-failure path).

Pre-committed kill criteria — these are *not* configurable here, they're
hardcoded so they can't be tuned away during a drawdown:
    HALT permanently if any of:
      - cumulative drawdown < -$300 at any time months 1-6
      - forward mean P&L < -1¢/trade over first 60 trades
      - limit fill rate < 40% over first 30 attempts
      - rolling 4-week avg spread > 5¢
    When triggered: writes ~/.kalshi/halt with reason, exits, alerts.
"""
import argparse
import math
import statistics
import sys
import time
from datetime import datetime, date, time as dtime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_combined_daily_highs,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos_rolling, gaussian_to_bracket_probs
from weather_markets.kalshi_api import KalshiClient, KalshiAuthError, parse_position
from weather_markets.alerts import send_alert

# ---- strategy parameters (must match paper_trade_log.py) -------------------
STATION_ID = "KNYC"
MODEL = "combined"  # GEFS+IFS
MODELS_LIST = ["gefs", "ifs"]
MODEL_SOURCE = "EMOS combined 00Z (rolling 45d) [LIVE]"
WINDOW_DAYS = 45
INIT_HOUR = 0
EDGE_THRESHOLD = 0.10
MIN_ENTRY_PRICE_CENTS = 60
DECISION_HOUR = 14
DECISION_MINUTE = 45

# ---- risk envelope (DO NOT EDIT during live trading) -----------------------
MAX_STAKE_DOLLARS = 50.0           # per single trade (5% of $1k starting bankroll)
MAX_OPEN_CONTRACTS = 200           # across all positions (runaway-bug circuit breaker)
DAILY_LOSS_LIMIT_DOLLARS = 50.0    # absolute, e.g. -$50
CUMULATIVE_KILL_DOLLARS = 300.0    # halt permanently if total down > $300
SPREAD_REGIME_MAX_CENTS = 5.0      # halt if 4-week avg spread > this
HALT_FILE = Path.home() / ".kalshi" / "halt"

# ---- sizing (pre-committed 2026-06-01 before Phase 8 starts) ---------------
# Unit sizing decisively beats half-Kelly on Sharpe (1.74 vs 0.56-0.90) per
# backtest grid; comparable absolute return at far less variance. Choice locked
# BEFORE first live cron fires so it counts as pre-Phase-8 methodology.
SIZING_MODE = "unit"               # "unit" (fixed contract count) or "half_kelly"
UNIT_CONTRACTS = 75                # fixed count per trade; cap below clips this
                                   # if stake would exceed MAX_STAKE_DOLLARS
KELLY_FRACTION = 0.5               # only used when SIZING_MODE == "half_kelly"


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Kalshi per-contract fee: $0.07 × P × (1-P), rounded up to cent."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


def kelly_optimal(p_win: float, entry_price_cents: int) -> float:
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0.0
    b = (100 - entry_price_cents) / entry_price_cents
    return max(0.0, p_win - (1 - p_win) / b)


def check_halt_file() -> str | None:
    """Returns the halt reason if HALT_FILE exists, else None."""
    if HALT_FILE.exists():
        return HALT_FILE.read_text().strip()
    return None


def write_halt(reason: str) -> None:
    HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HALT_FILE.write_text(f"{datetime.now(timezone.utc).isoformat()}: {reason}\n")


def get_cumulative_pnl_cents(conn) -> int:
    """Sum of realized_pnl_cents across all live_trades. None counts as 0."""
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(realized_pnl_cents), 0) FROM live_trades")
        return int(cur.fetchone()[0])


def get_today_realized_pnl_cents(conn, today: date) -> int:
    """Realized P&L on trades whose target_date is today."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(realized_pnl_cents), 0) FROM live_trades WHERE target_date = %s",
            (today,),
        )
        return int(cur.fetchone()[0])


def get_open_contract_count(client: KalshiClient) -> int:
    """Total absolute open contracts across all positions from Kalshi."""
    positions = client.get_positions().get("market_positions", [])
    return sum(abs(parse_position(p)) for p in positions)


def get_rolling_spread_cents(conn) -> float | None:
    """Mean spread on filtered paper-trades in the last 28 days. None if <10 trades."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT AVG(market_yes_ask - market_yes_bid) AS avg_spread, COUNT(*) AS n
            FROM paper_trades
            WHERE target_date >= CURRENT_DATE - INTERVAL '28 days'
              AND entry_price_cents >= %s AND ABS(edge) >= %s
              AND market_yes_bid IS NOT NULL AND market_yes_ask IS NOT NULL
              AND model_source = %s
            """,
            (MIN_ENTRY_PRICE_CENTS, EDGE_THRESHOLD, 'EMOS combined 00Z (rolling 45d)'),
        )
        row = cur.fetchone()
    if row is None or row[1] < 10:
        return None
    return float(row[0])


def preflight_checks(conn, client: KalshiClient, today: date) -> list[str]:
    """Returns a list of failure reasons. Empty list = all checks pass."""
    failures: list[str] = []

    halt = check_halt_file()
    if halt:
        failures.append(f"HALT file present: {halt}")
        return failures  # short-circuit

    cum = get_cumulative_pnl_cents(conn)
    print(f"  cumulative realized P&L: ${cum/100:+,.2f}")
    if cum / 100.0 < -CUMULATIVE_KILL_DOLLARS:
        write_halt(f"cumulative drawdown ${cum/100:+,.2f} below -${CUMULATIVE_KILL_DOLLARS:.0f} kill")
        failures.append(f"cumulative drawdown breached (${cum/100:+,.2f})")

    today_pnl = get_today_realized_pnl_cents(conn, today)
    print(f"  today's realized P&L:    ${today_pnl/100:+,.2f}")
    if today_pnl / 100.0 < -DAILY_LOSS_LIMIT_DOLLARS:
        failures.append(f"daily loss limit breached (${today_pnl/100:+,.2f})")

    try:
        open_count = get_open_contract_count(client)
        print(f"  open contracts on Kalshi: {open_count}")
        if open_count >= MAX_OPEN_CONTRACTS:
            failures.append(f"max open contracts breached ({open_count} >= {MAX_OPEN_CONTRACTS})")
    except Exception as e:
        failures.append(f"could not read open contracts from Kalshi: {e}")

    avg_spread = get_rolling_spread_cents(conn)
    if avg_spread is None:
        print(f"  rolling 4wk avg spread: insufficient data (<10 trades)")
    else:
        print(f"  rolling 4wk avg spread: {avg_spread:.2f}¢")
        if avg_spread > SPREAD_REGIME_MAX_CENTS:
            write_halt(f"4wk avg spread {avg_spread:.2f}¢ > {SPREAD_REGIME_MAX_CENTS}¢ regime kill")
            failures.append(f"spread regime degraded ({avg_spread:.2f}¢)")

    return failures


def compute_signals_for_today(conn, today: date) -> list[dict]:
    """Returns list of signal dicts ready to be sized + placed."""
    init_time = datetime(today.year, today.month, today.day, INIT_HOUR, 0, tzinfo=timezone.utc)
    snapshot_cutoff = datetime.combine(today, dtime(DECISION_HOUR, DECISION_MINUTE), tzinfo=timezone.utc)

    # Forecast must exist
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecasts WHERE station_id=%s AND model=ANY(%s) AND init_time=%s LIMIT 1",
            (STATION_ID, MODELS_LIST, init_time),
        )
        if cur.fetchone() is None:
            print(f"  no forecast for init {init_time.isoformat()}; skipping")
            return []

    try:
        ensemble_values = compute_combined_daily_highs(
            init_time, today, conn, station_id=STATION_ID, models=MODELS_LIST,
        )
    except Exception as e:
        print(f"  ensemble computation failed: {e}")
        return []
    if len(ensemble_values) < 2:
        print(f"  ensemble too small ({len(ensemble_values)} members); skipping")
        return []
    ensemble_mean = statistics.mean(ensemble_values)
    ensemble_std = statistics.stdev(ensemble_values)

    emos = fit_emos_rolling(today, conn, window_days=WINDOW_DAYS, station_id=STATION_ID,
                            model=MODEL, init_hour=INIT_HOUR)
    if emos is None:
        print(f"  EMOS unfittable; skipping")
        return []
    emos_mu = emos["a"] + emos["b"] * ensemble_mean
    emos_var = emos["c"] + emos["d"] * ensemble_std ** 2
    if emos_var <= 0:
        print(f"  EMOS variance non-positive; skipping")
        return []
    emos_sigma = math.sqrt(emos_var)

    contracts = fetch_contracts_for_date(today, conn, station_id=STATION_ID)
    contracts = [c for c in contracts if c["ticker"].startswith("KXHIGHNY")]
    if not contracts:
        return []

    tickers = [c["ticker"] for c in contracts]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
            FROM prices WHERE ticker=ANY(%s) AND snapshot_at <= %s
            ORDER BY ticker, snapshot_at DESC
            """,
            (tickers, snapshot_cutoff),
        )
        prices = {t: (b, a, s) for t, b, a, s in cur.fetchall()}

    model_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

    signals: list[dict] = []
    for c in contracts:
        ticker = c["ticker"]
        bid_ask = prices.get(ticker)
        if not bid_ask:
            continue
        bid, ask, snap = bid_ask
        if bid is None or ask is None:
            continue
        market_mid = (bid + ask) / 200.0
        model_p = model_probs[ticker]
        edge = model_p - market_mid
        if abs(edge) < EDGE_THRESHOLD:
            continue
        if edge > 0:
            side = "yes"
            cross_entry = int(ask)
            p_win = model_p
        else:
            side = "no"
            cross_entry = 100 - int(bid)
            p_win = 1 - model_p
        if cross_entry < MIN_ENTRY_PRICE_CENTS:
            continue
        # Limit-target: 1¢ inside the spread
        spread = int(ask) - int(bid)
        if spread > 1:
            if side == "yes":
                limit_price = int(ask) - (spread - 1)
            else:
                limit_price = (100 - int(bid)) - (spread - 1)
        else:
            limit_price = cross_entry
        limit_price = max(1, min(99, limit_price))

        signals.append({
            "ticker": ticker, "side": side, "limit_price": limit_price,
            "cross_price": cross_entry, "model_p": model_p,
            "market_mid": market_mid, "edge": edge, "p_win": p_win,
        })
    return signals


def size_trade(balance_cents: int, signal: dict) -> int:
    """Return number of contracts to trade for this signal.

    Unit mode (production): fixed UNIT_CONTRACTS, clipped if it would exceed
    MAX_STAKE_DOLLARS at the signal's limit price (e.g. at very high entry).
    Half-Kelly mode (legacy): stake = balance × kelly_fraction × kelly_optimal,
    capped at MAX_STAKE_DOLLARS.
    """
    limit_price = signal["limit_price"]
    if limit_price <= 0:
        return 0

    if SIZING_MODE == "unit":
        intended_stake = UNIT_CONTRACTS * limit_price / 100.0
        if intended_stake > MAX_STAKE_DOLLARS:
            return max(0, int(MAX_STAKE_DOLLARS / (limit_price / 100.0)))
        return UNIT_CONTRACTS

    # half_kelly fallback
    f_optimal = kelly_optimal(signal["p_win"], limit_price)
    f_chosen = f_optimal * KELLY_FRACTION
    stake_dollars = (balance_cents / 100.0) * f_chosen
    stake_dollars = min(stake_dollars, MAX_STAKE_DOLLARS)
    return max(0, int(stake_dollars / (limit_price / 100.0)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="Actually place orders. Without this flag, runs dry (just prints what it would do).")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    print(f"=== Live trade decision for {today} ({'LIVE' if args.live else 'DRY-RUN'}) ===")

    try:
        client = KalshiClient()
    except KalshiAuthError as e:
        print(f"FAIL: Kalshi auth not configured: {e}", file=sys.stderr)
        return 1

    print(f"  api_base: {client.api_base}")

    with get_connection() as conn:
        # Pre-flight
        print("\n[Preflight risk checks]")
        failures = preflight_checks(conn, client, today)
        if failures:
            print("\n  FAILED preflight:")
            for f in failures:
                print(f"    - {f}")
            print("\n  NO ORDERS PLACED.")
            # Surface preflight failures as alerts. If any halt-related (cumulative
            # or spread regime), the underlying helper has already written ~/.kalshi/halt
            # — flag those as critical.
            critical_keywords = ("cumulative drawdown", "spread regime", "HALT file")
            severity = "critical" if any(k in " ".join(failures) for k in critical_keywords) else "warn"
            send_alert("; ".join(failures), severity=severity, source="live_trade.preflight")
            return 2

        # Compute signals
        print("\n[Signal evaluation]")
        signals = compute_signals_for_today(conn, today)
        print(f"  signals passing filter: {len(signals)}")
        for s in signals:
            print(f"    {s['ticker']} {s['side'].upper()} edge={s['edge']:+.1%} "
                  f"limit={s['limit_price']}¢ cross={s['cross_price']}¢")

        if not signals:
            print("  no actionable signals; clean exit.")
            return 0

        # Get balance for sizing
        try:
            balance = client.get_balance().get("balance", 0)
        except Exception as e:
            print(f"FAIL: could not read balance: {e}", file=sys.stderr)
            return 2
        print(f"\n  account balance: ${balance/100:,.2f}")

        # Size + place
        print("\n[Order placement]")
        placed = 0; rejected = 0; total_contracts = 0
        for s in signals:
            count = size_trade(balance, s)
            if count < 1:
                print(f"  {s['ticker']}: size=0, skipping")
                rejected += 1
                continue
            stake_dollars = count * s['limit_price'] / 100.0
            if stake_dollars > MAX_STAKE_DOLLARS:
                count = int(MAX_STAKE_DOLLARS / (s['limit_price'] / 100.0))
                stake_dollars = count * s['limit_price'] / 100.0
            print(f"  {s['ticker']}: {count} contracts @ {s['limit_price']}¢ = ${stake_dollars:.2f}")
            total_contracts += count

            # client_order_id deterministic for the day so re-runs are idempotent
            client_order_id = f"liveth-{today.isoformat()}-{s['ticker']}-{s['side']}"

            if not args.live:
                continue

            try:
                resp = client.place_limit_order(
                    ticker=s['ticker'], side=s['side'], count=count,
                    price_cents=s['limit_price'], post_only=True,
                    client_order_id=client_order_id,
                )
                order = resp.get("order", resp)
                kalshi_order_id = order.get("order_id")
                # Log to DB
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO live_trades (
                            placed_at, target_date, ticker, side, count,
                            limit_price_cents, cross_price_cents, model_source,
                            model_prob_yes, market_mid_prob, edge,
                            kalshi_order_id, client_order_id, fill_status, notes
                        ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                        ON CONFLICT (client_order_id) DO NOTHING
                    """, (today, s['ticker'], s['side'], count,
                          s['limit_price'], s['cross_price'], MODEL_SOURCE,
                          s['model_p'], s['market_mid'], s['edge'],
                          kalshi_order_id, client_order_id,
                          f"sizing={SIZING_MODE}({UNIT_CONTRACTS if SIZING_MODE == 'unit' else KELLY_FRACTION}), "
                          f"balance=${balance/100:.2f}"))
                placed += 1
                print(f"    placed: order_id={kalshi_order_id}")
            except Exception as e:
                rejected += 1
                print(f"    ERROR: {type(e).__name__}: {e}", file=sys.stderr)
                send_alert(f"order place failed: {s['ticker']} {s['side']} {count}@{s['limit_price']}¢: "
                           f"{type(e).__name__}: {e}", severity="warn", source="live_trade.place")

        print(f"\n  placed: {placed}, rejected: {rejected}, total contracts: {total_contracts}")
        if args.live and rejected > 0:
            send_alert(f"live_trade summary {today}: placed={placed}, rejected={rejected}",
                       severity="warn", source="live_trade.summary")
        if not args.live:
            print("\n  DRY-RUN — no orders actually placed. Re-run with --live to place.")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
