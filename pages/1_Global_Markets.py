import streamlit as st
import pandas as pd
import logging

from config import (
    GLOBAL_RISK_SNAPSHOT,
    GLOBAL_INDICES,
    CURRENCIES,
    COMMODITIES,
    CRYPTO,
    BOND_MARKETS
)

from data_fetch import batch_download, extract_price_data, get_ticker_price

# Setup logging
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Global Markets", layout="wide")

st.title("🌍 Global Macro Dashboard")

st.caption("Markets snapshot helps identify global risk sentiment before trading.")

# ==================== DOWNLOAD DATA ====================

all_symbols = list(set(
    list(GLOBAL_RISK_SNAPSHOT.keys()) +
    list(GLOBAL_INDICES.keys()) +
    list(CURRENCIES.keys()) +
    list(COMMODITIES.keys()) +
    list(CRYPTO.keys()) +
    list(BOND_MARKETS.keys())
))

with st.spinner("Fetching global market data..."):
    data = batch_download(all_symbols, period="5d")

# Debugging info
with st.expander("🔍 Data Status (Debug)", expanded=False):
    st.write(f"**Requested**: {len(all_symbols)} symbols")
    st.write(f"**Retrieved**: {len(data)} symbols")

    if len(data) < len(all_symbols):
        missing = [s for s in all_symbols if s not in data]
        st.warning(f"⚠️ Missing data for {len(missing)} symbols:")
        for sym in missing[:15]:  # Show first 15
            st.write(f"- {sym}")

    # Show what we actually got
    if data:
        st.success("✅ Successfully loaded symbols:")
        for symbol, df in list(data.items())[:10]:  # Show first 10
            if df is not None and len(df) > 0:
                latest = df['Close'].iloc[-1] if 'Close' in df.columns else None
                st.write(
                    f"✓ {symbol}: {latest:.2f}" if latest and not pd.isna(latest) else f"⚠️ {symbol}: NaN or no Close")

    # Test a specific symbol in detail
    st.markdown("---")
    st.write("**Detailed Check - S&P 500:**")
    test_df = data.get('^GSPC')
    if test_df is not None:
        st.write(f"- Shape: {test_df.shape}")
        st.write(f"- Columns: {test_df.columns.tolist()}")
        st.write(f"- Last 2 rows:")
        st.dataframe(test_df.tail(2))

# ==================== SNAPSHOT ====================

st.subheader("📊 Global Risk Snapshot")

cols = st.columns(len(GLOBAL_RISK_SNAPSHOT))

for col, (symbol, name) in zip(cols, GLOBAL_RISK_SNAPSHOT.items()):
    df = data.get(symbol)

    # FIXED: Prioritize LIVE price over historical for current market data
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical data if live fetch fails
    if price is None:
        logger.info(f"Using historical data for {symbol}")
        price, change, change_pct = extract_price_data(df)

    if price is not None:
        # Format based on value magnitude
        if price > 1000:
            value_str = f"{price:,.0f}"
        elif price > 10:
            value_str = f"{price:.2f}"
        else:
            value_str = f"{price:.4f}"

        col.metric(
            label=name,
            value=value_str,
            delta=f"{change_pct:.2f}%" if change_pct is not None else None
        )
    else:
        col.metric(label=name, value="N/A")
        logger.warning(f"No data for {symbol} ({name})")

st.caption("Guide: Nasdaq ↑ + DXY ↓ = Risk ON | DXY ↑ + Yields ↑ = Risk OFF")

# ==================== GLOBAL INDICES ====================

st.subheader("🌎 Global Indices")

rows = []
for symbol, name in GLOBAL_INDICES.items():
    df = data.get(symbol)

    # FIXED: Prioritize LIVE price over historical
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical data
    if price is None:
        price, change, change_pct = extract_price_data(df)

    rows.append({
        "Index": name,
        "Price": f"{price:,.2f}" if price is not None else "N/A",
        "Change %": f"{change_pct:.2f}%" if change_pct is not None else "N/A"
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ==================== CURRENCIES ====================

st.subheader("💱 Currency Markets")

rows = []
for symbol, name in CURRENCIES.items():
    df = data.get(symbol)

    # FIXED: Prioritize LIVE price over historical
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical data
    if price is None:
        price, change, change_pct = extract_price_data(df)

    rows.append({
        "Pair": name,
        "Price": f"{price:.4f}" if price is not None else "N/A",
        "Change %": f"{change_pct:.2f}%" if change_pct is not None else "N/A"
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ==================== COMMODITIES ====================

st.subheader("🛢 Commodities")

rows = []
for symbol, name in COMMODITIES.items():
    df = data.get(symbol)

    # FIXED: Prioritize LIVE price over historical
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical data
    if price is None:
        price, change, change_pct = extract_price_data(df)

    rows.append({
        "Commodity": name,
        "Price": f"{price:,.2f}" if price is not None else "N/A",
        "Change %": f"{change_pct:.2f}%" if change_pct is not None else "N/A"
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ==================== CRYPTO ====================

st.subheader("₿ Crypto Markets")

rows = []
for symbol, name in CRYPTO.items():
    df = data.get(symbol)

    # FIXED: Prioritize LIVE price over historical
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical data
    if price is None:
        price, change, change_pct = extract_price_data(df)

    rows.append({
        "Asset": name,
        "Price": f"${price:,.2f}" if price is not None else "N/A",
        "Change %": f"{change_pct:.2f}%" if change_pct is not None else "N/A"
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ==================== BONDS ====================

st.subheader("📉 Bond Markets")

rows = []
for symbol, name in BOND_MARKETS.items():
    df = data.get(symbol)

    # FIXED: Prioritize LIVE price over historical
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical data
    if price is None:
        price, change, change_pct = extract_price_data(df)

    rows.append({
        "Instrument": name,
        "Value": f"{price:.2f}%" if price is not None else "N/A",
        "Change": f"{change_pct:+.2f}%" if change_pct is not None else "N/A"
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)