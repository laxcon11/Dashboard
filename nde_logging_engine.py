import json
import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ==================== STATE MANAGEMENT ====================
STATE_FILE = Path("notes/strategy_state.json")
AUDIT_FILE = Path("notes/nde_strategy_log.jsonl")
STATE_VERSION = "2.0"

class CustomJsonEncoder(json.JSONEncoder):
    """Handles NumPy and Pandas types for JSON serialization."""
    def default(self, obj):
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def _default_strategy_state() -> Dict[str, Any]:
    return {"last_strategy": "NO_TRADE", "persistence_days": 1, "last_update": "", "state_version": STATE_VERSION}

def load_strategy_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try: 
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                if data.get("state_version") != STATE_VERSION:
                    logger.info(f"Strategy state version mismatch ({data.get('state_version')} != {STATE_VERSION}), resetting.")
                    return _default_strategy_state()
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load strategy state: {e}")
    return _default_strategy_state()

def save_strategy_state(state: Dict[str, Any]):
    STATE_FILE.parent.mkdir(exist_ok=True)
    state["state_version"] = STATE_VERSION
    state["last_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATE_FILE.write_text(json.dumps(state, indent=2, cls=CustomJsonEncoder))

def append_strategy_audit(entry: Dict[str, Any]):
    """
    Canonical Audit Logging Engine.
    Ensures one entry per evaluation with full institutional telemetry.
    """
    AUDIT_FILE.parent.mkdir(exist_ok=True)
    try:
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(entry, cls=CustomJsonEncoder) + "\n")
    except Exception as e:
        logger.error(f"Audit log failure: {e}")

def log_execution(ctx: dict, narrative: dict, execution_plan: dict):
    """
    Execution Persistence Engine.
    Tracks ENTER events and historical context.
    """
    try:
        master = ctx.get("master_setup", {})
        m_state = master.get("market_state", {})
        rv = ctx.get("realized_metrics", {})
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "spot": ctx.get("spot"),
            "state": m_state.get("state"),
            "substate": m_state.get("substate"),
            "volatility_regime": m_state.get("volatility_regime"),
            "suppression_regime": m_state.get("suppression_regime"),
            "confidence": m_state.get("confidence"),
            "transition_risk": m_state.get("transition_risk"),
            "rv_structure": rv,
            "signal_alignment": master.get("signal_alignment"),
            "action": narrative.get("dominant_action"),
            "template": execution_plan.get("template"),
            "legs": execution_plan.get("legs"),
            "ctx_snapshot": ctx,
            "narrative": narrative
        }
        os.makedirs("logs", exist_ok=True)
        with open("logs/execution_audit_log.jsonl", "a") as f:
            f.write(json.dumps(entry, cls=CustomJsonEncoder) + "\n")
            
        # Position Manager logic has been decoupled from the primary engine.
            
    except Exception as e:
        logger.error(f"Failed to log execution: {e}")
