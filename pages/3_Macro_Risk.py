import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data_fetch import (
    batch_download,
    extract_price_data,
    prepare_timeseries_for_chart,
    fetch_india_vix,
    get_ticker_price,
    fetch_fred_series
)


from config import MACRO_THRESHOLDS, FRED_API_KEY, MACRO_WEIGHTS, MACRO_SYMBOLS
from utils import setup_page
import analytics

setup_page("Dashboard Launcher")
st.title("🌍 India Macro Risk Dashboard")

st.caption(
    "Combines global markets, FX, yields, commodities, and volatility "
    "to estimate daily Risk-On / Risk-Off conditions."
)

liquidity_series = {}   # <-- initialize first

if not FRED_API_KEY:
    st.warning("FRED API key not found. Liquidity indicators disabled.")
else:
    with st.spinner("Fetching liquidity data..."):
        liquidity_series = {
            "Fed Balance Sheet": fetch_fred_series("WALCL", FRED_API_KEY, days=30),
            "Reverse Repo": fetch_fred_series("RRPONTSYD", FRED_API_KEY, days=30),
            "Treasury General Account": fetch_fred_series("WTREGEN", FRED_API_KEY, days=30),
        }



# Indicators and Weights are imported from config.py
T = {
    "equity": MACRO_THRESHOLDS.get("equity", 0.5),
    "dxy": MACRO_THRESHOLDS.get("dxy", 0.5),
    "yield": MACRO_THRESHOLDS.get("yield", 0.5),
    "crude": MACRO_THRESHOLDS.get("crude", 0.5),
    "gold": MACRO_THRESHOLDS.get("gold", 0.7),
    "vix": MACRO_THRESHOLDS.get("vix", 2),
}


# ================= SCORING LOGIC =================

def score_indicator(symbol, df):
    """Daily risk scoring logic"""

    price, change, change_pct = extract_price_data(df)

    # Fallback if history failed
    if change_pct is None:
        price, change, change_pct = get_ticker_price(symbol)

    if change_pct is None:
        return None

    # Risk assets rising = bullish
    if symbol in ["^DJI", "^IXIC", "^NSEI", "^NSEBANK", "BTC-USD"]:
        if change_pct > T["equity"]:
            return 1
        elif change_pct < -T["equity"]:
            return -1
        else:
            return 0

    # Dollar / yields rising = risk-off

    if symbol == "DX-Y.NYB":
        return -1 if change_pct > T["dxy"] else (1 if change_pct < -T["dxy"] else 0)

    # Yields
    if symbol == "^TNX":
        return -1 if change_pct > T["yield"] else (1 if change_pct < -T["yield"] else 0)

    # USDINR
    if symbol == "USDINR=X":  # FIXED: Updated from INRUSD=X
        return -1 if change_pct > T["dxy"] else (1 if change_pct < -T["dxy"] else 0)

    # Crude rising hurts India
    if symbol == "CL=F":
        if change_pct > T["crude"]:
            return -1
        elif change_pct < -T["crude"]:
            return 1
        else:
            return 0

    # Gold defensive
    if symbol == "GC=F":
        return -1 if change_pct > T["gold"] else 0

    return 0


# ================= REGIME CLASSIFICATION =================

def classify_regime(score, indicator_count):
    threshold = max(4, (indicator_count + 2) // 3)

    if score >= threshold:
        return "🟢 Risk On", "success"
    elif score <= -threshold:
        return "🔴 Risk Off", "error"
    else:
        return "🟡 Neutral", "warning"



# ================= PLOT FUNCTION =================

def plot_smooth_chart(df, title):
    df_prepared = prepare_timeseries_for_chart(df)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_prepared.index,
        y=df_prepared["Close"],
        mode="lines",
        name=title
    ))

    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=30, b=10),
        title=title,
        hovermode="x unified"
    )

    return fig


# ================= FETCH DATA =================

symbols = list(MACRO_SYMBOLS.keys())

with st.spinner("Fetching macro data..."):
    data_1mo = batch_download(symbols, period="1mo")

# ================= INDIA VIX =================

vix_price, vix_change = fetch_india_vix()

# ================= SNAPSHOT =================

st.subheader("📊 Macro Snapshot")

cols = st.columns(4)

scores = []
rows = []
failed_symbols = []

all_items = list(MACRO_SYMBOLS.items()) + [("INDIAVIX", "India VIX")]

for i, (symbol, name) in enumerate(all_items):

    if symbol == "INDIAVIX":
        price = vix_price
        change_pct = vix_change
        if change_pct is None or price is None:
            score = None

        elif change_pct > T["vix"]:
            score = -1
        elif change_pct < -T["vix"]:
            score = 1
        else:
            score = 0





    else:
        # FIXED: Prioritize LIVE price (current market) over historical
        # This ensures Indicator Breakdown shows TODAY's actual changes
        df = data_1mo.get(symbol)
        price, change, change_pct = extract_price_data(df)

        if price is None:
            price, change, change_pct = get_ticker_price(symbol)

        # Score calculation still uses historical data for consistency
        df = data_1mo.get(symbol)
        score = score_indicator(symbol, df)

    if score is not None:
        weight = MACRO_WEIGHTS.get(symbol, 1)
        scores.append(score * weight)
    else:
        failed_symbols.append(name)

    rows.append({
        "Indicator": name,
        "1-Day Change %": round(change_pct, 2) if change_pct is not None else "N/A",
        "Score": score if score is not None else "N/A"
    })

    with cols[i % 4]:
        if price is not None:
            delta_str = f"{change_pct:+.2f}%" if change_pct is not None else None
            st.metric(name, f"{price:.2f}", delta_str)
        else:
            st.metric(name, "No Data")

# Liquidity logic has been moved to analytics.py

# ================= TOTAL SCORE =================

if not scores:
    st.error("No valid indicators available.")
    st.stop()

macro_score = sum(scores)

# Liquidity score
liquidity_score = analytics.calculate_liquidity_score(liquidity_series)

# ================= FINAL COMBINED SCORE =================

final_score = macro_score + liquidity_score
regime, regime_color = classify_regime(final_score, len(scores))

# Prepare data for stance
sofr_spread = 0 # 3_Macro_Risk doesn't fetch SOFR/IORB yet
regime_stance, _, decision_msg = analytics.get_liquidity_stance(liquidity_series, sofr_spread=sofr_spread)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Macro Score", macro_score)

with col2:
    st.metric("Liquidity Score", liquidity_score)
    st.caption(f"Status: **{regime_stance}**")

with col3:
    st.metric("Final Risk Score", final_score)


# ==================== REGIME DISPLAY ====================

if regime_color == "success":
    st.success(f"### {regime}")
elif regime_color == "error":
    st.error(f"### {regime}")
else:
    st.warning(f"### {regime}")

st.caption(f"Liquidity Overlay: **{regime_stance}**")
st.info(f"**Decision POV**: {decision_msg}")


# ================= RISK GAUGE =================

st.subheader("Risk Gauge")


max_expected_score = max(10, len(scores) * 2)
scaled = (final_score + max_expected_score) / (2 * max_expected_score)
scaled = min(max(scaled, 0), 1)

st.progress(scaled)


# ================= TRADING STANCE (Useful Insight) =================

if final_score >= 4:
    stance = "Aggressive Longs Allowed"
elif final_score <= -4:
    stance = "Defensive Mode – Reduce Risk"
else:
    stance = "Normal Positioning"

st.info(f"Trading Stance: {stance}")


# ================= DESCRIPTION =================

st.caption(
    "Macro score = market sentiment. Liquidity score = monetary conditions. "
    "Final score = combined risk regime."
)



# ================= TABLE =================

st.subheader("📋 Indicator Breakdown")
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if failed_symbols:
    st.caption("Data unavailable: " + ", ".join(failed_symbols))


# ================= RISK TREND (7 DAYS) =================

st.subheader("📉 Macro Risk Trend (Last 7 Days)")

trend_scores = []
trend_regimes = []

def get_historical_liquidity_score(series_dict, lookback_idx: int) -> int:
    """Compute liquidity score aligned with the same historical day in trend loop."""
    if not series_dict:
        return 0

    historical = {}
    for name, df in series_dict.items():
        if df is None or df.empty:
            historical[name] = None
            continue
        if lookback_idx > 0 and len(df) > lookback_idx:
            historical[name] = df.iloc[:-lookback_idx].copy()
        else:
            historical[name] = df.copy()

    return analytics.calculate_liquidity_score(historical)

for i in range(7):
    day_score = 0
    valid_count = 0

    for symbol in MACRO_SYMBOLS.keys():
        df = data_1mo.get(symbol)

        if df is not None and len(df) > i + 1:
            temp_df = df.iloc[:-i] if i > 0 else df
            score = score_indicator(symbol, temp_df)

            if score is not None:
                weight = MACRO_WEIGHTS.get(symbol, 1)
                day_score += score * weight
                valid_count += 1

    day_score += get_historical_liquidity_score(liquidity_series, i)
    trend_scores.append(day_score)

    regime_name, _ = classify_regime(day_score, valid_count)
    trend_regimes.append(regime_name)

trend_scores = list(reversed(trend_scores))
trend_regimes = list(reversed(trend_regimes))

if trend_scores:
    days_index = pd.date_range(
        end=pd.Timestamp.today(),
        periods=len(trend_scores)
    ).date
else:
    days_index = []

trend_df = pd.DataFrame({
    "Day": days_index,
    "Score": trend_scores,
    "Regime": trend_regimes
})



fig = go.Figure()

color_map = {
    "🟢 Risk On": "green",
    "🟡 Neutral": "orange",
    "🔴 Risk Off": "red"
}

fig.add_trace(go.Scatter(
    x=trend_df["Day"],
    y=trend_df["Score"],
    mode="lines+markers",
    marker=dict(
        color=[color_map.get(r, "gray") for r in trend_df["Regime"]],
        size=10
    ),
    line=dict(width=2),
    name="Risk Score"
))

fig.update_layout(height=300)
st.plotly_chart(fig, use_container_width=True)

# ================= TREND CHARTS =================

st.subheader("📈 Trend Charts (1 Month)")

chart_items = list(MACRO_SYMBOLS.items())

for idx in range(0, len(chart_items), 2):
    col1, col2 = st.columns(2)

    symbol1, name1 = chart_items[idx]
    df1 = data_1mo.get(symbol1)

    with col1:
        if df1 is not None and len(df1) > 0:
            with st.expander(name1):
                fig1 = plot_smooth_chart(df1, name1)
                st.plotly_chart(fig1, use_container_width=True)

    if idx + 1 < len(chart_items):
        symbol2, name2 = chart_items[idx + 1]
        df2 = data_1mo.get(symbol2)

        with col2:
            if df2 is not None and len(df2) > 0:
                with st.expander(name2):
                    fig2 = plot_smooth_chart(df2, name2)
                    st.plotly_chart(fig2, use_container_width=True)

# ================= LIQUIDITY DRIVERS =================

st.subheader("💧 Liquidity Drivers")

for name, df in liquidity_series.items():
    if df is not None and not df.empty:

        with st.expander(name):
            if "date" in df.columns and "value" in df.columns:
                st.line_chart(df.set_index("date")["value"])

st.caption(
"Fed balance ↑ = liquidity positive | Reverse Repo ↓ = positive | TGA ↓ = positive"
)

# ================= REGIME CHANGE ALERT =================

if len(trend_regimes) >= 2:
    if trend_regimes[-1] != trend_regimes[-2]:
        st.warning(
            f"⚠️ Regime Shift Detected: {trend_regimes[-2]} → {trend_regimes[-1]}"
        )

# ================= FOOTER =================

st.markdown("---")
st.caption("Data Sources: Yahoo Finance + NSE India + FRED")
st.caption(f"Last updated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")

