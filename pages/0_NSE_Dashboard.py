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
import time
import importlib.util

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
    GIFT_NIFTY_DASHBOARD_CARD,
    GIFT_NIFTY_SESSION_START_IST_HOUR,
    GIFT_NIFTY_COLLAPSE_IST_HOUR,
    EODHD_API_KEY,
    FINNHUB_API_KEY,
)
from gift_nifty import get_gift_nifty_snapshot, is_gift_session_active
from trading_calendar import is_nse_trading_day

# Import NSE-specific config
from NSE_Config import (
    NSE_SECTOR_INDICES,
    SECTOR_CATEGORIES,
    THEMATIC_CATEGORIES,
    PRESET_WATCHLISTS,
    NIFTY_200
)

from data_fetch import (
    batch_download,
    extract_price_data,
    get_last_batch_telemetry,
    fetch_equity_fundamentals,
)
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
    render_decision_header,
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
_page_t0 = time.perf_counter()
_perf: dict[str, float] = {}

st.title("🚀 NSE Dashboard Launcher")
st.caption("Advanced swing trading analysis for Indian markets - NIFTY 200 Coverage")
render_decision_header(source="macro_ssot")

if GIFT_NIFTY_DASHBOARD_CARD and is_gift_session_active(
    session_start_hour=GIFT_NIFTY_SESSION_START_IST_HOUR,
    cutoff_hour=GIFT_NIFTY_COLLAPSE_IST_HOUR,
):
    prev_close = None
    try:
        pre_mkt = batch_download(["^NSEI"], period="5d")
        nd = pre_mkt.get("^NSEI")
        if nd is not None and not nd.empty and "Close" in nd.columns:
            close = pd.to_numeric(nd["Close"], errors="coerce").dropna()
            if len(close) >= 1:
                prev_close = float(close.iloc[-1])
    except Exception:
        prev_close = None

    gift = get_gift_nifty_snapshot(prev_nifty_close=prev_close)
    with st.expander(
        "🧭 GIFT NIFTY Pre-Open Context",
        expanded=True,
    ):
        if not gift.get("available", False):
            st.info("GIFT NIFTY feed unavailable. Configure API/local snapshot source first.")
        else:
            g1, g2, g3, g4 = st.columns(4)
            with g1:
                st.metric("GIFT NIFTY", f"{float(gift.get('price')):,.2f}", None if gift.get("change_pct") is None else f"{float(gift.get('change_pct')):+.2f}%")
            with g2:
                prem = gift.get("premium_pct_vs_prev_close")
                st.metric("Premium/Discount vs Prev Close", "N/A" if prem is None else f"{float(prem):+.2f}%")
            with g3:
                st.metric("Implied Gap", str(gift.get("implied_label", "Unknown")))
            with g4:
                delay_min = gift.get("delay_min")
                st.metric("Feed Delay", "N/A" if delay_min is None else f"{float(delay_min):.0f} min")
            st.caption(
                f"Source: {gift.get('source', 'N/A')} | As of: {gift.get('as_of_ist', 'N/A')} | "
                f"Mode: {gift.get('delay_note', 'unknown')} | {gift.get('note', '')}"
            )
            if gift.get("unverified", False):
                st.warning("GIFT source is scrape-based (unverified). Treat as directional context only.")
            if gift.get("quality_note"):
                st.caption(f"Normalization: {gift.get('quality_note')}")
            st.caption(
                f"Active window: {int(GIFT_NIFTY_SESSION_START_IST_HOUR):02d}:00 IST to "
                f"{int(GIFT_NIFTY_COLLAPSE_IST_HOUR):02d}:00 IST (next day)."
            )

# Helper functions have been moved to analytics.py


# ==================== SIDEBAR - STOCK SELECTION ====================
st.sidebar.header("📊 Stock Selection")

selection_method = st.sidebar.radio(
    "Selection Method",
    ["Preset Watchlists", "By Category", "Custom Selection"],
    help="Choose how to select stocks"
)

selected_stocks = []
preset = ""
category = ""

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

st.sidebar.markdown("---")
st.sidebar.header("📎 RS Benchmark")
rs_benchmark_mode = st.sidebar.selectbox(
    "Relative Strength vs",
    ["NIFTY 50", "Sector Index (if mapped)"],
    index=0,
    help="Use sector benchmark when available; otherwise fallback to NIFTY 50.",
)

# ==================== FETCH DATA ====================
if not selected_stocks:
    st.warning("⚠️ Please select at least one stock from the sidebar")
    st.stop()

with st.spinner(f"📊 Fetching data for {len(selected_stocks)} stocks..."):
    _t_fetch = time.perf_counter()
    index_symbols = list(MAIN_INDICES.keys())
    sector_symbols = list(NSE_SECTOR_INDICES.keys())
    all_symbols = sorted(set(index_symbols + sector_symbols + selected_stocks))

    # Single batched pull is faster than multiple overlapping network/cache calls.
    merged_data = batch_download(all_symbols, period="3mo")
    index_data = {s: merged_data.get(s) for s in index_symbols}
    sector_data = {s: merged_data.get(s) for s in sector_symbols}
    watchlist_data = {s: merged_data.get(s) for s in selected_stocks}
    _perf["data_fetch_s"] = round(time.perf_counter() - _t_fetch, 3)

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
_t_mode = time.perf_counter()

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
                vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=True)
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
            vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=True)
            
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
            vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=True)
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

        with st.expander("🏛️ Fundamentals (EODHD/Finnhub)", expanded=False):
            if not FINNHUB_API_KEY and not EODHD_API_KEY:
                st.caption("No fundamentals provider configured (set EODHD_API_KEY and/or FINNHUB_API_KEY).")
            elif FINNHUB_API_KEY and importlib.util.find_spec("finnhub") is None and not EODHD_API_KEY:
                st.caption("finnhub-python not installed in active environment.")
            else:
                f = fetch_equity_fundamentals(
                    selected_stock,
                    finnhub_api_key=FINNHUB_API_KEY,
                    eodhd_api_key=EODHD_API_KEY,
                )
                if not f:
                    st.caption("Fundamentals unavailable for this symbol right now.")
                else:
                    fc1, fc2, fc3, fc4 = st.columns(4)
                    with fc1:
                        pe = f.get("peBasicExclExtraTTM")
                        st.metric("P/E", "N/A" if pe is None else f"{float(pe):.2f}")
                    with fc2:
                        eps = f.get("epsBasicExclExtraItemsTTM")
                        st.metric("EPS (TTM)", "N/A" if eps is None else f"{float(eps):.2f}")
                    with fc3:
                        beta = f.get("beta")
                        st.metric("Beta", "N/A" if beta is None else f"{float(beta):.2f}")
                    with fc4:
                        de = f.get("debtEquityAnnual")
                        st.metric("Debt/Equity", "N/A" if de is None else f"{float(de):.2f}")

        # Smart Trade Planner (moved below chart section)
        st.markdown("---")
        with st.expander("🛡️ Smart Trade Planner (Risk/Reward Calculator)", expanded=False):
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
            "rs_floor_penalty": 0.15,
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
            "rs_floor_penalty": 0.10,
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
            "rs_floor_penalty": 0.08,
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

    def rs_spread_ema3(symbol_df, benchmark_df) -> float:
        if symbol_df is None or benchmark_df is None:
            return 0.0
        if "Close" not in symbol_df.columns or "Close" not in benchmark_df.columns:
            return 0.0
        s_close = pd.to_numeric(symbol_df["Close"], errors="coerce").dropna()
        b_close = pd.to_numeric(benchmark_df["Close"], errors="coerce").dropna()
        merged = pd.concat([s_close.rename("s"), b_close.rename("b")], axis=1).dropna()
        if len(merged) < 8:
            return 0.0
        spread = (merged["s"].pct_change() - merged["b"].pct_change()) * 100.0
        spread = spread.dropna()
        if spread.empty:
            return 0.0
        return float(spread.ewm(span=3, adjust=False).mean().iloc[-1])

    sector_name_to_index = {v: k for k, v in NSE_SECTOR_INDICES.items()}
    stock_to_sector = {}
    for sector_label, members in SECTOR_CATEGORIES.items():
        clean_sector = sector_label.split(" ", 1)[-1] if " " in sector_label else sector_label
        for s in members:
            stock_to_sector[s] = clean_sector

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

    def recent_swing_low(series_low, lookback=20):
        if series_low is None:
            return np.nan
        s = pd.to_numeric(series_low, errors="coerce").dropna()
        if s.empty:
            return np.nan
        return float(s.tail(lookback).min())

    def momentum_leg_low(close_series, ema_series, low_series, fallback_lookback=20):
        c = pd.to_numeric(close_series, errors="coerce")
        e = pd.to_numeric(ema_series, errors="coerce")
        l = pd.to_numeric(low_series, errors="coerce")
        df_leg = pd.concat([c.rename("c"), e.rename("e"), l.rename("l")], axis=1).dropna()
        if len(df_leg) < 5:
            return recent_swing_low(low_series, lookback=fallback_lookback)
        start_idx = None
        vals_c = df_leg["c"].values
        vals_e = df_leg["e"].values
        for i in range(len(df_leg) - 2, 2, -1):
            # Start leg on EMA20 reclaim only after at least 2 bars below EMA20.
            if (vals_c[i - 2] <= vals_e[i - 2]) and (vals_c[i - 1] <= vals_e[i - 1]) and (vals_c[i] > vals_e[i]):
                start_idx = i
                break
        if start_idx is None:
            return recent_swing_low(low_series, lookback=fallback_lookback)
        leg_low = df_leg["l"].iloc[start_idx:].min()
        if pd.isna(leg_low):
            return recent_swing_low(low_series, lookback=fallback_lookback)
        return float(leg_low)

    def pullback_leg_low(df_local):
        if df_local is None or df_local.empty or "High" not in df_local.columns or "Low" not in df_local.columns:
            return np.nan
        highs = pd.to_numeric(df_local["High"], errors="coerce")
        lows = pd.to_numeric(df_local["Low"], errors="coerce")
        w = min(25, len(df_local))
        if w < 5:
            return float(lows.dropna().tail(10).min()) if not lows.dropna().empty else np.nan
        high_window = highs.tail(w)
        if high_window.dropna().empty:
            return float(lows.dropna().tail(10).min()) if not lows.dropna().empty else np.nan
        high_idx = high_window.idxmax()
        leg_lows = lows.loc[high_idx:]
        leg_lows = leg_lows.dropna()
        if leg_lows.empty:
            return float(lows.dropna().tail(10).min()) if not lows.dropna().empty else np.nan
        return float(leg_lows.min())

    def prior_support_below(series_low, anchor, bars=60):
        s = pd.to_numeric(series_low, errors="coerce").dropna().tail(bars)
        if len(s) < 7 or pd.isna(anchor):
            return np.nan
        candidates = []
        vals = s.values
        for i in range(2, len(vals) - 2):
            v = vals[i]
            if v < vals[i - 1] and v < vals[i + 1] and v < vals[i - 2] and v < vals[i + 2]:
                if v < anchor:
                    candidates.append(v)
        if not candidates:
            return np.nan
        return float(max(candidates))

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
    with st.expander("📐 Invalidation v2.2 Assumption Spec", expanded=False):
        st.markdown(
            "- Momentum leg starts at latest close reclaim above EMA20 after at least 2 bars below EMA20.\n"
            "- Momentum consolidation does not reset anchor unless a close below EMA20 occurs.\n"
            "- Prior support uses 2-left/2-right pivot lows from last 60 bars; highest pivot below pullback anchor (conservative).\n"
            "- Pivot lag: 2-right confirmation means the newest confirmed pivot is at least 2 bars old.\n"
            "- ATR regime is per-symbol: current ATR14 versus the same symbol's last 60 ATR14 values, computed on latest daily snapshot.\n"
            "- Gap trigger buffers are setup-specific: Momentum 0.25 ATR, Pullback 0.20 ATR, Volatility 0.10 ATR.\n"
            "- Time-stop clock starts on the next trading bar after entry."
        )

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

                vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=True)
                benchmark_df = nifty_df
                benchmark_label = "NIFTY 50"
                if rs_benchmark_mode == "Sector Index (if mapped)":
                    sector_name = stock_to_sector.get(symbol)
                    sector_idx_symbol = sector_name_to_index.get(sector_name, "") if sector_name else ""
                    sector_idx_df = sector_data.get(sector_idx_symbol) if sector_idx_symbol else None
                    if sector_idx_df is not None and not sector_idx_df.empty:
                        benchmark_df = sector_idx_df
                        benchmark_label = sector_name
                rs = analytics.calculate_relative_strength(df, benchmark_df, period=20)
                rs_ema3 = rs_spread_ema3(df, benchmark_df)
                rsi = calculate_rsi(df).iloc[-1] if len(df) > 14 else np.nan
                ema20_series = calculate_ema(df, 20)
                ema20 = ema20_series.iloc[-1]
                ema50 = calculate_ema(df, 50).iloc[-1]
                atr_series = calculate_atr(df, ATR_PERIOD) if len(df) > ATR_PERIOD else pd.Series(dtype=float)
                atr14 = atr_series.iloc[-1] if len(atr_series) > 0 else np.nan
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
                low_series = df["Low"] if "Low" in df.columns else close
                mom_leg_low = momentum_leg_low(close, ema20_series, low_series, fallback_lookback=20)
                pb_leg_low = pullback_leg_low(df)
                prior_support = prior_support_below(low_series, pb_leg_low, bars=60)
                range_series = (pd.to_numeric(df["High"], errors="coerce") - pd.to_numeric(df["Low"], errors="coerce")).dropna() if {"High", "Low"}.issubset(df.columns) else pd.Series(dtype=float)
                if not range_series.empty:
                    tight_idx = range_series.tail(10).idxmin()
                    tight_bar_low = pd.to_numeric(df.loc[tight_idx, "Low"], errors="coerce")
                else:
                    tight_bar_low = np.nan
                contraction_range_low = pd.to_numeric(low_series, errors="coerce").tail(7).min() if len(low_series) >= 7 else np.nan
                atr_buffer_q = (0.25 * atr14) if pd.notna(atr14) and atr14 > 0 else 0.0
                atr_buffer_h = (0.50 * atr14) if pd.notna(atr14) and atr14 > 0 else 0.0
                atr_buffer_m = (0.75 * atr14) if pd.notna(atr14) and atr14 > 0 else 0.0
                atr_recent = pd.to_numeric(atr_series, errors="coerce").dropna().tail(60) if len(atr_series) > 0 else pd.Series(dtype=float)
                atr_adj = 0
                if len(atr_recent) >= 20:
                    q25 = float(atr_recent.quantile(0.25))
                    q75 = float(atr_recent.quantile(0.75))
                    if atr14 >= q75:
                        atr_adj = -1
                    elif atr14 <= q25:
                        atr_adj = 1

                inv_momentum = max(
                    [x for x in [mom_leg_low, (ema20 - atr_buffer_m)] if pd.notna(x)]
                ) if (pd.notna(mom_leg_low) or pd.notna(ema20)) else low10

                pb_anchor = pb_leg_low if pd.notna(pb_leg_low) else low10
                pb_candidate = pb_anchor - atr_buffer_q
                ps_candidate = (prior_support - atr_buffer_q) if pd.notna(prior_support) else np.nan
                inv_pullback = max([x for x in [pb_candidate, ps_candidate] if pd.notna(x)]) if pd.notna(ps_candidate) else pb_candidate

                contraction_anchor_candidates = [x for x in [contraction_range_low, tight_bar_low] if pd.notna(x)]
                if contraction_anchor_candidates:
                    inv_volatility = min(contraction_anchor_candidates) - atr_buffer_h
                else:
                    inv_volatility = (low20 - atr_buffer_h) if pd.notna(low20) else low20

                mom_time_stop = max(2, 5 + atr_adj)
                pb_time_stop = max(3, 7 + atr_adj)
                vol_time_stop = max(2, 4 + atr_adj)

                rel_std = np.nan
                if benchmark_df is not None and "Close" in benchmark_df.columns:
                    merged = pd.concat(
                        [close.rename("s"), benchmark_df["Close"].dropna().rename("b")],
                        axis=1
                    ).dropna()
                    if len(merged) >= 30:
                        rel_ret = merged["s"].pct_change() - merged["b"].pct_change()
                        rel_std = rel_ret.tail(20).std()

                trend_align = 1.0 if trend_bull else 0.0
                vol_quality = clip01(vol_ratio / 2.0)
                rs_blend = (0.7 * rs) + (0.3 * rs_ema3)
                if rs >= 2.0 and rs_ema3 >= 0:
                    rs_tier = "Strong"
                elif rs <= -1.0 or rs_ema3 < -0.2:
                    rs_tier = "Weak"
                else:
                    rs_tier = "Neutral"

                # Strict setup families
                momentum_pass = bool(trend_bull and breakout and (vol_ratio >= 1.0) and (rsi >= 52) and (rsi <= 78))
                pullback_pass = bool(trend_bull and (-2.5 <= dist_ema20 <= 1.5) and (40 <= rsi <= 58) and (not breakout))
                vol_contract_pass = bool(nr7 and inside_day and (abs(dist_ema20) <= 4.0) and (pd.isna(atr_pct) or atr_pct <= 4.0))

                hard_gate_pass = bool(regime_gate_pass and liquidity_gate_pass)
                gate_reason = "OK" if hard_gate_pass else ("Regime" if not regime_gate_pass else "Liquidity")

                raw_rows.append({
                    "Symbol": symbol.replace('.NS', ''),
                    "Price": price,
                    "Change %": change_pct,
                    "RS": rs,
                    "RS EMA3": rs_ema3,
                    "RS Tier": rs_tier,
                    "RS Benchmark": benchmark_label,
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
                    "RS RelStd": rel_std,
                    "RS Blend": rs_blend,
                    "RS Stability": 0.5,
                    "RS Quality": 0.5,
                    "RS Floor Penalty": 0.0,
                    "Quality Score Base": 0.0,
                    "Quality Score": 0.0,
                    "Quality Band": "Blocked",
                    "Quality Gate": False,
                    "Regime Gate": regime_gate_pass,
                    "Liquidity Gate": liquidity_gate_pass,
                    "Hard Gate": hard_gate_pass,
                    "Gate Reason": gate_reason,
                    "Momentum Pass": momentum_pass,
                    "Pullback Pass": pullback_pass,
                    "Volatility Pass": vol_contract_pass,
                    "Mom Base": analytics.calculate_momentum_score(df, nifty_df),
                    "PB Base": analytics.calculate_pullback_score(df, nifty_df),
                    "Inv Momentum": inv_momentum,
                    "Inv Pullback": inv_pullback,
                    "Inv Volatility": inv_volatility,
                    "Inv Rule Momentum": "max(momentum_leg_low, ema20 - 0.75*ATR14)",
                    "Inv Rule Pullback": "max(pullback_leg_low - 0.25*ATR14, prior_support - 0.25*ATR14)",
                    "Inv Rule Volatility": "contraction_low - 0.50*ATR14",
                    "Inv Detail Momentum": f"max(ML {mom_leg_low:.2f}, EMA20 {ema20:.2f} - 0.75*ATR {atr14:.2f})",
                    "Inv Detail Pullback": (
                        f"max(PL {pb_anchor:.2f} - 0.25*ATR {atr14:.2f}, "
                        + (f"PS {prior_support:.2f} - 0.25*ATR {atr14:.2f})" if pd.notna(prior_support) else "PS n/a)")
                    ),
                    "Inv Detail Volatility": (
                        f"min(CR {contraction_range_low:.2f}, TB {tight_bar_low:.2f}) - 0.50*ATR {atr14:.2f}"
                        if contraction_anchor_candidates else f"L20 {low20:.2f} - 0.50*ATR {atr14:.2f}"
                    ),
                    "ML": mom_leg_low,
                    "LTP vs ML %": (((price - mom_leg_low) / mom_leg_low) * 100.0) if pd.notna(mom_leg_low) and mom_leg_low > 0 else np.nan,
                    "Time Stop Momentum": mom_time_stop,
                    "Time Stop Pullback": pb_time_stop,
                    "Time Stop Volatility": vol_time_stop,
                })
            except Exception as e:
                logger.error(f"Error scoring {symbol}: {e}")

    if not raw_rows:
        st.warning("No stocks had enough data for setup-family scoring.")
        st.stop()

    score_df = pd.DataFrame(raw_rows)
    rel_std_series = pd.to_numeric(score_df.get("RS RelStd"), errors="coerce").dropna()
    if len(rel_std_series) >= 20:
        q10 = float(rel_std_series.quantile(0.10))
        q50 = float(rel_std_series.quantile(0.50))
        q90 = float(rel_std_series.quantile(0.90))
        denom = max(q90 - q10, 1e-6)
        rs_stab_slope = 0.8 / denom
        rs_stab_intercept = 0.9 + (rs_stab_slope * q10)
    else:
        q10, q50, q90 = np.nan, np.nan, np.nan
        rs_stab_slope = 35.0
        rs_stab_intercept = 1.0

    score_df["RS Stability"] = (
        rs_stab_intercept - (rs_stab_slope * pd.to_numeric(score_df["RS RelStd"], errors="coerce"))
    ).clip(lower=0.0, upper=1.0).fillna(0.5)
    score_df["RS Quality"] = ((
        pd.to_numeric(score_df["RS Blend"], errors="coerce").fillna(0.0) + 10.0
    ) / 20.0).clip(lower=0.0, upper=1.0)
    score_df["Quality Score Base"] = (
        (0.40 * pd.to_numeric(score_df["Vol Quality"], errors="coerce").fillna(0.0)) +
        (0.30 * score_df["RS Quality"]) +
        (0.30 * score_df["RS Stability"])
    )
    rs_floor_penalty = float(cfg.get("rs_floor_penalty", 0.10))
    score_df["RS Floor Penalty"] = np.where(
        pd.to_numeric(score_df["RS Blend"], errors="coerce").fillna(0.0) < float(cfg.get("min_rs", -3.0)),
        rs_floor_penalty,
        0.0,
    )
    score_df["Quality Score"] = (score_df["Quality Score Base"] - score_df["RS Floor Penalty"]).clip(lower=0.0, upper=1.0)
    score_df["Quality Band"] = np.where(
        score_df["Quality Score"] >= 0.65,
        "Strong",
        np.where(score_df["Quality Score"] >= 0.45, "Pass-Caution", "Blocked"),
    )
    score_df["Quality Gate"] = (
        (pd.to_numeric(score_df["Vol Ratio"], errors="coerce").fillna(0.0) >= float(cfg["min_vol_ratio"])) &
        (score_df["Quality Score"] >= 0.45)
    )
    score_df["Setup Any Pass"] = (
        score_df["Momentum Pass"].astype(bool) |
        score_df["Pullback Pass"].astype(bool) |
        score_df["Volatility Pass"].astype(bool)
    )
    score_df["Hard Gate"] = (
        score_df["Regime Gate"].astype(bool) &
        score_df["Liquidity Gate"].astype(bool) &
        score_df["Quality Gate"].astype(bool)
    )
    def _gate_reason(row):
        reasons = []
        if not bool(row.get("Regime Gate", False)):
            reasons.append("Regime")
        if not bool(row.get("Liquidity Gate", False)):
            reasons.append("Liquidity")
        if not bool(row.get("Quality Gate", False)):
            reasons.append("Quality")
        return "OK" if not reasons else ", ".join(reasons)
    score_df["Gate Reason"] = score_df.apply(_gate_reason, axis=1)
    def _near_miss_reason(row):
        dist = float(row.get("dist_ema20", 0.0))
        if bool(row.get("Trend") == "Bullish") and (not bool(row.get("Breakout"))):
            return "Momentum not confirmed (no breakout)"
        if dist > 1.5:
            return f"Pullback not ready (too extended: {dist:.2f}% above EMA20)"
        if dist < -2.5:
            return f"Pullback not ready (too deep: {dist:.2f}% below EMA20)"
        if (not bool(row.get("NR7"))) or (not bool(row.get("Inside Day"))):
            return "Contraction pattern not formed (NR7/Inside Day missing)"
        return "Setup conditions not aligned yet"
    score_df["Near Miss Reason"] = score_df.apply(_near_miss_reason, axis=1)

    with st.expander("🧪 Quality Diagnostics (RS Stability Calibration)", expanded=False):
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("rel_std p10", f"{q10:.4f}" if pd.notna(q10) else "n/a")
        d2.metric("rel_std p50", f"{q50:.4f}" if pd.notna(q50) else "n/a")
        d3.metric("rel_std p90", f"{q90:.4f}" if pd.notna(q90) else "n/a")
        d4.metric("Stability Slope", f"{rs_stab_slope:.2f}")
        band_counts = score_df["Quality Band"].value_counts()
        st.caption(
            f"Bands → Strong: {int(band_counts.get('Strong', 0))} | "
            f"Pass-Caution: {int(band_counts.get('Pass-Caution', 0))} | "
            f"Blocked: {int(band_counts.get('Blocked', 0))}"
        )
        st.caption(
            f"Soft RS floor: min_rs={cfg.get('min_rs')} | penalty={rs_floor_penalty:.2f} "
            f"(applied when RS blend < min_rs)."
        )

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
        if setup_name.startswith("Momentum"):
            temp["Invalidation Rule"] = temp["Inv Rule Momentum"]
            temp["Time Stop (bars)"] = temp["Time Stop Momentum"]
            temp["Invalidation Detail"] = temp["Inv Detail Momentum"]
            temp["Gap Buffer (ATR)"] = 0.25
        elif setup_name.startswith("Pullback"):
            temp["Invalidation Rule"] = temp["Inv Rule Pullback"]
            temp["Time Stop (bars)"] = temp["Time Stop Pullback"]
            temp["Invalidation Detail"] = temp["Inv Detail Pullback"]
            temp["Gap Buffer (ATR)"] = 0.20
        else:
            temp["Invalidation Rule"] = temp["Inv Rule Volatility"]
            temp["Time Stop (bars)"] = temp["Time Stop Volatility"]
            temp["Invalidation Detail"] = temp["Inv Detail Volatility"]
            temp["Gap Buffer (ATR)"] = 0.10
        temp["Trigger Type"] = temp["Gap Buffer (ATR)"].map(
            lambda b: f"Close < Invalidation | Gap Open < Inv - {b:.2f}*ATR => Immediate"
        )
        temp["Invalidation %"] = ((temp["Price"] - temp["Invalidation"]) / temp["Price"] * 100).round(2)
        temp["Risk (ATR)"] = np.where(
            pd.to_numeric(temp["ATR%"], errors="coerce") > 0,
            ((temp["Price"] - temp["Invalidation"]) / ((temp["ATR%"] / 100.0) * temp["Price"])).round(2),
            np.nan
        )
        temp["Gate Status"] = np.where(temp["Hard Gate"], "Pass", "Blocked")
        return temp.sort_values(
            ["Score", "Quality Score", "Trend Align", "Vol Quality", "RS Stability", "RS"],
            ascending=[False, False, False, False, False, False]
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
        ["Score", "Quality Score", "Trend Align", "Vol Quality", "RS Stability"],
        ascending=[False, False, False, False, False]
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
                        risk_atr_txt = f"{row['Risk (ATR)']:.2f} ATR" if pd.notna(row.get("Risk (ATR)")) else "ATR n/a"
                        st.caption(
                            f"Invalidation: {format_price(row['Invalidation'])} "
                            f"({row['Invalidation %']:.2f}% | {risk_atr_txt})"
                        )
                        st.caption(str(row.get("Invalidation Detail", row.get("Invalidation Rule", ""))))
                        st.caption(f"Trigger: {row.get('Trigger Type', 'Close < Invalidation')} | Time Stop: {int(row.get('Time Stop (bars)', 0))} bars")
                        st.caption(
                            f"RS20: {float(row.get('RS', 0.0)):+.2f} | "
                            f"RS EMA3: {float(row.get('RS EMA3', 0.0)):+.2f} | "
                            f"Tier: {row.get('RS Tier', 'Neutral')} vs {row.get('RS Benchmark', 'NIFTY 50')}"
                        )
                        st.caption(
                            f"Quality: {float(row.get('Quality Score', 0.0)):.2f} "
                            f"({row.get('Quality Band', 'Blocked')}) | RS floor penalty: {float(row.get('RS Floor Penalty', 0.0)):.2f}"
                        )
                        if pd.notna(row.get("ML")) and row.get("ML", 0) > 0:
                            run_abs = float(row["Price"]) - float(row["ML"])
                            st.caption(f"Run-up from ML: {run_abs:+.2f} ({float(row.get('LTP vs ML %', 0.0)):+.2f}%)")
                        sym = row['Symbol']
                        prefill_symbol = sym if sym.endswith(".NS") else f"{sym}.NS"
                        setup_label = str(row.get("Setup Type", "Swing Ranking"))
                        if setup_label.startswith("Momentum"):
                            pre_setup_family = "Momentum"
                        elif setup_label.startswith("Pullback"):
                            pre_setup_family = "Pullback"
                        elif setup_label.startswith("Volatility"):
                            pre_setup_family = "Volatility Contraction"
                        else:
                            pre_setup_family = "Other"
                        if st.button("Log Setup", key=f"log_setup_toprank_{i}_{sym}", width='stretch'):
                            st.session_state["journal_prefill"] = {
                                "symbol": prefill_symbol,
                                "strategy": "Swing Ranking",
                                "side": "LONG",
                                "setup_family": pre_setup_family,
                                "entry_price": float(row.get("Price", 0.0) or 0.0),
                                "stop_loss": float(row.get("Invalidation", 0.0) or 0.0),
                                "invalidation": float(row.get("Invalidation", 0.0) or 0.0),
                                "entry_risk_atr": float(row.get("Risk (ATR)", 0.0) or 0.0),
                                "target_price": 0.0,
                                "trigger_policy": str(row.get("Trigger Type", "")),
                                "notes": (
                                    f"Auto from Swing: {setup_label} | "
                                    f"Score {float(row.get('Score', 0.0)):.2f} | "
                                    f"Trigger: {row.get('Trigger Type', '')}"
                                ),
                            }
                            st.switch_page("pages/5_Trading_Journal.py")

    actionable = combined[
        (combined["Tier"].isin(["A+", "A"])) &
        (combined["Hard Gate"])
    ].drop_duplicates(subset=["Symbol", "Setup Type"]).sort_values(
        ["Score", "Quality Score", "Trend Align", "Vol Quality", "RS Stability"],
        ascending=[False, False, False, False, False]
    ).head(cfg["top_n"])

    monitor = combined[
        (combined["Tier"].isin(["A+", "A", "B"])) &
        (~combined["Hard Gate"] | combined["Tier"].eq("B"))
    ].drop_duplicates(subset=["Symbol", "Setup Type"]).sort_values(
        ["Score", "Quality Score", "Trend Align", "Vol Quality", "RS Stability"],
        ascending=[False, False, False, False, False]
    ).head(cfg["watchlist_n"])

    # -------------------- Tradable Lookback (20D) --------------------
    tradable_today = combined[
        (combined["Tier"].isin(["A+", "A"])) & (combined["Hard Gate"])
    ].drop_duplicates(subset=["Symbol", "Setup Type"]).copy()
    source_category_label = "Sector: Unassigned"
    if selection_method == "Custom Selection":
        source_category_label = "Custom Selection"
    elif selection_method == "Preset Watchlists" and preset:
        source_category_label = f"Preset: {preset}"
    elif selection_method == "By Category" and category:
        source_category_label = f"Sector: {category}"

    snapshot_cols = [
        "date", "symbol", "setup_type", "tier", "score", "quality_score",
        "quality_band", "regime", "liquidity", "category_label"
    ]
    snapshot_path = Path("data/snapshots/tradable_signals.parquet")
    snapshot_meta_path = Path("data/snapshots/tradable_signals_meta.json")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    run_date = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    # Always persist run heartbeat, even when no A+/A hard-gate pass rows exist.
    try:
        snapshot_meta_path.write_text(
            json.dumps(
                {
                    "last_run_date": str(run_date.date()),
                    "rows_written_today": int(len(tradable_today)),
                    "updated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
                },
                indent=2,
            )
        )
    except Exception:
        pass
    if not tradable_today.empty:
        snap = pd.DataFrame({
            "date": run_date,
            "symbol": tradable_today["Symbol"].astype(str),
            "setup_type": tradable_today["Setup Type"].astype(str),
            "tier": tradable_today["Tier"].astype(str),
            "score": pd.to_numeric(tradable_today["Score"], errors="coerce").fillna(0.0),
            "quality_score": pd.to_numeric(tradable_today["Quality Score"], errors="coerce").fillna(0.0),
            "quality_band": tradable_today["Quality Band"].astype(str),
            "regime": regime_label,
            "liquidity": liquidity_label,
            "category_label": source_category_label,
        })[snapshot_cols]
        if snapshot_path.exists():
            try:
                hist_all = pd.read_parquet(snapshot_path)
            except Exception:
                hist_all = pd.DataFrame(columns=snapshot_cols)
        else:
            hist_all = pd.DataFrame(columns=snapshot_cols)
        hist_all = pd.concat([hist_all, snap], ignore_index=True)
        hist_all["date"] = pd.to_datetime(hist_all["date"], errors="coerce").dt.normalize()
        hist_all = hist_all.dropna(subset=["date", "symbol", "setup_type"])
        hist_all = hist_all.drop_duplicates(subset=["date", "symbol", "setup_type"], keep="last")
        hist_all = hist_all[hist_all["date"] >= (run_date - pd.Timedelta(days=600))]
        hist_all = hist_all.sort_values(["date", "symbol", "setup_type"])
        hist_all.to_parquet(snapshot_path, index=False)

    if snapshot_path.exists():
        try:
            hist = pd.read_parquet(snapshot_path)
        except Exception:
            hist = pd.DataFrame(columns=snapshot_cols)
    else:
        hist = pd.DataFrame(columns=snapshot_cols)

    def _is_trading_day(d: pd.Timestamp) -> bool:
        return bool(is_nse_trading_day(d))

    def _calc_streak(date_set: set[pd.Timestamp], ordered_dates: list[pd.Timestamp], current_d: pd.Timestamp) -> int:
        if current_d not in date_set or current_d not in ordered_dates:
            return 0
        idx = ordered_dates.index(current_d)
        count = 0
        for j in range(idx, -1, -1):
            if ordered_dates[j] in date_set:
                count += 1
            else:
                break
        return count

    def _strip_ns(sym: str) -> str:
        s = str(sym or "").strip().upper()
        return s[:-3] if s.endswith(".NS") else s

    if not hist.empty:
        hist["date"] = pd.to_datetime(hist["date"], errors="coerce").dt.normalize()
        hist = hist.dropna(subset=["date"])
        all_dates = sorted(hist["date"].unique().tolist())
        latest_snapshot_date = all_dates[-1] if all_dates else run_date
        latest_run_date = latest_snapshot_date
        if snapshot_meta_path.exists():
            try:
                meta_obj = json.loads(snapshot_meta_path.read_text())
                meta_d = pd.to_datetime(meta_obj.get("last_run_date"), errors="coerce")
                if not pd.isna(meta_d):
                    latest_run_date = meta_d.normalize()
            except Exception:
                pass
        lookback_dates = all_dates[-20:] if len(all_dates) >= 20 else all_dates
        hist20 = hist[hist["date"].isin(lookback_dates)].copy()

        master_universe = {_strip_ns(s) for s in NIFTY_200}
        current_scan_universe = {_strip_ns(s) for s in selected_stocks}
        hist20["symbol"] = hist20["symbol"].astype(str).map(_strip_ns)
        orphan_master = sorted(set(hist20["symbol"].unique()) - master_universe)
        scan_miss = sorted(
            (set(hist20["symbol"].unique()) - set(orphan_master)) - current_scan_universe
        )
        # Exclude hard-orphans from all downstream streak/day calculations.
        if orphan_master:
            hist20 = hist20[~hist20["symbol"].isin(orphan_master)].copy()

        today_rows = hist[hist["date"] == latest_snapshot_date].copy()
        today_rows["symbol"] = today_rows["symbol"].astype(str).map(_strip_ns)
        if orphan_master:
            today_rows = today_rows[~today_rows["symbol"].isin(orphan_master)].copy()
        prev_date = all_dates[-2] if len(all_dates) >= 2 else None
        prev_rows = hist[hist["date"] == prev_date].copy() if prev_date is not None else pd.DataFrame(columns=hist.columns)
        if not prev_rows.empty:
            prev_rows["symbol"] = prev_rows["symbol"].astype(str).map(_strip_ns)
            if orphan_master:
                prev_rows = prev_rows[~prev_rows["symbol"].isin(orphan_master)].copy()

        today_keys = set(zip(today_rows["symbol"], today_rows["setup_type"]))
        prev_keys = set(zip(prev_rows.get("symbol", pd.Series(dtype=str)), prev_rows.get("setup_type", pd.Series(dtype=str))))
        dropped_keys = sorted(list(prev_keys - today_keys))

        ctx_rows = []
        for _, r in today_rows.iterrows():
            sym = str(r["symbol"])
            stype = str(r["setup_type"])
            h_setup = hist20[(hist20["symbol"] == sym) & (hist20["setup_type"] == stype)]
            h_sym = hist20[hist20["symbol"] == sym]
            setup_dates = sorted(h_setup["date"].unique().tolist())
            sym_dates = sorted(h_sym["date"].unique().tolist())
            setup_days = len(setup_dates)
            sym_days = len(sym_dates)
            setup_streak = _calc_streak(set(setup_dates), lookback_dates, latest_snapshot_date)
            sym_streak = _calc_streak(set(sym_dates), lookback_dates, latest_snapshot_date)
            qhist = pd.to_numeric(h_setup["quality_score"], errors="coerce").dropna().tail(5)
            qtrend = (float(qhist.iloc[-1] - qhist.iloc[0]) if len(qhist) >= 3 else 0.0)
            is_new = setup_days == 1
            is_fading = (setup_days >= 8 and qtrend <= -0.06)
            tags = []
            if is_new:
                tags.append("NEW")
            if is_fading:
                tags.append("FADING")
            ctx_rows.append({
                "Tag": ("🆕" if is_new else "") + (" ⚠️" if is_fading else ""),
                "Symbol": sym,
                "Setup": stype,
                "Tier": r.get("tier", ""),
                "Score": float(r.get("score", 0.0)),
                "Quality": float(r.get("quality_score", 0.0)),
                "Quality Band": str(r.get("quality_band", "")),
                "Category": str(r.get("category_label", "")),
                "Setup Streak": setup_streak,
                "Symbol Streak": sym_streak,
                "Days in 20D": setup_days,
                "Symbol Days 20D": sym_days,
                "Quality Trend(5)": qtrend,
                "Status Tag": ", ".join(tags) if tags else "ACTIVE",
            })

        dropped_rows = []
        for sym, stype in dropped_keys:
            h_setup = hist20[(hist20["symbol"] == sym) & (hist20["setup_type"] == stype)]
            setup_days = int(h_setup["date"].nunique())
            label = "PAUSED" if setup_days >= 8 else "DROPPED"
            dropped_rows.append({
                "Tag": "🔁" if label == "PAUSED" else "🔻",
                "Symbol": sym,
                "Setup": stype,
                "Days in 20D": setup_days,
                "Status Tag": label,
            })

        tradable_ctx_df = pd.DataFrame(ctx_rows).sort_values(
            ["Score", "Quality", "Setup Streak"], ascending=[False, False, False]
        ) if ctx_rows else pd.DataFrame()
        dropped_df = pd.DataFrame(dropped_rows).sort_values(
            ["Days in 20D", "Symbol"], ascending=[False, True]
        ) if dropped_rows else pd.DataFrame()

        today_ist = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
        stale_today = _is_trading_day(today_ist) and (latest_run_date != today_ist)

        with st.expander("✅ Tradable Across Categories (20D Context)", expanded=False):
            with st.expander("ℹ️ How to Use", expanded=False):
                st.markdown(
                    "- Tradable Today: names passing all gates now.\n"
                    "- Setup Streak: consecutive trading-day streak for same setup.\n"
                    "- Days in 20D: total setup appearances in last 20 trading days.\n"
                    "- 🆕 New: first appearance in current 20D window (alert state; trigger may still take 1-2 sessions).\n"
                    "- 🔻 Dropped: tradable yesterday, not today. If holding: reassess risk. If watching: remove from active list.\n"
                    "- 🔁 Paused Leader: strong 20D presence but currently off-list; watch for re-entry.\n"
                    "- ⚠️ Fading: still tradable but quality trend has declined; monitor closely before fresh sizing."
                )
            if orphan_master:
                show = ", ".join(orphan_master[:12])
                suffix = "" if len(orphan_master) <= 12 else f" +{len(orphan_master)-12} more"
                st.warning(
                    f"⚠️ Not in current master universe (excluded from streak math): {show}{suffix}"
                )
            if scan_miss:
                show = ", ".join(scan_miss[:12])
                suffix = "" if len(scan_miss) <= 12 else f" +{len(scan_miss)-12} more"
                st.info(
                    f"ℹ️ Not in current scan universe (historical context only): {show}{suffix}"
                )
            if stale_today:
                st.warning(f"Snapshot is stale for trading day {today_ist.date()} (latest run: {latest_run_date.date()}).")
            st.caption(f"Latest run: {latest_run_date.date()} | Lookback days loaded: {len(lookback_dates)}")
            if not tradable_ctx_df.empty:
                tview = tradable_ctx_df.copy()
                tview["Score"] = tview["Score"].map(lambda x: f"{x:.2f}")
                tview["Quality"] = tview["Quality"].map(lambda x: f"{x:.2f}")
                tview["Quality Trend(5)"] = tview["Quality Trend(5)"].map(lambda x: f"{x:+.2f}")
                st.dataframe(tview, width="stretch", hide_index=True)
            else:
                st.info("No tradable rows found in latest snapshot.")
            if not dropped_df.empty:
                st.markdown("**Dropped / Paused Since Previous Trading Day**")
                st.dataframe(dropped_df, width="stretch", hide_index=True)

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
                    risk_atr_txt = f"{row['Risk (ATR)']:.2f} ATR" if pd.notna(row.get("Risk (ATR)")) else "ATR n/a"
                    st.caption(
                        f"Invalidation: {format_price(row['Invalidation'])} "
                        f"({row['Invalidation %']:.2f}% | {risk_atr_txt})"
                    )
                    st.caption(str(row.get("Invalidation Detail", row.get("Invalidation Rule", ""))))
                    st.caption(f"Trigger: {row.get('Trigger Type', 'Close < Invalidation')} | Time Stop: {int(row.get('Time Stop (bars)', 0))} bars")
                    st.caption(
                        f"RS20: {float(row.get('RS', 0.0)):+.2f} | "
                        f"RS EMA3: {float(row.get('RS EMA3', 0.0)):+.2f} | "
                        f"Tier: {row.get('RS Tier', 'Neutral')} vs {row.get('RS Benchmark', 'NIFTY 50')}"
                    )
                    st.caption(
                        f"Quality: {float(row.get('Quality Score', 0.0)):.2f} "
                        f"({row.get('Quality Band', 'Blocked')}) | RS floor penalty: {float(row.get('RS Floor Penalty', 0.0)):.2f}"
                    )
                    if pd.notna(row.get("ML")) and row.get("ML", 0) > 0:
                        run_abs = float(row["Price"]) - float(row["ML"])
                        st.caption(f"Run-up from ML: {run_abs:+.2f} ({float(row.get('LTP vs ML %', 0.0)):+.2f}%)")
                    st.caption(f"Trend:{row['Trend']} | Vol:{row['Vol Ratio']:.2f}x | RSI:{row['RSI']:.1f}")

                    sym = row['Symbol']
                    prefill_symbol = sym if sym.endswith(".NS") else f"{sym}.NS"
                    setup_label = str(row.get("Setup Type", "Swing Ranking"))
                    if setup_label.startswith("Momentum"):
                        pre_setup_family = "Momentum"
                    elif setup_label.startswith("Pullback"):
                        pre_setup_family = "Pullback"
                    elif setup_label.startswith("Volatility"):
                        pre_setup_family = "Volatility Contraction"
                    else:
                        pre_setup_family = "Other"
                    if st.button("Log Setup", key=f"log_setup_phase2_{i}_{sym}", width='stretch'):
                        st.session_state["journal_prefill"] = {
                            "symbol": prefill_symbol,
                            "strategy": "Swing Ranking",
                            "side": "LONG",
                            "setup_family": pre_setup_family,
                            "entry_price": float(row.get("Price", 0.0) or 0.0),
                            "stop_loss": float(row.get("Invalidation", 0.0) or 0.0),
                            "invalidation": float(row.get("Invalidation", 0.0) or 0.0),
                            "entry_risk_atr": float(row.get("Risk (ATR)", 0.0) or 0.0),
                            "target_price": 0.0,
                            "trigger_policy": str(row.get("Trigger Type", "")),
                            "notes": (
                                f"Auto from Swing: {setup_label} | "
                                f"Score {float(row.get('Score', 0.0)):.2f} | "
                                f"Trigger: {row.get('Trigger Type', '')}"
                            ),
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
            "Invalidation", "Invalidation %", "Risk (ATR)", "Trigger Type", "Time Stop (bars)",
            "ML", "LTP vs ML %", "RS", "RS EMA3", "RS Tier", "RS Benchmark",
            "Vol Ratio", "RSI", "Quality Score", "Quality Band", "RS Floor Penalty", "Gate Reason", "Invalidation Rule", "Invalidation Detail"
        ]].copy()
        mon = mon.rename(columns={"Gate Status": "Entry Gate", "Gate Reason": "Block Reason"})
        mon["Price"] = mon["Price"].apply(format_price)
        mon["Change %"] = mon["Change %"].apply(format_change)
        mon["Invalidation"] = mon["Invalidation"].apply(format_price)
        mon["Vol Ratio"] = mon["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
        mon["RSI"] = mon["RSI"].apply(lambda x: f"{x:.1f}")
        mon["Quality Score"] = mon["Quality Score"].apply(lambda x: f"{x:.2f}")
        mon["RS Floor Penalty"] = mon["RS Floor Penalty"].apply(lambda x: f"{x:.2f}")
        mon["Invalidation %"] = mon["Invalidation %"].apply(lambda x: f"{x:.2f}%")
        mon["ML"] = mon["ML"].apply(lambda x: format_price(x) if pd.notna(x) and x > 0 else "-")
        mon["LTP vs ML %"] = mon["LTP vs ML %"].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "-")
        mon["RS"] = mon["RS"].apply(lambda x: f"{x:+.2f}")
        mon["RS EMA3"] = mon["RS EMA3"].apply(lambda x: f"{x:+.2f}")
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

    near_miss_df = score_df[
        score_df["Hard Gate"].astype(bool) &
        score_df["Quality Gate"].astype(bool) &
        (~score_df["Setup Any Pass"].astype(bool))
    ].copy()
    if not near_miss_df.empty:
        near_miss_df = near_miss_df.sort_values(
            ["Quality Score", "RS", "Vol Ratio"],
            ascending=[False, False, False]
        )
        with st.expander(
            f"👀 Near Miss Watch Queue ({len(near_miss_df)} symbols passed hard+quality, setup pending)",
            expanded=False,
        ):
            nview = near_miss_df[[
                "Symbol", "Trend", "Price", "RS", "RS EMA3", "Vol Ratio", "RSI",
                "Quality Score", "Quality Band", "dist_ema20", "Near Miss Reason"
            ]].copy()
            nview["Price"] = nview["Price"].apply(format_price)
            nview["RS"] = nview["RS"].apply(lambda x: f"{x:+.2f}")
            nview["RS EMA3"] = nview["RS EMA3"].apply(lambda x: f"{x:+.2f}")
            nview["Vol Ratio"] = nview["Vol Ratio"].apply(lambda x: f"{x:.2f}x")
            nview["RSI"] = nview["RSI"].apply(lambda x: f"{x:.1f}")
            nview["Quality Score"] = nview["Quality Score"].apply(lambda x: f"{x:.2f}")
            nview["dist_ema20"] = nview["dist_ema20"].apply(lambda x: f"{x:+.2f}%")
            st.dataframe(nview.head(25 if view_mode == "Summary" else 100), width="stretch", hide_index=True)

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

_perf["mode_render_s"] = round(time.perf_counter() - _t_mode, 3)
_perf["total_page_s"] = round(time.perf_counter() - _page_t0, 3)
if st.sidebar.checkbox("Show Performance Diagnostics", value=False):
    st.sidebar.dataframe(
        pd.DataFrame([{"Step": k, "Seconds": v} for k, v in _perf.items()]),
        width="stretch",
        hide_index=True,
    )

# ==================== FOOTER ====================
st.markdown("---")

footer_cols = st.columns([2, 1, 1])

with footer_cols[0]:
    st.caption(f"📊 Analyzing **{len(selected_stocks)}** stocks from **{selection_method}**")

with footer_cols[1]:
    st.caption(f"🕐 Updated: {datetime.now().strftime('%H:%M:%S')}")

with footer_cols[2]:
    st.caption("✅ Enhanced: VWAP | Tables | Better visuals")
