import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
import json
from pathlib import Path

import nde_options_logic
from utils import setup_page

setup_page("NSE Monthly Engine V2")

# --- UI HEADER ---
st.title("🏛️ NSE Monthly Engine V2")
st.caption("Institutional Term Structure | Migration Tracking | Adaptive Sensitivity")

# --- CONFIG & TOGGLES ---
with st.sidebar:
    st.header("⚙️ Engine Controls")
    metric_mode = st.radio("Heatmap Metric", ["Net GEX", "OI", "Vega"], index=0)
    scale_mode = st.radio("Display Scale", ["Raw (Total)", "Pro (Per-Lot)"], index=1)
    show_historical = st.checkbox("Show Migration Deltas", value=True)
    if st.button("♻️ Clear Snap Cache"):
        snap_path = Path("data/term_structure_snap.json")
        if snap_path.exists(): snap_path.unlink()
        st.cache_data.clear()
        st.rerun()

# --- DATA LAYER ---
@st.cache_data(ttl=60, show_spinner=False)
def load_term_structure_v2():
    return nde_options_logic.compute_term_structure("NIFTY")

term_data = load_term_structure_v2()

if not term_data:
    st.warning("⚠️ No active expiries found. Please fetch or upload data first.")
    st.stop()

# --- SECTION 0: SURFACE STATE SUMMARY CARD ---
st.write("### 🧭 SURFACE STATE SNAPSHOT")
exp_list = list(term_data.keys())
w1_exp = exp_list[0]
w2_exp = exp_list[1] if len(exp_list) > 1 else None
mn_exp = exp_list[-1]

w1_state = term_data[w1_exp]["state"]
w2_state = term_data[w2_exp]["state"] if w2_exp else "Unknown"
mn_state = term_data[mn_exp]["state"]

# Interpretation Logic
playbook = "Standard Mean Reversion"
if w1_state == "Stable":
    if w2_state == "Fragile":
        playbook = "⚠️ CAUTION: Near-term Pinned, Mid-term Breakout Risk. Reduce Size."
    else:
        playbook = "✅ OPTIMAL: High Stability Across Front weeks. Sell Premium."
elif w1_state == "Fragile":
    playbook = "🚀 TREND PRIORITY: Negative Gamma breakout likely. Momentum Scaling."

# Layout
c1, c2, c3, c4 = st.columns(4)
c1.metric("W1 (Near)", w1_state)
if w2_exp: c2.metric("W2/W3 (Mid)", w2_state)
c3.metric("Monthly", mn_state)
c4.metric("Spot", f"{term_data[w1_exp]['spot']:.0f}")

st.info(f"🎯 **Playbook**: {playbook}")

st.write("---")

# --- SECTION 1: EXPIRY SUMMARY & MIGRATION ---
st.header("📊 SECTION 1: TERM STRUCTURE DETAILS")

summary_rows = []
for exp, m in term_data.items():
    summary_rows.append({
        "Expiry": exp,
        "DTE": m["dte"],
        "State": m["state"],
        "ATM IV": f"{m['atm_iv']:.1f}%",
        f"GEX Net (Scaled)": f"{m['ui_display']['gex_net_norm'] if 'Pro' in scale_mode else m['ui_display']['gex_net']} {m['ui_display']['delta_gex']}",
        "Flip": f"{m['flip']:.0f}" if m['flip'] > 0 else ("N/A (Short)" if m['gex_net'] < 0 else "N/A (Long)"),
        "Flip Dist": f"{m['flip_dist']:.1f}%" if m['flip'] > 0 else "---",
        "IV Adj": f"{m['iv_adj']}x"
    })

df_summary = pd.DataFrame(summary_rows)

def color_state(val):
    c = {"Stable": "#00c853", "Fragile": "#ff1744", "Anchor": "#2979ff", "Neutral": "gray"}.get(val, "gray")
    return f"color: {c}; font-weight: bold"

st.dataframe(
    df_summary.style.applymap(color_state, subset=["State"]),
    hide_index=True, use_container_width=True
)

# --- SECTION 2: SURFACE CURVES ---
c1, c2 = st.columns(2)
with c1:
    st.subheader("Gamma Surface (Normalized)")
    y_vals = [m["gex_net_norm"] for m in term_data.values()] # Already in Millions-per-lot
    fig = go.Figure(go.Scatter(x=exp_list, y=y_vals, mode='lines+markers', line=dict(color='#00c853', width=3)))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
with c2:
    st.subheader("Vega Curve")
    y_v = [m["vega_norm"] for m in term_data.values()] # Already in Millions-per-lot
    fig_v = go.Figure(go.Bar(x=exp_list, y=y_v, marker_color='#2979ff'))
    fig_v.update_layout(template="plotly_dark", height=300, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_v, use_container_width=True)

st.write("---")

# --- SECTION 3: STRIKE GEX HEATMAP V2 ---
st.header("🔥 SECTION 3: STRIKE DENSITY HEATMAP")

# Filter Range
spot = term_data[w1_exp]["spot"]
strike_step = 50.0
range_pts = 10 
lower = int((spot - range_pts*strike_step) / strike_step) * strike_step
upper = int((spot + range_pts*strike_step) / strike_step) * strike_step
strikes = np.arange(lower, upper + strike_step, strike_step)

heatmap_matrix = []
overlay_markers = {"call_wall": [], "put_wall": [], "flip": []}

grouped_exposures = {}
# Identify Walls (Max OI per expiry) and pre-group DataFrames
for exp, m in term_data.items():
    df_exp = m.get("raw_exposures")
    if df_exp is None:
        fname = m.get("filename", f"option-chain-ED-NIFTY-{exp}.csv")
        df_exp, _ = nde_options_logic.parse_nse_option_chain_csv(Path("data/option_chain") / fname)
        
    if df_exp is not None and not df_exp.empty:
        calls = df_exp[df_exp["type"]=="call"]
        puts = df_exp[df_exp["type"]=="put"]
        
        # Use idxmax for efficiency instead of sort_values
        c_wall = float(df_exp.loc[calls["oi"].idxmax()]["strike"]) if not calls.empty else None
        p_wall = float(df_exp.loc[puts["oi"].idxmax()]["strike"]) if not puts.empty else None
        
        if c_wall: overlay_markers["call_wall"].append((exp, c_wall))
        if p_wall: overlay_markers["put_wall"].append((exp, p_wall))
        
        # Pre-group by strike for O(1) inner loop lookup
        grouped_exposures[exp] = df_exp.groupby("strike")[["gex_net", "oi", "vega_exp"]].sum()

for s in strikes:
    row = {"Strike": int(s)}
    for exp, m in term_data.items():
        if exp in grouped_exposures and s in grouped_exposures[exp].index:
            s_row = grouped_exposures[exp].loc[s]
            
            # Metric Logic
            if metric_mode == "Net GEX":
                val = s_row["gex_net"] / 1e7
            elif metric_mode == "OI":
                val = s_row["oi"] / 1e5
            else: # Vega
                val = s_row["vega_exp"] / 1e6
        else:
            val = 0.0
            
        row[exp] = val
        
        # Markers
        if s == m["flip"]:
            overlay_markers["flip"].append((exp, s))
            
    heatmap_matrix.append(row)

df_heat = pd.DataFrame(heatmap_matrix).sort_values("Strike", ascending=False)
z_vals = df_heat[exp_list].values

# Plotly Heatmap
fig_heat = go.Figure()
fig_heat.add_trace(go.Heatmap(
    z=z_vals, x=exp_list, y=df_heat["Strike"],
    colorscale='RdYlGn' if metric_mode != "OI" else 'Blues',
    zmid=0 if metric_mode != "OI" else None,
    colorbar=dict(title=f"{metric_mode}")
))

# Call Walls (▲)
cw_x = [v[0] for v in overlay_markers["call_wall"]]
cw_y = [v[1] for v in overlay_markers["call_wall"]]
fig_heat.add_trace(go.Scatter(x=cw_x, y=cw_y, mode='markers', marker=dict(symbol='triangle-up', color='black', size=12), name="Call Wall"))

# Put Walls (▼)
pw_x = [v[0] for v in overlay_markers["put_wall"]]
pw_y = [v[1] for v in overlay_markers["put_wall"]]
fig_heat.add_trace(go.Scatter(x=pw_x, y=pw_y, mode='markers', marker=dict(symbol='triangle-down', color='black', size=12), name="Put Wall"))

# Flip (✦)
fl_x = [v[0] for v in overlay_markers["flip"]]
fl_y = [v[1] for v in overlay_markers["flip"]]
fig_heat.add_trace(go.Scatter(x=fl_x, y=fl_y, mode='markers', marker=dict(symbol='diamond', color='white', size=8), name="Gamma Flip"))

fig_heat.update_layout(template="plotly_dark", height=700, margin=dict(l=20, r=20, t=20, b=20), yaxis=dict(dtick=50))
st.plotly_chart(fig_heat, use_container_width=True)

st.write("---")
st.caption(" institutional-grade multi-expiry surface analytics. Decision logic is lot-invariant.")
