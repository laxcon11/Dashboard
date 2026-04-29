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
st.caption("Institutional Term Structure | Migration Tracking | Adaptive Sensitivity")

from nde_automation_logic import get_historical_snapshot_df

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
@st.cache_data(ttl=300, show_spinner=False)
def load_term_structure_v2():
    return nde_options_logic.compute_term_structure("NIFTY")

term_data = load_term_structure_v2()

if not term_data:
    st.warning("⚠️ No active expiries found. Please fetch or upload data first.")
    st.stop()

# Interpretation Logic
# ... (existing logic) ...

# --- SECTION 0: STRUCTURE OVER TIME (Phase 4.1) ---
st.write("### 🏛️ STRUCTURE OVER TIME (Last 10 Snapshots)")
hist_df = get_historical_snapshot_df(limit=10)
if not hist_df.empty:
    from plotly.subplots import make_subplots
    fig_hist = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig_hist.add_trace(go.Scatter(x=hist_df['date'], y=hist_df['gamma_flip'], name="Gamma Flip", line=dict(color='#ffd600', width=3)), secondary_y=False)
    fig_hist.add_trace(go.Scatter(x=hist_df['date'], y=hist_df['max_pain'], name="Max Pain", line=dict(color='#00c853', dash='dot')), secondary_y=False)
    fig_hist.add_trace(go.Scatter(x=hist_df['date'], y=hist_df['pcr_oi'], name="PCR OI", line=dict(color='#2979ff', width=2)), secondary_y=True)
    
    fig_hist.update_layout(template="plotly_dark", height=300, margin=dict(l=10,r=10,t=10,b=10), 
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    fig_hist.update_yaxes(title_text="Nifty Price / Levels", secondary_y=False)
    fig_hist.update_yaxes(title_text="PCR Ratio", secondary_y=True)
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("No historical snapshots found. Start running automation to build migration history.")

st.write("---")

# --- SECTION 0.1: SURFACE STATE SNAPSHOT ---
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
elif w1_state == "Anchor":
    playbook = "⚓ ANCHOR ZONE: Monthly structural gravity dominates. Sell premium at walls, expect time-decay dominated P&L."
elif w1_state == "Neutral":
    playbook = "⚖️ MIXED SIGNALS: Neutral structural bias. Reduce size, wait for directional confirmation before momentum entry."

# Layout
c1, c2, c3, c4 = st.columns(4)
c1.metric("W1 (Near)", w1_state)
if w2_exp: c2.metric("W2/W3 (Mid)", w2_state)
c3.metric("Monthly", mn_state)
c4.metric("Spot", f"{term_data[w1_exp]['spot']:.0f}")

st.info(f"🎯 **Playbook**: {playbook}")

# --- Phase 4 Enhancement: Rationale & Implication ---
with st.expander("🔍 **Deep Dive: Why this state?**", expanded=True):
    col_a, col_b = st.columns(2)
    
    # Logic for Why
    why_map = {
        "Stable": "Dealers are in a **Long Gamma** regime. They sell into rallies and buy into dips to remain delta-neutral, creating price 'stickiness'.",
        "Fragile": "Dealers are in a **Short Gamma** regime. Hedging requirements force them to sell as price drops and buy as it rises, accelerating volatility.",
        "Anchor": "Large **Monthly Positioning** outweighs weekly flows. The market is structurally attracted to major GEX clusters (Pinning risk).",
        "Neutral": "GEX concentration is low or balanced. No structural dealer bias; market is driven by pure order flow or macro headlines."
    }
    
    # Logic for Implication
    impl_map = {
        "Stable": "Fading extremes at Call/Put walls is high-probability. Expect ranges to hold; Theta-positive strategies favored.",
        "Fragile": "Counter-trend trading is extremely dangerous. Expect 'Slippery' moves and gap risk. Delta-neutral setups require frequent rebalancing.",
        "Anchor": "Price will likely 'magnetize' towards the primary GEX cluster by expiry. Avoid momentum bets far from the anchor strike.",
        "Neutral": "Lower conviction for systematic setups. Tighten stop-losses and wait for a clear Gamma Flip or Vanna shift."
    }
    
    with col_a:
        st.subheader("💡 Analytical Drivers")
        st.write(why_map.get(w1_state, "Surface complexity is high; see detailed heatmap below."))
        
    with col_b:
        st.subheader("⚔️ Tactical Implications")
        st.write(impl_map.get(w1_state, "Monitor Gamma Flip level for directional confirmation."))

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
        "GEX Net": f"{m.get('gex_net_norm', 0.0):.1f} M" if 'Pro' in scale_mode else f"₹{m.get('gex_net', 0)/1e7:.1f} Cr",
        "TW Gravity": f"{m.get('gex_tw_norm', 0.0):.1f} M" if "Pro" in scale_mode else "---",
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
    column_config={
        "TW Gravity": st.column_config.TextColumn(
            "TW Gravity",
            help="Time-Weighted GEX: Normalizes gamma gravity by days remaining. Higher = stronger near-term pinning pressure."
        )
    },
    hide_index=True, use_container_width=True
)

# --- SECTION 2: SURFACE CURVES ---
c1, c2 = st.columns(2)
with c1:
    st.subheader("Gamma Surface (Pin Gravity)")
    y_vals = [m["gex_net_norm"] for m in term_data.values()] 
    y_tw = [m.get("gex_tw_norm", 0.0) for m in term_data.values()]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=exp_list, y=y_vals, mode='lines+markers', name="Raw GEX (M/lot)", line=dict(color='#37474f', dash='dot')))
    fig.add_trace(go.Scatter(x=exp_list, y=y_tw, mode='lines+markers', name="TW Gravity (Pinning)", line=dict(color='#00c853', width=4)))
    
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        template="plotly_dark", height=300, 
        margin=dict(l=10, r=10, t=10, b=10), 
        yaxis_title="GEX (M INR / lot)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)
with c2:
    st.subheader("Vega Curve")
    y_v = [m["vega_norm"] for m in term_data.values()] # Already in Millions-per-lot
    fig_v = go.Figure(go.Bar(x=exp_list, y=y_v, marker_color='#2979ff'))
    fig_v.update_layout(
        template="plotly_dark", height=300, 
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Vega (M INR / lot)"
    )
    st.plotly_chart(fig_v, use_container_width=True)

# Row 2: Theta + IV Term Structure
c3, c4 = st.columns(2)
with c3:
    st.subheader("Theta Decay Curve (Income)")
    y_theta = [m["theta_norm"] for m in term_data.values()]
    fig_theta = go.Figure(go.Bar(x=exp_list, y=y_theta, marker_color='#ff9100'))
    fig_theta.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_theta.update_layout(
        template="plotly_dark", height=300, 
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Theta (M INR / lot)"
    )
    st.plotly_chart(fig_theta, use_container_width=True)
with c4:
    st.subheader("IV Term Structure")
    y_iv = [m["atm_iv"] for m in term_data.values()]
    y_dte = [m["dte"] for m in term_data.values()]
    fig_iv = go.Figure()
    fig_iv.add_trace(go.Scatter(
        x=y_dte, y=y_iv, mode='lines+markers+text',
        text=exp_list, textposition='top center', textfont=dict(size=9),
        line=dict(color='#e040fb', width=3),
        marker=dict(size=8)
    ))
    # Contango/Backwardation detection
    if len(y_iv) >= 2:
        slope = y_iv[-1] - y_iv[0]
        label = "Inverted (Far > Near)" if slope > 0 else "Normal (Near > Far)"
        color = "#ff1744" if slope > 0 else "#00c853"
        fig_iv.add_annotation(x=y_dte[-1], y=max(y_iv), text=label, 
                             font=dict(color=color, size=12), showarrow=False)
    fig_iv.update_layout(
        template="plotly_dark", height=300, 
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Days to Expiry", yaxis_title="ATM IV (%)"
    )
    st.plotly_chart(fig_iv, use_container_width=True)

st.write("---")

# --- SECTION 3: STRIKE LADDER & PRESSURE (Phase 4.1) ---
st.header("🪜 SECTION 3: STRIKE LADDER (Selected Expiry)")
sel_exp = st.selectbox("Select Expiry for Pressure Analysis", exp_list, index=0)

if sel_exp in term_data:
    m = term_data[sel_exp]
    df_exp = m.get("raw_exposures")
    if df_exp is not None:
        ladder_metric = st.radio("Ladder Metric", ["GEX (Institutional)", "Open Interest (Walls)"], horizontal=True, index=0)
        col_to_use = "gex_net" if "GEX" in ladder_metric else "oi"
        
        # Group by strike and type for true pressure splitting
        ladder_df = df_exp.groupby(["strike", "type"]).agg({col_to_use: "sum"}).reset_index()
        
        # Filter around spot
        spot = m["spot"]
        ladder_df = ladder_df[(ladder_df["strike"] >= spot*0.95) & (ladder_df["strike"] <= spot*1.05)]
        
        # Split sides
        calls = ladder_df[ladder_df["type"] == "call"]
        puts = ladder_df[ladder_df["type"] == "put"]
        
        fig_ladder = go.Figure()
        # Calls (Negative for divergent look)
        fig_ladder.add_trace(go.Bar(y=calls["strike"], x=calls[col_to_use] * -1, 
                                   orientation='h', name="CALLS", marker_color="#ff1744"))
        # Puts
        fig_ladder.add_trace(go.Bar(y=puts["strike"], x=puts[col_to_use], 
                                   orientation='h', name="PUTS", marker_color="#00c853"))
        
        # Overlays
        fig_ladder.add_hline(y=spot, line_color="#2979ff", line_width=4, annotation_text="SPOT")
        if m.get('flip'): fig_ladder.add_hline(y=m['flip'], line_color="#ffd600", line_dash="dash", annotation_text="FLIP")
        
        fig_ladder.update_layout(template="plotly_dark", height=600, barmode='relative',
                                  xaxis_title=ladder_metric, yaxis_title="Strike",
                                  legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_ladder, use_container_width=True)

st.write("---")

# --- SECTION 4: ADVANCED SURFACE ANALYSIS ---
with st.expander("🔥 **ADVANCED: Multi-Expiry Surface Heatmap**", expanded=False):
    st.subheader("Multi-Expiry Exposure Matrix")

    # Filter Range (Expanded to ensure key markers like Flips are visible)
    spot = term_data[w1_exp]["spot"]
    strike_step = 50.0
    range_pts = 25 # Increased from 10 to 25 for broader surface visibility 
    lower = int((spot - range_pts*strike_step) / strike_step) * strike_step
    upper = int((spot + range_pts*strike_step) / strike_step) * strike_step
    strikes = np.arange(lower, upper + strike_step, strike_step)

    heatmap_matrix = []
    overlay_markers = {"call_wall": [], "put_wall": [], "flip": [], "max_pain": []}

    grouped_exposures = {}
    # Identify Walls (Max OI per expiry) and pre-group DataFrames
    for exp, m in term_data.items():
        df_exp = m.get("raw_exposures")
        if df_exp is not None and not df_exp.empty:
            calls = df_exp[df_exp["type"]=="call"]
            puts = df_exp[df_exp["type"]=="put"]
            
            c_wall = float(df_exp.loc[calls["oi"].idxmax()]["strike"]) if not calls.empty else None
            p_wall = float(df_exp.loc[puts["oi"].idxmax()]["strike"]) if not puts.empty else None
            
            if c_wall: overlay_markers["call_wall"].append((exp, c_wall))
            if p_wall: overlay_markers["put_wall"].append((exp, p_wall))
            if m.get("flip"): overlay_markers["flip"].append((exp, m["flip"]))
            
            # Phase 46: Max Pain Integration
            mp = nde_options_logic.calculate_max_pain(df_exp)
            if mp: overlay_markers["max_pain"].append((exp, mp))
            
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
        heatmap_matrix.append(row)

    if heatmap_matrix:
        df_heat = pd.DataFrame(heatmap_matrix).sort_values("Strike", ascending=False)
        z_vals = df_heat[exp_list].values

        # Plotly Heatmap
        fig_heat = go.Figure()
        hover_label = "Exposure" if metric_mode == "Net GEX" else "Size" if metric_mode == "OI" else "Sensitivity"
        unit_label = "Cr" if metric_mode == "Net GEX" else "Lakh" if metric_mode == "OI" else "M"

        fig_heat.add_trace(go.Heatmap(
            z=z_vals, x=exp_list, y=df_heat["Strike"],
            colorscale='IceFire' if metric_mode == "Net GEX" else 'Viridis' if metric_mode == "OI" else 'RdGy',
            zmid=0 if metric_mode != "OI" else None,
            colorbar=dict(title=f"{metric_mode} ({unit_label})"),
            hovertemplate="<b>Strike: %{y}</b><br>Expiry: %{x}<br>"+f"{hover_label}: %{{z:.2f}} {unit_label}<br>"+"<extra></extra>"
        ))

        # 🎯 Market Anchors
        fig_heat.add_hline(y=spot, line_dash="dash", line_color="white", line_width=2, annotation_text=f"Live Spot ({spot:.1f})")

        # Call Walls (▲)
        fig_heat.add_trace(go.Scatter(
            x=[v[0] for v in overlay_markers["call_wall"]], y=[v[1] for v in overlay_markers["call_wall"]], 
            mode='markers', marker=dict(symbol='triangle-up', color='black', size=14, line=dict(color='white', width=1)), 
            name="Max Call OI", showlegend=False
        ))
        # Put Walls (▼)
        fig_heat.add_trace(go.Scatter(
            x=[v[0] for v in overlay_markers["put_wall"]], y=[v[1] for v in overlay_markers["put_wall"]], 
            mode='markers', marker=dict(symbol='triangle-down', color='black', size=14, line=dict(color='white', width=1)), 
            name="Max Put OI", showlegend=False
        ))
        # Flip (✦)
        fig_heat.add_trace(go.Scatter(
            x=[v[0] for v in overlay_markers["flip"]], y=[v[1] for v in overlay_markers["flip"]], 
            mode='markers', marker=dict(symbol='diamond', color='cyan', size=10, line=dict(color='white', width=1)), 
            name="Flip", showlegend=False
        ))

        fig_heat.update_layout(
            title=dict(text=f"Institutional Strategy Map: {metric_mode} Surface", x=0.5),
            template="plotly_dark", height=750, margin=dict(l=40, r=40, t=60, b=40),
            yaxis=dict(title="Strike", dtick=50), xaxis=dict(title="Expiry")
        )
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("Insufficient data to build Multi-Expiry Surface.")

st.write("---")
st.caption(" institutional-grade multi-expiry surface analytics. Decision logic is lot-invariant.")
