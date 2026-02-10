"""
Money Supply Dashboard - OPTIMIZED VERSION

Optimizations:
- Uses FRED_SERIES from config
- Better error handling
- Cleaner structure
"""

import streamlit as st
import pandas as pd

from config import FRED_SERIES, FRED_API_KEY
from data_fetch import fetch_fred_series

st.set_page_config(page_title="Liquidity Dashboard", layout="wide")

st.title("💰 Liquidity & Money Supply Dashboard")

st.caption(
    "Tracks major global liquidity indicators. "
    "Rising balance sheet or falling reverse repo generally supports liquidity."
)

# ==================== API KEY CHECK ====================

if not FRED_API_KEY:
    st.error("⚠️ FRED API key not found in .env file")
    st.info("Get a free API key at: https://fred.stlouisfed.org/docs/api/api_key.html")
    st.stop()

# ==================== FETCH DATA ====================

rows = []
series_data = {}

with st.spinner("Fetching liquidity data..."):
    for name, series_id in FRED_SERIES.items():
        df = fetch_fred_series(series_id, FRED_API_KEY, days=30)

        if df is not None and len(df) > 0:
            latest_value = df["value"].iloc[-1]
            latest_date = df["date"].iloc[-1]

            rows.append({
                "Indicator": name,
                "Latest Value": f"{latest_value:,.2f}",
                "Last Updated": latest_date.date()
            })

            series_data[name] = df
        else:
            rows.append({
                "Indicator": name,
                "Latest Value": "N/A",
                "Last Updated": "N/A"
            })

# ==================== SUMMARY TABLE ====================

st.subheader("📊 Latest Liquidity Indicators")

if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.warning("No liquidity data available")

# ==================== TREND CHARTS ====================

st.subheader("📈 Trend View (Last 30 observations)")

if series_data:
    for name, df in series_data.items():
        with st.expander(name):
            st.line_chart(df.set_index("date")["value"])
else:
    st.info("No trend data available")

st.markdown("---")
st.caption("Data: FRED (Federal Reserve Economic Data) | ✅ Optimized structure")