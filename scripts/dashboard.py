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
    page_title="NYC Weather Forecasting Dashboard",
    page_icon="🌡️",
    layout="wide",
)


# =====================================================================
# SHARED DATA LAYER (cached) — defined above the tabs so both can use it
# =====================================================================

@st.cache_data
def collect_training_data():
    """Collect GEFS ensemble stats, observations, dates from database (market window)."""
    means, stds, obs, dates = [], [], [], []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id = %s", ("KNYC",))
            end = cur.fetchone()[0]

        target_date = date(2026, 5, 5)
        while target_date <= end:
            init_time = datetime(
                target_date.year, target_date.month, target_date.day,
                12, 0, tzinfo=timezone.utc,
            )
            try:
                highs = compute_daily_highs(init_time, target_date, conn)
                observation = fetch_observed_high(target_date, conn)
                if observation is not None:
                    values = list(highs.values())
                    means.append(statistics.mean(values))
                    stds.append(statistics.stdev(values))
                    obs.append(observation)
                    dates.append(target_date)
            except Exception:
                pass
            target_date += timedelta(days=1)

    return means, stds, obs, dates


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


def simulate_pnl(
    df: pd.DataFrame,
    starting_balance: float,
    sizing_type: str,
    *,
    contracts: int = 1,
    kelly_fraction: float = 0.5,
    scaling_pct: float = 0.05,
    execution_mode: str = "cross",
) -> pd.DataFrame:
    """Walk resolved trades chronologically and compute cumulative balance.

    sizing_type:
      - "unit"    — buy `contracts` contracts per trade (constant; ignores bankroll).
      - "kelly"   — stake = bankroll × kelly_fraction × Kelly-optimal fraction;
                    bankroll compounds. Bets MORE on high-edge trades.
      - "scaling" — stake = bankroll × scaling_pct (fixed % of CURRENT bankroll);
                    bankroll compounds but the % is constant regardless of edge.
                    Risk-per-trade is deterministic; aggressiveness doesn't depend
                    on the model's confidence in any particular signal.

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

    fill_rate = {"cross": 1.0, "limit_100": 1.0, "limit_70": 0.7, "limit_50": 0.5}[execution_mode]
    rng = random.Random(42)

    history = [{"date": None, "balance": starting_balance, "trade_pnl": 0.0}]
    balance = starting_balance

    for _, row in resolved.iterrows():
        cross_entry = int(row["entry_price_cents"])
        won = bool(row["won"])

        if execution_mode == "cross":
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

        if sizing_type == "unit":
            num_contracts_actual = int(contracts)
            gross_pnl = contracts * (100 - entry if won else -entry) / 100.0
            trade_pnl = gross_pnl - contracts * fee_per_contract
            stake_dollars = contracts * entry / 100.0
        elif sizing_type == "scaling":
            # Fixed % of CURRENT bankroll, no Kelly multiplier
            b = (100 - entry) / entry
            stake = balance * scaling_pct
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
            stake = balance * f  # dollars
            num_contracts = stake / (entry / 100.0) if entry > 0 else 0
            num_contracts_actual = int(round(num_contracts))
            total_fee = num_contracts * fee_per_contract
            gross_pnl = stake * b if won else -stake
            trade_pnl = gross_pnl - total_fee
            stake_dollars = stake

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
        })

    return pd.DataFrame(history)


@st.cache_data
def run_full_backtest():
    """For each day in the market window, compute raw / EMOS / market Brier."""
    means, stds, obs, dates = collect_training_data()

    results = []

    with get_connection() as conn:
        for i, target_date in enumerate(dates):
            init_time = datetime(
                target_date.year, target_date.month, target_date.day,
                12, 0, tzinfo=timezone.utc,
            )

            highs = compute_daily_highs(init_time, target_date, conn)
            contracts = fetch_contracts_for_date(target_date, conn)

            if not contracts:
                continue

            observation = int(obs[i])

            # Raw
            raw_probs = compute_ensemble_probabilities(highs, contracts)
            raw_scores = evaluate_predictions(raw_probs, contracts, observation)
            raw_brier = sum(raw_scores.values()) / len(raw_scores)

            # EMOS LOO
            train_means = means[:i] + means[i+1:]
            train_stds = stds[:i] + stds[i+1:]
            train_obs = obs[:i] + obs[i+1:]

            emos_brier = None
            if len(train_means) >= 2:
                try:
                    params = fit_emos(train_means, train_stds, train_obs)
                except RuntimeError:
                    params = None
                if params is not None:
                    corrected_mu = params['a'] + params['b'] * means[i]
                    corrected_var = params['c'] + params['d'] * stds[i]**2
                    if corrected_var > 0:
                        corrected_sigma = math.sqrt(corrected_var)
                        emos_probs = gaussian_to_bracket_probs(corrected_mu, corrected_sigma, contracts)
                        emos_scores = evaluate_predictions(emos_probs, contracts, observation)
                        emos_brier = sum(emos_scores.values()) / len(emos_scores)

            # Market
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                    FROM prices
                    WHERE ticker = ANY(%s) AND snapshot_at <= %s
                    ORDER BY ticker, snapshot_at DESC
                """, (tickers, init_time))
                price_rows = cur.fetchall()

            market_brier = None
            if price_rows:
                mkt_scores = []
                price_dict = {t: (b, a) for t, b, a in price_rows if b is not None and a is not None}
                for c in contracts:
                    if c["ticker"] in price_dict:
                        bid, ask = price_dict[c["ticker"]]
                        mid_prob = (bid + ask) / 200  # cents to prob
                        outcome = contract_resolved_yes(observation, c)
                        mkt_scores.append(brier_score(mid_prob, outcome))
                if mkt_scores:
                    market_brier = sum(mkt_scores) / len(mkt_scores)

            results.append({
                "date": target_date,
                "observed": observation,
                "raw_brier": raw_brier,
                "emos_brier": emos_brier,
                "market_brier": market_brier,
            })

    return pd.DataFrame(results)


@st.cache_data
def collect_calibration_pairs():
    """For each day in backtest range, collect (probability, outcome) pairs per model."""
    means, stds, obs, dates = collect_training_data()

    raw_pairs = []
    emos_pairs = []
    market_pairs = []

    with get_connection() as conn:
        for i, target_date in enumerate(dates):
            init_time = datetime(
                target_date.year, target_date.month, target_date.day,
                12, 0, tzinfo=timezone.utc,
            )

            highs = compute_daily_highs(init_time, target_date, conn)
            contracts = fetch_contracts_for_date(target_date, conn)
            if not contracts:
                continue

            observation = int(obs[i])

            # Raw
            raw_probs = compute_ensemble_probabilities(highs, contracts)
            for c in contracts:
                outcome = contract_resolved_yes(observation, c)
                raw_pairs.append((raw_probs[c["ticker"]], outcome))

            # EMOS LOO
            train_means = means[:i] + means[i+1:]
            train_stds = stds[:i] + stds[i+1:]
            train_obs = obs[:i] + obs[i+1:]

            if len(train_means) >= 2:
                try:
                    params = fit_emos(train_means, train_stds, train_obs)
                except RuntimeError:
                    params = None
                if params is not None:
                    emos_mu = params['a'] + params['b'] * means[i]
                    emos_var = params['c'] + params['d'] * stds[i]**2
                    if emos_var > 0:
                        emos_sigma = math.sqrt(emos_var)
                        emos_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)
                        for c in contracts:
                            outcome = contract_resolved_yes(observation, c)
                            emos_pairs.append((emos_probs[c["ticker"]], outcome))

            # Market
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                    FROM prices
                    WHERE ticker = ANY(%s) AND snapshot_at <= %s
                    ORDER BY ticker, snapshot_at DESC
                """, (tickers, init_time))
                for ticker, bid, ask in cur.fetchall():
                    if bid is not None and ask is not None:
                        mid_prob = (bid + ask) / 200
                        c = next(c for c in contracts if c["ticker"] == ticker)
                        outcome = contract_resolved_yes(observation, c)
                        market_pairs.append((mid_prob, outcome))

    return raw_pairs, emos_pairs, market_pairs


@st.cache_data
def build_diagnostic_df():
    means, stds, obs, dates = collect_training_data()

    rows = []
    for i, target_date in enumerate(dates):
        raw_pred = means[i]
        raw_std = stds[i]
        observed = obs[i]
        raw_error = raw_pred - observed
        raw_abs_error = abs(raw_error)

        rows.append({
            "date": target_date,
            "raw_predicted": raw_pred,
            "raw_std": raw_std,
            "observed": observed,
            "raw_error": raw_error,
            "raw_abs_error": raw_abs_error,
        })

    return pd.DataFrame(rows)


@st.cache_data
def run_multimodel_comparison():
    """Six-way MAE/CRPS comparison: raw vs EMOS for gefs, ifs, combined (full year)."""
    from weather_markets.emos import crps_gaussian

    def collect(conn, source, start, end):
        m_, s_, o_ = [], [], []
        td = start
        while td <= end:
            it = datetime(td.year, td.month, td.day, 12, 0, tzinfo=timezone.utc)
            try:
                if source == "combined":
                    values = compute_combined_daily_highs(it, td, conn)
                else:
                    values = list(compute_daily_highs(it, td, conn, model=source).values())
            except Exception:
                td += timedelta(days=1); continue
            if len(values) < 2:
                td += timedelta(days=1); continue
            ob = fetch_observed_high(td, conn)
            if ob is None:
                td += timedelta(days=1); continue
            m_.append(statistics.mean(values)); s_.append(statistics.stdev(values)); o_.append(ob)
            td += timedelta(days=1)
        return m_, s_, o_

    rows = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id=%s", ("KNYC",))
            end = cur.fetchone()[0]
        for source in ["gefs", "ifs", "combined"]:
            m_, s_, o_ = collect(conn, source, date(2025, 5, 1), end)
            n = len(m_)
            if n < 10:
                continue
            raw_mae = sum(abs(a - b) for a, b in zip(m_, o_)) / n
            raw_crps = sum(crps_gaussian(a, c, b) for a, c, b in zip(m_, s_, o_) if c > 0) / n
            try:
                params = fit_emos(m_, s_, o_)
            except RuntimeError:
                continue
            e_abs, e_crps = [], []
            for a, c, b in zip(m_, s_, o_):
                mu = params["a"] + params["b"] * a
                var = params["c"] + params["d"] * c**2
                if var <= 0:
                    continue
                e_abs.append(abs(mu - b)); e_crps.append(crps_gaussian(mu, math.sqrt(var), b))
            rows.append({
                "Source": source, "Days": n,
                "Raw MAE": raw_mae, "EMOS MAE": sum(e_abs) / len(e_abs),
                "Raw CRPS": raw_crps, "EMOS CRPS": sum(e_crps) / len(e_crps),
            })
    return pd.DataFrame(rows)


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

tab_analysis, tab_live, tab_backtest = st.tabs(["Analysis", "Live Trading", "Backtest"])


# ---------------------------------------------------------------------
# ANALYSIS TAB (existing panels)
# ---------------------------------------------------------------------
with tab_analysis:
    st.title("NYC Weather Forecasting Dashboard")
    st.markdown(
        "Backtesting raw ensemble vs EMOS vs Kalshi market predictions "
        "for daily NYC high temperatures."
    )

    with st.sidebar:
        st.header("Info")
        st.markdown("""
        This dashboard compares three forecasting approaches for NYC daily high temperatures:

        - **Raw Ensemble**: Naive probability from GEFS 31-member ensemble
        - **EMOS**: Gaussian post-processing with leave-one-out validation
        - **Market**: Kalshi mid-price implied probabilities

        Lower Brier score = better forecast.
        """)
        st.divider()
        if st.button("Clear Cache"):
            st.cache_data.clear()
            st.rerun()

    df = run_full_backtest()

    if df.empty:
        st.error("No backtest data available.")
        st.stop()

    # === Panel 1: Summary stats ===
    st.header("Summary")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Days backtested", len(df))
    with col2:
        raw_mean = df['raw_brier'].mean()
        st.metric("Raw Ensemble Brier", f"{raw_mean:.4f}")
    with col3:
        emos_mean = df['emos_brier'].mean()
        delta = emos_mean - raw_mean
        st.metric("EMOS Brier", f"{emos_mean:.4f}", delta=f"{delta:+.4f}", delta_color="inverse")
    with col4:
        market_mean = df['market_brier'].mean()
        delta = market_mean - raw_mean
        st.metric("Market Brier", f"{market_mean:.4f}", delta=f"{delta:+.4f}", delta_color="inverse")

    # === Panel 2: Daily comparison chart ===
    st.header("Daily Brier Comparison")

    chart_df = df.melt(
        id_vars=['date'],
        value_vars=['raw_brier', 'emos_brier', 'market_brier'],
        var_name='Model',
        value_name='Brier Score'
    )
    chart_df['date_str'] = chart_df['date'].astype(str)
    chart_df['Model'] = chart_df['Model'].map({
        'raw_brier': 'Raw Ensemble',
        'emos_brier': 'EMOS',
        'market_brier': 'Market',
    })

    chart = alt.Chart(chart_df).mark_bar().encode(
        x=alt.X('date_str:N', title='Date', sort=None),
        xOffset='Model:N',
        y=alt.Y('Brier Score:Q', title='Brier Score'),
        color=alt.Color(
            'Model:N',
            scale=alt.Scale(
                domain=['Raw Ensemble', 'EMOS', 'Market'],
                range=['#ff6b6b', '#4ecdc4', '#ffe66d'],
            ),
        ),
        tooltip=['date_str:N', 'Model:N', 'Brier Score:Q'],
    ).properties(height=400)

    st.altair_chart(chart, width='stretch')

    # === Panel 3: Per-day data table ===
    st.header("Per-Day Details")
    display_df = df.copy()
    display_df['raw_brier'] = display_df['raw_brier'].round(4)
    display_df['emos_brier'] = display_df['emos_brier'].round(4)
    display_df['market_brier'] = display_df['market_brier'].round(4)
    st.dataframe(display_df, width='stretch')

    # === Panel 4: Rolling Mean Brier ===
    st.header("Rolling Mean Brier")
    cumulative_df = pd.DataFrame()
    for col in ['raw_brier', 'emos_brier', 'market_brier']:
        cumulative_df[col] = df[col].expanding().mean()
    cumulative_df['date'] = df['date']

    melted = cumulative_df.melt(
        id_vars=['date'],
        value_vars=['raw_brier', 'emos_brier', 'market_brier'],
        var_name='Model',
        value_name='Cumulative Brier'
    )
    melted['Model'] = melted['Model'].map({
        'raw_brier': 'Raw Ensemble',
        'emos_brier': 'EMOS',
        'market_brier': 'Market',
    })
    st.line_chart(melted, x='date', y='Cumulative Brier', color='Model')

    # === Panel 5: Per-day drill-down ===
    st.header("Per-Day Drill-Down")
    available_dates = df['date'].tolist()
    selected_date = st.selectbox(
        "Select a date to investigate",
        options=available_dates,
        format_func=lambda d: d.strftime("%a %b %d, %Y"),
        index=len(available_dates) - 1,
    )

    with get_connection() as conn:
        init_time = datetime(
            selected_date.year, selected_date.month, selected_date.day,
            12, 0, tzinfo=timezone.utc,
        )
        highs = compute_daily_highs(init_time, selected_date, conn)
        contracts = fetch_contracts_for_date(selected_date, conn)
        observed = fetch_observed_high(selected_date, conn)

        raw_probs = compute_ensemble_probabilities(highs, contracts) if contracts else {}

        means, stds, obs, dates = collect_training_data()
        idx = dates.index(selected_date)
        train_means = means[:idx] + means[idx+1:]
        train_stds = stds[:idx] + stds[idx+1:]
        train_obs = obs[:idx] + obs[idx+1:]

        emos_probs = {}
        emos_mu = None
        if len(train_means) >= 2 and contracts:
            params = fit_emos(train_means, train_stds, train_obs)
            emos_mu = params['a'] + params['b'] * means[idx]
            emos_var = params['c'] + params['d'] * stds[idx]**2
            if emos_var > 0:
                emos_sigma = math.sqrt(emos_var)
                emos_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)

        market_probs = {}
        if contracts:
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask
                    FROM prices
                    WHERE ticker = ANY(%s) AND snapshot_at <= %s
                    ORDER BY ticker, snapshot_at DESC
                """, (tickers, init_time))
                for ticker, bid, ask in cur.fetchall():
                    if bid is not None and ask is not None:
                        market_probs[ticker] = (bid + ask) / 200

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Observed", f"{observed}°F" if observed else "—")
    with col2:
        ensemble_mean = statistics.mean(highs.values())
        st.metric("Raw mean", f"{ensemble_mean:.1f}°F")
    with col3:
        if emos_mu is not None:
            st.metric("EMOS mean", f"{emos_mu:.1f}°F")
        else:
            st.metric("EMOS mean", "—")
    with col4:
        raw_err = ensemble_mean - observed if observed else None
        st.metric("Raw error", f"{raw_err:+.1f}°F" if raw_err is not None else "—")

    st.subheader("Ensemble Member Distribution")
    hist_df = pd.DataFrame({
        'temperature': list(highs.values()),
        'count': [1] * len(highs),
    })
    hist_chart = alt.Chart(hist_df).mark_bar(opacity=0.7).encode(
        x=alt.X('temperature:Q', bin=alt.Bin(step=0.5), title='Predicted High (°F)'),
        y=alt.Y('count():Q', title='Member Count'),
        color=alt.value('#4ecdc4'),
    ).properties(height=300)

    if observed is not None:
        obs_line = alt.Chart(pd.DataFrame({'observed': [observed]})).mark_rule(
            color='#ff6b6b', strokeWidth=3,
        ).encode(x='observed:Q')
        chart_combined = hist_chart + obs_line
    else:
        chart_combined = hist_chart
    st.altair_chart(chart_combined, width='stretch')

    st.subheader("Contract Probabilities")
    if contracts:
        table_rows = []
        for c in contracts:
            ticker = c["ticker"]
            if c["bracket_type"] == "greater_than":
                range_str = f">{c['strike_low']}°"
            elif c["bracket_type"] == "less_than":
                range_str = f"<{c['strike_high']}°"
            else:
                range_str = f"{c['strike_low']}-{c['strike_high']}°"

            outcome = contract_resolved_yes(int(observed), c) if observed else None

            table_rows.append({
                "Contract": ticker.replace("KXHIGHNY-", ""),
                "Range": range_str,
                "Raw P": f"{raw_probs.get(ticker, 0):.1%}" if raw_probs else "—",
                "EMOS P": f"{emos_probs.get(ticker, 0):.1%}" if emos_probs else "—",
                "Market P": f"{market_probs.get(ticker, 0):.1%}" if market_probs else "—",
                "Resolved": "YES" if outcome else "NO" if outcome is not None else "—",
            })
        st.dataframe(pd.DataFrame(table_rows), width='stretch', hide_index=True)

    # === Panel 6: Calibration plot ===
    st.header("🎯 Calibration")
    st.markdown(
        "Are predicted probabilities reliable? "
        "If a model says 70% and the event happens 70% of the time, it's calibrated. "
        "Points on the diagonal = perfect calibration. "
        "Points below = overconfident. Points above = underconfident."
    )

    raw_pairs, emos_pairs, market_pairs = collect_calibration_pairs()
    n_bins = st.slider("Number of bins", min_value=3, max_value=10, value=5)

    raw_bins = calibration_bins(raw_pairs, n_bins=n_bins)
    emos_bins = calibration_bins(emos_pairs, n_bins=n_bins)
    market_bins = calibration_bins(market_pairs, n_bins=n_bins)

    def bins_to_df(bins_data, model_name):
        return pd.DataFrame([
            {
                "mean_predicted": b["mean_predicted"],
                "fraction_true": b["fraction_true"],
                "count": b["count"],
                "Model": model_name,
            }
            for b in bins_data
        ])

    calib_df = pd.concat([
        bins_to_df(raw_bins, "Raw Ensemble"),
        bins_to_df(emos_bins, "EMOS"),
        bins_to_df(market_bins, "Market"),
    ], ignore_index=True)

    diagonal_df = pd.DataFrame({"mean_predicted": [0, 1], "fraction_true": [0, 1]})
    diagonal_chart = alt.Chart(diagonal_df).mark_line(
        color='gray', strokeDash=[5, 5],
    ).encode(x='mean_predicted:Q', y='fraction_true:Q')

    points_chart = alt.Chart(calib_df).mark_circle().encode(
        x=alt.X('mean_predicted:Q', scale=alt.Scale(domain=[0, 1]),
                title='Mean Predicted Probability'),
        y=alt.Y('fraction_true:Q', scale=alt.Scale(domain=[0, 1]),
                title='Observed Fraction True'),
        size=alt.Size('count:Q', title='Sample size', scale=alt.Scale(range=[50, 500])),
        color=alt.Color('Model:N', scale=alt.Scale(
            domain=['Raw Ensemble', 'EMOS', 'Market'],
            range=['#ff6b6b', '#4ecdc4', '#ffe66d'])),
        tooltip=['Model:N', 'mean_predicted:Q', 'fraction_true:Q', 'count:Q'],
    )

    lines_chart = alt.Chart(calib_df).mark_line(opacity=0.3).encode(
        x='mean_predicted:Q', y='fraction_true:Q',
        color=alt.Color('Model:N', scale=alt.Scale(
            domain=['Raw Ensemble', 'EMOS', 'Market'],
            range=['#ff6b6b', '#4ecdc4', '#ffe66d'])),
    )

    calib_chart = (diagonal_chart + lines_chart + points_chart).properties(height=500, width=600)
    st.altair_chart(calib_chart, width='stretch')

    with st.expander("Per-bin data"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Raw Ensemble**")
            st.dataframe(bins_to_df(raw_bins, "Raw").drop(columns=["Model"]))
        with c2:
            st.markdown("**EMOS**")
            st.dataframe(bins_to_df(emos_bins, "EMOS").drop(columns=["Model"]))
        with c3:
            st.markdown("**Market**")
            st.dataframe(bins_to_df(market_bins, "Market").drop(columns=["Model"]))

    # === Panel 7: Diagnostics ===
    st.header("🔬 Diagnostics")
    st.markdown(
        "Three views into model behavior. These help reveal where EMOS works "
        "and where it falls short."
    )

    diag_df = build_diagnostic_df()

    st.subheader("1. Is bias systematic in predicted temperature?")
    st.markdown(
        "If the model has a constant bias (e.g., always 1.6°F too warm), "
        "this scatter should show a horizontal trend. "
        "If the bias depends on temperature, you'll see a slope."
    )
    scatter_1 = alt.Chart(diag_df).mark_circle(size=100).encode(
        x=alt.X('raw_predicted:Q', title='Raw Predicted Mean (°F)', scale=alt.Scale(zero=False)),
        y=alt.Y('raw_error:Q', title='Error (predicted - observed, °F)'),
        tooltip=['date:T', 'raw_predicted:Q', 'observed:Q', 'raw_error:Q'],
    )
    zero_line_1 = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
        color='gray', strokeDash=[5, 5]).encode(y='y:Q')
    regression_1 = alt.Chart(diag_df).transform_regression(
        'raw_predicted', 'raw_error', method='linear'
    ).mark_line(color='red').encode(x='raw_predicted:Q', y='raw_error:Q')
    st.altair_chart((scatter_1 + zero_line_1 + regression_1).properties(height=350),
                    width='stretch')
    st.caption(
        "Gray dashed line = no bias. Red line = best linear fit through points. "
        "If the red line slopes downward, bias decreases as predicted temperature rises."
    )

    st.subheader("2. Does ensemble spread predict actual uncertainty?")
    st.markdown(
        "Theoretically, days where ensemble members disagree more should have "
        "bigger forecast errors. If spread is informative, you'll see a positive slope."
    )
    scatter_2 = alt.Chart(diag_df).mark_circle(size=100).encode(
        x=alt.X('raw_std:Q', title='Ensemble Standard Deviation (°F)', scale=alt.Scale(zero=False)),
        y=alt.Y('raw_abs_error:Q', title='Absolute Error (°F)', scale=alt.Scale(zero=False)),
        tooltip=['date:T', 'raw_std:Q', 'raw_abs_error:Q', 'observed:Q'],
    )
    regression_2 = alt.Chart(diag_df).transform_regression(
        'raw_std', 'raw_abs_error', method='linear'
    ).mark_line(color='red').encode(x='raw_std:Q', y='raw_abs_error:Q')
    st.altair_chart((scatter_2 + regression_2).properties(height=350),
                    width='stretch')
    st.caption(
        "If ensemble spread is informative, points should slope upward. "
        "Flat or negative slope = under-dispersion."
    )

    st.subheader("3. Is the model calibrated differently for confident vs uncertain predictions?")
    st.markdown(
        "Split predictions into 'high confidence' (>70%) and 'low confidence' (<30%) bins. "
        "Are both bands calibrated, or just one?"
    )

    def calibration_summary(pairs, label):
        high_conf = [(p, o) for p, o in pairs if p > 0.7]
        low_conf = [(p, o) for p, o in pairs if p < 0.3]
        mid_conf = [(p, o) for p, o in pairs if 0.3 <= p <= 0.7]

        def stats(pp):
            if not pp:
                return None, None, 0
            probs = [p for p, _ in pp]
            outcomes = [o for _, o in pp]
            return sum(probs) / len(probs), sum(outcomes) / len(outcomes), len(pp)

        high_pred, high_actual, high_n = stats(high_conf)
        mid_pred, mid_actual, mid_n = stats(mid_conf)
        low_pred, low_actual, low_n = stats(low_conf)
        return [
            {"Model": label, "Regime": "High (>70%)",
             "Mean Predicted": high_pred, "Actual Rate": high_actual, "Count": high_n},
            {"Model": label, "Regime": "Mid (30-70%)",
             "Mean Predicted": mid_pred, "Actual Rate": mid_actual, "Count": mid_n},
            {"Model": label, "Regime": "Low (<30%)",
             "Mean Predicted": low_pred, "Actual Rate": low_actual, "Count": low_n},
        ]

    rows_3 = []
    rows_3.extend(calibration_summary(raw_pairs, "Raw Ensemble"))
    rows_3.extend(calibration_summary(emos_pairs, "EMOS"))
    rows_3.extend(calibration_summary(market_pairs, "Market"))

    regime_df = pd.DataFrame(rows_3)
    regime_display_df = regime_df.dropna(subset=['Mean Predicted']).copy()
    regime_display_df['Mean Predicted'] = regime_display_df['Mean Predicted'].apply(
        lambda x: f"{x:.1%}" if x else "—")
    regime_display_df['Actual Rate'] = regime_display_df['Actual Rate'].apply(
        lambda x: f"{x:.1%}" if x is not None else "—")
    st.dataframe(regime_display_df, width='stretch', hide_index=True)
    st.caption(
        "If predicted and actual rates match in a regime, the model is calibrated there. "
        "With few days, low counts mean any single regime is noisy."
    )


    # === Panel 8: Multi-model comparison (full year) ===
    st.header("Multi-Model Comparison (full year)")
    st.markdown(
        "MAE and CRPS over the full year for GEFS, ECMWF, and combined ensembles, "
        "raw vs EMOS-calibrated. Lower is better. This is the trustworthy large-sample result."
    )

    mm_df = run_multimodel_comparison()
    if mm_df.empty:
        st.info("Not enough data for the multi-model comparison yet.")
    else:
        mae_long = mm_df.melt(id_vars=["Source"], value_vars=["Raw MAE", "EMOS MAE"],
                              var_name="Method", value_name="MAE")
        mae_chart = alt.Chart(mae_long).mark_bar().encode(
            x=alt.X("Source:N", title=None),
            xOffset="Method:N",
            y=alt.Y("MAE:Q", title="MAE (degrees F)"),
            color=alt.Color("Method:N", scale=alt.Scale(
                domain=["Raw MAE", "EMOS MAE"], range=["#ff6b6b", "#4ecdc4"])),
            tooltip=["Source:N", "Method:N", alt.Tooltip("MAE:Q", format=".2f")],
        ).properties(height=300, title="Mean Absolute Error")
        st.altair_chart(mae_chart, width='stretch')

        crps_long = mm_df.melt(id_vars=["Source"], value_vars=["Raw CRPS", "EMOS CRPS"],
                               var_name="Method", value_name="CRPS")
        crps_chart = alt.Chart(crps_long).mark_bar().encode(
            x=alt.X("Source:N", title=None),
            xOffset="Method:N",
            y=alt.Y("CRPS:Q", title="CRPS"),
            color=alt.Color("Method:N", scale=alt.Scale(
                domain=["Raw CRPS", "EMOS CRPS"], range=["#ff6b6b", "#4ecdc4"])),
            tooltip=["Source:N", "Method:N", alt.Tooltip("CRPS:Q", format=".3f")],
        ).properties(height=300, title="CRPS (probabilistic quality)")
        st.altair_chart(crps_chart, width='stretch')

        disp = mm_df.copy()
        disp["MAE improve"] = ((disp["Raw MAE"] - disp["EMOS MAE"]) / disp["Raw MAE"] * 100).map(lambda x: f"{x:+.1f}%")
        disp["CRPS improve"] = ((disp["Raw CRPS"] - disp["EMOS CRPS"]) / disp["Raw CRPS"] * 100).map(lambda x: f"{x:+.1f}%")
        for col in ["Raw MAE", "EMOS MAE", "Raw CRPS", "EMOS CRPS"]:
            disp[col] = disp[col].map(lambda x: f"{x:.3f}")
        st.dataframe(disp, width='stretch', hide_index=True)


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


@st.cache_data(ttl=30)
def _live_db_state() -> dict:
    """Pull live_trades aggregates from DB. Cached 30s."""
    out: dict = {}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM live_trades")
        out["total_attempts"] = cur.fetchone()[0]
        cur.execute("""
            SELECT COALESCE(SUM(realized_pnl_cents), 0),
                   COUNT(*) FILTER (WHERE settlement IS NOT NULL),
                   COUNT(*) FILTER (WHERE fill_status IN ('filled','partial')),
                   COALESCE(SUM(realized_pnl_cents) FILTER (WHERE target_date = CURRENT_DATE), 0)
            FROM live_trades
        """)
        out["cum_pnl_cents"], out["n_settled"], out["n_filled"], out["today_pnl_cents"] = cur.fetchone()
        cur.execute("""
            SELECT target_date,
                   SUM(realized_pnl_cents) FILTER (WHERE settlement IS NOT NULL) AS daily_pnl
            FROM live_trades
            GROUP BY target_date ORDER BY target_date
        """)
        out["pnl_by_day"] = cur.fetchall()
        cur.execute("""
            SELECT placed_at, target_date, ticker, side, count,
                   limit_price_cents, cross_price_cents, edge,
                   fill_status, fill_price_cents, settlement, realized_pnl_cents
            FROM live_trades
            WHERE target_date = CURRENT_DATE
            ORDER BY placed_at
        """)
        out["today_trades"] = cur.fetchall()
        cur.execute("""
            SELECT AVG(market_yes_ask - market_yes_bid), COUNT(*)
            FROM paper_trades
            WHERE target_date >= CURRENT_DATE - INTERVAL '28 days'
              AND entry_price_cents >= 60 AND ABS(edge) >= 0.10
              AND market_yes_bid IS NOT NULL AND market_yes_ask IS NOT NULL
              AND model_source = 'EMOS combined 00Z (rolling 45d)'
        """)
        spr, n = cur.fetchone()
        out["spread_4wk"] = (float(spr), n) if spr is not None else (None, n)
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

                    # Today's model edge for this contract (from paper-trade cron)
                    model_p = market_mid = edge = None
                    if td == today:
                        cur.execute("""
                            SELECT model_prob_yes, market_mid_prob, edge
                            FROM paper_trades
                            WHERE ticker = %s AND target_date = %s
                              AND model_source = 'EMOS combined 00Z (rolling 45d)'
                            ORDER BY logged_at DESC LIMIT 1
                        """, (ticker, td))
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


def _read_halt_reason() -> str | None:
    from pathlib import Path
    p = Path.home() / ".kalshi" / "halt"
    if p.exists():
        return p.read_text().strip()
    return None


@st.fragment(run_every="15s")
def _live_trading_panel():
    """Auto-refreshing Live Trading view. Re-runs every 15s; underlying
    Kalshi/DB calls are @st.cache_data ttl=15-30s so API rate stays low."""
    # Refresh indicator (shows EST time so user can see it's updating)
    from zoneinfo import ZoneInfo
    now_local = datetime.now(ZoneInfo("America/New_York"))
    st.caption(f"⟳ Updated {now_local.strftime('%I:%M:%S %p %Z')} (auto-refreshes every 15s)")

    halt_reason = _read_halt_reason()
    if halt_reason:
        st.error(f"🛑 **STRATEGY HALTED.** No new orders will be placed by the cron until "
                 f"this file is removed: `~/.kalshi/halt`\n\n```\n{halt_reason}\n```")
        st.markdown("To clear: investigate root cause, then `rm ~/.kalshi/halt` to re-enable trading.")

    # Pull state
    live = _live_account_state()
    db = _live_db_state()

    if not live["ok"]:
        st.warning(f"Kalshi API unavailable: {live['error']}")

    is_demo = live.get("api_base") and "demo" in live["api_base"]
    env_label = "DEMO" if is_demo else "LIVE (real money)"

    # === Top status row ===
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        bal = live.get("balance_cents")
        st.metric("Account balance", f"${bal/100:,.2f}" if bal is not None else "—", env_label)
    with m2:
        st.metric("Cumulative live P&L", f"${int(db['cum_pnl_cents'])/100:+,.2f}",
                  f"{db['n_settled']} settled trades")
    with m3:
        st.metric("Today's realized P&L", f"${int(db['today_pnl_cents'])/100:+,.2f}",
                  f"{len(db['today_trades'])} orders placed today" if db['today_trades'] else "no orders today")
    with m4:
        from weather_markets.kalshi_api import parse_position
        open_contracts = sum(abs(parse_position(p)) for p in live.get("positions", []))
        st.metric("Open contracts (Kalshi)", open_contracts, f"{len(live.get('orders', []))} resting orders")

    st.divider()

    # === Risk envelope ===
    st.subheader("Risk envelope")
    st.caption("All four bars must stay green. A breached limit halts the strategy.")
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        cum_pct = max(0, min(100, abs(int(db['cum_pnl_cents'])/100) / 300 * 100)) if db['cum_pnl_cents'] < 0 else 0
        st.metric("Cumulative drawdown", f"${int(db['cum_pnl_cents'])/100:+,.2f}", f"limit −$300", delta_color="inverse")
        st.progress(min(1.0, cum_pct/100), text=f"{cum_pct:.0f}% of kill threshold")
    with r2:
        today_loss_pct = max(0, min(100, abs(int(db['today_pnl_cents'])/100) / 50 * 100)) if db['today_pnl_cents'] < 0 else 0
        st.metric("Today's loss", f"${int(db['today_pnl_cents'])/100:+,.2f}", "limit −$50", delta_color="inverse")
        st.progress(min(1.0, today_loss_pct/100), text=f"{today_loss_pct:.0f}% of daily limit")
    with r3:
        at_cap = open_contracts >= 200
        delta = "AT CAP — new orders blocked" if at_cap else "limit 200"
        st.metric("Open contracts", open_contracts, delta,
                  delta_color="inverse" if at_cap else "normal")
        st.progress(min(1.0, open_contracts/200), text=f"{open_contracts/200*100:.0f}% of cap")
        if at_cap:
            st.caption("⚠️ Live-trade cron will skip new signals until a position closes.")
    with r4:
        spr_val, spr_n = db['spread_4wk']
        if spr_val is None:
            st.metric("4wk avg spread", "—", "limit 5¢")
            st.caption("Insufficient data")
        else:
            st.metric("4wk avg spread", f"{spr_val:.2f}¢", f"limit 5¢ (over {spr_n} trades)")
            st.progress(min(1.0, spr_val/5), text=f"{spr_val/5*100:.0f}% of regime kill")

    st.divider()

    # === Current positions with live unrealized P&L ===
    st.subheader("Current positions")
    st.caption("Each row = one contract you hold. Mark = current bid/ask mid. "
               "Unrealized P&L = (mark − avg cost) × qty. Refreshes every 15 seconds.")

    positions_for_enrich = live.get("positions", [])
    from weather_markets.kalshi_api import parse_position as _parse_pos
    if not positions_for_enrich or all(_parse_pos(p) == 0 for p in positions_for_enrich):
        st.info("No open positions right now.")
    else:
        try:
            enriched = _enrich_positions(positions_for_enrich)
        except Exception as e:
            st.warning(f"Could not enrich positions: {type(e).__name__}: {e}")
            enriched = []

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
                    "Contract": e["ticker"].replace("KXHIGHNY-", ""),
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

    # === Today's orders table ===
    st.subheader("Today's live orders")
    if db['today_trades']:
        import pandas as pd
        cols = ["placed_at", "target_date", "ticker", "side", "count",
                "limit", "cross", "edge", "status", "fill_price", "settled", "pnl"]
        rows = []
        for r in db['today_trades']:
            (placed, td, tk, side, cnt, lim, cross, edge, status, fp, settle, pnl) = r
            rows.append({
                "placed_at (ET)": _to_local_time(placed, "%I:%M:%S %p") if placed else "",
                "target_date": str(td),
                "ticker": tk.replace("KXHIGHNY-", ""),
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
                    "ticker": o.get("ticker", "").replace("KXHIGHNY-", ""),
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
                    "ticker": f.get("ticker", "").replace("KXHIGHNY-", ""),
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

    # === Strategy parameters (static reference) ===
    with st.expander("Strategy parameters in effect"):
        st.markdown("""
- **Production filter:** |edge| ≥ 10%, entry ≥ 60¢
- **Decision time:** 14:45 UTC daily
- **Model:** EMOS combined GEFS+IFS 00Z, rolling 45-day fit
- **Sizing:** Unit (75 contracts/trade), clipped if stake would exceed $50
- **Execution:** post-only limit at 1¢ inside the spread
- **Risk caps:**
    - max stake per trade: $50 (5% of $1k bankroll)
    - max open contracts: 200 (runaway-bug circuit breaker)
- **Kill criteria (immutable):**
    - cumulative drawdown < −$300 → halt
    - daily loss > −$50 → block new orders for 24h
    - 4-week avg spread > 5¢ → halt (regime kill)
    - first-30-attempts fill rate < 40% → halt
    - first-60-trade forward mean < −1¢/trade → halt
""")


with tab_live:
    st.title("Live Trading")
    _live_trading_panel()


# ---------------------------------------------------------------------
# BACKTEST TAB (forecast-vs-market diagnostic view)
# Was previously labeled "Trading View"; the actual live trading lives in
# the Live Trading tab now.
# ---------------------------------------------------------------------
with tab_backtest:
    st.title("Backtest / Forecast View")
    st.markdown(
        "Today's combined GEFS+ECMWF forecast vs current Kalshi prices. "
        "Edge = model probability minus market mid. Large positive edge means "
        "the model thinks YES is underpriced. **This is a diagnostic view — "
        "actual live trading is in the Live Trading tab.**"
    )

    # City selector drives station/series for the WHOLE tab: forecast view,
    # edge by bracket, AND the downstream P&L simulation.
    _stations = all_stations()
    _city_labels = {f"{s.city} ({s.station_id})": s.station_id for s in _stations}
    _default_city = next(iter(_city_labels))  # KNYC sorts first
    chosen_city_label = st.selectbox(
        "City",
        options=list(_city_labels.keys()),
        index=0,
        help="Switches the entire backtest tab — forecast, edge table, and P&L sim — "
             "to the selected city's contracts, station, and EMOS calibration.",
    )
    selected_station_id = _city_labels[chosen_city_label]
    selected_station = get_station(selected_station_id)
    selected_series = selected_station.kalshi_series

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
        )
        observed_high = fetch_observed_high(trade_date, conn, station_id=selected_station_id)

        # Market prices as of the paper-trade decision time for this workflow
        # (14:45 UTC for 00Z ECMWF, 18:45 UTC for 12Z combined). Locks the
        # displayed market state to when a trade would realistically be placed,
        # so historical views don't show post-resolution prices.
        decision_time = datetime(
            trade_date.year, trade_date.month, trade_date.day,
            cfg["decision_hour"], cfg["decision_minute"], tzinfo=timezone.utc,
        )
        market_probs = {}
        if contracts:
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (ticker) ticker, yes_bid, yes_ask, snapshot_at
                    FROM prices
                    WHERE ticker = ANY(%s)
                      AND snapshot_at <= %s
                    ORDER BY ticker, snapshot_at DESC
                """, (tickers, decision_time))
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
        m_prob = model_probs.get(ticker)
        mkt = market_probs.get(ticker)
        edge = (m_prob - mkt) if (m_prob is not None and mkt is not None) else None

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

    st.caption(
        f"Signal source: {model_choice}. "
        f"Flagging when |edge| ≥ {edge_threshold:.0%}. "
        "Market prices are the most recent snapshot, which may be newer than the forecast run. "
        "This is a decision aid, not advice — small sample, paper-trade first."
    )

    # P&L simulation (resolved paper trades, configurable sizing + filters) + log table
    pt_df_all = paper_trades_with_outcomes(limit=10000)
    n_total_all = len(pt_df_all)

    st.subheader("P&L simulation")

    if pt_df_all.empty:
        st.info("No paper trades logged yet. The 14:45 UTC cron will populate this once it runs.")
    elif int(pt_df_all["won"].notna().sum()) == 0:
        st.info(f"{n_total_all} paper trade(s) logged, none resolved yet. Simulation appears once observations land.")
    else:
        # --- Scope paper_trades to the city chosen at the top of the tab ----
        # Filter model_sources to those belonging to the selected city. NYC's
        # sources don't have a city tag in their name (legacy); everywhere else
        # tags the city name in the source string ("Chicago", "Miami", etc.).
        other_city_tags = [s.city for s in all_stations() if s.station_id != "KNYC"]
        all_sources = sorted(pt_df_all["model_source"].unique().tolist())
        if selected_station_id == "KNYC":
            city_sources = [s for s in all_sources if not any(t in s for t in other_city_tags)]
        else:
            city_sources = [s for s in all_sources if selected_station.city in s]

        if not city_sources:
            st.info(
                f"No paper trades for {selected_station.city} yet — "
                "backfill or daily cron hasn't populated trades for this city."
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
                    ["Unit", "Kelly", "Scaling"],
                    index=0,
                    horizontal=True,
                    help=(
                        "Unit: fixed contract count per trade (ignores bankroll). "
                        "Kelly: stake = bankroll × Kelly_optimal × chosen fraction (bets MORE on high-edge signals). "
                        "Scaling: stake = bankroll × chosen %% (fixed % of current bankroll, edge-agnostic)."
                    ),
                )
            with c3:
                execution_label = st.radio(
                    "Execution",
                    ["Cross spread", "Limit (100% fill)", "Limit (70% fill)", "Limit (50% fill)"],
                    index=0,
                    help=(
                        "Cross spread = pay the marketable price (paper-trade default). "
                        "Limit = post 1¢ inside the spread, missed fills count as $0. "
                        "Fill seed is fixed so the curve is deterministic."
                    ),
                )
                execution_mode = {
                    "Cross spread": "cross",
                    "Limit (100% fill)": "limit_100",
                    "Limit (70% fill)": "limit_70",
                    "Limit (50% fill)": "limit_50",
                }[execution_label]
            with c4:
                # Defaults — only the active mode's value is used by the sim
                contracts_per_trade = 1
                kelly_fraction = 0.5
                scaling_pct = 0.05

                if sizing_type == "Unit":
                    contracts_per_trade = st.number_input(
                        "Contracts per trade", min_value=1, value=1, step=1,
                        help="Same fixed count on every trade. Ignores bankroll.",
                    )
                    strategy_label = f"Unit ({contracts_per_trade} contract{'s' if contracts_per_trade != 1 else ''})"
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

            sim_mode = {"Unit": "unit", "Kelly": "kelly", "Scaling": "scaling"}[sizing_type]
            sim_df = simulate_pnl(
                pt_df, starting_balance, sim_mode,
                contracts=int(contracts_per_trade),
                kelly_fraction=kelly_fraction,
                scaling_pct=scaling_pct,
                execution_mode=execution_mode,
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

            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("Final balance", f"${final_balance:.2f}", f"{return_pct:+.1f}%")
            with m2:
                st.metric("Resolved trades", f"{n_won}/{n_resolved}", f"{n_won/n_resolved*100:.0f}% win rate")
            with m3:
                st.metric("Sharpe (annualized)", f"{sharpe:.2f}" if sharpe == sharpe else "—",
                          help="Per-trade P&L annualized by sqrt(trades/year). Uses filled trades only. "
                               "No risk-free subtraction. Higher = better risk-adjusted return.")
            with m4:
                st.metric("Pending", n_total - n_resolved)
            with m5:
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
            st.caption(
                f"Strategy: {strategy_label}. Execution: {execution_label}. "
                f"Filter: |edge| ≥ {edge_filter:.0%}, entry ≥ {min_entry_price}¢, source = {source_filter}. "
                f"P&L is net of Kalshi trading fees "
                f"(per-contract: $0.07 × P × (1-P), rounded up to nearest cent). "
                f"Limit mode posts 1¢ inside the spread; missed fills (seed=42) are $0."
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