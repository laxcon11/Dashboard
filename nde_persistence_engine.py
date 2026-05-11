import json
import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from nde_schema import EngineContext, EngineEncoder

# Canonical Persistence Paths
DATA_DIR = Path("data/persistence")
STREAM_FILE = DATA_DIR / "nde_stream.jsonl"
LATEST_SNAPSHOT_DIR = DATA_DIR / "latest"

def ensure_persistence_structure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def persist_context(ctx: EngineContext):
    """
    Consolidated Persistence Logic (Carmack Refactor).
    Writes full deterministic state to an append-only JSONL stream
    and updates the latest index-specific alias atomically.
    """
    ensure_persistence_structure()
    
    # 1. Use Exchange Timestamp as Canonical ID
    snapshot_id = ctx.raw_chain_timestamp or ctx.timestamp.strftime("%Y%m%d_%H%M%S")
    
    # 2. Prepare Payload
    payload = {
        "snapshot_id": snapshot_id,
        "index_name": ctx.index_name,
        "timestamp": ctx.timestamp.isoformat(),
        "spot": ctx.spot,
        "atr": ctx.atr,
        "t_days": ctx.t_days,
        "flow": ctx.flow,
        "rv": ctx.rv,
        "gamma_local": ctx.gamma_local,
        "state": ctx.state,
        "execution": ctx.execution,
        "meta": ctx.meta
    }
    
    # 3. Append to Global Stream (JSONL)
    # Using JSONL for auditability, replayability, and data recovery
    line = json.dumps(payload, cls=EngineEncoder) + "\n"
    with open(STREAM_FILE, "a") as f:
        f.write(line)
        
    # 4. Atomic 'Latest' Update
    # Prevents reading partial snapshots during high-frequency writes
    latest_file = LATEST_SNAPSHOT_DIR / f"latest_{ctx.index_name.upper()}.json"
    
    with tempfile.NamedTemporaryFile('w', delete=False, dir=LATEST_SNAPSHOT_DIR) as tf:
        json.dump(payload, tf, cls=EngineEncoder, indent=2)
        temp_name = tf.name
        
    shutil.move(temp_name, latest_file)
    
    # Backward Compatibility: Symlink global latest
    global_latest = LATEST_SNAPSHOT_DIR / "latest_snapshot.json"
    if global_latest.exists():
        global_latest.unlink()
    
    try:
        os.symlink(latest_file.name, global_latest)
    except OSError:
        # Fallback if symlinks are not supported or fail
        shutil.copy2(latest_file, global_latest)

def load_latest_context(index_name: str = "NIFTY") -> Optional[Dict[str, Any]]:
    """Loads the most recent deterministic state for a specific index."""
    target = LATEST_SNAPSHOT_DIR / f"latest_{index_name.upper()}.json"
    if not target.exists():
        return None
        
    try:
        with open(target, 'r') as f:
            return json.load(f)
    except Exception:
        return None
