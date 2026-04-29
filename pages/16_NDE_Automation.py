import streamlit as st
import json
from pathlib import Path
from datetime import datetime

from utils import setup_page
import nde_automation_logic

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

if snapshot.get("snapshot_version") != "2.0":
    st.warning("⚠️ **Deprecated Snapshot Version**: Your current snapshot is out of date. Please run a new extraction from the NIFTY Strategy Engine to ensure accurate metrics.")

# Phase 46: Format Unix epoch to human-readable string
readable_ts = "N/A"
if snapshot.get("timestamp"):
    readable_ts = datetime.fromtimestamp(snapshot["timestamp"]).strftime("%Y-%m-%d %H:%M")

st.success(f"Successfully loaded NDE Snapshot from: {snapshot.get('date')} (Refreshed: {readable_ts})")

status = nde_automation_logic.get_ingestion_hub_context()
if status["is_active"]:
    st.caption(f"🟢 **Auto-Sync Active**: Last ingestion sync at {status['latest_file_ts']}. Analytics are current.")
else:
    st.caption(f"🟡 **Manual Fallback**: No fresh ingestion detected in last 8h. Using last saved snapshot.")

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
    # v5: Handle billions formatting and prevent misleading zero
    gex_val = flow.get('total_gex', 0)
    if abs(gex_val) >= 1000:
        gex_display = f"{gex_val/1000:,.2f} B"
    else:
        gex_display = f"{gex_val:,.1f} M"
    st.metric("Total GEX", gex_display)
with fc3:
    st.metric("Gamma Flip", flow.get('gamma_flip'))
    st.metric("Vanna Bias", flow.get('vanna_bias'))

st.subheader("Tactical Bias Target & Transition Profile")
b1, b2, b3 = st.columns(3)
with b1:
    st.info(f"Tactical Bias: **{snapshot.get('bias', {}).get('tactical', 'N/A')}**")
with b2:
    st.info(f"Structural Bias: **{snapshot.get('bias', {}).get('structural', 'N/A')}**")
with b3:
    escalation = snapshot.get("escalation_probability", 0.0)
    risk_label = "Low" if escalation < 0.2 else "Moderate" if escalation < 0.5 else "High"
    st.warning(f"Escalation Risk: **{escalation:.1%}** ({risk_label})")
    
    # Interpretation context (Phase 46 + V5 Hardening)
    regime = str(snapshot.get("regime", "UNKNOWN")).upper()
    drift = snapshot.get("drift_score", 0.0)
    
    # Transition Lookup (V5)
    TRANSITION_LOOKUP = {
        "RISK_ON": {"pos": "OVEREXTENSION", "neg": "SELECTIVE"},
        "SELECTIVE": {"pos": "RISK_ON", "neg": "DEFENSIVE"},
        "DEFENSIVE": {"pos": "SELECTIVE", "neg": "CRISIS"},
        "CRISIS": {"pos": "RECOVERY", "neg": "CAPITULATION"},
        "UNKNOWN": {"pos": "EXPANSION", "neg": "CONTRACTION"}
    }
    target_state = TRANSITION_LOOKUP.get(regime, TRANSITION_LOOKUP["UNKNOWN"])["pos" if drift >= 0 else "neg"]
    
    if risk_label == "High":
        st.error(f"⚠️ **{regime}** regime at high risk of transition toward **{target_state}**.")
    elif risk_label == "Moderate":
        st.warning(f"🔍 **{regime}** regime showing moderate expansion — monitoring breakout toward **{target_state}**.")
    else:
        st.success(f"✅ **{regime}** regime currently shows stable structural alignment.")

st.subheader("Risk Mapping")
rmap = snapshot.get('risk_map', {})
r1, r2, r3 = st.columns(3)
with r1:
    st.error(f"Invalidation Level: ₹{rmap.get('invalidation', 0):,.2f}")
with r2:
    e_range = snapshot.get("expected_move", {})
    st.info(f"Expected Range (1SD): {int(e_range.get('lower',0))} - {int(e_range.get('upper',0))}")
with r3:
    st.warning(f"Bear: {rmap.get('bear_trigger', 0):.0f} | Bull: {rmap.get('bull_trigger', 0):.0f}")

with st.expander("Raw Snapshot JSON", expanded=False):
    st.json(snapshot)

# ==================== PERFORMANCE AUDIT (Criterion E4) ====================
st.divider()
st.subheader("📊 Historical Strategy Performance Audit")
log_file = Path("notes/nde_strategy_log.jsonl")

if log_file.exists():
    try:
        import pandas as pd
        # Read last 50 entries for the audit
        log_data = [json.loads(line) for line in log_file.read_text().splitlines()]
        df_log = pd.DataFrame(log_data).tail(50)
        
        if not df_log.empty:
            # Clean up for display
            df_log = df_log[['date', 'strategy', 'spot', 'regime', 'size', 'quality']]
            df_log = df_log.rename(columns={'date': 'Timestamp', 'strategy': 'Strategy', 'spot': 'Spot', 'regime': 'Regime', 'size': 'Size', 'quality': 'Quality'})
            df_log = df_log.sort_values('Timestamp', ascending=False)
            
            st.dataframe(df_log, use_container_width=True, hide_index=True)
            st.caption("Last 50 automated recommendations recorded in the audit log.")
        else:
            st.info("Performance log is empty.")
    except Exception as e:
        st.error(f"Failed to load performance audit: {e}")
else:
    st.info("No historical strategy log found at `notes/nde_strategy_log.jsonl`.")

# ==================== HISTORICAL SNAPSHOT TREND (E4 Activation) ====================
st.subheader("📈 Snapshot Lineage & Regime Persistence")
try:
    df_history = nde_automation_logic.get_historical_snapshot_df(limit=30)
    if not df_history.empty:
        # Display as a condensed trend table
        trend_df = df_history[['date', 'regime', 'drift_score', 'stability_20d', 'escalation_probability']].copy()
        trend_df = trend_df.rename(columns={
            'date': 'Date', 'regime': 'Regime', 'drift_score': 'Drift', 
            'stability_20d': 'Stability', 'escalation_probability': 'Escalation'
        })
        st.dataframe(trend_df, use_container_width=True, hide_index=True)
        st.caption("Trend derived from last 30 unique daily snapshots.")
    else:
        st.info("No historical snapshots available for trend analysis.")
except Exception as e:
    st.caption(f"Trend Analysis unavailable: {e}")
