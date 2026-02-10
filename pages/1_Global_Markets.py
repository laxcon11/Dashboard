"""
Global Markets Dashboard - OPTIMIZED VERSION

Optimizations:
- Uses utils.display_price_metric() for all sections
- Consistent formatting via utils
- Cleaner code structure
"""

import streamlit as st
import pandas as pd

from config import (
    GLOBAL_RISK_SNAPSHOT,
    GLOBAL_INDICES,
    CURRENCIES,
    COMMODITIES,
    CRYPTO,
    BOND_MARKETS
)

from data_fetch import batch_download
from utils import display_price_metric, create_price_table

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

# Debug info
with st.expander("🔍 Data Status", expanded=False):
    st.write(f"**Requested**: {len(all_symbols)} symbols")
    st.write(f"**Retrieved**: {len(data)} symbols")

    if len(data) < len(all_symbols):
        missing = [s for s in all_symbols if s not in data]
        st.warning(f"⚠️ Missing: {', '.join(missing[:10])}")

# ==================== GLOBAL RISK SNAPSHOT ====================

st.subheader("📊 Global Risk Snapshot")

cols = st.columns(len(GLOBAL_RISK_SNAPSHOT))

for col, (symbol, name) in zip(cols, GLOBAL_RISK_SNAPSHOT.items()):
    display_price_metric(col, symbol, name, data.get(symbol))

st.caption("Guide: Nasdaq ↑ + DXY ↓ = Risk ON | DXY ↑ + Yields ↑ = Risk OFF")

# ==================== GLOBAL INDICES ====================

st.subheader("🌎 Global Indices")
st.dataframe(
    create_price_table(GLOBAL_INDICES, data, ["Index", "Price", "Change %"]),
    use_container_width=True,
    hide_index=True
)

# ==================== CURRENCIES ====================

st.subheader("💱 Currency Markets")
st.dataframe(
    create_price_table(CURRENCIES, data, ["Pair", "Price", "Change %"]),
    use_container_width=True,
    hide_index=True
)

# ==================== COMMODITIES ====================

st.subheader("🛢 Commodities")
st.dataframe(
    create_price_table(COMMODITIES, data, ["Commodity", "Price", "Change %"]),
    use_container_width=True,
    hide_index=True
)

# ==================== CRYPTO ====================

st.subheader("₿ Crypto Markets")
st.dataframe(
    create_price_table(CRYPTO, data, ["Asset", "Price", "Change %"]),
    use_container_width=True,
    hide_index=True
)

# ==================== BONDS ====================

st.subheader("📉 Bond Markets")
st.dataframe(
    create_price_table(BOND_MARKETS, data, ["Instrument", "Value", "Change"]),
    use_container_width=True,
    hide_index=True
)

st.markdown("---")
st.caption("Data: Yahoo Finance (15-20 min delay) | ✅ Optimized with shared utilities")