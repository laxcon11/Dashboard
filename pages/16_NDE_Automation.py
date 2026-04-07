import streamlit as st
import json
from pathlib import Path
from datetime import datetime

from utils import setup_page

AUTOMATION_OUTPUT_DIR = Path("data/automation")
AUTOMATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

setup_page("NDE Automation Reader")

# ==================== DATA LAYER ====================

with st.sidebar:
    st.header("⚙️ Snapshot Reader")
    if st.button("🔃 Force Data Refresh"):
        st.rerun()

def get_latest_snapshot():
    # Phase 41: Prioritize the 'Latest' alias
    alias = AUTOMATION_OUTPUT_DIR / "latest_snapshot.json"
    if alias.exists():
        try:
            return json.loads(alias.read_text())
        except: pass
        
    files = list(AUTOMATION_OUTPUT_DIR.glob("nde_v12_*.json"))
    if not files:
        return None
    latest = max(files, key=lambda x: x.stat().st_mtime)
    try:
        return json.loads(latest.read_text())
    except Exception as e:
        st.error(f"Failed to read snapshot: {e}")
        return None

snapshot = get_latest_snapshot()

st.title("🤖 Daily Automated NDE Snapshot")

if not snapshot:
    st.warning("No daily snapshot found. Please generate one from the NIFTY Strategy Engine (Page 17) first.")
    st.stop()

st.success(f"Successfully loaded NDE Snapshot from: {snapshot.get('date')} (Timestamp: {snapshot.get('timestamp')})")

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Curr Regime", snapshot.get('regime', 'N/A'))
    st.metric("Persistence", f"{snapshot.get('persistence_days', 0)} Days")
with col2:
    st.metric("Trend Drift", snapshot.get('drift_score', 0.0))
    st.metric("Acceleration", snapshot.get('drift_accel', 0.0))
with col3:
    st.metric("5D Stability", snapshot.get('stability_5d', 0))
    # Schema Resilience: fallback to older 'stability_score' if 'stability_20d' is missing
    stab_20 = snapshot.get('stability_20d', snapshot.get('stability_score', 50))
    st.metric("20D Stability", stab_20)


st.subheader("Options Intelligence Flow")
flow = snapshot.get('options_flow', {})
fc1, fc2, fc3 = st.columns(3)
with fc1:
    st.metric("Active Expiry", flow.get('expiry'))
    st.metric("Flow Regime", flow.get('flow_regime'))
with fc2:
    st.metric("Gamma Regime", flow.get('gamma_regime'))
    st.metric("Total GEX", f"{flow.get('total_gex', 0):,.1f} M")
with fc3:
    st.metric("Gamma Flip", flow.get('gamma_flip'))
    st.metric("Vanna Bias", flow.get('vanna_bias'))

st.subheader("Tactical Bias Target")
b1, b2 = st.columns(2)
with b1:
    st.info(f"Tactical Bias: **{snapshot.get('bias', {}).get('tactical', 'N/A')}**")
with b2:
    st.info(f"Structural Bias: **{snapshot.get('bias', {}).get('structural', 'N/A')}**")

st.subheader("Risk Mapping")
rmap = snapshot.get('risk_map', {})
r1, r2, r3 = st.columns(3)
with r1:
    st.error(f"Invalidation Risk: {rmap.get('invalidation', 0):.2f}")
with r2:
    st.warning(f"Bear Trigger: {rmap.get('bear_trigger', 0):.2f}")
with r3:
    st.success(f"Bull Trigger: {rmap.get('bull_trigger', 0):.2f}")

with st.expander("Raw Snapshot JSON", expanded=False):
    st.json(snapshot)
