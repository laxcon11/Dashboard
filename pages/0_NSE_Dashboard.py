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
import watchlist_manager as wm
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
    SECTOR_CATEGORIES,
    THEMATIC_CATEGORIES,
    PRESET_WATCHLISTS,
    NIFTY_200
)

from data_fetch import batch_download, extract_price_data, get_last_batch_telemetry
from indicators import calculate_rsi, calculate_ema, calculate_atr

# Import analytics for centralized logic
import analytics

# Import utils for consistency
from utils import (
    setup_page,
    display_price_metric,
    display_market_breadth,
    format_price,
    format_change,
    create_line_chart,
    get_live_price_safe,
    render_key_observations,
    get_ui_detail_mode,
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
setup_page("NSE Dashboard")
view_mode = get_ui_detail_mode("Summary")

st.title("🚀 NSE Dashboard Launcher")
st.caption("Advanced swing trading analysis for Indian markets - NIFTY 200 Coverage")

# Helper functions have been moved to analytics.py


# ==================== SIDEBAR - STOCK SELECTION ====================
st.sidebar.header("📊 Stock Selection")

selection_method = st.sidebar.radio(
    "Selection Method",
    ["Preset Watchlists", "By Category", "Custom Selection"],
    help="Choose how to select stocks"
)

selected_stocks = []

if selection_method == "Preset Watchlists":
    # Dynamic Watchlist Loading
    watchlists = wm.load_watchlists()
    watchlist_names = [name for name in watchlists.keys() if name != "NIFTY 200"]
    
    col1, col2 = st.sidebar.columns([3, 1])
    with col1:
        preset = st.selectbox(
            "Choose Watchlist",
            watchlist_names,
            help="Select a saved watchlist"
        )
    with col2:
        if st.button("🔄", help="Refresh Watchlists"):
            st.rerun()

    if preset:
        selected_stocks = watchlists[preset]
        st.sidebar.success(f"✅ {len(selected_stocks)} stocks loaded")
        
        # Watchlist Management Options
        with st.sidebar.expander("📝 Manage Watchlist"):
            new_name = st.text_input("New List Name")
            if st.button("Save Current Selection as New List"):
                if new_name and selected_stocks:
                    wm.add_watchlist(new_name, selected_stocks)
                    st.success(f"Saved '{new_name}'!")
                    st.rerun()
                else:
                    st.error("Enter a name and ensure stocks are selected")
            
            if st.button("❌ Delete Current List"):
                if preset in PRESET_WATCHLISTS:
                    st.error("Cannot delete default system presets")
                else:
                    wm.delete_watchlist(preset)
                    st.success(f"Deleted '{preset}'!")
                    st.rerun()

elif selection_method == "By Category":
    category_view = st.sidebar.radio(
        "Category View",
        ["Sector-wise", "Thematic"],
        horizontal=True,
        help="Use sector-wise buckets for first-pass scanning."
    )
    category_map = SECTOR_CATEGORIES if category_view == "Sector-wise" else THEMATIC_CATEGORIES
    category = st.sidebar.selectbox(
        "Choose Category",
        list(category_map.keys()),
        help="Select by sector/theme"
    )
    category_stocks = category_map[category]

    per_category_limit = 30 if category == "🔥 Most Traded F&O (30)" else 20
    max_select = min(per_category_limit, len(category_stocks))
    selected_stocks = st.sidebar.multiselect(
        f"Select stocks (max {max_select})",
        category_stocks,
        default=category_stocks[:max_select],
        max_selections=per_category_limit
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

st.sidebar.markdown("---")
st.sidebar.header("🎯 Swing Engine")
swing_strictness = st.sidebar.selectbox(
    "Strictness",
    ["Balanced", "Conservative", "Aggressive"],
    index=0,
    help="Conservative = fewer/higher-conviction picks. Aggressive = more candidates."
)

st.sidebar.markdown("---")
st.sidebar.header("⚓ VWAP Settings")
vwap_period = st.sidebar.selectbox(
    "VWAP Anchor",
    ["Weekly (5 Days)", "Monthly (20 Days)", "Quarterly (60 Days)"],
    index=0,
    help="Calculate VWAP from the last N days"
)

# Map selection to days
vwap_map = {
    "Weekly (5 Days)": 5,
    "Monthly (20 Days)": 20,
    "Quarterly (60 Days)": 60
}
vwap_days = vwap_map[vwap_period]

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

# ==================== DATA SOURCE & FRESHNESS ====================
telemetry_df = get_last_batch_telemetry()
if telemetry_df is not None and not telemetry_df.empty:
    wl_telemetry = telemetry_df[telemetry_df["symbol"].isin(selected_stocks)].copy()
    if not wl_telemetry.empty:
        wl_telemetry = wl_telemetry.sort_values(["severity", "age_bdays"], ascending=[True, False])
        with st.sidebar.expander("🛡️ Data Freshness", expanded=False):
            stale_n = int(wl_telemetry["is_stale"].sum())
            st.caption(f"{len(wl_telemetry)} symbols tracked • stale: {stale_n}")
            show = wl_telemetry[["symbol", "source", "last_date", "age_bdays", "severity"]].rename(
                columns={"symbol": "Symbol", "source": "Source", "last_date": "Last Date", "age_bdays": "Age (Bdays)", "severity": "Status"}
            )
            st.dataframe(show, width='stretch', hide_index=True)

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

# Build sector context once and reuse in swing mode for objective "Selective" guidance.
sector_context_rows = []
for symbol, name in NSE_SECTOR_INDICES.items():
    df = sector_data.get(symbol)
    _, _, chg_pct = get_live_price_safe(symbol, df)
    if chg_pct is None:
        continue
    sector_context_rows.append({"Sector": name, "Change %": float(chg_pct)})
sector_context_df = pd.DataFrame(sector_context_rows)
if not sector_context_df.empty:
    sector_context_df = sector_context_df.sort_values("Change %", ascending=False).reset_index(drop=True)

# ==================== SECTORAL VIEW - IMPROVED BAR CHART ====================
if mode != "Swing Rankings":
    st.subheader("📊 Sectoral Performance")
    st.caption("✅ Includes Banking & Capital Market sectors")

    if not sector_context_df.empty:
        sector_df = sector_context_df.copy()

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

        st.plotly_chart(fig, width='stretch')

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
       # Market Breadth Display
        display_market_breadth(advances, declines, unchanged)

    st.markdown("---")

    # IMPROVEMENT 2: Gap Analysis as Tables
    gap_up_stocks = []
    gap_down_stocks = []

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if df is not None and len(df) >= 2:
            gap, gap_pct = analytics.detect_gap(df)
            if abs(gap_pct) > 0.5:
                vol_ratio = analytics.calculate_volume_ratio(df)
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
            width='stretch',
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
            width='stretch',
            hide_index=True
        )

        st.caption(f"📊 {len(gap_down_df)} stocks gapping down with volume confirmation")

    if not gap_up_stocks and not gap_down_stocks:
        st.info("ℹ️ No significant gaps detected in selected stocks")

    st.markdown("---")
    st.subheader("🌀 Volatility Contraction (NR7)")
    st.caption("Stocks with the narrowest range in 7 days - Watch for expansion/breakout")

    nr7_stocks = []
    
    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if analytics.detect_nr7(df):
            price, change, change_pct = get_live_price_safe(symbol, df)
            vol_ratio = analytics.calculate_volume_ratio(df)
            
            nr7_stocks.append({
                "Symbol": symbol.replace('.NS', ''),
                "Price": price,
                "Change %": change_pct,
                "Vol Ratio": vol_ratio
            })
            
    if nr7_stocks:
        nr7_df = pd.DataFrame(nr7_stocks)
        
        # Format
        nr7_df['Price'] = nr7_df['Price'].apply(lambda x: format_price(x) if x else 'N/A')
        nr7_df['Change %'] = nr7_df['Change %'].apply(lambda x: format_change(x) if x else 'N/A')
        nr7_df['Vol Ratio'] = nr7_df['Vol Ratio'].apply(lambda x: f"{x:.2f}x")
        
        st.dataframe(nr7_df, width='stretch', hide_index=True)
        st.success(f"🔥 Found {len(nr7_stocks)} stocks coiling for a move!")
    else:
        st.info("No NR7 setups detected today.")

elif mode == "End of Day":
    st.subheader("🌆 End of Day Review")
    st.caption(f"Analyzing {len(selected_stocks)} selected stocks")

    # IMPROVEMENT 1: VWAP Analysis - Side by Side Tables
    st.markdown("### 📊 VWAP Analysis")

    above_vwap_list = []
    below_vwap_list = []

    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        if df is not None and len(df) >= 1:
            # Calculate VWAP based on selected anchor
            df_vwap = df.tail(vwap_days)
            vwap = analytics.calculate_vwap(df_vwap)
            if vwap is not None:
                current_price = df['Close'].iloc[-1]
                vwap_value = vwap.iloc[-1]
                
                entry = {
                    'Symbol': symbol.replace('.NS', ''),
                    'Close': current_price,
                    'VWAP': vwap_value
                }

                if current_price > vwap_value:
                    above_vwap_list.append(entry)
                else:
                    below_vwap_list.append(entry)

    # Calculate counts for metrics
    above_count = len(above_vwap_list)
    below_count = len(below_vwap_list)
    total_vwap = above_count + below_count

    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Above VWAP", above_count, f"{(above_count/total_vwap*100):.1f}%" if total_vwap > 0 else "N/A")
    with col2:
        st.metric("Below VWAP", below_count, f"{(below_count/total_vwap*100):.1f}%" if total_vwap > 0 else "N/A")
    with col3:
        if above_count > below_count:
            st.success("🟢 Bullish Bias")
        else:
            st.error("🔴 Bearish Bias")

    # Side-by-Side Tables
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### 🟢 Above VWAP")
        if above_vwap_list:
            df_above = pd.DataFrame(above_vwap_list)
            df_above['Close'] = df_above['Close'].apply(lambda x: f"₹{x:.2f}")
            df_above['VWAP'] = df_above['VWAP'].apply(lambda x: f"₹{x:.2f}")
            st.dataframe(df_above, width='stretch', hide_index=True)
        else:
            st.info("No stocks above VWAP")

    with col_right:
        st.markdown("#### 🔴 Below VWAP")
        if below_vwap_list:
            df_below = pd.DataFrame(below_vwap_list)
            df_below['Close'] = df_below['Close'].apply(lambda x: f"₹{x:.2f}")
            df_below['VWAP'] = df_below['VWAP'].apply(lambda x: f"₹{x:.2f}")
            st.dataframe(df_below, width='stretch', hide_index=True)
        else:
            st.info("No stocks below VWAP")

    st.markdown("---")

    # IMPROVEMENT 2: Advance/Decline - Table + Pie Chart
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
        col_table, col_chart = st.columns([1, 1])

        with col_table:
            st.markdown("#### Market Breadth Stats")
            ad_data = [
                {"Category": "Advances 🟢", "Count": advances, "Percent": f"{(advances/total)*100:.1f}%"},
                {"Category": "Declines 🔴", "Count": declines, "Percent": f"{(declines/total)*100:.1f}%"},
                {"Category": "Unchanged ⚪", "Count": unchanged, "Percent": f"{(unchanged/total)*100:.1f}%"}
            ]
            st.dataframe(pd.DataFrame(ad_data), width='stretch', hide_index=True)
            
            # Summary stats below table
            st.markdown("#### Summary")
            ad_ratio = advances / declines if declines > 0 else advances
            st.metric("A/D Ratio", f"{ad_ratio:.2f}")

            if advances > declines * 1.5:
                st.success("✅ Strong advancing day")
            elif declines > advances * 1.5:
                st.error("⚠️ Strong declining day")
            else:
                st.info("➡️ Mixed market")

        with col_chart:
            # Pie chart
            fig = go.Figure(data=[go.Pie(
                labels=['Advances', 'Declines', 'Unchanged'],
                values=[advances, declines, unchanged],
                marker_colors=['green', 'red', 'gray'],
                hole=0.4
            )])
            fig.update_layout(height=300, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, width='stretch')

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
            except Exception as exc:
                logger.debug(f"RSI extreme calculation failed for {symbol}: {exc}")

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

        st.plotly_chart(fig, width='stretch')

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
        # Calculate VWAP based on selected anchor
        df_vwap = df.tail(vwap_days)
        vwap = analytics.calculate_vwap(df_vwap)

        # Metrics row
        col1, col2, col3, col4, col5 = st.columns(5)  # Increased to 5 columns for VWAP

        price, change, change_pct = get_live_price_safe(symbol, df)

        with col1:
            st.metric("Current Price", format_price(price), format_change(change_pct))

        with col2:
            vwap_val = vwap.iloc[-1] if vwap is not None else None
            st.metric("VWAP", format_price(vwap_val) if vwap_val else "N/A")

        with col3:
            try:
                rsi = calculate_rsi(df, RSI_PERIOD).iloc[-1]
                rsi_status = "Overbought" if rsi >= RSI_OVERBOUGHT else ("Oversold" if rsi <= RSI_OVERSOLD else "Neutral")
                st.metric("RSI (14)", f"{rsi:.2f}", rsi_status)
            except Exception as exc:
                logger.debug(f"RSI metric failed for {symbol}: {exc}")
                st.metric("RSI (14)", "N/A")

        with col4:
            try:
                atr = calculate_atr(df, ATR_PERIOD).iloc[-1]
                stop_loss = price - (atr * ATR_MULTIPLIER) if price and atr else None
                st.metric("ATR Stop Loss", format_price(stop_loss) if stop_loss else "N/A")
            except Exception as exc:
                logger.debug(f"ATR metric failed for {symbol}: {exc}")
                st.metric("ATR Stop Loss", "N/A")

        with col5:
            vol_ratio = analytics.calculate_volume_ratio(df)
            vol_status = "High" if vol_ratio > 1.5 else ("Low" if vol_ratio < 0.8 else "Normal")
            st.metric("Volume", f"{vol_ratio:.2f}x", vol_status)

        # Support & Resistance
        support, resistance = analytics.calculate_support_resistance(df, period=20)

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
            except Exception as exc:
                logger.debug(f"EMA overlay failed for {symbol}: {exc}")

        # Add VWAP line
        if vwap is not None:
            # Reindex to match full chart timeline (it will start mid-chart)
            vwap_series = vwap.reindex(df.index)
            
            fig.add_trace(go.Scatter(
                x=vwap_series.index, y=vwap_series,
                name=f'VWAP ({vwap_days}D)',
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

        st.plotly_chart(fig, width='stretch')

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
        st.plotly_chart(vol_fig, width='stretch')

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

        # Smart Trade Planner (moved below chart section)
        st.markdown("---")
        with st.expander("🛡️ Smart Trade Planner (Risk/Reward Calculator)", expanded=True):
            avg_range = calculate_atr(df, 14).iloc[-1]

            p_col1, p_col2, p_col3 = st.columns(3)

            with p_col1:
                risk_amt = st.number_input("Max Risk (Loss) ₹", value=5000, step=1000, help="Amount you are willing to lose if Stop Loss is hit")
                entry = st.number_input("Entry Price", value=float(price))

            with p_col2:
                sl_type = st.selectbox("Stop Loss Strategy", ["2x ATR (Vol Based)", "Recent Low (20D)", "3% Fixed"])

                if "ATR" in sl_type:
                    stop_loss = entry - (avg_range * 2)
                    sl_desc = f"Based on 2x ATR ({avg_range:.2f})"
                elif "Recent Low" in sl_type:
                    stop_loss = df['Low'].tail(20).min()
                    sl_desc = "Lowest low of last 20 days"
                else:
                    stop_loss = entry * 0.97
                    sl_desc = "Fixed 3% Stop"

                st.metric("Suggested Stop Loss", format_price(stop_loss), sl_desc)

            with p_col3:
                risk_per_share = entry - stop_loss
                if risk_per_share > 0:
                    qty = int(risk_amt / risk_per_share)
                    target = entry + (risk_per_share * 2) # 1:2
                    capital_req = qty * entry

                    st.metric("Target (1:2 Risk)", format_price(target), f"Capital Req: {format_price(capital_req)}")
                    st.success(f"Position Size: **{qty} shares**")
                else:
                    st.error("Invalid Stop Loss (Must be < Entry)")

    else:
        st.warning(f"Insufficient data for {selected_stock}")

elif mode == "Swing Rankings":
    st.subheader("🎯 Swing Trade Rankings")
    st.caption(f"Regime-gated setup engine on {len(selected_stocks)} selected stocks")

    strictness_cfg = {
        "Conservative": {
            "tier_a_plus": 8.8,
            "tier_a": 8.0,
            "tier_b": 7.2,
            "min_vol_ratio": 1.0,
            "min_rs": -1.0,
            "risk_on_breadth": 1.2,
            "risk_off_breadth": 0.85,
            "risk_off_min_score": 9.4,
            "top_n": 2,
            "watchlist_n": 4,
        },
        "Balanced": {
            "tier_a_plus": 8.5,
            "tier_a": 7.5,
            "tier_b": 6.5,
            "min_vol_ratio": 0.8,
            "min_rs": -3.0,
            "risk_on_breadth": 1.1,
            "risk_off_breadth": 0.9,
            "risk_off_min_score": 9.0,
            "top_n": 3,
            "watchlist_n": 5,
        },
        "Aggressive": {
            "tier_a_plus": 8.2,
            "tier_a": 7.0,
            "tier_b": 6.0,
            "min_vol_ratio": 0.6,
            "min_rs": -5.0,
            "risk_on_breadth": 1.0,
            "risk_off_breadth": 0.95,
            "risk_off_min_score": 8.6,
            "top_n": 4,
            "watchlist_n": 8,
        },
    }
    cfg = strictness_cfg.get(swing_strictness, strictness_cfg["Balanced"])

    def clamp_score(value):
        return max(0.0, min(10.0, value))

    def setup_tier(score):
        if score >= cfg["tier_a_plus"]:
            return "A+"
        if score >= cfg["tier_a"]:
            return "A"
        if score >= cfg["tier_b"]:
            return "B"
        return "C"

    nifty_df = index_data.get('^NSEI')
    bank_df = index_data.get('^NSEBANK')

    advances, declines = 0, 0
    for symbol in selected_stocks:
        df = watchlist_data.get(symbol)
        _, _, chg = get_live_price_safe(symbol, df)
        if chg is not None:
            if chg > 0.1:
                advances += 1
            elif chg < -0.1:
                declines += 1

    breadth_ratio = (advances / declines) if declines > 0 else (float(advances) if advances > 0 else 0.0)

    def trend_signal(df):
        if df is None or len(df) < 50:
            return 0
        close = df['Close'].dropna()
        if len(close) < 50:
            return 0
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        current = close.iloc[-1]
        if current > ema20 > ema50:
            return 1
        if current < ema20 < ema50:
            return -1
        return 0

    regime_score = trend_signal(nifty_df) + trend_signal(bank_df)
    if regime_score >= 1 and breadth_ratio >= cfg["risk_on_breadth"]:
        regime_label = "🟢 Risk On"
        regime_bias = "Long setups preferred"
        regime_adj = 0.7
    elif regime_score <= -1 and breadth_ratio <= cfg["risk_off_breadth"]:
        regime_label = "🔴 Risk Off"
        regime_bias = "Defensive mode, avoid aggressive longs"
        regime_adj = -1.0
    else:
        regime_label = "🟡 Neutral"
        regime_bias = "Selective setups only"
        regime_adj = 0.0

    r1, r2, r3 = st.columns(3)
    r1.metric("Market Regime", regime_label)
    r2.metric("A/D Breadth", f"{advances}:{declines}", f"{breadth_ratio:.2f}")
    r3.info(f"{regime_bias} | {swing_strictness}")

    # Objective context for Neutral/Selective regimes using sector-level dispersion and breadth.
    if regime_label == "🟡 Neutral":
        st.markdown("### 🎯 Selective Context (Objective)")
        if sector_context_df.empty:
            st.info("Sector context unavailable for now.")
        else:
            sector_adv = int((sector_context_df["Change %"] > 0).sum())
            sector_total = int(len(sector_context_df))
            sector_breadth = (sector_adv / sector_total) if sector_total > 0 else 0.0
            sector_dispersion = float(sector_context_df["Change %"].std(ddof=0)) if sector_total > 1 else 0.0
            leadership_spread = float(sector_context_df["Change %"].iloc[0] - sector_context_df["Change %"].iloc[-1])

            if sector_breadth >= 0.65 and sector_dispersion < 0.8:
                selective_note = "Broad participation improving. You can be less selective."
            elif sector_breadth <= 0.35:
                selective_note = "Weak participation. Keep exposure light and prioritize capital protection."
            else:
                selective_note = "Dispersion market. Focus only on leadership sectors and avoid laggards."

            s1, s2, s3 = st.columns(3)
            s1.metric("Sector Breadth", f"{sector_adv}/{sector_total}", f"{sector_breadth:.0%}")
            s2.metric("Sector Dispersion", f"{sector_dispersion:.2f}")
            s3.metric("Leadership Spread", f"{leadership_spread:+.2f}%")
            st.caption(selective_note)

            leaders = sector_context_df.head(3).copy()
            laggards = sector_context_df.tail(2).copy().sort_values("Change %", ascending=True)
            l1, l2 = st.columns(2)
            with l1:
                st.markdown("**Focus Sectors (Top 3)**")
                st.dataframe(
                    leaders.assign(**{"Change %": leaders["Change %"].map(lambda x: f"{x:+.2f}%")}),
                    width="stretch",
                    hide_index=True,
                )
            with l2:
                st.markdown("**Avoid / Underweight (Bottom 2)**")
                st.dataframe(
                    laggards.assign(**{"Change %": laggards["Change %"].map(lambda x: f"{x:+.2f}%")}),
                    width="stretch",
                    hide_index=True,
                )

    def clip01(v):
        return max(0.0, min(1.0, v))

    liq_score = 0
    liq_score += 1 if breadth_ratio >= 1.05 else -1
    liq_score += 1 if advances > declines else -1
    liq_score += 1 if trend_signal(nifty_df) >= 0 else -1
    liq_score += 1 if trend_signal(bank_df) >= 0 else -1
    if liq_score >= 2:
        liquidity_label = "🟢 Healthy"
        liquidity_gate_pass = True
    elif liq_score >= 0:
        liquidity_label = "🟡 Neutral"
        liquidity_gate_pass = True
    else:
        liquidity_label = "🔴 Tight"
        liquidity_gate_pass = False

    regime_gate_pass = regime_label != "🔴 Risk Off"
    g1, g2, g3 = st.columns(3)
    g1.metric("Liquidity Check", liquidity_label, f"Score {liq_score:+d}")
    g2.metric("Regime Check", "Pass" if regime_gate_pass else "Blocked", regime_label)
    g3.metric("Global Checks", "Pass" if (regime_gate_pass and liquidity_gate_pass) else "Blocked")

    n_change = 0.0
    b_change = 0.0
    if nifty_df is not None and "Close" in nifty_df.columns:
        s = pd.to_numeric(nifty_df["Close"], errors="coerce").dropna()
        if len(s) >= 2 and s.iloc[-2] != 0:
            n_change = ((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2]) * 100
    if bank_df is not None and "Close" in bank_df.columns:
        s = pd.to_numeric(bank_df["Close"], errors="coerce").dropna()
        if len(s) >= 2 and s.iloc[-2] != 0:
            b_change = ((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2]) * 100
    swing_observations = [
        f"Regime filter: {regime_label} ({regime_bias}).",
        f"Liquidity gate: {liquidity_label} (score {liq_score:+d}).",
        f"NIFTY {n_change:+.2f}% | BANKNIFTY {b_change:+.2f}% | Breadth {advances}:{declines} ({breadth_ratio:.2f}).",
    ]
    render_key_observations(swing_observations)

    raw_rows = []
    with st.spinner("Scoring candidates with setup-family and hard gates..."):
        for symbol in selected_stocks:
            df = watchlist_data.get(symbol)
            if df is None or len(df) < 80:
                continue

            try:
                price, change, change_pct = get_live_price_safe(symbol, df)
                if price is None:
                    continue

                vol_ratio = analytics.calculate_volume_ratio(df)
                rs = analytics.calculate_relative_strength(df, nifty_df)
                rsi = calculate_rsi(df).iloc[-1] if len(df) > 14 else np.nan
                ema20 = calculate_ema(df, 20).iloc[-1]
                ema50 = calculate_ema(df, 50).iloc[-1]
                atr14 = calculate_atr(df, ATR_PERIOD).iloc[-1] if len(df) > ATR_PERIOD else np.nan
                atr_pct = ((atr14 / price) * 100.0) if (price and pd.notna(atr14) and atr14 > 0) else np.nan
                trend_bull = bool(price > ema20 > ema50)
                breakout = analytics.detect_breakout(df)
                nr7 = analytics.detect_nr7(df)
                dist_ema20 = ((price - ema20) / ema20 * 100) if ema20 else 0
                inside_day = bool(
                    len(df) >= 2 and
                    (df["High"].iloc[-1] <= df["High"].iloc[-2]) and
                    (df["Low"].iloc[-1] >= df["Low"].iloc[-2])
                )
                close = df["Close"].dropna()
                if close.empty:
                    continue
                low10 = df["Low"].tail(10).min() if "Low" in df.columns else close.tail(10).min()
                low20 = df["Low"].tail(20).min() if "Low" in df.columns else close.tail(20).min()

                rs_stability = 0.5
                if nifty_df is not None and "Close" in nifty_df.columns:
                    merged = pd.concat(
                        [close.rename("s"), nifty_df["Close"].dropna().rename("b")],
                        axis=1
                    ).dropna()
                    if len(merged) >= 30:
                        rel_ret = merged["s"].pct_change() - merged["b"].pct_change()
                        rel_std = rel_ret.tail(20).std()
                        if pd.notna(rel_std):
                            rs_stability = clip01(1.0 - (rel_std * 35.0))

                trend_align = 1.0 if trend_bull else 0.0
                vol_quality = clip01(vol_ratio / 2.0)
                rs_quality = clip01((rs + 10.0) / 20.0)
                quality_score = (0.40 * vol_quality) + (0.30 * rs_quality) + (0.30 * rs_stability)
                quality_gate_pass = bool(
                    (vol_ratio >= cfg["min_vol_ratio"]) and
                    (rs >= cfg["min_rs"]) and
                    (quality_score >= 0.45)
                )

                # Strict setup families
                momentum_pass = bool(trend_bull and breakout and (vol_ratio >= 1.0) and (rsi >= 52) and (rsi <= 78))
                pullback_pass = bool(trend_bull and (-2.5 <= dist_ema20 <= 1.5) and (40 <= rsi <= 58) and (not breakout))
                vol_contract_pass = bool(nr7 and inside_day and (abs(dist_ema20) <= 4.0) and (pd.isna(atr_pct) or atr_pct <= 4.0))

                hard_gate_pass = bool(regime_gate_pass and liquidity_gate_pass and quality_gate_pass)
                gate_reasons = []
                if not regime_gate_pass:
                    gate_reasons.append("Regime")
                if not liquidity_gate_pass:
                    gate_reasons.append("Liquidity")
                if not quality_gate_pass:
                    gate_reasons.append("Quality")
                gate_reason = "OK" if not gate_reasons else ", ".join(gate_reasons)

                raw_rows.append({
                    "Symbol": symbol.replace('.NS', ''),
                    "Price": price,
                    "Change %": change_pct,
                    "RS": rs,
                    "Vol Ratio": vol_ratio,
                    "RSI": rsi,
                    "dist_ema20": dist_ema20,
                    "Trend": "Bullish" if trend_bull else "Bearish",
                    "Breakout": breakout,
                    "NR7": nr7,
                    "Inside Day": inside_day,
                    "ATR%": atr_pct,
                    "Trend Align": trend_align,
                    "Vol Quality": vol_quality,
                    "RS Stability": rs_stability,
                    "Quality Score": quality_score,
                    "Quality Gate": quality_gate_pass,
                    "Regime Gate": regime_gate_pass,
                    "Liquidity Gate": liquidity_gate_pass,
                    "Hard Gate": hard_gate_pass,
                    "Gate Reason": gate_reason,
                    "Momentum Pass": momentum_pass,
                    "Pullback Pass": pullback_pass,
                    "Volatility Pass": vol_contract_pass,
                    "Mom Base": analytics.calculate_momentum_score(df, nifty_df),
                    "PB Base": analytics.calculate_pullback_score(df, nifty_df),
                    "Inv Momentum": max(low10, ema20 - (atr14 if pd.notna(atr14) else 0.0)),
                    "Inv Pullback": low10,
                    "Inv Volatility": df["Low"].iloc[-1] if "Low" in df.columns else low20,
                })
            except Exception as e:
                logger.error(f"Error scoring {symbol}: {e}")

    if not raw_rows:
        st.warning("No stocks had enough data for setup-family scoring.")
        st.stop()

    score_df = pd.DataFrame(raw_rows)
    score_df["RS Pct"] = score_df["RS"].rank(pct=True).fillna(0.5)
    score_df["Vol Pct"] = score_df["Vol Ratio"].rank(pct=True).fillna(0.5)

    # Decomposed scoring with tie-breaker quality terms
    score_df["M_Breakout"] = score_df["Breakout"].apply(lambda x: 1.6 if x else -0.8)
    score_df["M_Trend"] = score_df["Trend"].apply(lambda x: 1.2 if x == "Bullish" else -1.0)
    score_df["M_RS"] = 2.3 * score_df["RS Pct"]
    score_df["M_Vol"] = 1.6 * score_df["Vol Pct"]
    score_df["M_Stability"] = 1.0 * score_df["RS Stability"]
    score_df["Momentum Score"] = (
        3.0 + (0.55 * score_df["Mom Base"]) + score_df["M_Breakout"] + score_df["M_Trend"] +
        score_df["M_RS"] + score_df["M_Vol"] + score_df["M_Stability"] + regime_adj
    ).apply(clamp_score)

    score_df["P_Distance"] = score_df["dist_ema20"].apply(lambda x: 1.4 if -2.5 <= x <= 1.5 else -0.6)
    score_df["P_RSI"] = score_df["RSI"].apply(lambda x: 1.2 if 40 <= x <= 58 else -0.6)
    score_df["P_Trend"] = score_df["Trend"].apply(lambda x: 1.0 if x == "Bullish" else -0.8)
    score_df["P_RS"] = 1.8 * score_df["RS Pct"]
    score_df["P_Stability"] = 1.1 * score_df["RS Stability"]
    score_df["Pullback Score"] = (
        2.8 + (0.60 * score_df["PB Base"]) + score_df["P_Distance"] + score_df["P_RSI"] +
        score_df["P_Trend"] + score_df["P_RS"] + score_df["P_Stability"] + (regime_adj * 0.8)
    ).apply(clamp_score)

    score_df["V_NR7"] = score_df["NR7"].apply(lambda x: 2.8 if x else 0.0)
    score_df["V_Inside"] = score_df["Inside Day"].apply(lambda x: 1.2 if x else 0.0)
    score_df["V_Distance"] = score_df["dist_ema20"].apply(lambda x: 1.3 if abs(x) <= 4 else -0.4)
    score_df["V_Vol"] = 1.5 * score_df["Vol Pct"]
    score_df["V_RS"] = 1.0 * score_df["RS Pct"]
    score_df["Volatility Score"] = (
        1.8 + score_df["V_NR7"] + score_df["V_Inside"] + score_df["V_Distance"] +
        score_df["V_Vol"] + score_df["V_RS"] + (0.9 * score_df["RS Stability"]) + (regime_adj * 0.5)
    ).apply(clamp_score)

    def build_family(df, score_col, setup_name, pass_col, inv_col):
        temp = df[df[pass_col]].copy()
        if temp.empty:
            return temp
        temp["Score"] = temp[score_col].round(2)
        temp["Setup Type"] = setup_name
        temp["Tier"] = temp["Score"].apply(setup_tier)
        temp["Invalidation"] = temp[inv_col]
        temp["Invalidation %"] = ((temp["Price"] - temp["Invalidation"]) / temp["Price"] * 100).round(2)
        temp["Gate Status"] = np.where(temp["Hard Gate"], "Pass", "Blocked")
        return temp.sort_values(
            ["Score", "Trend Align", "Vol Quality", "RS Stability", "RS"],
            ascending=[False, False, False, False, False]
        )

    momentum_df = build_family(score_df, "Momentum Score", "Momentum 🚀", "Momentum Pass", "Inv Momentum")
    pullback_df = build_family(score_df, "Pullback Score", "Pullback 🛒", "Pullback Pass", "Inv Pullback")
    volatility_df = build_family(score_df, "Volatility Score", "Volatility Contraction 🌀", "Volatility Pass", "Inv Volatility")

    combined = pd.concat([momentum_df, pullback_df, volatility_df], ignore_index=True) if (
        (not momentum_df.empty) or (not pullback_df.empty) or (not volatility_df.empty)
    ) else pd.DataFrame()

    if combined.empty:
        st.warning("No setup-family candidates met strict definitions today.")
        st.stop()

    # Tier buckets (familiar A+/A/B/C view)
    tier_best = combined.sort_values(
        ["Score", "Trend Align", "Vol Quality", "RS Stability"],
        ascending=[False, False, False, False]
    ).drop_duplicates(subset=["Symbol"])
    tier_counts = tier_best["Tier"].value_counts()
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("A+", int(tier_counts.get("A+", 0)))
    t2.metric("A", int(tier_counts.get("A", 0)))
    t3.metric("B", int(tier_counts.get("B", 0)))
    t4.metric("C", int(tier_counts.get("C", 0)))

    execution_mode = st.toggle(
        "Execution Mode (Tradable-Only)",
        value=True,
        help="ON: show only executable picks. OFF: show discovery view with pre-gate and blocked candidates.",
    )
    if execution_mode:
        st.caption("Mode: Execution-first. Primary view shows only Tradable Now setups.")
    else:
        st.caption("Mode: Discovery-first. Includes pre-gate and blocked/watch candidates.")

    hard_pass_total = combined[combined["Hard Gate"]].drop_duplicates(subset=["Symbol"]).shape[0]
    hard_pass_a_total = combined[
        combined["Hard Gate"] & combined["Tier"].isin(["A+", "A"])
    ].drop_duplicates(subset=["Symbol"]).shape[0]
    st.caption(
        f"Tradable-check pass: {hard_pass_total} symbols | "
        f"A+/A among tradable-check pass: {hard_pass_a_total}"
    )

    if not execution_mode:
        st.markdown(f"### ⭐ Top Ranked (Pre-Gate) - Best {cfg['top_n']}")
        top_ranked = tier_best.head(cfg["top_n"]).copy()
        if not top_ranked.empty:
            top_rank_cols = st.columns(len(top_ranked))
            for i, (_, row) in enumerate(top_ranked.iterrows()):
                with top_rank_cols[i]:
                    with st.container(border=True):
                        st.markdown(f"#### {i+1}. {row['Symbol']}")
                        st.caption(f"{row['Setup Type']} • Tier {row['Tier']}")
                        st.metric("Score", f"{row['Score']:.2f}/10")
                        st.metric("Price", format_price(row['Price']), format_change(row['Change %']))
                        st.caption(f"Entry Gate: {row['Gate Status']} ({row['Gate Reason']})")
                        st.caption(f"Invalidation: {format_price(row['Invalidation'])} ({row['Invalidation %']:.2f}% risk)")
                        sym = row['Symbol']
                        prefill_symbol = sym if sym.endswith(".NS") else f"{sym}.NS"
                        if st.button("Log Setup", key=f"log_setup_toprank_{i}_{sym}", width='stretch'):
                            st.session_state["journal_prefill"] = {
                                "symbol": prefill_symbol,
                                "strategy": "Top Ranked Pick",
                                "side": "LONG",
                            }
                            st.switch_page("pages/5_Trading_Journal.py")

    actionable = combined[
        (combined["Tier"].isin(["A+", "A"])) &
        (combined["Hard Gate"])
    ].drop_duplicates(subset=["Symbol", "Setup Type"]).sort_values(
        ["Score", "Trend Align", "Vol Quality", "RS Stability"],
        ascending=[False, False, False, False]
    ).head(cfg["top_n"])

    monitor = combined[
        (combined["Tier"].isin(["A+", "A", "B"])) &
        (~combined["Hard Gate"] | combined["Tier"].eq("B"))
    ].drop_duplicates(subset=["Symbol", "Setup Type"]).sort_values(
        ["Score", "Trend Align", "Vol Quality", "RS Stability"],
        ascending=[False, False, False, False]
    ).head(cfg["watchlist_n"])

    if not actionable.empty:
        st.markdown("### 🏆 Tradable Now (A+/A + Entry Gate Pass)")
        top_cols = st.columns(len(actionable))
        for i, (_, row) in enumerate(actionable.iterrows()):
            with top_cols[i]:
                with st.container(border=True):
                    st.markdown(f"#### {i+1}. {row['Symbol']}")
                    st.caption(f"{row['Setup Type']} • Tier {row['Tier']}")
                    st.metric("Score", f"{row['Score']:.2f}/10")
                    st.metric("Price", format_price(row['Price']), format_change(row['Change %']))
                    st.caption(f"Invalidation: {format_price(row['Invalidation'])} ({row['Invalidation %']:.2f}% risk)")
                    st.caption(f"Trend:{row['Trend']} | Vol:{row['Vol Ratio']:.2f}x | RSI:{row['RSI']:.1f}")

                    sym = row['Symbol']
                    prefill_symbol = sym if sym.endswith(".NS") else f"{sym}.NS"
                    if st.button("Log Setup", key=f"log_setup_phase2_{i}_{sym}", width='stretch'):
                        st.session_state["journal_prefill"] = {
                            "symbol": prefill_symbol,
                            "strategy": "Swing Family v2",
                            "side": "LONG",
                        }
                        st.switch_page("pages/5_Trading_Journal.py")
    else:
        if hard_pass_total == 0:
            st.info("No stock passed Entry Gate today (Regime + Liquidity + Quality).")
        elif hard_pass_a_total == 0:
            st.info(f"{hard_pass_total} stocks passed Entry Gate, but all are B/C tier (no A+/A tradable picks).")
        else:
            st.info("No A+/A tradable setups passed Entry Gate today.")

    if (not execution_mode) and (not monitor.empty):
        st.markdown("### 👀 Watch / Improve (A+/A Blocked + B Tier)")
        mon = monitor[[
            "Symbol", "Setup Type", "Tier", "Score", "Gate Status", "Price", "Change %",
            "Invalidation", "Invalidation %", "RS", "Vol Ratio", "RSI", "Quality Score", "Gate Reason"
        ]].copy()
        mon = mon.rename(columns={"Gate Status": "Entry Gate", "Gate Reason": "Block Reason"})
        mon["Price"] = mon["Price"].apply(format_price)
        mon["Change %"] = mon["Change %"].apply(format_change)
        mon["Invalidation"] = mon["Invalidation"].apply(format_price)
        mon["Vol Ratio"] = mon["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
        mon["RSI"] = mon["RSI"].apply(lambda x: f"{x:.1f}")
        mon["Quality Score"] = mon["Quality Score"].apply(lambda x: f"{x:.2f}")
        mon["Invalidation %"] = mon["Invalidation %"].apply(lambda x: f"{x:.2f}%")
        st.dataframe(mon, width='stretch', hide_index=True)

        blocked_a = monitor[(monitor["Tier"].isin(["A+", "A"])) & (~monitor["Hard Gate"])].shape[0]
        b_count = monitor[monitor["Tier"] == "B"].shape[0]
        st.caption(f"Breakdown: {blocked_a} A+/A blocked, {b_count} B-tier watch candidates.")

        blocked_diag = monitor[(monitor["Tier"].isin(["A+", "A"])) & (~monitor["Hard Gate"])].copy()
        if not blocked_diag.empty:
            st.markdown("#### Why A+/A Were Blocked")
            diag_rows = []
            for _, row in blocked_diag.head(20).iterrows():
                reasons = str(row.get("Gate Reason", "Unknown"))
                diag_rows.append(
                    {
                        "Symbol": row["Symbol"],
                        "Setup": row["Setup Type"],
                        "Tier": row["Tier"],
                        "Score": f"{row['Score']:.2f}",
                        "Regime Check": "Pass" if bool(row.get("Regime Gate")) else "Blocked",
                        "Liquidity Check": "Pass" if bool(row.get("Liquidity Gate")) else "Blocked",
                        "Quality Check": "Pass" if bool(row.get("Quality Gate")) else "Blocked",
                        "Block Reason": reasons,
                    }
                )
            st.dataframe(pd.DataFrame(diag_rows), width="stretch", hide_index=True)

    if (not execution_mode) and (view_mode == "Detail"):
        with st.expander("🏷️ Tier Buckets (A+ / A / B / C)", expanded=False):
            tier_cols = ["Symbol", "Setup Type", "Tier", "Score", "Gate Status", "Gate Reason", "Price", "Change %", "Invalidation %"]
            for tier_label in ["A+", "A", "B", "C"]:
                st.markdown(f"### {tier_label} Tier")
                tdf = tier_best[tier_best["Tier"] == tier_label][tier_cols].head(15).copy()
                if tdf.empty:
                    st.info(f"No {tier_label} tier picks.")
                    continue
                tdf = tdf.rename(columns={"Gate Status": "Entry Gate", "Gate Reason": "Block Reason"})
                tdf["Price"] = tdf["Price"].apply(format_price)
                tdf["Change %"] = tdf["Change %"].apply(format_change)
                tdf["Invalidation %"] = tdf["Invalidation %"].apply(lambda x: f"{x:.2f}%")
                st.dataframe(tdf, width='stretch', hide_index=True)

    if (not execution_mode) and (view_mode == "Detail"):
        with st.expander("📊 Setup Family Boards", expanded=False):
            st.markdown("### 🚀 Momentum")
            mview_cols = ["Symbol", "Tier", "Score", "Price", "Change %", "RS", "Vol Ratio", "RSI", "Trend", "Gate Status", "Invalidation %"]
            if not momentum_df.empty:
                mview = momentum_df[mview_cols].head(12).copy()
                mview["Price"] = mview["Price"].apply(format_price)
                mview["Change %"] = mview["Change %"].apply(format_change)
                mview["Vol Ratio"] = mview["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
                mview["RSI"] = mview["RSI"].apply(lambda x: f"{x:.1f}")
                mview["Invalidation %"] = mview["Invalidation %"].apply(lambda x: f"{x:.2f}%")
                st.dataframe(mview, width='stretch', hide_index=True)
            else:
                st.info("No momentum setups today.")

            st.markdown("### 🛒 Pullback")
            if not pullback_df.empty:
                pview = pullback_df[["Symbol", "Tier", "Score", "Price", "RSI", "dist_ema20", "Trend", "Gate Status", "Invalidation %"]].head(12).copy()
                pview["Price"] = pview["Price"].apply(format_price)
                pview["RSI"] = pview["RSI"].apply(lambda x: f"{x:.1f}")
                pview["dist_ema20"] = pview["dist_ema20"].apply(lambda x: f"{x:.1f}%")
                pview["Invalidation %"] = pview["Invalidation %"].apply(lambda x: f"{x:.2f}%")
                st.dataframe(pview, width='stretch', hide_index=True)
            else:
                st.info("No pullback setups today.")

            st.markdown("### 🌀 Volatility Contraction")
            if not volatility_df.empty:
                vview = volatility_df[["Symbol", "Tier", "Score", "Price", "Vol Ratio", "NR7", "Inside Day", "Gate Status", "Invalidation %"]].head(12).copy()
                vview["Price"] = vview["Price"].apply(format_price)
                vview["Vol Ratio"] = vview["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
                vview["NR7"] = vview["NR7"].apply(lambda x: "Yes" if x else "-")
                vview["Inside Day"] = vview["Inside Day"].apply(lambda x: "Yes" if x else "-")
                vview["Invalidation %"] = vview["Invalidation %"].apply(lambda x: f"{x:.2f}%")
                st.dataframe(vview, width='stretch', hide_index=True)
            else:
                st.info("No volatility contraction setups today.")

            st.markdown("### 🧮 Score Decomposition (Top Combined)")
            dcols = [
                "Symbol", "Setup Type", "Tier", "Score", "Gate Status", "Quality Score",
                "Trend Align", "Vol Quality", "RS Stability", "RS Pct", "Vol Pct"
            ]
            if not combined.empty:
                dview = combined[dcols].sort_values("Score", ascending=False).head(20).copy()
                dview["Quality Score"] = dview["Quality Score"].apply(lambda x: f"{x:.2f}")
                dview["Trend Align"] = dview["Trend Align"].apply(lambda x: f"{x:.2f}")
                dview["Vol Quality"] = dview["Vol Quality"].apply(lambda x: f"{x:.2f}")
                dview["RS Stability"] = dview["RS Stability"].apply(lambda x: f"{x:.2f}")
                dview["RS Pct"] = dview["RS Pct"].apply(lambda x: f"{x:.2f}")
                dview["Vol Pct"] = dview["Vol Pct"].apply(lambda x: f"{x:.2f}")
                st.dataframe(dview, width='stretch', hide_index=True)

# ==================== FOOTER ====================
st.markdown("---")

footer_cols = st.columns([2, 1, 1])

with footer_cols[0]:
    st.caption(f"📊 Analyzing **{len(selected_stocks)}** stocks from **{selection_method}**")

with footer_cols[1]:
    st.caption(f"🕐 Updated: {datetime.now().strftime('%H:%M:%S')}")

with footer_cols[2]:
    st.caption("✅ Enhanced: VWAP | Tables | Better visuals")
