import pandas as pd
import numpy as np
import sys
from pathlib import Path
import scoring
from NSE_Config import NIFTY_200
from config import MAIN_INDICES
from data_fetch import batch_download

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def get_new_report(symbols, strictness="Balanced"):
    all_data = batch_download(symbols + ["^NSEI"], period="3mo")
    nifty_df = all_data.get("^NSEI")
    
    rows = []
    for sym in symbols:
        df = all_data.get(sym)
        if df is None or len(df) < 80: continue
        try:
            metrics = scoring.calculate_quality_metrics(df, nifty_df)
            if metrics is None: continue
            
            # Additional raw components for parity check
            from indicators import calculate_rsi, calculate_ema, calculate_atr
            from analytics import calculate_momentum_score, calculate_pullback_score, detect_breakout, detect_nr7
            
            close = df["Close"].dropna()
            rsi = calculate_rsi(df).iloc[-1]
            ema20 = calculate_ema(df, 20).iloc[-1]
            atr14 = calculate_atr(df, 14).iloc[-1]
            breakout = detect_breakout(df)
            nr7 = detect_nr7(df)
            dist_ema20 = ((metrics["price"] - ema20)/ema20*100)
            mom_base = calculate_momentum_score(df, nifty_df)
            pb_base = calculate_pullback_score(df, nifty_df)
            
            rows.append({
                "symbol": sym,
                "price": metrics["price"],
                "vol_ratio": metrics["vol_ratio"],
                "rs": metrics["rs"],
                "rs_ema3": metrics["rs_ema3"],
                "rsi": rsi,
                "ema20": ema20,
                "atr14": atr14,
                "breakout": breakout,
                "nr7": nr7,
                "dist_ema20": dist_ema20,
                "rel_std": metrics["rel_std"],
                "mom_base": mom_base,
                "pb_base": pb_base
            })
        except Exception as e:
            print(f"Error processing {sym}: {e}")
            continue
    return pd.DataFrame(rows)

if __name__ == "__main__":
    log_dir = ROOT / "data" / "verification"
    baseline_path = log_dir / "baseline_scores.parquet"
    if not baseline_path.exists():
        print("Baseline not found. Run verify_scoring_parity.py first.")
        sys.exit(1)
        
    baseline_df = pd.read_parquet(baseline_path).sort_values("symbol").reset_index(drop=True)
    symbols = baseline_df["symbol"].tolist()
    
    print(f"Running shadow test on {len(symbols)} symbols...")
    new_df = get_new_report(symbols).sort_values("symbol").reset_index(drop=True)
    
    # Compare
    comparison = baseline_df.compare(new_df)
    if comparison.empty:
        print("✅ SUCCESS: 0.00% variance. Bit-for-bit parity achieved.")
    else:
        print("❌ FAILURE: Variance detected!")
        print(comparison)
        sys.exit(1)
