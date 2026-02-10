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
from config import FRED_API_KEY

# ==================== PAGE CONFIG ====================
st.set_page_config(
    page_title="Leading Indicators",
    page_icon="📊",
    layout="wide"
)

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

# ==================== CONFIG ====================
MARKET_SYMBOLS = {
    "^IXIC": "NASDAQ",
    "^NSEI": "NIFTY 50",
    "DX-Y.NYB": "Dollar Index",
    "USDINR=X": "USD/INR",
    "GC=F": "Gold",
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield"
}

FRED_SERIES = {
    "Fed Balance Sheet": "WALCL",
    "Reverse Repo": "RRPONTSYD",
    "Treasury General Account": "WTREGEN"
}

LEADING_SYMBOLS = {
    "HG=F": "Copper",
    "GC=F": "Gold",
    "HYG": "High Yield Bonds",
    "LQD": "Investment Grade Bonds",
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield",
    "^NSEI": "NIFTY 50",
    "DX-Y.NYB": "Dollar Index"
}

# ==================== FETCH DATA ====================
ALL_SYMBOLS = list(set(MARKET_SYMBOLS.keys()) | set(LEADING_SYMBOLS.keys()))

with st.spinner("📡 Fetching market data..."):
    all_data = batch_download(ALL_SYMBOLS, period="6mo")

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
    with st.spinner("💰 Fetching liquidity data..."):
        for name, series in FRED_SERIES.items():
            liquidity_data[name] = fetch_fred_series(series, FRED_API_KEY, days=90)


# ==================== HELPER FUNCTIONS ====================

def get_last_valid_close(df):
    """Safely get last close price"""
    if df is None or "Close" not in df.columns:
        return None
    series = df["Close"].dropna()
    return series.iloc[-1] if len(series) > 0 else None


def copper_gold_signal(data):
    """Calculate Copper/Gold ratio signal"""
    copper = data.get("HG=F")
    gold = data.get("GC=F")

    if copper is None or gold is None:
        return None, None, "No Data"
    if "Close" not in copper.columns or "Close" not in gold.columns:
        return None, None, "No Data"

    df = pd.concat([
        copper["Close"].rename("copper"),
        gold["Close"].rename("gold")
    ], axis=1).ffill().dropna()

    if len(df) < 15:
        return None, None, "Insufficient Data"

    ratio = df["copper"] / df["gold"]
    ma = ratio.rolling(10).mean()

    latest_ratio = ratio.iloc[-1]
    latest_ma = ma.iloc[-1]

    score = 1 if latest_ratio > latest_ma else -1
    signal = "Copper/Gold Positive" if score == 1 else "Copper/Gold Defensive"

    return latest_ratio, score, signal


def credit_spread_signal(data):
    """Calculate HYG/LQD credit spread signal"""
    hyg = data.get("HYG")
    lqd = data.get("LQD")

    if hyg is None or lqd is None:
        return None, None, "No Data"
    if "Close" not in hyg.columns or "Close" not in lqd.columns:
        return None, None, "No Data"

    df = pd.concat([
        hyg["Close"].rename("hyg"),
        lqd["Close"].rename("lqd")
    ], axis=1).ffill().dropna()

    if len(df) < 15:
        return None, None, "Insufficient Data"

    ratio = df["hyg"] / df["lqd"]
    ratio = ratio.replace([float("inf"), -float("inf")], pd.NA).dropna()

    if len(ratio) < 10:
        return None, None, "Insufficient Data"

    ma = ratio.rolling(10).mean()

    latest_ratio = ratio.iloc[-1]
    latest_ma = ma.iloc[-1]

    score = 1 if latest_ratio > latest_ma else -1
    signal = "Credit Risk On" if score == 1 else "Credit Risk Off"

    return latest_ratio, score, signal


def dollar_trend_signal(market_data):
    """Calculate Dollar Index trend signal"""
    dxy = market_data.get("DX-Y.NYB")

    if dxy is None or len(dxy) < 10:
        return None, None, "No Data"

    latest = dxy["Close"].iloc[-1]
    ma = dxy["Close"].rolling(10).mean().iloc[-1]

    score = -1 if latest > ma else 1  # Rising dollar = risk off
    signal = "Dollar Rising" if score == -1 else "Dollar Stable"

    return latest, score, signal


def yield_trend_signal(market_data):
    """Calculate 10Y Yield trend signal - FIXED"""
    y10 = market_data.get("^TNX")

    if y10 is None or len(y10) < 10:
        return None, None, "No Data"

    if "Close" not in y10.columns:
        return None, None, "No Close Data"

    # Get clean series
    close_series = y10["Close"].dropna()

    if len(close_series) < 10:
        return None, None, "Insufficient Data"

    latest = close_series.iloc[-1]
    ma = close_series.rolling(10).mean().iloc[-1]

    score = -1 if latest > ma else 1  # Rising yields = tightening
    signal = "Yields Rising" if score == -1 else "Yields Stable"

    return latest, score, signal


# ==================== DASHBOARD LAYOUT ====================

# Top Summary Cards
st.markdown('<div class="section-header">🎯 Quick Market Signals</div>', unsafe_allow_html=True)

# Calculate all signals
ratio_cg, cg_score, cg_signal = copper_gold_signal(data)
ratio_credit, credit_score, credit_signal = credit_spread_signal(data)
dxy_value, dxy_score, dxy_signal = dollar_trend_signal(market_data)
yield_value, yield_score, yield_signal = yield_trend_signal(market_data)

# Get yield curve
yield_10y = market_data.get("^TNX")
yield_3m = market_data.get("^IRX")
y10 = get_last_valid_close(yield_10y)
y3m = get_last_valid_close(yield_3m)

curve_signal = None
if y10 is not None and y3m is not None:
    curve = y10 - y3m
    curve_signal = "Yield Curve Positive" if curve > 0 else "Yield Curve Inverted"

# Display signal cards
col1, col2, col3 = st.columns(3)

with col1:
    if curve_signal:
        card_class = "signal-card-positive" if "Positive" in curve_signal else "signal-card-negative"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>📈 Yield Curve</h3>
            <h2>{y10:.2f}% - {y3m:.2f}% = {curve:.2f}%</h2>
            <p>{SIGNAL_EXPLANATIONS.get(curve_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

with col2:
    if credit_signal != "No Data":
        card_class = "signal-card-positive" if credit_score == 1 else "signal-card-negative"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>💰 Credit Spread</h3>
            <h2>{ratio_credit:.3f}</h2>
            <p>{SIGNAL_EXPLANATIONS.get(credit_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

with col3:
    if dxy_signal != "No Data":
        card_class = "signal-card-negative" if dxy_score == -1 else "signal-card-positive"
        st.markdown(f'''
        <div class="signal-card {card_class}">
            <h3>💵 Dollar Trend</h3>
            <h2>{dxy_value:.2f}</h2>
            <p>{SIGNAL_EXPLANATIONS.get(dxy_signal, "")}</p>
        </div>
        ''', unsafe_allow_html=True)

st.markdown("---")

# ==================== DETAILED SIGNALS ====================
st.markdown('<div class="section-header">📊 Detailed Market Signals</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    # Copper/Gold Ratio
    if ratio_cg is not None:
        emoji = "🟢" if cg_score == 1 else "🔴"
        st.markdown(f"### {emoji} Copper / Gold Ratio")
        st.metric("Current Ratio", f"{ratio_cg:.4f}")
        st.caption(SIGNAL_EXPLANATIONS.get(cg_signal, ""))
    else:
        st.warning("⚠️ Copper/Gold data unavailable")

    # Dollar Index
    if dxy_value is not None:
        emoji = "🟢" if dxy_score == 1 else "🔴"
        st.markdown(f"### {emoji} Dollar Index Trend")
        st.metric("DXY", f"{dxy_value:.2f}")
        st.caption(SIGNAL_EXPLANATIONS.get(dxy_signal, ""))
    else:
        st.warning("⚠️ Dollar Index data unavailable")

with col2:
    # Credit Spread
    if ratio_credit is not None:
        emoji = "🟢" if credit_score == 1 else "🔴"
        st.markdown(f"### {emoji} Credit Spread (HYG/LQD)")
        st.metric("Ratio", f"{ratio_credit:.3f}")
        st.caption(SIGNAL_EXPLANATIONS.get(credit_signal, ""))
    else:
        st.warning("⚠️ Credit spread data unavailable")

    # Treasury Yield - FIXED
    if yield_value is not None:
        emoji = "🟢" if yield_score == 1 else "🔴"
        st.markdown(f"### {emoji} US 10Y Treasury Yield")
        st.metric("Yield", f"{yield_value:.2f}%")
        st.caption(SIGNAL_EXPLANATIONS.get(yield_signal, ""))
    else:
        st.warning("⚠️ Treasury yield data unavailable")

st.markdown("---")

# ==================== MARKET IMPULSE GAUGE ====================
st.markdown('<div class="section-header">🎯 Market Impulse Gauge</div>', unsafe_allow_html=True)

impulse_score = 0
factors = 0
factor_details = []

# Yield Curve
if y10 is not None and y3m is not None:
    score = 1 if (y10 - y3m) > 0 else -1
    impulse_score += score
    factors += 1
    factor_details.append(f"Yield Curve: {'✅' if score == 1 else '❌'}")

# Dollar
if dxy_score is not None:
    impulse_score += dxy_score
    factors += 1
    factor_details.append(f"Dollar: {'✅' if dxy_score == 1 else '❌'}")

# Equities
nifty = market_data.get("^NSEI")
if nifty is not None and len(nifty) > 20:
    ma20 = nifty["Close"].rolling(20).mean().iloc[-1]
    score = 1 if nifty["Close"].iloc[-1] > ma20 else -1
    impulse_score += score
    factors += 1
    factor_details.append(f"Equities: {'✅' if score == 1 else '❌'}")

# Liquidity
fed = liquidity_data.get("Fed Balance Sheet")
if fed is not None and len(fed) > 1:
    score = 1 if fed["value"].iloc[-1] > fed["value"].iloc[-2] else -1
    impulse_score += score
    factors += 1
    factor_details.append(f"Liquidity: {'✅' if score == 1 else '❌'}")

# Copper/Gold
if cg_score is not None:
    impulse_score += cg_score
    factors += 1
    factor_details.append(f"Copper/Gold: {'✅' if cg_score == 1 else '❌'}")

# Credit
if credit_score is not None:
    impulse_score += credit_score
    factors += 1
    factor_details.append(f"Credit: {'✅' if credit_score == 1 else '❌'}")

# Yields - FIXED: Now included
if yield_score is not None:
    impulse_score += yield_score
    factors += 1
    factor_details.append(f"Yields: {'✅' if yield_score == 1 else '❌'}")

normalized = impulse_score / factors if factors >= 3 else 0

col1, col2 = st.columns([2, 1])

with col1:
    # Gauge chart
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=normalized,
        title={'text': "Market Impulse Score", 'font': {'size': 24}},
        delta={'reference': 0},
        gauge={
            'axis': {'range': [-1, 1], 'tickwidth': 1, 'tickcolor': "darkgray"},
            'bar': {'color': "darkblue"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [-1, -0.3], 'color': '#ffcdd2'},
                {'range': [-0.3, 0.3], 'color': '#fff9c4'},
                {'range': [0.3, 1], 'color': '#c8e6c9'}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 0
            }
        }
    ))

    fig.update_layout(
        height=300,
        margin=dict(l=20, r=20, t=50, b=20)
    )

    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.markdown("### Factor Breakdown")
    st.markdown(f"**Analyzing {factors} factors:**")
    for detail in factor_details:
        st.markdown(f"• {detail}")

    if normalized > 0.3:
        st.success("🟢 **Risk ON** Environment")
    elif normalized < -0.3:
        st.error("🔴 **Risk OFF** Environment")
    else:
        st.warning("🟡 **Neutral** Environment")

st.markdown("---")

# ==================== LIQUIDITY TRENDS ====================
st.markdown('<div class="section-header">💰 Liquidity Trends</div>', unsafe_allow_html=True)

if liquidity_data:
    liquidity_shown = False

    for name, df in liquidity_data.items():
        if df is not None and len(df) > 0 and {"date", "value"}.issubset(df.columns):
            liquidity_shown = True
            with st.expander(f"📊 {name}", expanded=False):
                # Get trend
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
st.markdown('<div class="section-header">📈 Key Ratio Trends</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    # Copper/Gold Ratio
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

        # Add moving average
        ma = df_ratio["ratio"].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=df_ratio.index,
            y=ma,
            mode='lines',
            line=dict(color='red', width=2, dash='dash'),
            name="20-day MA"
        ))

        fig.update_layout(
            title="Copper / Gold Ratio (Growth Indicator)",
            height=300,
            hovermode='x unified'
        )

        st.plotly_chart(fig, use_container_width=True)

with col2:
    # HYG/LQD Credit Spread
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

        # Add moving average
        ma = df_ratio["ratio"].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=df_ratio.index,
            y=ma,
            mode='lines',
            line=dict(color='red', width=2, dash='dash'),
            name="20-day MA"
        ))

        fig.update_layout(
            title="HYG / LQD Credit Spread (Risk Appetite)",
            height=300,
            hovermode='x unified'
        )

        st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ==================== MARKET INDICATORS ====================
with st.expander("📊 View All Market Indicators", expanded=False):
    for symbol, label in MARKET_SYMBOLS.items():
        df = market_data.get(symbol)
        if df is not None and len(df) > 0:
            col1, col2 = st.columns([3, 1])

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
                latest = df["Close"].iloc[-1]
                prev = df["Close"].iloc[-2] if len(df) >= 2 else latest
                change = ((latest - prev) / prev * 100) if prev != 0 else 0

                st.metric(
                    "Latest",
                    f"{latest:.2f}",
                    f"{change:+.2f}%"
                )

# ==================== SUMMARY ====================
st.markdown('<div class="section-header">📝 Signal Summary</div>', unsafe_allow_html=True)

all_signals = []
if curve_signal:
    all_signals.append(curve_signal)
if dxy_signal != "No Data":
    all_signals.append(dxy_signal)
if yield_signal != "No Data":
    all_signals.append(yield_signal)
if cg_signal not in ["No Data", "Insufficient Data"]:
    all_signals.append(cg_signal)
if credit_signal not in ["No Data", "Insufficient Data"]:
    all_signals.append(credit_signal)

if nifty is not None and len(nifty) > 20:
    ma20 = nifty["Close"].rolling(20).mean().iloc[-1]
    signal = "Equities Strong" if nifty["Close"].iloc[-1] > ma20 else "Equities Weak"
    all_signals.append(signal)

if all_signals:
    for signal in all_signals:
        explanation = SIGNAL_EXPLANATIONS.get(signal, "")
        emoji = "🟢" if any(x in signal for x in ["Positive", "Risk On", "Stable", "Strong"]) else "🔴"
        st.markdown(f"**{emoji} {signal}**")
        if explanation:
            st.caption(explanation)
else:
    st.info("Insufficient data for signal generation")

# ==================== FOOTER ====================
st.markdown("---")
st.caption("💡 **Tip**: Leading indicators help anticipate regime shifts before markets move")
st.caption("Data: Yahoo Finance, FRED | Updated: Real-time with 15-20min delay")
st.caption("✅ Enhanced: Fixed US Treasury Yield signal | Modern UI | Better visuals")