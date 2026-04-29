import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


SNAPSHOT_FILE = Path("notes/current_regime_snapshot.json")
EOD_SNAPSHOT_DIR = Path("data/snapshots")
logger = logging.getLogger(__name__)


def save_regime_snapshot(payload: Dict[str, Any]) -> None:
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    to_write = dict(payload or {})
    to_write["updated_at"] = datetime.now().isoformat(timespec="seconds")
    SNAPSHOT_FILE.write_text(json.dumps(to_write, indent=2))


def _from_eod_snapshot(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if payload is None:
        files = sorted(EOD_SNAPSHOT_DIR.glob("eod_*.json"))
        if not files:
            return {}
        try:
            payload = json.loads(files[-1].read_text())
        except Exception as exc:
            logger.warning("Failed to load EOD regime snapshot %s: %s", files[-1], exc)
            return {}
    
    regime = str(payload.get("regime", "Unknown"))
    macro_ctx = payload.get("macro_context", {})
    
    # Prioritize Macro Context Score (V1 Institutional) for the dashboard
    v1_score = macro_ctx.get("score")
    if v1_score is None:
        # Fallback to regime_score but scale it down (V4/V5 scores are ~10-60x larger)
        v1_score = payload.get("regime_score", 0.0) / 10.0
    
    return {
        "regime_label": regime if regime else "Unknown",
        "current_regime": regime if regime else "Unknown",
        "confidence": None,
        "final_score": v1_score,
        "pillar_scores": macro_ctx.get("pillars", {}),
        "source": "eod_snapshot",
        "updated_at": payload.get("generated_at"),
    }


def load_regime_snapshot() -> Dict[str, Any]:
    if SNAPSHOT_FILE.exists():
        try:
            payload = json.loads(SNAPSHOT_FILE.read_text())
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            logger.warning("Failed to read current regime snapshot %s: %s", SNAPSHOT_FILE, exc)
    return _from_eod_snapshot()


# ==================== REGIME HISTORY (JSONL) ====================

HISTORY_FILE = Path("notes/regime_history.jsonl")


def _confidence_label(probs: Dict[str, float]) -> str:
    """Derive confidence label from probability distribution."""
    if not probs:
        return "LOW"
    max_p = max(probs.values())
    if max_p >= 0.60:
        return "HIGH"
    if max_p >= 0.40:
        return "MEDIUM"
    return "LOW"


def _regime_tag(regime_label: str) -> str:
    """Map human-readable regime label to timeline tag."""
    r = regime_label.upper()
    if "RISK ON" in r or "RISK_ON" in r:
        return "RISK_ON"
    if "CRISIS" in r:
        return "CRISIS"
    if "DEFENSIVE" in r or "RISK OFF" in r or "RISK_OFF" in r:
        return "DEFENSIVE"
    if "SELECTIVE" in r or "NEUTRAL" in r:
        return "SELECTIVE"
    return "SELECTIVE"


def append_regime_history(payload: Dict[str, Any]) -> None:
    """Append today's regime result to the JSONL history file.

    Deduplicates by date — if today already has an entry, it is replaced
    with the latest computation.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    probs = payload.get("probabilities", {})
    if isinstance(probs, dict):
        # Normalise keys to lowercase for consistency
        probs = {k.lower(): float(v) for k, v in probs.items()}
    else:
        probs = {}

    pillar_scores = payload.get("pillar_scores", {})

    record = {
        "date": today_str,
        "regime": _regime_tag(str(payload.get("regime_label", payload.get("regime", "SELECTIVE")))),
        "score": round(float(payload.get("final_score", 0.0) or 0.0) * 10.0, 2),
        "confidence": _confidence_label(probs),
        "confidence_val": round(float(payload.get("confidence", 0.0)), 4),
        "probabilities": probs,
        "pillar_scores": {k: round(float(v), 4) for k, v in pillar_scores.items()} if pillar_scores else {},
    }

    # Read existing lines, replace today if present
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    replaced = False
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if row.get("date") == today_str:
                    existing.append(json.dumps(record, separators=(",", ":")))
                    replaced = True
                else:
                    existing.append(line)
            except json.JSONDecodeError:
                existing.append(line)

    if not replaced:
        existing.append(json.dumps(record, separators=(",", ":")))

    HISTORY_FILE.write_text("\n".join(existing) + "\n")


def load_regime_history(days: int = 90) -> list[Dict[str, Any]]:
    """Load up to `days` most recent regime history entries from JSONL."""
    if not HISTORY_FILE.exists():
        return []

    rows: list[Dict[str, Any]] = []
    for line in HISTORY_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Sort by date descending, take the latest `days`, then reverse to chronological
    rows.sort(key=lambda r: r.get("date", ""), reverse=True)
    rows = rows[:days]
    rows.reverse()
    return rows
