import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from pathlib import Path
import json

# Internal Logic Imports
import nde_options_logic
import nde_strategy_logic
import nde_expiry_helper
from nde_automation_logic import compute_expiry_phase
from data_fetch import batch_download
from utils import setup_page, get_ui_device_mode

# ==================== UI CONFIG ====================
setup_page("Nifty Arbitrage Scanner")

st.title("⚖️ Nifty Arbitrage Scanner")
st.caption("Institutional Derivatives Desk — Phase 5.8")

# ==================== CONTRACT SELECTOR ====================

def get_available_contracts():
    pattern = "option-chain-ED-*-NIFTY-*.csv"
    files = list(nde_options_logic.OPTION_CHAIN_DIR.glob(pattern))
    by_expiry = {}
    for f in files:
        parts = f.name.split("-")
        expiry_str = parts[-1].replace(".csv", "")
        source_tag = parts[3] if len(parts) > 3 else "UNKNOWN"
        priority = 0 if source_tag == "v3" else (1 if source_tag == "sensi" else 2)
        if expiry_str not in by_expiry or priority < by_expiry[expiry_str]["priority"]:
            by_expiry[expiry_str] = {
                "label": f"{expiry_str} ({nde_expiry_helper.get_expiry_type(expiry_str)})",
                "expiry": expiry_str,
                "filename": f.name,
                "priority": priority
            }
    contracts = list(by_expiry.values())
    try:
        contracts.sort(key=lambda x: datetime.strptime(x["expiry"], "%d-%b-%Y"))
    except Exception: pass
    return contracts

available_contracts = get_available_contracts()
if not available_contracts:
    st.error("No Option Chain shards found. Please run a fresh fetch.")
    st.stop()

st.sidebar.subheader("🎯 Contract Selection")
selected_contract = st.sidebar.selectbox("Target Expiry", options=available_contracts, format_func=lambda x: x["label"], index=0)

# ==================== DATA HYDRATION ====================

@st.cache_data(ttl=300)
def fetch_arbitrage_context(contract_filename: str):
    market_data = batch_download(["^NSEI", "^INDIAVIX"], period="3mo")
    nifty_df = market_data.get("^NSEI")
    yf_spot = nifty_df["Close"].iloc[-1]
    
    raw_chain, used_expiry, source, meta, fname = nde_options_logic.load_index_v3_data(contract_filename)
    
    # Spot: yfinance ^NSEI is primary (real-time close),
    # sensibull meta as fallback only
    spot = yf_spot
    if not spot or spot <= 0:
        spot = meta.get("spot_at_fetch", 24000.0)
    
    # Futures Price: Use stored synthetic forward if available,
    # otherwise compute it at runtime from ATM options
    futures_price = meta.get("underlyingValue", 0.0)
    if not futures_price or abs(futures_price - spot) < 1.0:
        # Meta doesn't have a distinct futures price — compute Synthetic Forward
        futures_price = nde_options_logic.calculate_synthetic_forward(raw_chain, spot)
    
    dte = nde_expiry_helper.get_dte_from_string(used_expiry)
    term_data = nde_options_logic.compute_term_structure("NIFTY")
    
    atr = nde_options_logic.calculate_atr_sma(nifty_df)
    flow_metrics = nde_options_logic.compute_option_flow_exposures(spot, raw_chain, atr=atr)
    
    return {
        "spot": spot,
        "futures_price": futures_price,
        "raw_chain": raw_chain,
        "used_expiry": used_expiry,
        "dte": dte,
        "term_data": term_data,
        "source": source,
        "timestamp": meta.get("timestamp", "N/A"),
        "flow_metrics": flow_metrics
    }

ctx = fetch_arbitrage_context(selected_contract["filename"])
spot, futures_price, raw_chain = ctx["spot"], ctx["futures_price"], ctx["raw_chain"]
dte, term_data, flow_metrics = ctx["dte"], ctx["term_data"], ctx["flow_metrics"]

phase = compute_expiry_phase(dte)
basis_data = nde_options_logic.compute_basis_metrics(spot, futures_price, dte, r=0.07)
pcp_df = nde_options_logic.compute_pcp_violations(raw_chain, futures_price, r=0.07, t_days=dte)
cal_data = nde_options_logic.compute_calendar_spread_opportunity(term_data)
box_df = nde_options_logic.compute_box_spreads(raw_chain, r=0.07, t_days=dte)
roll_data = nde_options_logic.compute_roll_arbitrage(term_data, spot, r=0.07)

# ==================== MASTER DECISION PANEL ====================

st.write("---")

# Determine primary edge across all strategies
edges = []
if basis_data.get("score", 0) >= 4:
    edges.append(f"Basis: {basis_data['signal']} ({basis_data['strength']})")
if not pcp_df.empty and (pcp_df["arb_action"] != "FAIR").any():
    edges.append("Synthetic Arb: ACTIVE")
if not box_df.empty and (box_df["action"] != "FAIR").any():
    edges.append("Box Spread: ACTIVE")
if roll_data.get("signal", "NEUTRAL") != "NEUTRAL" and roll_data.get("signal") != "INSUFFICIENT_DATA":
    edges.append(f"Roll: {roll_data['signal']}")

m1, m2, m3 = st.columns(3)
with m1:
    if edges:
        st.metric("Active Edges", f"{len(edges)} Found")
        for e in edges:
            st.caption(f"✔ {e}")
    else:
        st.metric("Active Edges", "NONE")

with m2:
    # Primary action: strongest edge
    if basis_data.get("score", 0) >= 7:
        st.metric("Primary Action", f"EXECUTE {basis_data['signal']}")
    elif edges:
        st.metric("Primary Action", "REVIEW TABS")
    else:
        st.metric("Primary Action", "STAND ASIDE")

with m3:
    # Confidence: Based on data freshness, edge size, and DTE — NOT GEX
    # GEX/gamma flip has no analytical relationship to futures mispricing
    _edge_score = basis_data.get("score", 0)
    _source_fresh = ctx["source"].startswith("SENSIBULL") or ctx["source"] == "LIVEv3"
    _dte_convergent = dte <= 14  # Closer to expiry = faster arb convergence
    
    _conf_count = sum([_edge_score >= 4, _source_fresh, _dte_convergent])
    if _conf_count >= 3:
        conf = "HIGH"
    elif _conf_count >= 2 or _edge_score >= 6:
        conf = "MEDIUM"
    else:
        conf = "LOW"
    st.metric("Confidence", conf)

# Context overlay
gamma_regime = flow_metrics.get("gamma_regime", "Unknown")
dist_flip = flow_metrics.get("dist_to_flip_atr", 0)
st.info(f"🧬 **{gamma_regime}** | Flip Distance: {dist_flip:.2f} ATR | Phase: {phase} | DTE: {dte}")

if phase in ("PRE_EXPIRY", "EXPIRY_RISK"):
    st.warning(f"⚠️ **{phase}**: PCF/Box deviations may be untradeable due to settlement averaging.")

# ==================== TABBED STRATEGIES ====================

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Basis & Synthetic", "📦 Box Spreads", "🔄 Roll Arbitrage", "📅 Calendar IV", "⏱️ EFP Monitor"
])

# ==================== TAB 1: BASIS & SYNTHETIC ====================
with tab1:
    st.subheader(f"Basis Cockpit: {selected_contract['label']}")
    st.caption(f"Fair Value for **{selected_contract['expiry']}** ({dte} DTE) | Synthetic Forward as futures proxy")
    
    b1, b2, b3 = st.columns([1.5, 1, 1.5])
    with b1:
        st.markdown(f"**Spot (^NSEI)**: `{spot:,.2f}`  \n**Synthetic Fwd**: `{futures_price:,.2f}`  \n**Fair Value**: `{basis_data['fair_futures']:,.2f}`")
    with b2:
        color = "#FF3B30" if basis_data["signal"] == "RICH" else "#00C805" if basis_data["signal"] == "CHEAP" else "#8E8E93"
        st.markdown(f"<div style='background:{color};padding:15px;border-radius:10px;text-align:center;color:white;font-weight:bold;'>{basis_data['signal']}<br><small>{basis_data.get('strength','')}</small></div>", unsafe_allow_html=True)
    with b3:
        st.metric("Basis Score", f"{basis_data.get('score', 0)}/10", delta=f"{basis_data['annualised_basis_pct']:.2f}% Carry")
    
    # Implied Borrowing
    implied_rate = nde_options_logic.compute_implied_borrowing_rate(spot, futures_price, dte)
    r1, r2 = st.columns(2)
    with r1:
        st.metric("Implied Borrowing Rate", f"{implied_rate:.2f}%", delta=f"{implied_rate - 6.5:.2f}% vs Repo", delta_color="inverse")
        if implied_rate > 7.5:
            st.success("💰 **Attractive Lending**: Rate exceeds Repo + 1%. Cash-and-carry is favorable.")
        elif implied_rate < 6.5:
            st.warning("⚠️ **Below Repo**: Avoid carry trades. Market is pricing negative carry.")
    with r2:
        friction = nde_options_logic.get_arbitrage_transaction_costs(spot)
        st.markdown(f"**Friction**: `₹{friction:,}` per lot  \n**Repo**: `6.50%` | **91D T-Bill**: `6.90%`")
    
    st.divider()
    
    # Strategy Playbook
    if basis_data["signal"] == "CHEAP":
        st.success("🎯 **REVERSE CASH-AND-CARRY**")
        st.markdown(f"- **BUY** Nifty Futures @ `{futures_price:,.2f}`  \n- **SELL** Nifty ETF @ `{spot:,.2f}`  \n- **Edge**: `+{abs(basis_data['basis_error_pts']):.2f}` pts | **Size**: 1-2 Lots per 10L")
    elif basis_data["signal"] == "RICH":
        st.success("🎯 **CASH-AND-CARRY**")
        st.markdown(f"- **BUY** Nifty ETF @ `{spot:,.2f}`  \n- **SELL** Nifty Futures @ `{futures_price:,.2f}`  \n- **Locked**: `{basis_data['annualised_basis_pct']:.2f}%` annualized")
    else:
        st.info("⚖️ Basis in equilibrium. No structural edge.")
    
    st.divider()
    
    # Synthetic Futures Arb (PCP with arb_action)
    st.subheader("🧬 Synthetic Futures Arbitrage")
    st.caption("Each strike creates a synthetic future via Put-Call Parity. Trade the synthetic against the actual future when mispriced.")
    
    if not pcp_df.empty:
        arb_df = pcp_df[pcp_df["arb_action"] != "FAIR"].head(8)
        if not arb_df.empty:
            display_cols = ["strike", "synthetic", "net_edge", "arb_action", "confidence_label"]
            st.dataframe(
                arb_df[display_cols].rename(columns={
                    "strike": "Strike", "synthetic": "Synthetic Fwd", "net_edge": "Net Edge (Pts)",
                    "arb_action": "Action", "confidence_label": "Confidence"
                }),
                use_container_width=True, hide_index=True
            )
            
            # Explain the best opportunity
            best = arb_df.iloc[0]
            with st.expander("📋 How to Execute the Top Signal"):
                if "BUY SYNTHETIC" in best["arb_action"]:
                    st.markdown(f"""
                    **At Strike {int(best['strike'])}**:
                    1. **BUY** {int(best['strike'])} Call
                    2. **SELL** {int(best['strike'])} Put
                    3. **SELL** Nifty Futures
                    
                    **Net Edge**: `{best['net_edge']:.2f}` pts after friction.  
                    All 3 legs execute on NSE. No ETF/stock basket needed.
                    """)
                else:
                    st.markdown(f"""
                    **At Strike {int(best['strike'])}**:
                    1. **SELL** {int(best['strike'])} Call
                    2. **BUY** {int(best['strike'])} Put
                    3. **BUY** Nifty Futures
                    
                    **Net Edge**: `{best['net_edge']:.2f}` pts after friction.
                    """)
        else:
            st.info("No synthetic arb opportunities exceed friction threshold.")
    else:
        st.info("No PCP data available.")

# ==================== TAB 2: BOX SPREADS ====================
with tab2:
    st.subheader("📦 Box Spread Scanner")
    st.caption("A box spread always settles at K2 - K1 at expiry. If you can buy it for less than fair value, you lock in riskless profit.")
    
    if not box_df.empty:
        tradeable_boxes = box_df[box_df["action"] != "FAIR"]
        
        if not tradeable_boxes.empty:
            st.dataframe(
                tradeable_boxes[["K1", "K2", "box_cost", "fair_box", "friction", "net_edge", "action", "min_leg_oi"]].rename(columns={
                    "K1": "Lower Strike", "K2": "Upper Strike", "box_cost": "Box Cost",
                    "fair_box": "Fair Value", "friction": "Friction", "net_edge": "Net Edge",
                    "action": "Action", "min_leg_oi": "Min OI"
                }),
                column_config={
                    "Net Edge": st.column_config.NumberColumn(format="%.2f"),
                    "Box Cost": st.column_config.NumberColumn(format="%.2f"),
                    "Fair Value": st.column_config.NumberColumn(format="%.2f"),
                },
                use_container_width=True, hide_index=True
            )
            
            best_box = tradeable_boxes.iloc[0]
            with st.expander("📋 Box Spread Execution"):
                st.markdown(f"""
                **{best_box['action']} at {int(best_box['K1'])}/{int(best_box['K2'])}**:
                1. **BUY** {int(best_box['K1'])} Call + **SELL** {int(best_box['K2'])} Call *(Bull Call Spread)*
                2. **BUY** {int(best_box['K2'])} Put + **SELL** {int(best_box['K1'])} Put *(Bear Put Spread)*
                
                **Guaranteed Payoff**: `{int(best_box['K2']) - int(best_box['K1'])}` pts at expiry  
                **Cost**: `{best_box['box_cost']:.2f}` pts | **Fair**: `{best_box['fair_box']:.2f}` pts  
                **Net Edge**: `{best_box['net_edge']:.2f}` pts after 4-leg friction
                
                ⚠️ **Hold to expiry** — early exit requires unwinding all 4 legs simultaneously.
                """)
        else:
            st.info("No box spread opportunities exceed the 2-point net edge threshold.")
    else:
        st.info("Insufficient data for box spread analysis.")

# ==================== TAB 3: ROLL ARBITRAGE ====================
with tab3:
    st.subheader("🔄 Roll Arbitrage (Inter-Expiry)")
    st.caption("Compares the synthetic futures price between near and far expiries against expected carry cost.")
    
    if roll_data.get("signal") != "INSUFFICIENT_DATA":
        r1, r2 = st.columns(2)
        with r1:
            st.markdown(f"""
            **Near ({roll_data.get('near_exp', 'N/A')})**: `{roll_data.get('near_synth', 0):,.2f}`  
            **Far ({roll_data.get('far_exp', 'N/A')})**: `{roll_data.get('far_synth', 0):,.2f}`
            """)
        with r2:
            st.markdown(f"""
            **Expected Spread**: `{roll_data.get('expected_spread', 0):,.2f}` pts  
            **Actual Spread**: `{roll_data.get('actual_spread', 0):,.2f}` pts  
            **Roll Edge**: `{roll_data.get('roll_edge', 0):+.2f}` pts
            """)
        
        sig_roll = roll_data.get("signal", "NEUTRAL")
        if sig_roll != "NEUTRAL":
            st.success(f"🎯 **{roll_data['action']}**")
            st.caption("Execute by trading the ATM synthetic (Buy Call + Sell Put) on each expiry.")
        else:
            st.info("⚖️ Roll spread is within expected carry range. No inter-expiry mispricing.")
        
        # Visual: Near vs Far synthetic
        fig = go.Figure()
        fig.add_trace(go.Bar(x=["Near Synthetic", "Far Synthetic", "Expected Spread", "Actual Spread"],
                             y=[roll_data.get("near_synth", 0), roll_data.get("far_synth", 0),
                                roll_data.get("expected_spread", 0), roll_data.get("actual_spread", 0)],
                             marker_color=["#007AFF", "#5856D6", "#8E8E93", "#FF9500"]))
        fig.update_layout(height=280, template="plotly_dark", margin=dict(l=0,r=0,t=20,b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Need at least 2 active expiry shards for Roll Arbitrage analysis.")

# ==================== TAB 4: CALENDAR IV ====================
with tab4:
    st.subheader("📅 Calendar IV Spread")
    st.caption("Detects when near-expiry IV is unusually cheap or expensive relative to far-expiry IV.")
    
    c1, c2 = st.columns([2, 1])
    with c1:
        exp_list = list(term_data.keys())
        iv_list = [d.get("atm_iv", 0) for d in term_data.values()]
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=exp_list, y=iv_list, mode='lines+markers', name="ATM IV",
                                 line=dict(color='#007AFF', width=3), marker=dict(size=10, symbol='diamond')))
        
        # Normal spread band (±1% around far IV)
        far_iv_val = cal_data.get("far_iv", 15.0)
        fig.add_hrect(y0=far_iv_val - 1.0, y1=far_iv_val + 1.0,
                      fillcolor="rgba(255,165,0,0.1)", line_width=0,
                      annotation_text="Normal Band (±1%)", annotation_position="top left")
        
        # Highlight selected contract
        if selected_contract["expiry"] in exp_list:
            idx = exp_list.index(selected_contract["expiry"])
            fig.add_trace(go.Scatter(x=[exp_list[idx]], y=[iv_list[idx]], mode='markers',
                                     marker=dict(size=15, color='#FF9500', symbol='star'), name="Active"))
        
        fig.update_layout(height=300, margin=dict(l=0,r=0,t=20,b=0), template="plotly_dark",
                          yaxis_title="ATM IV (%)", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    
    with c2:
        st.markdown(f"**Near IV**: `{cal_data.get('near_iv', 0):.2f}%`  \n**Far IV**: `{cal_data.get('far_iv', 0):.2f}%`")
        st.markdown(f"**Spread**: `{cal_data.get('current_spread', 0):.2f}%`  \n**Deviation**: `{cal_data.get('deviation', 0):+.2f}%`")
        st.divider()
        action_cal = cal_data.get("action", "STAND_ASIDE")
        if action_cal != "STAND_ASIDE":
            st.success(f"**{action_cal}**")
        else:
            st.info("**STAND ASIDE**")

# ==================== TAB 5: EFP MONITOR ====================
with tab5:
    st.subheader("⏱️ EFP Monitor (Expiry Day Settlement)")
    
    if phase in ("PRE_EXPIRY", "EXPIRY_RISK"):
        st.warning("🔴 **EXPIRY SESSION ACTIVE**")
        st.markdown("""
        **Exchange Delivery Settlement Price (EDSP)**: Nifty futures settle at the arithmetic mean of the 
        last 30 minutes of spot values (2:30 PM – 3:00 PM IST).
        
        **The Opportunity**: If futures trade *below* the running 30-minute spot average with 15 minutes 
        remaining, they are cheap relative to expected settlement → **BUY FUTURES, hold to settlement**.
        
        **Inverse**: If futures trade *above* the running average → **SELL FUTURES, hold to settlement**.
        """)
        
        st.info("⚠️ **Intraday Data Required**: This strategy requires real-time spot data feed (not currently connected). "
                "Monitor the basis manually during 2:30-3:00 PM on expiry day.")
        
        st.metric("Current Basis", f"{basis_data['basis']:+.2f} pts", 
                  delta=f"{'Cheap' if basis_data['basis'] < 0 else 'Rich'} vs Settlement")
    else:
        st.info(f"EFP Monitor activates on expiry day. Current phase: **{phase}** ({dte} DTE remaining).")
        st.caption("This tab will become active when `compute_expiry_phase(dte)` returns `EXPIRY_RISK` or `PRE_EXPIRY`.")

# ==================== RISK DISCLOSURE ====================
st.divider()
with st.expander("⚠️ Trade Risk Disclosure"):
    st.warning("""
    **Execution Risks**:
    - **Slippage**: Actual fills may vary 2-5 points from LTP, especially in illiquid OTM strikes.
    - **4-Leg Friction**: Box spreads incur ~12bps per trade. Only execute when net edge exceeds this.
    - **Early Unwind**: Carry trades are sensitive to sudden repo rate changes. Box spreads require hold-to-expiry.
    
    **Structural Risks**:
    - **Expiry Distortion**: Avoid execution during final 30 minutes of monthly expiry (EDSP settlement averaging).
    - **Dividend Impact**: Near ex-dividend dates for HDFC Bank, Reliance, or TCS, basis may widen by 0.1-0.3% temporarily. 
      This is **not a true arb** — it reverses at settlement. The current engine uses a static dividend yield.
    - **Margin**: Synthetic futures and box spreads require margin. Size positions within available margin limits.
    """)

st.caption(f"Sync: {ctx['timestamp']} | DTE: {dte} | Source: {ctx['source']} | Phase: {phase}")
