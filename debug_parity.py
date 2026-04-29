import pandas as pd
from data_fetch import load_latest_bhavcopy_prices, get_latest_bhavcopy_snapshot
from NSE_Config import NIFTY_200, PRESET_WATCHLISTS

universe = set(NIFTY_200)

snap = get_latest_bhavcopy_snapshot()
prices = snap.get("prices", {}) or {}
trade_date = snap.get("trade_date")

from config import LOCAL_NSE_HISTORY_PATH
df = pd.read_parquet(LOCAL_NSE_HISTORY_PATH)
work = df.copy()
work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
work["symbol"] = work["symbol"].astype(str).str.upper().str.strip()
day = pd.to_datetime(trade_date).normalize()

local = work[(work["date"] == day) & (work["symbol"].isin(universe))][["symbol", "close", "volume"]].copy()
local = local.rename(columns={"close": "close_local", "volume": "vol_local"})

rows = []
for s in sorted(universe):
    row = prices.get(s)
    if not row:
        continue
    close_b, _prev_b, vol_b, _, _, _ = row
    rows.append({"symbol": s, "close_bhav": float(close_b), "vol_bhav": float(vol_b or 0.0)})
bh = pd.DataFrame(rows)

if bh.empty:
    print(f"Bhavcopy dictionary is completely empty! Keys: {list(prices.keys())[:10]}")
    exit(1)

merged = local.merge(bh, on="symbol", how="outer")
merged["close_diff_pct"] = ((merged["close_local"] - merged["close_bhav"]) / merged["close_bhav"] * 100.0).abs()

print(f"Total Universe: {len(universe)}")
print(f"Bhavcopy Rows: {len(bh)}")
print(f"Local Rows for {day.date()}: {len(local)}")
print(f"Merged Rows: {len(merged)}")
print("\nSample of mismatched rows:")
print(merged[merged["close_diff_pct"] > 0.2].head(10).to_string())
