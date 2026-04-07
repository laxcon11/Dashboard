import sys
import os
import json
import unittest
from pathlib import Path
from datetime import datetime, timedelta

# Add Dashboard and pages to path
repo_root = Path("..")
sys.path.append(str(repo_root))
sys.path.append(str(repo_root / "pages"))

# Now import the logic directly
from nde_automation_logic import (
    compute_drift,
    compute_stability,
    compute_transition_risk,
    compute_probabilities,
)

class TestNDEv12Logic(unittest.TestCase):

    def setUp(self):
        # Create a mock automation directory if it doesn't exist for test
        self.test_dir = Path("data/automation")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        
        self.history_flat = [
            {"date": "2026-03-01", "score": 0.5, "regime": "RISK_ON"},
            {"date": "2026-03-02", "score": 0.5, "regime": "RISK_ON"},
            {"date": "2026-03-03", "score": 0.5, "regime": "RISK_ON"},
            {"date": "2026-03-04", "score": 0.5, "regime": "RISK_ON"},
            {"date": "2026-03-05", "score": 0.5, "regime": "RISK_ON"},
        ]
        
        self.history_uptrend = [
            {"date": "2026-03-01", "score": 0.1},
            {"date": "2026-03-02", "score": 0.2},
            {"date": "2026-03-03", "score": 0.3},
            {"date": "2026-03-04", "score": 0.4},
            {"date": "2026-03-05", "score": 0.5},
        ]

    def test_drift_correctness(self):
        # Flat history: Current (0.5) - MA5 (0.5) = 0.0
        drift, delta, accel = compute_drift(self.history_flat)
        self.assertEqual(drift, 0.0)

        
        # Uptrend: Current (0.5) - MA5 (0.3) = 0.2
        drift, delta, accel = compute_drift(self.history_uptrend)
        self.assertAlmostEqual(drift, 0.2, places=4)
        self.assertGreater(drift, 0) # Direction check


    def test_stability_bounds(self):
        # Middle of range: Score = 0.3, History: [0.1...0.5], Persistence = 20
        # norm_pos = (0.3 - 0.1) / (0.5 - 0.1) = 0.5
        # term1 = min(1.0, 20/20)*50 = 50
        # term2 = (1.0 - abs(0.5-0.5)*2)*50 = 50
        # Total = 100
        stability, stab_5d, fragile = compute_stability(0.3, self.history_uptrend * 4, 20)
        self.assertEqual(stability, 100)
        self.assertFalse(fragile)

        
        # Persistence = 0, Score at edge (0.5)
        # term1 = 0
        # term2 = (1 - abs(0.5 - 1.0)*2)*50 = 0
        stability, stab_5d, fragile = compute_stability(0.5, self.history_uptrend * 4, 0)
        self.assertEqual(stability, 0)
        self.assertTrue(fragile) 

    def test_risk_score_monotonicity(self):
        # Lower stability or higher drift should increase escalation risk
        risk_low = compute_transition_risk(0.0, 100)
        risk_high_drift = compute_transition_risk(0.5, 100)
        risk_low_stability = compute_transition_risk(0.0, 20)
        
        self.assertGreater(risk_high_drift, risk_low)
        self.assertGreater(risk_low_stability, risk_low)

    def test_json_schema(self):
        # Minimal schema check logic
        required_keys = [
            "date", "regime", "persistence_days", "stability_score", 
            "drift_score", "fragility_flag", "probabilities", 
            "escalation_probability", "gamma", "bias", "risk_map", "config_hash"
        ]
        # This is more about ensuring the structure generated in the page matches
        pass

if __name__ == "__main__":
    unittest.main()
