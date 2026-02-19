import streamlit as st

from regime_model import load_regime_settings, save_regime_settings, reset_regime_settings
from utils import setup_page


setup_page("Dashboard Launcher")
st.title("⚙️ Regime Settings")
st.caption("Configure Macro + Liquidity scoring inputs, weights, and thresholds.")

settings = load_regime_settings()

st.subheader("Model Blend")
blend = settings["blend"]

col1, col2 = st.columns(2)
with col1:
    blend["macro_weight"] = st.slider("Macro Weight", 0.0, 1.0, float(blend["macro_weight"]), 0.01)
    blend["liquidity_weight"] = st.slider("Liquidity Weight", 0.0, 1.0, float(blend["liquidity_weight"]), 0.01)
    blend["max_factor_weight"] = st.slider("Max Factor Weight Cap", 0.05, 0.50, float(blend["max_factor_weight"]), 0.01)
    blend["neutral_band"] = st.slider("Neutral Band", 0.05, 0.60, float(blend["neutral_band"]), 0.01)

with col2:
    blend["fast_weight"] = st.slider("Fast Signal Weight", 0.0, 1.0, float(blend["fast_weight"]), 0.01)
    blend["slow_weight"] = st.slider("Slow Signal Weight", 0.0, 1.0, float(blend["slow_weight"]), 0.01)
    blend["fast_window"] = st.slider("Fast Window (periods)", 1, 5, int(blend["fast_window"]), 1)
    blend["slow_window"] = st.slider("Slow Window (periods)", 5, 30, int(blend["slow_window"]), 1)

st.subheader("Decision Thresholds")
col3, col4 = st.columns(2)
with col3:
    blend["risk_on_threshold"] = st.slider("Risk On Probability Threshold", 0.40, 0.90, float(blend["risk_on_threshold"]), 0.01)
with col4:
    blend["risk_off_threshold"] = st.slider("Risk Off Probability Threshold", 0.40, 0.90, float(blend["risk_off_threshold"]), 0.01)


def render_factor_controls(domain_key: str, title: str):
    st.markdown(f"### {title}")
    factors = settings[domain_key]
    for factor_id, factor in factors.items():
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1.4])
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


render_factor_controls("macro_factors", "Macro Factors")
render_factor_controls("liquidity_factors", "Liquidity Factors")

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

st.caption("`On` = include factor, `Inv` = invert direction (higher value becomes bearish).")
