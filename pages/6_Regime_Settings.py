import math
import streamlit as st

from regime_model import load_regime_settings, save_regime_settings, reset_regime_settings
from regime_state import load_regime_snapshot
from utils import setup_page, get_ui_detail_mode


setup_page("Regime Settings")
_ = get_ui_detail_mode("Summary")
st.title("⚙️ Regime Settings")
st.caption("Configure Macro + Liquidity scoring inputs, weights, and thresholds.")

settings = load_regime_settings()

st.subheader("Model Blend")
blend = settings["blend"]
group_caps = blend.setdefault("group_caps", {
    "Macro": 0.30,
    "Liquidity": 0.35,
    "Risk Appetite": 0.20,
    "Rates/Currency": 0.20,
    "Commodities": 0.20,
})

col1, col2 = st.columns(2)
with col1:
    blend["macro_weight"] = st.slider("Macro Weight", 0.0, 1.0, float(blend["macro_weight"]), 0.01)
    blend["liquidity_weight"] = st.slider("Liquidity Weight", 0.0, 1.0, float(blend["liquidity_weight"]), 0.01)
    blend["max_factor_weight"] = st.slider("Max Factor Weight Cap", 0.05, 0.50, float(blend["max_factor_weight"]), 0.01)
    blend["neutral_band"] = st.slider("Neutral Band", 0.05, 0.60, float(blend["neutral_band"]), 0.01)

with col2:
    blend["fast_weight"] = st.slider("Fast Signal Weight", 0.0, 1.0, float(blend["fast_weight"]), 0.01)
    blend["slow_weight"] = st.slider("Slow Signal Weight", 0.0, 1.0, float(blend["slow_weight"]), 0.01)
    blend["impulse_influence"] = st.slider("Impulse Influence on Final", 0.0, 0.6, float(blend.get("impulse_influence", 0.25)), 0.01)
    blend["fast_window"] = st.slider("Fast Window (periods)", 1, 5, int(blend["fast_window"]), 1)
    blend["slow_window"] = st.slider("Slow Window (periods)", 5, 30, int(blend["slow_window"]), 1)

st.subheader("Decision Thresholds")
col3, col4 = st.columns(2)
with col3:
    blend["risk_on_threshold"] = st.slider("Risk On Probability Threshold", 0.40, 0.90, float(blend["risk_on_threshold"]), 0.01)
with col4:
    blend["risk_off_threshold"] = st.slider("Risk Off Probability Threshold", 0.40, 0.90, float(blend["risk_off_threshold"]), 0.01)

st.subheader("SOFR/IORB Stress Penalty")
col5, col6 = st.columns(2)
with col5:
    blend["sofr_iorb_penalty_enabled"] = st.checkbox(
        "Enable SOFR/IORB penalty",
        value=bool(blend.get("sofr_iorb_penalty_enabled", True)),
    )
    blend["sofr_iorb_warn_bps"] = st.slider(
        "Penalty starts above (bps)",
        1.0,
        20.0,
        float(blend.get("sofr_iorb_warn_bps", 5.0)),
        0.5,
    )
    blend["sofr_iorb_full_penalty_bps"] = st.slider(
        "Full penalty at (bps)",
        5.0,
        50.0,
        float(blend.get("sofr_iorb_full_penalty_bps", 15.0)),
        0.5,
    )
with col6:
    blend["sofr_iorb_max_penalty"] = st.slider(
        "Max Liquidity Penalty",
        0.05,
        0.50,
        float(blend.get("sofr_iorb_max_penalty", 0.25)),
        0.01,
    )
    blend["sofr_iorb_persistence_days"] = st.slider(
        "Persistence Days (escalation)",
        1,
        10,
        int(blend.get("sofr_iorb_persistence_days", 3)),
        1,
    )
    blend["sofr_iorb_persisted_max_penalty"] = st.slider(
        "Persisted Max Penalty",
        0.05,
        0.60,
        float(blend.get("sofr_iorb_persisted_max_penalty", 0.35)),
        0.01,
    )

st.subheader("Group Caps")
gc1, gc2, gc3 = st.columns(3)
with gc1:
    group_caps["Macro"] = st.slider("Macro Cap", 0.05, 0.60, float(group_caps.get("Macro", 0.30)), 0.01)
    group_caps["Risk Appetite"] = st.slider("Risk Appetite Cap", 0.05, 0.60, float(group_caps.get("Risk Appetite", 0.20)), 0.01)
with gc2:
    group_caps["Liquidity"] = st.slider("Liquidity Cap", 0.05, 0.60, float(group_caps.get("Liquidity", 0.35)), 0.01)
    group_caps["Rates/Currency"] = st.slider("Rates/Currency Cap", 0.05, 0.60, float(group_caps.get("Rates/Currency", 0.20)), 0.01)
with gc3:
    group_caps["Commodities"] = st.slider("Commodities Cap", 0.05, 0.60, float(group_caps.get("Commodities", 0.20)), 0.01)


def render_factor_controls(domain_key: str, title: str):
    st.markdown(f"### {title}")
    factors = settings[domain_key]
    group_options = ["Macro", "Liquidity", "Risk Appetite", "Rates/Currency", "Commodities"]
    for factor_id, factor in factors.items():
        c1, c2, c3, c4, c5 = st.columns([2.4, 1, 1, 1.3, 1.6])
        with c1:
            st.write(factor.get("label", factor_id))
        with c2:
            factor["enabled"] = st.checkbox("On", value=bool(factor.get("enabled", True)), key=f"{domain_key}_{factor_id}_enabled")
        with c3:
            factor["inverse"] = st.checkbox("Inv", value=bool(factor.get("inverse", False)), key=f"{domain_key}_{factor_id}_inverse")
        with c4:
            factor["weight"] = st.number_input(
                "Weight",
                min_value=0.0,
                max_value=1.0,
                value=float(factor.get("weight", 0.1)),
                step=0.01,
                key=f"{domain_key}_{factor_id}_weight",
            )
        with c5:
            current_group = factor.get("group", "Liquidity" if domain_key == "liquidity_factors" else "Macro")
            factor["group"] = st.selectbox(
                "Group",
                options=group_options,
                index=group_options.index(current_group) if current_group in group_options else 0,
                key=f"{domain_key}_{factor_id}_group",
            )


render_factor_controls("macro_factors", "Macro Factors")
render_factor_controls("liquidity_factors", "Liquidity Factors")

st.subheader("Live Preview")
snapshot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
if isinstance(snapshot, dict) and snapshot:
    final_score = float(snapshot.get("final_score", 0.0) or 0.0)
    k = 3.0
    neutral_band = float(blend.get("neutral_band", 0.30))
    risk_on_threshold = float(blend.get("risk_on_threshold", 0.60))
    risk_off_threshold = float(blend.get("risk_off_threshold", 0.60))
    risk_on_raw = math.exp(k * (final_score - neutral_band))
    risk_off_raw = math.exp(k * (-final_score - neutral_band))
    neutral_raw = math.exp(k * (neutral_band - abs(final_score)))
    total = risk_on_raw + risk_off_raw + neutral_raw
    p_on = risk_on_raw / total if total > 0 else 0.0
    p_off = risk_off_raw / total if total > 0 else 0.0
    p_neu = neutral_raw / total if total > 0 else 1.0

    if p_on >= risk_on_threshold and p_on > p_off and p_on > p_neu:
        preview_regime = "🟢 Risk On"
    elif p_off >= risk_off_threshold and p_off > p_on and p_off > p_neu:
        preview_regime = "🔴 Risk Off"
    else:
        preview_regime = "🟡 Neutral"

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Preview Regime", preview_regime)
    p2.metric("Preview P(Risk On)", f"{p_on:.0%}")
    p3.metric("Preview P(Neutral)", f"{p_neu:.0%}")
    p4.metric("Preview P(Risk Off)", f"{p_off:.0%}")
    st.caption(
        f"Preview uses latest Macro SSOT score {final_score:+.3f} with current unsaved thresholds/band. "
        "Weight changes require save + Macro Risk recompute for full effect."
    )
else:
    st.info("No Macro SSOT snapshot found yet. Open Macro Risk page once, then return for live preview.")

st.markdown("---")
btn1, btn2, btn3 = st.columns(3)
with btn1:
    if st.button("💾 Save Settings", width='stretch'):
        save_regime_settings(settings)
        st.success("Settings saved.")
with btn2:
    if st.button("↩️ Reset to Defaults", width='stretch'):
        settings = reset_regime_settings()
        st.success("Reset to defaults. Refresh page to view default values.")
with btn3:
    if st.button("🔄 Reload Saved", width='stretch'):
        st.rerun()

st.caption("`On` = include factor, `Inv` = inverse logic (higher value treated bearish), `Group` = cap bucket for anti-bias constraints.")
st.caption("SOFR/IORB penalty is applied to Liquidity directional/impulse (bounded; escalates only after configured persistence).")
st.caption("Design note: SOFR/IORB currently contributes both as a continuous liquidity factor and as an explicit stress penalty layer (intentional dual-path).")
