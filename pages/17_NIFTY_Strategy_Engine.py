import streamlit as st
import pandas as pd
import numpy as np
import json
import re
import html
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path

safe = lambda s: html.escape(str(s)) if s else ""

# v3 Calibration Core (Moved to top to prevent circularity)
import NSE_Config
LOT = NSE_Config.NIFTY_LOT_SIZE
CONFIG_VERSION = NSE_Config.CONFIG_VERSION

# Core Logic Imports
import nde_options_logic
import nde_automation_logic
import nde_strategy_logic
from data_fetch import batch_download, fetch_nse_option_chain
from regime_state import load_regime_history, load_regime_snapshot
from utils import setup_page, get_ui_detail_mode, get_ui_device_mode

# ⚙️ STRATEGY SIDEBAR
with st.sidebar:
    st.header("🎯 Strategy Tuning")
    view_mode = get_ui_detail_mode(default="Summary")
    st.write("---")
    mode = st.radio("Execution Bias", ["Defensive", "Balanced", "Aggressive"], index=1, help="Adjusts strike widening/tightness.")
    st.caption(f"Engine: `{CONFIG_VERSION}`")

    with st.expander("🛠️ Data Operations Hub", expanded=False):
        st.subheader("🌐 Greeks Ingestion")
        
        # ── Auto-convert check ─
        if "auto_convert_checked" not in st.session_state:
            _converted = nde_automation_logic.auto_convert_raw_files()
            if _converted:
                st.toast(f"🔄 Auto-converted {_converted} raw files", icon="🦅")
            st.session_state.auto_convert_checked = True

        status = nde_automation_logic.get_ingestion_hub_context()
        if status["is_active"]:
            st.success(f"🦅 Active · {status['sensi_count']} exp · {status['age_mins']}m ago")
        else:
            st.warning("⏳ Data Stale or Missing")

        if st.button("📥 Process Local Folder", use_container_width=True):
            import nde_scripts_bridge
            with st.spinner("Processing..."):
                nde_scripts_bridge.run_ingestion_cycle()
                st.rerun()

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🧹 Cache", use_container_width=True):
                st.cache_data.clear(); st.rerun()
        with col2:
            if st.button("🗑️ Purge", use_container_width=True):
                nde_options_logic.cleanup_expired_chains(); st.rerun()

        st.divider()
        available_chains = nde_options_logic.list_available_option_chains()
        if available_chains:
            nearest = next((c for c in available_chains if c.get("is_near_active")), available_chains[0])
            selected_filename = nearest["filename"]
            st.info(f"📅 **{nearest['expiry']}**")
        else:
            st.error("No Data")
            selected_filename = None
    st.write("---")




def render_institutional_option_chain(df_exp: pd.DataFrame, spot: float, intel: dict, walls: tuple):
    """
    NSE-Style Institutional Option Chain with side-by-side Calls/Puts and Greek heatmaps.
    """
    if df_exp.empty:
        st.warning("No option chain data available for visualization.")
        return

    # 1. Prepare Call/Put subsets
    calls = df_exp[df_exp["type"] == "call"].copy()
    puts = df_exp[df_exp["type"] == "put"].copy()
    
    # 2. Rename columns for side-by-side merge
    c_cols = {
        "oi": "C_OI", "iv": "C_IV", "delta": "C_Delta", 
        "gamma": "C_Gamma", "vega": "C_Vega", "theta": "C_Theta"
    }
    p_cols = {
        "oi": "P_OI", "iv": "P_IV", "delta": "P_Delta", 
        "gamma": "P_Gamma", "vega": "P_Vega", "theta": "P_Theta"
    }
    
    # Safe Selection: Only rename and select if column exists
    calls_renamed = calls.rename(columns=c_cols)
    puts_renamed = puts.rename(columns=p_cols)
    
    available_c = [v for k, v in c_cols.items() if k in calls.columns]
    available_p = [v for k, v in p_cols.items() if k in puts.columns]
    
    calls_final = calls_renamed[["strike"] + available_c]
    puts_final = puts_renamed[["strike"] + available_p]
    
    # 3. Merge on strike
    chain = pd.merge(calls_final, puts_final, on="strike", how="outer").sort_values("strike")
    
    # 4. Filter range (+/- 12 strikes around spot)
    # Find all strikes, handle potential missing side data
    strikes = chain["strike"].values
    closest_strike = strikes[np.abs(strikes - spot).argmin()]
    idx_closest = chain[chain["strike"] == closest_strike].index[0]
    
    center_idx = chain.index.get_loc(idx_closest)
    start_idx = max(0, center_idx - 12)
    end_idx = min(len(chain), center_idx + 13)
    chain_filtered = chain.iloc[start_idx:end_idx].copy()
    
    # 5. Define Highlight Rules
    dns_zones = intel.get("dns_zones", [])
    optimal = intel.get("optimal_strikes", {})
    call_wall, put_wall = walls
    
    def highlight_row(row):
        style = [''] * len(row)
        s = row["strike"]
        
        # DNS Zone (Red)
        for zone in dns_zones:
            if zone[0] <= s <= zone[1]:
                return ['background-color: rgba(255, 0, 0, 0.2); border-left: 2px solid red;'] * len(row)
        
        # Recommended (Green)
        is_rec = False
        if optimal:
            if "put" in optimal and s == optimal["put"]["strike"]: is_rec = True
            if "call" in optimal and s == optimal["call"]["strike"]: is_rec = True
            
        if is_rec:
            return ['background-color: rgba(0, 255, 0, 0.15); border-left: 3px solid #00ff00; font-weight: bold;'] * len(row)
            
        # Walls (Blue Border)
        if s == call_wall:
            style = ['border-top: 2px dashed #00b0ff; color: #00b0ff;'] * len(row)
        elif s == put_wall:
            style = ['border-bottom: 2px dashed #00b0ff; color: #00b0ff;'] * len(row)
            
        # Centered Strike Highlight
        if s == closest_strike:
            # Find index of 'strike' in chain_filtered.columns
            strike_col_idx = list(chain_filtered.columns).index("strike")
            style[strike_col_idx] = 'background-color: #ffd700; color: black; font-weight: bold;'
            
        return style

    # Final Column Order
    final_cols = [
        "C_Theta", "C_Vega", "C_Gamma", "C_Delta", "C_OI",
        "strike",
        "P_OI", "P_Delta", "P_Gamma", "P_Vega", "P_Theta"
    ]
    
    # Filter only if columns exist
    present_cols = [c for c in final_cols if c in chain_filtered.columns]
    
    styled_df = chain_filtered[present_cols].style.apply(highlight_row, axis=1).format({
        "C_Delta": "{:.2f}", "C_Gamma": "{:.4f}", "C_Vega": "{:.2f}", "C_Theta": "{:.2f}",
        "P_Delta": "{:.2f}", "P_Gamma": "{:.4f}", "P_Vega": "{:.2f}", "P_Theta": "{:.2f}",
        "C_OI": "{:,.0f}", "P_OI": "{:,.0f}", "strike": "{:.0f}"
    })
    
    st.dataframe(
        styled_df, 
        use_container_width=True, 
        height=600, 
        hide_index=True,
        column_config={
            "strike": st.column_config.NumberColumn("Strike", format="%.0f", width="medium"),
            "C_Delta": st.column_config.NumberColumn("C-Delta", format="%.2f", width="small"),
            "P_Delta": st.column_config.NumberColumn("P-Delta", format="%.2f", width="small"),
            "C_OI": st.column_config.NumberColumn("C-OI", format="%d", width="small"),
            "P_OI": st.column_config.NumberColumn("P-OI", format="%d", width="small"),
            "C_Vega": st.column_config.NumberColumn("C-Vega", format="%.1f", width="small"),
            "P_Vega": st.column_config.NumberColumn("P-Vega", format="%.1f", width="small"),
            "C_Theta": st.column_config.NumberColumn("C-Theta", format="%.1f", width="small"),
            "P_Theta": st.column_config.NumberColumn("P-Theta", format="%.1f", width="small"),
            "C_Gamma": st.column_config.NumberColumn("C-Gamma", format="%.4f", width="small"),
            "P_Gamma": st.column_config.NumberColumn("P-Gamma", format="%.4f", width="small"),
        }
    )

def render_greek_cluster(clusters, total_val, greek_type, current_spot=None):
    """
    Renders an institutional-grade cluster table with currency formatting and progress bars.
    """
    if not clusters:
        st.caption(f"No significant {greek_type} clusters detected.")
        return
        
    df = pd.DataFrame(clusters)
    # Convert raw INR exposure to Crore (Cr)
    df["Exposure (Cr)"] = df["exposure"] / 10_000_000.0
    
    # Calculate Dist from Spot if available
    if current_spot:
        df["Dist (%)"] = ((df["strike"] / current_spot - 1) * 100).round(2)
    
    # Align units: total_val is in M (Millions), exposure is raw INR. 
    # Use Millions for both to maintain formula sanity and avoid trillion-scale denominators.
    total_in_m = abs(total_val)
    if total_in_m > 0:
        df["exposure_m"] = df["exposure"] / 1_000_000.0
        df["Weight (%)"] = (df["exposure_m"] / total_in_m * 100).clip(0, 100)
    else:
        df["Weight (%)"] = 0.0
    
    # Format for display
    df = df.rename(columns={"strike": "Strike Zone"})
    
    cols = ["Strike Zone", "Exposure (Cr)", "Weight (%)"]
    if current_spot:
        cols.insert(1, "Dist (%)")
        
    st.dataframe(
        df[cols],
        column_config={
            "Strike Zone": st.column_config.NumberColumn(format="%.0f"),
            "Exposure (Cr)": st.column_config.NumberColumn(format="₹%.2f Cr"),
            "Weight (%)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
            "Dist (%)": st.column_config.NumberColumn(format="%.2f%%")
        },
        use_container_width=True,
        hide_index=True
    )
    
    if greek_type == "Vega":
        st.caption("⚠️ **Vol Risk**: IV spikes will impact these strikes most aggressively.")
    else:
        st.caption("⏳ **Decay Harvest**: These strikes represent the primary 'Income Zones' for the expiry.")

# ==================== UI SETUP ====================
setup_page("Nifty Strategy Engine")


st.title("🎯 NIFTY Strategy Engine (NDE)")
st.caption("Derived from NDE v12 Intelligence Layer")

@st.cache_data(ttl=300, show_spinner=False)
def load_cached_term_structure():
    """Performance Shield: Vectorizes all expiries once and reuses the result."""
    return nde_options_logic.compute_term_structure("NIFTY")

from nde_automation_logic import get_historical_snapshot_df

term_data = load_cached_term_structure()

try:
    # 1. LOAD DATA
    regime_history = load_regime_history()
    market_data = batch_download(["^NSEI", "^INDIAVIX"], period="3mo")
    nifty_df = market_data.get("^NSEI")
    vix_df = market_data.get("^INDIAVIX")
    
    # Updated: v3 Multi-source data loader (Live/Cached)
    raw_chain, used_expiry, source, meta, fname = nde_options_logic.load_nifty_v3_data(selected_filename)
    
    spot = nifty_df["Close"].iloc[-1]
    
    # 2. UNIFIED ENGINE CONTEXT (Phase 41 Hardening)
    from nde_strategy_logic import generate_engine_context
    ctx = generate_engine_context(
        raw_chain=raw_chain,
        spot=spot,
        nifty_df=nifty_df,
        used_expiry=used_expiry,
        regime_history=regime_history,
        regime_snap=load_regime_snapshot(),
        vix_df=vix_df,
        meta=meta,
        mode=mode,
        source=source,
        term_data=term_data
    )

    flow_metrics = ctx["flow_metrics"]
    auto_metrics = ctx["auto_metrics"]
    stability_20d = auto_metrics.get("stability", 50.0)
    stability_5d = auto_metrics.get("stability_5d", 50.0)
    drift = auto_metrics.get("drift", 0.0)
    drift_accel = auto_metrics.get("drift_acceleration", 0.0)
    intel = flow_metrics.get("intelligence", {})
    call_wall, put_wall = ctx["walls"]
    iv_data = ctx["iv_data"]
    strategy_code = ctx["strategy_code"]
    master_setup = ctx["master_setup"]
    regime_snap = ctx["regime_snap"]
    current_atm_iv = ctx["current_atm_iv"]
    atr = ctx["atr"]
    t_days = ctx["t_days"]
    quality_score = ctx["quality_score"]
    state = ctx["state"]
    
    bias_conv = master_setup.get("bias_conviction", {})
    vol_trend = master_setup.get("vol_trend", {})
    exec_summary = master_setup.get("executive_summary", {})

    # 3. Status Telemetry & Health Check
    ts = meta.get("timestamp", "N/A")
    ui = ctx["ui_display"]

    # ⚠️ SYSTEM WARNING BANNER (Phase 1 Hardening)
    if meta.get("data_quality") == "LOW":
        st.error(f"""
            ### 🚨 CRITICAL: STALE DATA (>5 MINS)
            Data feed is lagging by **{meta.get('staleness_seconds', 0)} seconds** during market hours.
            The Strategy Engine has forced a **WAIT** state and downgraded signal trust.
            **DO NOT EXECUTE** live trades until feed syncs.
        """)
    elif ctx.get("requires_warning"):
        st.error("""
            ### ⚠️ CRITICAL DATA INTEGRITY WARNING
            This setup is running on **DEGRADED DATA** (Strike Mean Fallback) or triggered a Risk Pre-Filter. 
            Institutional signals (GEX/Vanna/TV) are analytically unstable. 
            **DO NOT EXECUTE** without manual chain verification.
        """)

    # 🏆 HERO ACTION COCKPIT (V5 - TEST)
    playbook = master_setup.get("playbook", {})
    risk_data = playbook.get('risk', 'N/A')
    risk_name = risk_data.get('risk_type', 'N/A') if isinstance(risk_data, dict) else risk_data
    strategy_name = playbook.get("strategy", master_setup.get("name", "NO TRADE"))
    market_state = playbook.get("market_state", "NEUTRAL DRIFT")
    
    trans_score = playbook.get("transition_score", 0.0)
    trans_label = "IMMINENT" if trans_score >= 0.8 else "PRE-TRANSITION" if trans_score >= 0.6 else "WATCH" if trans_score >= 0.3 else "IGNORE"
    trans_color = "#FF3B30" if trans_score >= 0.6 else "#FF9500" if trans_score >= 0.3 else "#8E8E93"
    
    vol_regime = playbook.get("vol_regime", "NORMAL")
    vol_color = "#FF3B30" if vol_regime == "EXPLOSIVE" else "#00C805" if vol_regime == "QUIET" else "#FF9500"
    
    final_size = playbook.get("position_size", master_setup.get("size", 0.0))
    bias_label = playbook.get("bias", bias_conv.get("bias", "Neutral")).upper()
    conflict = bias_conv.get("conflict_reason", "")
    bias_colors = {"BULLISH": "#00C805", "BEARISH": "#FF3B30", "NEUTRAL": "#8E8E93"}
    bias_color = bias_colors.get(bias_label, "#8E8E93")
    
    # Action Signal (ENTER/WAIT/EXIT)
    action_signal = playbook.get("action", "WAIT").upper()
    action_color = "#00C805" if action_signal == "ENTER" else "#FF3B30" if action_signal == "EXIT" else "#FF9500"
    
    # Enforce WAIT state in top UI
    is_waiting = (playbook.get("action") == "WAIT")
    ui_action_label = "WAIT (No Active Trade)" if is_waiting else f"{bias_label} / {strategy_name}"
    ui_action_color = "#8E8E93" if is_waiting else "#FFFFFF"
    display_size = 0.0 if is_waiting else final_size

    st.markdown(f"""
        <div style="background: linear-gradient(180deg, rgba(30,30,30,0.95), rgba(20,20,20,0.98)); padding: 35px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 20px 40px rgba(0,0,0,0.4); -webkit-font-smoothing: antialiased;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <span style="font-size: 0.85em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 2px;">Market State & Tactical Logic</span>
                    <div style="margin-top: 10px; display: flex; align-items: center; gap: 15px;">
                        <span style="font-size: 1.2em; color: {ui_action_color if is_waiting else bias_color}; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;">{safe(ui_action_label)}</span>
                    </div>
                </div>
                <div style="text-align: right; display: flex; gap: 20px;">
                    <div style="background: rgba(255,255,255,0.03); padding: 18px 25px; border-radius: 12px; border-top: 5px solid {vol_color}; box-shadow: inset 0 0 20px rgba(0,0,0,0.2);">
                        <span style="font-size: 0.75em; color: #8E8E93; text-transform: uppercase; font-weight: 700; letter-spacing: 1px;">Volatility</span><br>
                        <span style="font-size: 1.8em; font-weight: 900; color: {vol_color};">{vol_regime}</span>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); padding: 18px 25px; border-radius: 12px; border-top: 5px solid {trans_color}; box-shadow: inset 0 0 20px rgba(0,0,0,0.2);">
                        <span style="font-size: 0.75em; color: #8E8E93; text-transform: uppercase; font-weight: 700; letter-spacing: 1px;">Transition</span><br>
                        <span style="font-size: 1.8em; font-weight: 900; color: {trans_color};">{trans_score:.2f}</span>
                        <span style="font-size: 0.75em; color: {trans_color}; display: block; font-weight: 800;">{trans_label}</span>
                    </div>
                </div>
            </div>
            <div style="margin-top: 30px; display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;">
                <div style="display: flex; gap: 40px;">
                    <div>
                        <span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 600;">Optimal Sizing</span><br>
                        <span style="font-size: 1.6em; font-weight: 800; color: {'#8E8E93' if is_waiting else '#00C805'};">{display_size:.2f}X</span>
                    </div>
                    <div>
                        <span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 600;">Time Decay</span><br>
                        <span style="font-size: 1.4em; font-weight: 800; color: #007AFF;">{playbook.get('time_decay', 'Moderate')}</span>
                    </div>
                    <div>
                        <span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 600;">Confidence</span><br>
                        <span style="font-size: 1.4em; font-weight: 800; color: #FFFFFF;">{playbook.get('confidence', 0):.2f}</span>
                    </div>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 0.75em; color: #8E8E93; text-transform: uppercase; font-weight: 600;">Primary Exposure Risk</span><br>
                    <span style="font-size: 1.15em; font-weight: 700; color: #FF3B30;">{risk_name}</span>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # 🕵️ DATA TRUST & TRUST INDICATORS
    source_label = ctx.get("source_mode", "UNKNOWN")
    trust_color = "#00C805" if "TRUSTED" in source_label or "INSTITUTIONAL" in source_label else "#FF9500"
    if "DEGRADED" in source_label: trust_color = "#FF3B30"
    
    # CSS for Pulse Animation (Phase 5 Polish)
    st.markdown("""
        <style>
        @keyframes pulse-green {
            0% { box-shadow: 0 0 0 0 rgba(0, 200, 5, 0.4); }
            70% { box-shadow: 0 0 0 10px rgba(0, 200, 5, 0); }
            100% { box-shadow: 0 0 0 0 rgba(0, 200, 5, 0); }
        }
        .trust-pulse {
            width: 8px; height: 8px; border-radius: 50%;
            display: inline-block;
            animation: pulse-green 2s infinite;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
        <div style="display: flex; gap: 12px; margin-bottom: 25px; padding: 0 10px; -webkit-font-smoothing: antialiased; flex-wrap: wrap;">
            <div style="background: rgba(255,255,255,0.03); padding: 6px 12px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.05); font-size: 0.85em; color: #8E8E93; display: flex; align-items: center; gap: 8px;">
                <div class="{'trust-pulse' if trust_color == '#00C805' else ''}" style="width: 8px; height: 8px; border-radius: 50%; background: {trust_color};"></div>
                Source: <span style="color: {trust_color}; font-weight: 800; text-shadow: 0 0 10px {trust_color}33;">{source_label}</span>
            </div>
            <div style="background: rgba(0,122,255,0.05); padding: 6px 12px; border-radius: 20px; border: 1px solid rgba(0,122,255,0.1); font-size: 0.85em; color: #8E8E93; display: flex; align-items: center; gap: 8px;">
                <div style="width: 8px; height: 8px; border-radius: 50%; background: #007AFF;"></div>
                Persistence: <span style="color: #007AFF; font-weight: 800; text-shadow: 0 0 10px #007AFF33;">{state.get('persistence_days', 1)}d</span>
            </div>
            <div style="background: rgba(255,149,0,0.05); padding: 6px 12px; border-radius: 20px; border: 1px solid rgba(255,149,0,0.1); font-size: 0.85em; color: #8E8E93; display: flex; align-items: center; gap: 8px;">
                <div style="width: 8px; height: 8px; border-radius: 50%; background: {trans_color};"></div>
                Analytical Drift: <span style="color: {trans_color}; font-weight: 800; text-shadow: 0 0 10px {trans_color}33;">{drift:+.2f} u</span>
            </div>
            <div style="background: rgba(90,200,250,0.05); padding: 6px 12px; border-radius: 20px; border: 1px solid rgba(90,200,250,0.1); font-size: 0.85em; color: #8E8E93; display: flex; align-items: center; gap: 8px;">
                <div style="width: 8px; height: 8px; border-radius: 50%; background: #5AC8FA;"></div>
                Synthetic Forward: <span style="color: #5AC8FA; font-weight: 800;">{intel.get('synthetic_forward', spot):,.1f}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if conflict:
        st.error(f"⚠️ **FLOW CONFLICT DETECTED**: {bias_conv.get('conflict_reason', 'Macro and GEX signals are diverging.')}")
        
    # --- SECTION: STRATEGY PLAYBOOK (V5) ---
    st.write("### 📖 STRATEGY PLAYBOOK")
    
    # Calculate Alpha Metrics Highlights (Heat-mapped Phase 5)
    conf = playbook.get('confidence', 0.0)
    rev = playbook.get('reversion_strength', 0.0)
    conf_color = "#FF3B30" if conf < 0.4 else "#007AFF" if conf < 0.7 else "#00C805"
    rev_color = "#8E8E93" if rev < 0.4 else "#007AFF" if rev < 0.7 else "#5AC8FA"
    
    p1, p2 = st.columns([1, 1.2])
    with p1:
        st.markdown(f"""<div style="background: linear-gradient(145deg, rgba(20, 20, 25, 0.98), rgba(30, 30, 35, 0.95)); padding: 25px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.08); border-left: 5px solid #007AFF; -webkit-font-smoothing: antialiased; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
<span style="font-size: 0.85em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Structural Setup</span><br>
<span style="font-size: 2.2em; font-weight: 900; color: #FFFFFF; line-height: 1.1; letter-spacing: -1px; text-shadow: 0 2px 10px rgba(0,0,0,0.3);">{playbook.get('setup', strategy_name)}</span><br>
<div style="margin-top: 15px;">
    <span style="font-size: 0.85em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Tactical Action</span><br>
    <div style="display: inline-block; margin-top: 5px; background: {action_color}; color: black; padding: 5px 15px; border-radius: 8px; font-weight: 900; font-size: 1.1em; letter-spacing: 1.5px; box-shadow: 0 4px 15px {action_color}44;">{action_signal}</div>
</div>
<div style="display: flex; gap: 15px; margin-top: 30px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;">
<div style="flex: 1; background: rgba(255,255,255,0.03); padding: 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); box-shadow: inset 0 0 15px rgba(0,0,0,0.2); position: relative; overflow: hidden;">
<span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Confidence</span><br>
<span style="font-size: 1.5em; font-weight: 900; color: {conf_color}; text-shadow: 0 0 20px {conf_color}66;">{conf:.2f}</span>
<div style="position: absolute; bottom: 0; left: 0; height: 3px; width: {conf*100}%; background: {conf_color}; box-shadow: 0 0 10px {conf_color}AA;"></div>
</div>
<div style="flex: 1; background: rgba(255,255,255,0.03); padding: 12px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); box-shadow: inset 0 0 15px rgba(0,0,0,0.2); position: relative; overflow: hidden;">
<span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Reversion Str</span><br>
<span style="font-size: 1.5em; font-weight: 900; color: {rev_color}; text-shadow: 0 0 20px {rev_color}66;">{rev:.2f}</span>
<div style="position: absolute; bottom: 0; left: 0; height: 3px; width: {rev*100}%; background: {rev_color}; box-shadow: 0 0 10px {rev_color}AA;"></div>
</div>
</div>
</div>""", unsafe_allow_html=True)
        
        # 3. Decision Trails (Heat-mapped)
        trail = playbook.get('decision_trail', [])
        
        # [P2 Fix] Suppression Logic for Legs
        is_actionable = playbook.get("action") not in ("WAIT", "STAND ASIDE", "DECISION_ONLY")
        is_suppressed = master_setup.get("strike_plan", {}).get("suppressed", False)
        
        if is_suppressed or not is_actionable:
            st.warning(f"🛡️ **PLAN SUPPRESSED**: {master_setup.get('strike_plan', {}).get('reason', 'Conditions not met for active execution.')}")
            st.info("The legs below are for **Reference Only** and should not be traded in current conditions.")

        st.markdown("**Decision Trail**")
        for step in trail:
            st.caption(f"🔍 {step}")
            
        st.markdown("**Why This Trade**")
        for w in playbook.get("why", []):
            st.markdown(f"✅ {w}")
            
        st.markdown("**Primary Risk**")
        risk_obj = playbook.get("risk", "Theta Decay / Whipsaw")
        if isinstance(risk_obj, dict):
            st.markdown(f"⚠️ **{risk_obj.get('risk_type', 'Market Noise')}**")
            st.caption(f"**Invalidation**: {risk_obj.get('invalidation', 'Thesis holds.')}")
        else:
            st.markdown(f"⚠️ {risk_obj}")

    with p2:
        # Dynamic Styling for Legibility
        is_waiting = (playbook.get("action") == "WAIT")
        action_state = "PLAN (Not Active)" if is_waiting else "ACTIVE EXECUTION"
        
        # Force a Dark Slate background for the box to ensure visibility on light themes
        plan_bg = "rgba(20, 20, 25, 0.95)" if is_waiting else "rgba(0, 40, 5, 0.95)"
        plan_border = "rgba(255, 255, 255, 0.1)" if is_waiting else "rgba(0, 200, 5, 0.3)"
        accent_color = "#8E8E93" if is_waiting else "#00C805"
        text_color = "#E0E0E0" # High contrast silver/white

        strike_plan = playbook.get("strike_plan", {})
        is_waiting = (playbook.get("action") in ("WAIT", "DECISION_ONLY", "STAND ASIDE"))
        is_suppressed = strike_plan.get("suppressed", False)
        
        rows = ""
        for key, label in [("sell_ce", "SELL"), ("sell_pe", "SELL"), ("buy_leg", "BUY"), 
                            ("sell_leg", "SELL"), ("buy_ce", "BUY"), ("buy_pe", "BUY")]:
            val = strike_plan.get(key)
            if val:
                suffix = "CE" if "ce" in key else "PE" if "pe" in key else "LEG"
                # [P2 Fix] Explicit State Visualization
                status_text = "EXECUTE"
                status_color = text_color
                if is_suppressed:
                    status_text = "N/A (BLOCKED)"
                    status_color = "#FF3B30"
                elif is_waiting:
                    status_text = "WATCHING"
                    status_color = "#FF9500"
                
                rows += f'<tr><td style="color: #AAAAAA; padding: 5px 0;">{label} {val} {suffix}</td><td style="text-align: right; color: {status_color}; font-weight: 900; letter-spacing: 1px;">{ status_text }</td></tr>'

        st.markdown(f"""<div style="background: {plan_bg}; padding: 25px; border-radius: 15px; border: 1px solid {plan_border}; -webkit-font-smoothing: antialiased; box-shadow: 0 8px 30px rgba(0,0,0,0.5);">
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
<span style="font-size: 0.9em; color: {accent_color}; font-weight: 900; letter-spacing: 2px;">{action_state}</span>
<span style="font-size: 0.75em; color: #FFFFFF; background: rgba(255,255,255,0.15); padding: 4px 10px; border-radius: 6px; font-weight: 800; text-transform: uppercase;">{strike_plan.get('template', 'NO TEMPLATE')}</span>
</div>
<table style="width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono', 'Roboto Mono', monospace; font-size: 1.25em;">
{rows if rows else f'<tr><td colspan="2" style="color: #8E8E93; text-align: center; padding: 20px;">No trade structure viable for current state.</td></tr>'}
</table>
<div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
<span style="font-size: 0.85em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Activation Trigger</span><br>
<div style="color: {text_color}; font-weight: 700; margin-top: 5px; font-size: 1.1em;">
{' • ' + '<br> • '.join(playbook.get('triggers', ['Maintain thesis monitoring.'])) if playbook.get('triggers') else 'Manual confirmation required.'}
</div>
</div>
</div>""", unsafe_allow_html=True)
            
        st.markdown("### 🎯 Threat Invalidation")
        st.error(f"**STOP THESIS**: {playbook.get('invalidation', 'Thesis holds in current regime.')}")
        if playbook.get("avoid"):
            for a in playbook.get("avoid", []):
                st.markdown(f"⚠️ **GUARDRAIL**: {a}")
        else:
            st.write("No active guardrail violations.")
    # --- SECTION: 5 LEVELS THAT MATTER (Phase 5.2) ---
    st.write("---")
    st.write("### 🧭 KEY TRADING LEVELS")
    
    mp = intel.get("max_pain", 0)
    
    # Define Levels with Institutional Colors
    levels = [
        {"val": spot, "label": "SPOT", "color": "#2979ff"}, # Blue
        {"val": flow_metrics.get("gamma_flip_level"), "label": "FLIP", "color": "#ffd600"}, # Yellow
        {"val": mp, "label": "PAIN", "color": "#00c853"}, # Green
        {"val": call_wall, "label": "CALL WALL", "color": "#ff1744"}, # Red
        {"val": put_wall, "label": "PUT WALL", "color": "#ff1744"}, # Red
    ]
    
    # Sort by value (Left to Right = Lower to Higher price)
    sorted_levels = sorted([l for l in levels if l["val"]], key=lambda x: x["val"])
    
    # Create the Level Ribbon
    strip_html = '<div style="display: flex; width: 100%; gap: 6px; margin: 30px 0; align-items: stretch;">'
    for l in sorted_levels:
        is_spot = (l["label"] == "SPOT")
        # Contrast handling for text
        text_color = "#FFFFFF" if l['label'] in ("CALL WALL", "PUT WALL", "SPOT") else "#121212"
        
        strip_html += f"""
        <div style="flex: 1; background: {l['color']}; padding: 15px 5px; border-radius: 6px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); position: relative; min-width: 80px;">
            <div style="font-size: 0.65em; font-weight: 900; color: {text_color}; opacity: 0.9; text-transform: uppercase; letter-spacing: 1px;">{l['label']}</div>
            <div style="font-size: 1.15em; font-weight: 900; color: {text_color}; font-family: 'JetBrains Mono', monospace; margin-top: 4px;">{l['val']:,.0f}</div>
            {"<div style='position: absolute; top: -10px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 8px solid transparent; border-right: 8px solid transparent; border-bottom: 10px solid " + l['color'] + ";'></div>" if is_spot else ""}
        </div>
        """
    strip_html += '</div>'
    
    # Clean and render
    strip_html = strip_html.replace("\n", "").replace("    ", " ")
    st.markdown(strip_html, unsafe_allow_html=True)
    
    # Reversion Signal Details
    rev_label = playbook.get('reversion_label', 'WAIT')
    rev_color = "#00C805" if rev_label == "HIGH_REVERSION" else "#FF9500" if rev_label == "MODERATE_REVERSION" else "gray"
    
    c_rev1, c_rev2 = st.columns([1, 1])
    with c_rev1:
        st.markdown(f"**Reversion Signal**: <span style='color:{rev_color}; font-weight:700;'>{rev_label}</span>", unsafe_allow_html=True)
        st.caption(f"Score: `{playbook.get('reversion_score', 0.0)}/10` | Proxy: `{playbook.get('vwap_proxy', 'N/A')}`")
    with c_rev2:
        if playbook.get('reversion_reasons'):
            st.markdown("**Drivers**")
            st.caption(", ".join(playbook.get('reversion_reasons')))

    # Spot Drift Warning
    if source == "CACHED" and meta.get("spot_at_fetch"):
        cached_spot = meta["spot_at_fetch"]
        drift_pct = abs(spot - cached_spot) / spot * 100
        if drift_pct > 0.5:
            st.warning(f"⚠️ **SPOT DRIFT**: Market is {drift_pct:.2f}% away from cached snapshot (Spot: {spot:.0f}, Cache: {cached_spot:.0f}). Option Walls might be stale.")


    # --- SECTION: WHAT CHANGED (Trend Strip - Phase 4.1) ---
    st.write("---")
    st.subheader("⏱️ WHAT CHANGED (Last vs Current)")
    # Requesting 5 days but only using the topmost (dated) row for direct Comparison
    hist_df = get_historical_snapshot_df(limit=5, daily_only=True)
    
    # Logic: If today's dated snapshot already exists, iloc[0] is Today. iloc[1] is Yesterday.
    # We want to compare current UI state vs Yesterday (iloc[1] if iloc[0] is today, else iloc[0])
    target_bench = None
    if not hist_df.empty:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if str(hist_df.iloc[-1]["date"])[:10] == today_str:
            target_bench = hist_df.iloc[-2] if len(hist_df) >= 2 else None
        else:
            target_bench = hist_df.iloc[-1]
    if target_bench is not None:
        prev = target_bench
        # Current data from ctx
        curr_flip = flow_metrics.get("gamma_flip_level", 0)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Flip Shift", f"{curr_flip:.0f}", delta=f"{curr_flip - prev.get('gamma_flip', curr_flip):.0f}", delta_color="inverse")
        with c2: st.metric("Pain Shift", f"{int(mp):,}", delta=f"{int(mp - prev.get('max_pain', mp)):,}")
        with c3: st.metric("PCR Delta", f"{intel.get('pcr_oi', 0.0):.2f}", delta=f"{(intel.get('pcr_oi', 0.0) - prev.get('pcr_oi', 0.0)):.2f}")
        with c4:
            prev_iv = prev.get('atm_iv')
            if prev_iv is not None and prev_iv > 0:
                iv_delta = current_atm_iv - prev_iv
                st.metric("IV Accel", f"{current_atm_iv:.1f}%", delta=f"{iv_delta:+.1f}%", delta_color="inverse")
            else:
                st.metric("IV Accel", f"{current_atm_iv:.1f}%", delta="N/A (no baseline)", delta_color="off")
    else:
        st.info("No historical baseline (Yesterday's Close) found for drift comparison.")

    # --- UI TABBED LAYOUT (Phase 4.1) ---
    tab_dashboard, tab_intel, tab_risk, tab_audit = st.tabs([
        "🏆 Strategy Dashboard", "🧠 Market Intelligence", "🗺️ Risk Surface", "📋 System Audit"
    ])

    with tab_dashboard:
        # 🏆 SECTION 1: PRIMARY TRADE SETUP
        st.header("🏆 PRIMARY TRADE SETUP (Deterministic)")
        
        # 30-Second Headline Banner
        if master_setup.get("code") != "NO_TRADE":
            cv = "High" if master_setup.get("quality_score", 0) > 7.5 else "Medium" if master_setup.get("quality_score", 0) > 5.0 else "Low"
            st.info(f"**⚡ ACTION**: **{master_setup.get('name')}** | **Conviction**: {cv} | **Edge**: {exec_summary.get('primary_edge', 'Volatility/Premium')}")

        # --- Phase 4 Enhancement: Institutional Term Structure Context ---
        with st.container():
            t_cols = st.columns([2, 1])
            with t_cols[0]:
                st.markdown("#### 🏛️ Institutional Term Structure Context")
                if term_data:
                    exp_list = list(term_data.keys())
                    w1 = exp_list[0]
                    mn = exp_list[-1]
                    w1_state = term_data[w1]["state"]
                    mn_state = term_data[mn]["state"]
                    
                    st.markdown(f"""
                        <div style="display: flex; gap: 10px;">
                            <div style="background: rgba(255,255,255,0.05); padding: 8px 15px; border-radius: 6px; border-left: 3px solid #2979ff;">
                                <span style="font-size: 0.7em; color: gray;">WEEKLY (NEAR)</span><br>
                                <span style="font-weight: 700;">{w1_state}</span>
                            </div>
                            <div style="background: rgba(255,255,255,0.05); padding: 8px 15px; border-radius: 6px; border-left: 3px solid #00c853;">
                                <span style="font-size: 0.7em; color: gray;">MONTHLY (ANCHOR)</span><br>
                                <span style="font-weight: 700;">{mn_state}</span>
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
                else:
                    st.caption("Term structure analysis unavailable.")
            with t_cols[1]:
                st.write("")
                st.write("")
                if st.button("🔍 Analyze Monthly Surface", use_container_width=True):
                    st.switch_page("pages/18_NSE_Monthly_Engine.py")
        
        # 🧠 SECTION 2: THE DECISION & EXECUTION plan
        st.write("---")
        device = get_ui_device_mode()
        
        # Use responsive cols for the triple-card section
        from utils import responsive_cols
        d_cols = responsive_cols(3)
        
        # --- ROADMAP UPDATE 3: LIVE P&L DRIFT WATCHER ---
        if source == "CACHED" and meta.get("spot_at_fetch"):
            cached_spot = meta["spot_at_fetch"]
            drift_pts = spot - cached_spot
            drift_pct = (drift_pts / cached_spot) * 100
            
            # Contextual Color: Is drift favorable for the strategy?
            # For Mean Reversion (Short Vol), drift away from entry is usually unfavorable.
            # For Straddles (Long Vol), drift is favorable.
            is_long_vol = strategy_code in ("TREND_ACCELERATION", "GAMMA_FLIP")
            drift_favorable = (abs(drift_pts) > 50) if is_long_vol else (abs(drift_pts) < 30)
            drift_color = "#00C805" if drift_favorable else "#FF3B30"
            
            with st.container():
                st.markdown(f"""
                    <div style="background: rgba(255,255,255,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); margin-bottom: 20px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <span style="font-size: 0.75em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Execution P&L Watcher</span><br>
                                <span style="font-size: 1.1em; font-weight: 700;">Spot Drift: <span style="color: {drift_color};">{drift_pts:+.2f} pts</span> ({drift_pct:+.2f}%)</span>
                            </div>
                            <div style="text-align: right;">
                                <span style="font-size: 0.7em; color: #8E8E93;">SNAPSHOT BASE</span><br>
                                <span style="font-family: monospace; font-weight: 700;">{cached_spot:,.0f}</span>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        
        with d_cols[0]:
            st.markdown("### 1️⃣ DECISION CARD")
            # --- PHASE 4: EXPLICIT ACTION LABEL SURFACING ---
            st.markdown(f"""
                <div style="background: rgba(255,255,255,0.05); padding: 10px; border-radius: 8px; border-left: 5px solid {ui['trade_action'].get('color', '#2979ff')}; margin-bottom: 12px;">
                    <span style="font-size: 0.8em; color: gray; text-transform: uppercase;">Operator Action</span><br>
                    <span style="font-size: 1.3em; font-weight: 800; color: white;">{safe(ui['trade_action']['label'].upper())}</span>
                </div>
            """, unsafe_allow_html=True)
            
            flip_lvl = flow_metrics.get("gamma_flip_level", None)
            flip_dist_pct = abs(spot - flip_lvl)/spot*100 if flip_lvl is not None and spot > 0 else 0
            flip_badge = f"<span style='font-size: 0.85em; color: gray;'> (Flip: {flip_dist_pct:.1f}%)</span>" if flip_lvl is not None and flip_lvl > 0 else ""
            st.markdown(f"**Strategy**: `{safe(master_setup.get('name', ''))}`{flip_badge}", unsafe_allow_html=True)
            
            score = master_setup.get("quality_score", 0)
            rec_size = master_setup.get("size", 1.0)
            st.progress(min(1.0, score / 10.0), text=f"Quality: {score}/10 (Size: {rec_size:.1f}x)")
            
            pnl = master_setup.get("estimated_pnl", {})
            if pnl:
                st.markdown(f"**Est. Yield**: ₹{int(pnl.get('net',0)):,} <span style='color:gray; font-size:0.8em'>(Gross: ₹{int(pnl.get('gross',0)):,})</span>", unsafe_allow_html=True)

            st.markdown(f"**Alignment**: <span style='color:{ui['alignment_color']}; font-weight:bold'>{safe(master_setup.get('alignment', 'ALIGNED'))}</span>", unsafe_allow_html=True)
            gamma_regime = str(flow_metrics.get("gamma_regime", "UNKNOWN")).split("(")[0].strip()
            st.caption(f"State: {gamma_regime} | {ui['tv_ratio']['label']}")

        with d_cols[1]:
            st.markdown("### 2️⃣ ENVIRONMENT PANEL")
            rb = ui["regime_badge"]
            vix_val = vix_df["Close"].iloc[-1] if vix_df is not None else 0
            vix_badge = f"<span style='background-color:#444; color:white; padding:2px 6px; border-radius:4px; font-size:0.7em; margin-left:10px'>VIX: {vix_val:.1f}</span>"
            st.markdown(f"**Regime**: <span style='color:{rb['color']}; font-weight:bold; font-size:1.1em'>{rb['label']}</span>{vix_badge}", unsafe_allow_html=True)
            
            vt_label = vol_trend.get("vol_trend", "Stable")
            vt_color = "#FF3B30" if "Rising" in vt_label else "#00C805" if "Falling" in vt_label else "gray"
            st.markdown(f"**Vol Trend**: <span style='color:{vt_color};'>{vt_label}</span>", unsafe_allow_html=True)
            st.markdown(f"**ATM IV**: `{current_atm_iv:.1f}%` (Rank: `{iv_data.get('iv_rank', 50.0)}%`)")
            st.markdown(f"**Flow Label**: `{flow_metrics.get('flow_regime_label', 'Passive')}`")
            st.markdown(f"**TV Ratio**: `{ui['tv_ratio']['val']}` <span style='color:{ui['tv_ratio']['color']}; font-weight:bold'>({ui['tv_ratio']['label']})</span>", unsafe_allow_html=True)
            
            iq = flow_metrics.get("institutional_iq", {})
            if iq:
                st.markdown(f"**Max Pain**: `{int(iq.get('max_pain', 0)):,}` | **PCR (OI)**: `{iq.get('pcr_oi', 'N/A')}`")
                exp_r = iq.get("expected_move", {})
                st.markdown(f"**Expected Move**: `{int(exp_r.get('low', 0))} - {int(exp_r.get('high', 0))}`")

        with d_cols[2]:
            if view_mode == "Full (Institutional)":
                st.markdown("### 3️⃣ SIGNAL SIGNAL")
                buckets = master_setup.get("quality_breakdown", {}).get("convergence_buckets", {})
                weights = {"macro": "30%", "flow": "25%", "structure": "20%", "momentum": "15%", "vol": "10%"}
                st.markdown(f"{'✅' if buckets.get('macro') else '❌'} Regime `({weights['macro']})`")
                st.markdown(f"{'✅' if buckets.get('flow') else '❌'} GEX `({weights['flow']})`")
                st.markdown(f"{'✅' if buckets.get('momentum') else '❌'} Drift `({weights['momentum']})`")
                st.markdown(f"{'✅' if buckets.get('vol') else '❌'} IV `({weights['vol']})`")
                st.markdown(f"{'✅' if buckets.get('structure') else '❌'} Stability `({weights['structure']})`")
            else:
                st.markdown("### 📋 SUMMARY")
                st.write(master_setup.get("reason", "Follow bias rules."))

        st.divider()

        c1, c2 = st.columns([1.5, 1])
        with c1:
            st.markdown("#### ⚡ EXECUTION INSTRUCTIONS")
            st.markdown(f"**Mode**: **{mode}**")
            
            # FIX 10 (Phase 5.8 Review): Unified execution display using playbook strike_plan
            # This is the single source of truth for trade legs, with suppression logic applied
            template = master_setup.get("template")
            pb_plan = playbook.get("strike_plan", {})
            pb_suppressed = pb_plan.get("suppressed", False)
            
            if pb_plan.get("template"):
                st.info(f"**Structure**: {pb_plan.get('template', 'N/A')} | Schema: `{pb_plan.get('schema', 'NONE')}`")
            
            st.markdown("**EXECUTION LEGS:**")
            _leg_shown = False
            for key, label in [("sell_ce", "Sell Call"), ("sell_pe", "Sell Put"), 
                               ("buy_ce", "Buy Call"), ("buy_pe", "Buy Put"),
                               ("sell_leg", "Sell Leg"), ("buy_leg", "Buy Leg")]:
                val = pb_plan.get(key)
                if val and isinstance(val, (int, float)) and val > 0:
                    if pb_suppressed:
                        st.markdown(f"- **{label}** → `—` *(blocked)*")
                    else:
                        st.markdown(f"- **{label}** → `{int(val)}`")
                    _leg_shown = True
            
            if not _leg_shown:
                st.markdown("- No trade structure viable for current state.")
            
            if pb_suppressed:
                st.warning(f"🛡️ **BLOCKED**: {pb_plan.get('reason', 'Conditions not met.')}")


            st.divider()
            st.markdown("#### 💡 STRATEGIC RATIONALE")
            rat = master_setup.get("rationale", [])
            
            # Mobile UX Clarification: Rationale in expander for mobile
            if device == "Mobile":
                with st.expander("Show Strategic Drivers", expanded=False):
                    if rat:
                        for r in rat:
                            st.write(f"- {r}")
                    else:
                        st.write("- No specific tactical drivers identified.")
            else:
                if rat:
                    for r in rat:
                        st.write(f"- {r}")
                else:
                    st.write("- No specific tactical drivers identified.")
            
            st.write("---")
            st.markdown("**Executive Summary**")
            st.info(master_setup.get("executive_summary", {}).get("rationale", "Follow primary bias rules for the current regime."))
                    
            payoff = template.get("payoff_summary", {})
            if payoff:
                st.divider()
                st.markdown("**PAYOFF MATRIX**")
                p1, p2 = st.columns(2)
                
                # Compute R:R
                max_p_str = str(payoff.get('max_profit', 'N/A'))
                rp = payoff.get('risk_proxy_inr', 1.0)
                rr_str = ""
                try:
                    cleaned = re.sub(r"[^\d.]", "", max_p_str)
                    p_val = float(cleaned) if cleaned else 0.0
                    if p_val == 0.0:
                        rr_str = " <span style='color:gray'>(R:R unavailable)</span>"
                    elif isinstance(rp, (int, float)) and rp > 0:
                        rr = p_val / rp
                        rr_str = f" <span style='color:gray; font-size: 0.8em;'>(1:{1/rr:.1f} R:R)</span>"
                except Exception:
                    rr_str = " <span style='color:gray'>(R:R parse error)</span>"
                    
                with p1:
                    st.markdown(f"**Max Profit**: {payoff.get('max_profit', 'N/A')}{rr_str}", unsafe_allow_html=True)
                    st.write(f"**Max Loss**: {payoff.get('max_loss', 'N/A')}")
                with p2:
                    st.write(f"**Risk Proxy**: ₹{int(rp):,}" if isinstance(rp, (int, float)) else "N/A")
                    be_u, be_l = payoff.get('breakeven_upper'), payoff.get('breakeven_lower')
                    if be_u and be_l:
                        st.write(f"**Breakevens**: {be_l:.0f} - {be_u:.0f}")
                    else:
                        st.write("**Breakevens**: N/A")

                st.divider()
                if payoff and payoff.get('invalidation'):
                    st.warning(f"**THESIS INVALIDATION**: {safe(payoff.get('invalidation'))}")
                else:
                    st.warning(f"**THESIS INVALIDATION**: {safe(exec_summary.get('invalidation', 'N/A'))}")

        with c2:
            st.subheader("⚠ MARKET WARNING")
            risk_flags = 0
            if flow_metrics.get('total_vega', 0) > 300:
                st.error("Spot inside massive Vega cluster. Vol expansion risk elevated.")
                risk_flags += 1
            if flow_metrics.get('total_gex', 0) < 0:
                st.warning("Negative Gamma regime. Market volatility elevated.")
                risk_flags += 1
            for w in master_setup.get("warnings", []):
                st.warning(w)
                risk_flags += 1
            if risk_flags == 0:
                st.success("No critical market hazard flags active.")

    with tab_intel:
        st.header("📉 GREEK INTERPRETATION LAYER")
        gr1, gr2, gr3 = st.columns(3)
        gr4, gr5, gr6 = st.columns(3)
        with gr1: st.metric("Net Delta", ui["greeks"]["delta"])
        with gr2: st.metric("Absolute GEX", ui["greeks"]["gex_abs"])
        with gr3: st.metric("Net GEX", ui["greeks"]["gex_net"])
        with gr4: st.metric("Total Vega", ui["greeks"]["vega"])
        with gr5: st.metric("Total Theta", ui["greeks"]["theta"])
        with gr6: st.metric("T/V Carry", ui["tv_ratio"]["val"], delta=ui["tv_ratio"]["label"])
            
        from nde_options_logic import classify_greek_market_state
        greek_state = classify_greek_market_state(flow_metrics)
        vanna_label = flow_metrics.get("vanna_bias", "Passive")
        charm_label = flow_metrics.get("charm_flow", "Neutral")
        st.info(f"**Market State**: `{greek_state['state']}` | **Vol Bias**: `{vanna_label}` | **Decay Regime**: `{charm_label}`")
        
        st.divider()
        st.subheader("🏛️ Institutional IQ Panel")
        iq = flow_metrics.get("institutional_iq", {})
        # Phase 46: Movements (Trends)
        tr = master_setup.get("trends", {})
        
        i1, i2, i3, i4 = st.columns(4)
        with i1:
            st.metric("Max Pain", f"{int(iq.get('max_pain', 0)):,}", delta=tr.get("max_pain_delta"), delta_color="normal")
            st.metric("PCR (OI)", iq.get("pcr_oi", "N/A"), delta=tr.get("pcr_oi_delta"), delta_color="inverse")
        with i2:
            st.metric("POC (Volume)", f"{int(iq['poc']):,}" if iq.get('poc') is not None else "N/A")
            st.metric("PCR (Vol)", iq.get("pcr_vol", "N/A"))
        with i3:
            va_low, va_high = iq.get('va_low'), iq.get('va_high')
            st.metric("Value Area (VA)", f"{int(va_low)} - {int(va_high)}" if va_low and va_high else "N/A")
            st.metric("Near-ATM Share", f"{iq.get('atm_oi_share', 0)}%", delta=f"{tr.get('atm_oi_share_delta', 0)}%" if tr.get("atm_oi_share_delta") else None, delta_color="off")
        with i4:
            e_move = master_setup.get("expected_move", {})
            st.metric("Expected Range (1SD)", f"{int(e_move.get('lower',0))} - {int(e_move.get('upper',0))}", 
                      delta=f"±{int(e_move.get('points',0))}", delta_color="off")
            st.metric("Gamma Flip", f"{flow_metrics.get('gamma_flip_level', 0):,.0f}", delta=tr.get("gamma_flip_delta"), delta_color="normal")

        if view_mode == "Full (Institutional)":
            st.divider()
            col_v, col_t = st.columns(2)
            with col_v:
                st.subheader("🔥 Vega Cluster Map")
                render_greek_cluster(flow_metrics.get("vega_clusters"), flow_metrics.get("total_vega", 0), "Vega", current_spot=spot)
            with col_t:
                st.subheader("⏳ Theta Decay Map")
                render_greek_cluster(flow_metrics.get("theta_clusters"), flow_metrics.get("total_theta", 0), "Theta", current_spot=spot)
        else:
            st.caption("Greek clusters hidden in Compact Mode.")

        # --- ROADMAP UPDATE 2: TERM STRUCTURE VISUALIZER ---
        st.divider()
        st.subheader("🏛️ Volatility Term Structure (IV Term)")
        if term_data:
            try:
                # Prepare term structure data
                exp_dates = list(term_data.keys())
                ivs = [d.get("atm_iv", 0) for d in term_data.values()]
                
                fig_term = go.Figure()
                fig_term.add_trace(go.Scatter(
                    x=exp_dates, y=ivs, mode='lines+markers',
                    line=dict(color='#007AFF', width=3),
                    marker=dict(size=10, color='#007AFF', symbol='diamond'),
                    name="IV Term Structure"
                ))
                
                # Check for Contango/Backwardation
                if len(ivs) >= 2:
                    slope = ivs[1] - ivs[0]
                    regime_label = "Normal (Near > Far)" if slope < 0 else "Inverted (Far > Near — Stress Signal)"
                    regime_color = "#00C805" if slope < 0 else "#FF3B30"
                    st.caption(f"Structure Regime: <span style='color:{regime_color}; font-weight:700;'>{regime_label}</span>", unsafe_allow_html=True)
                
                fig_term.update_layout(
                    height=250, margin=dict(l=20, r=20, t=40, b=20),
                    xaxis_title="Expiry Date", yaxis_title="ATM IV (%)",
                    showlegend=False, template="plotly_dark",
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_term, use_container_width=True, config={'displayModeBar': False})
            except Exception as e:
                st.info(f"Term Structure Visualization unavailable: {e}")
        else:
            st.info("Insufficient multi-expiry data to render term structure.")

    with tab_risk:
        st.header("🗺️ RISK SURFACE MAP")
        
        # Phase 46: Dynamic Window Alignment
        # Expand window to include any suggested trade strikes
        trade_strikes = []
        if master_setup.get("template") and "execution" in master_setup["template"]:
            exec_data = master_setup["template"]["execution"]
            trade_strikes = [v for k, v in exec_data.items() if "strike" in k or k.startswith("sell_") or k.startswith("buy_")]
            trade_strikes = [s for s in trade_strikes if isinstance(s, (int, float)) and s > 0]
            
        # Default window +/- 400 around spot
        min_win = min([spot - 400] + trade_strikes) if trade_strikes else spot - 400
        max_win = max([spot + 400] + trade_strikes) if trade_strikes else spot + 400
        map_strikes = range(int(min_win)//50*50, int(max_win)//50*50 + 50, 50)
        
        raw_exp = flow_metrics.get("raw_exposures", pd.DataFrame())
        dns_z = intel.get("dns_zones", [])
        
        if not raw_exp.empty:
            wd = master_setup.get("wall_drift", {})
            if wd.get("is_squeeze"):
                st.error("🌪️ **VOLATILITY SQUEEZE DETECTED**: Call/Put walls have compressed to within 1.5x ATR. Neutralizing directional bias for breakout monitoring.")
            elif wd.get("call", 0) != 0 or wd.get("put", 0) != 0:
                c_drift, p_drift = wd.get("call", 0), wd.get("put", 0)
                st.info(f"🛰️ **WALL MIGRATION**: Call Wall: {c_drift:+.0f} | Put Wall: {p_drift:+.0f} points since open.")
            
            profile_map = {
                int(row["strike"]): nde_options_logic.get_strike_risk_profile(row["strike"], raw_exp, dns_z)
                for _, row in raw_exp.drop_duplicates("strike").iterrows()
            }
            risk_dict = {s: profile_map.get(int(s), "LOW") for s in map_strikes}
            
            # Phase 45: Tiered Row Grouping
            tiers = {
                "HIGH": {"label": "🔴 HIGH RISK ZONES", "strikes": [], "bg": "rgba(255,0,0,0.05)"},
                "MED":  {"label": "🟡 MODERATE RISK", "strikes": [], "bg": "rgba(255,165,0,0.05)"},
                "LOW":  {"label": "🟢 SAFE ZONES", "strikes": [], "bg": "rgba(0,128,0,0.05)"}
            }
            for s in map_strikes:
                rt = risk_dict[s]
                if rt in tiers: tiers[rt]["strikes"].append(s)
                else: tiers["LOW"]["strikes"].append(s)

            for tid, tdata in tiers.items():
                st.markdown(f"##### {tdata['label']}")
                if not tdata["strikes"]:
                    st.caption("No strikes identified in this tier.")
                    continue
                    
                row_html = '<div style="display: flex; overflow-x: auto; gap: 15px; padding: 10px 5px; scrollbar-width: thin; font-family: sans-serif;">'
                for s in tdata["strikes"]:
                    icon = "🔴" if tid == "HIGH" else "🟡" if tid == "MED" else "🟢"
                    is_spot_nearest = abs(s - spot) <= 25 
                    spot_label = f"<div style='color: #00ff00; font-weight: bold; font-size: 0.7rem; margin-top: 4px;'>📍 SPOT</div>" if is_spot_nearest else ""
                    border_style = "border: 1px solid #00ff00;" if is_spot_nearest else f"border: 1px solid {tdata['bg'].replace('0.05', '0.2')};"
                    
                    # Force single-line string and strip HTML to prevent markdown code-block detection
                    strike_cell = f'<div style="min-width: 85px; text-align: center; padding: 10px; border-radius: 8px; {border_style} flex: 0 0 auto; background: {tdata["bg"]};">'
                    strike_cell += f'<div style="font-size: 1.2rem; margin-bottom: 3px;">{icon}</div>'
                    strike_cell += f'<div style="font-size: 0.95rem; font-weight: 700; color: inherit;">{s}</div>'
                    strike_cell += f'{spot_label}</div>'
                    row_html += strike_cell
                    
                row_html += '</div>'
                st.markdown(row_html, unsafe_allow_html=True)
            
            st.caption("👈 Swipe rows for more strikes | Logic: DNS Zones + High-Vega Cluster detection.")
        
        st.divider()
        st.header("🕵️ Institutional Option Chain")
        with st.expander("🏛️ Full Institutional Option Chain Explorer", expanded=True):
            if not raw_exp.empty:
                render_institutional_option_chain(raw_exp, spot, intel, (call_wall, put_wall))
            else:
                st.info("Chain unavailable.")

    with tab_audit:
        st.header("📋 SYSTEM AUDIT & SIZES")
        g1, g2 = st.columns(2)
        with g1:
            st.progress(max(0.0, min(1.0, stability_20d / 100.0)), text=f"Regime Stability (20D): {stability_20d}%")
            st.caption(f"5D Stability: {stability_5d}%")
        with g2:
            st.progress(min(1.0, abs(drift) / 0.5), text=f"Drift Intensity: {abs(drift):.2f}")
            st.caption(f"Acceleration: {drift_accel:.4f}")
        
        st.divider()
        st.subheader("24h Thesis Validity")
        audit_file = Path("notes/nde_strategy_log.jsonl")
        validity_score = None
        if audit_file.exists():
            try:
                audit_rows = []
                with open(audit_file, "r") as f:
                    for line in f: audit_rows.append(json.loads(line))
                if len(audit_rows) >= 2:
                    correct, total = 0, 0
                    for i in range(len(audit_rows) - 1):
                        row = audit_rows[i]
                        next_row = audit_rows[i+1]
                        
                        # Modern logic (Strategy codes)
                        strat = row.get("strategy", "NO_TRADE")
                        drift_val = next_row.get("drift", 0)
                        
                        # Legacy logic fallback
                        bias = row.get("bias", "Neutral")
                        
                        is_valid = False
                        if strat == "TREND_ACCELERATION" or bias == "Bullish":
                            if drift_val > 0.05: is_valid = True
                        elif strat == "MEAN_REVERSION" or bias == "Neutral":
                            if abs(drift_val) < 0.2: is_valid = True
                        elif strat == "GAMMA_FLIP":
                            if abs(drift_val) > 0.1: is_valid = True
                        else:
                            is_valid = True # NO_TRADE/Wait & Watch is generally defensive
                            
                        if is_valid: correct += 1
                        total += 1
                    validity_score = round((correct / total) * 100, 1) if total > 0 else None
            except json.JSONDecodeError as e:
                st.warning(f"⚠️ Audit log has a corrupt entry and was partially read: {e}")
            except Exception as e:
                st.warning(f"⚠️ Could not read audit log: {e}")
        if validity_score is not None:
            st.metric("Signal Persistence Score", f"{validity_score}%", delta=f"{len(audit_rows)-1} samples", delta_color="off")
        else:
            st.info("Thesis tracking requires more data.")

        st.divider()
        st.subheader("System Sizing Policy")
        st.markdown(f"- **Managed Risk Proxy**: 1.0 ATR\n- **Operational SL**: 0.5 ATR\n- **Policy Mode**: `{mode}`")
        
        with st.expander("📝 Full Audit Trail (Latest 10)"):
            if audit_file.exists():
                raw_df = pd.DataFrame(audit_rows)
                # Filter for modern schema (rows having 'quality' key)
                if "quality" in raw_df.columns:
                    modern_df = raw_df[raw_df["quality"].notna()].tail(10).copy()
                    display_cols = ["date", "strategy", "quality", "size", "spot", "regime"]
                    # Ensure all columns exist before selecting
                    actual_cols = [c for c in display_cols if c in modern_df.columns]
                    st.dataframe(modern_df[actual_cols], use_container_width=True, hide_index=True)
                else:
                    st.info("Legacy audit format detected. History will resume with next trade.")

    # ⚖️ SECTION 5: STRATEGY HIERARCHY
    st.sidebar.header("⚖️ Strategy Confidence Hierarchy")
    
    def highlight_strat(name, *codes):
        return f"**{name}** 👈 *Active*" if strategy_code in codes else name

    st.sidebar.markdown(f"""
    1. {highlight_strat('Gamma Flip', 'GAMMA_FLIP')} (Critical Pivot)
    2. {highlight_strat('Trend/Mean Rev', 'TREND_ACCELERATION', 'MEAN_REVERSION')} (Regime Core)
    3. {highlight_strat('Vanna Flow', 'VANNA')} (Vol Dependency)
    4. {highlight_strat('Charm Decay', 'CHARM')} (Passivity)
    """)

    st.sidebar.divider()
    from nde_automation_logic import write_daily_nde_snapshot, compute_probabilities, compute_transition_risk
    if st.sidebar.button("💾 Finalize Daily Snapshot"):
        try:
            curr_reg = regime_snap.get("current_regime", "Unknown")
            pers = regime_snap.get("persistence", 0)
            c_probs = compute_probabilities(curr_reg, drift, pers)
            c_escalation = compute_transition_risk(drift, stability_20d)
            
            saved_f = write_daily_nde_snapshot(
                curr_regime=curr_reg, 
                persistence=pers,
                stability_20d=stability_20d, 
                stability_5d=stability_5d, 
                drift=drift, 
                drift_accel=drift_accel, 
                fragility=auto_metrics.get("fragility", False),
                probs=c_probs,
                escalation=c_escalation,
                used_expiry=used_expiry, 
                gamma_regime=flow_metrics.get("gamma_regime", "UNKNOWN"), 
                flip=flow_metrics.get("gamma_flip_level", 0), 
                vanna=flow_metrics.get("vanna_bias", "UNKNOWN"), 
                charm=flow_metrics.get("charm_flow", "UNKNOWN"),
                flow_regime=flow_metrics.get("flow_regime_label", "UNKNOWN"), 
                total_gex=flow_metrics.get("total_gex", 0), 
                t_bias=bias_conv.get("bias", "NEUTRAL"),
                s_bias=intel.get("structural_bias", "NEUTRAL"), 
                spot=spot, 
                atr=atr, 
                config_hash=CONFIG_VERSION,
                source_mode=ctx.get("source_mode", "UNKNOWN"),
                data_quality_score=quality_score,
                tv_label=flow_metrics.get("tv_label", "UNKNOWN"),
                convergence_score=master_setup.get("quality_breakdown", {}).get("convergence", 0),
                strategy_code=strategy_code,
                inst_iq=flow_metrics.get("institutional_iq"),
                atm_iv=current_atm_iv
            )
            st.sidebar.success(f"Snapshot saved to {saved_f.name}")
        except Exception as e:
            st.sidebar.error(f"Error saving snapshot: {e}")

    st.sidebar.markdown("---")
    st.sidebar.page_link("pages/18_NSE_Monthly_Engine.py", label="🏛️ NSE Monthly Engine", icon="📈")


except Exception as e:
    st.error(f"Critical Error in Strategy Engine: {e}")
    st.exception(e)
