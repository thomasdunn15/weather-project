"""Weather forecasting dashboard.

Run with: uv run streamlit run scripts/dashboard.py

Two tabs:
  - Analysis: backtests, calibration, diagnostics (the existing panels)
  - Trading:  today's combined+EMOS forecast vs Kalshi prices, with edge highlighting
"""
import math
import random
import statistics
from datetime import datetime, date, timezone, timedelta

import streamlit as st
import altair as alt
import pandas as pd

from weather_markets.db import get_connection
from weather_markets.aggregation import (
    compute_daily_highs,
    compute_combined_daily_highs,
    compute_ensemble_probabilities,
    fetch_observed_high,
    fetch_contracts_for_date,
    collect_training_pairs,
)
from weather_markets.emos import fit_emos, gaussian_to_bracket_probs, fit_emos_rolling
from weather_markets.evaluation import (
    evaluate_predictions,
    contract_resolved_yes,
    brier_score,
    calibration_bins,
)
from weather_markets.stations import all_stations, get as get_station

# set_page_config MUST be the first Streamlit call, before tabs or any other st.* call.
st.set_page_config(
    page_title="Kalshi Weather Trading",
    page_icon="🌡️",
    layout="wide",
)

# Strip Streamlit's default chrome so the redesigned dashboard fills the viewport
# edge-to-edge with no visible iframe border or container padding.
st.markdown("""
<style>
    /* Kill all padding/margin in main container, go truly full-width */
    .main .block-container {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        max-width: 100% !important;
    }
    /* Remove iframe borders (the box around components.html embeds) */
    iframe { border: none !important; }
    [data-testid="stIFrame"] { border: none !important; padding: 0 !important; }
    /* Tighten tab bar — give Live Trading + Backtest proper gap */
    .stTabs [data-baseweb="tab-list"] {
        gap: 18px !important;
        padding-left: 18px;
        background-color: transparent !important;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 4px !important;
        background-color: transparent !important;
    }
    /* Streamlit's top header bar (where Deploy lives) — match dashboard bg */
    [data-testid="stHeader"], header[data-testid="stHeader"] {
        background-color: #14130e !important;
    }
    [data-testid="stToolbar"] { background-color: transparent !important; }
    /* Hide default Streamlit footer */
    footer { display: none !important; }
    /* Make every Streamlit container surface match the dashboard bg */
    [data-testid="stAppViewContainer"], .main, .stApp,
    [data-testid="stMainBlockContainer"] {
        background-color: #14130e !important;
    }
    /* Reduce vertical gap between Streamlit elements */
    div[data-testid="stVerticalBlock"] > div { gap: 0 !important; }
</style>
""", unsafe_allow_html=True)


# =====================================================================
# SHARED DATA LAYER (cached) — defined above the tabs so both can use it
# =====================================================================


@st.cache_data
def collect_combined_training_data(station_id: str = "KNYC"):
    """Collect COMBINED (GEFS+ECMWF) ensemble stats over the full year for EMOS fitting."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id = %s", (station_id,))
            end = cur.fetchone()[0]
        return collect_training_pairs(
            conn, date(2025, 5, 1), end,
            station_id=station_id, models=["gefs", "ifs"],
        )


@st.cache_data
def fit_combined_emos(station_id: str = "KNYC"):
    """Fit EMOS once on the full-year combined ensemble. Returns params dict."""
    means, stds, obs, dates = collect_combined_training_data(station_id=station_id)
    if len(means) < 10:
        return None
    return fit_emos(means, stds, obs)


@st.cache_data(ttl=3600)
def fit_emos_rolling_cached(trade_date, window_days=45, model="combined", init_hour=12, station_id: str = "KNYC"):
    """Cached rolling-window EMOS fit. Returns None when fewer than min_train_days
    (default 30) effective training days are available.

    Defaults match the 12Z combined workflow. Pass model="ifs", init_hour=0 for
    the 00Z ECMWF workflow used by market-open paper trading."""
    with get_connection() as conn:
        return fit_emos_rolling(
            trade_date, conn,
            window_days=window_days, station_id=station_id,
            model=model, init_hour=init_hour,
        )


@st.cache_data(ttl=10)
def paper_trades_with_outcomes(limit: int = 500):
    """Pull paper trades joined with contracts and observations.

    Returns DataFrame with outcome resolution columns: contract_yes_resolved,
    won, pnl_cents_per_unit. Unresolved trades (observation hasn't landed yet)
    have None for those columns. Sorted by target_date DESC, logged_at DESC.

    Filters target_date >= 2025-05-27 to exclude the pre-Nov-2024 wide-spread
    regime (mean spread 20¢ vs current ~3¢). Year-2 backfill data IS in the DB
    under the same model_source, but the spread environment was so different
    (median spread 8¢, 30% of trades had spread ≥20¢) that pooling it with the
    current tight-spread regime would conflate two different markets. Cutoff
    aligned with the year-1 production backfill start.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pt.target_date, pt.logged_at, pt.ticker, pt.model_source,
                       pt.model_prob_yes, pt.market_mid_prob, pt.edge,
                       pt.position, pt.entry_price_cents,
                       pt.market_yes_bid, pt.market_yes_ask,
                       c.bracket_type, c.strike_low, c.strike_high,
                       o.high_temp_f
                FROM paper_trades pt
                JOIN contracts c ON c.ticker = pt.ticker
                -- LATERAL subquery is a TimescaleDB workaround: the planner
                -- silently returns wrong results when LEFT JOIN'ing a hypertable
                -- (observations) on a key that references another table's column
                -- (c.station_id). Wrapping observations in LATERAL forces row-wise
                -- evaluation and gives correct results.
                LEFT JOIN LATERAL (
                    SELECT high_temp_f FROM observations
                    WHERE date = pt.target_date AND station_id = c.station_id
                    LIMIT 1
                ) o ON TRUE
                WHERE pt.target_date >= '2025-05-27'
                ORDER BY pt.target_date DESC, pt.logged_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df

    def resolve(row):
        if pd.isna(row["high_temp_f"]):
            return pd.Series({"won": None, "pnl_cents_per_unit": None})
        contract = {
            "bracket_type": row["bracket_type"],
            "strike_low": row["strike_low"],
            "strike_high": row["strike_high"],
        }
        resolved_yes = contract_resolved_yes(int(row["high_temp_f"]), contract)
        won = resolved_yes if row["position"] == "BUY_YES" else (not resolved_yes)
        pnl = (100 - row["entry_price_cents"]) if won else (-row["entry_price_cents"])
        return pd.Series({"won": won, "pnl_cents_per_unit": pnl})

    enriched = df.apply(resolve, axis=1)
    return pd.concat([df, enriched], axis=1)


def _kelly_fraction(p_win: float, entry_price_cents: int) -> float:
    """Full Kelly fraction for a binary contract. Returns 0 if no positive edge."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0.0
    b = (100 - entry_price_cents) / entry_price_cents
    f = p_win - (1 - p_win) / b
    return max(0.0, f)


def _apply_stake_cap(
    raw_stake: float,
    balance: float,
    max_stake_pct: float | None,
    max_stake_dollars: float | None,
) -> tuple[float, bool]:
    """Clamp `raw_stake` to whichever cap binds (pct of bankroll, $ ceiling).
    Returns (clamped_stake, was_capped). A None cap is treated as +inf.

    Required because uncapped Kelly bets the model's full conviction (up to
    100% of bankroll on near-certain trades), which guarantees ruin on one
    loss. Scaling needs it too: at high overfit means, 5% compounds to fantasy
    multi-billion balances unreachable at Kalshi depth (~$1k per side)."""
    pct_cap = balance * max_stake_pct if max_stake_pct is not None else float("inf")
    dollar_cap = max_stake_dollars if max_stake_dollars is not None else float("inf")
    cap = min(pct_cap, dollar_cap)
    if raw_stake > cap:
        return cap, True
    return raw_stake, False


def kalshi_fee_cents(entry_price_cents: int) -> int:
    """Kalshi trading fee per contract in cents.

    Formula (per Kalshi docs): $0.07 × contracts × P × (1−P), rounded UP to the
    nearest $0.01 per fill. Charged on the entry trade only; no fee at settlement.
    Returns 0 for degenerate prices (≤0 or ≥100)."""
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return 0
    p = entry_price_cents / 100.0
    fee_dollars = 0.07 * p * (1.0 - p)
    return max(1, math.ceil(fee_dollars * 100))


@st.cache_data(ttl=300)
def compute_empirical_fills_for_trades(trade_keys: tuple, modes: tuple = ("post_inside_spread", "cross_at_ask", "cross_with_premium_1")) -> dict:
    """For each trade key (ticker, target_date, side, decision_time_iso, cross_entry_cents),
    compute fill outcome under each execution mode using the prices table.

    Returns dict: {trade_key: {mode: {"filled": bool, "fill_price": int|None, "limit_price": int}}}

    Caching keyed on (trade_keys, modes) — same tuple = same result.

    Mode semantics:
      - post_inside_spread: limit_price = cross - max(1, spread-1). Fills if yes/no_ask reaches
        that price after decision_time (or before EOD).
      - cross_at_ask: limit_price = cross. Assumed to fill at cross (top-of-book taker).
        We can't verify depth from snapshots, so this is a "would fill at the touch" assumption.
      - cross_with_premium_1: limit_price = cross + 1. Better fill than cross_at_ask;
        same caveat re: depth.
    """
    from datetime import datetime, time as dtime, timezone
    out = {}
    if not trade_keys:
        return out
    with get_connection() as conn, conn.cursor() as cur:
        for tk in trade_keys:
            ticker, target_date, side, decision_time_iso, cross_entry = tk
            decision_time = datetime.fromisoformat(decision_time_iso)
            # End of trading day — use end of target_date in UTC as cutoff
            eod = datetime.combine(target_date if isinstance(target_date, type(decision_time.date())) else decision_time.date(),
                                   dtime(23, 59), tzinfo=timezone.utc)
            # Pull all snapshots for this ticker between decision_time and EOD
            cur.execute("""
                SELECT yes_bid, yes_ask, no_bid, no_ask
                FROM prices
                WHERE ticker = %s AND snapshot_at > %s AND snapshot_at <= %s
                  AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL
            """, (ticker, decision_time, eod))
            snaps = cur.fetchall()

            # Need bid/ask AT decision time to compute spread (best estimate from first snap)
            cur.execute("""
                SELECT yes_bid, yes_ask
                FROM prices WHERE ticker = %s AND snapshot_at <= %s
                  AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL
                ORDER BY snapshot_at DESC LIMIT 1
            """, (ticker, decision_time))
            at_decision = cur.fetchone()
            if at_decision is None:
                # No price data at decision time — can't compute any mode
                out[tk] = {m: {"filled": False, "fill_price": None, "limit_price": 0} for m in modes}
                continue
            d_yes_bid, d_yes_ask = at_decision
            spread = max(1, int(d_yes_ask) - int(d_yes_bid))

            mode_out = {}
            for mode in modes:
                # Compute the limit price under this mode
                if mode == "post_inside_spread":
                    if spread > 1:
                        if side == "BUY_YES":
                            limit_price = max(1, int(d_yes_ask) - (spread - 1))
                        else:  # BUY_NO
                            limit_price = max(1, (100 - int(d_yes_bid)) - (spread - 1))
                    else:
                        # Falls back to cross since no room inside
                        limit_price = cross_entry
                elif mode == "cross_at_ask":
                    limit_price = cross_entry
                elif mode == "cross_with_premium_1":
                    limit_price = min(99, cross_entry + 1)
                else:
                    limit_price = cross_entry

                # Determine fill
                if mode in ("cross_at_ask", "cross_with_premium_1"):
                    # Taker — assume fills at the limit (depth-unverifiable)
                    mode_out[mode] = {"filled": True, "fill_price": limit_price, "limit_price": limit_price}
                else:  # post_inside_spread — empirically check
                    filled = False
                    for ybid, yask, nbid, nask in snaps:
                        if side == "BUY_YES" and yask is not None and int(yask) <= limit_price:
                            filled = True; break
                        if side == "BUY_NO" and nask is not None and int(nask) <= limit_price:
                            filled = True; break
                    mode_out[mode] = {"filled": filled, "fill_price": limit_price if filled else None, "limit_price": limit_price}
            out[tk] = mode_out
    return out


def simulate_pnl(
    df: pd.DataFrame,
    starting_balance: float,
    sizing_type: str,
    *,
    contracts: int = 1,
    kelly_fraction: float = 0.5,
    scaling_pct: float = 0.05,
    amount_dollars: float = 25.0,
    execution_mode: str = "cross",
    max_stake_pct: float | None = 0.05,
    max_stake_dollars: float | None = None,
    max_contracts_per_trade: int | None = None,
    empirical_fills: dict | None = None,
) -> pd.DataFrame:
    """Walk resolved trades chronologically and compute cumulative balance.

    sizing_type:
      - "unit"    — buy `contracts` contracts per trade (constant; ignores bankroll).
      - "amount"  — stake = `amount_dollars` per trade (constant; ignores bankroll).
                    Contracts = amount_dollars / (entry_price/100). Like unit, but
                    risks the same DOLLARS regardless of contract price — at 10c
                    entry you get 10x more contracts than at 100c entry.
      - "kelly"   — stake = bankroll × kelly_fraction × Kelly-optimal fraction;
                    bankroll compounds. Bets MORE on high-edge trades.
      - "scaling" — stake = bankroll × scaling_pct (fixed % of CURRENT bankroll);
                    bankroll compounds but the % is constant regardless of edge.
                    Risk-per-trade is deterministic; aggressiveness doesn't depend
                    on the model's confidence in any particular signal.

    max_stake_pct / max_stake_dollars: stake caps applied to Kelly and Scaling.
    Both are evaluated; the lower binds. Set either to None to disable that cap.
    Defaults to 5% of bankroll, matching live_trade.py's MAX_STAKE_DOLLARS
    ($50 on $1k bankroll). Without these caps, Kelly blows up to $0 when a
    near-1.0 model_prob says "bet 50%+ of bankroll" and that trade loses, and
    Scaling compounds to multi-billion fantasy numbers that can't actually be
    filled on Kalshi's ~$1k-depth markets.

    execution_mode:
      - "cross"      — pay the cross-spread (entry_price_cents). Always fills.
      - "limit_100"  — post 1¢ inside the spread, assume 100% fills.
      - "limit_70"   — same limit price, 70% deterministic fill rate.
      - "limit_50"   — same limit price, 50% deterministic fill rate.
      Missed limit fills produce $0 P&L (no fee, no exposure). Fill is
      seeded so the curve is deterministic across reruns.

    All P&L is net of Kalshi trading fees (per-contract entry fee).
    """
    resolved = (
        df[df["won"].notna()]
        .sort_values(["target_date", "logged_at"])
        .reset_index(drop=True)
    )

    # execution_mode names ending in "_emp_<mode>" use empirical fill lookup from
    # the precomputed dict. Format: "emp:post_inside_spread" / "emp:cross_at_ask" /
    # "emp:cross_with_premium_1". The fills dict is keyed by row index.
    is_empirical = execution_mode.startswith("emp:")
    emp_mode_key = execution_mode[4:] if is_empirical else None

    fill_rate = ({"cross": 1.0, "limit_100": 1.0, "limit_70": 0.7, "limit_50": 0.5}
                 .get(execution_mode, 1.0))
    rng = random.Random(42)

    history = [{"date": None, "balance": starting_balance, "trade_pnl": 0.0}]
    balance = starting_balance

    for idx, row in resolved.iterrows():
        cross_entry = int(row["entry_price_cents"])
        won = bool(row["won"])

        if is_empirical:
            # Empirical: limit_price + fill bool come from precomputed dict
            emp = (empirical_fills or {}).get(idx, {}).get(emp_mode_key)
            if emp is None:
                # Missing data — skip with $0 P&L
                entry = cross_entry
                empirical_did_fill = False
            else:
                entry = int(emp["limit_price"])
                empirical_did_fill = bool(emp["filled"])
        elif execution_mode == "cross":
            entry = cross_entry
        else:
            bid, ask = row["market_yes_bid"], row["market_yes_ask"]
            if pd.isna(bid) or pd.isna(ask) or ask <= bid + 1:
                # No room to post inside the spread — fall back to cross.
                entry = cross_entry
            else:
                entry = max(1, cross_entry - int(ask - bid - 1))

        # Bracket label for display (same logic as Edge by bracket table)
        bt = row.get("bracket_type")
        if bt == "greater_than":
            bracket_str = f">{int(row['strike_low'])}°"
        elif bt == "less_than":
            bracket_str = f"<{int(row['strike_high'])}°"
        else:
            bracket_str = f"{int(row['strike_low'])}-{int(row['strike_high'])}°"

        if is_empirical:
            filled = empirical_did_fill
        else:
            filled = rng.random() < fill_rate
        if not filled:
            history.append({
                "date": pd.Timestamp(row["target_date"]),
                "balance": balance,
                "trade_pnl": 0.0,
                "ticker": row.get("ticker"),
                "bracket": bracket_str,
                "side": row.get("position"),
                "edge": float(row.get("edge", 0)),
                "entry_price_cents": entry,
                "contracts": 0,
                "stake_dollars": 0.0,
                "won": bool(row["won"]),
                "filled": False,
            })
            continue

        fee_per_contract = kalshi_fee_cents(entry) / 100.0  # dollars

        was_capped = False  # only relevant for kelly/scaling; unit/amount ignore caps
        if sizing_type == "unit":
            num_contracts_actual = int(contracts)
            gross_pnl = contracts * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - contracts * fee_per_contract
            stake_dollars = contracts * entry / 100.0
        elif sizing_type == "amount":
            # Fixed dollars per trade — like unit but in $ instead of contract count.
            # Doesn't compound (uses amount_dollars, not bankroll-derived value).
            stake = float(amount_dollars)
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(num_contracts)  # round DOWN — never over-bet
            actual_stake = num_contracts_actual * entry / 100.0
            total_fee = num_contracts_actual * fee_per_contract
            gross_pnl = num_contracts_actual * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - total_fee
            stake_dollars = actual_stake
        elif sizing_type == "scaling":
            # Fixed % of CURRENT bankroll, no Kelly multiplier
            b = (100 - entry) / entry
            raw_stake = balance * scaling_pct
            stake, was_capped = _apply_stake_cap(raw_stake, balance, max_stake_pct, max_stake_dollars)
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(round(num_contracts))
            total_fee = num_contracts * fee_per_contract
            gross_pnl = stake * b if won else -stake
            trade_pnl = gross_pnl - total_fee
            stake_dollars = stake
        else:  # kelly
            p_win = row["model_prob_yes"] if row["position"] == "BUY_YES" else (1 - row["model_prob_yes"])
            b = (100 - entry) / entry
            f = _kelly_fraction(p_win, entry) * kelly_fraction
            raw_stake = balance * f  # dollars
            stake, was_capped = _apply_stake_cap(raw_stake, balance, max_stake_pct, max_stake_dollars)
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(round(num_contracts))
            total_fee = num_contracts * fee_per_contract
            gross_pnl = stake * b if won else -stake
            trade_pnl = gross_pnl - total_fee
            stake_dollars = stake

        # Apply max_contracts_per_trade depth cap if set. Models real-world
        # Kalshi book depth — beyond ~1500 contracts at the touch you'd get
        # partial fills, so cap the simulated position size to a realistic max.
        # Recompute stake / fees / pnl from the capped contract count.
        if max_contracts_per_trade is not None and num_contracts_actual > max_contracts_per_trade:
            num_contracts_actual = int(max_contracts_per_trade)
            stake_dollars = num_contracts_actual * entry / 100.0
            total_fee_capped = num_contracts_actual * fee_per_contract
            gross_pnl = num_contracts_actual * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - total_fee_capped

        balance += trade_pnl
        history.append({
            "date": pd.Timestamp(row["target_date"]),
            "balance": balance,
            "trade_pnl": trade_pnl,
            "ticker": row.get("ticker"),
            "bracket": bracket_str,
            "side": row.get("position"),
            "edge": float(row.get("edge", 0)),
            "entry_price_cents": entry,
            "contracts": num_contracts_actual,
            "stake_dollars": stake_dollars,
            "won": bool(row["won"]),
            "filled": True,
            "stake_capped": was_capped,
        })

    return pd.DataFrame(history)


def latest_available_init(conn, target_date, init_hour=12, model_aware=True, station_id: str = "KNYC"):
    """
    Return the target date's init_hour UTC init_time IF forecast data exists
    for it, else None. Matches backtest methodology (canonical same-day run at
    the chosen hour); never uses a later run, which would be lookahead bias.

    init_hour defaults to 12 for the legacy combined workflow; pass init_hour=0
    for the 00Z ECMWF market-open workflow.
    """
    preferred = datetime(
        target_date.year, target_date.month, target_date.day,
        init_hour, 0, tzinfo=timezone.utc,
    )
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM forecasts
            WHERE station_id = %s
              AND init_time = %s
            LIMIT 1
        """, (station_id, preferred))
        row = cur.fetchone()
    return preferred if row else None


# =====================================================================
# TABS
# =====================================================================

tab_live, tab_backtest = st.tabs(["Live Trading", "Backtest"])


# ---------------------------------------------------------------------
# LIVE TRADING TAB (real account state + today's orders + risk envelope)
# ---------------------------------------------------------------------

@st.cache_data(ttl=30)
def _live_account_state() -> dict:
    """Pull live state from Kalshi. Cached 30s so dashboard reloads don't hammer the API."""
    from weather_markets.kalshi_api import KalshiClient, KalshiAuthError
    out: dict = {"ok": False, "error": None,
                 "balance_cents": None, "positions": [], "orders": [], "fills": []}
    try:
        client = KalshiClient()
        out["api_base"] = client.api_base
        out["balance_cents"] = client.get_balance().get("balance")
        out["positions"] = client.get_positions().get("market_positions", [])
        out["orders"] = client.get_orders(status="resting", limit=50).get("orders", [])
        import time as _t
        out["fills"] = client.get_fills(min_ts=int(_t.time()) - 7*86400, limit=50).get("fills", [])
        client.close()
        out["ok"] = True
    except KalshiAuthError as e:
        out["error"] = f"Kalshi auth not configured: {e}"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _strip_series(ticker: str) -> str:
    """Strip the KXHIGH<city>- prefix from a ticker for compact display.
    e.g. 'KXHIGHCHI-26JUN05-B85.5' -> '26JUN05-B85.5'."""
    import re as _re
    return _re.sub(r"^KXHIGH[A-Z]+-", "", ticker or "")


# Constants imported from live_trade.py so the dashboard stays in sync with the cron.
# (Adding scripts/ to sys.path because scripts isn't a package; safe import — live_trade
# guards its main() with __name__ == '__main__'.)
def _live_trade_config():
    import sys as _sys
    from pathlib import Path as _P
    scripts_dir = str(_P(__file__).parent)
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    import live_trade as _lt
    return {
        "CITY_CONFIG": _lt.CITY_CONFIG,
        "AGG_DAILY_LOSS": _lt.AGGREGATE_DAILY_LOSS_LIMIT_DOLLARS,
        "AGG_CUM_KILL":   _lt.AGGREGATE_CUMULATIVE_KILL_DOLLARS,
        "SPREAD_MAX":     _lt.SPREAD_REGIME_MAX_CENTS,
        "EDGE_THRESHOLD": _lt.EDGE_THRESHOLD,
        "EXECUTION_MODE": getattr(_lt, "EXECUTION_MODE", "post_inside_spread"),
    }


@st.cache_data(ttl=30)
def _live_db_state() -> dict:
    """Pull live_trades aggregates from DB. Cached 30s.

    Returns dict with per-city scoping (KORD, KMIA) plus aggregate.
    Per-city is keyed by the LIVE model_source tag in live_trades."""
    cfg = _live_trade_config()
    out: dict = {"per_city": {}, "agg": {}, "pnl_by_day": [], "today_trades": []}

    def _city_query(cur, src_like: str) -> dict:
        cur.execute(
            """SELECT COALESCE(SUM(realized_pnl_cents), 0),
                      COUNT(*) FILTER (WHERE settlement IS NOT NULL),
                      COUNT(*) FILTER (WHERE fill_status IN ('filled','partial')),
                      COALESCE(SUM(realized_pnl_cents) FILTER (WHERE target_date = CURRENT_DATE), 0),
                      COUNT(*) FILTER (WHERE target_date = CURRENT_DATE),
                      COALESCE(SUM(count * limit_price_cents) FILTER (WHERE target_date = CURRENT_DATE), 0)
               FROM live_trades WHERE model_source LIKE %s""",
            (src_like,),
        )
        cum, n_settle, n_fill, today, n_today, stake_today_cents = cur.fetchone()
        return {
            "cum_pnl_cents": int(cum),
            "n_settled": int(n_settle),
            "n_filled": int(n_fill),
            "today_pnl_cents": int(today),
            "n_today_orders": int(n_today),
            "today_stake_cents": int(stake_today_cents),
        }

    with get_connection() as conn, conn.cursor() as cur:
        # Aggregate (all rows)
        cur.execute("""
            SELECT COALESCE(SUM(realized_pnl_cents), 0),
                   COUNT(*),
                   COUNT(*) FILTER (WHERE settlement IS NOT NULL),
                   COALESCE(SUM(realized_pnl_cents) FILTER (WHERE target_date = CURRENT_DATE), 0)
            FROM live_trades
        """)
        agg_cum, agg_total, agg_settled, agg_today = cur.fetchone()
        out["agg"] = {
            "cum_pnl_cents": int(agg_cum),
            "total_attempts": int(agg_total),
            "n_settled": int(agg_settled),
            "today_pnl_cents": int(agg_today),
        }

        # Per-city — use a wildcard pattern by city name so a model-source
        # change (e.g., combined -> combined_hrrr) doesn't orphan prior trades
        # from the per-city tile. Pattern matches any live source containing
        # the city name with [LIVE] suffix.
        for city in cfg["CITY_CONFIG"]:
            city_name = cfg["CITY_CONFIG"][city]["city_name"]
            # Special case for NYC: legacy tag doesn't have city in the string
            if city == "KNYC":
                pattern = "%NYC%[LIVE]%"
                # Fallback if old tags don't have "NYC" — also try the legacy "EMOS combined 00Z (rolling 45d) [LIVE]"
                # which has no city name
                out["per_city"][city] = _city_query(cur, "EMOS combined 00Z (rolling 45d) [LIVE]")
            else:
                pattern = f"%{city_name}%[LIVE]%"
                out["per_city"][city] = _city_query(cur, pattern)

        # Daily P&L for chart
        cur.execute("""
            SELECT target_date,
                   SUM(realized_pnl_cents) FILTER (WHERE settlement IS NOT NULL) AS daily_pnl
            FROM live_trades
            GROUP BY target_date ORDER BY target_date
        """)
        out["pnl_by_day"] = cur.fetchall()

        # Today's trades — all cities
        cur.execute("""
            SELECT placed_at, target_date, ticker, side, count,
                   limit_price_cents, cross_price_cents, edge,
                   fill_status, fill_price_cents, settlement, realized_pnl_cents, model_source
            FROM live_trades
            WHERE target_date = CURRENT_DATE
            ORDER BY placed_at
        """)
        out["today_trades"] = cur.fetchall()

        # Per-city rolling 4wk avg spread (from paper data on the paper source)
        out["spread_4wk_per_city"] = {}
        for city, ccfg in cfg["CITY_CONFIG"].items():
            cur.execute("""
                SELECT AVG(market_yes_ask - market_yes_bid), COUNT(*)
                FROM paper_trades
                WHERE target_date >= CURRENT_DATE - INTERVAL '28 days'
                  AND ABS(edge) >= %s
                  AND market_yes_bid IS NOT NULL AND market_yes_ask IS NOT NULL
                  AND model_source = %s
            """, (cfg["EDGE_THRESHOLD"], ccfg["paper_model_source"]))
            spr, n = cur.fetchone()
            out["spread_4wk_per_city"][city] = (float(spr) if spr is not None else None, int(n))
    return out


@st.cache_data(ttl=15)
def _enrich_positions(positions: list[dict]) -> list[dict]:
    """For each non-zero position: fetch live market, compute unrealized P&L,
    pull bracket info from DB, look up today's model probability if available.

    Cached 15s — short enough that live P&L feels real, long enough to avoid
    hammering Kalshi during dashboard refresh."""
    from weather_markets.kalshi_api import KalshiClient, parse_position, parse_dollars_to_cents
    open_positions = [p for p in positions if parse_position(p) != 0]
    if not open_positions:
        return []

    enriched: list[dict] = []
    client = KalshiClient()
    today = date.today()
    try:
        with get_connection() as conn:
            for p in open_positions:
                ticker = p["ticker"]
                pos = parse_position(p)
                side = "yes" if pos > 0 else "no"
                qty = abs(pos)
                # Cost basis: market_exposure_dollars is the dollars committed; convert to cents.
                exposure_cents = parse_dollars_to_cents(p, "market_exposure_dollars")
                avg_cost_cents = (exposure_cents / qty) if qty else 0

                # Live market (Kalshi returns prices as dollar strings; convert to cents)
                try:
                    mkt = client.get_market(ticker).get("market", {})
                    if side == "yes":
                        bid = parse_dollars_to_cents(mkt, "yes_bid_dollars")
                        ask = parse_dollars_to_cents(mkt, "yes_ask_dollars")
                    else:
                        bid = parse_dollars_to_cents(mkt, "no_bid_dollars")
                        ask = parse_dollars_to_cents(mkt, "no_ask_dollars")
                    if bid == 0 and ask == 0:
                        bid = ask = None  # missing or no quote
                except Exception:
                    bid = ask = None
                mark = (bid + ask) / 2.0 if (bid is not None and ask is not None) else None

                # Unrealized P&L = (mark - avg_cost) * qty, both in cents
                if mark is not None:
                    unrealized_cents = int(round((mark - avg_cost_cents) * qty))
                else:
                    unrealized_cents = None

                # Bracket info + today's model view (if available from paper_trades)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT bracket_type, strike_low, strike_high, target_date
                        FROM contracts WHERE ticker = %s
                    """, (ticker,))
                    contract_row = cur.fetchone()
                    if contract_row:
                        bt, slo, shi, td = contract_row
                        if bt == "greater_than":
                            range_str = f">{int(slo)}°"
                        elif bt == "less_than":
                            range_str = f"<{int(shi)}°"
                        else:
                            range_str = f"{int(slo)}-{int(shi)}°"
                    else:
                        range_str = "?"
                        td = None

                    # Model edge for this contract — derive paper source from ticker
                    # series so KORD/KMIA positions resolve to their own paper data.
                    # Look up regardless of date (held positions awaiting settlement
                    # still need the original decision-time edge to display).
                    model_p = market_mid = edge = None
                    if td is not None:
                        series = ticker.split("-")[0]  # KXHIGHCHI, KXHIGHMIA, etc.
                        # Find the station for this series (registry-driven)
                        try:
                            from weather_markets.stations import all_stations as _all_st
                            station_for_series = next(
                                (s for s in _all_st() if s.kalshi_series == series), None,
                            )
                        except Exception:
                            station_for_series = None
                        if station_for_series is not None:
                            paper_src = (
                                "EMOS combined 00Z (rolling 45d)"
                                if station_for_series.station_id == "KNYC"
                                else f"EMOS combined 00Z {station_for_series.city} (rolling 45d)"
                            )
                            cur.execute("""
                                SELECT model_prob_yes, market_mid_prob, edge
                                FROM paper_trades
                                WHERE ticker = %s AND target_date = %s
                                  AND model_source = %s
                                ORDER BY logged_at DESC LIMIT 1
                            """, (ticker, td, paper_src))
                            mp_row = cur.fetchone()
                            if mp_row:
                                model_p, market_mid, edge = mp_row

                # Action heuristic
                if edge is not None:
                    # If we're long YES and current model edge is still positive → HOLD
                    # If we're long NO  and current model edge is still negative → HOLD
                    # If the sign flipped → REVIEW
                    if (side == "yes" and edge > 0) or (side == "no" and edge < 0):
                        action = "HOLD (model agrees)"
                    else:
                        action = "REVIEW (model flipped)"
                else:
                    action = "—"

                enriched.append({
                    "ticker": ticker,
                    "range": range_str,
                    "target_date": td,
                    "side": side,
                    "qty": qty,
                    "avg_cost_cents": avg_cost_cents,
                    "bid": bid,
                    "ask": ask,
                    "mark": mark,
                    "unrealized_cents": unrealized_cents,
                    "model_p": float(model_p) if model_p is not None else None,
                    "market_mid": float(market_mid) if market_mid is not None else None,
                    "edge": float(edge) if edge is not None else None,
                    "action": action,
                    "realized_pnl_cents": parse_dollars_to_cents(p, "realized_pnl_dollars"),
                    "fees_paid_cents": parse_dollars_to_cents(p, "fees_paid_dollars"),
                })
    finally:
        client.close()
    return enriched


def _to_local_time(dt_or_str, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Convert a UTC datetime, ISO string, or naive timestamp to Eastern time.
    Uses America/New_York zone so EST↔EDT switches automatically."""
    from zoneinfo import ZoneInfo
    if dt_or_str is None or dt_or_str == "":
        return ""
    if isinstance(dt_or_str, str):
        s = dt_or_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return dt_or_str
    else:
        dt = dt_or_str
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("America/New_York")).strftime(fmt)


def _read_recent_alerts(n: int = 10) -> list[str]:
    from pathlib import Path
    p = Path("/var/log/weather/alerts.log")
    if not p.exists():
        return []
    try:
        with p.open() as f:
            return f.readlines()[-n:]
    except Exception:
        return []


def _read_log_tail(path: str, n: int = 60) -> str:
    """Read the last n lines of a log file. Returns formatted string with header
    if file is missing or empty."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return f"(no log yet at {path} — cron hasn't fired or output is elsewhere)"
    try:
        with p.open() as f:
            lines = f.readlines()
        if not lines:
            return f"(log {path} is empty)"
        return "".join(lines[-n:])
    except Exception as e:
        return f"(error reading {path}: {e})"


def _read_halts() -> list[tuple[str, str, str]]:
    """Returns list of (scope, file_path, reason). Empty list = no halts active.

    Multi-city halt-file structure (see live_trade.py CITY_CONFIG):
      halt/ALL  — halts BOTH cities
      halt/KORD — halts Chicago only
      halt/KMIA — halts Miami only
    """
    from pathlib import Path
    halt_dir = Path(__file__).parent.parent / "halt"
    out = []
    for scope in ["ALL", "KORD", "KMIA"]:
        p = halt_dir / scope
        if p.exists():
            try:
                out.append((scope, str(p), p.read_text().strip()))
            except Exception as e:
                out.append((scope, str(p), f"(unreadable: {e})"))
    return out


def _cron_health() -> list[dict]:
    """Parse the tail of each daily cron log to surface last-run + status.

    Returns list of dicts: {name, path, last_seen, status, last_line}.
    status is 'ok' / 'stale' (no run in 25h) / 'error' (recent ERROR/Traceback).
    """
    from pathlib import Path
    import re as _re
    crons = [
        ("Chicago live_trade (14:46 UTC)", "/var/log/weather/live_trade.log",  "Live trade decision for KORD"),
        ("Miami live_trade (15:30 UTC)",   "/var/log/weather/live_trade.log",  "Live trade decision for KMIA"),
        ("paper_trade (14:45 UTC)",        "/var/log/weather/paper_trade.log",  None),
        ("monitor_fills (every 30 min)",   "/var/log/weather/monitor_fills.log", None),
        ("reconcile (04:00 UTC)",          "/var/log/weather/reconcile.log",    None),
    ]
    out = []
    for name, path, expect_marker in crons:
        p = Path(path)
        if not p.exists():
            out.append({"name": name, "path": path, "status": "missing",
                        "last_seen": None, "last_line": "(no log file)"})
            continue
        try:
            with p.open() as f:
                lines = f.readlines()
        except Exception as e:
            out.append({"name": name, "path": path, "status": "error",
                        "last_seen": None, "last_line": f"(read err: {e})"})
            continue
        # If we expect a city marker, find the latest matching line
        if expect_marker:
            relevant = [l for l in lines if expect_marker in l]
            tail = relevant[-12:] if relevant else lines[-4:]
        else:
            tail = lines[-12:]
        joined = "".join(tail)
        # Extract a timestamp from the most recent line that has one
        ts_match = None
        for line in reversed(tail):
            m = _re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
            if m:
                ts_match = m.group(1)
                break
        # Detect error keywords in recent tail
        has_error = any(k in joined for k in ("ERROR", "Traceback", "[WARN", "FAIL", "exception"))
        status = "error" if has_error else "ok"
        # Stale check: if last_seen is older than 25h, mark stale
        last_seen_dt = None
        if ts_match:
            try:
                last_seen_dt = datetime.fromisoformat(ts_match.replace(" ", "T"))
                if last_seen_dt.tzinfo is None:
                    last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - last_seen_dt).total_seconds() > 25 * 3600:
                    status = "stale"
            except Exception:
                pass
        out.append({
            "name": name, "path": path, "status": status,
            "last_seen": last_seen_dt, "last_line": tail[-1].strip() if tail else "",
        })
    return out


@st.cache_data(ttl=30)
def _todays_signals_vs_fills():
    """Cross-reference today's paper-trade signals with live_trades placements.
    Returns list of dicts joined per ticker."""
    cfg = _live_trade_config()
    paper_sources = [c["paper_model_source"] for c in cfg["CITY_CONFIG"].values()]
    live_sources = [c["live_model_source_tag"] for c in cfg["CITY_CONFIG"].values()]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT pt.ticker, c.station_id, pt.position, pt.entry_price_cents, pt.edge,
                   pt.model_prob_yes, pt.market_mid_prob,
                   lt.count, lt.limit_price_cents, lt.fill_status,
                   lt.fill_count, lt.fill_price_cents, lt.settlement, lt.realized_pnl_cents
            FROM paper_trades pt
            JOIN contracts c ON c.ticker = pt.ticker
            LEFT JOIN live_trades lt ON lt.ticker = pt.ticker AND lt.target_date = pt.target_date
                  AND lt.model_source = ANY(%s)
            WHERE pt.target_date = CURRENT_DATE
              AND pt.model_source = ANY(%s)
            ORDER BY c.station_id, ABS(pt.edge) DESC
        """, (live_sources, paper_sources))
        return cur.fetchall()


@st.fragment(run_every="15s")
def _live_trading_panel():
    """Auto-refreshing Live Trading view. Re-runs every 15s; underlying
    Kalshi/DB calls are @st.cache_data ttl=15-30s so API rate stays low."""
    from zoneinfo import ZoneInfo
    now_local = datetime.now(ZoneInfo("America/New_York"))
    st.caption(f"⟳ Updated {now_local.strftime('%I:%M:%S %p %Z')} (auto-refreshes every 15s)")

    cfg = _live_trade_config()

    # Multi-city halt banner — per-file
    halts = _read_halts()
    if halts:
        for scope, path, reason in halts:
            scope_label = "BOTH CITIES" if scope == "ALL" else cfg["CITY_CONFIG"].get(scope, {}).get("city_name", scope)
            st.error(
                f"🛑 **{scope_label} HALTED.** Cron will skip new orders for this scope "
                f"until removed: `rm {path}`\n\n```\n{reason}\n```"
            )

    # Pull state
    live = _live_account_state()
    db = _live_db_state()

    if not live["ok"]:
        st.warning(f"Kalshi API unavailable: {live['error']}")

    is_demo = live.get("api_base") and "demo" in live["api_base"]
    env_label = "DEMO" if is_demo else "LIVE (real money)"

    # === Compute enriched positions early so unrealized P&L flows into metrics ===
    from weather_markets.kalshi_api import parse_position
    positions_raw = live.get("positions", [])
    open_contracts = sum(abs(parse_position(p)) for p in positions_raw)
    try:
        enriched_positions = _enrich_positions(positions_raw) if positions_raw else []
    except Exception as e:
        st.warning(f"Could not enrich positions: {type(e).__name__}: {e}")
        enriched_positions = []

    # Map ticker series → station_id → city for per-city unrealized totals.
    try:
        from weather_markets.stations import all_stations as _all_st
        series_to_city = {s.kalshi_series: s.station_id for s in _all_st()}
    except Exception:
        series_to_city = {}

    agg_unrealized_cents = 0
    per_city_unrealized: dict[str, int] = {city: 0 for city in cfg["CITY_CONFIG"]}
    for e in enriched_positions:
        u = e.get("unrealized_cents")
        if u is None:
            continue
        agg_unrealized_cents += u
        series = e["ticker"].split("-")[0]
        city = series_to_city.get(series)
        if city in per_city_unrealized:
            per_city_unrealized[city] += u

    bal = live.get("balance_cents")
    agg_realized = db['agg']['cum_pnl_cents'] / 100.0
    agg_unrealized = agg_unrealized_cents / 100.0
    agg_total = agg_realized + agg_unrealized

    # === Top status row — account + total P&L ===
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Account balance", f"${bal/100:,.2f}" if bal is not None else "—", env_label)
    with m2:
        st.metric("Realized (settled) P&L",
                  f"${agg_realized:+,.2f}",
                  f"{db['agg']['n_settled']} settled trades")
    with m3:
        st.metric("Unrealized (open positions)",
                  f"${agg_unrealized:+,.2f}",
                  f"{len(enriched_positions)} open positions, {open_contracts} contracts")
    with m4:
        st.metric("Combined P&L (realized + unrealized)",
                  f"${agg_total:+,.2f}",
                  f"{len(live.get('orders', []))} resting orders")

    # === Per-city breakdown — realized + unrealized side by side ===
    st.markdown("**Per-city realized + unrealized P&L:**")
    pc_cols = st.columns(len(cfg["CITY_CONFIG"]))
    for i, (city, ccfg) in enumerate(cfg["CITY_CONFIG"].items()):
        d = db["per_city"][city]
        city_unrealized = per_city_unrealized.get(city, 0) / 100.0
        city_realized = d['cum_pnl_cents'] / 100.0
        city_total = city_realized + city_unrealized
        with pc_cols[i]:
            st.metric(
                f"{ccfg['city_name']} — combined",
                f"${city_total:+,.2f}",
                f"realized ${city_realized:+,.2f} + unrealized ${city_unrealized:+,.2f}",
            )
            # Activity label depends on sizing mode (unit = no dollar budget cap)
            if ccfg.get("sizing_mode") == "unit":
                activity_caption = (
                    f"${d['today_stake_cents']/100:.0f} deployed "
                    f"(unit {ccfg.get('unit_contracts', '?')} contracts/trade)"
                )
            else:
                activity_caption = (
                    f"${d['today_stake_cents']/100:.0f} / "
                    f"${ccfg.get('daily_stake_budget_dollars', 0):.0f} budget deployed"
                )
            st.metric(
                f"{ccfg['city_name']} — today's activity",
                f"{d['n_today_orders']} orders",
                activity_caption,
            )

    st.divider()

    # === Risk envelope — per-city + aggregate, sourced from live_trade.py constants ===
    st.subheader("Risk envelope")
    st.caption("Per-city + aggregate caps from live_trade.py CITY_CONFIG. "
               "Bars red the closer they get to the kill threshold.")

    # Aggregate row
    a_cols = st.columns(3)
    agg_cum = db['agg']['cum_pnl_cents'] / 100.0
    agg_today = db['agg']['today_pnl_cents'] / 100.0
    with a_cols[0]:
        cum_pct = abs(agg_cum) / cfg["AGG_CUM_KILL"] if agg_cum < 0 else 0
        st.metric("Aggregate cumulative drawdown",
                  f"${agg_cum:+,.2f}",
                  f"kill at −${cfg['AGG_CUM_KILL']:.0f}",
                  delta_color="inverse")
        st.progress(min(1.0, cum_pct), text=f"{cum_pct*100:.0f}% of kill threshold")
    with a_cols[1]:
        today_pct = abs(agg_today) / cfg["AGG_DAILY_LOSS"] if agg_today < 0 else 0
        st.metric("Aggregate daily loss",
                  f"${agg_today:+,.2f}",
                  f"halt at −${cfg['AGG_DAILY_LOSS']:.0f}",
                  delta_color="inverse")
        st.progress(min(1.0, today_pct), text=f"{today_pct*100:.0f}% of daily limit")
    with a_cols[2]:
        st.metric("Open contracts (all cities)", open_contracts,
                  f"sum of city caps: {sum(c['max_open_contracts'] for c in cfg['CITY_CONFIG'].values())}")

    # Per-city row
    pc_risk_cols = st.columns(len(cfg["CITY_CONFIG"]))
    for i, (city, ccfg) in enumerate(cfg["CITY_CONFIG"].items()):
        d = db["per_city"][city]
        with pc_risk_cols[i]:
            cum_d = d['cum_pnl_cents'] / 100.0
            today_d = d['today_pnl_cents'] / 100.0
            cum_pct = abs(cum_d) / ccfg["cumulative_kill_dollars"] if cum_d < 0 else 0
            today_pct = abs(today_d) / ccfg["daily_loss_limit_dollars"] if today_d < 0 else 0
            st.markdown(f"**{ccfg['city_name']}**")
            st.metric("Cumulative", f"${cum_d:+,.2f}", f"kill at −${ccfg['cumulative_kill_dollars']:.0f}",
                      delta_color="inverse")
            st.progress(min(1.0, cum_pct), text=f"{cum_pct*100:.0f}%")
            st.metric("Today's loss", f"${today_d:+,.2f}", f"halt at −${ccfg['daily_loss_limit_dollars']:.0f}",
                      delta_color="inverse")
            st.progress(min(1.0, today_pct), text=f"{today_pct*100:.0f}%")
            spr = db["spread_4wk_per_city"].get(city)
            if spr and spr[0] is not None:
                spr_val, spr_n = spr
                spr_pct = spr_val / cfg["SPREAD_MAX"]
                st.metric("4wk spread", f"{spr_val:.2f}¢",
                          f"halt > {cfg['SPREAD_MAX']:.0f}¢ ({spr_n} samples)",
                          delta_color="inverse")
                st.progress(min(1.0, spr_pct), text=f"{spr_pct*100:.0f}%")
            else:
                st.caption(f"4wk spread: insufficient data ({spr[1] if spr else 0} samples)")

    st.divider()

    # === Cron health summary ===
    st.subheader("Cron health")
    cron_status = _cron_health()
    cron_cols = st.columns(len(cron_status))
    for i, c in enumerate(cron_status):
        with cron_cols[i]:
            icon = {"ok": "✅", "stale": "⚠️", "error": "🛑", "missing": "❔"}[c["status"]]
            last_seen = _to_local_time(c["last_seen"], "%m-%d %I:%M %p") if c["last_seen"] else "never"
            st.markdown(f"{icon} **{c['name']}**")
            st.caption(f"Last: {last_seen}  ·  Status: `{c['status']}`")

    st.divider()

    # === Current positions with live unrealized P&L ===
    st.subheader("Current positions")
    st.caption("Each row = one contract you hold. Mark = current bid/ask mid. "
               "Unrealized P&L = (mark − avg cost) × qty. Refreshes every 15 seconds. "
               "Model P / Edge are from the decision-time paper-trade row, regardless of how old the position is.")

    # Reuse the enriched_positions computed at the top of the panel.
    if not enriched_positions:
        st.info("No open positions right now.")
    else:
        enriched = enriched_positions
        if not enriched:
            st.info("No open positions right now.")
        else:
            # Display as table with conditional formatting
            import pandas as pd
            rows = []
            total_unrealized_cents = 0
            for e in enriched:
                upnl = e["unrealized_cents"]
                if upnl is not None:
                    total_unrealized_cents += upnl
                rows.append({
                    "Contract": _strip_series(e["ticker"]),
                    "Range": e["range"],
                    "Side": e["side"].upper(),
                    "Qty": e["qty"],
                    "Avg cost": f"{e['avg_cost_cents']:.1f}¢",
                    "Bid": f"{e['bid']}¢" if e["bid"] is not None else "—",
                    "Ask": f"{e['ask']}¢" if e["ask"] is not None else "—",
                    "Mark": f"{e['mark']:.1f}¢" if e["mark"] is not None else "—",
                    "Unrealized P&L": f"${e['unrealized_cents']/100:+,.2f}" if e["unrealized_cents"] is not None else "—",
                    "Model P": f"{e['model_p']:.1%}" if e["model_p"] is not None else "—",
                    "Market P": f"{e['market_mid']:.1%}" if e["market_mid"] is not None else "—",
                    "Edge": f"{e['edge']:+.1%}" if e["edge"] is not None else "—",
                    "Signal": e["action"],
                })
            df = pd.DataFrame(rows)

            def color_pnl(v):
                if "+" in str(v) and "$" in str(v):
                    return "background-color: #1b4d2e; color: #b6f5c8"
                if "-" in str(v) and "$" in str(v):
                    return "background-color: #5c1a1a; color: #f5b6b6"
                return ""

            def color_signal(v):
                if v == "HOLD (model agrees)":
                    return "background-color: #1b4d2e; color: #b6f5c8"
                if v == "REVIEW (model flipped)":
                    return "background-color: #5c4a1a; color: #f5e0b6"
                return ""

            styled = (df.style
                .map(color_pnl, subset=["Unrealized P&L"])
                .map(color_signal, subset=["Signal"]))
            st.dataframe(styled, width="stretch", hide_index=True)

            # Aggregate footer
            n_pos = len(enriched)
            st.metric("Total unrealized P&L across all positions",
                      f"${total_unrealized_cents/100:+,.2f}",
                      f"{n_pos} position{'s' if n_pos != 1 else ''}")

    st.divider()

    # === P&L Timeline ===
    st.subheader("Cumulative P&L since first live trade")
    if db['pnl_by_day']:
        import pandas as pd
        pnl_df = pd.DataFrame(db['pnl_by_day'], columns=["date", "daily_pnl_cents"])
        pnl_df["daily_pnl_dollars"] = pnl_df["daily_pnl_cents"].fillna(0).astype(float) / 100.0
        pnl_df["cum_pnl_dollars"] = pnl_df["daily_pnl_dollars"].cumsum()
        pnl_df["date"] = pd.to_datetime(pnl_df["date"])
        line = alt.Chart(pnl_df).mark_line(point=True).encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("cum_pnl_dollars:Q", title="Cumulative P&L ($)"),
            tooltip=[alt.Tooltip("date:T"),
                     alt.Tooltip("daily_pnl_dollars:Q", title="Day P&L", format="$.2f"),
                     alt.Tooltip("cum_pnl_dollars:Q", title="Cumulative", format="$.2f")],
        )
        zero_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4,4], color="gray").encode(y="y:Q")
        st.altair_chart((line + zero_line).properties(height=240), width="stretch")
    else:
        st.info("No live trades yet. Chart will populate after first fill + settlement.")

    st.divider()

    # === Today's signals → fills cross-reference ===
    st.subheader("Today's signals vs fills")
    st.caption("Every signal the paper-trade cron logged today + whether live trading "
               "placed it + fill status. Lets you see at a glance: signals fired, orders "
               "placed, fills completed.")
    sigs = _todays_signals_vs_fills()
    if sigs:
        import pandas as pd
        rows = []
        for r in sigs:
            (tk, sta, position, entry_c, edge_v, m_p, m_mid,
             lt_count, lt_lim, lt_status, lt_fc, lt_fp, settle, pnl_c) = r
            city = cfg["CITY_CONFIG"].get(sta, {}).get("city_name", sta)
            placed_icon = "✅" if lt_count else "❌"
            rows.append({
                "City": city,
                "Contract": _strip_series(tk),
                "Side": position.upper() if position else "—",
                "Edge (decision-time)": f"{float(edge_v):+.1%}" if edge_v is not None else "—",
                "Paper entry": f"{entry_c}¢" if entry_c is not None else "—",
                "Placed?": placed_icon + (f" ({lt_count} @ {lt_lim}¢)" if lt_count else " skipped"),
                "Fill status": lt_status or "—",
                "Fill count": lt_fc if lt_fc else "—",
                "Fill price": f"{lt_fp}¢" if lt_fp else "—",
                "Settled": settle or "—",
                "Realized P&L": f"${int(pnl_c)/100:+,.2f}" if pnl_c is not None else "—",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("No paper-trade signals logged for today yet (cron fires at 14:45 UTC).")

    st.divider()

    # === Today's orders table (raw live_trades view) ===
    st.subheader("Today's live orders")
    if db['today_trades']:
        import pandas as pd
        rows = []
        for r in db['today_trades']:
            (placed, td, tk, side, cnt, lim, cross, edge,
             status, fp, settle, pnl, model_source) = r
            # Map model_source → city tag for display
            city_tag = "?"
            for _city, _ccfg in cfg["CITY_CONFIG"].items():
                if _ccfg["live_model_source_tag"] == model_source:
                    city_tag = _ccfg["city_name"]; break
            rows.append({
                "placed_at (ET)": _to_local_time(placed, "%I:%M:%S %p") if placed else "",
                "city": city_tag,
                "ticker": _strip_series(tk),
                "side": side.upper(),
                "count": cnt,
                "limit": f"{lim}¢",
                "cross": f"{cross}¢",
                "edge": f"{float(edge):+.1%}",
                "status": status,
                "fill_price": f"{fp}¢" if fp else "—",
                "settled": settle if settle else "—",
                "pnl": f"${int(pnl)/100:+,.2f}" if pnl is not None else "—",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("Cron hasn't placed any orders today (either no signals passed filters, or hasn't fired yet).")

    st.divider()

    # === Open Kalshi orders + recent fills (side by side) ===
    o1, o2 = st.columns(2)
    with o1:
        st.subheader("Open orders on Kalshi")
        orders = live.get("orders", [])
        if orders:
            import pandas as pd
            from weather_markets.kalshi_api import parse_count as _pc, parse_dollars_to_cents as _pd
            order_rows = []
            for o in orders[:10]:
                price_c = _pd(o, "yes_price_dollars") or _pd(o, "no_price_dollars")
                order_rows.append({
                    "ticker": _strip_series(o.get("ticker", "")),
                    "side": o.get("side", "").upper(),
                    "remaining": _pc(o, "remaining_count_fp"),
                    "price": f"{price_c}¢" if price_c else "—",
                    "placed (ET)": _to_local_time(o.get("created_time", ""), "%m-%d %I:%M:%S %p"),
                })
            st.dataframe(pd.DataFrame(order_rows), width="stretch", hide_index=True)
        else:
            st.caption("No resting orders.")
    with o2:
        st.subheader("Recent fills (7 days)")
        fills = live.get("fills", [])
        if fills:
            import pandas as pd
            from weather_markets.kalshi_api import parse_count as _pc, parse_dollars_to_cents as _pd
            fill_rows = []
            for f in fills[:10]:
                price_c = _pd(f, "yes_price_dollars") or _pd(f, "no_price_dollars")
                fill_rows.append({
                    "time (ET)": _to_local_time(f.get("created_time", ""), "%m-%d %I:%M:%S %p"),
                    "ticker": _strip_series(f.get("ticker", "")),
                    "side": f.get("side", "").upper(),
                    "count": _pc(f, "count_fp"),
                    "price": f"{price_c}¢" if price_c else "—",
                })
            st.dataframe(pd.DataFrame(fill_rows), width="stretch", hide_index=True)
        else:
            st.caption("No fills in the last 7 days.")

    st.divider()

    # === Cron activity (tabbed view of the four daily cron logs) ===
    st.subheader("Cron activity")
    st.caption("Last entries from each daily cron log. Use these to confirm trades fired, "
               "see what got filled, and surface errors that didn't reach the alerts file.")

    log_tabs = st.tabs(["live_trade", "paper_trade", "monitor_fills", "reconcile"])
    log_configs = [
        ("/var/log/weather/live_trade.log",     "Live trade decision (14:46 UTC daily)"),
        ("/var/log/weather/paper_trade.log",    "Paper-trade signal log (14:45 UTC daily)"),
        ("/var/log/weather/monitor_fills.log",  "Fill checker (every 30 min 15-19 UTC + 20:00 EOD cancel)"),
        ("/var/log/weather/reconcile.log",      "Settlement + daily P&L summary (04:00 UTC daily)"),
    ]
    for tab, (path, caption) in zip(log_tabs, log_configs):
        with tab:
            st.caption(caption)
            st.code(_read_log_tail(path, n=60), language="log")

    st.divider()

    # === Recent alerts ===
    st.subheader("Recent alerts")
    alerts = _read_recent_alerts(10)
    if alerts:
        # Rewrite leading ISO UTC timestamp to ET for readability.
        converted = []
        for line in alerts:
            parts = line.split(" ", 1)
            if len(parts) == 2 and "T" in parts[0]:
                local_ts = _to_local_time(parts[0], "%Y-%m-%d %I:%M:%S %p ET")
                converted.append(f"{local_ts} {parts[1]}")
            else:
                converted.append(line)
        st.code("".join(converted), language="log")
    else:
        st.caption("No alerts logged.")

    st.divider()

    # === Strategy parameters (auto-rendered from live_trade.py so it can't drift) ===
    with st.expander("Strategy parameters in effect (live from live_trade.py)"):
        st.markdown(f"**Filter:** |edge| ≥ {cfg['EDGE_THRESHOLD']:.0%}, no entry-price floor")
        st.markdown(f"**Sizing:** even-split across all signals (`stake = budget / n_signals`)")
        st.markdown(f"**Execution mode:** `{cfg['EXECUTION_MODE']}`")
        st.markdown(f"**Aggregate kills:** daily loss −${cfg['AGG_DAILY_LOSS']:.0f}, cumulative drawdown −${cfg['AGG_CUM_KILL']:.0f}, "
                    f"4wk avg spread > {cfg['SPREAD_MAX']:.0f}¢")
        st.markdown("**Per-city:**")
        for city, ccfg in cfg["CITY_CONFIG"].items():
            mode = ccfg.get("sizing_mode", "even_split")
            if mode == "unit":
                sizing_str = f"sizing: unit ({ccfg.get('unit_contracts', '?')} contracts/trade)"
            else:
                sizing_str = f"daily budget ${ccfg.get('daily_stake_budget_dollars', 0):.0f}"
            st.markdown(
                f"- **{ccfg['city_name']}** ({city}, decision {ccfg['decision_hour']:02d}:{ccfg['decision_minute']:02d} UTC) — "
                f"{sizing_str}, "
                f"daily loss halt −${ccfg['daily_loss_limit_dollars']:.0f}, "
                f"cumulative kill −${ccfg['cumulative_kill_dollars']:.0f}, "
                f"max open contracts {ccfg['max_open_contracts']}"
            )
        st.markdown("**Halt files (touch to stop trading immediately):**")
        st.code("touch halt/KORD   # Chicago only\ntouch halt/KMIA   # Miami only\ntouch halt/ALL    # both cities", language="bash")


with tab_live:
    # Redesigned Live Trading tab (Bloomberg-terminal aesthetic).
    # Renders the React prototype via components.html with live data from DB+Kalshi.
    from live_dashboard_renderer import render_live_tab as _render_redesigned_live

    @st.fragment(run_every=15)
    def _live_trading_fragment():
        cfg = _live_trade_config()
        _render_redesigned_live(cfg, height=2600)

    _live_trading_fragment()

    # Legacy panel kept as a fallback under an expander in case the
    # redesigned view has data issues — easy to diff against the old one.
    with st.expander("Show legacy Live Trading panel", expanded=False):
        _live_trading_panel()


# ---------------------------------------------------------------------
# BACKTEST TAB (forecast-vs-market diagnostic view)
# Was previously labeled "Trading View"; the actual live trading lives in
# the Live Trading tab now.
# ---------------------------------------------------------------------
with tab_backtest:
    # Redesigned Backtest tab — bidirectional declare_component. The React
    # panel's controls (Platform/City/Target date/Edge/sizing/exec/depth)
    # round-trip through Streamlit so Python recomputes when params change.
    from backtest_dashboard_renderer import render_backtest_tab as _render_redesigned_backtest

    # session_state keeps the current backtest selections across reruns so
    # changing one control doesn't reset the others.
    if "bt_state" not in st.session_state:
        st.session_state.bt_state = {
            "cityCode": "KORD",
            "date": date.today().isoformat(),
            "sizing": "amount",
            "amount": 50.0,
            "depth": 500,
            "edge": 0.25,
            "minEntry": 0,
            "exec": "post_inside_spread",
            "platform": "Kalshi",
        }
    s = st.session_state.bt_state
    # Parse date back to a date object
    try:
        _bt_date = date.fromisoformat(s["date"]) if isinstance(s["date"], str) else s["date"]
    except (TypeError, ValueError):
        _bt_date = date.today()

    result = _render_redesigned_backtest(
        s["cityCode"], _bt_date, s["sizing"],
        float(s["amount"]), int(s["depth"]), float(s["edge"]),
        height=2400,
    )
    # Only round-trip Python when params that AFFECT the data payload change.
    # Sim params (sizing/amount/depth/edge/exec/minEntry/bankroll) are recomputed
    # in JS instantly — no Python rerun needed.
    if isinstance(result, dict):
        changed = any(s.get(k) != result.get(k) for k in ("cityCode", "date", "platform"))
        if changed:
            s.update({k: result.get(k, s.get(k)) for k in
                      ("cityCode", "date", "platform")})
            st.rerun()

    # Keep the legacy panel under an expander for diff/fallback
    with st.expander("Show legacy Backtest panel", expanded=False):
        st.title("Backtest / Forecast View (legacy)")
        st.markdown(
            "Today's combined GEFS+ECMWF forecast vs current Kalshi prices. "
            "Edge = model probability minus market mid. Large positive edge means "
            "the model thinks YES is underpriced. **This is a diagnostic view — "
            "actual live trading is in the Live Trading tab.**"
        )

    # Platform + City selectors drive station/series for the WHOLE tab.
    # Platform first: Kalshi vs Polymarket. Each platform has different cities
    # (Polymarket uses KMDW for Chicago, KSFO for SF; Kalshi uses KORD, no SF).
    _stations = all_stations()
    KALSHI_STATIONS = [s for s in _stations if s.kalshi_series]  # has Kalshi market
    POLYMARKET_STATIONS = [
        # Polymarket US weather city codes verified in contracts table:
        # mdwhigh=KMDW, nychigh=KNYC, miahigh=KMIA, laxhigh=KLAX, sfohigh=KSFO
        get_station(sid) for sid in ["KMDW", "KNYC", "KMIA", "KLAX", "KSFO"]
        if sid in {s.station_id for s in _stations}
    ]

    plat_col, city_col = st.columns([1, 2])
    with plat_col:
        selected_platform = st.radio(
            "Platform",
            options=["Kalshi", "Polymarket"],
            index=0,
            horizontal=True,
            help="Kalshi: KORD/KMIA/etc. Polymarket: KMDW/KNYC/etc. "
                 "Each platform has different settlement stations (e.g., Chicago = KORD on "
                 "Kalshi vs KMDW on Polymarket — contracts are NOT fungible across platforms).",
        )
    platform_stations = KALSHI_STATIONS if selected_platform == "Kalshi" else POLYMARKET_STATIONS
    with city_col:
        _city_labels = {f"{s.city} ({s.station_id})": s.station_id for s in platform_stations}
        if not _city_labels:
            st.error(f"No cities configured for {selected_platform}.")
            st.stop()
        chosen_city_label = st.selectbox(
            "City",
            options=list(_city_labels.keys()),
            index=0,
            help="Switches the entire backtest tab — forecast, edge table, and P&L sim — "
                 "to the selected city's contracts, station, and EMOS calibration.",
        )
    selected_station_id = _city_labels[chosen_city_label]
    selected_station = get_station(selected_station_id)
    # For Kalshi we use station.kalshi_series. For Polymarket we use the
    # tc-temp-{city}high series naming convention.
    POLYMARKET_SERIES_MAP = {
        "KMDW": "tc-temp-mdwhigh", "KNYC": "tc-temp-nychigh",
        "KMIA": "tc-temp-miahigh", "KLAX": "tc-temp-laxhigh",
        "KSFO": "tc-temp-sfohigh",
    }
    if selected_platform == "Kalshi":
        selected_series = selected_station.kalshi_series
        selected_platform_db = "kalshi"
    else:
        selected_series = POLYMARKET_SERIES_MAP.get(selected_station_id, "")
        selected_platform_db = "polymarket"

    # Controls
    ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])
    with ctrl1:
        trade_date = st.date_input(
            "Target date",
            value=date.today(),
            help="The contract day you're evaluating. Defaults to today.",
        )
    with ctrl2:
        model_choice = st.radio(
            "Probability source",
            options=["EMOS combined 00Z (rolling 45d)"],
            index=0,
            help="Production strategy: combined GEFS+IFS 00Z ensemble, post-processed with a rolling 45-day EMOS fit.",
        )
    with ctrl3:
        edge_threshold = st.slider(
            "Signal threshold (edge)",
            min_value=0.02, max_value=0.30, value=0.10, step=0.01,
            help="Flag BUY YES / BUY NO when |edge| exceeds this.",
        )

    # Production strategy: 00Z init, 14:45 UTC decision time.
    cfg = {
        "init_hour": 0,
        "models": ["gefs", "ifs"],
        "ensemble_label": "Combined 00Z",
        "decision_hour": 14,
        "decision_minute": 45,
    }

    emos_params = fit_emos_rolling_cached(
        trade_date, model="combined", init_hour=0, station_id=selected_station_id,
    )
    if emos_params is None:
        st.warning(
            f"Rolling combined 00Z EMOS unavailable for {selected_station.city} — "
            "fewer than 30 days of training data. Showing raw combined probabilities only."
        )

    with get_connection() as conn:
        # Resolve which forecast run to use (canonical init for the chosen workflow).
        chosen_init = latest_available_init(
            conn, trade_date, init_hour=cfg["init_hour"], station_id=selected_station_id,
        )

        if chosen_init is None:
            st.info(
                f"No {cfg['init_hour']:02d} UTC forecast is available yet for "
                f"{selected_station.city} on {trade_date}. "
                "Check back after the next ingest cron runs."
            )
            st.stop()

        preferred_init = datetime(
            trade_date.year, trade_date.month, trade_date.day,
            cfg["init_hour"], 0, tzinfo=timezone.utc,
        )
        is_stale = chosen_init != preferred_init

        # Ensemble for the chosen run (single model or combined per cfg).
        try:
            combined_values = compute_combined_daily_highs(
                chosen_init, trade_date, conn,
                station_id=selected_station_id, models=cfg["models"],
            )
        except Exception as e:
            st.error(f"Could not load forecast: {e}")
            st.stop()

        # Which models actually contributed (only relevant when we expected multiple).
        models_present = set(cfg["models"])
        if len(cfg["models"]) > 1:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT model
                    FROM forecasts
                    WHERE init_time = %s AND station_id = %s AND model = ANY(%s)
                    GROUP BY model
                    """,
                    (chosen_init, selected_station_id, cfg["models"]),
                )
                models_present = {row[0] for row in cur.fetchall()}

        contracts = fetch_contracts_for_date(
            trade_date, conn, station_id=selected_station_id, series=selected_series,
            platform=selected_platform_db,
        )
        observed_high = fetch_observed_high(trade_date, conn, station_id=selected_station_id)

        # Market prices as of the paper-trade decision time for this workflow
        # (14:45 UTC for 00Z ECMWF, 18:45 UTC for 12Z combined). For HISTORICAL
        # dates this lock prevents post-decision (post-resolution) prices from
        # contaminating backtest views. For TODAY (or any date where no snapshot
        # exists before the decision time — e.g. a new city that just started
        # being snapshotted), drop the upper bound and use the most recent
        # snapshot we have.
        decision_time = datetime(
            trade_date.year, trade_date.month, trade_date.day,
            cfg["decision_hour"], cfg["decision_minute"], tzinfo=timezone.utc,
        )
        today_utc = datetime.now(tz=timezone.utc).date()
        lock_to_decision_time = trade_date < today_utc
        market_probs = {}
        if contracts:
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
                if lock_to_decision_time:
                    cur.execute("""
                        SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
                        FROM prices
                        WHERE ticker = ANY(%s) AND snapshot_at <= %s
                        ORDER BY ticker, snapshot_at DESC
                    """, (tickers, decision_time))
                else:
                    cur.execute("""
                        SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
                        FROM prices
                        WHERE ticker = ANY(%s)
                        ORDER BY ticker, snapshot_at DESC
                    """, (tickers,))
                for ticker, bid, ask, snap in cur.fetchall():
                    if bid is not None and ask is not None:
                        market_probs[ticker] = (bid + ask) / 200

    # Forecast statistics
    cmean = statistics.mean(combined_values)
    cstd = statistics.stdev(combined_values) if len(combined_values) > 1 else 0.0

    emos_mu = emos_sigma = None
    if emos_params is not None and cstd > 0:
        emos_mu = emos_params['a'] + emos_params['b'] * cmean
        emos_var = emos_params['c'] + emos_params['d'] * cstd**2
        if emos_var > 0:
            emos_sigma = math.sqrt(emos_var)

    if is_stale:
        st.warning(
            f"No {cfg['init_hour']:02d} UTC run for {trade_date} yet. "
            f"Using most recent available run: {chosen_init.isoformat()}."
        )

    # Model-missing warnings only apply when we expected multiple models.
    if len(cfg["models"]) > 1:
        if "ifs" not in models_present:
            st.warning(
                "ECMWF data missing for this run — combined forecast is GEFS-only. "
                "Edges may be less reliable than usual."
            )
        elif "gefs" not in models_present:
            st.warning(
                "GEFS data missing for this run — combined forecast is ECMWF-only. "
                "Edges may be less reliable than usual."
            )

    # Forecast card
    st.subheader("Forecast")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        st.metric("Ensemble members", len(combined_values))
    with f2:
        st.metric(f"{cfg['ensemble_label']} mean", f"{cmean:.1f}°F")
    with f3:
        st.metric(f"{cfg['ensemble_label']} spread", f"{cstd:.2f}°F")
    with f4:
        if emos_mu is not None:
            st.metric("EMOS μ / σ", f"{emos_mu:.1f}° / {emos_sigma:.2f}°")
        else:
            st.metric("EMOS μ / σ", "—")

    # Probabilities
    if not contracts:
        st.info(f"No Kalshi contracts found for {trade_date}.")
        st.stop()

    raw_probs = compute_ensemble_probabilities(combined_values, contracts)
    emos_probs = {}
    if emos_mu is not None and emos_sigma is not None:
        emos_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

    # Decide which model drives the signal
    is_emos_choice = model_choice.startswith("EMOS")
    use_emos = is_emos_choice and bool(emos_probs)
    model_probs = emos_probs if use_emos else raw_probs
    if is_emos_choice and not emos_probs:
        st.warning("EMOS unavailable for this day; falling back to raw combined for signals.")

    # Edge table
    st.subheader("Edge by bracket")

    # Pull decision-time snapshot values from paper_trades AND live_trades for
    # this day. Both are decision-time records but at different times:
    #   - paper_trades: 14:45 UTC for all cities
    #   - live_trades:  per-city decision time (KMIA 15:30 UTC, KORD 14:46 UTC)
    # For Miami specifically, the paper-trade cron may have seen no signals at
    # 14:45 UTC but the live cron at 15:30 UTC saw 2 — prefer the live source
    # since it's what the actual order was placed against.
    # Pull per-city model_source from live_trade.CITY_CONFIG instead of
    # hardcoding — otherwise per-city model overrides (e.g. KORD's combined_hrrr)
    # wouldn't show up in Edge by bracket / live-trade matching. The local `cfg`
    # at this scope is a different dict, so call _live_trade_config() directly.
    _ltcfg = _live_trade_config()
    _ccfg = _ltcfg["CITY_CONFIG"].get(selected_station_id, {})
    paper_source_for_city = _ccfg.get("paper_model_source") or (
        "EMOS combined 00Z (rolling 45d)" if selected_station_id == "KNYC"
        else f"EMOS combined 00Z {selected_station.city} (rolling 45d)"
    )
    live_source_for_city = _ccfg.get("live_model_source_tag") or (paper_source_for_city + " [LIVE]")
    paper_snapshot: dict[str, dict] = {}
    with get_connection() as _pconn:
        with _pconn.cursor() as _pcur:
            # 1. Pull paper_trades (14:45 UTC snapshot, all cities)
            _pcur.execute(
                """SELECT ticker, edge, market_mid_prob, model_prob_yes,
                          market_yes_bid, market_yes_ask, position, entry_price_cents,
                          market_snapshot_at
                   FROM paper_trades
                   WHERE target_date = %s AND model_source = %s""",
                (trade_date, paper_source_for_city),
            )
            for row in _pcur.fetchall():
                paper_snapshot[row[0]] = {
                    "edge": float(row[1]),
                    "market_mid": float(row[2]),
                    "model_p": float(row[3]),
                    "yes_bid": row[4],
                    "yes_ask": row[5],
                    "position": row[6],
                    "entry": row[7],
                    "snap_at": row[8],
                    "source": "paper",
                }
            # 2. Pull live_trades (per-city decision time) — overwrites paper if both exist
            _pcur.execute(
                """SELECT ticker, edge, market_mid_prob, model_prob_yes,
                          side, limit_price_cents, placed_at
                   FROM live_trades
                   WHERE target_date = %s AND model_source = %s""",
                (trade_date, live_source_for_city),
            )
            for row in _pcur.fetchall():
                paper_snapshot[row[0]] = {
                    "edge": float(row[1]),
                    "market_mid": float(row[2]),
                    "model_p": float(row[3]),
                    "yes_bid": None,
                    "yes_ask": None,
                    "position": ("BUY_YES" if row[4] == "yes" else "BUY_NO"),
                    "entry": int(row[5]),
                    "snap_at": row[6],
                    "source": "live",
                }
    n_frozen = len(paper_snapshot)

    # Fallback for contracts WITHOUT a frozen snapshot yet: pull latest live
    # prices so Market P / Edge / Signal update in real time before the cron
    # fires at 14:45 UTC. After cron, the paper_snapshot above takes over and
    # the values are LOCKED at decision time (so the user sees what was true
    # when the trade was entered, not chasing post-decision price movement).
    live_prices: dict[str, dict] = {}
    if contracts:
        with get_connection() as _lconn, _lconn.cursor() as _lcur:
            _lcur.execute(
                """SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
                   FROM prices
                   WHERE ticker = ANY(%s)
                   ORDER BY ticker, snapshot_at DESC""",
                ([c["ticker"] for c in contracts],),
            )
            for tk, yb, ya, sa in _lcur.fetchall():
                if yb is not None and ya is not None:
                    mid = (yb + ya) / 200.0
                    live_prices[tk] = {"market_mid": mid, "yes_bid": yb, "yes_ask": ya, "snap_at": sa}

    def range_label(c):
        if c["bracket_type"] == "greater_than":
            return f">{c['strike_low']}°"
        elif c["bracket_type"] == "less_than":
            return f"<{c['strike_high']}°"
        return f"{c['strike_low']}-{c['strike_high']}°"

    def sort_key(c):
        # Sort brackets by their lower edge for a readable ladder
        if c["bracket_type"] == "less_than":
            return (c["strike_high"] or 0) - 1000
        return c["strike_low"] if c["strike_low"] is not None else 0

    rows = []
    for c in sorted(contracts, key=sort_key):
        ticker = c["ticker"]
        # ALL Market P / Edge / Signal values are frozen at the 14:45 UTC
        # paper-trade snapshot. If no paper_trades row exists for this contract
        # (didn't pass |edge|>=10% at decision time, or paper-trade cron hasn't
        # fired yet today), show '—' rather than live-recomputed values — the
        # whole point is to show what was true AT TRADE ENTRY.
        snap = paper_snapshot.get(ticker)
        if snap is not None:
            # FROZEN at decision time (paper_trades / live_trades snapshot)
            m_prob = snap["model_p"]
            mkt = snap["market_mid"]
            edge = snap["edge"]
            is_live_pre_decision = False
        elif live_prices.get(ticker) and (emos_probs.get(ticker) or raw_probs.get(ticker)):
            # LIVE pre-decision: market prices update in real time, edge computed
            # against current EMOS (or raw) model probability
            m_prob = emos_probs.get(ticker) or raw_probs.get(ticker)
            mkt = live_prices[ticker]["market_mid"]
            edge = m_prob - mkt
            is_live_pre_decision = True
        else:
            m_prob = None
            mkt = None
            edge = None
            is_live_pre_decision = False

        if edge is None:
            signal = "—"
        elif edge >= edge_threshold:
            signal = "BUY YES"
        elif edge <= -edge_threshold:
            signal = "BUY NO"
        else:
            signal = ""

        if observed_high is None:
            resolved = "—"
        else:
            resolved = "YES" if contract_resolved_yes(int(observed_high), c) else "NO"

        rows.append({
            "Contract": ticker.replace(f"{selected_series}-", ""),
            "Range": range_label(c),
            "Raw P": f"{raw_probs.get(ticker, 0):.1%}",
            "EMOS P": f"{emos_probs.get(ticker, 0):.1%}" if emos_probs else "—",
            "Market P": f"{mkt:.1%}" if mkt is not None else "—",
            "Edge": f"{edge:+.1%}" if edge is not None else "—",
            "Signal": signal,
            "Resolved": resolved,
        })

    edge_df = pd.DataFrame(rows)

    def highlight_resolved(val):
        if val == "YES":
            return "background-color: #1b4d2e; color: #b6f5c8"
        if val == "NO":
            return "background-color: #5c1a1a; color: #f5b6b6"
        return ""

    def highlight_signal(val):
        if val == "BUY YES":
            return "background-color: #1b4d2e; color: #b6f5c8"
        if val == "BUY NO":
            return "background-color: #5c1a1a; color: #f5b6b6"
        return ""

    styled = (
        edge_df.style
        .map(highlight_signal, subset=["Signal"])
        .map(highlight_resolved, subset=["Resolved"])
    )
    st.dataframe(styled, width='stretch', hide_index=True)

    n_live = sum(1 for c in contracts if c["ticker"] in live_prices and c["ticker"] not in paper_snapshot)
    if n_frozen > 0:
        edge_basis = (
            f"Market P / Edge / Signal are frozen at the 14:45 UTC paper-trade snapshot "
            f"({n_frozen} of {len(contracts)} brackets had a logged signal). "
            "Brackets without a logged signal show live current prices "
            "(updating every ~5min) until cron locks them at 14:45 UTC."
        )
    elif n_live > 0:
        edge_basis = (
            f"LIVE pre-decision view ({n_live} brackets have live prices). "
            "Market P / Edge update every ~5min until 14:45 UTC cron fires; "
            "then values lock at the decision snapshot."
        )
    else:
        edge_basis = (
            "No price snapshots yet today. Market P / Edge / Signal will populate "
            "as soon as Kalshi prices come in (every 5min cron)."
        )
    st.caption(
        f"Signal source: {model_choice}. Flagging when |edge| ≥ {edge_threshold:.0%}. "
        + edge_basis +
        " This is a decision aid, not advice — small sample, paper-trade first."
    )

    # P&L simulation (resolved paper trades, configurable sizing + filters) + log table
    # NOTE: limit raised from 10000 to 100000 — total paper_trades is ~17k
    # since the 2025-05-27 cutoff and continues to grow. The old 10000 silently
    # truncated the OLDEST ~6k trades, biasing the backtest toward the most
    # recent period (which differs from earlier months). Use a high enough
    # cap that we never truncate in practice.
    pt_df_all = paper_trades_with_outcomes(limit=100000)
    n_total_all = len(pt_df_all)

    st.subheader("P&L simulation")

    if pt_df_all.empty:
        st.info("No paper trades logged yet. The 14:45 UTC cron will populate this once it runs.")
    elif int(pt_df_all["won"].notna().sum()) == 0:
        st.info(f"{n_total_all} paper trade(s) logged, none resolved yet. Simulation appears once observations land.")
    else:
        # --- Scope paper_trades to the city chosen at the top of the tab ----
        # Filter model_sources to those belonging to the selected city + platform.
        # Platform tag convention: model_source contains 'POLYMARKET' for Polymarket-
        # backfilled sources. Otherwise Kalshi (default).
        other_city_tags = [s.city for s in all_stations() if s.station_id != "KNYC"]
        all_sources = sorted(pt_df_all["model_source"].unique().tolist())
        if selected_station_id == "KNYC":
            city_sources = [s for s in all_sources if not any(t in s for t in other_city_tags)]
        else:
            city_sources = [s for s in all_sources if selected_station.city in s]
        # Apply platform filter
        if selected_platform == "Polymarket":
            city_sources = [s for s in city_sources if "POLYMARKET" in s.upper()]
        else:
            city_sources = [s for s in city_sources if "POLYMARKET" not in s.upper()]

        if not city_sources:
            st.info(
                f"No {selected_platform} paper trades for {selected_station.city} yet — "
                f"backfill needed. (Run: backfill_paper_trades.py --station {selected_station_id} "
                f"--platform polymarket once forecasts + observations are ingested.)"
            )
            st.stop()

        # Compute overfit-optimal (entry, edge) per source. Brute search over a
        # standard grid; pick the cell with highest mean P&L at n>=20.
        # NOT cached — closures over the outer pt_df_all DataFrame don't play
        # well with st.cache_data (it can't see the data changed). Recomputes
        # on each rerun, which is fine because the grid is tiny.
        def _overfit_optimal_for_source(source: str) -> tuple[int, float, dict]:
            """Returns (best_entry_pct, best_edge_pct, stats_dict)."""
            subset = pt_df_all[pt_df_all["model_source"] == source].copy()
            subset = subset[subset["won"].notna()]
            if len(subset) < 20:
                return (60, 0.10, {"mean": 0, "n": len(subset)})
            best = (60, 0.10, {"mean": -999, "n": 0})
            for et in [0, 30, 50, 60, 65, 70, 75, 80]:
                for ed in [0.10, 0.125, 0.15, 0.20, 0.25, 0.30]:
                    cell = subset[
                        (subset["entry_price_cents"] >= et)
                        & (subset["edge"].abs() >= ed)
                    ]
                    if len(cell) < 20:
                        continue
                    fees = cell["entry_price_cents"].astype(int).map(kalshi_fee_cents)
                    net = cell["pnl_cents_per_unit"] - fees
                    m = float(net.mean())
                    if m > best[2]["mean"]:
                        best = (et, ed, {"mean": m, "n": len(cell), "win": float(cell["won"].mean())})
            return best

        # --- Model-variant selector (gefs / ifs / combined) within the chosen city.
        def _variant_label(s: str) -> str:
            if "GEFS" in s and "combined" not in s: return "GEFS only"
            if "ECMWF" in s or ("IFS" in s and "combined" not in s): return "ECMWF only"
            if "combined" in s: return "Combined (GEFS + ECMWF)"
            return s
        variant_labels = {_variant_label(s): s for s in city_sources}
        # Prefer combined as default
        default_variant = next((l for l in variant_labels if "Combined" in l), list(variant_labels)[0])

        c_select, c_info = st.columns([1, 2])
        with c_select:
            chosen_variant = st.radio(
                f"{selected_station.city} model variant",
                options=list(variant_labels.keys()),
                index=list(variant_labels.keys()).index(default_variant),
                help="Toggle between the three EMOS variants available for this city. "
                     "Combined is the production source; single-model variants are diagnostics.",
            )
            source_filter = variant_labels[chosen_variant]
        with c_info:
            opt_entry, opt_edge, opt_stats = _overfit_optimal_for_source(source_filter)
            if opt_stats.get("mean", 0) > -100:
                st.info(
                    f"**Overfit-optimal filter for {selected_station.city} / {chosen_variant}:** "
                    f"entry ≥ {opt_entry}¢ AND |edge| ≥ {opt_edge:.0%} → "
                    f"mean P&L {opt_stats['mean']:+.2f}¢/trade across n={opt_stats['n']} trades "
                    f"({opt_stats.get('win', 0)*100:.0f}% win rate). "
                    "**Filters below are set to this — adjust to explore.**"
                )

        st.warning(
            "⚠️ **Overfit defaults.** These filters were selected POST-HOC by scanning the city's data "
            "for the best mean P&L. They are NOT pre-committed strategy choices. Different cities have "
            "different 'optimal' filters that contradict each other — that's the signature of overfitting. "
            "The live strategy uses NYC's pre-committed filter (entry ≥ 60¢, |edge| ≥ 10%) unchanged."
        )

        # --- Filter controls. Defaults wire to the city's overfit-optimal. ----
        # Use a session key per source so sliders snap when the city changes.
        slider_key_suffix = source_filter.replace(" ", "_")
        f1, f2 = st.columns(2)
        with f1:
            edge_filter = st.slider(
                "Min |edge| filter", min_value=0.10, max_value=0.50,
                value=max(0.10, opt_edge), step=0.01,
                key=f"edge_filter_{slider_key_suffix}",
                help="Only include trades where |edge| ≥ this. Lower thresholds aren't available "
                     "because the cron only logs trades at |edge| ≥ 0.10.",
            )
        with f2:
            min_entry_price = st.slider(
                "Min entry price (¢)", min_value=0, max_value=99,
                value=int(opt_entry), step=1,
                key=f"entry_filter_{slider_key_suffix}",
                help="Only include trades where entry price ≥ this. Default snaps to the city's "
                     "overfit-optimal cell.",
            )

        # Strategy comparison table — this city's model_sources at the chosen edge + entry filters.
        # Shows the headline edge-test stats for each configuration side-by-side so you
        # can compare without toggling the radio.
        st.markdown(
            f"**Strategy comparison — {selected_station.city}** "
            f"(|edge| ≥ {edge_filter:.0%}, entry ≥ {min_entry_price}¢)"
        )
        comparison_rows = []
        for source in sorted(city_sources):
            subset = pt_df_all[
                (pt_df_all["model_source"] == source)
                & (pt_df_all["edge"].abs() >= edge_filter)
                & (pt_df_all["entry_price_cents"] >= min_entry_price)
                & (pt_df_all["won"].notna())
            ]
            if subset.empty:
                continue
            n = len(subset)
            win_rate = subset["won"].sum() / n
            fees = subset["entry_price_cents"].astype(int).map(kalshi_fee_cents)
            net = subset["pnl_cents_per_unit"] - fees
            mean_net = float(net.mean())
            sd_net = float(net.std()) if n > 1 else 0.0
            t_stat = mean_net / (sd_net / math.sqrt(n)) if sd_net > 0 else float("nan")
            total_dollars = float(net.sum()) / 100.0
            comparison_rows.append({
                "Model source": source,
                "n": n,
                "Win rate": f"{win_rate:.1%}",
                "Mean net P&L": f"{mean_net:+.2f}¢",
                "t-stat": f"{t_stat:+.2f}" if not math.isnan(t_stat) else "—",
                "Total ($, unit sizing)": f"${total_dollars:+.2f}",
            })
        if comparison_rows:
            st.dataframe(pd.DataFrame(comparison_rows), width="stretch", hide_index=True)
            st.caption(
                "Each row is the full edge-test result for that strategy at |edge| ≥ "
                f"{edge_filter:.0%}. Slide the threshold up to explore subgroup behavior — "
                "but per the pre-registered protocol, decision criteria need to be set BEFORE seeing the table."
            )
        else:
            st.info("No resolved trades for any model source at this threshold.")

        pt_df = pt_df_all[
            (pt_df_all["edge"].abs() >= edge_filter)
            & (pt_df_all["entry_price_cents"] >= min_entry_price)
            & (pt_df_all["model_source"] == source_filter)
        ]
        n_total = len(pt_df)
        n_resolved = int(pt_df["won"].notna().sum()) if not pt_df.empty else 0

        if n_resolved == 0:
            st.info(
                f"No resolved trades match the current filters "
                f"(|edge| ≥ {edge_filter:.0%}, entry ≥ {min_entry_price}¢, "
                f"source = {source_filter}, n_filtered = {n_total})."
            )
        else:
            c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
            with c1:
                starting_balance = st.number_input(
                    "Starting balance ($)", min_value=1.0, value=100.0, step=10.0,
                )
            with c2:
                sizing_type = st.radio(
                    "Sizing strategy",
                    ["Unit", "Amount $", "Kelly", "Scaling"],
                    index=0,
                    horizontal=True,
                    help=(
                        "Unit: fixed contract count per trade. "
                        "Amount $: fixed dollars staked per trade (contracts = $ / entry_price). "
                        "Kelly: stake = bankroll × Kelly_optimal × chosen fraction. "
                        "Scaling: stake = bankroll × chosen % (compounds)."
                    ),
                )
            with c3:
                execution_label = st.radio(
                    "Execution",
                    ["Cross spread", "Limit (100% fill)", "Limit (70% fill)", "Limit (50% fill)",
                     "Empirical comparison"],
                    index=0,
                    help=(
                        "Cross spread = pay the marketable price (paper-trade default). "
                        "Limit = post 1¢ inside the spread, missed fills count as $0 (% is a guess). "
                        "Empirical comparison = compute actual fill outcomes from historical price "
                        "snapshots and run 3 modes side-by-side (post-inside-spread / cross-at-ask / "
                        "cross-with-premium+1)."
                    ),
                )
                execution_mode = {
                    "Cross spread": "cross",
                    "Limit (100% fill)": "limit_100",
                    "Limit (70% fill)": "limit_70",
                    "Limit (50% fill)": "limit_50",
                    "Empirical comparison": "empirical_compare",
                }[execution_label]
            with c4:
                # Defaults — only the active mode's value is used by the sim
                contracts_per_trade = 1
                kelly_fraction = 0.5
                scaling_pct = 0.05
                amount_dollars = 25.0

                if sizing_type == "Unit":
                    contracts_per_trade = st.number_input(
                        "Contracts per trade", min_value=1, value=1, step=1,
                        help="Same fixed count on every trade. Ignores bankroll.",
                    )
                    strategy_label = f"Unit ({contracts_per_trade} contract{'s' if contracts_per_trade != 1 else ''})"
                elif sizing_type == "Amount $":
                    amount_dollars = st.number_input(
                        "Dollars per trade ($)", min_value=1.0, value=25.0, step=5.0,
                        help="Fixed $ staked per trade. Contracts = $ / (entry_price / 100). "
                             "At 10¢ entry, $25 = 250 contracts. At 50¢ entry, $25 = 50 contracts. "
                             "Doesn't compound (no bankroll dependency).",
                    )
                    strategy_label = f"Amount (${amount_dollars:.0f}/trade)"
                elif sizing_type == "Scaling":
                    scaling_pct_int = st.select_slider(
                        "% of bankroll per trade",
                        options=[1, 2, 3, 5, 7, 10, 15, 20, 25],
                        value=5,
                        help="Each trade stakes this fixed percentage of CURRENT bankroll, "
                             "regardless of edge magnitude. Compounds with wins/losses.",
                    )
                    scaling_pct = scaling_pct_int / 100.0
                    strategy_label = f"Scaling ({scaling_pct_int}% of bankroll)"
                else:  # Kelly
                    kelly_pct = st.select_slider(
                        "Kelly fraction (%)",
                        options=[10, 20, 25, 33, 50, 75, 100],
                        value=50,
                        help="Multiplier on the Kelly-optimal stake. 50% = half Kelly (conservative).",
                    )
                    kelly_fraction = kelly_pct / 100.0
                    strategy_label = f"Kelly ({kelly_pct}%)"

            sim_mode = {"Unit": "unit", "Amount $": "amount",
                        "Kelly": "kelly", "Scaling": "scaling"}[sizing_type]

            # Stake cap UI (Kelly + Scaling only). Without a cap, Kelly bets the
            # model's full conviction (near-100% on confident trades → ruin on
            # one loss), and Scaling compounds to fantasy multi-billion balances
            # unreachable at Kalshi depth. Default 5% mirrors live_trade.py.
            max_stake_pct = None
            max_stake_dollars = None
            if sim_mode in ("kelly", "scaling"):
                cap_c1, cap_c2, cap_c3 = st.columns([1, 1, 2])
                with cap_c1:
                    cap_pct_int = st.select_slider(
                        "Max stake (% of bankroll)",
                        options=[1, 2, 5, 10, 20, 50, 100],
                        value=5,
                        help="Per-trade cap on stake as a fraction of CURRENT bankroll. "
                             "Live trading uses 5%. Set to 100% to disable (matches old "
                             "uncapped behavior — Kelly tanks to $0, Scaling compounds wildly).",
                    )
                    max_stake_pct = cap_pct_int / 100.0
                with cap_c2:
                    cap_dollar_input = st.number_input(
                        "Max stake ($, hard cap)",
                        min_value=0.0, value=0.0, step=10.0,
                        help="Hard dollar ceiling per trade (0 = no $ cap, only the % cap applies). "
                             "Use to model Kalshi market depth (~$1k per side).",
                    )
                    max_stake_dollars = cap_dollar_input if cap_dollar_input > 0 else None
                with cap_c3:
                    cap_summary = f"Active cap: {cap_pct_int}% of bankroll"
                    if max_stake_dollars:
                        cap_summary += f" OR ${max_stake_dollars:.0f}/trade (whichever lower)"
                    st.caption(cap_summary)

            # Max contracts per trade — models real-world Kalshi book depth.
            # Available for ALL sizing modes. 0 = no cap (default for backwards
            # compat). Set to ~1500 to match what real Kalshi books actually absorb
            # at the touch on low-priced contracts.
            depth_c1, depth_c2 = st.columns([1, 3])
            with depth_c1:
                max_contracts_input = st.number_input(
                    "Max contracts/trade (depth cap)",
                    min_value=0, value=0, step=100,
                    help="Per-trade cap on contract count, modeling Kalshi book depth at the touch. "
                         "0 = no cap (backtest assumes infinite depth). "
                         "Set to ~1500 for realistic ceiling: when Amount $ or Kelly would buy more "
                         "than this many contracts (typically on cheap entries), clamp the order to this cap. "
                         "Stake / fees / P&L recomputed from the capped count.",
                )
            max_contracts_per_trade = int(max_contracts_input) if max_contracts_input > 0 else None
            with depth_c2:
                if max_contracts_per_trade:
                    st.caption(f"📐 Depth cap: max **{max_contracts_per_trade:,} contracts/trade**. "
                               "Amount $ / Kelly / Scaling that would exceed this get clamped.")
                else:
                    st.caption("📐 No depth cap. Sim assumes infinite Kalshi book depth at every price.")

            # === Empirical comparison branch — runs simulator under 3 execution
            # modes side by side using actual price-history fill checks. ===
            if execution_mode == "empirical_compare":
                from datetime import datetime as _dt, time as _t, timezone as _tz
                # Build trade keys for the fill helper. decision time = 14:45 UTC for
                # paper-trade dataset (or per-city paper-trade decision time).
                # CRITICAL: sort ASC by (target_date, logged_at) to match simulate_pnl's
                # internal sort. Without this alignment the idx used to build
                # empirical_fills points to DIFFERENT trades than simulate_pnl iterates
                # — producing PnL computed with one trade's limit_price applied to a
                # different trade's win/loss flag (catastrophic miscalc, especially for
                # BUY_NO trades where limit_price differs hugely from cross_entry).
                resolved_df = (
                    pt_df[pt_df["won"].notna()]
                    .copy()
                    .sort_values(["target_date", "logged_at"])
                    .reset_index(drop=True)
                )
                keys = []
                idx_to_key = {}
                # Snapshot density check — only trades from days with at least
                # 50 prices/day for the ticker count as "empirical-eligible."
                trade_keys: list[tuple] = []
                for i, r in resolved_df.iterrows():
                    target_date = r["target_date"]
                    decision_time = _dt.combine(target_date, _t(14, 45), tzinfo=_tz.utc).isoformat()
                    side = r["position"]
                    cross_entry = int(r["entry_price_cents"])
                    tk = (r["ticker"], target_date, side, decision_time, cross_entry)
                    trade_keys.append(tk)
                    idx_to_key[i] = tk

                # Run the fill check
                fills_by_key = compute_empirical_fills_for_trades(tuple(trade_keys))
                # Map row idx -> mode -> {filled, fill_price, limit_price}
                fills_by_idx: dict[int, dict] = {
                    i: fills_by_key.get(tk, {}) for i, tk in idx_to_key.items()
                }

                # Coverage: how many trades have ANY snapshot data for the day
                n_total_resolved = len(resolved_df)
                n_with_coverage = sum(
                    1 for i in fills_by_idx
                    if fills_by_idx[i] and any(
                        v.get("limit_price", 0) > 0 for v in fills_by_idx[i].values()
                    )
                )

                st.markdown(f"### Empirical execution-mode comparison")
                st.info(
                    f"📊 **Coverage:** {n_with_coverage} of {n_total_resolved} resolved trades have "
                    f"historical price snapshots for their target date. Modes shown below run only on "
                    f"the eligible subset. Newer dates have richer snapshot data (5-min) than older "
                    f"dates (hourly candles)."
                )
                st.caption(
                    "**post_inside_spread**: empirical — post at ask−(spread−1), check if "
                    "market price ever traded through our level. "
                    "**cross_at_ask**: assumes 100% fill at the ask (top-of-book, depth not verifiable). "
                    "**cross_with_premium+1**: assumes 100% fill at ask+1."
                )

                # Run sim for each mode
                modes = ("post_inside_spread", "cross_at_ask", "cross_with_premium_1")
                results = {}
                for m in modes:
                    sd = simulate_pnl(
                        pt_df, starting_balance, sim_mode,
                        contracts=int(contracts_per_trade),
                        kelly_fraction=kelly_fraction,
                        scaling_pct=scaling_pct,
                        amount_dollars=float(amount_dollars),
                        execution_mode=f"emp:{m}",
                        max_stake_pct=max_stake_pct,
                        max_stake_dollars=max_stake_dollars,
                        max_contracts_per_trade=max_contracts_per_trade,
                        empirical_fills=fills_by_idx,
                    )
                    results[m] = sd

                # Comparison table
                comp_rows = []
                for m in modes:
                    sd = results[m]
                    n_filled = int(sd["filled"].sum()) if "filled" in sd.columns else 0
                    n_attempts = max(1, int(sd["filled"].notna().sum()))
                    fill_pct = 100.0 * n_filled / n_attempts
                    final_bal = float(sd["balance"].iloc[-1])
                    ret_pct = (final_bal / starting_balance - 1) * 100
                    filled_pnl = sd.loc[sd["filled"] == True, "trade_pnl"] if "filled" in sd.columns else pd.Series([], dtype=float)
                    mean_pnl_per_filled = float(filled_pnl.mean()) if len(filled_pnl) > 0 else 0.0
                    # Max DD
                    bals = sd["balance"].dropna().astype(float).values
                    mdd_pct = 0.0
                    if len(bals) > 1:
                        peak = bals[0]
                        for b in bals:
                            if b > peak: peak = b
                            if peak > 0 and (b - peak) / peak < mdd_pct:
                                mdd_pct = (b - peak) / peak
                    comp_rows.append({
                        "Mode": {"post_inside_spread": "post_inside_spread (empirical)",
                                 "cross_at_ask": "cross_at_ask (depth-blind)",
                                 "cross_with_premium_1": "cross_with_premium=1 (depth-blind)"}[m],
                        "Fill rate": f"{fill_pct:.1f}% ({n_filled}/{n_attempts})",
                        "Mean $/filled trade": f"${mean_pnl_per_filled:+.2f}",
                        "Final balance": f"${final_bal:,.2f} ({ret_pct:+.1f}%)",
                        "Max drawdown": f"{mdd_pct*100:+.1f}%",
                    })
                st.dataframe(pd.DataFrame(comp_rows), width="stretch", hide_index=True)

                # Overlay balance curves
                import pandas as pd
                chart_rows = []
                for m in modes:
                    sd = results[m].dropna(subset=["date"]).copy()
                    sd["Mode"] = {"post_inside_spread": "post_inside_spread",
                                  "cross_at_ask": "cross_at_ask",
                                  "cross_with_premium_1": "cross_with_premium+1"}[m]
                    chart_rows.append(sd[["date", "balance", "Mode"]])
                chart_df = pd.concat(chart_rows, ignore_index=True)
                line = alt.Chart(chart_df).mark_line().encode(
                    x=alt.X("date:T", title="Date"),
                    y=alt.Y("balance:Q", title="Balance ($)"),
                    color=alt.Color("Mode:N", scale=alt.Scale(scheme="category10")),
                    tooltip=["date:T", "balance:Q", "Mode:N"],
                )
                baseline = alt.Chart(pd.DataFrame({"y": [starting_balance]})).mark_rule(
                    strokeDash=[4, 4], color="gray").encode(y="y:Q")
                st.altair_chart((line + baseline).properties(height=320), width="stretch")

                # Use the post_inside_spread result as the "main" sim_df for downstream code
                sim_df = results["post_inside_spread"]
            else:
                sim_df = simulate_pnl(
                    pt_df, starting_balance, sim_mode,
                    contracts=int(contracts_per_trade),
                    kelly_fraction=kelly_fraction,
                    scaling_pct=scaling_pct,
                    amount_dollars=float(amount_dollars),
                    execution_mode=execution_mode,
                    max_stake_pct=max_stake_pct,
                    max_stake_dollars=max_stake_dollars,
                    max_contracts_per_trade=max_contracts_per_trade,
                )
            final_balance = sim_df["balance"].iloc[-1]
            return_pct = (final_balance / starting_balance - 1) * 100
            n_won = int(pt_df["won"].sum())

            # Annualized Sharpe ratio. Uses per-trade P&L as a fraction of
            # starting bankroll. Annualizes by sqrt(trades_per_year). Only counts
            # FILLED trades (limit-mode misses excluded; they're 0 P&L by design).
            # No risk-free rate subtraction (negligible on Kalshi-style horizons).
            sharpe = float("nan")
            if "filled" in sim_df.columns:
                filled_pnl = sim_df.loc[sim_df["filled"] == True, "trade_pnl"]
                if len(filled_pnl) >= 2 and filled_pnl.std() > 0:
                    per_trade_returns = filled_pnl / starting_balance
                    # Annualize from the window span
                    dates = sim_df.dropna(subset=["date"])["date"]
                    if len(dates) >= 2:
                        window_days = max(1, (dates.max() - dates.min()).days)
                        trades_per_year = len(filled_pnl) * 365 / window_days
                    else:
                        trades_per_year = len(filled_pnl)
                    sharpe = (per_trade_returns.mean() / per_trade_returns.std()) * (trades_per_year ** 0.5)

            # Max drawdown — largest peak-to-trough decline in the balance curve.
            # Tells you the worst losing streak you'd have lived through. Reported
            # both as % of running peak (risk-adjusted) and as $ (absolute).
            balances = sim_df["balance"].dropna().astype(float).values
            max_dd_pct = 0.0
            max_dd_dollars = 0.0
            if len(balances) > 1:
                running_peak = balances[0]
                for b in balances:
                    if b > running_peak:
                        running_peak = b
                    dd_dollars = b - running_peak
                    dd_pct = dd_dollars / running_peak if running_peak > 0 else 0
                    if dd_dollars < max_dd_dollars:
                        max_dd_dollars = dd_dollars
                    if dd_pct < max_dd_pct:
                        max_dd_pct = dd_pct

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            with m1:
                st.metric("Final balance", f"${final_balance:.2f}", f"{return_pct:+.1f}%")
            with m2:
                st.metric("Resolved trades", f"{n_won}/{n_resolved}", f"{n_won/n_resolved*100:.0f}% win rate")
            with m3:
                st.metric("Sharpe (annualized)", f"{sharpe:.2f}" if sharpe == sharpe else "—",
                          help="Per-trade P&L annualized by sqrt(trades/year). Uses filled trades only. "
                               "No risk-free subtraction. Higher = better risk-adjusted return.")
            with m4:
                st.metric(
                    "Max drawdown",
                    f"{max_dd_pct*100:+.1f}%",
                    f"${max_dd_dollars:,.2f} peak-to-trough",
                    delta_color="inverse",
                    help="Largest peak-to-trough decline in the balance curve. "
                         "% is the deepest drop relative to running peak; $ is the absolute. "
                         "A −20% max DD means at some point you'd have been 20% below your high. "
                         "Closer to 0% = smoother ride.",
                )
            with m5:
                st.metric("Pending", n_total - n_resolved)
            with m6:
                st.metric("Filtered / total", f"{n_total} / {n_total_all}")

            plot_df = sim_df.dropna(subset=["date"]).copy()
            line = alt.Chart(plot_df).mark_line(point=True).encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("balance:Q", title="Balance ($)"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("balance:Q", title="Balance", format="$.2f"),
                    alt.Tooltip("trade_pnl:Q", title="Trade P&L", format="$.2f"),
                ],
            )
            baseline = (
                alt.Chart(pd.DataFrame({"y": [starting_balance]}))
                .mark_rule(strokeDash=[4, 4], color="gray")
                .encode(y="y:Q")
            )
            st.altair_chart((line + baseline).properties(height=300), width="stretch")

            cap_note = ""
            if sim_mode in ("kelly", "scaling") and "stake_capped" in sim_df.columns:
                n_capped = int(sim_df["stake_capped"].fillna(False).sum())
                if n_capped > 0:
                    cap_note = (
                        f" **Stake cap bound on {n_capped} of {n_resolved} trades** — "
                        "raw sizing exceeded the cap and was clamped. Without the cap, "
                        "balance curves are misleading (Kelly → $0, Scaling → fantasy)."
                    )
            st.caption(
                f"Strategy: {strategy_label}. Execution: {execution_label}. "
                f"Filter: |edge| ≥ {edge_filter:.0%}, entry ≥ {min_entry_price}¢, source = {source_filter}. "
                f"P&L is net of Kalshi trading fees "
                f"(per-contract: $0.07 × P × (1-P), rounded up to nearest cent). "
                f"Limit mode posts 1¢ inside the spread; missed fills (seed=42) are $0." + cap_note
            )

            # === Per-trade detail (what made up the curve above) ===
            st.markdown("**Trade-by-trade detail** — every paper trade that contributed to the curve above.")
            trade_rows = sim_df.dropna(subset=["date"]).copy()
            if not trade_rows.empty and "ticker" in trade_rows.columns:
                # Newest first so today's trades are at the top
                trade_rows = trade_rows.sort_values("date", ascending=False).reset_index(drop=True)

                table = pd.DataFrame({
                    "Date": trade_rows["date"].dt.strftime("%Y-%m-%d"),
                    "Contract": trade_rows["ticker"].astype(str).str.replace(f"{selected_series}-", "", regex=False),
                    "Bracket": trade_rows["bracket"],
                    "Side": trade_rows["side"],
                    "Edge": trade_rows["edge"].map(lambda x: f"{x:+.1%}"),
                    "Entry": trade_rows["entry_price_cents"].map(lambda x: f"{int(x)}¢"),
                    "Contracts": trade_rows["contracts"].map(lambda x: f"{int(x)}" if pd.notna(x) else "—"),
                    "Stake": trade_rows["stake_dollars"].map(lambda x: f"${x:.2f}"),
                    "Filled": trade_rows["filled"].map(lambda x: "✓" if x else "missed"),
                    "Won": trade_rows["won"].map(lambda x: "WIN" if x else "LOSS"),
                    "Trade P&L": trade_rows["trade_pnl"].map(lambda x: f"${x:+,.2f}"),
                    "Running balance": trade_rows["balance"].map(lambda x: f"${x:,.2f}"),
                })

                def color_pnl(v):
                    if "+" in str(v):
                        return "background-color: #1b4d2e; color: #b6f5c8"
                    if "-" in str(v):
                        return "background-color: #5c1a1a; color: #f5b6b6"
                    return ""

                def color_outcome(v):
                    if v == "WIN":
                        return "background-color: #1b4d2e; color: #b6f5c8"
                    if v == "LOSS":
                        return "background-color: #5c1a1a; color: #f5b6b6"
                    if v == "missed":
                        return "color: #888"
                    return ""

                styled = (table.style
                    .map(color_pnl, subset=["Trade P&L"])
                    .map(color_outcome, subset=["Won", "Filled"]))
                st.dataframe(styled, width="stretch", hide_index=True, height=420)

                # Summary footer
                n_total = len(trade_rows)
                n_filled = int(trade_rows["filled"].sum())
                n_wins = int(trade_rows["won"].sum())
                fc1, fc2, fc3, fc4 = st.columns(4)
                with fc1: st.metric("Trades", n_total)
                with fc2: st.metric("Filled", f"{n_filled} ({n_filled/n_total*100:.0f}%)" if n_total else "—")
                with fc3: st.metric("Wins", f"{n_wins} ({n_wins/n_total*100:.0f}%)" if n_total else "—")
                with fc4: st.metric("Avg P&L / trade", f"${trade_rows['trade_pnl'].mean():+,.2f}")
            else:
                st.caption("No trades in this filter window.")

    # Recent paper trades log (with outcomes)
    st.subheader("Recent paper trades")
    st.caption(
        "Daily prospective log of what the model would have traded (cron at 18:45 UTC). "
        "Outcome and P&L per unit appear once the day's observation lands."
    )
    if not pt_df.empty:
        recent = pt_df.head(14)

        def fmt_outcome(x):
            if x is True:
                return "Won"
            if x is False:
                return "Lost"
            return "Pending"

        # Limit-target = entry minus (spread - 1). Saves (spread - 1)¢/contract by
        # posting inside the spread rather than crossing it. Shown as guidance for
        # manual real-money trading; paper sim still uses cross-spread entry.
        def limit_target(row):
            bid, ask = row["market_yes_bid"], row["market_yes_ask"]
            entry = row["entry_price_cents"]
            if pd.isna(bid) or pd.isna(ask) or ask <= bid + 1:
                return None
            return int(entry - (ask - bid - 1))

        recent_with_target = recent.copy()
        recent_with_target["limit_target_cents"] = recent.apply(limit_target, axis=1)

        table = pd.DataFrame({
            "Date": recent["target_date"].astype(str),
            "Contract": recent["ticker"].str.replace(f"{selected_series}-", "", regex=False),
            "Position": recent["position"],
            "Model P": recent["model_prob_yes"].map(lambda x: f"{x:.1%}"),
            "Market P": recent["market_mid_prob"].map(lambda x: f"{x:.1%}"),
            "Edge": recent["edge"].map(lambda x: f"{x:+.1%}"),
            "Entry (cross)": recent["entry_price_cents"].map(lambda x: f"{x}¢"),
            "Limit target": recent_with_target["limit_target_cents"].map(
                lambda x: f"{int(x)}¢" if pd.notna(x) else "—"
            ),
            "High": recent["high_temp_f"].map(lambda x: f"{x:.0f}°" if pd.notna(x) else "—"),
            "Outcome": recent["won"].map(fmt_outcome),
            "P&L/unit": recent["pnl_cents_per_unit"].map(lambda x: f"{x:+.0f}¢" if pd.notna(x) else "—"),
        })

        def highlight_outcome(val):
            if val == "Won":
                return "background-color: #1b4d2e; color: #b6f5c8"
            if val == "Lost":
                return "background-color: #5c1a1a; color: #f5b6b6"
            return ""

        styled = table.style.map(highlight_outcome, subset=["Outcome"])
        st.dataframe(styled, width="stretch", hide_index=True)
        n_dates = recent["target_date"].nunique()
        st.caption(
            f"Showing {len(recent)} most recent entries across {n_dates} distinct target date(s). "
            "**Entry (cross)** = the marketable price (paper sim uses this). "
            "**Limit target** = posting 1¢ inside the spread (better fill if it executes); "
            "savings = spread − 1¢ per contract. Use limit-target for real trades when possible."
        )