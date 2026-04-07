from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from utils import setup_page, get_ui_detail_mode, get_ui_device_mode, responsive_cols as _responsive_cols


setup_page("Roadmap TODO")
_ = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"

STORE_FILE = Path("notes/todo_inventory.json")


# _responsive_cols imported from utils


def _default_seed() -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "pending": [
            {
                "id": f"task_{uuid.uuid4().hex[:8]}",
                "title": "Phase B: Add India factors to Regime Settings (disabled by default)",
                "area": "Regime",
                "priority": "High",
                "status": "WAITING",
                "condition": "Run Phase A for at least 10 sessions with stable freshness.",
                "owner": "",
                "due_date": "",
                "notes": "",
                "created_at": now,
            },
            {
                "id": f"task_{uuid.uuid4().hex[:8]}",
                "title": "Phase C Step 1: Enable FII Net + India VIX in scoring",
                "area": "Regime",
                "priority": "High",
                "status": "WAITING",
                "condition": "Shadow validation pass: flip count and confidence stability acceptable.",
                "owner": "",
                "due_date": "",
                "notes": "",
                "created_at": now,
            },
            {
                "id": f"task_{uuid.uuid4().hex[:8]}",
                "title": "Automate GST + India curve context ingestion",
                "area": "Data",
                "priority": "Medium",
                "status": "WAITING",
                "condition": "Finalize source endpoints and parsing reliability checks.",
                "owner": "",
                "due_date": "",
                "notes": "",
                "created_at": now,
            },
        ],
        "completed": [],
        "updated_at": now,
    }


def _load_store() -> dict:
    if not STORE_FILE.exists():
        payload = _default_seed()
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STORE_FILE.write_text(json.dumps(payload, indent=2))
        return payload
    try:
        payload = json.loads(STORE_FILE.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Invalid TODO payload")
        payload.setdefault("pending", [])
        payload.setdefault("completed", [])
        return payload
    except Exception:
        payload = _default_seed()
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STORE_FILE.write_text(json.dumps(payload, indent=2))
        return payload


def _save_store(payload: dict) -> None:
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STORE_FILE.write_text(json.dumps(payload, indent=2))


def _complete_task(payload: dict, task_id: str) -> bool:
    pending = payload.get("pending", [])
    for i, task in enumerate(pending):
        if str(task.get("id")) == str(task_id):
            task = dict(task)
            task["completed_at"] = datetime.now().isoformat(timespec="seconds")
            task["status"] = "DONE"
            payload.setdefault("completed", []).append(task)
            del pending[i]
            payload["pending"] = pending
            _save_store(payload)
            return True
    return False


def _delete_task(payload: dict, task_id: str) -> bool:
    pending = payload.get("pending", [])
    new_pending = [t for t in pending if str(t.get("id")) != str(task_id)]
    if len(new_pending) != len(pending):
        payload["pending"] = new_pending
        _save_store(payload)
        return True
    return False


st.title("✅ Roadmap TODO Tracker")
st.caption("Track pending updates, dependencies, and implementation conditions. Completed items auto-hide from active list.")
st.caption(f"Store file: `{STORE_FILE}`")
st.caption(f"Device mode: **{device_mode}**")

store = _load_store()
pending = store.get("pending", [])
completed = store.get("completed", [])

m1, m2, m3 = _responsive_cols(3)
m1.metric("Pending", len(pending))
m2.metric("Completed", len(completed))
m3.metric("Total", len(pending) + len(completed))

with st.expander("➕ Add New Task", expanded=False):
    with st.form("add_todo_form"):
        c1, c2 = _responsive_cols(2)
        with c1:
            title = st.text_input("Task Title")
            area = st.selectbox("Area", ["Regime", "Liquidity", "Swing", "Journal", "Data", "Ops", "UI", "Other"])
            priority = st.selectbox("Priority", ["High", "Medium", "Low"], index=1)
        with c2:
            status = st.selectbox("Status", ["TODO", "WAITING", "IN_PROGRESS"], index=0)
            owner = st.text_input("Owner")
            due_date = st.text_input("Due Date (optional)", placeholder="YYYY-MM-DD")
        condition = st.text_area("Condition to Start / Implement", placeholder="What must be true before implementation?")
        notes = st.text_area("Notes", placeholder="Optional context")
        add = st.form_submit_button("Add Task", use_container_width=True)
        if add and title.strip():
            store["pending"].append(
                {
                    "id": f"task_{uuid.uuid4().hex[:8]}",
                    "title": title.strip(),
                    "area": area,
                    "priority": priority,
                    "status": status,
                    "condition": condition.strip(),
                    "owner": owner.strip(),
                    "due_date": due_date.strip(),
                    "notes": notes.strip(),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            _save_store(store)
            st.success("Task added.")
            st.rerun()

st.markdown("### Active TODO")
if not pending:
    st.success("No pending tasks. Active list is clear.")
else:
    pending_sorted = sorted(
        pending,
        key=lambda x: (
            {"High": 0, "Medium": 1, "Low": 2}.get(str(x.get("priority", "Medium")), 1),
            str(x.get("status", "TODO")),
            str(x.get("title", "")),
        ),
    )

    for task in pending_sorted:
        tid = str(task.get("id"))
        tcol1, tcol2 = _responsive_cols(2, [5, 1])
        with tcol1:
            st.markdown(
                f"**{task.get('title', 'Untitled')}**  \n"
                f"`{task.get('status', 'TODO')}` | `{task.get('priority', 'Medium')}` | `{task.get('area', 'Other')}`"
            )
            if task.get("condition"):
                st.caption(f"Condition: {task.get('condition')}")
            meta = []
            if task.get("owner"):
                meta.append(f"Owner: {task.get('owner')}")
            if task.get("due_date"):
                meta.append(f"Due: {task.get('due_date')}")
            if meta:
                st.caption(" | ".join(meta))
            if task.get("notes"):
                st.caption(f"Notes: {task.get('notes')}")
        with tcol2:
            if st.checkbox("Done", key=f"done_{tid}"):
                if _complete_task(store, tid):
                    st.rerun()
            if st.button("Delete", key=f"del_{tid}", use_container_width=True):
                if _delete_task(store, tid):
                    st.rerun()
        st.markdown("---")

with st.expander("Completed (Hidden from Active TODO)", expanded=False):
    if not completed:
        st.info("No completed tasks yet.")
    else:
        done_df = pd.DataFrame(completed)
        cols = [c for c in ["completed_at", "title", "area", "priority", "owner", "due_date", "condition"] if c in done_df.columns]
        st.dataframe(done_df[cols].sort_values("completed_at", ascending=False), width="stretch", hide_index=True)
        if st.button("Clear Completed History", type="secondary"):
            store["completed"] = []
            _save_store(store)
            st.success("Completed history cleared.")
            st.rerun()
