import math
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    FRED_API_KEY,
    GIFT_NIFTY_MACRO_BADGE,
    GIFT_NIFTY_STRESS_FLAG_PCT,
    GIFT_NIFTY_SESSION_START_IST_HOUR,
    GIFT_NIFTY_COLLAPSE_IST_HOUR,
)
from data_fetch import (
    batch_download, 
    fetch_fred_series, 
    fetch_india_vix, 
    prepare_timeseries_for_chart,
    load_local_nse_history
)
from gift_nifty import get_gift_nifty_snapshot, is_gift_session_active
from india_context import get_india_macro_signals_v1
from regime_model import load_regime_settings
from regime_state import save_regime_snapshot, append_regime_history, load_regime_history
import regime_scoring as scoring
import regime_classification as classification
from NSE_Config import NIFTY_200
from utils import (
    setup_page,
    render_key_observations,
    get_ui_detail_mode,
    get_ui_device_mode,
    render_source_freshness,
    render_regime_timeline_strip,
    render_decision_header,
    render_manual_data_staleness_alerts,
)
from analytics import round_percentages_sum_to_100


setup_page("Macro Risk")
view_mode = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"
st.title("🏛️ Institutional Regime Engine")
st.caption("Professional 4-Phase Regime Model: Global Filter -> Domestic Growth -> Liquidity -> Market Stress.")
st.caption(f"Device mode: **{device_mode}**")
_page_t0 = time.perf_counter()
_perf: dict[str, float] = {}

from institutional_engine import generate_institutional_regime

with st.spinner("Executing 4-Pillar Regime Engine..."):
    main_regime_result = generate_institutional_regime(offset=0)

# Unpack for UI
final_score = main_regime_result["final_score"]
regime_label = main_regime_result["regime"]
pillar_scores = main_regime_result["pillar_scores"]
all_rows = main_regime_result["rows"]

# Unpack shared dependencies for downstream UI components
blend = main_regime_result["blend"]
market_data = main_regime_result["market_data"]
india_signals = main_regime_result["india_ctx"]
vix_price = main_regime_result.get("vix_price", 0.0)
breadth_series = main_regime_result.get("breadth_series", pd.Series(dtype=float))


def _responsive_cols(n: int, spec=None):
    if is_mobile:
        return [st.container() for _ in range(n)]
    return st.columns(spec if spec is not None else n)

# Deterministic regime color and bias
if "Risk On" in regime_label:
    regime_color = "success"
    bias = "Aggressive Long / Risk Seeking"
elif "Selective" in regime_label or "Neutral" in regime_label:
    regime_color = "warning"
    bias = "Selective Longs / Reduced Position Size"
elif "Crisis" in regime_label:
    regime_color = "error"
    bias = "Cash / Hedges Only"
else:
    # Defensive/Risk Off
    regime_color = "error"
    bias = "Defensive / Tactical Shorts"

# Confidence derived from state-aware hysteresis rules (v4)
probs = main_regime_result.get("probabilities", {"selective": 1.0})
confidence = float(main_regime_result.get("confidence", 0.50))

render_decision_header(
    regime_label=regime_label,
    final_score=final_score,
    confidence=confidence,
    bias=bias,
    source="institutional_v1",
)

if main_regime_result.get("is_pending"):
    st.warning("⚠️ **Regime Change Pending**: Market signal shifted, awaiting 3-day persistence confirmation.")

with st.expander("📊 Detailed Pillar Performance", expanded=True):
    p1, p2, p3, p4 = _responsive_cols(4)
    with p1:
        # Metrics now show the raw Pillar score (from -1.0 to +1.0)
        st.metric("Global Pillar", f"{pillar_scores['Global']:+.2f}")
        st.caption(f"Weight: {blend.get('global_weight', 0.40):.0%}")
    with p2:
        st.metric("Growth Pillar", f"{pillar_scores['Growth']:+.2f}")
        st.caption(f"Weight: {blend.get('macro_weight', 0.20):.0%}")
    with p3:
        st.metric("Liquidity Pillar", f"{pillar_scores['Liquidity']:+.2f}")
        st.caption(f"Weight: {blend.get('liquidity_weight', 0.25):.0%}")
    with p4:
        st.metric("Risk Pillar", f"{pillar_scores['Risk']:+.2f}")
        st.caption(f"Weight: {blend.get('risk_weight', 0.15):.0%}")

    st.write("---")
    # Show factor breakdown table
    df_factors = pd.DataFrame(all_rows)
    if not df_factors.empty:
        st.dataframe(
            df_factors[["Pillar", "Factor", "Value", "Score", "Sentiment", "Weight"]],
            hide_index=True,
            use_container_width=True
        )

if regime_color == "success":
    st.success(f"### Current Regime: {regime_label}")
elif regime_color == "error":
    st.error(f"### Current Regime: {regime_label}")
else:
        st.warning(f"### Current Regime: {regime_label}")

st.info(f"Strategic Actionable Bias: **{bias}**")

# Key Observations
# Signal Stability & Confidence Diagnostics
if float(confidence) < 0.3:
    st.error("⚠️ **Low Signal Confidence Detected**")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(
            "The current regime classification is considered **low confidence** ( < 30% ) because the model score is extremely near a boundary. "
            "Small shifts in underlying factors or momentum filters could trigger a whipsaw transition."
        )
        # Logic to explain the boundary proximity
        if abs(float(final_score)) < 0.15:
            st.info(f"**Boundary Analysis**: Score ({float(final_score):+.3f}) is within ±0.15 of the Neutral/Selective boundary (0.00).")
        elif 0.35 <= abs(float(final_score)) <= 0.55:
            st.info(f"**Boundary Analysis**: Score ({float(final_score):+.3f}) is near the Defensive/Risk-On boundary (±0.45).")
    with c2:
        st.metric("Boundary Buffer", f"{abs(float(final_score)):.3f}", help="Distance from center line. Lower values increase flip risk.")

observations = [
    f"Market Regime is {regime_label} with a final institutional score of {final_score:+.2f}.",
    f"Global environment is {'supportive' if pillar_scores['Global'] > 0 else 'restrictive'} ({pillar_scores['Global']:+.2f}).",
    f"India Growth (Macro) is {'expanding' if pillar_scores['Growth'] > 0 else 'contracting'} ({pillar_scores['Growth']:+.2f}).",
    f"Liquidity state is {'expanding' if pillar_scores['Liquidity'] > 0 else 'tightening'} ({pillar_scores['Liquidity']:+.2f}).",
    f"Market Risk/Stress is {'low' if pillar_scores['Risk'] > 0 else 'high'} ({pillar_scores['Risk']:+.2f})."
]

# Breadth check for observations
b_row = next((r for r in all_rows if r["Factor"] == "Market Breadth (Nifty 200)"), None)
breadth_value = float(b_row["Value"]) / 100.0 if b_row else 0.5

if "Crisis" in regime_label:
    observations.append(f"⚠️ CRISIS OVERRIDE ACTIVE: {main_regime_result.get('crisis_reason', 'Market Stress')}")

if breadth_value < 0.30:
    observations.append(f"🔴 CRITICAL BREADTH: Only {breadth_value:.1%} of Nifty 200 stocks above 200DMA.")
elif breadth_value < 0.50:
    observations.append(f"🟠 CAUTION: Market breadth is deteriorating ({breadth_value:.1%}).")

render_key_observations(observations, max_items=8)

# Note: Domestic markers are now part of the Risk/Growth pillars. 
# We can add a high-level summary of India Macro here if needed, 
# but for now we'll focus on the institutional 4-pillar scores.

# Publish canonical regime payload for cross-page consistency.
regime_payload = {
    "regime_label": regime_label,
    "current_regime": regime_label,
    "confidence": round(float(confidence), 4),
    "final_score": round(float(final_score), 4),
    "pillar_scores": pillar_scores,
    "probabilities": probs,
    "bias": bias,
    "source": "institutional_v1",
}
save_regime_snapshot(regime_payload)
st.session_state["macro_regime_snapshot"] = regime_payload

# Persist today's regime to JSONL history for the timeline
append_regime_history(regime_payload)

# 90-day pulse-tape timeline from real persisted history
history = load_regime_history(days=90)
timeline_rows = [
    {
        "ts": row["date"], 
        "regime": row["regime"], 
        "score": row["score"], 
        "confidence": row["confidence"],
        "confidence_val": row.get("confidence_val") # Pass numeric value if available
    }
    for row in history
]
render_regime_timeline_strip(timeline_rows, key="institutional_regime_timeline_90d")

if view_mode == "Detail":
    with st.expander("🧮 Pillar Scoring Formulas", expanded=True):
        st.markdown("### Weighted Blending Formula")
        w_g = blend.get("global_weight", 0.40)
        w_gr = blend.get("macro_weight", 0.20)
        w_l = blend.get("liquidity_weight", 0.25)
        w_r = blend.get("risk_weight", 0.15)
        st.latex(rf"Score_{{Final}} = G_{{raw}} \cdot {w_g:.2f} + GR_{{raw}} \cdot {w_gr:.2f} + L_{{raw}} \cdot {w_l:.2f} + R_{{raw}} \cdot {w_r:.2f}")
        st.caption("G: Global, GR: India Growth, L: Liquidity, R: Market Risk (Raw scores from -1 to +1)")
        
        st.markdown("---")
        for p, s in pillar_scores.items():
            st.write(f"**{p} Pillar Score:** {s:+.3f}")

    with st.expander("📈 Advanced Diagnostics", expanded=True):
        st.markdown("### Factor Contribution Analysis")
        df_factors = pd.DataFrame(all_rows)
        if not df_factors.empty:
            df_factors["Abs_Score"] = df_factors["Score"].abs()
            top_drivers = df_factors.sort_values("Abs_Score", ascending=False).head(10)
            st.table(top_drivers[["Pillar", "Factor", "Score", "Sentiment"]])
        
        # Freshness markers
        render_source_freshness(
            {
                "^TNX": "US 10Y Yield",
                "DX-Y.NYB": "Dollar Index",
                "BTC-USD": "Bitcoin",
                "^NSEI": "NIFTY 50",
            },
            market_data,
            title="Core Input Data Freshness",
        )

st.markdown("---")
st.caption("Institutional Regime Engine v1.0 | Configuration driven by `Regime Settings` page.")
_perf["total_page_s"] = round(time.perf_counter() - _page_t0, 3)

if st.sidebar.checkbox("Show Performance Diagnostics", value=False):
    st.sidebar.dataframe(
        pd.DataFrame([{"Step": k, "Seconds": v} for k, v in _perf.items()]),
        use_container_width=True,
        hide_index=True,
    )
