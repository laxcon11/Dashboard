import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Singleton Cache Storage
_COMPUTE_CACHE: Dict[str, Dict[str, Any]] = {}

def get_cached_result(snapshot_id: str, stage: str) -> Optional[Any]:
    """Retrieves a cached result for a specific snapshot and compute stage."""
    if snapshot_id in _COMPUTE_CACHE:
        return _COMPUTE_CACHE[snapshot_id].get(stage)
    return None

def set_cached_result(snapshot_id: str, stage: str, result: Any):
    """Stores a result in the cache and clears stale snapshots."""
    global _COMPUTE_CACHE
    
    # Simple LRU-style cleanup: If cache grows too large, clear it
    if len(_COMPUTE_CACHE) > 10:
        _COMPUTE_CACHE.clear()
        
    if snapshot_id not in _COMPUTE_CACHE:
        _COMPUTE_CACHE[snapshot_id] = {}
        
    _COMPUTE_CACHE[snapshot_id][stage] = result

def invalidate_cache():
    """Explicitly clears all cached computations."""
    _COMPUTE_CACHE.clear()
