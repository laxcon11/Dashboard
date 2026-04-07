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
    get_ui_device_mode,
    render_source_freshness,
)

setup_page("Global Markets")
view_mode = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"


def _compact_table(df: pd.DataFrame, preferred_cols: list[str]) -> pd.DataFrame:
    if not is_mobile or df is None or df.empty:
        return df
    keep = [c for c in preferred_cols if c in df.columns]
    return df[keep] if keep else df

st.title("🌍 Global Macro Dashboard")
st.caption("Markets snapshot helps identify global risk sentiment before trading.")
st.caption(f"Device mode: **{device_mode}**")
PAGE_PRICE_MODE = "close_only"

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
if view_mode == "Detail":
    with st.expander("🔍 Data Status", expanded=False):
        st.write(f"**Requested**: {len(all_symbols)} symbols")
        st.write(f"**Retrieved**: {len(data)} symbols")

        if len(data) < len(all_symbols):
            missing = [s for s in all_symbols if s not in data]
            st.warning(f"⚠️ Missing: {', '.join(missing[:10])}")

# ==================== GLOBAL RISK SNAPSHOT ====================

st.subheader("📊 Global Risk Snapshot")

cols = st.columns(1 if is_mobile else len(GLOBAL_RISK_SNAPSHOT))

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
indices_df = create_price_table(
    GLOBAL_INDICES,
    data,
    ["Index", "Price", "Change %"],
    mode=PAGE_PRICE_MODE,
    include_meta=(view_mode == "Detail"),
)
st.dataframe(
    _compact_table(indices_df, ["Index", "Price", "Change %"]),
    width='stretch',
    hide_index=True
)

# ==================== CURRENCIES ====================

st.subheader("💱 Currency Markets")
currency_df = create_price_table(
    CURRENCIES,
    data,
    ["Pair", "Price", "Change %"],
    mode=PAGE_PRICE_MODE,
    include_meta=(view_mode == "Detail"),
)
st.dataframe(
    _compact_table(currency_df, ["Pair", "Price", "Change %"]),
    width='stretch',
    hide_index=True
)

# ==================== COMMODITIES ====================

st.subheader("🛢 Commodities")
commodity_rows = []
include_meta = (view_mode == "Detail")

# Fetch telemetry once if in detail mode
telemetry_map = {}
if include_meta:
    try:
        from data_fetch import get_last_batch_telemetry
        telem = get_last_batch_telemetry()
        if telem is not None and not telem.empty:
            for _, row in telem.iterrows():
                telemetry_map[str(row.get("symbol"))] = {
                    "source": row.get("source", "UNKNOWN"),
                    "age_bdays": row.get("age_bdays"),
                }
    except Exception:
        pass

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
    
    as_of = "N/A"
    if selected_df is not None and not selected_df.empty:
        idx = getattr(selected_df, "index", None)
        if isinstance(idx, pd.DatetimeIndex) and len(idx) > 0:
            as_of = idx[-1].strftime("%Y-%m-%d")

    display_name = name if selected_symbol in (None, primary_symbol) else f"{name} (Proxy)"
    
    row = {
        "Commodity": display_name,
        "Price": format_price(price),
        "Change %": format_change(change_pct)
    }
    
    if include_meta:
        meta = telemetry_map.get(selected_symbol or primary_symbol, {})
        row["Source"] = meta.get("source", "API")
        age = meta.get("age_bdays")
        row["Age(BD)"] = "-" if age is None or pd.isna(age) else int(age)
        row["As Of"] = as_of
        
    commodity_rows.append(row)

commodity_df = pd.DataFrame(commodity_rows)
st.dataframe(
    _compact_table(commodity_df, ["Commodity", "Price", "Change %"]),
    width='stretch',
    hide_index=True
)

# ==================== CRYPTO ====================

st.subheader("₿ Crypto Markets")
crypto_df = create_price_table(
    CRYPTO, 
    data, 
    ["Asset", "Price", "Change %"], 
    mode=PAGE_PRICE_MODE, 
    include_meta=(view_mode == "Detail")
)
st.dataframe(
    _compact_table(crypto_df, ["Asset", "Price", "Change %"]),
    width='stretch',
    hide_index=True
)

# ==================== BONDS ====================

st.subheader("📉 Bond Markets")
bond_df = create_price_table(
    BOND_MARKETS,
    data,
    ["Instrument", "Value", "Change"],
    mode=PAGE_PRICE_MODE,
    include_meta=(view_mode == "Detail"),
)
st.dataframe(
    _compact_table(bond_df, ["Instrument", "Value", "Change"]),
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
