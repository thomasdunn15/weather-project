"""Weather forecasting dashboard.

Run with: uv run streamlit run scripts/dashboard.py
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
    compute_ensemble_probabilities,
    fetch_observed_high,
    fetch_contracts_for_date,
)
from weather_markets.emos import fit_emos, gaussian_to_bracket_probs
from weather_markets.evaluation import (
    evaluate_predictions, 
    contract_resolved_yes, 
    brier_score,
)

from weather_markets.evaluation import calibration_bins

# === Page config ===
st.set_page_config(
    page_title="NYC Weather Forecasting Dashboard",
    page_icon="🌡️",
    layout="wide",
)

st.title("NYC Weather Forecasting Dashboard")
st.markdown("Backtesting raw ensemble vs EMOS vs Kalshi market predictions for daily NYC high temperatures.")


# === Data layer (cached) ===

@st.cache_data
def collect_training_data():
    """Collect ensemble stats, observations, dates from database."""
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
def run_full_backtest():
    """For each day, compute raw / EMOS / market Brier."""
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
                params = fit_emos(train_means, train_stds, train_obs)
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


# === Sidebar (filters / info) ===

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


# === Main content ===

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

# Reshape for grouped bar chart
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
).properties(
    height=400,
)

st.write(f"Date column type: {chart_df['date'].dtype}")
st.write(chart_df.head())

st.altair_chart(chart, use_container_width=True)


# === Panel 3: Per-day data table ===

st.header("Per-Day Details")

display_df = df.copy()
display_df['raw_brier'] = display_df['raw_brier'].round(4)
display_df['emos_brier'] = display_df['emos_brier'].round(4)
display_df['market_brier'] = display_df['market_brier'].round(4)

st.dataframe(display_df, use_container_width=True)

# Panel 4: Rolling Mean Brier
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

# === Panel 4: Per-day drill-down ===

st.header("Per-Day Drill-Down")

# Date picker
available_dates = df['date'].tolist()
selected_date = st.selectbox(
    "Select a date to investigate",
    options=available_dates,
    format_func=lambda d: d.strftime("%a %b %d, %Y"),
    index=len(available_dates) - 1,  # default to latest
)

# Load the data for this specific date
with get_connection() as conn:
    init_time = datetime(
        selected_date.year, selected_date.month, selected_date.day,
        12, 0, tzinfo=timezone.utc,
    )
    
    highs = compute_daily_highs(init_time, selected_date, conn)
    contracts = fetch_contracts_for_date(selected_date, conn)
    observed = fetch_observed_high(selected_date, conn)
    
    # Compute all three probability sets
    raw_probs = compute_ensemble_probabilities(highs, contracts) if contracts else {}
    
    # EMOS LOO for this day
    means, stds, obs, dates = collect_training_data()
    idx = dates.index(selected_date)
    train_means = means[:idx] + means[idx+1:]
    train_stds = stds[:idx] + stds[idx+1:]
    train_obs = obs[:idx] + obs[idx+1:]
    
    emos_probs = {}
    if len(train_means) >= 2 and contracts:
        params = fit_emos(train_means, train_stds, train_obs)
        emos_mu = params['a'] + params['b'] * means[idx]
        emos_var = params['c'] + params['d'] * stds[idx]**2
        if emos_var > 0:
            emos_sigma = math.sqrt(emos_var)
            emos_probs = gaussian_to_bracket_probs(emos_mu, emos_sigma, contracts)
    
    # Market prices closest to init_time
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


# Show summary metrics for this day
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Observed", f"{observed}°F" if observed else "—")

with col2:
    ensemble_mean = statistics.mean(highs.values())
    st.metric("Raw mean", f"{ensemble_mean:.1f}°F")

with col3:
    if emos_probs:  # we have EMOS for this day
        st.metric("EMOS mean", f"{emos_mu:.1f}°F")
    else:
        st.metric("EMOS mean", "—")

with col4:
    raw_err = ensemble_mean - observed if observed else None
    st.metric("Raw error", f"{raw_err:+.1f}°F" if raw_err is not None else "—")


# Ensemble histogram with observed value
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

# Add vertical line for observed value
if observed is not None:
    obs_line = alt.Chart(pd.DataFrame({'observed': [observed]})).mark_rule(
        color='#ff6b6b',
        strokeWidth=3,
    ).encode(x='observed:Q')
    
    chart_combined = hist_chart + obs_line
else:
    chart_combined = hist_chart

st.altair_chart(chart_combined, use_container_width=True)

# Probability comparison table
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
            "Resolved": "✓" if outcome else "✗" if outcome is not None else "—",
        })
    
    table_df = pd.DataFrame(table_rows)
    st.dataframe(table_df, use_container_width=True, hide_index=True)

# === Panel 5: Calibration plot ===

st.header("🎯 Calibration")

st.markdown(
    "Are predicted probabilities reliable? "
    "If a model says 70% and the event happens 70% of the time, it's calibrated. "
    "Points on the diagonal = perfect calibration. "
    "Points below = overconfident. Points above = underconfident."
)

@st.cache_data
def collect_calibration_pairs():
    """
    For each day in backtest range, collect (probability, outcome) pairs
    for each contract under each model (raw, EMOS, market).
    """
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
                params = fit_emos(train_means, train_stds, train_obs)
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
                        # Find matching contract
                        c = next(c for c in contracts if c["ticker"] == ticker)
                        outcome = contract_resolved_yes(observation, c)
                        market_pairs.append((mid_prob, outcome))
    
    return raw_pairs, emos_pairs, market_pairs

raw_pairs, emos_pairs, market_pairs = collect_calibration_pairs()

n_bins = st.slider("Number of bins", min_value=3, max_value=10, value=5)

raw_bins = calibration_bins(raw_pairs, n_bins=n_bins)
emos_bins = calibration_bins(emos_pairs, n_bins=n_bins)
market_bins = calibration_bins(market_pairs, n_bins=n_bins)


# Build a DataFrame for plotting
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


# Diagonal reference line
diagonal_df = pd.DataFrame({
    "mean_predicted": [0, 1],
    "fraction_true": [0, 1],
})

diagonal_chart = alt.Chart(diagonal_df).mark_line(
    color='gray',
    strokeDash=[5, 5],
).encode(
    x='mean_predicted:Q',
    y='fraction_true:Q',
)

# Calibration points (size = count)
points_chart = alt.Chart(calib_df).mark_circle().encode(
    x=alt.X('mean_predicted:Q', 
            scale=alt.Scale(domain=[0, 1]),
            title='Mean Predicted Probability'),
    y=alt.Y('fraction_true:Q',
            scale=alt.Scale(domain=[0, 1]),
            title='Observed Fraction True'),
    size=alt.Size('count:Q', title='Sample size', scale=alt.Scale(range=[50, 500])),
    color=alt.Color(
        'Model:N',
        scale=alt.Scale(
            domain=['Raw Ensemble', 'EMOS', 'Market'],
            range=['#ff6b6b', '#4ecdc4', '#ffe66d'],
        ),
    ),
    tooltip=['Model:N', 'mean_predicted:Q', 'fraction_true:Q', 'count:Q'],
)

# Connect points within each model with lines
lines_chart = alt.Chart(calib_df).mark_line(opacity=0.3).encode(
    x='mean_predicted:Q',
    y='fraction_true:Q',
    color=alt.Color('Model:N',
        scale=alt.Scale(
            domain=['Raw Ensemble', 'EMOS', 'Market'],
            range=['#ff6b6b', '#4ecdc4', '#ffe66d'],
        ),
    ),
)

calib_chart = (diagonal_chart + lines_chart + points_chart).properties(
    height=500,
    width=600,
)

st.altair_chart(calib_chart, use_container_width=True)

# Show the per-bin data tables
with st.expander("Per-bin data"):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Raw Ensemble**")
        st.dataframe(bins_to_df(raw_bins, "Raw").drop(columns=["Model"]))
    with col2:
        st.markdown("**EMOS**")
        st.dataframe(bins_to_df(emos_bins, "EMOS").drop(columns=["Model"]))
    with col3:
        st.markdown("**Market**")
        st.dataframe(bins_to_df(market_bins, "Market").drop(columns=["Model"]))

# === Panel 6: Diagnostic plots ===

st.header("🔬 Diagnostics")
st.markdown(
    "Three views into model behavior. These help reveal where EMOS works "
    "and where it falls short."
)

# Build the diagnostic dataframe
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
            "raw_error": raw_error,         # positive = warm bias
            "raw_abs_error": raw_abs_error,
        })
    
    return pd.DataFrame(rows)

diag_df = build_diagnostic_df()

st.subheader("1. Is bias systematic in predicted temperature?")

st.markdown(
    "If the model has a constant bias (e.g., always 1.6°F too warm), "
    "this scatter should show a horizontal trend. "
    "If the bias depends on temperature, you'll see a slope."
)

# Scatter: x = predicted, y = error
scatter_1 = alt.Chart(diag_df).mark_circle(size=100).encode(
    x=alt.X('raw_predicted:Q', 
            title='Raw Predicted Mean (°F)',
            scale=alt.Scale(zero=False)),
    y=alt.Y('raw_error:Q', 
            title='Error (predicted - observed, °F)'),
    tooltip=['date:T', 'raw_predicted:Q', 'observed:Q', 'raw_error:Q'],
)

# Zero reference line
zero_line_1 = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
    color='gray', strokeDash=[5, 5]
).encode(y='y:Q')

# Linear regression line (Altair can do this automatically)
regression_1 = alt.Chart(diag_df).transform_regression(
    'raw_predicted', 'raw_error', method='linear'
).mark_line(color='red').encode(
    x='raw_predicted:Q',
    y='raw_error:Q',
)

chart_1 = (scatter_1 + zero_line_1 + regression_1).properties(height=350)
st.altair_chart(chart_1, use_container_width=True)

st.caption(
    "Gray dashed line = no bias. Red line = best linear fit through points. "
    "If the red line slopes downward, bias decreases as predicted temperature rises "
    "(i.e., the model is warmer-biased for cool predictions)."
)

st.subheader("2. Does ensemble spread predict actual uncertainty?")

st.markdown(
    "Theoretically, days where ensemble members disagree more should have "
    "bigger forecast errors. If spread is informative, you'll see a positive slope."
)

scatter_2 = alt.Chart(diag_df).mark_circle(size=100).encode(
    x=alt.X('raw_std:Q', 
            title='Ensemble Standard Deviation (°F)',
            scale=alt.Scale(zero=False)),
    y=alt.Y('raw_abs_error:Q', 
            title='Absolute Error (°F)',
            scale=alt.Scale(zero=False)),
    tooltip=['date:T', 'raw_std:Q', 'raw_abs_error:Q', 'observed:Q'],
)

regression_2 = alt.Chart(diag_df).transform_regression(
    'raw_std', 'raw_abs_error', method='linear'
).mark_line(color='red').encode(
    x='raw_std:Q',
    y='raw_abs_error:Q',
)

chart_2 = (scatter_2 + regression_2).properties(height=350)
st.altair_chart(chart_2, use_container_width=True)

st.caption(
    "If ensemble spread is informative, points should slope upward "
    "(more spread → bigger errors). Flat or negative slope = under-dispersion."
)

st.subheader("3. Is the model calibrated differently for confident vs uncertain predictions?")

st.markdown(
    "Split predictions into 'high confidence' (>70%) and 'low confidence' (<30%) bins. "
    "Are both bands calibrated, or just one?"
)

raw_pairs, emos_pairs, market_pairs = collect_calibration_pairs()


def calibration_summary(pairs, label):
    """Return high-confidence and low-confidence calibration stats."""
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

# Filter out empty rows for display
regime_display_df = regime_df.dropna(subset=['Mean Predicted']).copy()
regime_display_df['Mean Predicted'] = regime_display_df['Mean Predicted'].apply(lambda x: f"{x:.1%}" if x else "—")
regime_display_df['Actual Rate'] = regime_display_df['Actual Rate'].apply(lambda x: f"{x:.1%}" if x is not None else "—")

st.dataframe(regime_display_df, use_container_width=True, hide_index=True)

st.caption(
    "If predicted and actual rates match in a regime, the model is calibrated in that regime. "
    "Big differences signal miscalibration. With 13 days, low counts mean any single regime "
    "is noisy."
)