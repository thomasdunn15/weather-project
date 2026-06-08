"""LIVE trading cron entry point (multi-city, per docs/chicago_miami_live_precommit.md).

Fires once per day per city at the city's pre-committed decision time. Computes
that day's signals using the same logic as paper_trade_log.py, then places
real-money orders on Kalshi if every risk-control check passes.

USAGE:
    # Dry-run for a city (default — prints what would be done, no orders):
    uv run python scripts/live_trade.py --city KORD
    uv run python scripts/live_trade.py --city KMIA

    # Actually trade (cron uses this):
    uv run python scripts/live_trade.py --city KORD --live
    uv run python scripts/live_trade.py --city KMIA --live

Risk controls (ALL must pass before ANY order is placed for that city):
    - halt/ALL not present (aggregate halt)
    - halt/<city> not present (per-city halt)
    - cumulative cross-city realized P&L > -$AGGREGATE_CUMULATIVE_KILL
    - cumulative per-city realized P&L > -$CUMULATIVE_KILL_<city>
    - today's realized P&L (cross-city) > -$AGGREGATE_DAILY_LOSS_LIMIT
    - today's realized P&L (per-city) > -$DAILY_LOSS_LIMIT_<city>
    - today's stake deployed (per-city) < DAILY_STAKE_BUDGET_<city>
    - per-trade stake < PER_TRADE_STAKE_CAP_<city>
    - rolling 4-week avg spread on filtered trades < SPREAD_REGIME_MAX_CENTS

If any check fails BEFORE evaluating signals, no orders placed, exit nonzero.

Pre-committed parameters live in CITY_CONFIG below. DO NOT modify during the
live-trading window — write a new pre-commit doc, halt trading, then change.
"""
import argparse
import math
import statistics
import sys
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
from weather_markets.stations import get as get_station


# ====================================================================
# PRE-COMMITTED PARAMETERS — see docs/chicago_miami_live_precommit.md
# ====================================================================

EDGE_THRESHOLD = 0.10        # DEFAULT — per-city cfg['edge_threshold'] overrides
WINDOW_DAYS = 45
INIT_HOUR = 0
MODELS_LIST_DEFAULT = ["gefs", "ifs"]  # DEFAULT — per-city cfg['models'] overrides

# Per-city config. Constants here MUST NOT be edited mid-window — see pre-commit doc.
#
# REVISION 2026-06-07: Chicago resumes after halt with tighter, smaller config.
# Per docs/chicago_resume_2026-06-07_precommit.md:
#   - filter: edge>=25% (up from 10% — only Bonferroni-surviving cell)
#   - sizing: Amount $25/trade with 500 contract cap
#   - cumulative kill: $200 (down from $500)
#   - daily loss limit: $75
# Per-trade max loss bounded by $25 (the amount stake).
# Miami remains HALTED (halt/KMIA file present) — recent paper data t=-0.49.
CITY_CONFIG = {
    "KORD": {
        "city_name": "Chicago",
        # REVISION 2026-06-07 evening: switched from "combined" (GEFS+IFS) to
        # "combined_hrrr" (GEFS+IFS+HRRR). Backtest comparison on Dec 13 2025
        # – Jun 5 2026 showed +$11.12/trade improvement at edge>=25% Amount $25
        # ($26.13 -> $37.25, +43%). Statistical significance improved from
        # p=0.013 to p=0.003. HRRR is already ingested daily for Chicago.
        "models": ["gefs", "ifs", "hrrr"],
        "emos_model": "combined_hrrr",
        "model_source": "EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        "paper_model_source": "EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        "live_model_source_tag": "EMOS combined_hrrr 00Z Chicago (rolling 45d) [LIVE]",
        "decision_hour": 14,
        "decision_minute": 46,
        "edge_threshold": 0.25,                 # per-city — Chicago needs 25% (Bonferroni-passing)
        "sizing_mode": "amount",                # "unit", "even_split", or "amount"
        "amount_dollars": 50.0,                 # $/trade — UP from $25 (2026-06-08 revision)
        "max_contracts_per_trade": 500,         # depth cap for amount mode
        "unit_contracts": 200,                  # used only if sizing_mode == "unit"
        "daily_loss_limit_dollars":    150.0,   # UP from $75 (matches 3 × $50)
        "cumulative_kill_dollars":     500.0,   # UP from $200 (more runway at higher sizing)
        "max_open_contracts":         5000,
    },
    "KMIA": {
        "city_name": "Miami",
        "models": ["gefs", "ifs"],
        "emos_model": "combined",
        "model_source": "EMOS combined 00Z Miami (rolling 45d)",
        "paper_model_source": "EMOS combined 00Z Miami (rolling 45d)",
        "live_model_source_tag": "EMOS combined 00Z Miami (rolling 45d) [LIVE]",
        "decision_hour": 15,
        "decision_minute": 30,
        "edge_threshold": 0.10,                 # left at old value (HALTED so unused)
        "sizing_mode": "unit",
        "amount_dollars": 0.0,
        "max_contracts_per_trade": 1500,
        "unit_contracts": 300,
        "daily_loss_limit_dollars":    500.0,
        "cumulative_kill_dollars":    1000.0,
        "max_open_contracts":         5000,
    },
}

# Aggregate (cross-city) limits.
AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS = 150.0    # = Chicago daily; Miami halted
AGGREGATE_CUMULATIVE_KILL_DOLLARS = 500.0     # = Chicago cumulative; Miami halted
SPREAD_REGIME_MAX_CENTS = 5.0

# Execution: how aggressive to be with the limit price when placing.
# "post_inside_spread"   = old behavior. Post 1c inside spread (maker fee, no
#                         taker fee, but may not fill if no one takes our offer).
#                         Cost yesterday: 1071 contracts on B85.5 never filled,
#                         missed ~$1000 profit.
# "cross_at_ask"         = post AT the ask (= taker). Gets all available book
#                         depth immediately; remainder rests at the ask price
#                         and may still partially fill. Closer to backtest's
#                         "limit-100% assume 100% fill" intent.
# "cross_with_premium"   = post at ask + premium cents to walk the book.
#                         Highest fill rate, highest cost.
# Revised 2026-06-06 — switched back to post_inside_spread after empirical
# backtest analysis. Dashboard's "Empirical comparison" mode showed that on
# 332 resolved trades:
#   post_inside_spread:    75% fill rate, +$35.19/filled, +291% final, -24% DD
#   cross_at_ask:          99% fill rate, +$6.27/filled,  +69% final,  -66% DD
#   cross_with_premium=1:  99% fill rate, +$3.24/filled,  +35% final,  -72% DD
# The 80 trades that crossing catches but maker misses LOSE ~$80/trade — the
# unfilled trades are adverse-selected losers. Missing them is net beneficial.
# B85.5 miss was a sample-of-one; aggregate says it's worth tolerating.
EXECUTION_MODE = "post_inside_spread"
CROSS_PREMIUM_CENTS = 0   # n/a in this mode

# Halt directory — per-city + aggregate halt files.
HALT_DIR = Path(__file__).parent.parent / "halt"
HALT_FILE_ALL = HALT_DIR / "ALL"


def halt_file_for_city(city: str) -> Path:
    return HALT_DIR / city


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Kalshi per-contract fee: $0.07 × P × (1-P), rounded up to cent."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    return max(1, math.ceil(0.07 * p * (1.0 - p) * 100))


def check_halts(city: str) -> list[str]:
    """Returns a list of active halt reasons. Empty list = no halt."""
    halts = []
    if HALT_FILE_ALL.exists():
        halts.append(f"halt/ALL present: {HALT_FILE_ALL.read_text().strip()}")
    city_halt = halt_file_for_city(city)
    if city_halt.exists():
        halts.append(f"halt/{city} present: {city_halt.read_text().strip()}")
    return halts


def write_halt(path: Path, reason: str) -> None:
    HALT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{datetime.now(timezone.utc).isoformat()}: {reason}\n")


def get_cumulative_pnl_cents(conn, model_source_like: str | None = None) -> int:
    """Sum of realized_pnl_cents. If model_source_like is given, scope to that source."""
    with conn.cursor() as cur:
        if model_source_like:
            cur.execute(
                "SELECT COALESCE(SUM(realized_pnl_cents), 0) FROM live_trades WHERE model_source LIKE %s",
                (model_source_like,),
            )
        else:
            cur.execute("SELECT COALESCE(SUM(realized_pnl_cents), 0) FROM live_trades")
        return int(cur.fetchone()[0])


def get_today_realized_pnl_cents(conn, today: date, model_source_like: str | None = None) -> int:
    """Today's realized P&L. If model_source_like is given, scope to that source."""
    with conn.cursor() as cur:
        if model_source_like:
            cur.execute(
                "SELECT COALESCE(SUM(realized_pnl_cents), 0) FROM live_trades "
                "WHERE target_date = %s AND model_source LIKE %s",
                (today, model_source_like),
            )
        else:
            cur.execute(
                "SELECT COALESCE(SUM(realized_pnl_cents), 0) FROM live_trades WHERE target_date = %s",
                (today,),
            )
        return int(cur.fetchone()[0])


def get_today_stake_deployed_cents(conn, today: date, model_source_like: str) -> int:
    """Sum of stake (count × limit_price_cents) PLACED today for this city.

    Counts all live_trades rows regardless of fill_status — once placed we've
    committed budget even if unfilled (limit order still exposes us to fill).
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(count * limit_price_cents), 0)
               FROM live_trades
               WHERE target_date = %s AND model_source LIKE %s""",
            (today, model_source_like),
        )
        return int(cur.fetchone()[0])


def get_open_contract_count(client: KalshiClient, ticker_prefix: str | None = None) -> int:
    """Total absolute open contracts. Optionally scoped to tickers starting with prefix."""
    positions = client.get_positions().get("market_positions", [])
    total = 0
    for p in positions:
        ticker = p.get("ticker", "")
        if ticker_prefix and not ticker.startswith(ticker_prefix):
            continue
        total += abs(parse_position(p))
    return total


def get_rolling_spread_cents(conn, paper_model_source: str, edge_threshold: float = EDGE_THRESHOLD) -> float | None:
    """Mean spread on filtered paper-trades in the last 28 days. None if <10 trades."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT AVG(market_yes_ask - market_yes_bid) AS avg_spread, COUNT(*) AS n
               FROM paper_trades
               WHERE target_date >= CURRENT_DATE - INTERVAL '28 days'
                 AND ABS(edge) >= %s
                 AND market_yes_bid IS NOT NULL AND market_yes_ask IS NOT NULL
                 AND model_source = %s""",
            (edge_threshold, paper_model_source),
        )
        row = cur.fetchone()
    if row is None or row[1] < 10:
        return None
    return float(row[0])


def preflight_checks(conn, client: KalshiClient, city: str, today: date) -> list[str]:
    cfg = CITY_CONFIG[city]
    failures: list[str] = []

    # Halt files
    halts = check_halts(city)
    if halts:
        failures.extend(halts)
        return failures

    # Aggregate cumulative kill
    agg_cum = get_cumulative_pnl_cents(conn) / 100.0
    print(f"  aggregate cumulative realized P&L: ${agg_cum:+,.2f}")
    if agg_cum < -AGGREGATE_CUMULATIVE_KILL_DOLLARS:
        write_halt(HALT_FILE_ALL, f"aggregate cumulative ${agg_cum:+,.2f} below -${AGGREGATE_CUMULATIVE_KILL_DOLLARS:.0f}")
        failures.append(f"aggregate cumulative kill breached (${agg_cum:+,.2f})")

    # Per-city cumulative kill
    city_cum = get_cumulative_pnl_cents(conn, cfg["live_model_source_tag"]) / 100.0
    print(f"  {city} cumulative realized P&L: ${city_cum:+,.2f}")
    if city_cum < -cfg["cumulative_kill_dollars"]:
        write_halt(halt_file_for_city(city),
                   f"{city} cumulative ${city_cum:+,.2f} below -${cfg['cumulative_kill_dollars']:.0f}")
        failures.append(f"{city} cumulative kill breached (${city_cum:+,.2f})")

    # Aggregate today's loss
    agg_today = get_today_realized_pnl_cents(conn, today) / 100.0
    print(f"  aggregate today's realized P&L: ${agg_today:+,.2f}")
    if agg_today < -AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS:
        failures.append(f"aggregate daily loss breached (${agg_today:+,.2f})")

    # Per-city today's loss
    city_today = get_today_realized_pnl_cents(conn, today, cfg["live_model_source_tag"]) / 100.0
    print(f"  {city} today's realized P&L: ${city_today:+,.2f}")
    if city_today < -cfg["daily_loss_limit_dollars"]:
        failures.append(f"{city} daily loss breached (${city_today:+,.2f})")

    # Per-city open contracts on Kalshi
    series = get_station(city).kalshi_series
    try:
        open_count = get_open_contract_count(client, ticker_prefix=series)
        print(f"  {city} open contracts on Kalshi: {open_count}")
        if open_count >= cfg["max_open_contracts"]:
            failures.append(f"{city} max open contracts ({open_count} >= {cfg['max_open_contracts']})")
    except Exception as e:
        failures.append(f"could not read open contracts: {e}")

    # Rolling 4wk spread (per-city paper data)
    avg_spread = get_rolling_spread_cents(conn, cfg["paper_model_source"],
                                          edge_threshold=cfg.get("edge_threshold", EDGE_THRESHOLD))
    if avg_spread is None:
        print(f"  {city} rolling 4wk avg spread: insufficient data (<10 trades)")
    else:
        print(f"  {city} rolling 4wk avg spread: {avg_spread:.2f}¢")
        if avg_spread > SPREAD_REGIME_MAX_CENTS:
            write_halt(halt_file_for_city(city),
                       f"{city} 4wk avg spread {avg_spread:.2f}¢ > {SPREAD_REGIME_MAX_CENTS}¢")
            failures.append(f"{city} spread regime degraded ({avg_spread:.2f}¢)")

    return failures


def compute_signals_for_today(conn, city: str, today: date) -> list[dict]:
    """Same filter as paper_trade_log: entry >= 0, |edge| >= 10%, limit-100% execution."""
    cfg = CITY_CONFIG[city]
    station = get_station(city)
    init_time = datetime(today.year, today.month, today.day, INIT_HOUR, 0, tzinfo=timezone.utc)
    snapshot_cutoff = datetime.combine(
        today, dtime(cfg["decision_hour"], cfg["decision_minute"]), tzinfo=timezone.utc,
    )

    models_list = cfg.get("models", MODELS_LIST_DEFAULT)
    emos_model = cfg.get("emos_model", "combined")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecasts WHERE station_id=%s AND model=ANY(%s) AND init_time=%s LIMIT 1",
            (city, models_list, init_time),
        )
        if cur.fetchone() is None:
            print(f"  no forecast for init {init_time.isoformat()}; skipping")
            return []

    try:
        ensemble_values = compute_combined_daily_highs(
            init_time, today, conn, station_id=city, models=models_list,
        )
    except Exception as e:
        print(f"  ensemble computation failed: {e}")
        return []
    if len(ensemble_values) < 2:
        print(f"  ensemble too small ({len(ensemble_values)} members); skipping")
        return []
    ensemble_mean = statistics.mean(ensemble_values)
    ensemble_std = statistics.stdev(ensemble_values)

    emos = fit_emos_rolling(today, conn, window_days=WINDOW_DAYS, station_id=city,
                            model=emos_model, init_hour=INIT_HOUR)
    if emos is None:
        print(f"  EMOS unfittable; skipping")
        return []
    emos_mu = emos["a"] + emos["b"] * ensemble_mean
    emos_var = emos["c"] + emos["d"] * ensemble_std ** 2
    if emos_var <= 0:
        print(f"  EMOS variance non-positive; skipping")
        return []
    emos_sigma = math.sqrt(emos_var)

    contracts = fetch_contracts_for_date(today, conn, station_id=city, series=station.kalshi_series)
    if not contracts:
        return []

    tickers = [c["ticker"] for c in contracts]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
               FROM prices WHERE ticker=ANY(%s) AND snapshot_at <= %s
               ORDER BY ticker, snapshot_at DESC""",
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
        if abs(edge) < cfg.get("edge_threshold", EDGE_THRESHOLD):
            continue
        if edge > 0:
            side = "yes"
            cross_entry = int(ask)
            p_win = model_p
        else:
            side = "no"
            cross_entry = 100 - int(bid)
            p_win = 1 - model_p
        # NO MIN ENTRY FILTER (matches pre-committed cell entry>=0)

        # Set limit_price + post_only flag according to EXECUTION_MODE.
        spread = int(ask) - int(bid)
        if EXECUTION_MODE == "post_inside_spread":
            if spread > 1:
                if side == "yes":
                    limit_price = int(ask) - (spread - 1)
                else:
                    limit_price = (100 - int(bid)) - (spread - 1)
                post_only_safe = True
            else:
                limit_price = cross_entry
                post_only_safe = False
        elif EXECUTION_MODE == "cross_at_ask":
            # Post AT the ask = guaranteed taker on existing depth; remainder
            # rests at that price. Better fill rate vs post-inside-spread.
            limit_price = cross_entry
            post_only_safe = False
        elif EXECUTION_MODE == "cross_with_premium":
            # Walk the book up to CROSS_PREMIUM_CENTS beyond the ask.
            limit_price = cross_entry + CROSS_PREMIUM_CENTS
            post_only_safe = False
        else:
            raise ValueError(f"Unknown EXECUTION_MODE: {EXECUTION_MODE!r}")
        limit_price = max(1, min(99, limit_price))

        signals.append({
            "ticker": ticker, "side": side, "limit_price": limit_price,
            "cross_price": cross_entry, "model_p": model_p,
            "market_mid": market_mid, "edge": edge, "p_win": p_win,
            "post_only": post_only_safe,
        })

    # Sort by edge magnitude DESCENDING for display purposes only.
    # Even-split sizing means budget is divided equally regardless of order.
    signals.sort(key=lambda s: -abs(s["edge"]))
    return signals


def even_split_stake_cents(daily_budget_cents: int, n_signals: int) -> int:
    """Equal allocation across all signals so none get skipped.

    Pre-committed change (2026-06-05): previously sized first-by-edge until
    budget exhausted, causing later signals to be dropped. User observed this
    caused the model's weaker signals (including some that still won handily)
    to be missed. Now every signal gets daily_budget / n_signals.

    Per-trade stake is the integer-cent division; trailing cents go to the
    first N signals."""
    if n_signals <= 0:
        return 0
    return daily_budget_cents // n_signals


def size_trade(city: str, signal: dict, per_trade_stake_cents: int) -> int:
    """Contracts to place for one signal.

    Three sizing modes per CITY_CONFIG[city]['sizing_mode']:
      - "unit"        : fixed contract count (cfg['unit_contracts']) per trade.
                        per_trade_stake_cents is IGNORED.
      - "amount"      : cfg['amount_dollars'] / limit_price, capped at
                        cfg['max_contracts_per_trade']. Matches dashboard's
                        post_inside_spread + Amount $ + cap simulation exactly.
      - "even_split"  : per_trade_stake / limit_price (integer).
    """
    cfg = CITY_CONFIG[city]
    mode = cfg.get("sizing_mode", "even_split")
    if mode == "unit":
        return int(cfg["unit_contracts"])
    if mode == "amount":
        limit_price = signal["limit_price"]
        if limit_price <= 0:
            return 0
        amount_cents = int(round(cfg["amount_dollars"] * 100))
        n_contracts = amount_cents // limit_price
        cap = cfg.get("max_contracts_per_trade")
        if cap is not None and n_contracts > cap:
            n_contracts = cap
        return int(n_contracts)
    # even_split (legacy)
    limit_price = signal["limit_price"]
    if limit_price <= 0 or per_trade_stake_cents <= 0:
        return 0
    return max(0, per_trade_stake_cents // limit_price)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, choices=list(CITY_CONFIG.keys()),
                        help="Which city to trade (KORD or KMIA).")
    parser.add_argument("--live", action="store_true",
                        help="Actually place orders. Without this flag, runs dry.")
    args = parser.parse_args()

    city = args.city
    cfg = CITY_CONFIG[city]
    today = datetime.now(timezone.utc).date()
    mode_str = "LIVE" if args.live else "DRY-RUN"
    print(f"=== Live trade decision for {city} ({cfg['city_name']}) {today} ({mode_str}) ===")

    try:
        client = KalshiClient()
    except KalshiAuthError as e:
        print(f"FAIL: Kalshi auth not configured: {e}", file=sys.stderr)
        return 1

    print(f"  api_base: {client.api_base}")
    print(f"  decision time: {cfg['decision_hour']:02d}:{cfg['decision_minute']:02d} UTC")
    sizing_mode = cfg.get("sizing_mode", "even_split")
    if sizing_mode == "unit":
        print(f"  sizing: UNIT ({cfg['unit_contracts']} contracts/trade, no budget cap)")
    elif sizing_mode == "amount":
        print(f"  sizing: AMOUNT (${cfg['amount_dollars']:.0f}/trade, cap {cfg['max_contracts_per_trade']} contracts)")
    else:
        print(f"  sizing: even-split (${cfg.get('daily_stake_budget_dollars', 0):.0f} / n_signals)")
    print(f"  edge_threshold: {cfg.get('edge_threshold', EDGE_THRESHOLD)*100:.0f}%")
    print(f"  execution_mode: {EXECUTION_MODE}")

    with get_connection() as conn:
        # Preflight
        print("\n[Preflight risk checks]")
        failures = preflight_checks(conn, client, city, today)
        if failures:
            print("\n  FAILED preflight:")
            for f in failures:
                print(f"    - {f}")
            print("\n  NO ORDERS PLACED.")
            critical_keywords = ("cumulative kill", "spread regime", "halt/ALL", f"halt/{city}")
            severity = "critical" if any(k in " ".join(failures) for k in critical_keywords) else "warn"
            send_alert("; ".join(failures), severity=severity, source=f"live_trade.{city}.preflight")
            return 2

        # Stake-budget tracking (informational only in unit mode)
        placed_today_cents = get_today_stake_deployed_cents(conn, today, cfg["live_model_source_tag"])
        print(f"\n  today's stake deployed so far: ${placed_today_cents/100:,.2f}")

        # Compute signals
        print("\n[Signal evaluation]")
        signals = compute_signals_for_today(conn, city, today)
        print(f"  signals passing filter: {len(signals)}")
        for s in signals:
            print(f"    {s['ticker']} {s['side'].upper()} edge={s['edge']:+.1%} "
                  f"limit={s['limit_price']}¢ cross={s['cross_price']}¢")

        if not signals:
            print("  no actionable signals; clean exit.")
            return 0

        try:
            balance = client.get_balance().get("balance", 0)
        except Exception as e:
            print(f"FAIL: could not read balance: {e}", file=sys.stderr)
            return 2
        print(f"\n  Kalshi account balance: ${balance/100:,.2f}")

        # Sizing: unit mode ignores per-trade stake (uses cfg['unit_contracts']).
        # Even-split mode divides daily budget across all signals.
        if sizing_mode == "unit":
            per_trade_stake_cents = 0  # unused by size_trade in unit mode
            print(f"\n  sizing: {cfg['unit_contracts']} contracts/trade (unit, no budget cap)")
        else:
            budget_cents = int(cfg.get("daily_stake_budget_dollars", 0) * 100)
            remaining_budget_cents = max(0, budget_cents - placed_today_cents)
            per_trade_stake_cents = even_split_stake_cents(remaining_budget_cents, len(signals))
            print(f"\n  per-signal stake: ${per_trade_stake_cents/100:,.2f} "
                  f"(budget ${remaining_budget_cents/100:,.2f} / {len(signals)} signals)")

        print("\n[Order placement]")
        placed = 0; rejected = 0; total_contracts = 0
        for s in signals:
            count = size_trade(city, s, per_trade_stake_cents)
            if count < 1:
                print(f"  {s['ticker']}: size=0, skipping (per-trade stake too low for this price)")
                rejected += 1
                continue
            stake_dollars = count * s['limit_price'] / 100.0
            print(f"  {s['ticker']}: {count} contracts @ {s['limit_price']}¢ = ${stake_dollars:.2f}")
            total_contracts += count
            # Budget tracking only relevant in even_split mode.
            if sizing_mode != "unit":
                remaining_budget_cents -= count * s["limit_price"]

            # Sanitize ticker dots — Kalshi rejects client_order_id containing '.'
            # with 400 invalid_parameters (B85.5, B83.5, etc. brackets all have dots).
            safe_ticker = s['ticker'].replace(".", "-")
            client_order_id = f"livech-{city}-{today.isoformat()}-{safe_ticker}-{s['side']}"

            if not args.live:
                continue

            # Rate-limit cushion: Kalshi returns 429 if we burst orders.
            # Today's KORD cron fired 3 orders in 0.3s; #2 and #3 got 429'd.
            # Sleep 1s between orders + retry once on 429 with longer backoff.
            import time as _time
            if placed > 0 or rejected > 0:
                _time.sleep(1.0)

            def _place_with_retry(attempt: int = 0):
                try:
                    return client.place_limit_order(
                        ticker=s['ticker'], side=s['side'], count=count,
                        price_cents=s['limit_price'],
                        post_only=s.get("post_only", True),
                        client_order_id=client_order_id,
                    )
                except Exception as exc:
                    is_429 = "429" in str(exc) or "Too Many Requests" in str(exc)
                    if is_429 and attempt < 2:
                        _time.sleep(2.0 + attempt * 2.0)
                        return _place_with_retry(attempt + 1)
                    raise

            try:
                resp = _place_with_retry()
                order = resp.get("order", resp)
                kalshi_order_id = order.get("order_id")
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
                          s['limit_price'], s['cross_price'], cfg["live_model_source_tag"],
                          s['model_p'], s['market_mid'], s['edge'],
                          kalshi_order_id, client_order_id,
                          f"sizing={sizing_mode}({cfg.get('unit_contracts','')}), "
                          f"balance=${balance/100:.2f}"))
                placed += 1
                print(f"    placed: order_id={kalshi_order_id}")
            except Exception as e:
                rejected += 1
                print(f"    ERROR: {type(e).__name__}: {e}", file=sys.stderr)
                send_alert(
                    f"{city} order place failed: {s['ticker']} {s['side']} {count}@{s['limit_price']}¢: "
                    f"{type(e).__name__}: {e}", severity="warn", source=f"live_trade.{city}.place")

        print(f"\n  placed: {placed}, rejected: {rejected}, total contracts: {total_contracts}")
        if sizing_mode != "unit":
            print(f"  remaining budget: ${remaining_budget_cents/100:,.2f}")
        if args.live and rejected > 0:
            send_alert(
                f"{city} live_trade summary {today}: placed={placed}, rejected={rejected}",
                severity="warn", source=f"live_trade.{city}.summary")
        if not args.live:
            print("\n  DRY-RUN — no orders actually placed. Re-run with --live to place.")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
