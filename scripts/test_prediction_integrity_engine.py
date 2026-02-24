"""Unit tests for prediction integrity engine core math helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prediction_integrity import engine


class TestPredictionIntegrityEngine(unittest.TestCase):
    def test_probs_from_regime_sum_to_one(self) -> None:
        probs = engine._probs_from_regime("RISK_ON", 6.0, trust_score=99.0)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=6)
        self.assertGreater(probs["RISK_ON"], probs["CRISIS"])

    def test_confidence_label_degrades_when_trust_is_low(self) -> None:
        probs = engine._probs_from_regime("RISK_ON", 8.0, trust_score=99.0)
        high_conf = engine._confidence_label(probs, trust_score=99.0)
        low_conf = engine._confidence_label(probs, trust_score=70.0)
        self.assertEqual(high_conf, "HIGH")
        self.assertIn(low_conf, {"MEDIUM", "LOW"})

    def test_confidence_label_thresholds(self) -> None:
        high = engine._confidence_label({"RISK_ON": 0.75, "SELECTIVE": 0.15, "DEFENSIVE": 0.07, "CRISIS": 0.03})
        med = engine._confidence_label({"RISK_ON": 0.55, "SELECTIVE": 0.25, "DEFENSIVE": 0.15, "CRISIS": 0.05})
        low = engine._confidence_label({"RISK_ON": 0.40, "SELECTIVE": 0.35, "DEFENSIVE": 0.20, "CRISIS": 0.05})
        self.assertEqual(high, "HIGH")
        self.assertEqual(med, "MEDIUM")
        self.assertEqual(low, "LOW")

    def test_business_day_add_uses_weekdays(self) -> None:
        # Friday + 1 business day should move to Monday.
        self.assertEqual(engine._business_add("2026-02-20", 1), "2026-02-23")
        self.assertEqual(engine._business_add("2026-02-20", 5), "2026-02-27")


if __name__ == "__main__":
    unittest.main()
