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
    st.warning("FRED API key not found. Please set it in your .env file.")
    st.stop()

# ==================== FETCH DATA ====================

rows = []
series_data = {}

with st.spinner("Fetching liquidity data..."):
    for series_id, name in FRED_SERIES.items():
        df = fetch_fred_series(series_id, FRED_API_KEY, days=30)

        if df is not None and len(df) > 0:
            latest_value = df["value"].iloc[-1]
            latest_date = df["date"].iloc[-1]

            rows.append({
                "Indicator": name,
                "Latest Value": round(latest_value, 2),
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

st.subheader("Latest Liquidity Indicators")
st.dataframe(pd.DataFrame(rows), use_container_width=True)

# ==================== TREND CHARTS ====================

st.subheader("Trend View (Last 30 observations)")

for name, df in series_data.items():
    with st.expander(name):
        st.line_chart(df.set_index("date")["value"])
