import streamlit as st
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
from pathlib import Path

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
from utils import setup_page

# ⚙️ STRATEGY SIDEBAR
with st.sidebar:
    st.header("🎯 Strategy Tuning")
    mode = st.radio("Execution Mode", ["Defensive", "Balanced", "Aggressive"], index=1, help="Adjusts strike widening/tightness.")
    st.caption(f"Engine: `{CONFIG_VERSION}`")
    st.write("---")

    # ── INGESTION HUB ──────────────────────────────────────────
    st.subheader("🌐 Sensibull Greeks Ingestion")

    import sys as _sys
    _scripts_dir = str(Path(__file__).parent.parent / "scripts")
    if _scripts_dir not in _sys.path:
        _sys.path.insert(0, _scripts_dir)

    from sensibull_smart_fetch import get_target_expiries, get_manual_download_urls
    from process_sensibull_excel import process_all_downloads
    from process_sensibull_csv import convert_all_sensibull_csvs

    # ── Auto-convert any raw Sensibull files already in the folder ─
    _raw = list(Path("data/option_chain").glob("*NIFTY*.xlsx")) + list(Path("data/option_chain").glob("*NIFTY*.csv"))
    _raw = [f for f in _raw if not f.name.startswith("option-chain-ED-sensi-")]
    if _raw:
        _converted = convert_all_sensibull_csvs()
        if _converted:
            st.toast(f"🔄 Auto-converted {_converted} raw Sensibull files", icon="🦅")

    # ── Status banner ─────────────────────────────────────────
    sensi_active = False
    sensi_count  = 0
    try:
        sensi_files = list(Path("data/option_chain").glob("option-chain-ED-sensi-NIFTY-*.csv"))
        sensi_count = len(sensi_files)
        if sensi_files:
            latest   = max(sensi_files, key=lambda f: f.stat().st_mtime)
            age_mins = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds() / 60
            if age_mins < 480:          # 8-hour freshness window
                sensi_active = True
                st.success(f"🦅 Greeks Active · {sensi_count} expiries · {int(age_mins)}m ago")
            else:
                st.warning(f"⏳ Greeks Stale ({int(age_mins // 60)}h {int(age_mins % 60)}m) — refresh recommended")
    except Exception:
        pass

    if not sensi_active and sensi_count == 0:
        st.info("💡 No Greeks loaded yet — follow the steps below.")

    st.write("---")

    # ── Step-by-step download guide ────────────────────────────
    st.markdown("**Step 1 — Download the required expiries from Sensibull (Greeks page):**")
    st.markdown(f"&nbsp;&nbsp;&nbsp;[🔗 Open Sensibull NIFTY Option Chain](https://web.sensibull.com/option-chain?view=greeks&tradingsymbol=NIFTY)")

    st.markdown("**Step 2 — Move files to `data/option_chain` and click:**")

    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("📥 Process Local Folder", use_container_width=True,
                     help="Scans data/option_chain/ for any Sensibull files and ingests them."):
            with st.spinner("Scanning data/option_chain..."):
                count = process_all_downloads()
                if count > 0:
                    st.success(f"✅ Ingested **{count}** expiries into the engine!")
                    st.rerun()
                else:
                    st.info(
                        "No **new** raw files found to process. "
                        "If you see 'Greeks Active' above, your data is already loaded. "
                        "Only new Downloads from Sensibull need to be processed."
                    )
    with col2:
        if st.button("🧹 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── Upload Fallback ───────────────────────────────────────
    with st.expander("📂 Drag-and-drop (alternative to manual move)"):
        up = st.file_uploader("Drop Sensibull Excel here", type=["xlsx", "csv"],
                               accept_multiple_files=True)
        if up:
            saved = 0
            tmp = Path("/tmp/sensibull_upload")
            tmp.mkdir(exist_ok=True)
            for f in up:
                dest = tmp / f.name
                dest.write_bytes(f.getbuffer())
                saved += 1
            if saved:
                count = process_all_downloads(extra_dir=tmp)
                if count > 0:
                    st.success(f"✅ Ingested {count} expiries from uploaded files!")
                    st.rerun()
                else:
                    st.error("Uploaded but couldn't parse. Check file format.")

    st.write("---")

    # ── EXPIRY: Auto-select nearest active only ────────────────
    # Strategy Engine = current expiry only.
    # All expiries are available on the Monthly Engine page.
    st.subheader("📅 Active Expiry")
    available_chains = nde_options_logic.list_available_option_chains()

    selected_filename = None
    if available_chains:
        nearest = next((c for c in available_chains if c.get("is_near_active")), available_chains[0])
        selected_filename = nearest["filename"]
        st.success(f"🗓️ **{nearest['expiry']}** ({nearest['type']})")
        st.caption("Monthly Engine shows all expiries.")
    else:
        st.warning("No option chain data found. Download from Sensibull above.")

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
    
    st.dataframe(styled_df, use_container_width=True, height=600, hide_index=True)

# ==================== UI SETUP ====================
setup_page("Nifty Strategy Engine")


st.title("🎯 NIFTY Strategy Engine (NDE)")
st.caption("Derived from NDE v12 Intelligence Layer")

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
        source=source
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

    # 3. Status Telemetry & Health Check
    ts = meta.get("timestamp", "N/A")
    ui = ctx["ui_display"]
    
    st.markdown(
        f"<span style='color:{ui['source_color']}; font-weight:bold;'>• {source}</span> | "
        f"Quality: <span style='color:{ui['quality_color']}; font-weight:bold;'>{quality_score:.1f}</span> | "
        f"{ts} | Expiry: `{used_expiry}`", 
        unsafe_allow_html=True
    )
    
    v_flags = meta.get("validation_flags", [])
    if v_flags:
        st.warning(f"⚠️ **Validation Warnings**: {', '.join(v_flags)}")

    # Spot Drift Warning
    if source == "CACHED" and meta.get("spot_at_fetch"):
        cached_spot = meta["spot_at_fetch"]
        drift_pct = abs(spot - cached_spot) / spot * 100
        if drift_pct > 0.5:
            st.warning(f"⚠️ **SPOT DRIFT**: Market is {drift_pct:.2f}% away from cached snapshot (Spot: {spot:.0f}, Cache: {cached_spot:.0f}). Option Walls might be stale.")

    # 🏆 SECTION 1: PRIMARY TRADE SETUP
    st.divider()
    st.header("🏆 PRIMARY TRADE SETUP (Deterministic)")

    # 🧠 SECTION 2: THE DECISION & EXECUTION plan
    st.write("---")
    
    # 3-Layer UI Panel (Phase 37)
    d1, d2, d3 = st.columns(3)
    
    with d1:
        st.markdown("### 1️⃣ DECISION CARD")
        flip_lvl = flow_metrics.get("gamma_flip_level", None)
        flip_dist_pct = abs(spot - flip_lvl)/spot*100 if flip_lvl is not None and spot > 0 else 0
        flip_badge = f"<span style='font-size: 0.85em; color: gray;'> (Flip: {flip_dist_pct:.1f}%)</span>" if flip_lvl is not None and flip_lvl > 0 else ""
        st.markdown(f"**Strategy**: `{master_setup['name']}`{flip_badge}", unsafe_allow_html=True)
        
        score = master_setup.get("quality_score", 0)
        rec_size = master_setup.get("size", 1.0)
        st.progress(min(1.0, score / 10.0), text=f"Quality: {score}/10 (Size: {rec_size:.1f}x)")
        
        # v3: Net Yield Summary
        pnl = master_setup.get("estimated_pnl", {})
        if pnl:
            st.markdown(f"**Est. Yield**: ₹{int(pnl.get('net',0)):,} <span style='color:gray; font-size:0.8em'>(Gross: ₹{int(pnl.get('gross',0)):,})</span>", unsafe_allow_html=True)

        st.markdown(f"**Alignment**: <span style='color:{ui['alignment_color']}; font-weight:bold'>{master_setup.get('alignment', 'ALIGNED')}</span>", unsafe_allow_html=True)
        
        # Risk Badge
        gamma_regime = str(flow_metrics.get("gamma_regime", "UNKNOWN")).split("(")[0].strip()
        st.caption(f"State: {gamma_regime} | {ui['tv_ratio']['label']}")

        
    with d2:
        st.markdown("### 2️⃣ ENVIRONMENT PANEL")
        
        # Regime Display
        rb = ui["regime_badge"]
        vix_val = vix_df["Close"].iloc[-1] if vix_df is not None else 0
        vix_badge = f"<span style='background-color:#444; color:white; padding:2px 6px; border-radius:4px; font-size:0.7em; margin-left:10px'>VIX: {vix_val:.1f}</span>"
        st.markdown(f"**Regime**: <span style='color:{rb['color']}; font-weight:bold; font-size:1.1em'>{rb['label']}</span>{vix_badge}", unsafe_allow_html=True)
        
        st.markdown(f"**ATM IV**: `{current_atm_iv:.1f}%` (Rank: `{iv_data.get('iv_rank', 50.0)}%`)")
        
        st.markdown(f"**TV Ratio**: `{ui['tv_ratio']['val']}` <span style='color:{ui['tv_ratio']['color']}; font-weight:bold'>({ui['tv_ratio']['label']})</span>", unsafe_allow_html=True)
        
        st.markdown(f"**Flip Velocity**: <span style='color:{ui['flip_vel']['color']}'>{ui['flip_vel']['label']}</span>", unsafe_allow_html=True)

        
    with d3:
        st.markdown("### 3️⃣ SIGNAL MATRIX")
        buckets = master_setup.get("quality_breakdown", {}).get("convergence_buckets", {})
        
        weights = {"macro": "30%", "flow": "25%", "structure": "20%", "momentum": "15%", "vol": "10%"}
        
        # Checkmarks mapping securely to orthogonal logic vectors (Phase 37.1)
        st.markdown(f"{'✅' if buckets.get('macro') else '❌'} Regime `({weights['macro']})`")
        st.markdown(f"{'✅' if buckets.get('flow') else '❌'} GEX `({weights['flow']})`")
        st.markdown(f"{'✅' if buckets.get('momentum') else '❌'} Drift `({weights['momentum']})`")
        st.markdown(f"{'✅' if buckets.get('vol') else '❌'} IV `({weights['vol']})`")
        st.markdown(f"{'✅' if buckets.get('structure') else '❌'} Stability `({weights['structure']})`")


    st.divider()

    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown("#### ⚡ EXECUTION INSTRUCTIONS")
        if mode == "Aggressive":
            st.markdown(f"**Mode**: **{mode}** (Tighter strikes, deeper decay capture)")
        elif mode == "Defensive":
            st.markdown(f"**Mode**: **{mode}** (Wider protection, risk averse)")
        else:
            st.markdown(f"**Mode**: **{mode}** (Optimal yield-risk balance)")
        
        template = master_setup.get("template")
        if template:
            st.divider()
            exec_data = template.get('execution', {})
            if exec_data.get("type"):
                st.info(f"**Type**: {exec_data.get('type')}")
                st.write(f"- Bias: {exec_data.get('bias')}")
                st.write(f"- Vol Edge: {exec_data.get('vol_edge')}")
            else:
                sell_c = int(exec_data.get('sell_call', 0)) or 'N/A'
                sell_p = int(exec_data.get('sell_put', 0)) or 'N/A'
                
                # Retrieve individual risk profiles
                dns_zones = intel.get("dns_zones", [])
                raw_exp_intel = flow_metrics.get("raw_exposures", pd.DataFrame())
                rc = nde_options_logic.get_strike_risk_profile(sell_c, raw_exp_intel, dns_zones) if sell_c != 'N/A' else "UNKNOWN"
                rp = nde_options_logic.get_strike_risk_profile(sell_p, raw_exp_intel, dns_zones) if sell_p != 'N/A' else "UNKNOWN"
                
                # Color tags
                rc_color = "🟢 (LOW RISK)" if rc == "LOW" else "🟡 (MED RISK)" if rc == "MED" else "🔴 (HIGH RISK)"
                rp_color = "🟢 (LOW RISK)" if rp == "LOW" else "🟡 (MED RISK)" if rp == "MED" else "🔴 (HIGH RISK)"
                
                st.markdown("**SELL:**")
                st.markdown(f"- **PUT**  → `{sell_p}`  {rp_color}")
                st.markdown(f"- **CALL** → `{sell_c}`  {rc_color}")
                
                # v3: Cost-Aware Payoff
                pnl = master_setup.get("estimated_pnl", {})
                if pnl:
                    st.markdown("**Yield & Costs:**")
                    st.markdown(f"- **Gross Yield** → `₹{int(pnl.get('gross',0)):,}`")
                    st.markdown(f"- **Est. Costs**  → `₹{int(pnl.get('costs',0)):,}`")
                    st.markdown(f"- **Net Profit**  → `₹{int(pnl.get('net',0)):,}`")
                
                exp_theta = template.get("expected_theta_per_lot", 0.0)
                if exp_theta > 0:
                    st.markdown(f"- **Expected Carry** → `₹{int(exp_theta)}/day` (per lot)")
                
            # 🎨 WHY THIS TRADE? (Phase 30)
            st.divider()
            st.markdown("**WHY THIS TRADE:**")
            for r in master_setup.get("rationale", []):
                st.markdown(r)
                
            st.caption(f"SL Guide: Upper `{int(template.get('stop', {}).get('upper', 0))}` | Lower `{int(template.get('stop', {}).get('lower', 0))}`")

        else:
            if master_setup["code"] == "NO_TRADE":
                name = master_setup.get("name", "Execution Blocked")
                reason = master_setup.get("reason", "Market conviction below threshold.")
                if "Policy" in name:
                    st.error(f"🛡️ **{name}**: {reason}")
                else:
                    st.warning(f"📝 **{name}**: {reason}")
            else:
                st.write("❌ Trade template unavailable (Check Wall/ATR data)")

    with c2:
        # Dynamic Risk Banner (Phase 30)
        st.subheader("⚠ MARKET WARNING")
        risk_flags = 0
        
        if flow_metrics['total_vega'] > 300:
            st.error("Spot inside massive Vega cluster. Vol expansion risk elevated.")
            risk_flags += 1
            
        if flow_metrics['total_gex'] < 0:
            st.warning("Negative Gamma regime. Market liquidity is volatile and prone to whipsaws.")
            risk_flags += 1
            
        for w in master_setup.get("warnings", []):
            st.warning(w)
            risk_flags += 1
            
        if risk_flags == 0:
            st.success("No critical market hazard flags active.")
        
        # MARKET WARNING PANEL ONLY (Progress bars removed for cognitive simplicity)

    # 🔴 STRIKE RISK MAP (Phase 28/30 Visual Upgrade)
    st.write("---")
    st.subheader("🗺️ STRIKE RISK MAP")
    
    # Generate map for near-spot strikes
    map_strikes = range(int(spot - 250)//50*50, int(spot + 300)//50*50, 50)
    map_cols = st.columns(len(map_strikes))
    
    raw_exp = flow_metrics.get("raw_exposures", pd.DataFrame())
    dns_z = intel.get("dns_zones", [])
    
    if raw_exp.empty:
        st.info("Strike Risk Map unavailable (No Option Chain data).")
    else:
        risk_dict = {s: nde_options_logic.get_strike_risk_profile(s, raw_exp, dns_z) for s in map_strikes}
        
        for i, s in enumerate(map_strikes):
            with map_cols[i]:
                # Determine Icon
                risk_tier = risk_dict[s]
                icon = "🟢" if risk_tier == "LOW" else "🟡" if risk_tier == "MED" else "🔴"
                
                st.markdown(f"<div style='text-align: center; font-size: 1.5rem;'>{icon}</div>", unsafe_allow_html=True)
                
                # Tag Spot / Strike Targets
                if abs(s - spot) < 70:
                    st.markdown(f"<div style='text-align: center; font-size: 1rem;'>⚫ <br><b>{s}</b></div>", unsafe_allow_html=True)
                elif template and template.get("execution") and (s == template["execution"].get("sell_call") or s == template["execution"].get("sell_put")):
                    st.markdown(f"<div style='text-align: center; font-size: 1rem;'>🎯 <br><b>{s}</b></div>", unsafe_allow_html=True)
                elif s == call_wall or s == put_wall:
                    st.markdown(f"<div style='text-align: center; font-size: 1rem;'>🛡️ <br><b>{s}</b></div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='text-align: center; font-size: 0.8rem;'><br>{s}</div>", unsafe_allow_html=True)

    st.caption("Legend: 🟢 Safe (Low Vega) | 🟡 Moderate | 🔴 HIGH RISK | ⚫ Market Spot | 🎯 Optimal Strike | 🛡️ Max OI Wall")

    # 📊 SECTION 2.5: GREEK RISK PANEL & INTERPRETATION (Phase 28 Consolidated)
    from nde_options_logic import classify_greek_market_state
    greek_state = classify_greek_market_state(flow_metrics)

    st.divider()
    st.header("📉 GREEK INTERPRETATION LAYER")
    
    # Institutional Greek Rows (Phase 41 Unit Normalization: INR Crore/Cr)
    r1, r2, r3, r4, r5, r6 = st.columns(6)
    with r1:
        st.metric("Net Delta", ui["greeks"]["delta"], help="Aggregate Net Directional Delta (Institutional Crore)")
    with r2:
        st.metric("Absolute GEX", ui["greeks"]["gex_abs"], help="Absolute Dealer Pinning Gravity (Institutional Crore)")
    with r3:
        st.metric("Net GEX (Skew)", ui["greeks"]["gex_net"], help="Net Dealer Skew (Institutional Crore)")
    with r4:
        st.metric("Total Vega", ui["greeks"]["vega"], help="Absolute Volatility Sensitivity (Institutional Crore)")
    with r5:
        st.metric("Total Theta", ui["greeks"]["theta"], help="Absolute Time Decay Rate (Institutional Crore)")
    with r6:
        st.metric("T/V Carry", ui["tv_ratio"]["val"], delta=ui["tv_ratio"]["label"], 
                  delta_color="normal" if ui["tv_ratio"]["label"] in ["PREMIUM","NORMAL"] else "inverse", 
                  help="Theta/Vega Continuous Entry Gate")
        
    st.write(f"**Market State**: `{greek_state['state']}` | **Vol Bias**: `{greek_state['vol_bias']}` | **Decay Regime**: `{greek_state['decay_regime']}`")
    
    # 🔥 Hotspot Auditing (Phase 28 Restore)
    st.write("---")
    col_v, col_t = st.columns(2)
    with col_v:
        st.subheader("🔥 Vega Cluster Map (Vol Risk)")
        v_clusters = flow_metrics.get("vega_clusters", [])
        if v_clusters:
            st.dataframe(pd.DataFrame(v_clusters), hide_index=True, use_container_width=True)
        else:
            st.caption("No significant Vega clusters detected.")
            
    with col_t:
        st.subheader("⏳ Theta Decay Map (Income)")
        t_clusters = flow_metrics.get("theta_clusters", [])
        if t_clusters:
            st.dataframe(pd.DataFrame(t_clusters), hide_index=True, use_container_width=True)
        else:
            st.caption("No significant Theta hotspots detected.")
    
    # 📊 SECTION 3: INSTITUTIONAL OPTION CHAIN
    st.write("---")
    st.header("🕵️ Institutional Option Chain")
    # 🏛️ COLLAPSIBLE EXPLORER
    with st.expander("🏛️ Full Institutional Option Chain Explorer"):
        if not flow_metrics.get("raw_exposures", pd.DataFrame()).empty:
            render_institutional_option_chain(flow_metrics["raw_exposures"], spot, intel, (call_wall, put_wall))
        else:
            st.info("Institutional Option Chain unavailable.")

    # 🚀 SECTION 4: SYSTEM GAUGES & AUDIT
    st.divider()
    st.header("🚀 INTELLIGENCE METRICS")
    
    g1, g2 = st.columns(2)
    with g1:
        safe_stab = max(0.0, min(1.0, stability_20d / 100.0))
        st.progress(safe_stab, text=f"Regime Stability (20D): {stability_20d}%")
        st.caption(f"5D Stability: {stability_5d}%")

    with g2:
        drift_norm = min(1.0, abs(drift) / 0.5)
        st.progress(drift_norm, text=f"Drift Intensity: {abs(drift):.2f}")
        st.caption(f"Acceleration: {drift_accel:.4f}")


    with st.expander("📝 Daily Strategy Audit Trail"):
        audit_file = Path("notes/nde_strategy_log.jsonl")
        if audit_file.exists():
            rows = []
            with open(audit_file, "r") as f:
                for line in f:
                    rows.append(json.loads(line))
            st.dataframe(pd.DataFrame(rows).tail(10), use_container_width=True)
        else:
            st.write("No audit logs found yet.")

    # ⚖️ SECTION 5: STRATEGY HIERARCHY
    st.sidebar.header("⚖️ Strategy Confidence Hierarchy")
    
    def highlight_strat(name, code):
        return f"**{name}** 👈 *Active*" if strategy_code == code else name

    st.sidebar.markdown(f"""
    1. {highlight_strat('Gamma Flip', 'GAMMA_FLIP')} (Critical Pivot)
    2. {highlight_strat('Trend/Mean Rev', 'TREND_ACCELERATION')} (Regime Core)
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
                fragility=False,
                probs=c_probs,
                escalation=c_escalation,
                used_expiry=used_expiry, 
                gamma_regime=flow_metrics.get("gamma_regime", "UNKNOWN"), 
                flip=flow_metrics.get("gamma_flip_level", 0), 
                vanna=flow_metrics.get("vanna_bias", "UNKNOWN"), 
                charm=flow_metrics.get("charm_flow", "UNKNOWN"),
                flow_regime=flow_metrics.get("flow_regime_label", "UNKNOWN"), 
                total_gex=flow_metrics.get("total_gex", 0), 
                t_bias=intel.get("structural_bias", "NEUTRAL"),
                s_bias=intel.get("structural_bias", "NEUTRAL"), 
                spot=spot, 
                atr=atr, 
                config_hash=CONFIG_VERSION
            )
            st.sidebar.success(f"Snapshot saved to {saved_f.name}")
        except Exception as e:
            st.sidebar.error(f"Error saving snapshot: {e}")

    st.sidebar.markdown("---")
    st.sidebar.page_link("pages/18_NSE_Monthly_Engine.py", label="🏛️ NSE Monthly Engine", icon="📈")

except Exception as e:
    st.error(f"Critical Error in Strategy Engine: {e}")
    st.exception(e)
