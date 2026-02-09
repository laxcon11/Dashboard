"""
NSE Swing Trading Dashboard
Integrated with central config and shared utilities
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
    WATCHLIST,
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
st.caption("Integrated swing trading analysis for Indian markets")

# ==================== SECTOR INDICES ====================
SECTOR_INDICES = {
    '^CNXIT': 'IT',
    '^CNXAUTO': 'Auto',
    '^CNXPHARMA': 'Pharma',
    '^CNXFMCG': 'FMCG',
    '^CNXMETAL': 'Metal',
    '^CNXREALTY': 'Realty',
    '^CNXENERGY': 'Energy'
}

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

def calculate_relative_strength(stock_df, nifty_df):
    """Calculate RS vs NIFTY"""
    if stock_df is None or nifty_df is None:
        return None
    
    try:
        stock_ret = ((stock_df['Close'].iloc[-1] / stock_df['Close'].iloc[0]) - 1) * 100
        nifty_ret = ((nifty_df['Close'].iloc[-1] / nifty_df['Close'].iloc[0]) - 1) * 100
        return stock_ret - nifty_ret
    except:
        return None

def detect_breakout(df, window=BREAKOUT_WINDOW):
    """Detect true breakout"""
    if df is None or len(df) < window + 1:
        return None
    
    try:
        current = df['Close'].iloc[-1]
        period_high = df['High'].iloc[-window-1:-1].max()
        period_low = df['Low'].iloc[-window-1:-1].min()
        
        if current > period_high:
            return "BREAKOUT HIGH"
        elif current < period_low:
            return "BREAKDOWN LOW"
    except:
        pass
    
    return None

def analyze_trend(current, ema20, ema50):
    """Classify trend strength"""
    try:
        if current > ema20 > ema50:
            return "🟢 Strong Bullish"
        elif current > ema20:
            return "🟢 Weak Bullish"
        elif current < ema20 < ema50:
            return "🔴 Strong Bearish"
        elif current < ema20:
            return "🔴 Weak Bearish"
        else:
            return "⚪ Neutral"
    except:
        return "⚪ Neutral"

def get_support_resistance(df, window=20):
    """Calculate S/R levels"""
    if df is None or len(df) < window:
        return None, None
    
    try:
        support = df['Low'].tail(window).min()
        resistance = df['High'].tail(window).max()
        return support, resistance
    except:
        return None, None

def calculate_swing_score(row):
    """Multi-factor swing scoring"""
    score = 0
    
    try:
        # Gap
        gap = row.get('Gap %', 0)
        if gap > 1:
            score += 2
        elif gap > 0.5:
            score += 1
        
        # Volume
        vol = row.get('Vol Ratio', 0)
        if vol > 2:
            score += 3
        elif vol > 1.5:
            score += 2
        elif vol > 1.2:
            score += 1
        
        # Relative Strength
        rs = row.get('RS vs NIFTY', 0)
        if rs is not None and not pd.isna(rs):
            if rs > 2:
                score += 3
            elif rs > 1:
                score += 2
            elif rs > 0:
                score += 1
        
        # Breakout
        if row.get('Signal', '') == 'BREAKOUT HIGH':
            score += 3
        
        # Trend
        trend = str(row.get('Trend', ''))
        if 'Strong Bullish' in trend:
            score += 2
        elif 'Weak Bullish' in trend:
            score += 1
        
        return score
    except:
        return 0

# ==================== SIDEBAR ====================
st.sidebar.title("⚙️ Dashboard Settings")

dashboard_mode = st.sidebar.radio(
    "Mode",
    ["Morning Review", "End of Day", "Full Analysis", "Swing Rankings"]
)

st.sidebar.subheader("📋 Watchlist")
watchlist_input = st.sidebar.text_area(
    "Symbols (one per line with .NS)",
    value='\n'.join(WATCHLIST),
    height=150
)

# Parse watchlist
watchlist = [s.strip().upper() for s in watchlist_input.split('\n') if s.strip()]

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.info("💡 Data updates every 5 min | 15-20 min delay")

# Session state for refresh tracking
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now()

# ==================== DATA LOADING ====================

all_symbols = list(set(list(MAIN_INDICES.keys()) + list(SECTOR_INDICES.keys()) + watchlist))

with st.spinner("📡 Fetching market data..."):
    data_1mo = batch_download(all_symbols, period='1mo')
    data_5d = {s: get_last_n_days(df, 5) for s, df in data_1mo.items()}
    
    nifty_data = data_1mo.get('^NSEI')
    
    st.session_state.last_refresh = datetime.now()

# Display refresh time
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown(f"*Current: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
with col2:
    st.markdown(f"*Refreshed: {st.session_state.last_refresh.strftime('%H:%M:%S')}*")

# Connection status
with st.expander("🔌 Data Status", expanded=False):
    if data_1mo:
        st.success(f"✅ Loaded {len(data_1mo)}/{len(all_symbols)} symbols")
    else:
        st.error("❌ Failed to load data")

# ==================== MARKET OVERVIEW ====================
st.header("🌐 Market Overview")

cols = st.columns(len(MAIN_INDICES))
for idx, (symbol, name) in enumerate(MAIN_INDICES.items()):
    with cols[idx]:
        df = data_5d.get(symbol)
        price, change, change_pct = extract_price_data(df)
        
        if price is not None:
            st.metric(
                name,
                f"₹{price:,.2f}" if price > 100 else f"{price:.2f}",
                f"{change_pct:.2f}%" if change_pct is not None else None
            )
        else:
            st.metric(name, "N/A")

# ==================== SECTOR PERFORMANCE ====================
st.header("📂 Sector Performance")

sector_data = []
for symbol, sector in SECTOR_INDICES.items():
    df = data_5d.get(symbol)
    _, _, change_pct = extract_price_data(df)
    
    if change_pct is not None:
        sector_data.append({'Sector': sector, 'Change %': change_pct})

if sector_data:
    sector_df = pd.DataFrame(sector_data).sort_values('Change %', ascending=False)
    
    fig = px.bar(
        sector_df,
        x='Sector',
        y='Change %',
        color='Change %',
        color_continuous_scale='RdYlGn',
        title='Sector Performance Today'
    )
    fig.update_layout(height=350, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# ==================== SWING RANKINGS ====================
if dashboard_mode == "Swing Rankings":
    st.header("🎯 Swing Trade Rankings")
    
    ranking_data = []
    
    for symbol in watchlist:
        df_1mo = data_1mo.get(symbol)
        df_5d = data_5d.get(symbol)
        
        if df_5d is not None and len(df_5d) > 0:
            price, _, change_pct = extract_price_data(df_5d)
            gap, gap_pct = detect_gap(df_5d)
            vol_ratio = calculate_volume_ratio(df_1mo)
            rs = calculate_relative_strength(df_1mo, nifty_data)
            breakout = detect_breakout(df_1mo)
            
            ema20 = calculate_ema(df_1mo, 20).iloc[-1] if df_1mo is not None and len(df_1mo) > 20 else None
            ema50 = calculate_ema(df_1mo, 50).iloc[-1] if df_1mo is not None and len(df_1mo) > 50 else None
            
            trend = analyze_trend(price, ema20, ema50) if price and ema20 and ema50 else "⚪ Neutral"
            
            row = {
                'Symbol': symbol.replace('.NS', ''),
                'Price': price or 0,
                'Change %': change_pct or 0,
                'Gap %': gap_pct,
                'Vol Ratio': vol_ratio,
                'RS vs NIFTY': rs or 0,
                'Signal': breakout or '',
                'Trend': trend
            }
            
            row['Score'] = calculate_swing_score(pd.Series(row))
            ranking_data.append(row)
    
    if ranking_data:
        rank_df = pd.DataFrame(ranking_data).sort_values('Score', ascending=False)
        rank_df.insert(0, 'Rank', range(1, len(rank_df) + 1))
        
        st.dataframe(
            rank_df.style.format({
                'Price': '₹{:.2f}',
                'Change %': '{:.2f}%',
                'Gap %': '{:.2f}%',
                'Vol Ratio': '{:.2f}x',
                'RS vs NIFTY': '{:.2f}%',
                'Score': '{:.0f}'
            }).background_gradient(subset=['Score'], cmap='RdYlGn'),
            use_container_width=True,
            hide_index=True
        )
        
        # Top 3
        st.subheader("🏆 Top 3 Candidates")
        top3 = rank_df.head(3)
        
        cols = st.columns(3)
        for idx, (_, row) in enumerate(top3.iterrows()):
            with cols[idx]:
                st.markdown(f"### #{idx+1} {row['Symbol']}")
                st.metric("Score", f"{row['Score']:.0f}")
                st.metric("Price", f"₹{row['Price']:.2f}", f"{row['Change %']:.2f}%")
                st.write(f"**Trend:** {row['Trend']}")
                if row['Signal']:
                    st.warning(f"⚠️ {row['Signal']}")

# ==================== MORNING REVIEW ====================
elif dashboard_mode == "Morning Review":
    st.header("🌅 Morning Review")
    
    watchlist_data = []
    
    for symbol in watchlist:
        df_1mo = data_1mo.get(symbol)
        df_5d = data_5d.get(symbol)
        
        if df_5d is not None:
            price, _, change_pct = extract_price_data(df_5d)
            gap, gap_pct = detect_gap(df_5d)
            support, resistance = get_support_resistance(df_1mo)
            vol_ratio = calculate_volume_ratio(df_1mo)
            rs = calculate_relative_strength(df_1mo, nifty_data)
            signal = detect_breakout(df_1mo)
            
            if price is not None:
                watchlist_data.append({
                    'Symbol': symbol.replace('.NS', ''),
                    'Price': price,
                    'Change %': change_pct or 0,
                    'Gap %': gap_pct,
                    'Support': support or 0,
                    'Resistance': resistance or 0,
                    'Vol Ratio': vol_ratio,
                    'RS': rs or 0,
                    'Signal': signal or ''
                })
    
    if watchlist_data:
        watch_df = pd.DataFrame(watchlist_data).sort_values('Change %', ascending=False)
        st.dataframe(watch_df, use_container_width=True, hide_index=True)
        
        # Highlights
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("**🚀 Gap-Up (>1%)**")
            gap_up = watch_df[watch_df['Gap %'] > 1]
            if not gap_up.empty:
                st.dataframe(gap_up[['Symbol', 'Gap %']], hide_index=True)
            else:
                st.info("None")
        
        with col2:
            st.markdown("**📉 Gap-Down (<-1%)**")
            gap_down = watch_df[watch_df['Gap %'] < -1]
            if not gap_down.empty:
                st.dataframe(gap_down[['Symbol', 'Gap %']], hide_index=True)
            else:
                st.info("None")
        
        with col3:
            st.markdown("**🔊 High Volume (>1.5x)**")
            high_vol = watch_df[watch_df['Vol Ratio'] > VOLUME_THRESHOLD]
            if not high_vol.empty:
                st.dataframe(high_vol[['Symbol', 'Vol Ratio']], hide_index=True)
            else:
                st.info("None")

# ==================== END OF DAY ====================
elif dashboard_mode == "End of Day":
    st.header("🌆 End of Day Review")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📊 Market Breadth**")
        
        advances = sum(1 for s in watchlist if extract_price_data(data_5d.get(s))[2] and extract_price_data(data_5d.get(s))[2] > 0)
        declines = len(watchlist) - advances
        
        if advances + declines > 0:
            fig = go.Figure(data=[go.Pie(
                labels=['Advances', 'Declines'],
                values=[advances, declines],
                marker=dict(colors=['#28a745', '#dc3545']),
                hole=0.3
            )])
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("**📈 RSI Extremes**")
        
        rsi_data = []
        for symbol in watchlist[:15]:
            df = data_1mo.get(symbol)
            if df is not None and len(df) > RSI_PERIOD:
                rsi_series = calculate_rsi(df, RSI_PERIOD)
                rsi = rsi_series.iloc[-1]
                
                if not pd.isna(rsi):
                    status = 'Overbought' if rsi > RSI_OVERBOUGHT else ('Oversold' if rsi < RSI_OVERSOLD else 'Neutral')
                    rsi_data.append({
                        'Symbol': symbol.replace('.NS', ''),
                        'RSI': rsi,
                        'Status': status
                    })
        
        if rsi_data:
            rsi_df = pd.DataFrame(rsi_data).sort_values('RSI')
            st.dataframe(rsi_df, hide_index=True)

# ==================== FULL ANALYSIS ====================
elif dashboard_mode == "Full Analysis":
    st.header("🔍 Detailed Analysis")
    
    selected = st.selectbox("Select Stock", watchlist)
    
    if selected:
        df = data_1mo.get(selected)
        
        if df is not None and len(df) > 0:
            price, _, change_pct = extract_price_data(data_5d.get(selected))
            support, resistance = get_support_resistance(df)
            
            rsi_series = calculate_rsi(df, RSI_PERIOD)
            rsi = rsi_series.iloc[-1] if len(rsi_series) > 0 else None
            
            ema20 = calculate_ema(df, 20).iloc[-1] if len(df) > 20 else None
            ema50 = calculate_ema(df, 50).iloc[-1] if len(df) > 50 else None
            
            atr_series = calculate_atr(df, ATR_PERIOD)
            atr = atr_series.iloc[-1] if len(atr_series) > 0 else None
            
            # Metrics
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Price", f"₹{price:,.2f}" if price else "N/A", f"{change_pct:.2f}%" if change_pct else None)
            with col2:
                st.metric("Support", f"₹{support:,.2f}" if support else "N/A")
            with col3:
                st.metric("Resistance", f"₹{resistance:,.2f}" if resistance else "N/A")
            with col4:
                st.metric("RSI", f"{rsi:.2f}" if rsi and not pd.isna(rsi) else "N/A")
            with col5:
                if atr and price and not pd.isna(atr):
                    stop = price - (ATR_MULTIPLIER * atr)
                    st.metric("Stop-Loss", f"₹{stop:,.2f}")
                else:
                    st.metric("Stop-Loss", "N/A")
            
            # Chart
            fig = go.Figure()
            
            fig.add_trace(go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name='Price'
            ))
            
            if ema20 and not pd.isna(ema20):
                ema20_series = calculate_ema(df, 20)
                fig.add_trace(go.Scatter(x=df.index, y=ema20_series, name='20 EMA', line=dict(color='blue')))
            
            if ema50 and not pd.isna(ema50):
                ema50_series = calculate_ema(df, 50)
                fig.add_trace(go.Scatter(x=df.index, y=ema50_series, name='50 EMA', line=dict(color='orange')))
            
            if support:
                fig.add_hline(y=support, line_dash="dash", line_color="green", annotation_text="Support")
            if resistance:
                fig.add_hline(y=resistance, line_dash="dash", line_color="red", annotation_text="Resistance")
            
            fig.update_layout(
                title=f'{selected} - 3 Month Chart',
                xaxis_rangeslider_visible=False,
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)

# ==================== NOTES ====================
st.markdown("---")
st.subheader("📝 Trading Notes")

notes = st.text_area("Daily observations:", height=100)

if st.button("💾 Save Notes"):
    notes_dir = Path.cwd() / 'notes'
    notes_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
    notes_file = notes_dir / f"nse_notes_{timestamp}.txt"
    
    try:
        with open(notes_file, 'w') as f:
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("="*50 + "\n\n")
            f.write(notes)
        st.success(f"✅ Saved to {notes_file.name}")
        logger.info(f"Notes saved: {notes_file}")
    except Exception as e:
        st.error(f"❌ Error: {e}")
        logger.error(f"Note save failed: {e}")

st.markdown("*NSE Dashboard Pro v3.0 | Integrated Suite*")
