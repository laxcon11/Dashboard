import streamlit as st
from nde_schema import UISnapshot, EngineContext

def safe(v):
    return str(v).replace("<", "&lt;").replace(">", "&gt;")

def safe_color(c):
    if not isinstance(c, str) or not c.startswith("#") or len(c) > 7:
        return "#8E8E93"
    return c


def render_hero_cockpit(ui: UISnapshot):
    """Renders the authoritative system state banner — the SOUL of the cockpit.
    Layout: STATE → ACTION → CONFIDENCE → WHY
    """
    st.markdown(f"""
    <div style="background: linear-gradient(180deg, rgba(30,30,30,0.95), rgba(20,20,20,0.98)); padding: 40px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 30px 60px rgba(0,0,0,0.5); margin-bottom: 30px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 25px; margin-bottom: 25px;">
            <div style="flex: 2;">
                <span style="font-size: 0.9em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 2px;">Structural Authority State</span>
                <div style="margin-top: 10px;"><span style="font-size: 2.8em; color: #FFFFFF; font-weight: 900; letter-spacing: -1.5px; text-transform: uppercase;">{safe(ui.hero_state)}</span></div>
            </div>
            <div style="flex: 1; text-align: right;">
                <span style="font-size: 0.9em; color: {ui.action_color}; text-transform: uppercase; font-weight: 900; letter-spacing: 2px;">Required Action</span>
                <div style="margin-top: 10px;"><span style="font-size: 3.5em; color: {ui.action_color}; font-weight: 950; letter-spacing: 2px; text-shadow: 0 0 30px {ui.action_color}44;">{safe(ui.hero_action)}</span></div>
            </div>
        </div>
        <div style="display: flex; gap: 40px;">
            <div style="flex: 1.5; border-right: 1px solid rgba(255,255,255,0.05); padding-right: 30px;">
                <span style="font-size: 0.8em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Why This Action?</span>
                <div style="margin-top: 15px;">{ui.reasons_html}</div>
            </div>
            <div style="flex: 0.8;">
                <span style="font-size: 0.8em; color: #8E8E93; text-transform: uppercase; font-weight: 800; letter-spacing: 1px;">Execution Confidence</span>
                <div style="margin-top: 15px; text-align: center;">
                    <div style="font-size: 2.2em; font-weight: 900; color: {ui.confidence_color};">{safe(ui.confidence_label)}</div>
                    <div style="margin-top: 15px; height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden;">
                        <div style="width: {min(ui.quality_score * 100, 100):.0f}%; height: 100%; background: {ui.confidence_color}; box-shadow: 0 0 15px {ui.confidence_color};"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_execution_summary(ui: UISnapshot):
    """Renders the compact tactical summary directly below the cockpit."""
    if ui.is_tradeable and ui.execution_summary:
        st.markdown(ui.execution_summary, unsafe_allow_html=True)


def render_market_logic(ui: UISnapshot):
    """Renders the behavior and Greek snapshots in a split column layout."""
    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.markdown("##### 🧩 Dealer Behavior Panel")
        st.markdown(ui.behavior_html, unsafe_allow_html=True)
    with c2:
        st.markdown("##### 🧠 Greek Snapshot")
        st.markdown(ui.greeks_html, unsafe_allow_html=True)


def render_trading_levels(ui: UISnapshot):
    """Renders the horizontal level ribbon with Max Pain."""
    st.markdown("### 🧭 KEY TRADING LEVELS")
    st.markdown(ui.levels_html, unsafe_allow_html=True)


def render_threat_invalidation(ui: UISnapshot, narrative=None):
    """Renders the structured thesis invalidation block."""
    st.markdown("### 🎯 Threat Invalidation")
    if ui.threat_html:
        st.markdown(ui.threat_html, unsafe_allow_html=True)
    elif narrative:
        st.error(f'**STOP THESIS**: {safe(narrative.invalidation)}')
        for a in (narrative.avoid or []):
            st.markdown(f"⚠️ **GUARDRAIL**: {safe(a)}")


def render_what_changed(ctx: EngineContext, hist_df, ui: UISnapshot):
    """Renders the 'What Changed' panel with delta comparisons.
    Displays: Flip Shift, ATM IV Change, Net GEX Change, PCR, Suppression, Max Pain
    """
    from datetime import datetime

    st.subheader("⏱️ WHAT CHANGED (Last vs Current)")

    if hist_df is not None and not hist_df.empty:
        # Find previous snapshot — NOT today, handles weekends/holidays gracefully
        today = datetime.now().strftime("%Y-%m-%d")
        prev = None
        # Iterate backward through sorted snapshots to find the most recent prior day
        for i in range(len(hist_df) - 1, -1, -1):
            row_date = str(hist_df.iloc[i].get("date", ""))[:10]
            if row_date != today:
                prev = hist_df.iloc[i]
                break

        curr_flip = ctx.flow.gamma_flip_level
        curr_iv = ctx.flow.atm_iv_current
        curr_gex = ctx.flow.total_gex
        
        # Current PCR and Max Pain from flow intelligence
        iq = ctx.flow.intelligence or {}
        curr_pcr = ctx.flow.pcr_oi if ctx.flow.pcr_oi > 0 else iq.get("pcr_oi", 0)
        curr_pain = iq.get("max_pain", 0)

        # Previous values (with safe defaults)
        prev_flip = prev.get("gamma_flip", curr_flip) if prev is not None else curr_flip
        prev_iv = prev.get("atm_iv", curr_iv) if prev is not None else curr_iv
        prev_gex = prev.get("total_gex", curr_gex) if prev is not None else curr_gex
        prev_pcr = prev.get("pcr_oi", curr_pcr) if prev is not None else curr_pcr
        prev_pain = prev.get("max_pain", curr_pain) if prev is not None else curr_pain

        f_delta = curr_flip - prev_flip
        iv_delta = curr_iv - prev_iv
        gex_delta = curr_gex - prev_gex
        pcr_delta = curr_pcr - prev_pcr if isinstance(prev_pcr, (int, float)) else 0
        pain_delta = curr_pain - prev_pain if isinstance(prev_pain, (int, float)) else 0

        # Row 1: Core deltas
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Flip Shift", f"{curr_flip:,.0f}", delta=f"{f_delta:+.0f}")
        with c2:
            st.metric("ATM IV Change", f"{curr_iv:.1f}%", delta=f"{iv_delta:+.1f}%")
        with c3:
            st.metric("Net GEX Δ", f"{curr_gex/1000:.1f}B", delta=f"{gex_delta/1000:+.1f}B")

        # Row 2: Context metrics with deltas
        c4, c5, c6 = st.columns(3)
        with c4:
            pcr_str = f"{curr_pcr:.2f}" if isinstance(curr_pcr, (int, float)) else str(curr_pcr)
            pcr_d_str = f"{pcr_delta:+.2f}" if pcr_delta != 0 else None
            st.metric("PCR (OI)", pcr_str, delta=pcr_d_str)
        with c5:
            pain_str = f"{int(curr_pain):,}" if curr_pain else "N/A"
            pain_d_str = f"{int(pain_delta):+,}" if pain_delta != 0 else None
            st.metric("Max Pain", pain_str, delta=pain_d_str)
        with c6:
            st.metric("Suppression", ui.suppression_display)
    else:
        # No historical data — show current values only
        iq = ctx.flow.intelligence or {}
        curr_pcr = ctx.flow.pcr_oi if ctx.flow.pcr_oi > 0 else iq.get("pcr_oi", 0)
        curr_pain = iq.get("max_pain", 0)
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Gamma Flip", f"{ctx.flow.gamma_flip_level:,.0f}")
        with c2:
            st.metric("ATM IV", f"{ctx.flow.atm_iv_current:.1f}%")
        with c3:
            st.metric("Net GEX", f"{ctx.flow.total_gex/1000:.1f}B")

        c4, c5, c6 = st.columns(3)
        with c4:
            st.metric("PCR (OI)", f"{curr_pcr:.2f}" if isinstance(curr_pcr, (int, float)) else "N/A")
        with c5:
            st.metric("Max Pain", f"{int(curr_pain):,}" if curr_pain else "N/A")
        with c6:
            st.metric("Suppression", ui.suppression_display)


def render_telemetry(ctx: EngineContext):
    """Renders system performance metrics."""
    t = ctx.telemetry
    st.sidebar.caption(f"Engine: {t.total_ms:.1f}ms | Flow: {t.flow_ms:.1f}ms | State: {t.state_ms:.1f}ms")
