import pandas as pd

preds = pd.read_parquet("data/prediction_integrity/predictions.parquet")
outs = pd.read_parquet("data/prediction_integrity/outcomes.parquet")
df = preds.merge(outs, on="prediction_id")

if df.empty:
    print("No evaluated outcomes available.")
else:
    df["dt"] = pd.to_datetime(df["target_date"])
    df = df.sort_values(by="dt")
    print("\n--- SAMPLE OUTCOMES ---")
    cols = ["target_date", "horizon_days", "pred_score_mid", "actual_score", "score_mae", "brier_score"]
    print(df[cols].head(10).to_string(index=False))
    
    print("\n--- AGGREGATE STATS ---")
    print(df.groupby("horizon_days")[["score_mae", "brier_score"]].mean().reset_index().to_string(index=False))

    corr = df["pred_score_mid"].corr(df["actual_score"])
    print(f"\nCorrelation between Pred Score vs Actual Score: {corr:.3f}")
