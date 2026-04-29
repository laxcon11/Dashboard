from prediction_integrity.engine import generate_monthly_calibration, _rolling_skill
import pandas as pd

preds = pd.read_parquet("data/prediction_integrity/predictions.parquet")
outs = pd.read_parquet("data/prediction_integrity/outcomes.parquet")
merged = preds.merge(outs, on="prediction_id", how="inner")
print(f"Total merged outcomes loaded: {len(merged)}")

rolling = _rolling_skill(merged, window=5)

if not rolling:
    print("No rolling skill metrics generated.")
else:
    print("\n--- ROLLING SKILL (Last 5 Days with window=5) ---")
    for r in rolling[-5:]:
        print(r)

print("\nSuccess! Python execution finished.")
