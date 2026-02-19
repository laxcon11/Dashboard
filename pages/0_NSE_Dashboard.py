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
setup_page("Dashboard Launcher")

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

# ==================== SECTORAL VIEW - IMPROVED BAR CHART ====================
if mode != "Swing Rankings":
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

        # Smart Trade Planner
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
    r1.metric("Regime Filter", regime_label)
    r2.metric("A/D Breadth", f"{advances}:{declines}", f"{breadth_ratio:.2f}")
    r3.info(f"{regime_bias} | {swing_strictness}")

    raw_rows = []
    with st.spinner("Scoring candidates with regime and setup filters..."):
        for symbol in selected_stocks:
            df = watchlist_data.get(symbol)
            if df is None or len(df) < 60:
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
                trend_bull = bool(price > ema20 > ema50)
                breakout = analytics.detect_breakout(df)
                nr7 = analytics.detect_nr7(df)
                dist_ema20 = ((price - ema20) / ema20 * 100) if ema20 else 0

                # Stage A: must-have quality filters
                if vol_ratio < cfg["min_vol_ratio"]:
                    continue
                if rs < cfg["min_rs"]:
                    continue

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
                    "Mom Base": analytics.calculate_momentum_score(df, nifty_df),
                    "PB Base": analytics.calculate_pullback_score(df, nifty_df),
                })
            except Exception as e:
                logger.error(f"Error scoring {symbol}: {e}")

    if not raw_rows:
        st.warning("No stocks passed base quality filters. Relax filters or expand watchlist.")
        st.stop()

    score_df = pd.DataFrame(raw_rows)
    score_df["RS Pct"] = score_df["RS"].rank(pct=True).fillna(0.5)
    score_df["Vol Pct"] = score_df["Vol Ratio"].rank(pct=True).fillna(0.5)

    score_df["Momentum Score"] = score_df.apply(
        lambda r: clamp_score(
            (0.60 * r["Mom Base"]) +
            (3.0 * r["RS Pct"]) +
            (1.5 * r["Vol Pct"]) +
            (1.0 if r["Breakout"] else 0.0) +
            (1.0 if r["Trend"] == "Bullish" else -1.0) -
            max(0.0, r["dist_ema20"] - 6.0) * 0.25 +
            regime_adj
        ),
        axis=1
    )

    score_df["Pullback Score"] = score_df.apply(
        lambda r: clamp_score(
            (0.70 * r["PB Base"]) +
            (1.0 if 0 <= r["dist_ema20"] <= 4 else 0.0) +
            (1.0 if 40 <= r["RSI"] <= 55 else 0.0) +
            (1.5 * r["RS Pct"]) +
            (0.5 if r["NR7"] else 0.0) +
            (0.5 if r["Trend"] == "Bullish" else -0.5) +
            (regime_adj * 0.8)
        ),
        axis=1
    )

    score_df["Volatility Score"] = score_df.apply(
        lambda r: clamp_score(
            (3.0 if r["NR7"] else 0.0) +
            (2.0 if abs(r["dist_ema20"]) <= 2 else 0.0) +
            (2.0 * r["Vol Pct"]) +
            (1.0 if r["Breakout"] else 0.0) +
            (1.0 * r["RS Pct"]) +
            (regime_adj * 0.5)
        ),
        axis=1
    )

    def build_archetype(df, score_col, setup_name):
        temp = df.copy()
        temp["Score"] = temp[score_col].round(2)
        temp["Setup Type"] = setup_name
        temp["Tier"] = temp["Score"].apply(setup_tier)
        return temp.sort_values("Score", ascending=False)

    momentum_df = build_archetype(score_df, "Momentum Score", "Momentum 🚀")
    pullback_df = build_archetype(score_df, "Pullback Score", "Pullback 🛒")
    volatility_df = build_archetype(score_df, "Volatility Score", "Volatility Expansion 🌀")

    combined = pd.concat([momentum_df, pullback_df, volatility_df], ignore_index=True)
    actionable = combined[
        (combined["Tier"].isin(["A+", "A"])) &
        ((regime_label != "🔴 Risk Off") | (combined["Score"] >= cfg["risk_off_min_score"]))
    ].sort_values("Score", ascending=False).drop_duplicates(subset=["Symbol"]).head(cfg["top_n"])

    watchlist_candidates = combined[
        combined["Tier"].isin(["B"])
    ].sort_values("Score", ascending=False).drop_duplicates(subset=["Symbol"]).head(cfg["watchlist_n"])

    if not actionable.empty:
        st.markdown("### 🏆 Top Actionable Picks (A+/A)")
        top_cols = st.columns(len(actionable))
        for i, (_, row) in enumerate(actionable.iterrows()):
            with top_cols[i]:
                with st.container(border=True):
                    st.markdown(f"#### {i+1}. {row['Symbol']}")
                    st.caption(f"{row['Setup Type']} • Tier {row['Tier']}")
                    st.metric("Score", f"{row['Score']:.2f}/10")
                    st.metric("Price", format_price(row['Price']), format_change(row['Change %']))
                    st.caption(f"RSI: {row['RSI']:.1f} | Vol: {row['Vol Ratio']:.2f}x")

                    sym = row['Symbol']
                    prefill_symbol = sym if sym.endswith(".NS") else f"{sym}.NS"
                    if st.button("Log Setup", key=f"log_setup_new_{i}_{sym}", width='stretch'):
                        st.session_state["journal_prefill"] = {
                            "symbol": prefill_symbol,
                            "strategy": "Swing Ranking",
                            "side": "LONG",
                        }
                        st.switch_page("pages/5_Trading_Journal.py")
    else:
        st.info("No A+/A setups today under current filters and regime gate.")

    if not watchlist_candidates.empty:
        st.markdown("### 👀 Watchlist Candidates (B Tier)")
        wl = watchlist_candidates[["Symbol", "Setup Type", "Score", "Price", "Change %", "RS", "Vol Ratio", "RSI"]].copy()
        wl["Price"] = wl["Price"].apply(format_price)
        wl["Change %"] = wl["Change %"].apply(format_change)
        wl["Vol Ratio"] = wl["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
        wl["RSI"] = wl["RSI"].apply(lambda x: f"{x:.1f}")
        st.dataframe(wl, width='stretch', hide_index=True)

    st.markdown("---")
    st.markdown("### 🚀 Momentum Candidates")
    mview = momentum_df[["Symbol", "Tier", "Score", "Price", "Change %", "Vol Ratio", "RSI", "Trend"]].head(12).copy()
    mview["Price"] = mview["Price"].apply(format_price)
    mview["Change %"] = mview["Change %"].apply(format_change)
    mview["Vol Ratio"] = mview["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
    mview["RSI"] = mview["RSI"].apply(lambda x: f"{x:.1f}")
    st.dataframe(mview, width='stretch', hide_index=True)

    st.markdown("### 🛒 Pullback Candidates")
    pview = pullback_df[["Symbol", "Tier", "Score", "Price", "RSI", "dist_ema20", "Trend", "NR7"]].head(12).copy()
    pview["Price"] = pview["Price"].apply(format_price)
    pview["RSI"] = pview["RSI"].apply(lambda x: f"{x:.1f}")
    pview["dist_ema20"] = pview["dist_ema20"].apply(lambda x: f"{x:.1f}%")
    pview["NR7"] = pview["NR7"].apply(lambda x: "Yes" if x else "-")
    st.dataframe(pview, width='stretch', hide_index=True)

    st.markdown("### 🌀 Volatility Expansion Candidates")
    vview = volatility_df[["Symbol", "Tier", "Score", "Price", "Vol Ratio", "NR7", "Breakout"]].head(12).copy()
    vview["Price"] = vview["Price"].apply(format_price)
    vview["Vol Ratio"] = vview["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
    vview["NR7"] = vview["NR7"].apply(lambda x: "Yes" if x else "-")
    vview["Breakout"] = vview["Breakout"].apply(lambda x: "Yes" if x else "-")
    st.dataframe(vview, width='stretch', hide_index=True)

# ==================== FOOTER ====================
st.markdown("---")

footer_cols = st.columns([2, 1, 1])

with footer_cols[0]:
    st.caption(f"📊 Analyzing **{len(selected_stocks)}** stocks from **{selection_method}**")

with footer_cols[1]:
    st.caption(f"🕐 Updated: {datetime.now().strftime('%H:%M:%S')}")

with footer_cols[2]:
    st.caption("✅ Enhanced: VWAP | Tables | Better visuals")
