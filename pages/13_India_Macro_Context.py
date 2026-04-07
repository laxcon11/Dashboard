import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import FRED_API_KEY, FRED_SERIES_INDIA_MACRO
from data_fetch import fetch_fred_batch
from india_context import get_india_macro_signals_v1
from utils import get_ui_detail_mode, render_key_observations, setup_page, get_ui_device_mode, responsive_cols as _responsive_cols

print(f"DEBUG: get_india_macro_signals_v1 imported: {get_india_macro_signals_v1 is not None}")


setup_page("India Macro Context")
_ = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"


# _responsive_cols imported from utils

st.title("🌐 India Macro Context")
st.caption("Global macro tailwinds/headwinds for Indian equities using FRED series.")
st.caption(f"Device mode: **{device_mode}**")

if not FRED_API_KEY:
    st.error("FRED_API_KEY not found in .env. This module requires FRED access.")
    st.stop()

INDIA_RELEVANCE = {
    "USD/INR Exchange Rate": "Rising USD/INR can pressure INR and foreign flows; falling USD/INR is usually supportive for Indian risk assets.",
    "US CPI (YoY)": "Higher US CPI can keep Fed policy tight, supporting USD and pressuring EM flows including India.",
    "US Core PCE": "Core PCE drives Fed reaction function; persistent rise often raises global discount rates.",
    "US Unemployment Rate": "Moderate labor softness can ease rate fears; sharp spikes can signal global growth stress.",
    "US Industrial Production": "Improving US production supports external demand and global cyclical sentiment.",
    "WTI Crude Oil Price": "Higher crude raises India import bill and inflation pressure; softer crude is typically supportive.",
    "Gold Price (FRED)": "Rapid gold strength can indicate risk aversion and USD stress periods for EM assets.",
    "US 10Y Yield": "Higher US 10Y raises global hurdle rates and may reduce relative EM equity appeal.",
    "ECB Balance Sheet (EUR bn)": "Expanding ECB balance sheet supports global liquidity conditions.",
    "US Credit Spread (BAA-AAA)": "Widening spread signals rising credit risk aversion; tighter spread is risk supportive.",
}

POSITIVE_WHEN_RISING = {
    "US Industrial Production",
    "ECB Balance Sheet (EUR bn)",
}
NEGATIVE_WHEN_RISING = {
    "USD/INR Exchange Rate",
    "US CPI (YoY)",
    "US Core PCE",
    "WTI Crude Oil Price",
    "Gold Price (FRED)",
    "US 10Y Yield",
    "US Credit Spread (BAA-AAA)",
}

with st.spinner("Loading India-relevant macro series from FRED..."):
    batch = fetch_fred_batch(FRED_SERIES_INDIA_MACRO, FRED_API_KEY, days=180)

if not batch:
    st.warning("No series could be loaded from FRED right now.")
    st.stop()

scores = {}
observations = []
metric_rows = []

for name, df in batch.items():
    if df is None or df.empty or "value" not in df.columns:
        continue
    s = pd.to_numeric(df["value"], errors="coerce").dropna()
    if len(s) < 2:
        continue
    current = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    delta = current - prev
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")

    if name in POSITIVE_WHEN_RISING:
        score = 1 if delta > 0 else (-1 if delta < 0 else 0)
    elif name in NEGATIVE_WHEN_RISING:
        score = -1 if delta > 0 else (1 if delta < 0 else 0)
    else:
        # Neutral default for ambiguous changes (e.g., unemployment level nuance)
        score = 0 if abs(delta) < 1e-9 else (-1 if delta > 0 else 1)

    scores[name] = score
    metric_rows.append(
        {
            "Indicator": name,
            "Current": current,
            "Delta": delta,
            "Arrow": arrow,
            "Score": score,
        }
    )
    if score != 0:
        direction = "Tailwind" if score > 0 else "Headwind"
        observations.append(f"{name}: {arrow} ({direction})")

composite_score = int(sum(scores.values()))
label = "Tailwind" if composite_score > 0 else ("Headwind" if composite_score < 0 else "Neutral")
color = "#10b981" if composite_score > 0 else ("#ef4444" if composite_score < 0 else "#f59e0b")

gcol1, gcol2 = _responsive_cols(2, [1, 2])
with gcol1:
    st.metric("Composite Score", composite_score, label)
with gcol2:
    fig_g = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=composite_score,
            gauge={
                "axis": {"range": [-10, 10]},
                "bar": {"color": color},
                "steps": [
                    {"range": [-10, 0], "color": "#fee2e2"},
                    {"range": [0, 10], "color": "#dcfce7"},
                ],
            },
            title={"text": "Global Macro Headwind / Tailwind"},
        )
    )
    fig_g.update_layout(height=220, margin=dict(l=10, r=10, t=35, b=10))
    st.plotly_chart(fig_g, width="stretch")

render_key_observations(observations, title="🔎 Key Observations", max_items=8)

st.markdown("### Indicator Snapshot")
metrics_df = pd.DataFrame(metric_rows)
if metrics_df.empty:
    st.info("Insufficient data to compute indicator deltas.")
else:
    c1, c2, c3 = _responsive_cols(3)
    for i, (_, row) in enumerate(metrics_df.iterrows()):
        col = [c1, c2, c3][i % 3]
        with col:
            st.metric(
                row["Indicator"],
                f"{row['Current']:.2f}",
                f"{row['Arrow']} {row['Delta']:+.2f}",
            )

st.markdown("---")
st.markdown("### 6-Month Time Series")
for name, df in batch.items():
    if df is None or df.empty or not {"date", "value"}.issubset(df.columns):
        continue
    chart_df = df.copy()
    chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
    chart_df["value"] = pd.to_numeric(chart_df["value"], errors="coerce")
    chart_df = chart_df.dropna(subset=["date", "value"]).sort_values("date").tail(180)
    if chart_df.empty:
        continue

    fig = go.Figure(
        data=[
            go.Scatter(
                x=chart_df["date"],
                y=chart_df["value"],
                mode="lines",
                line={"width": 2},
                name=name,
            )
        ]
    )
    fig.update_layout(
        height=260,
        margin=dict(l=20, r=20, t=40, b=20),
        title=name,
        xaxis_title="Date",
        yaxis_title="Value",
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(f"India relevance: {INDIA_RELEVANCE.get(name, 'Context mapping not configured yet.')}")

st.markdown("---")
st.markdown("## 🇮🇳 Domestic Macro Pillars")
st.caption("GST Trends & Government Bond Yield Curve (Source: PIB/CCIL/Trading Economics)")

india_signals = get_india_macro_signals_v1()
gst = india_signals.get("gst", {})
curve = india_signals.get("curve", {})
gst_hist = india_signals.get("gst_history", [])

dcol1, dcol2 = _responsive_cols(2)

with dcol1:
    st.markdown("#### 🛍️ GST Collection")
    if gst.get("status") != "UNAVAILABLE":
        gst_val = gst.get("latest_collection", 0)
        gst_yoy = gst.get("yoy_growth", 0)
        gst_mom = gst.get("mom_growth", 0)
        gst_signal = gst.get("demand_signal", "Neutral")
        
        ath_badge = " 🏆 **ALL TIME HIGH**" if gst.get("is_all_time_high") else ""
        
        st.metric(
            "Latest Collection",
            f"₹{gst_val:.2f} L Cr",
            f"{gst_yoy:+.1f}% YoY",
            delta_color="normal"
        )
        st.write(f"**Demand Signal**: {gst_signal}{ath_badge}")
        st.caption(f"MoM: {gst_mom:+.1f}% | 3M Avg: ₹{gst.get('three_month_avg', 0):.2f} L Cr")
        st.info(f"Listed companies (0.62% of base) contribute **{gst.get('listed_contribution', 'N/A')}%** of revenue.")
        
        if gst_hist:
            gh_df = pd.DataFrame(gst_hist)
            gh_df["month"] = pd.to_datetime(gh_df["month"])
            
            # Show YoY Growth Chart
            fig_gst = go.Figure()
            fig_gst.add_trace(go.Bar(
                x=gh_df["month"],
                y=gh_df["gst_collection_lakh_cr"],
                name="Collection",
                marker_color="#1f77b4",
                opacity=0.6
            ))
            fig_gst.add_trace(go.Scatter(
                x=gh_df["month"],
                y=gh_df["gst_3m_avg"],
                name="3M Avg",
                line=dict(color="#ff7f0e", width=3)
            ))
            fig_gst.update_layout(
                height=300, 
                title="GST Collection Trend (Lakh Cr)",
                margin=dict(l=10, r=10, t=40, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_gst, use_container_width=True)
    else:
        st.warning("GST data unavailable.")

with dcol2:
    st.markdown("#### 📈 India Yield Curve")
    if curve.get("status") != "UNAVAILABLE":
        y10 = curve.get("ten_year_yield", 0)
        y3m = curve.get("three_month_yield", 0)
        spread = curve.get("spread_bps", 0)
        
        st.metric("10Y - 3M Spread", f"{spread} bps", f"{y10:.2f}% (10Y) / {y3m:.2f}% (3M)")
        st.write("**Curve State**: Positive Upward Slope" if spread > 0 else "**Curve State**: Inverted")
        st.caption(f"As of: {curve.get('as_of', 'Recent')}")
        
        st.markdown("---")
        st.markdown("**Official Portals & Sources**")
        for link in gst.get("portal_links", []) + curve.get("sources", []):
            st.markdown(f"- [{link['name']}]({link['url']})")
    else:
        st.warning("Yield curve data unavailable.")
