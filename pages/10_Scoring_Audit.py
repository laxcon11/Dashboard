from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from utils import setup_page, get_ui_detail_mode


setup_page("Scoring Audit")
view_mode = get_ui_detail_mode("Summary")

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "logs" / "scoring_audit_latest.json"
LOGIC_DOC = ROOT / "docs" / "SCORING_LOGIC.md"

st.title("🧮 Scoring Audit")
st.caption("Deterministic audit of scoring, weightage, logic consistency, and cross-page parity.")
st.caption(f"UI mode: **{view_mode}**")
if LOGIC_DOC.exists():
    st.info(f"Scoring logic reference: `{LOGIC_DOC}`")
else:
    st.warning("Scoring logic reference file not found: `docs/SCORING_LOGIC.md`")


def run_audit() -> tuple[int, str]:
    cmd = [sys.executable, "scripts/scoring_audit_report.py"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=1200)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out.strip()


c1, c2 = st.columns([1, 2])
with c1:
    if st.button("Run Scoring Audit", width="stretch"):
        rc, out = run_audit()
        if rc == 0:
            st.success("Scoring audit completed.")
        else:
            st.error(f"Scoring audit failed (code {rc}).")
        st.code(out[-5000:] if out else "(no output)", language="text")

with c2:
    if LOG_FILE.exists():
        st.caption(f"Latest report: `{LOG_FILE}`")
    else:
        st.info("No scoring audit report yet. Run audit first.")

if not LOG_FILE.exists():
    st.stop()

try:
    payload = json.loads(LOG_FILE.read_text())
except Exception:
    st.error("Latest scoring audit report is unreadable.")
    st.stop()

status = str(payload.get("status", "UNKNOWN")).upper()
overall = payload.get("overall_score", "N/A")

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    if status == "PASS":
        st.success(f"Status: {status}")
    elif status == "WARN":
        st.warning(f"Status: {status}")
    else:
        st.error(f"Status: {status}")
with m2:
    st.metric("Overall", overall)
with m3:
    st.metric("Config", payload.get("scores", {}).get("config", "N/A"))
with m4:
    st.metric("Macro", payload.get("scores", {}).get("macro", "N/A"))
with m5:
    st.metric("Leading", payload.get("scores", {}).get("leading", "N/A"))

hard_fails = payload.get("hard_fail_reasons", []) or []
if hard_fails:
    st.error("Hard Fail Reasons: " + ", ".join(hard_fails))
else:
    st.success("No hard-fail conditions.")

st.subheader("Cross-Page Parity")
parity = payload.get("details", {}).get("cross_page_parity", {})
match_rate = parity.get("match_rate")
if match_rate is None:
    st.info(parity.get("note", "No overlap details available."))
else:
    st.metric("Parity Match Rate", f"{float(match_rate):.0%}")
    cmp_rows = parity.get("comparisons", [])
    if cmp_rows:
        df = pd.DataFrame(cmp_rows)
        st.dataframe(df, width="stretch", hide_index=True)

with st.expander("Macro Math Details", expanded=(view_mode == "Detail")):
    macro = payload.get("details", {}).get("macro", {})
    st.json(macro)

with st.expander("Leading Math Details", expanded=(view_mode == "Detail")):
    leading = payload.get("details", {}).get("leading", {})
    st.json(leading)

with st.expander("Config Checks", expanded=(view_mode == "Detail")):
    cfg = payload.get("details", {}).get("config", {})
    st.json(cfg)

with st.expander("Raw Report JSON", expanded=False):
    st.json(payload)

st.caption("Audit scope: configuration validity, formula integrity, range checks, factor sufficiency, and shared-factor sign parity.")
