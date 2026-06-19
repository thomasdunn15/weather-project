"""LIVE trading cron entry point (multi-city, per docs/decisions/precommits/chicago-miami-live.md).

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
# PRE-COMMITTED PARAMETERS — see docs/decisions/precommits/chicago-miami-live.md
# ====================================================================

EDGE_THRESHOLD = 0.10        # DEFAULT — per-city cfg['edge_threshold'] overrides
WINDOW_DAYS = 45
INIT_HOUR = 0
MODELS_LIST_DEFAULT = ["gefs", "ifs"]  # DEFAULT — per-city cfg['models'] overrides

# Per-city config. Constants here MUST NOT be edited mid-window — see pre-commit doc.
#
# REVISION 2026-06-07: Chicago resumes after halt with tighter, smaller config.
# Per docs/decisions/precommits/chicago-resume-2026-06-07.md:
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
        #
        # REVISION 2026-06-09 (third): UNION MODE.
        # Trade fires if EITHER raw_edge ≥ 25% OR blend_edge ≥ 10%.
        # When both fire, they always agree on side (verified across 188 such
        # historical signals — zero disagreements). When only raw fires (86
        # cases), use raw side. When only blend fires (25 cases), use blend.
        # Backtest at unit=500 + market+1¢ + full sample (n=872 paper_trades):
        #   RAW only:     n=274, Sharpe 3.89, total +$61,700, p=0.00003
        #   BLEND only:   n=213, Sharpe 3.79, total +$47,620, p=0.00030
        #   UNION:        n=299, Sharpe 3.94, total +$67,480, p=0.00001  ← winner
        # Adds 86 raw-only + 25 blend-only trades on top of the 188 overlap.
        # Risk envelope (kill/halt thresholds) UNCHANGED.
        "models": ["gefs", "ifs", "hrrr"],
        "emos_model": "combined_hrrr",
        "model_source": "EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        "paper_model_source": "EMOS combined_hrrr 00Z Chicago (rolling 45d)",
        "live_model_source_tag": "EMOS combined_hrrr UNION raw25+blend10 00Z Chicago (rolling 45d) [LIVE]",
        "decision_hour": 14,
        "decision_minute": 46,
        "use_union": True,                      # NEW 2026-06-09: union of raw + blend
        "use_blend": True,                      # blend coefficients still computed
        "edge_threshold": 0.25,                 # raw threshold (25%)
        "blend_edge_threshold": 0.10,           # blend threshold (10%)
        "smart_cross_edge_threshold": 0.40,     # exec: cross at ≥40% edge (union raw edges get big; keep maker savings on the long tail)
        # REVISION 2026-06-09: switched from "amount" $50 → "unit" 500 contracts.
        # Backtest at unit=500 + blend@15% + market+1¢: Sharpe 3.88, +517% return.
        # Per-trade stake now scales with entry price: 500 contracts × entry/100
        # ($150 at 30¢, $250 at 50¢, $400 at 80¢). Bigger per-trade risk but
        # better Sharpe (more contracts per trade → more diversification within day).
        # Daily/cumulative limits unchanged — they'll halt sooner if a string of
        # losses hits, which is the desired safety behavior.
        "sizing_mode": "unit",                  # changed from "amount"
        "unit_contracts": 500,                  # changed from 200 → matches backtest config
        "amount_dollars": 50.0,                 # unused now (kept for reference)
        "max_contracts_per_trade": 500,         # depth cap (same as unit_contracts — no over-bet)
        "daily_loss_limit_dollars":    150.0,   # UP from $75 (matches 3 × $50)
        "cumulative_kill_dollars":     500.0,   # UP from $200 (more runway at higher sizing)
        "max_open_contracts":         5000,
        "is_active": True,                      # dashboard status indicator
    },
    "KMIA": {
        "city_name": "Miami",
        # RESUMED 2026-06-10 per docs/decisions/precommits/miami-resume-2026-06-10.md.
        # Original halt (2026-06-04) was based on RAW strategy showing t=-0.49
        # over the prior 90 days. Rolling 90-day BLEND backtest at 10% edge
        # shows consistent profitability across all 7 windows (t=+4.10 to
        # +9.21), passes Bonferroni for 6-city correction. Most recent 90-day
        # window: t=+4.10, +$16.53, 61% wins (n=61).
        # SIZING: matches KORD framework — unit=500 contracts. Earlier draft
        # used Amount $15/trade ("conservative"); user noted it under-deployed
        # given Miami's t-stat strength. Same 500-unit sizing as KORD on the
        # rationale that Miami's edge is comparable per trade.
        "models": ["gefs", "ifs"],
        "emos_model": "combined",
        "model_source": "EMOS combined 00Z Miami (rolling 45d)",
        "paper_model_source": "EMOS combined 00Z Miami (rolling 45d)",
        "live_model_source_tag": "EMOS combined BLEND-only 00Z Miami (rolling 45d) [LIVE]",
        "decision_hour": 15,
        "decision_minute": 30,
        "use_union": False,                     # BLEND ONLY (raw has no edge)
        "use_blend": True,
        "edge_threshold": 1.00,                 # raw threshold disabled (impossibly high)
        "blend_edge_threshold": 0.10,           # the only filter that fires (UNCHANGED — same trades fire)
        "smart_cross_edge_threshold": 0.10,     # exec: cross at ≥10% edge. Blend edges are ~10-15%; the
                                                # default 40% meant KMIA NEVER crossed → passive maker orders
                                                # chronically missed fills (2026-06-17). This makes the trades
                                                # the 10% filter already selects actually take liquidity.
        "sizing_mode": "unit",                  # matches KORD framework
        "unit_contracts": 500,                  # matches KORD: same backtest-validated unit
        "amount_dollars": 50.0,                 # unused (sizing_mode=unit)
        "max_contracts_per_trade": 500,         # depth cap (= unit_contracts)
        "daily_loss_limit_dollars":    150.0,   # matches KORD
        "cumulative_kill_dollars":     500.0,   # matches KORD
        "max_open_contracts":         5000,     # matches KORD
        "is_active": True,                      # RESUMED per precommit doc
    },
}

# Aggregate (cross-city) limits.
AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS = 300.0    # = Chicago $150 + Miami $150
AGGREGATE_CUMULATIVE_KILL_DOLLARS = 1000.0    # = Chicago $500 + Miami $500
SPREAD_REGIME_MAX_CENTS = 5.0

# Execution: how aggressive to be with the limit price when placing.
# "post_inside_spread"   = post 1c inside spread (maker fee, no taker fee).
#                         May fail to fill if no one takes our offer. Cost on
#                         2026-06-10: T90 trade (88.7% edge) got 0 fills because
#                         spread was 2¢ wide.
# "cross_at_ask"         = post AT the ask (= taker). Gets all available book
#                         depth immediately; remainder rests.
# "cross_with_premium"   = post at ask + premium cents to walk the book.
# "smart"                = edge-aware: cross at ask for high-edge trades (don't
#                         risk missing the fill), post_inside_spread for moderate
#                         edges (capture spread savings on the long tail).
#                         Threshold: |edge| ≥ SMART_CROSS_EDGE_THRESHOLD.
# Revised 2026-06-10 — switched to "smart". Past empirical data:
#   post_inside_spread:    75% fill rate, +$35.19/filled, +291% final, -24% DD
#   cross_at_ask:          99% fill rate, +$6.27/filled,  +69% final,  -66% DD
# Smart mode aims to keep post_inside's per-trade profit while plugging the
# "missed huge edge" hole that bit us on T90. For high-edge trades, the
# expected profit on filling vs. the small spread savings is overwhelmingly
# tilted toward filling.
EXECUTION_MODE = "smart"
CROSS_PREMIUM_CENTS = 0
SMART_CROSS_EDGE_THRESHOLD = 0.40   # |edge| ≥ 40% → cross at ask, else post inside

# Full expected ensemble per model (what NOAA/ECMWF publish). The pre-trade
# guard refuses to trade unless every configured model has ALL its members —
# a partial ensemble under-estimates spread → overconfident bracket probs.
EXPECTED_MEMBERS = {"gefs": 31, "ifs": 50, "hrrr": 1}


def resolve_exec_path(execution_mode: str, edge: float,
                      cross_threshold: float = SMART_CROSS_EDGE_THRESHOLD) -> str:
    """Map (EXECUTION_MODE, signal edge) → concrete execution path.

    'smart' is edge-aware: cross at ask when |edge| ≥ cross_threshold (don't
    risk missing the fill), post inside the spread below it (capture spread
    savings). All other modes pass through unchanged.

    cross_threshold is per-city (CITY_CONFIG[city]['smart_cross_edge_threshold'],
    default SMART_CROSS_EDGE_THRESHOLD). KMIA is blend-only with inherently
    small edges (~10-15%); with the default 40% it would NEVER cross and its
    passive maker orders chronically missed fills (2026-06-17), so it gets a
    low threshold to actually take liquidity. NOTE: this is an EXECUTION knob
    only — it does not change which signals fire (that's the edge filter)."""
    if execution_mode == "smart":
        if abs(edge) >= cross_threshold:
            return "cross_at_ask"
        return "post_inside_spread"
    return execution_mode


def incomplete_ensembles(present: dict, models_list: list) -> list[str]:
    """Return ['gefs=15/31', ...] for every configured model whose ensemble
    is short of EXPECTED_MEMBERS. Empty list = safe to trade."""
    out = []
    for m in models_list:
        have = int(present.get(m, 0))
        want = EXPECTED_MEMBERS.get(m, 1)
        if have < want:
            out.append(f"{m}={have}/{want}")
    return out


def best_cross_price_from_book(book_resp: dict, side: str) -> int | None:
    """Taker (cross) price in cents to immediately buy `side` from a Kalshi
    orderbook response, or None if that side has no resting depth.

    Kalshi books list YES bids and NO bids separately; an "ask" is the opposite
    side's best bid. To BUY YES you lift the best YES ask = 100 − best NO bid.
    To BUY NO, 100 − best YES bid. Handles both the current
    `orderbook_fp.{yes,no}_dollars` shape and the legacy `orderbook.{yes,no}`."""
    book = book_resp.get("orderbook_fp") or book_resp.get("orderbook") or {}
    yes_levels = book.get("yes_dollars") or book.get("yes") or []
    no_levels = book.get("no_dollars") or book.get("no") or []

    def _best_bid(levels):
        best = None
        for lvl in levels:
            try:
                c = int(round(float(lvl[0]) * 100))
            except (TypeError, ValueError, IndexError):
                continue
            if 1 <= c <= 99 and (best is None or c > best):
                best = c
        return best

    opposite = _best_bid(no_levels) if side == "yes" else _best_bid(yes_levels)
    return (100 - opposite) if opposite is not None else None


def fetch_live_cross_price(client, ticker: str, side: str) -> int | None:
    """Re-fetch the live order book and return the current cross price (cents)
    for `side`, or None if unavailable. Used to reprice a maker order the
    exchange rejected for would-crossing so it can be resubmitted as a taker."""
    try:
        ob = client.get_orderbook(ticker)
    except Exception:
        return None
    return best_cross_price_from_book(ob, side)


def place_with_guaranteed_fill(client, *, ticker, side, count, limit_price,
                               cross_price, primary_post_only, client_order_id,
                               sleep=lambda _s: None):
    """Place an order, guaranteeing it lands on the exchange.

    Tries the intended (usually maker / post_only) order first. If the exchange
    rejects it — the common case being a post_only order the book has moved
    under so it would now cross — resubmit as a TAKER (post_only=False) at the
    current ask. A would-cross rejection on a BUY only happens when price moved
    toward us, so the taker price is at-or-below our original limit; we never
    overpay past what we already wanted.

    Pure of the database and of wall-clock (sleep is injected) so it can be
    unit-tested with a fake client. Returns:
        (status, price_used, kalshi_order_id, client_order_id_used, note_suffix)
    status is 'placed' or 'rejected'. The caller records the result to the DB —
    keeping placement (which must never be retried blindly) separate from
    recording (which is idempotent and safe to fail)."""
    def _place(price, post_only_flag, coid, attempt=0):
        try:
            return client.place_limit_order(
                ticker=ticker, side=side, count=count, price_cents=price,
                post_only=post_only_flag, client_order_id=coid,
            )
        except Exception as exc:
            is_429 = "429" in str(exc) or "Too Many Requests" in str(exc)
            if is_429 and attempt < 2:
                sleep(2.0 + attempt * 2.0)
                return _place(price, post_only_flag, coid, attempt + 1)
            raise

    try:
        resp = _place(limit_price, primary_post_only, client_order_id)
        koid = resp.get("order", resp).get("order_id")
        return ("placed", limit_price, koid, client_order_id, "")
    except Exception as e_primary:
        # A taker order that fails isn't a would-cross race — don't loop on it.
        if not primary_post_only:
            return ("rejected", limit_price, None, client_order_id,
                    f"REJECTED: {type(e_primary).__name__}: {str(e_primary)[:200]}")
        live_cross = fetch_live_cross_price(client, ticker, side) or cross_price
        cross_coid = f"{client_order_id}-x"
        sleep(1.0)  # rate-limit cushion before the retry
        try:
            resp = _place(live_cross, False, cross_coid)
            koid = resp.get("order", resp).get("order_id")
            return ("placed", live_cross, koid, cross_coid,
                    f"; cross-fallback after post_only would-cross "
                    f"({type(e_primary).__name__})")
        except Exception as e_cross:
            return ("rejected", limit_price, None, client_order_id,
                    f"REJECTED (incl. cross-fallback): "
                    f"{type(e_cross).__name__}: {str(e_cross)[:200]}")


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

    # CRITICAL: verify EVERY configured model has its FULL ensemble at this
    # init_time. Two failure modes this guards against:
    #   1. Entire model missing (e.g. GEFS 00Z silently failed) — that's what
    #      contributed to yesterday's -$114 loss
    #   2. Partial ensemble (e.g. GEFS got 15 of 31 members before DB blip) —
    #      the model would average over fewer members → narrower ensemble
    #      spread → overconfident bracket probabilities → oversized bets that
    #      shouldn't have fired. User flagged 2026-06-11: with full GEFS, the
    #      90-91°F NO bet (which lost $315) would have shown only -4% blend
    #      edge and would NOT have fired.
    # Expected member counts per model: see module-level EXPECTED_MEMBERS.
    with conn.cursor() as cur:
        cur.execute(
            """SELECT model, COUNT(DISTINCT member_id) AS n_members FROM forecasts
               WHERE station_id=%s AND model=ANY(%s) AND init_time=%s
               GROUP BY model""",
            (city, models_list, init_time),
        )
        present = {m: int(n) for m, n in cur.fetchall()}
    incomplete = incomplete_ensembles(present, models_list)
    if incomplete:
        print(f"  HALT: incomplete forecast ensembles at init {init_time.isoformat()}: "
              f"{incomplete}. Have: {present}, expected: "
              f"{ {m: EXPECTED_MEMBERS.get(m, 1) for m in models_list} }. "
              f"Refusing to trade on partial ensemble — model uncertainty would be "
              f"under-estimated, leading to overconfident bracket probabilities.")
        return []
    print(f"  forecast data check OK: {present} (expected "
          f"{ {m: EXPECTED_MEMBERS.get(m, 1) for m in models_list} })")

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

    # Signal mode selection:
    #   UNION    — fire if raw_edge ≥ raw_threshold OR blend_edge ≥ blend_threshold
    #   BLEND    — fire only on blend signal
    #   RAW      — fire only on raw model signal (default)
    use_union = cfg.get("use_union", False)
    use_blend = cfg.get("use_blend", False) or use_union
    blend_fit = None
    if use_blend:
        from weather_markets.blend import get_blend
        blend_fit = get_blend(city, cfg["city_name"], cfg["paper_model_source"])
        if blend_fit is None:
            print(f"  blend unfittable (need ≥100 settled paper_trades); FALLING BACK to raw model edge only")
            use_blend = False
            use_union = False
        else:
            print(f"  BLEND fit: α={blend_fit.alpha:+.3f} β_m={blend_fit.beta_model:+.3f} β_mkt={blend_fit.beta_market:+.3f} "
                  f"(mkt share {blend_fit.market_share()*100:.0f}%, n_train={blend_fit.n_train})")
    raw_thresh = cfg.get("edge_threshold", EDGE_THRESHOLD)
    blend_thresh = cfg.get("blend_edge_threshold", 0.10)
    if use_union:
        print(f"  UNION MODE ACTIVE: fire if |raw_edge| ≥ {raw_thresh:.0%} OR |blend_edge| ≥ {blend_thresh:.0%}")
    elif use_blend:
        print(f"  BLEND ONLY: fire if |blend_edge| ≥ {blend_thresh:.0%}")
    else:
        print(f"  RAW MODEL ONLY: fire if |raw_edge| ≥ {raw_thresh:.0%}")

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
        # Compute raw + blend edges. UNION fires if either passes threshold.
        raw_edge = model_p - market_mid
        blend_p = float(blend_fit.predict(model_p, market_mid)) if blend_fit else None
        blend_edge = (blend_p - market_mid) if blend_p is not None else None
        raw_fires = abs(raw_edge) >= raw_thresh
        blend_fires = (blend_edge is not None) and (abs(blend_edge) >= blend_thresh)
        # Decide whether to act based on mode
        if use_union:
            if not (raw_fires or blend_fires):
                continue
            # Use raw side preferentially when it fires (they always agree
            # historically when both fire; use raw's prob for Kelly etc.)
            if raw_fires:
                decision_p = model_p
                edge = raw_edge
                signal_source = "union_both" if blend_fires else "union_raw_only"
            else:
                decision_p = blend_p
                edge = blend_edge
                signal_source = "union_blend_only"
        elif use_blend:
            if not blend_fires:
                continue
            decision_p = blend_p
            edge = blend_edge
            signal_source = "blend"
        else:
            if not raw_fires:
                continue
            decision_p = model_p
            edge = raw_edge
            signal_source = "raw"
        if edge > 0:
            side = "yes"
            cross_entry = int(ask)
            p_win = decision_p
        else:
            side = "no"
            cross_entry = 100 - int(bid)
            p_win = 1 - decision_p
        # NO MIN ENTRY FILTER (matches pre-committed cell entry>=0)

        # Set limit_price + post_only flag according to EXECUTION_MODE.
        spread = int(ask) - int(bid)
        exec_path = resolve_exec_path(
            EXECUTION_MODE, edge,
            cfg.get("smart_cross_edge_threshold", SMART_CROSS_EDGE_THRESHOLD),
        )

        if exec_path == "post_inside_spread":
            if spread > 1:
                if side == "yes":
                    limit_price = int(ask) - (spread - 1)
                else:
                    limit_price = (100 - int(bid)) - (spread - 1)
                post_only_safe = True
            else:
                limit_price = cross_entry
                post_only_safe = False
        elif exec_path == "cross_at_ask":
            # Post AT the ask = guaranteed taker on existing depth; remainder
            # rests at that price. Better fill rate vs post-inside-spread.
            limit_price = cross_entry
            post_only_safe = False
        elif exec_path == "cross_with_premium":
            # Walk the book up to CROSS_PREMIUM_CENTS beyond the ask.
            limit_price = cross_entry + CROSS_PREMIUM_CENTS
            post_only_safe = False
        else:
            raise ValueError(f"Unknown EXECUTION_MODE/exec_path: {EXECUTION_MODE!r}/{exec_path!r}")
        limit_price = max(1, min(99, limit_price))

        signals.append({
            "ticker": ticker, "side": side, "limit_price": limit_price,
            "cross_price": cross_entry, "model_p": model_p,
            "blend_p": blend_p,                                # always recorded if blend fit available
            "raw_edge": raw_edge, "blend_edge": blend_edge,
            "signal_source": signal_source,                    # union_both / union_raw_only / union_blend_only / raw / blend
            "exec_path": exec_path,                            # what smart resolved to: cross_at_ask / post_inside_spread / etc
            "market_mid": market_mid, "edge": edge, "p_win": p_win,
            "post_only": post_only_safe,
        })

    # Sort by edge magnitude DESCENDING for display purposes only.
    # Even-split sizing means budget is divided equally regardless of order.
    signals.sort(key=lambda s: -abs(s["edge"]))
    # NOTE: anti-stacking control was added 2026-06-10 evening and reverted
    # later the same day — historical backtest showed it net-negative for
    # Sharpe on both cities. Today's stacked loss was a tail event, not
    # structural correlated risk. Code kept clean (no cap field) since the
    # dashboard backtest still offers it as a what-if toggle.
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
    # NOTE: edge-cap-for-sizing was added 2026-06-10 evening and reverted later
    # the same day. Backtest showed it net-negative — high-edge trades win at
    # the highest rate, so capping their stake removes positive EV. Dashboard
    # backtest still offers it as a what-if toggle for exploration.
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
            ep = s.get("exec_path", EXECUTION_MODE)
            print(f"    {s['ticker']} {s['side'].upper()} edge={s['edge']:+.1%} "
                  f"limit={s['limit_price']}¢ cross={s['cross_price']}¢ "
                  f"[exec={ep}]")

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
            # Sleep 1s between orders.
            import time as _time
            if placed > 0 or rejected > 0:
                _time.sleep(1.0)

            base_note = (f"sizing={sizing_mode}({cfg.get('unit_contracts','')}), "
                         f"balance=${balance/100:.2f}")

            def _insert_trade(price_cents, koid, coid, status, note):
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO live_trades (
                            placed_at, target_date, ticker, side, count,
                            limit_price_cents, cross_price_cents, model_source,
                            model_prob_yes, market_mid_prob, edge,
                            kalshi_order_id, client_order_id, fill_status, notes
                        ) VALUES (NOW(), %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (client_order_id) DO NOTHING
                    """, (today, s['ticker'], s['side'], count,
                          price_cents, s['cross_price'], cfg["live_model_source_tag"],
                          s['model_p'], s['market_mid'], s['edge'],
                          koid, coid, status, note))

            # PLACEMENT (network) is kept separate from RECORD (DB): a DB error
            # after a successful placement must never bounce us into a retry that
            # double-places on the exchange.
            status, price_used, kalshi_order_id, coid_used, note_suffix = \
                place_with_guaranteed_fill(
                    client, ticker=s['ticker'], side=s['side'], count=count,
                    limit_price=s['limit_price'], cross_price=s['cross_price'],
                    primary_post_only=bool(s.get("post_only", True)),
                    client_order_id=client_order_id, sleep=_time.sleep,
                )

            if status == "placed":
                placed += 1
                if note_suffix.startswith(";"):  # cross-fallback path
                    print(f"    placed (cross-fallback) @ {price_used}¢: order_id={kalshi_order_id}")
                else:
                    print(f"    placed: order_id={kalshi_order_id}")
                try:
                    _insert_trade(price_used, kalshi_order_id, coid_used,
                                  "pending", base_note + note_suffix)
                except Exception as db_e:
                    # Order IS on Kalshi; reconcile_live_trades recovers it by
                    # client_order_id. Do not re-place.
                    print(f"    (placed but DB insert failed; reconcile will recover: {db_e})",
                          file=sys.stderr)
            else:
                rejected += 1
                # Persist the rejection so it's visible on the dashboard /
                # reconcile — previously a rejected order left no DB trace,
                # making it look like the bot never tried the signal.
                try:
                    _insert_trade(s['limit_price'], None, client_order_id,
                                  "rejected", f"{base_note} | {note_suffix}")
                except Exception as db_e:
                    print(f"    (could not persist rejected row: {db_e})", file=sys.stderr)
                print(f"    ERROR: {note_suffix}", file=sys.stderr)
                send_alert(
                    f"{city} order place failed (incl. cross-fallback): "
                    f"{s['ticker']} {s['side']} {count}@{s['limit_price']}¢: {note_suffix}",
                    severity="warn", source=f"live_trade.{city}.place")

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
