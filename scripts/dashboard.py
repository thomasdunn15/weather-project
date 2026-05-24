"""Weather forecasting dashboard.

Run with: uv run streamlit run scripts/dashboard.py

Two tabs:
  - Analysis: backtests, calibration, diagnostics (the existing panels)
  - Trading:  today's combined+EMOS forecast vs Kalshi prices, with edge highlighting
"""
import math
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
def collect_combined_training_data():
    """Collect COMBINED (GEFS+ECMWF) ensemble stats over the full year for EMOS fitting."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM observations WHERE station_id = %s", ("KNYC",))
            end = cur.fetchone()[0]
        return collect_training_pairs(
            conn, date(2025, 5, 1), end,
            station_id="KNYC", models=["gefs", "ifs"],
        )


@st.cache_data
def fit_combined_emos():
    """Fit EMOS once on the full-year combined ensemble. Returns params dict."""
    means, stds, obs, dates = collect_combined_training_data()
    if len(means) < 10:
        return None
    return fit_emos(means, stds, obs)


@st.cache_data(ttl=3600)
def fit_combined_emos_rolling(trade_date, window_days=45):
    """Fit rolling-window EMOS for a specific target date. Returns None when
    fewer than min_train_days (default 30) effective training days are available."""
    with get_connection() as conn:
        return fit_emos_rolling(
            trade_date, conn,
            window_days=window_days, station_id="KNYC", model="combined",
        )


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


def latest_available_init(conn, target_date, model_aware=True):
    """
    Return the target date's 12 UTC init_time IF forecast data exists for it,
    else None. Matches the backtest methodology (always the 12 UTC same-day run);
    never uses a later run, which would be lookahead bias.
    """
    preferred = datetime(
        target_date.year, target_date.month, target_date.day,
        12, 0, tzinfo=timezone.utc,
    )
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM forecasts
            WHERE station_id = %s
              AND init_time = %s
            LIMIT 1
        """, ("KNYC", preferred))
        row = cur.fetchone()
    return preferred if row else None


# =====================================================================
# TABS
# =====================================================================

tab_analysis, tab_trade = st.tabs(["Analysis", "Trading"])


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
# TRADING TAB (operational view)
# ---------------------------------------------------------------------
with tab_trade:
    st.title("Trading View")
    st.markdown(
        "Today's combined GEFS+ECMWF forecast vs current Kalshi prices. "
        "Edge = model probability minus market mid. Large positive edge means "
        "the model thinks YES is underpriced."
    )

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
            options=["Raw combined", "EMOS combined", "EMOS combined (rolling 45d)"],
            index=0,
            help="Which model drives the edge and signal columns.",
        )
    with ctrl3:
        edge_threshold = st.slider(
            "Signal threshold (edge)",
            min_value=0.02, max_value=0.30, value=0.10, step=0.01,
            help="Flag BUY YES / BUY NO when |edge| exceeds this.",
        )

    if model_choice == "EMOS combined (rolling 45d)":
        emos_params = fit_combined_emos_rolling(trade_date)
        if emos_params is None:
            st.warning(
                "Rolling EMOS unavailable — fewer than 30 days of training data "
                "for this target date. Falling back to full-sample EMOS."
            )
            emos_params = fit_combined_emos()
    else:
        emos_params = fit_combined_emos()

    if emos_params is None:
        st.warning("Not enough combined training data to fit EMOS. Showing raw only.")

    with get_connection() as conn:
        # Resolve which forecast run to use, with fallback for early-morning gaps.
        chosen_init = latest_available_init(conn, trade_date)

        if chosen_init is None:
            st.info(
                f"No forecast is available yet for {trade_date}. "
                "The GEFS run lands ~12 UTC and ECMWF ~14:45 UTC. Check back later."
            )
            st.stop()

        preferred_init = datetime(
            trade_date.year, trade_date.month, trade_date.day,
            12, 0, tzinfo=timezone.utc,
        )
        is_stale = chosen_init != preferred_init

        # Combined ensemble for the chosen run
        try:
            combined_values = compute_combined_daily_highs(chosen_init, trade_date, conn)
        except Exception as e:
            st.error(f"Could not load combined forecast: {e}")
            st.stop()

        # compute_combined_daily_highs silently skips models with no data,
        # so query directly to know which models actually contributed.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT model
                FROM forecasts
                WHERE init_time = %s AND station_id = %s AND model IN ('gefs', 'ifs')
                GROUP BY model
                """,
                (chosen_init, "KNYC"),
            )
            models_present = {row[0] for row in cur.fetchall()}

        contracts = fetch_contracts_for_date(trade_date, conn)

        # Latest market prices for these contracts (most recent snapshot overall)
        market_probs = {}
        if contracts:
            tickers = [c["ticker"] for c in contracts]
            with conn.cursor() as cur:
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
            f"No 12 UTC run for {trade_date} yet. "
            f"Using most recent available run: {chosen_init.isoformat()}."
        )

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
        st.metric("Combined mean", f"{cmean:.1f}°F")
    with f3:
        st.metric("Combined spread", f"{cstd:.2f}°F")
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

        rows.append({
            "Contract": ticker.replace("KXHIGHNY-", ""),
            "Range": range_label(c),
            "Raw P": f"{raw_probs.get(ticker, 0):.1%}",
            "EMOS P": f"{emos_probs.get(ticker, 0):.1%}" if emos_probs else "—",
            "Market P": f"{mkt:.1%}" if mkt is not None else "—",
            "Edge": f"{edge:+.1%}" if edge is not None else "—",
            "Signal": signal,
        })

    edge_df = pd.DataFrame(rows)

    def highlight_signal(val):
        if val == "BUY YES":
            return "background-color: #1b4d2e; color: #b6f5c8"
        if val == "BUY NO":
            return "background-color: #5c1a1a; color: #f5b6b6"
        return ""

    styled = edge_df.style.map(highlight_signal, subset=["Signal"])
    st.dataframe(styled, width='stretch', hide_index=True)

    st.caption(
        f"Signal source: {model_choice}. "
        f"Flagging when |edge| ≥ {edge_threshold:.0%}. "
        "Market prices are the most recent snapshot, which may be newer than the forecast run. "
        "This is a decision aid, not advice — small sample, paper-trade first."
    )