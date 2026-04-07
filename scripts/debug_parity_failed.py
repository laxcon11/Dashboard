import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from NSE_Config import NIFTY_200
from data_fetch import load_latest_bhavcopy_prices, get_latest_bhavcopy_snapshot

def main():
    p = ROOT / "data/nse_230_history.parquet"
    if not p.exists():
        print("Parquet not found")
        return
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    
    snap = get_latest_bhavcopy_snapshot()
    bhav_prices = load_latest_bhavcopy_prices()
    trade_date = pd.to_datetime(snap.get("trade_date")).normalize()
    
    print(f"Comparing for Trade Date: {trade_date}")
    
    day_df = df[df["date"] == trade_date]
    if day_df.empty:
        print("No data in parquet for this date")
        return

    mismatches = []
    for sym in NIFTY_200:
        row = day_df[day_df["symbol"] == sym]
        if row.empty:
            print(f"Missing in parquet: {sym}")
            continue
            
        bhav = bhav_prices.get(sym)
        if not bhav:
            print(f"Missing in bhavcopy: {sym}")
            continue
            
        p_close = float(row["close"].iloc[0])
        b_close = float(bhav[0])
        diff_pct = abs((p_close - b_close) / b_close * 100)
        
        if diff_pct > 0.2:
            mismatches.append({
                "symbol": sym,
                "parquet_close": p_close,
                "bhav_close": b_close,
                "diff_pct": diff_pct
            })
            
    if mismatches:
        print(f"\nFound {len(mismatches)} mismatches in NIFTY 50:")
        for m in mismatches[:10]:
            print(f"{m['symbol']}: P={m['parquet_close']:.2f}, B={m['bhav_close']:.2f}, Diff={m['diff_pct']:.2f}%")
    else:
        print("\nNo mismatches found in NIFTY 50 components.")

if __name__ == "__main__":
    main()
