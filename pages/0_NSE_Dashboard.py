"""
NSE Swing Trading Dashboard - FINAL VERSION WITH IMPROVEMENTS

Improvements:
- Morning Review: Table format for gaps, Market Breadth added, readable sector labels
- End of Day: VWAP analysis, Advance/Decline
- Full Analysis: VWAP line on chart
- Swing Rankings: Score categories only, cleaner layout, VWAP integration
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import numpy as np
from pathlib import Path
import logging

# Import from shared modules
from config import (
    MAIN_INDICES,
    RSI_PERIOD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    ATR_PERIOD,
    ATR_MULTIPLIER,
    BREAKOUT_WINDOW,
    VOLUME_THRESHOLD
)

# Import NSE-specific config
from NSE_Config import (
    NSE_SECTOR_INDICES,
    STOCK_CATEGORIES,
    PRESET_WATCHLISTS,
    NIFTY_200
)

from data_fetch import batch_download, extract_price_data
from indicators import calculate_rsi, calculate_ema, calculate_atr

# Import utils for consistency
from utils import (
    format_price,
    format_change,
    create_line_chart,
    get_live_price_safe
)

# ==================== LOGGING ====================
log_dir = Path.cwd() / 'logs'
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f'nse_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== PAGE CONFIG ====================
st.set_page_config(
    page_title="NSE Swing Trading",
    page_icon="📈",
    layout="wide"
)

st.title("📈 NSE Swing Trading Dashboard")
st.caption("Advanced swing trading analysis for Indian markets - NIFTY 200 Coverage")

# ==================== HELPER FUNCTIONS ====================

def detect_gap(df):
    """Detect gap up/down"""
    if df is None or len(df) < 2:
        return 0, 0

    try:
        prev_close = df['Close'].iloc[-2]
        current_open = df['Open'].iloc[-1]

        if prev_close and current_open and prev_close != 0:
            gap = current_open - prev_close
            gap_pct = (gap / prev_close) * 100
            return gap, gap_pct
    except:
        pass

    return 0, 0


def calculate_volume_ratio(df) -> float:
    """Calculate volume ratio"""
    if df is None or len(df) < 20:
        return 0

    try:
        avg_vol = df['Volume'].tail(20).mean()
        latest_vol = df['Volume'].iloc[-1]

        if avg_vol == 0 or pd.isna(avg_vol):
            return 0

        return latest_vol / avg_vol
    except:
        return 0


def calculate_vwap(df):
    """Calculate VWAP (Volume Weighted Average Price)"""
    if df is None or len(df) < 1:
        return None

    try:
        # Typical price
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3

        # VWAP = Cumulative(Typical Price * Volume) / Cumulative(Volume)
        vwap = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()

        return vwap
    except:
        return None


def detect_breakout(df, window: int = BREAKOUT_WINDOW) -> bool:
    """Detect breakout"""
    if df is None or len(df) < window + 1:
        return False

    try:
        recent = df['High'].iloc[-(window+1):-1]
        if len(recent) == 0:
            return False
        recent_high = recent.max()
        current = df['Close'].iloc[-1]
        return current > recent_high
    except:
        return False


def calculate_relative_strength(symbol_df, index_df, period: int = 20) -> float:
    """Calculate relative strength vs index"""
    if symbol_df is None or index_df is None:
        return 0

    try:
        if len(symbol_df) < period or len(index_df) < period:
            return 0

        stock_return = ((symbol_df['Close'].iloc[-1] / symbol_df['Close'].iloc[-period]) - 1) * 100
        index_return = ((index_df['Close'].iloc[-1] / index_df['Close'].iloc[-period]) - 1) * 100

        return stock_return - index_return
    except:
        return 0


def calculate_swing_score(stock_data, index_data) -> int:
    """Calculate comprehensive swing score (0-14 points)"""
    if stock_data is None or len(stock_data) < 20:
        return 0

    score = 0

    # 1. Gap analysis (0-2 points)
    gap, gap_pct = detect_gap(stock_data)
    if abs(gap_pct) > 2:
        score += 2
    elif abs(gap_pct) > 1:
        score += 1

    # 2. Volume surge (0-3 points)
    vol_ratio = calculate_volume_ratio(stock_data)
    if vol_ratio > 2:
        score += 3
    elif vol_ratio > 1.5:
        score += 2
    elif vol_ratio > 1.2:
        score += 1

    # 3. Relative strength (0-3 points)
    rs = calculate_relative_strength(stock_data, index_data)
    if rs > 5:
        score += 3
    elif rs > 2:
        score += 2
    elif rs > 0:
        score += 1

    # 4. Breakout (0-3 points)
    if detect_breakout(stock_data):
        score += 3

    # 5. Trend alignment (0-3 points)
    try:
        if len(stock_data) >= 50:
            ema20 = calculate_ema(stock_data, 20).iloc[-1]
            ema50 = calculate_ema(stock_data, 50).iloc[-1]
            current = stock_data['Close'].iloc[-1]

            if current > ema20 > ema50:
                score += 3
            elif current > ema20:
                score += 2
            elif current > ema50:
                score += 1
    except:
        pass

    return score


def calculate_support_resistance(df, period: int = 20):
    """Calculate support and resistance levels"""
    if df is None or len(df) < period:
        return None, None

    try:
        recent = df.tail(period)
        resistance = recent['High'].max()
        support = recent['Low'].min()
        return support, resistance
    except:
        return None, None


# ==================== SIDEBAR - STOCK SELECTION ====================
st.sidebar.header("📊 Stock Selection")

selection_method = st.sidebar.radio(
    "Selection Method",
    ["Preset Watchlists", "By Category", "Custom Selection"],
    help="Choose how to select stocks"
)

selected_stocks = []

if selection_method == "Preset Watchlists":
    preset = st.sidebar.selectbox(
        "Choose Watchlist",
        list(PRESET_WATCHLISTS.keys()),
        help="Pre-configured watchlists"
    )
    selected_stocks = PRESET_WATCHLISTS[preset]
    st.sidebar.success(f"✅ {len(selected_stocks)} stocks selected")

elif selection_method == "By Category":
    category = st.sidebar.selectbox(
        "Choose Category",
        list(STOCK_CATEGORIES.keys()),
        help="Select by sector/theme"
    )
    category_stocks = STOCK_CATEGORIES[category]

    max_select = min(20, len(category_stocks))
    selected_stocks = st.sidebar.multiselect(
        f"Select stocks (max {max_select})",
        category_stocks,
        default=category_stocks[:max_select],
        max_selections=20
    )

else:
    selected_stocks = st.sidebar.multiselect(
        "Select stocks (max 20)",
        NIFTY_200,
        default=NIFTY_200[:20],
        max_selections=20,
        help="Select from NIFTY 200"
    )

st.sidebar.header("⚙️ Analysis Mode")
mode = st.sidebar.radio(
    "Mode",
    ["Morning Review", "End of Day", "Full Analysis", "Swing Rankings"],
    help="Different analysis modes"
)

# ==================== FETCH DATA ====================
if not selected_stocks:
    st.warning("⚠️ Please select at least one stock from the sidebar")
    st.stop()

with st.spinner(f"📊 Fetching data for {len(selected_stocks)} stocks..."):
    index_symbols = list(MAIN_INDICES.keys())
    index_data = batch_download(index_symbols, period="3mo")

    sector_symbols = list(NSE_SECTOR_INDICES.keys())
    sector_data = batch_download(sector_symbols, period="1mo")

    watchlist_data = batch_download(selected_stocks, period="3mo")

# ==================== MARKET OVERVIEW ====================
st.subheader("🏛️ Market Overview")

cols = st.columns(len(MAIN_INDICES))

for col, (symbol, name) in zip(cols, MAIN_INDICES.items()):
    df = index_data.get(symbol)
    price, change, change_pct = get_live_price_safe(symbol, df)

    if price:
        col.metric(name, format_price(price), format_change(change_pct))
    else:
        col.metric(name, "No Data")

# ==================== SECTORAL VIEW - IMPROVED BAR CHART ====================
st.subheader("📊 Sectoral Performance")
st.caption("✅ Includes Banking & Capital Market sectors")

sector_performance = []
for symbol, name in NSE_SECTOR_INDICES.items():
    df = sector_data.get(symbol)
    price, change, change_pct = get_live_price_safe(symbol, df)

    if change_pct is not None:
        sector_performance.append({
            'Sector': name,
            'Change %': change_pct
        })

if sector_performance:
    sector_df = pd.DataFrame(sector_performance).sort_values('Change %', ascending=False)

    # IMPROVED: Better text positioning for readability
    fig = go.Figure()

    colors = ['green' if x > 0 else 'red' for x in sector_df['Change %']]

    fig.add_trace(go.Bar(
        x=sector_df['Sector'],
        y=sector_df['Change %'],
        marker_color=colors,
        text=sector_df['Change %'].apply(lambda x: f"{x:.2f}%"),
        textposition='auto',  # FIXED: Auto positioning for better readability
        textangle=0,
        hovertemplate='<b>%{x}</b><br>Change: %{y:.2f}%<extra></extra>'
    ))

    fig.update_layout(
        title="Sector Performance (Sorted by Change %)",
        xaxis_title="Sector",
        yaxis_title="Change %",
        height=400,
        showlegend=False,
        hovermode='x',
        # Add more space for text labels
        margin=dict(t=50, b=100)
    )

    fig.update_xaxes(tickangle=-45)

    st.plotly_chart(fig, use_container_width=True)

# ==================== MODE-SPECIFIC DISPLAYS ====================

if mode == "Morning Review":
    st.subheader("🌅 Morning Review - Today's Opportunities")
    st.caption(f"Analyzing {len(selected_stocks)} selected stocks")

    # IMPROVEMENT 1: Market Breadth Added
    st.markdown("### 📊 Market Breadth")

    advances = 0
    declines = 0
    unchanged = 0

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        price, change, change_pct = get_live_price_safe(symbol, df)

        if change_pct is not None:
            if change_pct > 0.1:
                advances += 1
            elif change_pct < -0.1:
                declines += 1
            else:
                unchanged += 1

    total = advances + declines + unchanged

    if total > 0:
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Advances", advances, f"{(advances/total)*100:.1f}%")

        with col2:
            st.metric("Declines", declines, f"{(declines/total)*100:.1f}%")

        with col3:
            st.metric("Unchanged", unchanged, f"{(unchanged/total)*100:.1f}%")

        with col4:
            ad_ratio = advances / declines if declines > 0 else advances
            st.metric("A/D Ratio", f"{ad_ratio:.2f}")

        # Status indicator
        if advances > declines * 1.5:
            st.success("✅ Strong advancing day - Bullish sentiment")
        elif declines > advances * 1.5:
            st.error("⚠️ Strong declining day - Bearish sentiment")
        else:
            st.info("➡️ Mixed market - Neutral sentiment")

    st.markdown("---")

    # IMPROVEMENT 2: Gap Analysis as Tables
    gap_up_stocks = []
    gap_down_stocks = []

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if df is not None and len(df) >= 2:
            gap, gap_pct = detect_gap(df)
            if abs(gap_pct) > 0.5:
                vol_ratio = calculate_volume_ratio(df)
                price, change, change_pct = extract_price_data(df)

                stock_info = {
                    'Symbol': symbol.replace('.NS', ''),
                    'Gap %': gap_pct,
                    'Volume Ratio': vol_ratio,
                    'Price': price
                }

                if gap_pct > 0:
                    gap_up_stocks.append(stock_info)
                else:
                    gap_down_stocks.append(stock_info)

    # Gap Up Table
    if gap_up_stocks:
        st.markdown("### 📈 Gap Up Stocks with Volume")
        gap_up_df = pd.DataFrame(gap_up_stocks).sort_values('Gap %', ascending=False)

        # Format table
        gap_up_df['Gap %'] = gap_up_df['Gap %'].apply(lambda x: f"{x:+.2f}%")
        gap_up_df['Volume Ratio'] = gap_up_df['Volume Ratio'].apply(lambda x: f"{x:.2f}x")
        gap_up_df['Price'] = gap_up_df['Price'].apply(lambda x: f"₹{x:.2f}" if x else 'N/A')

        # Display with color
        st.dataframe(
            gap_up_df,
            use_container_width=True,
            hide_index=True
        )

        st.caption(f"📊 {len(gap_up_df)} stocks gapping up with volume confirmation")

    # Gap Down Table
    if gap_down_stocks:
        st.markdown("### 📉 Gap Down Stocks with Volume")
        gap_down_df = pd.DataFrame(gap_down_stocks).sort_values('Gap %')

        # Format table
        gap_down_df['Gap %'] = gap_down_df['Gap %'].apply(lambda x: f"{x:+.2f}%")
        gap_down_df['Volume Ratio'] = gap_down_df['Volume Ratio'].apply(lambda x: f"{x:.2f}x")
        gap_down_df['Price'] = gap_down_df['Price'].apply(lambda x: f"₹{x:.2f}" if x else 'N/A')

        st.dataframe(
            gap_down_df,
            use_container_width=True,
            hide_index=True
        )

        st.caption(f"📊 {len(gap_down_df)} stocks gapping down with volume confirmation")

    if not gap_up_stocks and not gap_down_stocks:
        st.info("ℹ️ No significant gaps detected in selected stocks")

elif mode == "End of Day":
    st.subheader("🌆 End of Day Review")
    st.caption(f"Analyzing {len(selected_stocks)} selected stocks")

    # IMPROVEMENT 1: VWAP Analysis
    st.markdown("### 📊 VWAP Analysis")

    above_vwap = 0
    below_vwap = 0
    vwap_stocks = []

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if df is not None and len(df) >= 1:
            vwap = calculate_vwap(df)
            if vwap is not None:
                current_price = df['Close'].iloc[-1]
                vwap_value = vwap.iloc[-1]

                if current_price > vwap_value:
                    above_vwap += 1
                    vwap_stocks.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'Close': current_price,
                        'VWAP': vwap_value,
                        'Position': 'Above VWAP'
                    })
                else:
                    below_vwap += 1
                    vwap_stocks.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'Close': current_price,
                        'VWAP': vwap_value,
                        'Position': 'Below VWAP'
                    })

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Above VWAP", above_vwap, f"{(above_vwap/(above_vwap+below_vwap)*100):.1f}%" if (above_vwap+below_vwap) > 0 else "N/A")

    with col2:
        st.metric("Below VWAP", below_vwap, f"{(below_vwap/(above_vwap+below_vwap)*100):.1f}%" if (above_vwap+below_vwap) > 0 else "N/A")

    with col3:
        if above_vwap > below_vwap:
            st.success("🟢 Bullish (More above VWAP)")
        else:
            st.error("🔴 Bearish (More below VWAP)")

    # VWAP table
    if vwap_stocks:
        with st.expander("📋 View VWAP Details"):
            vwap_df = pd.DataFrame(vwap_stocks)
            vwap_df['Close'] = vwap_df['Close'].apply(lambda x: f"₹{x:.2f}")
            vwap_df['VWAP'] = vwap_df['VWAP'].apply(lambda x: f"₹{x:.2f}")
            st.dataframe(vwap_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # IMPROVEMENT 2: Advance/Decline
    st.markdown("### 📊 Advance/Decline Analysis")

    advances = 0
    declines = 0
    unchanged = 0

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        price, change, change_pct = get_live_price_safe(symbol, df)

        if change_pct is not None:
            if change_pct > 0.1:
                advances += 1
            elif change_pct < -0.1:
                declines += 1
            else:
                unchanged += 1

    total = advances + declines + unchanged

    if total > 0:
        col1, col2 = st.columns(2)

        with col1:
            # Pie chart for breadth
            fig = go.Figure(data=[go.Pie(
                labels=['Advances', 'Declines', 'Unchanged'],
                values=[advances, declines, unchanged],
                marker_colors=['green', 'red', 'gray'],
                hole=0.4
            )])

            fig.update_layout(
                title=f"Market Breadth ({total} stocks)",
                height=300
            )

            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.metric("Advances", advances, f"{(advances/total)*100:.1f}%")
            st.metric("Declines", declines, f"{(declines/total)*100:.1f}%")
            st.metric("Unchanged", unchanged, f"{(unchanged/total)*100:.1f}%")

            ad_ratio = advances / declines if declines > 0 else advances
            st.metric("A/D Ratio", f"{ad_ratio:.2f}")

            if advances > declines * 1.5:
                st.success("✅ Strong advancing day")
            elif declines > advances * 1.5:
                st.error("⚠️ Strong declining day")
            else:
                st.info("➡️ Mixed market")

    st.markdown("---")

    # IMPROVEMENT 3: RSI Extremes (kept as is)
    st.markdown("### 🎯 RSI Extremes")

    extreme_rsi = []

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if df is not None and len(df) >= RSI_PERIOD:
            try:
                rsi = calculate_rsi(df, RSI_PERIOD).iloc[-1]
                if not pd.isna(rsi):
                    if rsi >= RSI_OVERBOUGHT or rsi <= RSI_OVERSOLD:
                        extreme_rsi.append({
                            'Symbol': symbol.replace('.NS', ''),
                            'RSI': rsi,
                            'Status': 'Overbought' if rsi >= RSI_OVERBOUGHT else 'Oversold'
                        })
            except:
                pass

    if extreme_rsi:
        rsi_df = pd.DataFrame(extreme_rsi)

        # Bar chart for RSI
        fig = go.Figure()

        colors = ['red' if x == 'Overbought' else 'green' for x in rsi_df['Status']]

        fig.add_trace(go.Bar(
            x=rsi_df['Symbol'],
            y=rsi_df['RSI'],
            marker_color=colors,
            text=rsi_df['RSI'].apply(lambda x: f"{x:.1f}"),
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>RSI: %{y:.1f}<extra></extra>'
        ))

        # Add reference lines
        fig.add_hline(y=RSI_OVERBOUGHT, line_dash="dash", line_color="red",
                     annotation_text="Overbought (70)")
        fig.add_hline(y=RSI_OVERSOLD, line_dash="dash", line_color="green",
                     annotation_text="Oversold (30)")

        fig.update_layout(
            title="RSI Extremes",
            xaxis_title="Stock",
            yaxis_title="RSI",
            height=300
        )

        st.plotly_chart(fig, use_container_width=True)

        st.caption(f"📊 {len(extreme_rsi)} stocks at RSI extremes")
    else:
        st.info("No RSI extremes in selected stocks")

elif mode == "Full Analysis":
    st.subheader("📈 Full Technical Analysis")

    stock_options = [s.replace('.NS', '') for s in selected_stocks]
    selected_stock = st.selectbox("Select Stock for Analysis", stock_options)

    symbol = f"{selected_stock}.NS"
    df = watchlist_data.get(symbol)

    if df is not None and len(df) > 20:
        # Calculate VWAP
        vwap = calculate_vwap(df)

        # Metrics row
        col1, col2, col3, col4 = st.columns(4)

        price, change, change_pct = get_live_price_safe(symbol, df)

        with col1:
            st.metric("Current Price", format_price(price), format_change(change_pct))

        with col2:
            try:
                rsi = calculate_rsi(df, RSI_PERIOD).iloc[-1]
                rsi_status = "Overbought" if rsi >= RSI_OVERBOUGHT else ("Oversold" if rsi <= RSI_OVERSOLD else "Neutral")
                st.metric("RSI (14)", f"{rsi:.2f}", rsi_status)
            except:
                st.metric("RSI (14)", "N/A")

        with col3:
            try:
                atr = calculate_atr(df, ATR_PERIOD).iloc[-1]
                stop_loss = price - (atr * ATR_MULTIPLIER) if price and atr else None
                st.metric("ATR Stop Loss", format_price(stop_loss) if stop_loss else "N/A")
            except:
                st.metric("ATR Stop Loss", "N/A")

        with col4:
            vol_ratio = calculate_volume_ratio(df)
            vol_status = "High" if vol_ratio > 1.5 else ("Low" if vol_ratio < 0.8 else "Normal")
            st.metric("Volume", f"{vol_ratio:.2f}x", vol_status)

        # Support & Resistance
        support, resistance = calculate_support_resistance(df, period=20)

        if support and resistance:
            st.markdown("### 📊 Support & Resistance Levels (20-day)")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Support", format_price(support),
                         f"{((price - support) / support * 100):.2f}% away" if price else "")

            with col2:
                current_range = ((price - support) / (resistance - support) * 100) if resistance > support else 50
                st.metric("Position in Range", f"{current_range:.1f}%")

            with col3:
                st.metric("Resistance", format_price(resistance),
                         f"{((resistance - price) / price * 100):.2f}% away" if price else "")

        # IMPROVEMENT: VWAP added to chart
        st.markdown("**📊 Price Chart with Moving Averages, VWAP & Levels**")

        fig = go.Figure()

        # Candlestick
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name='Price'
        ))

        # Add EMAs
        if len(df) >= 50:
            try:
                ema20 = calculate_ema(df, 20)
                ema50 = calculate_ema(df, 50)

                fig.add_trace(go.Scatter(
                    x=df.index, y=ema20,
                    name='EMA 20',
                    line=dict(color='orange', width=2)
                ))

                fig.add_trace(go.Scatter(
                    x=df.index, y=ema50,
                    name='EMA 50',
                    line=dict(color='red', width=2)
                ))
            except:
                pass

        # Add VWAP line
        if vwap is not None:
            fig.add_trace(go.Scatter(
                x=df.index, y=vwap,
                name='VWAP',
                line=dict(color='purple', width=2, dash='dot')
            ))

        # Add Support & Resistance lines
        if support:
            fig.add_hline(y=support, line_dash="dash", line_color="green",
                         annotation_text=f"Support: ₹{support:.2f}")

        if resistance:
            fig.add_hline(y=resistance, line_dash="dash", line_color="red",
                         annotation_text=f"Resistance: ₹{resistance:.2f}")

        fig.update_layout(
            height=500,
            hovermode='x unified',
            xaxis_title="Date",
            yaxis_title="Price (₹)",
            showlegend=True,
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(fig, use_container_width=True)

        # Volume Chart
        st.markdown("**📊 Volume Analysis**")

        vol_fig = go.Figure()

        colors = ['red' if df['Close'].iloc[i] < df['Open'].iloc[i] else 'green'
                 for i in range(len(df))]

        vol_fig.add_trace(go.Bar(
            x=df.index,
            y=df['Volume'],
            name='Volume',
            marker_color=colors
        ))

        # Add average volume line
        avg_vol = df['Volume'].rolling(20).mean()
        vol_fig.add_trace(go.Scatter(
            x=df.index,
            y=avg_vol,
            name='20-day Avg',
            line=dict(color='blue', width=2, dash='dash')
        ))

        vol_fig.update_layout(height=200, showlegend=True)
        st.plotly_chart(vol_fig, use_container_width=True)

        # Additional Stats
        st.markdown("**📈 Additional Statistics**")

        stat_col1, stat_col2, stat_col3 = st.columns(3)

        with stat_col1:
            week_high = df['High'].tail(5).max()
            week_low = df['Low'].tail(5).min()
            st.write(f"**5-Day Range**: ₹{week_low:.2f} - ₹{week_high:.2f}")

        with stat_col2:
            month_high = df['High'].tail(20).max()
            month_low = df['Low'].tail(20).min()
            st.write(f"**20-Day Range**: ₹{month_low:.2f} - ₹{month_high:.2f}")

        with stat_col3:
            avg_vol = df['Volume'].tail(20).mean()
            st.write(f"**Avg Volume (20D)**: {avg_vol/1000000:.2f}M")

    else:
        st.warning(f"Insufficient data for {selected_stock}")

elif mode == "Swing Rankings":
    st.subheader("🎯 Swing Trade Rankings")
    st.caption(f"Multi-factor analysis of {len(selected_stocks)} selected stocks")

    nifty_df = index_data.get('^NSEI')

    rankings = []

    with st.spinner("Calculating swing scores..."):
        for symbol in selected_stocks:
            df = watchlist_data.get(symbol)
            if df is not None and len(df) >= 20:
                try:
                    score = calculate_swing_score(df, nifty_df)
                    price, change, change_pct = get_live_price_safe(symbol, df)
                    gap, gap_pct = detect_gap(df)
                    vol_ratio = calculate_volume_ratio(df)
                    rs = calculate_relative_strength(df, nifty_df)

                    # Calculate VWAP
                    vwap = calculate_vwap(df)
                    vwap_value = vwap.iloc[-1] if vwap is not None else None
                    vwap_position = "Above" if (price and vwap_value and price > vwap_value) else "Below"

                    rankings.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'Score': score,
                        'Price': price,
                        'VWAP': vwap_value,
                        'vs VWAP': vwap_position,
                        'Change %': change_pct,
                        'Gap %': gap_pct,
                        'Vol Ratio': vol_ratio,
                        'Rel Strength': rs
                    })
                except Exception as e:
                    logger.error(f"Error calculating score for {symbol}: {e}")

    if rankings:
        rankings_df = pd.DataFrame(rankings).sort_values('Score', ascending=False)

        # Swing Rankings Table
        st.markdown("### 📊 Swing Trade Rankings")

        display_df = rankings_df.copy()
        display_df['Price'] = display_df['Price'].apply(lambda x: format_price(x) if x else 'N/A')
        display_df['VWAP'] = display_df['VWAP'].apply(lambda x: f"₹{x:.2f}" if x and not pd.isna(x) else 'N/A')
        display_df['Change %'] = display_df['Change %'].apply(lambda x: f"{x:+.2f}%" if x is not None else 'N/A')
        display_df['Gap %'] = display_df['Gap %'].apply(lambda x: f"{x:+.2f}%" if x else '0.00%')
        display_df['Vol Ratio'] = display_df['Vol Ratio'].apply(lambda x: f"{x:.2f}x")
        display_df['Rel Strength'] = display_df['Rel Strength'].apply(lambda x: f"{x:+.2f}")

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # IMPROVEMENT: Score Categories Only (removed histogram)
        st.markdown("### 📊 Score Categories")

        col1, col2 = st.columns([1, 1])

        with col1:
            # Score categories pie chart
            strong = len(rankings_df[rankings_df['Score'] >= 10])
            good = len(rankings_df[(rankings_df['Score'] >= 7) & (rankings_df['Score'] < 10)])
            average = len(rankings_df[(rankings_df['Score'] >= 4) & (rankings_df['Score'] < 7)])
            weak = len(rankings_df[rankings_df['Score'] < 4])

            fig_pie = go.Figure(data=[go.Pie(
                labels=['Strong (10+)', 'Good (7-9)', 'Average (4-6)', 'Weak (<4)'],
                values=[strong, good, average, weak],
                marker_colors=['darkgreen', 'lightgreen', 'orange', 'lightcoral'],
                hole=0.4,
                textinfo='label+value+percent',
                textfont_size=12
            )])

            fig_pie.update_layout(
                title="Score Distribution by Category",
                height=400
            )

            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            # VWAP Position analysis
            above_vwap = len(rankings_df[rankings_df['vs VWAP'] == 'Above'])
            below_vwap = len(rankings_df[rankings_df['vs VWAP'] == 'Below'])

            fig_vwap = go.Figure(data=[go.Pie(
                labels=['Above VWAP', 'Below VWAP'],
                values=[above_vwap, below_vwap],
                marker_colors=['green', 'red'],
                hole=0.4,
                textinfo='label+value+percent',
                textfont_size=12
            )])

            fig_vwap.update_layout(
                title="VWAP Position Distribution",
                height=400
            )

            st.plotly_chart(fig_vwap, use_container_width=True)

        # Score Statistics
        st.markdown("### 📈 Score Statistics")

        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)

        with stat_col1:
            st.metric("Average Score", f"{rankings_df['Score'].mean():.2f}")

        with stat_col2:
            st.metric("Median Score", f"{rankings_df['Score'].median():.0f}")

        with stat_col3:
            st.metric("Highest Score", f"{rankings_df['Score'].max():.0f}")

        with stat_col4:
            st.metric("Strong Setups (10+)", f"{strong}")

        # Top 3 Picks
        if len(rankings_df) >= 3:
            st.markdown("### ⭐ Top 3 Swing Picks")

            top3_cols = st.columns(3)

            for i, (idx, row) in enumerate(rankings_df.head(3).iterrows()):
                with top3_cols[i]:
                    score_color = "🟢" if row['Score'] >= 10 else ("🟡" if row['Score'] >= 7 else "🔴")
                    st.markdown(f"### {i+1}. {score_color} {rankings_df.iloc[i]['Symbol']}")
                    st.metric("Swing Score", f"{row['Score']}/14")
                    st.write(f"**Price**: {display_df.iloc[i]['Price']}")
                    st.write(f"**VWAP**: {display_df.iloc[i]['VWAP']} ({row['vs VWAP']})")
                    st.write(f"**Change**: {display_df.iloc[i]['Change %']}")
                    st.write(f"**Gap**: {display_df.iloc[i]['Gap %']}")
                    st.write(f"**Volume**: {display_df.iloc[i]['Vol Ratio']}")
                    st.write(f"**Rel. Strength**: {display_df.iloc[i]['Rel Strength']}")

                    if row['Score'] >= 10:
                        st.success("🔥 Strong Setup")
                    elif row['Score'] >= 7:
                        st.info("✅ Good Setup")
                    else:
                        st.warning("⚠️ Moderate Setup")

    else:
        st.info("Insufficient data to calculate swing rankings")

# ==================== FOOTER ====================
st.markdown("---")

footer_cols = st.columns([2, 1, 1])

with footer_cols[0]:
    st.caption(f"📊 Analyzing **{len(selected_stocks)}** stocks from **{selection_method}**")

with footer_cols[1]:
    st.caption(f"🕐 Updated: {datetime.now().strftime('%H:%M:%S')}")

with footer_cols[2]:
    st.caption("✅ Enhanced: VWAP | Tables | Better visuals")