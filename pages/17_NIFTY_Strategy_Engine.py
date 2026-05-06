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
_VALID_COLORS = {"#00C805","#FF3B30","#FF9500","#8E8E93","#007AFF","#5AC8FA","#ffd600","#2979ff","#00c853","#ff1744","#FFFFFF","#121212","#444","gray","transparent"}
safe_color = lambda c: c if c in _VALID_COLORS else "#8E8E93"

# v3 Calibration Core (Moved to top to prevent circularity)
import importlib
import NSE_Config
importlib.reload(NSE_Config)
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
    
    # P0: Multi-Index Support
    selected_index = st.radio("Active Index", ["NIFTY", "SENSEX", "BANKNIFTY"], horizontal=True)
    index_cfg = NSE_Config.MARKET_CONFIG[selected_index]
    LOT = index_cfg["lot_size"]
    ticker = index_cfg["ticker"]
    STRIKE_STEP = index_cfg.get("strike_interval", 50)
    
    mode = st.radio("Execution Bias", ["Defensive", "Balanced", "Aggressive"], index=1, help="Adjusts strike widening/tightness.")
    st.caption(f"Engine: `{CONFIG_VERSION}` | Index: `{selected_index}`")

    available_chains = nde_options_logic.list_available_option_chains(index_name=selected_index)
    selected_filename = None
    if available_chains:
        nearest = next((c for c in available_chains if c.get("is_near_active")), available_chains[0])
        selected_filename = nearest["filename"]
        st.info(f"📅 **{nearest['expiry']}**")
    else:
        st.error("No Data")

    with st.expander("🛠️ Data Operations Hub", expanded=False):
        st.subheader("🌐 Greeks Ingestion")
        
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
    
    loc = chain.index.get_loc(idx_closest)
    center_idx = loc.start if isinstance(loc, slice) else (loc.argmax() if hasattr(loc, 'argmax') else loc)
    
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


st.title(f"🎯 {selected_index} Strategy Engine")
st.caption(f"Derived from NDE v12 Intelligence Layer ({selected_index} Edition)")

@st.cache_data(ttl=300, show_spinner=False)
def load_cached_term_structure(index_name):
    """Performance Shield: Vectorizes all expiries once and reuses the result."""
    return nde_options_logic.compute_term_structure(index_name)

from nde_automation_logic import get_historical_snapshot_df

term_data = load_cached_term_structure(selected_index)

try:
    # 1. LOAD DATA
    regime_history = load_regime_history(index_name=selected_index)
    # P0: Fetch index-specific spot and VIX
    market_data = batch_download([ticker, "^INDIAVIX"], period="3mo")
    nifty_df = market_data.get(ticker)
    vix_df = market_data.get("^INDIAVIX")
    
    # Updated: v3 Multi-source data loader (Live/Cached)
    raw_chain, used_expiry, source, meta, fname = nde_options_logic.load_index_v3_data(selected_filename, index_name=selected_index)
    
    # 1.1 Secure Spot Extraction (Hardening for NaN/Missing data)
    spot = None
    if nifty_df is not None and not nifty_df.empty:
        spot = nifty_df["Close"].iloc[-1]
        
    # Secondary Fallback: Use metadata from Option Chain (Highest Fidelity for Greeks Sync)
    if spot is None or pd.isna(spot) or spot <= 0:
        spot = meta.get("underlyingValue") or meta.get("spot_at_fetch") or meta.get("spot")
        
    # Final Hard Fallback: Broad Index Averages
    if spot is None or pd.isna(spot) or spot <= 0:
        if selected_index == "NIFTY": spot = 24000.0
        elif selected_index == "BANKNIFTY": spot = 54000.0 # Updated to current regime
        else: spot = 77000.0 # SENSEX
    else:
        spot = float(spot)
    
    # 2. UNIFIED ENGINE CONTEXT (Phase 41 Hardening)
    from nde_strategy_logic import generate_engine_context
    ctx = generate_engine_context(
        raw_chain=raw_chain,
        spot=spot,
        nifty_df=nifty_df,
        used_expiry=used_expiry,
        regime_history=regime_history,
        regime_snap=load_regime_snapshot(index_name=selected_index),
        vix_df=vix_df,
        meta=meta,
        mode=mode,
        source=source,
        term_data=term_data,
        strike_interval=STRIKE_STEP,
        index_name=selected_index
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

    
    bias_conv = master_setup.get("bias_conviction", {})
    vol_trend = master_setup.get("vol_trend", {})
    exec_summary = master_setup.get("executive_summary", {})

    # 3. Status Telemetry & Health Check
    ts = meta.get("timestamp", "N/A")
    ui = ctx.get("ui_display", {}) # Fallback for derived metrics only

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

    # 🥇 OPERATOR ACTION CENTER (SINGLE SOURCE OF TRUTH)
    # Narrative and execution are now pre-computed in backend
    cockpit = master_setup.get("cockpit", {})
    details = cockpit.get("details", {})
    narrative = master_setup.get("narrative", {})
    execution_plan = narrative.get("execution_plan", {})
    payoff_summary = narrative.get("payoff_summary", {})
    
    master_setup = ctx.get("master_setup", {})
    flow_metrics = ctx.get("flow_metrics", {})
    
    if not isinstance(execution_plan, dict):
        execution_plan = {}

    conflict = bias_conv.get("conflict_reason", "")
    

    
    # Dominant Decision (Single Authority)
    action = narrative.get("dominant_action", "WAIT")
    state = narrative.get("dominant_state", "NEUTRAL")
    confidence = narrative.get("confidence", 0.0)

    
    # Action Colors & State
    action_colors = {"ENTER": "#00C805", "EXIT": "#FF3B30", "WAIT": "#FF9500", "STAND ASIDE": "#8E8E93"}
    action_color = safe_color(action_colors.get(action, "#8E8E93"))
    
    # Authoritative Alignment Visualization (Computed from Source)
    alignment = master_setup.get("alignment", "ALIGNED")
    alignment_color = safe_color("#00C805" if alignment == "ALIGNED" else "#FF9500" if alignment == "DIVERGENT" else "#FF3B30")
    
    # Upgrade: System is tradeable if we are entering OR exiting
    is_tradeable = action in ("ENTER", "EXIT")

    conf = narrative.get("execution_confidence", {})
    conf_val = conf.get("value", 0.0)
    conf_color = safe_color("#FF3B30" if conf_val < 0.4 else "#007AFF" if conf_val < 0.7 else "#00C805")
    
    # Operator Action Center (Authoritative View)
    reasons_html = "".join([f'<div style="color: #E0E0E0; font-size: 1.1em; font-weight: 600; margin-bottom: 12px; display: flex; gap: 10px;"><span>✅</span> {safe(r)}</div>' for r in narrative.get('reasoning', [])])
    triggers_html = "<br>• ".join([safe(t) for t in narrative.get('triggers', ["Maintain thesis monitoring."])])

    st.markdown(f"""<div style="background: linear-gradient(180deg, rgba(30,30,30,0.95), rgba(20,20,20,0.98)); padding: 40px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 30px 60px rgba(0,0,0,0.5); margin-bottom: 30px;"><div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 25px; margin-bottom: 25px;"><div style="flex: 2;"><span style="font-size: 0.9em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 2px;">Structural Authority State</span><div style="margin-top: 10px;"><span style="font-size: 2.8em; color: #FFFFFF; font-weight: 900; letter-spacing: -1.5px; text-transform: uppercase;">{safe(state)}</span></div></div><div style="flex: 1; text-align: right;"><span style="font-size: 0.9em; color: {action_color}; text-transform: uppercase; font-weight: 900; letter-spacing: 2px;">Required Action</span><div style="margin-top: 10px;"><span style="font-size: 3.5em; color: {action_color}; font-weight: 950; letter-spacing: 2px; text-shadow: 0 0 30px {action_color}44;">{safe(action)}</span></div></div></div><div style="display: flex; gap: 40px;"><div style="flex: 1.5; border-right: 1px solid rgba(255,255,255,0.05); padding-right: 30px;"><span style="font-size: 0.8em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Why This Action?</span><div style="margin-top: 15px;">{reasons_html}</div></div><div style="flex: 1.2; border-right: 1px solid rgba(255,255,255,0.05); padding-right: 30px;"><span style="font-size: 0.8em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Next Strategy Target</span><div style="margin-top: 15px; background: rgba(0,122,255,0.05); border: 1px solid rgba(0,122,255,0.1); padding: 15px; border-radius: 12px;"><span style="color: #007AFF; font-weight: 800; font-size: 1.2em;">{safe(narrative.get('next_trade'))}</span></div><div style="margin-top: 20px;"><span style="font-size: 0.75em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Activation Triggers</span><div style="margin-top: 8px; color: #AAAAAA; font-size: 0.9em; font-style: italic;">• {triggers_html}</div></div></div><div style="flex: 0.8;"><span style="font-size: 0.8em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Execution Confidence</span><div style="margin-top: 15px; text-align: center;"><div style="font-size: 2.2em; font-weight: 900; color: {conf_color};">{safe(conf.get('label'))}</div><div style="font-size: 1.1em; color: #FFFFFF; opacity: 0.6; margin-top: 2px;">{conf_val:.2f}</div><div style="margin-top: 15px; height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden;"><div style="width: {conf_val*100}%; height: 100%; background: {conf_color}; box-shadow: 0 0 15px {conf_color};"></div></div><div style="margin-top: 10px; font-size: 0.75em; color: #8E8E93; line-height: 1.3;">{safe(conf.get('reason'))}</div></div></div></div></div>""", unsafe_allow_html=True)

    # ==================== 🧩 2. SUPPORTING MARKET LOGIC ====================
    st.markdown("### 🧩 Supporting Market Logic")
    c_beh, c_snap = st.columns([1.2, 1])
    
    with c_beh:
        st.markdown("##### 🧩 Dealer Behavior Panel")
        behaviors = cockpit.get("dealer_behavior", [])
        beh_html = ""
        for b in behaviors:
            state_color = safe_color("#00C805" if b['state'] in ["LONG", "POSITIVE"] else "#FF3B30" if b['state'] in ["SHORT", "NEGATIVE"] else "#8E8E93")
            beh_html += f'<div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 15px; margin-bottom: 12px; display: flex; align-items: center; gap: 15px;">'
            beh_html += f'<div style="flex: 0 0 80px; text-align: center; border-right: 1px solid rgba(255,255,255,0.1); padding-right: 10px;">'
            beh_html += f'<span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 800;">{safe(b["label"])}</span><br>'
            beh_html += f'<span style="font-size: 1em; font-weight: 900; color: {state_color};">{safe(b["state"])}</span></div>'
            beh_html += f'<div style="flex: 1; color: #5AC8FA; font-size: 1em; font-weight: 700;">{safe(b["behavior"])}</div></div>'
        st.markdown(beh_html, unsafe_allow_html=True)

    with c_snap:
        st.markdown("##### 🧠 Greek Snapshot")
        snapshot = cockpit.get("greek_snapshot", [])
        snap_html = '<div style="background: rgba(255,255,255,0.03); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.05);">'
        for s in snapshot:
            val_color = safe_color("#00C805" if s['color'] == "green" else "#FF3B30" if s['color'] == "red" else "#007AFF" if s['color'] == "blue" else "#FF9500")
            snap_html += f'<div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">'
            snap_html += f'<span style="color: #8E8E93; font-weight: 600; font-size: 0.9em;">{safe(s["label"])}</span>'
            snap_html += f'<div style="text-align: right;"><span style="color: {val_color}; font-weight: 900; font-size: 1.1em;">{safe(s["value"])}</span><br>'
            snap_html += f'<span style="color: #666; font-size: 0.7em; text-transform: uppercase; font-weight: 800;">{safe(s["meaning"])}</span></div></div>'
        snap_html += '</div>'
        st.markdown(snap_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    if conflict:
        st.error(f"⚠️ **FLOW CONFLICT DETECTED**: {safe(bias_conv.get('conflict_reason', 'Macro and GEX signals are diverging.'))}")
        
    # --- SECTION: TACTICAL EXECUTION PLAN (CONSOLIDATED) ---
    st.write("### 📖 TACTICAL EXECUTION PLAN")
    
    if not is_tradeable:
        st.info(f"🛡️ **STANDBY MODE**: {safe(narrative.get('next_trade', 'No target'))} is currently being monitored. Execution legs are hidden until activation triggers are met.")
    
    p1, p2 = st.columns([1, 1.2])
    with p1:
        st.markdown("**Decision Trail**")
        for step in narrative.get('decision_trail', []):
            st.caption(f"🔍 {step}")
            
        st.markdown("**Primary Risk**")

        risk_obj = narrative.get("risk", "Standard Greek Decay / Whipsaw")
        if isinstance(risk_obj, dict):
            st.markdown(f"⚠️ **{risk_obj.get('risk_type', 'Market Noise')}**")
            st.caption(f"**Invalidation**: {risk_obj.get('invalidation', 'Thesis holds.')}")
        else:
            st.markdown(f"⚠️ {risk_obj}")

    with p2:
        if is_tradeable:
            # Dynamic Styling for Legibility
            action_state = "ACTIVE EXECUTION" if action == "ENTER" else "EXIT / UNWIND"
            plan_bg = "rgba(0, 40, 5, 0.95)" if action == "ENTER" else "rgba(40, 5, 0, 0.95)"
            plan_border = "rgba(0, 200, 5, 0.3)" if action == "ENTER" else "rgba(200, 5, 0, 0.3)"
            accent_color = "#00C805" if action == "ENTER" else "#FF3B30"
            text_color = "#E0E0E0"

            # [AUTHORITATIVE FIX] Source strike plan ONLY from narrative-sanctioned execution plan
            
            st.markdown(f"### <span style='color:{accent_color}'>{action_state}</span>", unsafe_allow_html=True)
            if isinstance(execution_plan, dict):
                st.caption(f"**{execution_plan.get('template', 'TACTICAL TEMPLATE').upper()}**")
                for leg in execution_plan.get("legs", []):
                    st.markdown(f"- **{leg['type']} {leg['opt']}** → `{leg['strike']}`")
            else:
                st.caption("**TACTICAL TEMPLATE**")
                st.write("No trade structure viable for current state.")
                
            st.markdown("---")
            st.markdown("**Activation Trigger**")
            for t in narrative.get('triggers', ['Manual confirmation required.']):
                st.markdown(f"* {safe(t)}")
        else:
            st.caption("Execution legs are suppressed. Clear the activation triggers to view strike details.")
            
        st.markdown("### 🎯 Threat Invalidation")
        st.error(f'**STOP THESIS**: {narrative.get("invalidation", "Thesis holds in current regime.")}')
        if narrative.get('avoid'):
            for a in narrative.get('avoid', []):
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
        text_color = safe_color("#FFFFFF" if l['label'] in ("CALL WALL", "PUT WALL", "SPOT") else "#121212")
        l_color = safe_color(l['color'])
        
        strip_html += f"""
        <div style="flex: 1; background: {l_color}; padding: 15px 5px; border-radius: 6px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); position: relative; min-width: 80px;">
            <div style="font-size: 0.65em; font-weight: 900; color: {text_color}; opacity: 0.9; text-transform: uppercase; letter-spacing: 1px;">{safe(l['label'])}</div>
            <div style="font-size: 1.15em; font-weight: 900; color: {text_color}; font-family: 'JetBrains Mono', monospace; margin-top: 4px;">{l['val']:,.0f}</div>
            {"<div style='position: absolute; top: -10px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 8px solid transparent; border-right: 8px solid transparent; border-bottom: 10px solid " + l_color + ";'></div>" if is_spot else ""}
        </div>
        """
    strip_html += '</div>'
    
    # Clean and render
    strip_html = strip_html.replace("\n", "").replace("    ", " ")
    st.markdown(strip_html, unsafe_allow_html=True)
    
    # Reversion Signal Details
    rev_data = narrative.get("reversion", {})
    rev_label = safe(rev_data.get("label", "NEUTRAL"))
    rev_color = safe_color("#00C805" if rev_label == "HIGH_REVERSION" else "#FF9500" if rev_label == "MODERATE_REVERSION" else "gray")
    
    c_rev1, c_rev2 = st.columns([1, 1])
    with c_rev1:
        st.markdown(f"**Reversion Signal**: <span style='color:{rev_color}; font-weight:700;'>{rev_label}</span>", unsafe_allow_html=True)
        st.caption(f"Score: `{rev_data.get('score', 0.0)}/10`")
    with c_rev2:
        if rev_data.get("reasons"):
            st.markdown("**Drivers**")
            st.caption(", ".join(rev_data.get("reasons")))

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
    hist_df = get_historical_snapshot_df(limit=5, daily_only=True, index_name=selected_index)
    
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
            drift_favorable = (abs(drift_pts) > STRIKE_STEP) if is_long_vol else (abs(drift_pts) < (STRIKE_STEP * 0.6))
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
                <div style="background: rgba(255,255,255,0.05); padding: 10px; border-radius: 8px; border-left: 5px solid {action_color}; margin-bottom: 12px;">
                    <span style="font-size: 0.75em; color: #8E8E93; text-transform: uppercase; font-weight: 800;">Dominant Strategy Action</span><br>
                    <span style="font-size: 1.3em; font-weight: 900; color: white;">{action.upper()}</span>
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

            st.markdown(f"**Alignment**: <span style='color:{alignment_color}; font-weight:bold'>{safe(master_setup.get('alignment', 'ALIGNED'))}</span>", unsafe_allow_html=True)
            gamma_regime = str(flow_metrics.get("gamma_regime", "UNKNOWN")).split("(")[0].strip()
            st.caption(f"State: {gamma_regime} | {narrative.get('reversion', {}).get('label', 'Neutral')}")

        with d_cols[1]:
            st.markdown("### 2️⃣ ENVIRONMENT PANEL")
            rb = master_setup.get('regime_badge', {'label': 'Passive', 'color': 'gray'})
            vix_val = vix_df["Close"].iloc[-1] if vix_df is not None else 0
            vix_badge = f"<span style='background-color:#444; color:white; padding:2px 6px; border-radius:4px; font-size:0.7em; margin-left:10px'>VIX: {vix_val:.1f}</span>"
            st.markdown(f"**Regime**: <span style='color:{safe_color(rb['color'])}; font-weight:bold; font-size:1.1em'>{safe(rb['label'])}</span>{vix_badge}", unsafe_allow_html=True)
            
            vt_label = vol_trend.get("vol_trend", "Stable")
            vt_color = "#FF3B30" if "Rising" in vt_label else "#00C805" if "Falling" in vt_label else "gray"
            st.markdown(f"**Vol Trend**: <span style='color:{safe_color(vt_color)};'>{safe(vt_label)}</span>", unsafe_allow_html=True)
            st.markdown(f"**ATM IV**: `{current_atm_iv:.1f}%` (Rank: `{iv_data.get('iv_rank', 50.0)}%`)")
            st.markdown(f"**Flow Label**: `{flow_metrics.get('flow_regime_label', 'Passive')}`")
            rev_data = narrative.get('reversion', {})
            st.markdown(f'**Reversion**: `{rev_data.get("score", 0.0)}/10` <span style="color:{safe_color(vt_color)}; font-weight:bold">({safe(rev_data.get("label", "Neutral"))})</span>', unsafe_allow_html=True)
            
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
            
             # This is the single source of truth for trade legs, with suppression logic applied



            
            if is_tradeable and execution_plan.get("template"):
                st.info(f"**Structure**: {execution_plan.get('template', 'N/A')} | Schema: `{execution_plan.get('schema', 'NONE')}`")
            
            st.markdown("**EXECUTION LEGS:**")
            _leg_shown = False
            for key, label in [("sell_ce", "Sell Call"), ("sell_pe", "Sell Put"), 
                               ("buy_ce", "Buy Call"), ("buy_pe", "Buy Put"),
                               ("sell_leg", "Sell Leg"), ("buy_leg", "Buy Leg")]:
                val = execution_plan.get(key)
                if val and isinstance(val, (int, float)) and val > 0:
                    st.markdown(f"- **{label}** → `{int(val)}`")
                    _leg_shown = True
            
            if not _leg_shown:
                st.markdown("- No trade structure viable for current state.")
            



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
                    
            payoff = narrative.get("payoff_summary", {})
            if payoff and payoff.get("structure") != "No Trade":
                st.divider()
                st.markdown("**PAYOFF MATRIX**")
                p1, p2 = st.columns(2)
                
                with p1:
                    st.markdown(f"**Max Reward**: {safe(str(payoff.get('max_reward', 'N/A')))}")
                    st.write(f"**Max Risk**: {safe(str(payoff.get('max_risk', 'N/A')))}")
                with p2:
                    st.write(f"**Structure**: {safe(str(payoff.get('structure', 'N/A')))}")
                    bes = payoff.get('breakevens', [])
                    if bes:
                        st.write(f"**Breakevens**: {', '.join(bes)}")
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
        gr4, gr5, gr6, gr7 = st.columns(4)
        
        g_ui = ui.get("greeks", {})
        with gr1:
            st.metric("Net Delta", g_ui.get("delta", "N/A"))
        with gr2:
            st.metric("Absolute GEX", g_ui.get("gex_abs", "N/A"))
        with gr3:
            st.metric("Net GEX", g_ui.get("gex_net", "N/A"))
            
        with gr4:
            st.metric("Total Vega", g_ui.get("vega", "N/A"))
        with gr5:
            st.metric("Total Theta", g_ui.get("theta", "N/A"))
        with gr6:
            vanna_val = ui.get("greeks", {}).get("vanna", "N/A")
            st.metric("Total Vanna", vanna_val)
        with gr7:
            tv = flow_metrics.get("tv_ratio", "N/A")
            st.metric("T/V Carry", f"x{tv:.2f}" if isinstance(tv, (int, float)) else "N/A")
            
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
        exec_plan = narrative.get("execution_plan", {})
        if exec_plan and isinstance(exec_plan, dict):
            trade_strikes = [leg.get("strike") for leg in exec_plan.get("legs", []) if leg.get("strike")]
            trade_strikes = [s for s in trade_strikes if isinstance(s, (int, float)) and s > 0]
            
        # Default window +/- 400 around spot
        min_win = min([spot - 400] + trade_strikes) if trade_strikes else spot - 400
        max_win = max([spot + 400] + trade_strikes) if trade_strikes else spot + 400
        
        # FINAL HARDENING: Protect against NaN conversion in range()
        if pd.isna(min_win) or pd.isna(max_win):
            min_win, max_win = spot - 400, spot + 400
            
        map_strikes = range(int(min_win)//STRIKE_STEP*STRIKE_STEP, int(max_win)//STRIKE_STEP*STRIKE_STEP + STRIKE_STEP, STRIKE_STEP)
        
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
        audit_rows = []
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
    2. {highlight_strat('Trend Acceleration', 'TREND_ACCELERATION')} (Momentum)
    3. {highlight_strat('Mean Reversion', 'MEAN_REVERSION')} (Range Stability)
    4. {highlight_strat('Vanna Flow', 'VANNA')} (Vol Dependency)
    5. {highlight_strat('Charm Decay', 'CHARM')} (Passivity)
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
