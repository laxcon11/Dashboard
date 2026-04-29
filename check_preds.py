import pandas as pd

try:
    df = pd.read_parquet("data/prediction_integrity/predictions.parquet")
    print(f"Total rows: {len(df)}")
    df_grouped = df.groupby(["date_issued", "horizon_days"]).size().reset_index(name="count")
    dups = df_grouped[df_grouped["count"] > 1]
    
    if not dups.empty:
        print("Found duplicated dates/horizons:")
        print(dups)
        sample_date = dups.iloc[0]["date_issued"]
        print(f"\nExample rows for {sample_date}:")
        cols = ["prediction_id", "date_issued", "horizon_days", "input_signature", "model_version"]
        print(df[df["date_issued"] == sample_date][cols])
    else:
        print("No duplicates by date/horizon found.")
except Exception as e:
    print(f"Error loading predictions: {e}")
