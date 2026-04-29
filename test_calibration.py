import pandas as pd
import numpy as np
from prediction_integrity.engine import generate_monthly_calibration, REGIMES

print("Generating monthly calibration...")
report = generate_monthly_calibration(month="2026-03")

# 1. Baseline Skill Score tests
skill = report.get("skill_metrics", {})
print(f"\n--- SKILL SCORE METRICS ---")
print(f"Model Accuracy:   {skill.get('model_accuracy')}")
print(f"Naive Accuracy:   {skill.get('naive_accuracy')}")
print(f"Raw Skill Score:  {skill.get('skill_score')}")
print(f"Normalized Skill: {skill.get('normalized_skill')}")

# 2. Probability Conservation tests
print(f"\n--- RELIABILITY CURVE (Bins) ---")
curve = report.get("reliability_curve", [])
if not curve:
    print("No reliable curve generated (possibly no data).")
for b in curve:
    print(b)
    assert 0.0 <= b["predicted_prob"] <= 1.0, f"Predicted prob out of bounds: {b['predicted_prob']}"
    assert 0.0 <= b["observed_freq"] <= 1.0, f"Observed freq out of bounds: {b['observed_freq']}"

# 3. Transition Matrix sum to 1.0 tests
print(f"\n--- TRANSITION MATRIX ---")
t_mat = report.get("transition_matrix", {})
for regime_from, transitions in t_mat.items():
    print(f"{regime_from} -> {transitions}")
    row_sum = sum(transitions.values())
    if row_sum > 0: # Only assert if there were actually observations
        assert np.isclose(row_sum, 1.0), f"Row {regime_from} sums to {row_sum}, not 1.0!"

print("\nSuccess! All mathematical constraints passed.")
