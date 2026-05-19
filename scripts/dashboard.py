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

st.header("🔍 Per-Day Drill-Down")

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