"""
Force EOD Reconcile from Bhavcopy into local parquet for the latest Bhavcopy date.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from data_fetch import load_latest_bhavcopy_prices, get_latest_bhavcopy_snapshot, _build_fallback_price_df, persist_local_nse_updates
from NSE_Config import NIFTY_200

def main():
    snap = get_latest_bhavcopy_snapshot()
    trade_date = snap.get("trade_date")
    prices = snap.get("prices", {})
    
    if not trade_date or not prices:
        print("[error] No bhavcopy available to force reconcile")
        return 1
        
    print(f"Applying Bhavcopy for {trade_date}...")
    
    valid_symbols = set(NIFTY_200)
    eod_updates = {}
    
    for symbol in valid_symbols:
        if not symbol.endswith(".NS"):
            continue
        row = prices.get(symbol)
        if not row:
            continue
        close, prev_close, vol, o, h, l = row
        bdf = _build_fallback_price_df(close, prev_close, trade_date=trade_date, volume=vol, o=o, h=h, l=l)
        eod_updates[symbol] = bdf

    print(f"Generated updates for {len(eod_updates)} symbols")
    if eod_updates:
        # persist_local_nse_updates concatenates and drops duplicates strictly keeping LAST, so this overwrites existing!
        persist_local_nse_updates(eod_updates)
        print("[ok] Parquet overwritten with EOD Bhavcopy.")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
