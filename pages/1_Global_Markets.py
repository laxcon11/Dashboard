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
    COMMODITY_FALLBACKS,
    CRYPTO,
    BOND_MARKETS
)

from data_fetch import batch_download
from utils import (
    display_price_metric,
    create_price_table,
    setup_page,
    get_live_price_safe,
    format_price,
    format_change,
    render_key_observations,
    get_ui_detail_mode,
    render_source_freshness,
)

setup_page("Global Markets")
view_mode = get_ui_detail_mode("Summary")

st.title("🌍 Global Macro Dashboard")
st.caption("Markets snapshot helps identify global risk sentiment before trading.")
PAGE_PRICE_MODE = "live_first"

# ==================== DOWNLOAD DATA ====================

all_symbols = sorted(set(
    list(GLOBAL_RISK_SNAPSHOT.keys()) +
    list(GLOBAL_INDICES.keys()) +
    list(CURRENCIES.keys()) +
    list(COMMODITIES.keys()) +
    [s for fallback_list in COMMODITY_FALLBACKS.values() for s in fallback_list] +
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
    display_price_metric(col, symbol, name, data.get(symbol), mode=PAGE_PRICE_MODE)

st.caption("Guide: Nasdaq ↑ + DXY ↓ = Risk ON | DXY ↑ + Yields ↑ = Risk OFF")

obs_rows = []
for symbol, name in GLOBAL_RISK_SNAPSHOT.items():
    df = data.get(symbol)
    if df is None or df.empty or "Close" not in df.columns:
        continue
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 2:
        continue
    pct = ((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100) if close.iloc[-2] != 0 else 0.0
    obs_rows.append((abs(pct), pct, name))

observations = []
for _, pct, name in sorted(obs_rows, reverse=True)[:3]:
    direction = "up" if pct >= 0 else "down"
    observations.append(f"{name}: {direction} {abs(pct):.2f}% today")
if len(data) < len(all_symbols):
    observations.append(f"{len(all_symbols) - len(data)} symbols missing from latest pull.")
render_key_observations(observations)

# ==================== GLOBAL INDICES ====================

st.subheader("🌎 Global Indices")
st.dataframe(
    create_price_table(
        GLOBAL_INDICES,
        data,
        ["Index", "Price", "Change %"],
        mode=PAGE_PRICE_MODE,
        include_meta=(view_mode == "Detail"),
    ),
    width='stretch',
    hide_index=True
)

# ==================== CURRENCIES ====================

st.subheader("💱 Currency Markets")
st.dataframe(
    create_price_table(
        CURRENCIES,
        data,
        ["Pair", "Price", "Change %"],
        mode=PAGE_PRICE_MODE,
        include_meta=(view_mode == "Detail"),
    ),
    width='stretch',
    hide_index=True
)

# ==================== COMMODITIES ====================

st.subheader("🛢 Commodities")
commodity_rows = []
for primary_symbol, name in COMMODITIES.items():
    candidate_symbols = [primary_symbol] + COMMODITY_FALLBACKS.get(primary_symbol, [])

    selected_symbol = None
    selected_df = None
    for symbol in candidate_symbols:
        df = data.get(symbol)
        if df is not None and not df.empty and "Close" in df.columns and not df["Close"].dropna().empty:
            selected_symbol = symbol
            selected_df = df
            break

    price, _, change_pct = get_live_price_safe(selected_symbol or primary_symbol, selected_df, mode=PAGE_PRICE_MODE)

    display_name = name if selected_symbol in (None, primary_symbol) else f"{name} (Proxy)"
    commodity_rows.append({
        "Commodity": display_name,
        "Price": format_price(price),
        "Change %": format_change(change_pct)
    })

st.dataframe(pd.DataFrame(commodity_rows), width='stretch', hide_index=True)

# ==================== CRYPTO ====================

st.subheader("₿ Crypto Markets")
if view_mode == "Detail":
    st.dataframe(
        create_price_table(CRYPTO, data, ["Asset", "Price", "Change %"], mode=PAGE_PRICE_MODE, include_meta=True),
        width='stretch',
        hide_index=True
    )

# ==================== BONDS ====================

st.subheader("📉 Bond Markets")
st.dataframe(
    create_price_table(
        BOND_MARKETS,
        data,
        ["Instrument", "Value", "Change"],
        mode=PAGE_PRICE_MODE,
        include_meta=(view_mode == "Detail"),
    ),
    width='stretch',
    hide_index=True
)

if view_mode == "Detail":
    render_source_freshness(
        {
            "^TNX": "US 10Y Yield",
            "DX-Y.NYB": "Dollar Index",
            "HG=F": "Copper",
            "GC=F": "Gold",
            "^GSPC": "S&P 500",
            "BTC-USD": "Bitcoin",
        },
        data,
        title="Cross-Page Factor Freshness",
    )

st.markdown("---")
st.caption("Data: Yahoo Finance (15-20 min delay) | ✅ Optimized with shared utilities")
