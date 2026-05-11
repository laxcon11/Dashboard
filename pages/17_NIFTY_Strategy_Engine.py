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

# v3 Calibration Core
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
import nde_ui_primitives

# ⚙️ STRATEGY SIDEBAR
with st.sidebar:
    st.header("🎯 Strategy Tuning")
    view_mode = get_ui_detail_mode(default="Summary")
    st.write("---")
    
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
    if df_exp.empty:
        st.warning("No option chain data available for visualization.")
        return

    calls = df_exp[df_exp["type"] == "call"].copy()
    puts = df_exp[df_exp["type"] == "put"].copy()
    
    c_cols = {"oi": "C_OI", "iv": "C_IV", "delta": "C_Delta", "gamma": "C_Gamma", "vega": "C_Vega", "theta": "C_Theta"}
    p_cols = {"oi": "P_OI", "iv": "P_IV", "delta": "P_Delta", "gamma": "P_Gamma", "vega": "P_Vega", "theta": "P_Theta"}
    
    calls_renamed = calls.rename(columns=c_cols)
    puts_renamed = puts.rename(columns=p_cols)
    
    available_c = [v for k, v in c_cols.items() if k in calls.columns]
    available_p = [v for k, v in p_cols.items() if k in puts.columns]
    
    calls_final = calls_renamed[["strike"] + available_c]
    puts_final = puts_renamed[["strike"] + available_p]
    
    chain = pd.merge(calls_final, puts_final, on="strike", how="outer").sort_values("strike")
    strikes = chain["strike"].values
    closest_strike = strikes[np.abs(strikes - spot).argmin()]
    idx_closest = chain[chain["strike"] == closest_strike].index[0]
    
    loc = chain.index.get_loc(idx_closest)
    center_idx = loc.start if isinstance(loc, slice) else (loc.argmax() if hasattr(loc, 'argmax') else loc)
    
    start_idx = max(0, center_idx - 12)
    end_idx = min(len(chain), center_idx + 13)
    chain_filtered = chain.iloc[start_idx:end_idx].copy()
    
    dns_zones = intel.get("dns_zones", [])
    optimal = intel.get("optimal_strikes", {})
    call_wall, put_wall = walls
    
    def highlight_row(row):
        style = [''] * len(row)
        s = row["strike"]
        for zone in dns_zones:
            if zone[0] <= s <= zone[1]:
                return ['background-color: rgba(255, 0, 0, 0.2); border-left: 2px solid red;'] * len(row)
        is_rec = False
        if optimal:
            if "put" in optimal and s == optimal["put"]["strike"]: is_rec = True
            if "call" in optimal and s == optimal["call"]["strike"]: is_rec = True
        if is_rec:
            return ['background-color: rgba(0, 255, 0, 0.15); border-left: 3px solid #00ff00; font-weight: bold;'] * len(row)
        if s == call_wall:
            style = ['border-top: 2px dashed #00b0ff; color: #00b0ff;'] * len(row)
        elif s == put_wall:
            style = ['border-bottom: 2px dashed #00b0ff; color: #00b0ff;'] * len(row)
        if s == closest_strike:
            strike_col_idx = list(chain_filtered.columns).index("strike")
            style[strike_col_idx] = 'background-color: #ffd700; color: black; font-weight: bold;'
        return style

    final_cols = ["C_Theta", "C_Vega", "C_Gamma", "C_Delta", "C_OI", "strike", "P_OI", "P_Delta", "P_Gamma", "P_Vega", "P_Theta"]
    present_cols = [c for c in final_cols if c in chain_filtered.columns]
    
    styled_df = chain_filtered[present_cols].style.apply(highlight_row, axis=1).format({
        "C_Delta": "{:.2f}", "C_Gamma": "{:.4f}", "C_Vega": "{:.2f}", "C_Theta": "{:.2f}",
        "P_Delta": "{:.2f}", "P_Gamma": "{:.4f}", "P_Vega": "{:.2f}", "P_Theta": "{:.2f}",
        "C_OI": "{:,.0f}", "P_OI": "{:,.0f}", "strike": "{:.0f}"
    })
    
    st.dataframe(styled_df, use_container_width=True, height=600, hide_index=True)

# ==================== UI SETUP ====================
setup_page("Nifty Strategy Engine")
st.title(f"🎯 {selected_index} Strategy Engine")

@st.cache_data(ttl=300, show_spinner=False)
def load_cached_term_structure(index_name):
    return nde_options_logic.compute_term_structure(index_name)

from nde_automation_logic import get_historical_snapshot_df, write_daily_nde_snapshot
term_data = load_cached_term_structure(selected_index)

try:
    # ═══════════════════════════════════════════════════════════════════
    # 1. LOAD DATA
    # ═══════════════════════════════════════════════════════════════════
    regime_history = load_regime_history(index_name=selected_index)
    market_data = batch_download([ticker, "^INDIAVIX"], period="3mo")
    nifty_df = market_data.get(ticker)
    vix_df = market_data.get("^INDIAVIX")
    
    raw_chain, used_expiry, source, meta, fname = nde_options_logic.load_index_v3_data(selected_filename, index_name=selected_index)
    
    # Secure Spot Extraction (FAIL HARD)
    spot = None
    if nifty_df is not None and not nifty_df.empty:
        spot = float(nifty_df["Close"].iloc[-1])
    
    if spot is None or pd.isna(spot) or spot <= 0:
        spot = meta.get("underlyingValue") or meta.get("spot_at_fetch") or meta.get("spot")

    if spot is None or pd.isna(spot) or spot <= 0:
        st.error("### 🛑 CRITICAL ENGINE FAILURE: MISSING PRICE DATA")
        st.stop()

    # ═══════════════════════════════════════════════════════════════════
    # 2. UNIFIED ENGINE CONTEXT
    # ═══════════════════════════════════════════════════════════════════
    from nde_strategy_logic import generate_engine_context
    
    # generate_engine_context already calls adapt_context_for_ui internally
    ctx = generate_engine_context(
        raw_chain=raw_chain, spot=spot, nifty_df=nifty_df, used_expiry=used_expiry,
        regime_history=regime_history, regime_snap=load_regime_snapshot(index_name=selected_index),
        vix_df=vix_df, meta=meta, mode=mode, source=source, term_data=term_data,
        strike_interval=STRIKE_STEP, index_name=selected_index
    )
    
    # Graceful degradation: if adapter fails, show error instead of blank page
    try:
        ui = ctx.ui
        narrative = ctx.narrative
    except Exception as adapter_err:
        st.error(f"UI Adapter Error: {adapter_err}. Falling back to raw context.")
        st.exception(adapter_err)
        st.stop()

    # ═══════════════════════════════════════════════════════════════════
    # PRIORITY 0 — OPERATOR COCKPIT (Core Cognition)
    # ═══════════════════════════════════════════════════════════════════
    
    # 🥇 1. STRUCTURAL AUTHORITY + ACTION + CONFIDENCE + WHY
    nde_ui_primitives.render_hero_cockpit(ui)
    nde_ui_primitives.render_execution_summary(ui)

    # 🎯 2. THREAT INVALIDATION
    nde_ui_primitives.render_threat_invalidation(ui, narrative)
    
    # 📖 3. TACTICAL EXECUTION PLAN
    st.markdown("### 📖 TACTICAL EXECUTION PLAN")
    if not ui.is_tradeable:
        st.info(f"🛡️ **STANDBY MODE**: {safe(narrative.next_trade)} monitoring. Legs hidden.")
    
    p1, p2 = st.columns([1, 1.2])
    with p1:
        st.markdown("**Decision Trail**")
        for step in narrative.reasoning:
            st.caption(f"🔍 {step}")
        st.markdown("**Primary Risk**")
        st.markdown(f"⚠️ {safe(narrative.invalidation)}")

    with p2:
        st.markdown("**Strategy Template**")
        st.code(f"TEMPLATE: {ctx.execution.strategy_code}\nACTION: {ctx.execution.action}", language="yaml")
        if ui.is_tradeable:
            st.markdown("**Leg Configuration**")
            for leg in ctx.execution.legs:
                action = leg.get('action', leg.get('side', leg.get('type', '?')))
                instrument = leg.get('instrument', leg.get('opt', '?'))
                strike = leg.get('strike', 0)
                st.write(f"🔹 {str(action).upper()} {str(instrument).upper()} @ {int(strike)}")

    if source == "CACHED" and meta.get("spot_at_fetch"):
        drift_pct = abs(spot - meta["spot_at_fetch"]) / spot * 100
        if drift_pct > 0.5:
            st.warning(f"⚠️ **SPOT DRIFT**: Market is {drift_pct:.2f}% away from cached snapshot.")

    # ═══════════════════════════════════════════════════════════════════
    # PRIORITY 1 — CONTEXT & TRUST
    # ═══════════════════════════════════════════════════════════════════

    # 🧩 4. DEALER BEHAVIOR + GREEK SNAPSHOT
    st.markdown("### 🧩 Supporting Market Logic")
    nde_ui_primitives.render_market_logic(ui)
    
    # 🧭 5. KEY TRADING LEVELS
    nde_ui_primitives.render_trading_levels(ui)
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ⏱️ 6. WHAT CHANGED
    st.write("---")
    hist_df = get_historical_snapshot_df(limit=5, daily_only=True, index_name=selected_index)
    nde_ui_primitives.render_what_changed(ctx, hist_df, ui)

    # ═══════════════════════════════════════════════════════════════════
    # PRIORITY 2 — DEEP ANALYTICS (Tabs)
    # ═══════════════════════════════════════════════════════════════════

    tab_dashboard, tab_intel, tab_risk, tab_audit = st.tabs(["🏆 Strategy", "🧠 Intelligence", "🗺️ Risk Map", "📋 Audit"])

    with tab_dashboard:
        st.header("🏆 PRIMARY TRADE SETUP")
        st.markdown(ui.execution_summary, unsafe_allow_html=True)
        d_cols = st.columns(3)
        with d_cols[0]:
            st.markdown("### 1️⃣ DECISION")
            st.markdown(f"**Action**: `{ui.hero_action}`")
            conf_norm = ctx.state.confidence if ctx.state.confidence <= 1.0 else ctx.state.confidence / 10.0
            st.progress(min(conf_norm, 1.0), text=f"Confidence: {conf_norm*100:.0f}%")
        with d_cols[1]:
            st.markdown("### 2️⃣ ENVIRONMENT")
            st.markdown(f"**ATM IV**: `{ctx.flow.atm_iv_current:.1f}%`")
            st.markdown(f"**Regime**: `{ctx.state.state}`")
            st.markdown(f"**Flow**: `{ctx.flow.flow_regime_label}`")
            st.markdown(f"**Gamma**: `{ctx.flow.gamma_regime}`")
        with d_cols[2]:
            st.markdown("### 3️⃣ RATIONALE")
            for r in narrative.reasoning[:4]:
                st.caption(f"- {r}")

    with tab_intel:
        st.header("🧠 INSTITUTIONAL INTELLIGENCE")
        st.divider()
        
        iq = ctx.flow.intelligence
        
        # Row 1: Core institutional metrics
        i1, i2, i3 = st.columns(3)
        with i1: st.metric("Max Pain", f"{int(iq.get('max_pain', 0)):,}")
        with i2: st.metric("PCR (OI)", ui.pcr_display)
        with i3: st.metric("Gamma Flip", f"{ctx.flow.gamma_flip_level:,.0f}")
        
        # Row 2: Extended metrics
        i4, i5, i6 = st.columns(3)
        with i4: st.metric("Expected Move", ui.expected_move_display)
        with i5: st.metric("Suppression", ui.suppression_display)
        with i6: st.metric("IV/RV Ratio", f"{ctx.rv.iv_rv_ratio:.2f}")
        
        # Row 3: Flow regime context
        i7, i8, i9 = st.columns(3)
        with i7: st.metric("Flow Regime", ctx.flow.flow_regime_label)
        with i8: st.metric("TV Ratio", f"{ctx.flow.tv_ratio:.2f} ({ctx.flow.tv_label})")
        with i9: st.metric("ATM OI Share", f"{ctx.flow.atm_oi_share:.1f}%")

    with tab_risk:
        st.header("🗺️ RISK SURFACE MAP")
        nde_ui_primitives.render_threat_invalidation(ui, narrative)
        with st.expander("🏛️ Full Option Chain Explorer", expanded=True):
            render_institutional_option_chain(ctx.flow.raw_exposures, ctx.spot, iq, (ctx.flow.call_wall, ctx.flow.put_wall))

    with tab_audit:
        st.header("📋 SYSTEM AUDIT")
        a1, a2, a3, a4 = st.columns(4)
        with a1: st.metric("Coherence Score", f"{ctx.state.coherence_score*100:.1f}%")
        with a2: st.metric("Trend Drift", f"{ctx.meta.get('drift', 0.0):.2f}")
        with a3: st.metric("Drift Accel", f"{ctx.meta.get('drift_accel', 0.0):.2f}")
        with a4: st.metric("Transition Risk", f"{ctx.state.transition_risk*100:.1f}%")
        
        st.markdown("**Telemetry**")
        t = ctx.telemetry
        t1, t2, t3, t4 = st.columns(4)
        with t1: st.metric("Flow", f"{t.flow_ms:.1f}ms")
        with t2: st.metric("RV", f"{t.rv_ms:.1f}ms")
        with t3: st.metric("State", f"{t.state_ms:.1f}ms")
        with t4: st.metric("Total", f"{t.total_ms:.1f}ms")

    # ═══════════════════════════════════════════════════════════════════
    # SIDEBAR — Strategy Hierarchy & Persistence
    # ═══════════════════════════════════════════════════════════════════
    
    st.sidebar.divider()
    st.sidebar.header("⚖️ Strategy Hierarchy")
    _STRATEGY_HIERARCHY = [
        ("GAMMA_FLIP",         "Gamma Flip"),
        ("TREND_ACCELERATION", "Trend Acceleration"),
        ("MEAN_REVERSION",     "Mean Reversion"),
        ("VANNA",              "Vanna Flow"),
        ("CHARM",              "Charm Decay"),
    ]
    for i, (code, name) in enumerate(_STRATEGY_HIERARCHY, 1):
        active = ctx.execution.strategy_code == code
        label = f"**{i}. {name}** 👈 *Active*" if active else f"{i}. {name}"
        st.sidebar.markdown(f"- {label}")

    nde_ui_primitives.render_telemetry(ctx)

    # Snapshot save with confirmation step
    if "snapshot_confirm" not in st.session_state:
        st.session_state.snapshot_confirm = False

    if st.sidebar.button("💾 Finalize Daily Snapshot"):
        st.session_state.snapshot_confirm = True

    if st.session_state.get("snapshot_confirm"):
        st.sidebar.warning("⚠️ This will overwrite today's snapshot. Continue?")
        sc1, sc2 = st.sidebar.columns(2)
        with sc1:
            if st.button("✅ Confirm", key="snap_yes"):
                try:
                    from nde_automation_logic import compute_probabilities, compute_transition_risk
                    c_probs = compute_probabilities(ctx.state.state, ctx.meta.get("drift", 0.0), ctx.meta.get("persistence", 0))
                    c_escalation = compute_transition_risk(ctx.meta.get("drift", 0.0), ctx.meta.get("stability", 50))
                    saved_f = write_daily_nde_snapshot(
                        curr_regime=ctx.state.state, persistence=ctx.meta.get("persistence", 0),
                        stability_20d=ctx.meta.get("stability", 50.0), stability_5d=ctx.meta.get("stability_5d", 50.0),
                        drift=ctx.meta.get("drift", 0.0), drift_accel=ctx.meta.get("drift_acceleration", 0.0),
                        fragility=ctx.meta.get("fragility", False), probs=c_probs, escalation=c_escalation,
                        used_expiry=ctx.meta.get("expiry_date", ""), gamma_regime=ctx.flow.gamma_regime,
                        flip=ctx.flow.gamma_flip_level, vanna=ctx.flow.vanna_bias,
                        charm=ctx.flow.charm_flow,
                        flow_regime=ctx.flow.flow_regime_label, total_gex=ctx.flow.total_gex,
                        t_bias=ctx.state.bias_tactical, s_bias=ctx.state.bias_structural,
                        spot=ctx.spot, atr=ctx.atr, config_hash=CONFIG_VERSION, source_mode=ctx.source,
                        data_quality_score=ctx.state.confidence, tv_label=ctx.flow.tv_label,
                        convergence_score=ctx.state.coherence_score, strategy_code=ctx.execution.strategy_code,
                        inst_iq=ctx.flow.intelligence, atm_iv=ctx.flow.atm_iv_current
                    )
                    st.sidebar.success(f"Snapshot saved: {saved_f.name}")
                    st.session_state.snapshot_confirm = False
                except Exception as e:
                    st.sidebar.error(f"Error saving snapshot: {e}")
        with sc2:
            if st.button("❌ Cancel", key="snap_no"):
                st.session_state.snapshot_confirm = False
                st.rerun()

except Exception as e:
    st.error(f"Critical Error in Strategy Engine: {e}")
    st.exception(e)
