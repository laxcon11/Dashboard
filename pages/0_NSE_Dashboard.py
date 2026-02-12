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
    STOCK_CATEGORIES,
    PRESET_WATCHLISTS,
    NIFTY_200
)

from data_fetch import batch_download, extract_price_data
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
    watchlist_names = list(watchlists.keys())
    
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
        
        st.dataframe(nr7_df, use_container_width=True, hide_index=True)
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
            st.dataframe(df_above, use_container_width=True, hide_index=True)
        else:
            st.info("No stocks above VWAP")

    with col_right:
        st.markdown("#### 🔴 Below VWAP")
        if below_vwap_list:
            df_below = pd.DataFrame(below_vwap_list)
            df_below['Close'] = df_below['Close'].apply(lambda x: f"₹{x:.2f}")
            df_below['VWAP'] = df_below['VWAP'].apply(lambda x: f"₹{x:.2f}")
            st.dataframe(df_below, use_container_width=True, hide_index=True)
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
            st.dataframe(pd.DataFrame(ad_data), use_container_width=True, hide_index=True)
            
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
            st.plotly_chart(fig, use_container_width=True)

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
            except:
                st.metric("RSI (14)", "N/A")

        with col4:
            try:
                atr = calculate_atr(df, ATR_PERIOD).iloc[-1]
                stop_loss = price - (atr * ATR_MULTIPLIER) if price and atr else None
                st.metric("ATR Stop Loss", format_price(stop_loss) if stop_loss else "N/A")
            except:
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
            except:
                pass

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

    rankings_momentum = []
    rankings_pullback = []

    with st.spinner("Calculating strategy scores..."):
        for symbol in selected_stocks:
            df = watchlist_data.get(symbol)
            if df is not None and len(df) >= 20:
                try:
                    price, change, change_pct = get_live_price_safe(symbol, df)
                    vol_ratio = analytics.calculate_volume_ratio(df)
                    rs = analytics.calculate_relative_strength(df, nifty_df)
                    
                    # Calculate VWAP based on selected anchor
                    df_vwap = df.tail(vwap_days)
                    vwap = analytics.calculate_vwap(df_vwap)
                    vwap_value = vwap.iloc[-1] if vwap is not None else None
                    vwap_position = "Above" if (price and vwap_value and price > vwap_value) else "Below"
                    
                    # 1. Momentum Score
                    mom_score = analytics.calculate_momentum_score(df, nifty_df)
                    rankings_momentum.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'Score': mom_score,
                        'Price': price,
                        'Change %': change_pct,
                        'Vol Ratio': vol_ratio,
                        'RSI': calculate_rsi(df).iloc[-1] if len(df) > 14 else 0,
                        'Trend': 'Bullish' if calculate_ema(df, 20).iloc[-1] > calculate_ema(df, 50).iloc[-1] else 'Bearish'
                    })
                    
                    # 2. Pullback Score
                    pb_score = analytics.calculate_pullback_score(df, nifty_df)
                    rankings_pullback.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'Score': pb_score,
                        'Price': price,
                        'dist EMA20': f"{((price - calculate_ema(df, 20).iloc[-1])/calculate_ema(df, 20).iloc[-1]*100):.1f}%",
                        'RSI': calculate_rsi(df).iloc[-1] if len(df) > 14 else 0,
                        'Auto-Setup': 'NR7' if analytics.detect_nr7(df) else '-'
                    })

                except Exception as e:
                    logger.error(f"Error calculating score for {symbol}: {e}")

    # Combine and find Top 3 Overall
    all_setups = []
    
    # Process Momentum for Top 3
    for r in rankings_momentum:
        r['Setup Type'] = 'Momentum 🚀'
        all_setups.append(r)
        
    # Process Pullback for Top 3
    for r in rankings_pullback:
        r['Setup Type'] = 'Pullback 🛒'
        all_setups.append(r)
        
    # Sort by Score descending
    all_setups.sort(key=lambda x: x['Score'], reverse=True)
    top_3 = all_setups[:3]

    if top_3:
        st.markdown("### 🏆 Top 3 Swing Picks Today")
        top_cols = st.columns(3)
        
        for i, setup in enumerate(top_3):
            with top_cols[i]:
                # Color code score
                score = setup['Score']
                color = "green" if score >= 8 else "orange"
                
                with st.container(border=True):
                    st.markdown(f"#### {i+1}. {setup['Symbol']}")
                    st.markdown(f"**Score: :{color}[{score}/10]**")
                    st.caption(f"Strategy: {setup['Setup Type']}")
                    
                    st.divider()
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric("Price", format_price(setup['Price']))
                    with c2:
                         st.metric("RSI", f"{setup['RSI']:.1f}" if isinstance(setup['RSI'], (int, float)) else setup['RSI'])
                    
                    if setup['Setup Type'] == 'Momentum 🚀':
                        st.caption(f"Trend: {setup.get('Trend', 'N/A')}")
                    else:
                        st.caption(f"EMA20: {setup.get('dist EMA20', 'N/A')}")

    st.markdown("---")

    # Custom styling function for scores
    def style_score(v):
        try:
            val = float(v)
            if val >= 10:
                return 'background-color: #008000; color: white; font-weight: bold'  # Solid Green
            elif val >= 7:
                return 'background-color: #90EE90; color: black'  # Light Green
            else:
                return ''
        except:
            return ''

    # Display Momentum Rankings
    st.markdown("### 🚀 Momentum / Breakout Candidates")
    if rankings_momentum:
        mom_df = pd.DataFrame(rankings_momentum).sort_values(by='Score', ascending=False)
        mom_style = mom_df.copy() # Keep numeric for styling
        
        # Format for display
        mom_df['Price'] = mom_df['Price'].apply(lambda x: format_price(x) if x else 'N/A')
        mom_df['Change %'] = mom_df['Change %'].apply(lambda x: format_change(x) if x else 'N/A')
        mom_df['Vol Ratio'] = mom_df['Vol Ratio'].apply(lambda x: f"{x:.2f}x")
        mom_df['RSI'] = mom_df['RSI'].apply(lambda x: f"{x:.1f}")
        
        # Apply strict score styling
        st.dataframe(mom_df.style.map(style_score, subset=['Score']), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Display Pullback Rankings
    st.markdown("### 🛒 Pullback / Value Candidates")
    if rankings_pullback:
        pb_df = pd.DataFrame(rankings_pullback).sort_values(by='Score', ascending=False)
        
        pb_df['Price'] = pb_df['Price'].apply(lambda x: format_price(x) if x else 'N/A')
        pb_df['RSI'] = pb_df['RSI'].apply(lambda x: f"{x:.1f}")
        
        st.dataframe(pb_df.style.map(style_score, subset=['Score']), use_container_width=True, hide_index=True)


    if not rankings_momentum and not rankings_pullback:
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