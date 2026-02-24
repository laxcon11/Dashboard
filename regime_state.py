import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


SNAPSHOT_FILE = Path("notes/current_regime_snapshot.json")
EOD_SNAPSHOT_DIR = Path("data/snapshots")


def save_regime_snapshot(payload: Dict[str, Any]) -> None:
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    to_write = dict(payload or {})
    to_write["updated_at"] = datetime.now().isoformat(timespec="seconds")
    SNAPSHOT_FILE.write_text(json.dumps(to_write, indent=2))


def _from_eod_snapshot() -> Dict[str, Any]:
    files = sorted(EOD_SNAPSHOT_DIR.glob("eod_*.json"))
    if not files:
        return {}
    try:
        payload = json.loads(files[-1].read_text())
    except Exception:
        return {}
    regime = str(payload.get("regime", "Unknown"))
    return {
        "regime_label": regime if regime else "Unknown",
        "confidence": None,
        "final_score": payload.get("score"),
        "macro_directional": None,
        "liquidity_directional": None,
        "probabilities": {},
        "bias": None,
        "source": f"eod:{files[-1].name}",
        "updated_at": payload.get("generated_at"),
    }


def load_regime_snapshot() -> Dict[str, Any]:
    if SNAPSHOT_FILE.exists():
        try:
            payload = json.loads(SNAPSHOT_FILE.read_text())
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return _from_eod_snapshot()

