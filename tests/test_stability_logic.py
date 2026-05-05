"""
Tests for Regime Stability and Persistence Filter.
Ensures that a 3-day persistence rule and momentum filter work as expected.
"""
import sys
import os
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import regime_classification as rc

def test_stability_logic():
    # 1. Start with a known state
    state_file = Path("notes/regime_v4_state.json")
    if state_file.exists():
        os.remove(state_file)
        
    settings = {"persistence_days": 3, "momentum_threshold": 0.10}
    
    print("Step 1: Initial Selective Regime (Score 0.20)")
    s1 = rc.apply_stability_filters(0.20, "Selective", settings)
    assert s1["current_regime"] == "Selective"
    assert s1["persistence_count"] == 0
    
    print("Step 2: Score jump to 0.60 (Risk On territory), Day 1")
    s2 = rc.apply_stability_filters(0.60, "Risk On", settings)
    assert s2["current_regime"] == "Selective", "Should still be Selective (Day 1 of Risk On)"
    assert s2["pending_regime"] == "Risk On"
    assert s2["persistence_count"] == 1
    
    print("Step 3: Day 2 of Risk On")
    s3 = rc.apply_stability_filters(0.65, "Risk On", settings)
    assert s3["current_regime"] == "Selective", "Should still be Selective (Day 2 of Risk On)"
    assert s3["persistence_count"] == 2
    
    print("Step 4: Day 3 of Risk On -> FLIP")
    s4 = rc.apply_stability_filters(0.70, "Risk On", settings)
    assert s4["current_regime"] == "Risk On", "Should have flipped to Risk On (Day 3)"
    assert s4["persistence_count"] == 0
    assert s4["pending_regime"] is None
    
    print("Step 5: Crisis bypass (Score -1.0), Day 1")
    s5 = rc.apply_stability_filters(-1.0, "Crisis", settings)
    assert s5["current_regime"] == "Crisis", "Crisis should trigger immediately"
    
    print("Step 6: Momentum lock (Score 0.68 vs 0.70 prev)")
    # prev state was s4 (Risk On, Score 0.70). s5 was Crisis but we want to check momentum.
    # Actually, s5 changed the regime. Let's start fresh for momentum.
    if state_file.exists(): os.remove(state_file)
    rc.apply_stability_filters(0.50, "Risk On", settings) # day 1
    rc.apply_stability_filters(0.50, "Risk On", settings) # day 2
    s_lock = rc.apply_stability_filters(0.50, "Risk On", settings) # day 3 flip
    
    # Now try a tiny change (0.50 -> 0.55, diff=0.05 < 0.10 threshold)
    s_jitter = rc.apply_stability_filters(0.55, "Risk On", settings)
    assert s_jitter["current_score"] == 0.50, f"Score should be locked due to momentum. Got {s_jitter['current_score']}"
    
    print("\n✅ All stability logic tests passed!")

if __name__ == "__main__":
    test_stability_logic()
