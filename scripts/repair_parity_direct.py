"""
Surgical repair for Parquet/Bhavcopy parity.
Specifically targets the latest Bhavcopy date and overwrites parquet rows for NIFTY 200 components.
"""
import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from NSE_Config import NIFTY_200
from config import LOCAL_NSE_HISTORY_PATH
from data_fetch import load_latest_bhavcopy_prices, get_latest_bhavcopy_snapshot

def main():
    # 1. Load Bhavcopy
    prices = load_latest_bhavcopy_prices()
    snap = get_latest_bhavcopy_snapshot()
    trade_date = snap.get("trade_date")
    if not prices or not trade_date:
        print("[error] no bhavcopy available for repair")
        return 1
    
    trade_date = pd.to_datetime(trade_date).normalize()
    print(f"Repairing data for date: {trade_date.date()}")

    # 2. Load Parquet
    p_path = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    if not p_path.exists():
        print(f"[error] parquet not found: {p_path}")
        return 1
    
    df = pd.read_parquet(p_path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["symbol"] = df["symbol"].str.upper().str.strip()

    # 3. Create patch rows
    patch_rows = []
    for sym in sorted(set(NIFTY_200)):
        if sym in prices:
            close, prev, vol, o, h, l = prices[sym]
            patch_rows.append({
                "date": trade_date,
                "symbol": sym,
                "open": float(o if o else close),
                "high": float(h if h else close),
                "low": float(l if l else close),
                "close": float(close),
                "volume": int(vol if vol else 0)
            })
    
    patch_df = pd.DataFrame(patch_rows)
    print(f"Created patch for {len(patch_df)} symbols.")

    # 4. Merge and save
    # Remove old rows for this date and these symbols
    symbols_to_patch = set(patch_df["symbol"])
    mask = (df["date"] == trade_date) & (df["symbol"].isin(symbols_to_patch))
    df = df[~mask].copy()

    final_df = pd.concat([df, patch_df], ignore_index=True)
    final_df = final_df.sort_values(["symbol", "date"]).drop_duplicates(subset=["symbol", "date"], keep="last")
    
    final_df.to_parquet(p_path, index=False)
    print(f"[ok] Parquet repaired and saved: {p_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
