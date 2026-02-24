from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from prediction_integrity.engine import (
    apply_approved_proposal,
    generate_monthly_calibration,
    run_daily_cycle,
)
from prediction_integrity.store import (
    CAL_DIR,
    PROPOSAL_DIR,
    latest_calibration_proposal,
    load_outcomes,
    load_predictions,
    load_versions,
    read_json,
    write_json,
)
from regime_state import load_regime_snapshot
from utils import get_ui_detail_mode, setup_page

MIN_SAMPLE_BY_HORIZON = {1: 20, 5: 12, 20: 8}


setup_page("Prediction Integrity")
view_mode = get_ui_detail_mode("Summary")

st.title("🧪 Prediction Integrity")
st.caption("Immutable prediction log, matured outcome scoring, and monthly calibration governance.")
st.caption(f"UI mode: **{view_mode}**")

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Run Daily Integrity Cycle", width="stretch"):
        out = run_daily_cycle()
        st.success(f"Cycle complete: issued={out['issue'].get('issued', 0)} | evaluated={out['evaluate'].get('evaluated', 0)}")
with c2:
    month = st.text_input("Calibration month (YYYY-MM)", value="", placeholder="2026-02")
with c3:
    if st.button("Generate Monthly Calibration", width="stretch"):
        report = generate_monthly_calibration(month=(month or None))
        st.success(f"Calibration generated for {report.get('month', 'N/A')} ({report.get('status', 'UNKNOWN')})")

preds = load_predictions()
outs = load_outcomes()
vers = load_versions()

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Predictions Logged", int(len(preds)))
with m2:
    st.metric("Outcomes Evaluated", int(len(outs)))
with m3:
    open_count = int(max(0, len(preds) - len(outs)))
    st.metric("Open Predictions", open_count)
with m4:
    acc = float(pd.to_numeric(outs.get("regime_correct"), errors="coerce").mean()) if not outs.empty else float("nan")
    st.metric("Regime Hit Rate", "N/A" if pd.isna(acc) else f"{acc:.1%}")

ssot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
if isinstance(ssot, dict) and ssot:
    probs = ssot.get("probabilities", {}) if isinstance(ssot.get("probabilities", {}), dict) else {}
    st.caption(
        f"Current Macro SSOT: {ssot.get('regime_label', 'Unknown')} | "
        f"Confidence {float(ssot.get('confidence', 0.0) or 0.0):.0%} | "
        f"Score {float(ssot.get('final_score', 0.0) or 0.0):+.2f} | "
        f"P(On/N/Off): {float(probs.get('risk_on', 0.0) or 0.0):.0%}/"
        f"{float(probs.get('neutral', 0.0) or 0.0):.0%}/"
        f"{float(probs.get('risk_off', 0.0) or 0.0):.0%}"
    )

st.subheader("Sample Sufficiency")
if outs.empty:
    st.warning("No matured outcomes yet. Calibration should be treated as informational only.")
else:
    counts = (
        preds[["prediction_id", "horizon_days"]]
        .merge(outs[["prediction_id"]], on="prediction_id", how="inner")
        .groupby("horizon_days", dropna=False)["prediction_id"]
        .count()
        .to_dict()
    )
    c1, c2, c3 = st.columns(3)
    for col, hz in zip([c1, c2, c3], [1, 5, 20]):
        actual_n = int(counts.get(hz, 0))
        min_n = int(MIN_SAMPLE_BY_HORIZON[hz])
        ready = actual_n >= min_n
        with col:
            st.metric(f"T+{hz} Samples", f"{actual_n}/{min_n}")
            if ready:
                st.success("Calibration-Ready")
            else:
                st.warning("Collect More Data")

with st.expander("How To Use This Page", expanded=False):
    st.markdown("**Regime definitions (objective intent)**")
    st.markdown("- `RISK_ON`: broad participation, trend-following bias.")
    st.markdown("- `DEFENSIVE`: reduced risk with selective defensive participation.")
    st.markdown("- `CRISIS`: risk-off protection-first posture.")
    st.markdown("- `SELECTIVE`: dispersion regime; trade only leadership pockets, not broad beta.")
    st.markdown("- For daily sector-level `SELECTIVE` context, refer to `Swing Rankings` on the NSE Dashboard.")

    st.markdown("**1) What this page does today**")
    st.markdown("- Logs immutable daily predictions for T+1, T+5, and T+20.")
    st.markdown("- Appends realized outcomes when target dates mature.")
    st.markdown("- Computes forecast-quality metrics (accuracy, Brier, log loss, band hit).")
    st.markdown("- Generates monthly calibration proposals with approval gate before applying.")

    st.markdown("**2) How to read and use it**")
    st.markdown("- Start with `Sample Sufficiency`: avoid heavy tuning until horizon sample is ready.")
    st.markdown("- Use `Prediction Records` to verify today has three horizons logged.")
    st.markdown("- Use `Outcome Records` to see predicted-vs-actual gap and error concentration.")
    st.markdown("- Use `Monthly Calibration & Approval` only when enough matured outcomes exist.")

    st.markdown("**3) What to watch for calibration**")
    st.markdown("- Regime accuracy by horizon: weak T+20 with strong T+1 often means over-reactive long horizon.")
    st.markdown("- Brier/log-loss drift: rising values indicate poorer probability calibration.")
    st.markdown("- `in_band` rate: low values suggest score ranges are too narrow or unstable.")
    st.markdown("- Confidence reliability: HIGH-confidence predictions should materially outperform MEDIUM/LOW.")
    st.markdown("- Version drift: compare performance after model-version changes before keeping tweaks.")

with st.expander("Latest Daily Cycle Log", expanded=False):
    log = read_json(Path("logs/prediction_integrity_latest.json"))
    if log:
        st.json(log)
    else:
        st.info("No cycle log found yet.")


st.subheader("Monthly Calibration & Approval")
proposal_path = latest_calibration_proposal()
if proposal_path is None:
    st.info("No calibration proposal file found yet. Generate monthly calibration first.")
else:
    proposal = read_json(proposal_path) or {}
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Proposal", str(proposal.get("proposal_id", "N/A")))
    r2.metric("Month", str(proposal.get("month", "N/A")))
    r3.metric("Status", str(proposal.get("status", "UNKNOWN")))
    r4.metric("Generated", str(proposal.get("generated_at", "N/A"))[:10])

    st.caption(f"File: `{proposal_path}`")

    changes = proposal.get("proposed_changes", [])
    if isinstance(changes, list) and changes:
        st.dataframe(pd.DataFrame(changes), width="stretch", hide_index=True)

    with st.expander("Review & Approval", expanded=False):
        reviewer = st.text_input("Reviewer", value="laxman")
        comments = st.text_area("Review comments", value=str(proposal.get("approval", {}).get("comments") or ""))
        s1, s2, s3 = st.columns(3)

        def _save_status(status: str) -> None:
            proposal["status"] = status
            proposal.setdefault("approval", {})
            proposal["approval"]["comments"] = comments
            proposal["approval"]["approved_by"] = reviewer if status == "APPROVED" else None
            proposal["approval"]["approved_at"] = pd.Timestamp.now().isoformat(timespec="seconds") if status == "APPROVED" else None
            write_json(proposal_path, proposal)
            st.success(f"Proposal status updated to {status}")

        with s1:
            if st.button("Mark APPROVED", width="stretch"):
                _save_status("APPROVED")
        with s2:
            if st.button("Mark MODIFY_REQUESTED", width="stretch"):
                _save_status("MODIFY_REQUESTED")
        with s3:
            if st.button("Mark REJECTED", width="stretch"):
                _save_status("REJECTED")

    if st.button("Apply Approved Proposal", width="stretch"):
        result = apply_approved_proposal(str(proposal_path), approved_by="streamlit")
        if result.get("applied", 0) > 0:
            st.success(f"Applied {result['applied']} changes and versioned settings.")
        else:
            st.warning(result.get("reason", "No changes applied."))


with st.expander("Prediction Records (immutable)", expanded=(view_mode == "Detail")):
    if preds.empty:
        st.info("No predictions yet.")
    else:
        show = preds.copy()
        show["pred_regime_probs"] = show["pred_regime_probs"].astype(str).str.slice(0, 120)
        st.dataframe(show.sort_values(["date_issued", "horizon_days"], ascending=[False, True]), width="stretch", hide_index=True)

with st.expander("Outcome Records", expanded=(view_mode == "Detail")):
    if outs.empty:
        st.info("No outcomes yet.")
    else:
        st.dataframe(outs.sort_values(["evaluated_at"], ascending=False), width="stretch", hide_index=True)

with st.expander("Model Versions", expanded=False):
    if vers.empty:
        st.info("No model versions recorded yet.")
    else:
        st.dataframe(vers.sort_values(["created_at"], ascending=False), width="stretch", hide_index=True)

with st.expander("Calibration Artifacts", expanded=False):
    reports = sorted(CAL_DIR.glob("monthly_calibration_*.json"))
    props = sorted(PROPOSAL_DIR.glob("proposal_*.json"))
    st.write(f"Reports: {len(reports)}")
    for p in reports[-12:][::-1]:
        st.write(f"- {p}")
    st.write(f"Proposals: {len(props)}")
    for p in props[-12:][::-1]:
        st.write(f"- {p}")

st.caption("Governance rule: Predictions are append-only; outcomes are appended only after target date matures.")
