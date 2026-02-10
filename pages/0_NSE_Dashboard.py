"""
NSE Swing Trading Dashboard - ENHANCED VERSION
Keeps original format with improvements:
- Category-based stock selection (20 at a time)
- NIFTY 200 support
- Bank + Capital Market sectors added
- Midcap removed
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import numpy as np
from pathlib import Path
import logging
from typing import Optional

# Import from shared modules
from config import (
    MAIN_INDICES,
    RSI_PERIOD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    ATR_PERIOD,
    ATR_MULTIPLIER,
    BREAKOUT_WINDOW,
    VOLUME_THRESHOLD,
    CACHE_TTL
)

# Import NSE-specific config
from NSE_Config import (
    NSE_SECTOR_INDICES,  # Includes Bank + Capital Market
    STOCK_CATEGORIES,
    PRESET_WATCHLISTS,
    NIFTY_200
)

from data_fetch import batch_download, extract_price_data, get_last_n_days
from indicators import calculate_rsi, calculate_ema, calculate_atr

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

def detect_gap(df: Optional[pd.DataFrame]):
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

def calculate_volume_ratio(df: Optional[pd.DataFrame]) -> float:
    """Calculate volume ratio with safety"""
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

def detect_breakout(df: Optional[pd.DataFrame], window: int = BREAKOUT_WINDOW) -> bool:
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
    """Calculate comprehensive swing score"""
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

# ==================== SIDEBAR - STOCK SELECTION ====================
st.sidebar.header("📊 Stock Selection")

# Selection method
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
        help="Pre-configured watchlists for different strategies"
    )
    selected_stocks = PRESET_WATCHLISTS[preset]
    st.sidebar.success(f"✅ {len(selected_stocks)} stocks selected")

elif selection_method == "By Category":
    category = st.sidebar.selectbox(
        "Choose Category",
        list(STOCK_CATEGORIES.keys()),
        help="Select stocks by sector/theme"
    )
    category_stocks = STOCK_CATEGORIES[category]

    # Allow selecting up to 20 stocks from category
    max_select = min(20, len(category_stocks))
    selected_stocks = st.sidebar.multiselect(
        f"Select stocks (max {max_select})",
        category_stocks,
        default=category_stocks[:max_select],
        max_selections=20
    )

else:  # Custom Selection
    selected_stocks = st.sidebar.multiselect(
        "Select stocks (max 20)",
        NIFTY_200,
        default=NIFTY_200[:20],
        max_selections=20,
        help="Select any stocks from NIFTY 200"
    )

# Analysis mode
st.sidebar.header("⚙️ Analysis Mode")
mode = st.sidebar.radio(
    "Mode",
    ["Morning Review", "End of Day", "Full Analysis", "Swing Rankings"],
    help="Different modes for different trading times"
)

# ==================== FETCH DATA ====================
if not selected_stocks:
    st.warning("⚠️ Please select at least one stock from the sidebar")
    st.stop()

with st.spinner(f"📊 Fetching data for {len(selected_stocks)} stocks..."):
    # Fetch main indices
    index_symbols = list(MAIN_INDICES.keys())
    index_data = batch_download(index_symbols, period="3mo")

    # Fetch sectors (now includes Bank + Capital Market)
    sector_symbols = list(NSE_SECTOR_INDICES.keys())
    sector_data = batch_download(sector_symbols, period="1mo")

    # Fetch selected watchlist
    watchlist_data = batch_download(selected_stocks, period="3mo")

# ==================== MARKET OVERVIEW ====================
st.subheader("🏛️ Market Overview")

cols = st.columns(len(MAIN_INDICES))

for col, (symbol, name) in zip(cols, MAIN_INDICES.items()):
    df = index_data.get(symbol)
    price, change, change_pct = extract_price_data(df)

    if price:
        col.metric(
            name,
            f"₹{price:,.0f}" if price > 1000 else f"₹{price:.2f}",
            f"{change_pct:+.2f}%" if change_pct else None
        )
    else:
        col.metric(name, "No Data")

# ==================== SECTORAL VIEW ====================
st.subheader("📊 Sectoral Performance")
st.caption("✅ Includes Banking & Capital Market sectors")

sector_performance = []
for symbol, name in NSE_SECTOR_INDICES.items():
    df = sector_data.get(symbol)
    price, change, change_pct = extract_price_data(df)

    if change_pct is not None:
        sector_performance.append({
            'Sector': name,
            'Change %': change_pct
        })

if sector_performance:
    sector_df = pd.DataFrame(sector_performance).sort_values('Change %', ascending=False)

    # Display in columns
    sector_cols = st.columns(min(3, len(sector_performance)))

    for i, (idx, row) in enumerate(sector_df.iterrows()):
        col = sector_cols[i % 3]

        color = "🟢" if row['Change %'] > 0 else "🔴"
        col.metric(
            f"{color} {row['Sector']}",
            f"{row['Change %']:.2f}%"
        )

# ==================== MODE-SPECIFIC ANALYSIS ====================

if mode == "Morning Review":
    st.subheader("🌅 Morning Review - Today's Opportunities")
    st.caption(f"Analyzing {len(selected_stocks)} selected stocks")

    gap_stocks = []

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if df is not None and len(df) >= 2:
            gap, gap_pct = detect_gap(df)
            if abs(gap_pct) > 0.5:  # Show all gaps > 0.5%
                vol_ratio = calculate_volume_ratio(df)
                price, change, change_pct = extract_price_data(df)

                gap_stocks.append({
                    'Symbol': symbol.replace('.NS', ''),
                    'Price': price,
                    'Gap %': gap_pct,
                    'Volume Ratio': vol_ratio,
                    'Type': 'Gap Up ⬆️' if gap_pct > 0 else 'Gap Down ⬇️'
                })

    if gap_stocks:
        gap_df = pd.DataFrame(gap_stocks).sort_values('Gap %', ascending=False)

        # Format display
        gap_df['Price'] = gap_df['Price'].apply(lambda x: f"₹{x:.2f}" if x else 'N/A')
        gap_df['Gap %'] = gap_df['Gap %'].apply(lambda x: f"{x:+.2f}%")
        gap_df['Volume Ratio'] = gap_df['Volume Ratio'].apply(lambda x: f"{x:.2f}x" if x else 'N/A')

        st.dataframe(gap_df, use_container_width=True, hide_index=True)

        # Highlight top gaps
        st.info(f"🎯 Top Gap: **{gap_df.iloc[0]['Symbol']}** at {gap_df.iloc[0]['Gap %']}")
    else:
        st.info("ℹ️ No significant gaps detected in selected stocks")

elif mode == "End of Day":
    st.subheader("🌆 End of Day Review")
    st.caption(f"Analyzing {len(selected_stocks)} selected stocks")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**📊 Market Breadth**")

        advances = 0
        declines = 0
        unchanged = 0

        for symbol in selected_stocks:
            df = watchlist_data.get(symbol)
            price, change, change_pct = extract_price_data(df)

            if change_pct is not None:
                if change_pct > 0.1:
                    advances += 1
                elif change_pct < -0.1:
                    declines += 1
                else:
                    unchanged += 1

        total = advances + declines + unchanged
        if total > 0:
            st.metric("Advances", advances, f"{(advances/total)*100:.0f}%")
            st.metric("Declines", declines, f"{(declines/total)*100:.0f}%")

            if advances > declines * 1.5:
                st.success("✅ Strong advancing day")
            elif declines > advances * 1.5:
                st.error("⚠️ Strong declining day")
            else:
                st.info("➡️ Mixed market")

    with col2:
        st.markdown("**🎯 RSI Extremes**")

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
                                'RSI': f"{rsi:.1f}",
                                'Status': '🔴 Overbought' if rsi >= RSI_OVERBOUGHT else '🟢 Oversold'
                            })
                except:
                    pass

        if extreme_rsi:
            st.dataframe(pd.DataFrame(extreme_rsi), use_container_width=True, hide_index=True)
            st.caption(f"Found {len(extreme_rsi)} stocks at RSI extremes")
        else:
            st.info("No RSI extremes in selected stocks")

elif mode == "Full Analysis":
    st.subheader("📈 Full Technical Analysis")

    # Stock selector
    stock_options = [s.replace('.NS', '') for s in selected_stocks]
    selected_stock = st.selectbox("Select Stock for Analysis", stock_options)

    symbol = f"{selected_stock}.NS"
    df = watchlist_data.get(symbol)

    if df is not None and len(df) > 20:
        # Metrics row
        col1, col2, col3, col4 = st.columns(4)

        price, change, change_pct = extract_price_data(df)

        with col1:
            st.metric("Current Price", f"₹{price:.2f}" if price else "N/A",
                     f"{change_pct:+.2f}%" if change_pct else None)

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
                st.metric("ATR Stop Loss", f"₹{stop_loss:.2f}" if stop_loss else "N/A")
            except:
                st.metric("ATR Stop Loss", "N/A")

        with col4:
            vol_ratio = calculate_volume_ratio(df)
            vol_status = "High" if vol_ratio > 1.5 else ("Low" if vol_ratio < 0.8 else "Normal")
            st.metric("Volume", f"{vol_ratio:.2f}x", vol_status)

        # Price Chart with EMAs
        st.markdown("**📊 Price Chart with Moving Averages**")

        fig = go.Figure()

        # Price line
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df['Close'],
            name='Price',
            line=dict(color='#1f77b4', width=2)
        ))

        # Add EMAs if enough data
        if len(df) >= 50:
            try:
                ema20 = calculate_ema(df, 20)
                ema50 = calculate_ema(df, 50)

                fig.add_trace(go.Scatter(
                    x=df.index, y=ema20,
                    name='EMA 20',
                    line=dict(color='orange', width=1.5, dash='dash')
                ))

                fig.add_trace(go.Scatter(
                    x=df.index, y=ema50,
                    name='EMA 50',
                    line=dict(color='red', width=1.5, dash='dot')
                ))
            except:
                pass

        fig.update_layout(
            height=400,
            hovermode='x unified',
            xaxis_title="Date",
            yaxis_title="Price (₹)",
            showlegend=True
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

        vol_fig.update_layout(height=200, showlegend=False)
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
                    price, change, change_pct = extract_price_data(df)
                    gap, gap_pct = detect_gap(df)
                    vol_ratio = calculate_volume_ratio(df)
                    rs = calculate_relative_strength(df, nifty_df)

                    rankings.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'Score': score,
                        'Price': price,
                        'Change %': change_pct,
                        'Gap %': gap_pct,
                        'Vol Ratio': vol_ratio,
                        'Rel Strength': rs
                    })
                except Exception as e:
                    logger.error(f"Error calculating score for {symbol}: {e}")

    if rankings:
        rankings_df = pd.DataFrame(rankings).sort_values('Score', ascending=False)

        # Format for display
        rankings_df['Price'] = rankings_df['Price'].apply(lambda x: f"₹{x:.2f}" if x else 'N/A')
        rankings_df['Change %'] = rankings_df['Change %'].apply(lambda x: f"{x:+.2f}%" if x is not None else 'N/A')
        rankings_df['Gap %'] = rankings_df['Gap %'].apply(lambda x: f"{x:+.2f}%" if x else '0.00%')
        rankings_df['Vol Ratio'] = rankings_df['Vol Ratio'].apply(lambda x: f"{x:.2f}x")
        rankings_df['Rel Strength'] = rankings_df['Rel Strength'].apply(lambda x: f"{x:+.2f}")

        # Color coding for scores
        def highlight_score(val):
            if isinstance(val, (int, float)):
                if val >= 10:
                    return 'background-color: #90EE90'
                elif val >= 7:
                    return 'background-color: #FFFFE0'
                elif val <= 3:
                    return 'background-color: #FFB6C1'
            return ''

        styled_df = rankings_df.style.applymap(highlight_score, subset=['Score'])

        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # Top 3 Picks
        if len(rankings_df) >= 3:
            st.subheader("⭐ Top 3 Swing Picks")

            top3_cols = st.columns(3)

            for i, (idx, row) in enumerate(rankings_df.head(3).iterrows()):
                with top3_cols[i]:
                    st.markdown(f"### {i+1}. {row['Symbol']}")
                    st.metric("Swing Score", f"{row['Score']}/14")
                    st.write(f"**Price**: {row['Price']}")
                    st.write(f"**Change**: {row['Change %']}")
                    st.write(f"**Gap**: {row['Gap %']}")
                    st.write(f"**Volume**: {row['Vol Ratio']}")
                    st.write(f"**Rel. Strength**: {row['Rel Strength']}")

                    if row['Score'] >= 10:
                        st.success("🔥 Strong Setup")
                    elif row['Score'] >= 7:
                        st.info("✅ Good Setup")

        # Score distribution
        st.markdown("**📊 Score Distribution**")

        score_bins = rankings_df['Score'].value_counts(bins=5, sort=False)
        st.bar_chart(score_bins)

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
    st.caption("✅ Enhanced: NIFTY 200 | Bank & Capital Market")