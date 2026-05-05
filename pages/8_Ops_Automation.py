import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

from utils import setup_page, get_ui_detail_mode, get_ui_device_mode, responsive_cols as _responsive_cols
from regime_state import load_regime_snapshot


setup_page("Ops & Automation")
_ = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"
st.title("🛠 Ops & Automation")
st.caption("Phase 5 operations center: EOD refresh, alerts, and recovery utilities.")
st.caption(f"Device mode: **{device_mode}**")

BASE_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"
ALERT_FILE = BASE_DIR / "logs" / "alerts.log"


# _responsive_cols imported from utils

ssot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
if isinstance(ssot, dict) and ssot:
    probs = ssot.get("probabilities", {}) if isinstance(ssot.get("probabilities", {}), dict) else {}
    st.info(
        "Macro SSOT: "
        f"{ssot.get('regime_label', 'Unknown')} | "
        f"Conf {float(ssot.get('confidence', 0.0) or 0.0):.0%} | "
        f"Score {float(ssot.get('final_score', 0.0) or 0.0):+.2f} | "
        f"P(On/S/D/C) {float(probs.get('risk_on', 0.0) or 0.0):.0%}/"
        f"{float(probs.get('selective', 0.0) or 0.0):.0%}/"
        f"{float(probs.get('defensive', 0.0) or 0.0):.0%}/"
        f"{float(probs.get('crisis', 0.0) or 0.0):.0%}"
    )


def run_script(script_name: str, args: list[str] | None = None) -> tuple[int, str]:
    cmd = [sys.executable, f"scripts/{script_name}"]
    if args:
        cmd.extend(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR), timeout=900)
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return proc.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return 124, f"Timeout while running {' '.join(cmd)}"
    except Exception as exc:
        return 1, f"Failed to run {' '.join(cmd)}: {exc}"


def latest_snapshot_info() -> tuple[Path | None, str]:
    files = sorted(SNAPSHOT_DIR.glob("eod_*.json"))
    if not files:
        return None, "No snapshots yet."
    p = files[-1]
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    age_hours = (datetime.now() - mtime).total_seconds() / 3600.0
    status = "Fresh" if age_hours <= 26 else ("Stale" if age_hours <= 48 else "Very Stale")
    return p, f"{mtime:%Y-%m-%d %H:%M} ({age_hours:.1f}h ago) • {status}"


left, right = _responsive_cols(2)
with left:
    st.subheader("📦 EOD Pipeline")
    snap_file, snap_msg = latest_snapshot_info()
    st.write(f"Latest snapshot: {snap_msg}")
    if snap_file is not None:
        try:
            payload = json.loads(snap_file.read_text())
            st.caption(
                f"Regime: {payload.get('regime', 'Unknown')} | "
                f"Symbols scanned: {payload.get('symbols_scanned', 0)}"
            )
        except Exception:
            st.caption("Snapshot parse failed.")

    if st.button("Run EOD Snapshot Now"):
        rc, out = run_script("eod_pipeline.py")
        if rc == 0:
            st.success("EOD pipeline completed.")
        else:
            st.error(f"EOD pipeline failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")

with right:
    st.subheader("🚨 Alert Engine")
    if st.button("Run Alerts Check"):
        rc, out = run_script("alert_engine.py")
        if rc == 0:
            st.success("Alert check completed.")
        else:
            st.error(f"Alert check failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")

    if ALERT_FILE.exists():
        today_str = datetime.now().strftime("%Y-%m-%d")
        lines = ALERT_FILE.read_text().splitlines()
        today_lines = [ln for ln in lines if ln.startswith(f"[{today_str}")]
        if today_lines:
            st.caption(f"Today's alerts ({len(today_lines)}):")
            for ln in today_lines:
                st.write(f"- {ln}")
        else:
            st.info("No alerts for today.")
        with st.expander("Full alert history (last 7 days)", expanded=False):
            for ln in lines[-30:]:
                st.write(f"- {ln}")
    else:
        st.info("No alerts log yet.")

st.markdown("---")
st.subheader("🕒 GIFT NIFTY Poller")
g1, g2 = _responsive_cols(2, [1, 1])
with g1:
    if st.button("Run GIFT Poll (Once)"):
        rc, out = run_script("poll_gift_nifty.py", ["--once"])
        if rc == 0:
            st.success("GIFT poll completed.")
        else:
            st.error(f"GIFT poll failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with g2:
    st.caption("Continuous polling command (run in terminal):")
    st.code(
        ".venv/bin/python scripts/poll_gift_nifty.py --interval-sec 180 --start-hour 17 --cutoff-hour 10",
        language="bash",
    )

st.markdown("---")
st.subheader("🧰 Recovery Tools")
col1, col2, col3, col4, col5 = _responsive_cols(5)
with col1:
    if st.button("Health Check"):
        rc, out = run_script("recovery_tools.py", ["--health"])
        if rc == 0:
            st.success("Health check complete.")
        else:
            st.error(f"Health check returned code {rc}.")
        st.code(out[-4000:] if out else "(no output)", language="text")
with col2:
    if st.button("Rebuild History"):
        rc, out = run_script("recovery_tools.py", ["--rebuild-history"])
        if rc == 0:
            st.success("History rebuild complete.")
        else:
            st.error(f"History rebuild returned code {rc}.")
        st.code(out[-4000:] if out else "(no output)", language="text")
with col3:
    if st.button("Repair Stale"):
        rc, out = run_script("recovery_tools.py", ["--repair-stale-bhavcopy"])
        if rc == 0:
            st.success("Stale repair complete.")
        else:
            st.error(f"Stale repair returned code {rc}.")
        st.code(out[-4000:] if out else "(no output)", language="text")
    backfill_days = st.number_input("Backfill Days", min_value=1, max_value=365, value=30, step=1)
    if st.button("Run Backfill"):
        rc, out = run_script("recovery_tools.py", ["--backfill-days", str(int(backfill_days))])
        if rc == 0:
            st.success("Backfill complete.")
        else:
            st.error(f"Backfill returned code {rc}.")
        st.code(out[-4000:] if out else "(no output)", language="text")
with col4:
    if st.button("Trust Score"):
        rc, out = run_script("recovery_tools.py", ["--trust-score"])
        if rc == 0:
            st.success("Trust score complete.")
        else:
            st.error(f"Trust score returned code {rc}.")
        st.code(out[-4000:] if out else "(no output)", language="text")
    if st.button("Run Regime Sanity Tests"):
        rc, out = run_script("regime_sanity_tests.py")
        if rc == 0:
            st.success("Regime sanity tests passed.")
        else:
            st.error(f"Sanity tests failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with col5:
    if st.button("Backfill Regime"):
        rc, out = run_script("recovery_tools.py", ["--backfill-regime-history"])
        if rc == 0:
            st.success("Regime history backfilled.")
        else:
            st.error(f"Regime history backfill failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")

st.markdown("---")
st.subheader("🧾 Bhavcopy Parity")
pc1, pc2 = _responsive_cols(2, [1, 1])
with pc1:
    if st.button("Run Parity Report"):
        rc, out = run_script("bhavcopy_parity_report.py")
        if rc == 0:
            st.success("Parity report generated.")
        else:
            st.error(f"Parity report failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with pc2:
    parity_file = BASE_DIR / "logs" / "bhavcopy_parity_latest.json"
    if parity_file.exists():
        try:
            payload = json.loads(parity_file.read_text())
            st.caption(
                f"Trade date: {payload.get('trade_date')} | "
                f"Close mismatch: {payload.get('close_mismatch_count_gt_0_2pct', 0)} | "
                f"Volume mismatch: {payload.get('volume_mismatch_count_gt_20pct', 0)}"
            )
        except Exception:
            st.caption("Parity report found but failed to parse.")
    else:
        st.caption("No parity report yet.")

st.markdown("---")
st.subheader("🛡 Data Trust Score")
t1, t2 = _responsive_cols(2, [1, 1])
with t1:
    if st.button("Run Data Trust Score"):
        rc, out = run_script("data_trust_score.py")
        if rc == 0:
            st.success("Data trust report generated.")
        else:
            st.error(f"Data trust failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with t2:
    trust_file = BASE_DIR / "logs" / "data_trust_latest.json"
    if trust_file.exists():
        try:
            payload = json.loads(trust_file.read_text())
            st.caption(
                f"Status: {payload.get('status')} | "
                f"Trust: {payload.get('trust_score', 0)} | "
                f"Integrity: {payload.get('integrity_score', 0)} | "
                f"Parity: {payload.get('parity_score', 0)} | "
                f"Compute: {payload.get('computation_score', 0)}"
            )
        except Exception:
            st.caption("Trust report found but failed to parse.")
    else:
        st.caption("No trust report yet.")

st.markdown("---")
st.subheader("🧪 Prediction Integrity")
pi1, pi2, pi3 = _responsive_cols(3, [1, 1, 1])
with pi1:
    if st.button("Run Integrity Cycle"):
        rc, out = run_script("prediction_integrity_cycle.py")
        if rc == 0:
            st.success("Prediction integrity cycle completed.")
        else:
            st.error(f"Integrity cycle failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with pi2:
    month_pi = st.text_input("Calibration Month (YYYY-MM)", value="", key="pi_cal_month")
    if st.button("Generate Calibration"):
        args = ["--month", month_pi] if month_pi else None
        rc, out = run_script("prediction_calibration_monthly.py", args)
        if rc == 0:
            st.success("Monthly calibration generated.")
        else:
            st.error(f"Calibration generation failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with pi3:
    if st.button("Apply Approved Proposal"):
        rc, out = run_script("prediction_apply_proposal.py", ["--approved-by", "ops_page"])
        if rc == 0:
            st.success("Approved proposal apply run complete.")
        else:
            st.error(f"Proposal apply failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")

st.markdown("---")
st.subheader("🧮 Scoring Audit")
sa1, sa2 = _responsive_cols(2, [1, 1])
with sa1:
    if st.button("Run Scoring Audit"):
        rc, out = run_script("scoring_audit_report.py")
        if rc == 0:
            st.success("Scoring audit completed.")
        else:
            st.error(f"Scoring audit failed (code {rc}).")
        st.code(out[-4000:] if out else "(no output)", language="text")
with sa2:
    audit_file = BASE_DIR / "logs" / "scoring_audit_latest.json"
    if audit_file.exists():
        try:
            payload = json.loads(audit_file.read_text())
            st.caption(
                f"Status: {payload.get('status')} | "
                f"Overall: {payload.get('overall_score', 0)} | "
                f"Hard fails: {len(payload.get('hard_fail_reasons', []) or [])}"
            )
        except Exception:
            st.caption("Scoring audit report found but failed to parse.")
    else:
        st.caption("No scoring audit report yet.")

st.markdown("---")
st.subheader("📅 Suggested EOD Routine")
st.markdown(
    "1. Run `EOD Snapshot` after market close.\n"
    "2. Run `Alert Engine` to detect regime flips/invalidation breaches.\n"
    "3. Use `Recovery Tools` only on stale/missing data issues."
)
