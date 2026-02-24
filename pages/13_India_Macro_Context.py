import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import FRED_API_KEY, FRED_SERIES_INDIA_MACRO
from data_fetch import fetch_fred_batch
from utils import get_ui_detail_mode, render_key_observations, setup_page


setup_page("India Macro Context")
_ = get_ui_detail_mode("Summary")

st.title("🌐 India Macro Context")
st.caption("Global macro tailwinds/headwinds for Indian equities using FRED series.")

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

gcol1, gcol2 = st.columns([1, 2])
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
    c1, c2, c3 = st.columns(3)
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
