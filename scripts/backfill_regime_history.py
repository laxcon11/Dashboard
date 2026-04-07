"""
One-time backfill: reads existing EOD snapshots from data/snapshots/
and writes corresponding entries to notes/regime_history.jsonl.

Usage:
    python scripts/backfill_regime_history.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import regime_classification as rc
from regime_state import _regime_tag, _confidence_label, HISTORY_FILE, _from_eod_snapshot

SNAPSHOT_DIR = ROOT / "data" / "snapshots"


def main() -> int:
    files = sorted(SNAPSHOT_DIR.glob("eod_*.json"))
    if not files:
        print("No EOD snapshots found in data/snapshots/")
        return 1

    print(f"Starting Smooth Backfill (V1 Engine + 3D Stability) for {len(files)} files...")
    
    # 1. Fresh Start: Clear history and reset stability state
    if HISTORY_FILE.exists():
        os.remove(HISTORY_FILE)
    
    state_file = Path("notes/regime_v4_state.json")
    if state_file.exists():
        os.remove(state_file)

    settings = {"persistence_days": 3, "momentum_threshold": 0.05}
    new_entries: list[str] = []

    for fpath in files:
        # Extract date from filename: eod_YYYYMMDD.json
        date_str_raw = fpath.stem.replace("eod_", "")
        try:
            dt = datetime.strptime(date_str_raw, "%Y%m%d")
            date_str = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

        try:
            payload = json.loads(fpath.read_text())
        except Exception as e:
            print(f"  Skipping {fpath.name}: {e}")
            continue

        # A) Reconstruct V1 Score from Snapshot
        # _from_eod_snapshot extracts the Pillar scores and computes final_score (V1)
        v1_data = _from_eod_snapshot(payload)
        v1_score = v1_data.get("final_score", 0.0)
        
        # B) Raw Classification (V1)
        raw_regime = rc.classify_regime(v1_score)
        
        # C) Apply Stability Filter (Sequential)
        # This updates regime_v4_state.json and respects the 3-day persistence
        st_result = rc.apply_stability_filters(v1_score, raw_regime, settings)
        
        final_regime = st_result["current_regime"]
        final_score_scaled = st_result["current_score"] * 10.0 # Scale to 10x for UI
        
        # D) Probabilities for history record
        probs = rc.calculate_regime_probabilities(v1_score, final_regime)

        record = {
            "date": date_str,
            "regime": _regime_tag(final_regime),
            "score": round(final_score_scaled, 2),
            "confidence": _confidence_label(probs),
            "probabilities": probs,
            "pillar_scores": v1_data.get("pillar_scores", {}),
        }

        new_entries.append(json.dumps(record, separators=(",", ":")))
        print(f"  {date_str}: {record['regime']:<10} (score={record['score']:>5.2f}) p_count={st_result['persistence_count']}")

    # Write all entries to the fresh history file
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        for entry in new_entries:
            f.write(entry + "\n")

    print(f"\n✅ Smooth backfill completed. {len(new_entries)} entries saved to {HISTORY_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
