"""
Leading Indicators Dashboard - ENHANCED VERSION
Fixes: US Treasury Yield signal
Improvements: Modern UI, better layout, visual indicators
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_fetch import (
    batch_download,
    fetch_fred_series,
    prepare_timeseries_for_chart
)
from utils import (
    setup_page,
    get_live_price_safe,
    render_key_observations,
    get_ui_detail_mode,
    get_ui_device_mode,
    render_source_freshness,
    render_decision_header,
    responsive_cols as _responsive_cols,
)
import analytics
from config import FRED_API_KEY, MARKET_SYMBOLS as CONFIG_MARKET_SYMBOLS, LEADING_SYMBOLS as CONFIG_LEADING_SYMBOLS

setup_page("Leading Indicators")
view_mode = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"


# _responsive_cols imported from utils

# ==================== CUSTOM CSS ====================
st.markdown("""
<style>
    /* Main title styling */
    .main-title {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }

    /* Signal cards */
    .signal-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }

    .signal-card-positive {
        background: linear-gradient(135deg, #56ab2f 0%, #a8e063 100%);
    }

    .signal-card-negative {
        background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
    }

    .signal-card-neutral {
        background: linear-gradient(135deg, #f2994a 0%, #f2c94c 100%);
    }

    /* Metric cards */
    .metric-card {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #1f77b4;
        margin: 0.5rem 0;
    }

    /* Section headers */
    .section-header {
        color: #2c3e50;
        font-size: 1.5rem;
        font-weight: 600;
        margin-top: 2rem;
        margin-bottom: 1rem;
        border-bottom: 2px solid #3498db;
        padding-bottom: 0.5rem;
    }

    /* Info boxes */
    .info-box {
        background-color: #e3f2fd;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #2196f3;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ==================== TITLE ====================
st.markdown('<h1 class="main-title">📊 Leading Indicators Dashboard</h1>', unsafe_allow_html=True)
st.markdown("**Early signals of market direction** • Liquidity • Yields • Currency • Risk Assets")
if view_mode == "Detail":
    st.caption(f"Device mode: **{device_mode}**")
render_decision_header(source="macro_ssot")
st.markdown("---")

# ==================== SIGNAL EXPLANATIONS ====================
SIGNAL_EXPLANATIONS = {
    "Copper/Gold Positive": "🟢 Copper outperforming Gold → Growth expectations rising, risk appetite improving",
    "Copper/Gold Defensive": "🔴 Gold outperforming Copper → Markets turning defensive, growth concerns rising",
    "Credit Risk On": "🟢 High yield bonds outperforming → Investors comfortable taking risk",
    "Credit Risk Off": "🔴 Investment grade outperforming → Credit stress rising, risk appetite falling",
    "Yield Curve Positive": "🟢 Normal yield curve → Growth supportive environment",
    "Yield Curve Inverted": "🔴 Inverted curve → Historically precedes recessions",
    "Dollar Rising": "🔴 Stronger dollar tightens global liquidity and pressures risk assets",
    "Dollar Stable": "🟢 Stable/weakening dollar supports equities and commodities",
    "Yields Rising": "🔴 Rising yields tighten financial conditions",
    "Yields Stable": "🟢 Stable/falling yields support risk assets",
    "Equities Strong": "🟢 Markets trading above trend → Positive momentum",
    "Equities Weak": "🔴 Markets below trend → Weak momentum"
}

INVALID_SIGNAL_STATES = {"No Data", "Insufficient Data", "Error", "No Close Data"}


def is_valid_signal(signal_text: str) -> bool:
    return bool(signal_text) and signal_text not in INVALID_SIGNAL_STATES

# Market symbols are mostly consistent with config.py
MARKET_SYMBOLS = CONFIG_MARKET_SYMBOLS
LEADING_SYMBOLS = CONFIG_LEADING_SYMBOLS

# Constants for impulse gauges
DAILY_NOISE_THRESHOLD = analytics.DAILY_NOISE_THRESHOLD
ENV_THRESHOLD = analytics.ENV_THRESHOLD

# ==================== FETCH DATA ====================
ALL_SYMBOLS = list(set(MARKET_SYMBOLS.keys()) | set(LEADING_SYMBOLS.keys()))

with st.spinner("📡 Fetching market data..."):
    all_data = batch_download(ALL_SYMBOLS, period="1y")

market_data = {k: all_data.get(k) for k in MARKET_SYMBOLS}
data = {k: all_data.get(k) for k in LEADING_SYMBOLS}

# Check critical symbols
missing_symbols = []
for symbol in ["HYG", "LQD", "^TNX", "^IRX"]:
    if symbol not in all_data or all_data[symbol] is None or len(all_data.get(symbol, [])) == 0:
        missing_symbols.append(symbol)

if missing_symbols:
    st.error(f"⚠️ Missing data: {', '.join(missing_symbols)}")

# Fetch liquidity data
liquidity_data = {}
if FRED_API_KEY:
    from config import FRED_SERIES
    with st.spinner("💰 Fetching liquidity data..."):
        for name, series in FRED_SERIES.items():
            if name in ["Fed Balance Sheet", "Reverse Repo", "Treasury General Account"]:
                liquidity_data[name] = fetch_fred_series(series, FRED_API_KEY, days=90)

# Global nifty reference for safety
nifty = market_data.get("^NSEI")


# ==================== HELPER FUNCTIONS ====================

# Logic moved to analytics.py


# ==================== DASHBOARD LAYOUT ====================

# Top Summary Cards
st.markdown('<div class="section-header">🎯 Quick Market Signals</div>', unsafe_allow_html=True)

# Calculate all signals using centralized analytics
ratio_cg, cg_score, cg_signal = analytics.calculate_copper_gold_signal(data)
ratio_credit, credit_score, credit_signal = analytics.calculate_credit_spread_signal(data)
dxy_value, dxy_score, dxy_signal = analytics.calculate_dollar_trend_signal(market_data)
yield_value, yield_score, yield_signal = analytics.calculate_yield_trend_signal(market_data)

def get_last_valid_close(df):
    if df is None or "Close" not in df.columns: return None
    v = df["Close"].dropna()
    return v.iloc[-1] if not v.empty else None

yield_10y = get_last_valid_close(market_data.get("^TNX"))
yield_3m = get_last_valid_close(market_data.get("^IRX"))
curve_signal = None
curve = None

if yield_10y is not None and yield_3m is not None:
    curve = yield_10y - yield_3m
    curve_signal = "Yield Curve Positive" if curve > 0 else "Yield Curve Inverted"
    
    # Calculate Z-score based directional signal for parity
    try:
        y10_series = market_data.get("^TNX")["Close"]
        y3m_series = market_data.get("^IRX")["Close"]
        curve_series = (y10_series - y3m_series).dropna()
        curve_directional = analytics.calculate_z_score_signal(curve_series)
    except Exception:
        curve_directional = 1 if curve > 0 else -1

# Display signal cards
col1, col2, col3, col4, col5 = _responsive_cols(5)

with col1:
    if curve_signal and yield_10y is not None and yield_3m is not None and curve is not None:
        card_class = "signal-card-positive" if "Positive" in curve_signal else "signal-card-negative"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>📈 Yield Curve</h3>
            <h2>{yield_10y:.2f}% - {yield_3m:.2f}% = {curve:.2f}%</h2>
            <p>{SIGNAL_EXPLANATIONS.get(curve_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

with col2:
    if yield_signal not in INVALID_SIGNAL_STATES and yield_value:
        card_class = "signal-card-negative" if yield_score == -1 else "signal-card-positive"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>📊 Yield Trend</h3>
            <h2>{yield_value:.2f}%</h2>
            <p>{SIGNAL_EXPLANATIONS.get(yield_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

with col3:
    if is_valid_signal(credit_signal) and ratio_credit:
        card_class = "signal-card-positive" if credit_score == 1 else "signal-card-negative"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>💰 Credit Spread</h3>
            <h2>{ratio_credit:.3f}</h2>
            <p>{SIGNAL_EXPLANATIONS.get(credit_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

with col4:
    if is_valid_signal(dxy_signal) and dxy_value:
        card_class = "signal-card-negative" if dxy_score == -1 else "signal-card-positive"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>💵 Dollar Trend</h3>
            <h2>{dxy_value:.2f}</h2>
            <p>{SIGNAL_EXPLANATIONS.get(dxy_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

with col5:
    if ratio_cg and is_valid_signal(cg_signal):
        card_class = "signal-card-positive" if cg_score == 1 else "signal-card-negative"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>🛢 Copper / Gold</h3>
            <h2>{ratio_cg:.4f}</h2>
            <p>{SIGNAL_EXPLANATIONS.get(cg_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

st.markdown("---")

# ==================== MARKET IMPULSE GAUGE ====================
st.markdown('<div class="section-header">🎯 Market Impulse Gauges</div>', unsafe_allow_html=True)


def add_factor_score(store: dict, name: str, daily=None, directional=None):
    if name not in store:
        store[name] = {"daily": None, "directional": None}
    if daily is not None:
        store[name]["daily"] = daily
    if directional is not None:
        store[name]["directional"] = directional


factor_scores = {}

# Yield Curve
if yield_10y is not None and yield_3m is not None:
    # Use directional calculated via Z-score in lines 199-205 if available
    # Otherwise fallback to binary sign.
    y10_df = market_data.get("^TNX")
    y3m_df = market_data.get("^IRX")
    if y10_df is not None and y3m_df is not None:
        spread_df = pd.concat(
            [y10_df["Close"].rename("y10"), y3m_df["Close"].rename("y3m")],
            axis=1
        ).ffill().dropna()
        curve_daily = analytics.daily_change_score(spread_df["y10"] - spread_df["y3m"])
    else:
        curve_daily = None
    add_factor_score(factor_scores, "Yield Curve", daily=curve_daily, directional=curve_directional)

# Dollar
if is_valid_signal(dxy_signal):
    dxy_df = market_data.get("DX-Y.NYB")
    dxy_daily = None
    if dxy_df is not None and "Close" in dxy_df.columns:
        dxy_daily = analytics.daily_change_score(dxy_df["Close"], inverse=True)
    add_factor_score(factor_scores, "Dollar", daily=dxy_daily, directional=dxy_score)

# Equities
nifty = market_data.get("^NSEI")
if nifty is not None and "Close" in nifty.columns:
    close_series = nifty["Close"].dropna()
    equity_daily = analytics.daily_change_score(close_series)
    if len(close_series) > 20:
        ma20 = close_series.rolling(20).mean().iloc[-1]
        equity_directional = 1 if close_series.iloc[-1] > ma20 else -1
    else:
        equity_directional = None
    add_factor_score(factor_scores, "Equities", daily=equity_daily, directional=equity_directional)

# Liquidity
if liquidity_data:
    # Daily: immediate liquidity pulse.
    liquidity_daily_raw = analytics.calculate_liquidity_score(liquidity_data, lookback_days=1)
    # Directional: slower liquidity backdrop (multi-print context).
    liquidity_directional_raw = analytics.calculate_liquidity_score(liquidity_data, lookback_days=4)

    # Preserve Weighting: Instead of collapsing to 1/-1, normalize by max possible score (4)
    # This keeps the factor in [-1, 1] range while reflecting intensity.
    liquidity_daily = liquidity_daily_raw / 4.0
    liquidity_directional = liquidity_directional_raw / 4.0
    
    # Only include if at least one underlying liquidity series is present.
    # Note: We filter out '0' scores for Daily Liquidity specifically because WALCL 
    # only updates weekly, and a 0 would artificially drag the DAILY gauge to neutral.
    has_liq_series = any(
        (df is not None and "value" in df.columns and len(df["value"].dropna()) >= 2)
        for df in liquidity_data.values()
    )
    if has_liq_series:
        add_factor_score(
            factor_scores,
            "Liquidity",
            daily=liquidity_daily if liquidity_daily != 0 else None,
            directional=liquidity_directional,
        )

# Copper/Gold
if is_valid_signal(cg_signal):
    cg_ratio_series = analytics.ratio_series(data.get("HG=F"), data.get("GC=F"))
    cg_daily = analytics.daily_change_score(cg_ratio_series) if cg_ratio_series is not None else None
    add_factor_score(factor_scores, "Copper/Gold", daily=cg_daily, directional=cg_score)

# Credit
if is_valid_signal(credit_signal):
    credit_ratio_series = analytics.ratio_series(data.get("HYG"), data.get("LQD"))
    credit_daily = analytics.daily_change_score(credit_ratio_series) if credit_ratio_series is not None else None
    add_factor_score(factor_scores, "Credit", daily=credit_daily, directional=credit_score)

# Yields (10Y direction: up is bearish)
if is_valid_signal(yield_signal):
    y10_df = market_data.get("^TNX")
    yield_daily = None
    if y10_df is not None and "Close" in y10_df.columns:
        yield_daily = analytics.daily_change_score(y10_df["Close"], inverse=True)
    add_factor_score(factor_scores, "Yields", daily=yield_daily, directional=yield_score)

daily_values = [v["daily"] for v in factor_scores.values() if v["daily"] is not None]
directional_values = [v["directional"] for v in factor_scores.values() if v["directional"] is not None]

# Refined Gating: Use available factors rather than forcing a 3-factor minimum which hides signals
daily_normalized = sum(daily_values) / len(daily_values) if len(daily_values) > 0 else 0
directional_normalized = sum(directional_values) / len(directional_values) if len(directional_values) > 0 else 0

g1, g2 = _responsive_cols(2)

with g1:
    fig_daily = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=daily_normalized,
        title={'text': "Daily Change Impulse", 'font': {'size': 22}},
        delta={'reference': 0},
        gauge={
            'axis': {'range': [-1, 1], 'tickwidth': 1, 'tickcolor': "darkgray"},
            'bar': {'color': "#1565c0"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [-1, -0.3], 'color': '#ffcdd2'},
                {'range': [-0.3, 0.3], 'color': '#fff9c4'},
                {'range': [0.3, 1], 'color': '#c8e6c9'}
            ],
            'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 0}
        }
    ))
    fig_daily.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig_daily, use_container_width=True)
    st.caption(f"Using {len(daily_values)} factors")

with g2:
    fig_directional = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=directional_normalized,
        title={'text': "Directional Trend Impulse", 'font': {'size': 22}},
        delta={'reference': 0},
        gauge={
            'axis': {'range': [-1, 1], 'tickwidth': 1, 'tickcolor': "darkgray"},
            'bar': {'color': "#2e7d32"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [-1, -0.3], 'color': '#ffcdd2'},
                {'range': [-0.3, 0.3], 'color': '#fff9c4'},
                {'range': [0.3, 1], 'color': '#c8e6c9'}
            ],
            'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 0}
        }
    ))
    fig_directional.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig_directional, use_container_width=True)
    st.caption(f"Using {len(directional_values)} factors")

summary_c1, summary_c2 = _responsive_cols(2)
with summary_c1:
    st.metric("Daily Impulse", f"{daily_normalized:+.2f}")
with summary_c2:
    st.metric("Directional Impulse", f"{directional_normalized:+.2f}")

observations = []
if curve_signal:
    observations.append(f"Yield curve signal: {curve_signal.replace('Yield Curve ', '')}.")
if is_valid_signal(dxy_signal):
    observations.append(f"Dollar regime signal: {dxy_signal}.")
if is_valid_signal(credit_signal):
    observations.append(f"Credit signal: {credit_signal}.")
if is_valid_signal(cg_signal):
    observations.append(f"Copper/Gold signal: {cg_signal}.")
observations.append(f"Daily impulse {daily_normalized:+.2f}, directional impulse {directional_normalized:+.2f}.")
render_key_observations(observations)

with st.expander("🧠 Factor Breakdown (Expand)", expanded=False):
    for name, values in factor_scores.items():
        daily_sent = analytics.score_to_sentiment(values["daily"])
        directional_sent = analytics.score_to_sentiment(values["directional"])

        daily_color = "#2e7d32" if daily_sent == "Bullish" else ("#c62828" if daily_sent == "Bearish" else "#f9a825")
        directional_color = "#2e7d32" if directional_sent == "Bullish" else ("#c62828" if directional_sent == "Bearish" else "#f9a825")

        st.markdown(
            f"• {name} | Daily: <span style='color:{daily_color};font-weight:600'>{daily_sent}</span> | "
            f"Directional: <span style='color:{directional_color};font-weight:600'>{directional_sent}</span>",
            unsafe_allow_html=True
        )
    st.caption("Daily reacts to latest move. Directional reflects broader trend context.")

def _env_label(v: float) -> str:
    if v > ENV_THRESHOLD:
        return "Risk ON"
    if v < -ENV_THRESHOLD:
        return "Risk OFF"
    return "Neutral"


daily_env = _env_label(daily_normalized)
directional_env = _env_label(directional_normalized)
if view_mode == "Summary":
    st.info(f"Environment: Daily {daily_env} | Directional {directional_env}")
else:
    if daily_env == "Risk ON":
        st.success("Daily Environment: Risk ON")
    elif daily_env == "Risk OFF":
        st.error("Daily Environment: Risk OFF")
    else:
        st.warning("Daily Environment: Neutral")

    if directional_env == "Risk ON":
        st.success("Directional Environment: Risk ON")
    elif directional_env == "Risk OFF":
        st.error("Directional Environment: Risk OFF")
    else:
        st.warning("Directional Environment: Neutral")

st.markdown("---")

# ==================== LIQUIDITY TRENDS ====================
with st.expander("💰 Liquidity Trends (Expand)", expanded=False):
    if liquidity_data:
        liquidity_shown = False

        for name, df in liquidity_data.items():
            if df is not None and len(df) > 0 and {"date", "value"}.issubset(df.columns):
                liquidity_shown = True
                with st.expander(f"📊 {name}", expanded=False):
                    if len(df) >= 2:
                        trend = "📈 Rising" if df["value"].iloc[-1] > df["value"].iloc[-2] else "📉 Falling"
                        latest = df["value"].iloc[-1]
                        st.metric(name, f"${latest:,.0f}B" if latest > 1000 else f"${latest:.2f}", trend)

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df["date"],
                        y=df["value"],
                        mode='lines',
                        fill='tozeroy',
                        line=dict(color='#1f77b4', width=2)
                    ))
                    fig.update_layout(
                        height=250,
                        margin=dict(l=0, r=0, t=20, b=0),
                        showlegend=False
                    )
                    st.plotly_chart(fig, use_container_width=True)

        if not liquidity_shown:
            st.info("💡 No liquidity data available. Add FRED_API_KEY to enable.")
    else:
        st.info("💡 Liquidity indicators disabled. Add FRED_API_KEY to config.py to enable.")

st.markdown("---")

# ==================== RATIO TRENDS ====================
with st.expander("📈 Key Ratio Trends (Expand)", expanded=False):
    col1, col2 = _responsive_cols(2)

    with col1:
        copper = data.get("HG=F")
        gold = data.get("GC=F")

        if copper is not None and gold is not None:
            df_ratio = pd.concat([
                copper["Close"].rename("copper"),
                gold["Close"].rename("gold")
            ], axis=1).ffill().dropna()

            df_ratio["ratio"] = df_ratio["copper"] / df_ratio["gold"]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_ratio.index,
                y=df_ratio["ratio"],
                mode='lines',
                fill='tozeroy',
                line=dict(color='#ff7f0e', width=2),
                name="Copper/Gold"
            ))
            ma = df_ratio["ratio"].rolling(20).mean()
            fig.add_trace(go.Scatter(
                x=df_ratio.index,
                y=ma,
                mode='lines',
                line=dict(color='red', width=2, dash='dash'),
                name="20-day MA"
            ))
            fig.update_layout(title="Copper / Gold Ratio (Growth Indicator)", height=300, hovermode='x unified')
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        hyg = data.get("HYG")
        lqd = data.get("LQD")

        if hyg is not None and lqd is not None:
            df_ratio = pd.concat([
                hyg["Close"].rename("hyg"),
                lqd["Close"].rename("lqd")
            ], axis=1).ffill().dropna()

            df_ratio["ratio"] = df_ratio["hyg"] / df_ratio["lqd"]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_ratio.index,
                y=df_ratio["ratio"],
                mode='lines',
                fill='tozeroy',
                line=dict(color='#2ca02c', width=2),
                name="HYG/LQD"
            ))
            ma = df_ratio["ratio"].rolling(20).mean()
            fig.add_trace(go.Scatter(
                x=df_ratio.index,
                y=ma,
                mode='lines',
                line=dict(color='red', width=2, dash='dash'),
                name="20-day MA"
            ))
            fig.update_layout(title="HYG / LQD Credit Spread (Risk Appetite)", height=300, hovermode='x unified')
            st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ==================== MARKET INDICATORS ====================
with st.expander("📊 View All Market Indicators", expanded=False):
    for symbol, label in MARKET_SYMBOLS.items():
        df = market_data.get(symbol)
        if df is not None and len(df) > 0:
            col1, col2 = _responsive_cols(2, [3, 1])

            with col1:
                df_chart = prepare_timeseries_for_chart(df)

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_chart.index,
                    y=df_chart["Close"],
                    mode='lines',
                    fill='tozeroy',
                    line=dict(width=2),
                    name=label
                ))

                fig.update_layout(
                    title=label,
                    height=200,
                    margin=dict(l=0, r=0, t=30, b=0),
                    showlegend=False
                )

                st.plotly_chart(fig, use_container_width=True)

            with col2:
                close_series = pd.to_numeric(df.get("Close"), errors="coerce").dropna() if "Close" in df.columns else pd.Series(dtype=float)
                if close_series.empty:
                    st.metric("Latest", "N/A", "N/A")
                else:
                    latest = float(close_series.iloc[-1])
                    prev = float(close_series.iloc[-2]) if len(close_series) >= 2 else latest
                    change = ((latest - prev) / prev * 100) if prev != 0 else 0.0
                    st.metric("Latest", f"{latest:.2f}", f"{change:+.2f}%")

# ==================== SUMMARY ====================
with st.expander("📝 Signal Summary (Expand)", expanded=False):

    summary_rows = []

    def add_summary(indicator: str, signal: str):
        explanation = SIGNAL_EXPLANATIONS.get(signal, "")
        signal_l = signal.lower()
        if any(x in signal_l for x in ["positive", "risk on", "stable", "strong"]):
            bias = "Bullish"
        elif any(x in signal_l for x in ["inverted", "risk off", "rising", "weak", "defensive"]):
            bias = "Bearish"
        else:
            bias = "Neutral"
        summary_rows.append({
            "Indicator": indicator,
            "Signal": signal,
            "Bias": bias,
            "Note": explanation,
        })

    if curve_signal:
        add_summary("Yield Curve", curve_signal)
    if is_valid_signal(dxy_signal):
        add_summary("Dollar Trend", dxy_signal)
    if is_valid_signal(yield_signal):
        add_summary("US 10Y Yield", yield_signal)
    if is_valid_signal(cg_signal):
        add_summary("Copper/Gold", cg_signal)
    if is_valid_signal(credit_signal):
        add_summary("Credit Spread", credit_signal)

    if nifty is not None and len(nifty) > 20:
        ma20 = nifty["Close"].rolling(20).mean().iloc[-1]
        signal = "Equities Strong" if nifty["Close"].iloc[-1] > ma20 else "Equities Weak"
        add_summary("NIFTY Trend", signal)

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)

        def bias_color(val):
            if val == "Bullish":
                return "color: #2e7d32; font-weight: 700;"
            if val == "Bearish":
                return "color: #c62828; font-weight: 700;"
            return "color: #f9a825; font-weight: 700;"

        styled = summary_df.style.map(bias_color, subset=["Bias"])
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("Insufficient data for signal generation")

if view_mode == "Detail":
    render_source_freshness(
        {
            "^TNX": "US 10Y Yield",
            "^IRX": "US 3M Yield",
            "DX-Y.NYB": "Dollar Index",
            "HG=F": "Copper",
            "GC=F": "Gold",
            "HYG": "High Yield (HYG)",
            "LQD": "IG Bonds (LQD)",
        },
        market_data,
        title="Leading Inputs: Source & Freshness",
    )

# ==================== FOOTER ====================
st.markdown("---")
st.caption("Data: Yahoo Finance + FRED (15-20 min delay).")
if view_mode == "Detail":
    st.caption("Tip: Leading indicators help anticipate regime shifts before markets move.")
