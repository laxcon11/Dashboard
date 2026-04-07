import pandas as pd
import numpy as np
import sys
import json
from pathlib import Path
import analytics
from config import MAIN_INDICES
from NSE_Config import NIFTY_200, NSE_SECTOR_INDICES, SECTOR_CATEGORIES
from data_fetch import batch_download
from indicators import calculate_rsi, calculate_ema, calculate_atr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------
# CONSTANTS & HELPERS (DUPLICATED FROM 0_NSE_Dashboard.py)
# ---------------------------------------------------------
ATR_PERIOD = 14
STRICTNESS_CFG = {
    "Balanced": {
        "tier_a_plus": 8.5, "tier_a": 7.5, "tier_b": 6.5,
        "min_vol_ratio": 0.8, "min_rs": -3.0, "rs_floor_penalty": 0.10,
        "risk_on_breadth": 1.1, "risk_off_breadth": 0.9,
        "risk_off_min_score": 9.0,
    },
}

def clamp_score(v): return max(0.0, min(10.0, v))
def clip01(v): return max(0.0, min(1.0, v))

def rs_spread_ema3(symbol_df, benchmark_df) -> float:
    if symbol_df is None or benchmark_df is None: return 0.0
    s_close = pd.to_numeric(symbol_df["Close"], errors="coerce").dropna()
    b_close = pd.to_numeric(benchmark_df["Close"], errors="coerce").dropna()
    merged = pd.concat([s_close.rename("s"), b_close.rename("b")], axis=1).dropna()
    if len(merged) < 8: return 0.0
    spread = (merged["s"].pct_change() - merged["b"].pct_change()) * 100.0
    return float(spread.dropna().ewm(span=3, adjust=False).mean().iloc[-1])

def momentum_leg_low(close_series, ema_series, low_series, fallback_lookback=20):
    c = pd.to_numeric(close_series, errors="coerce")
    e = pd.to_numeric(ema_series, errors="coerce")
    l = pd.to_numeric(low_series, errors="coerce")
    df_leg = pd.concat([c.rename("c"), e.rename("e"), l.rename("l")], axis=1).dropna()
    if len(df_leg) < 5: return float(l.tail(fallback_lookback).min())
    vals_c, vals_e = df_leg["c"].values, df_leg["e"].values
    start_idx = None
    for i in range(len(df_leg)-2, 2, -1):
        if (vals_c[i-2] <= vals_e[i-2]) and (vals_c[i-1] <= vals_e[i-1]) and (vals_c[i] > vals_e[i]):
            start_idx = i; break
    if start_idx is None: return float(l.tail(fallback_lookback).min())
    return float(df_leg["l"].iloc[start_idx:].min())

def pullback_leg_low(df_local):
    if df_local is None or df_local.empty: return np.nan
    highs = pd.to_numeric(df_local["High"], errors="coerce")
    lows = pd.to_numeric(df_local["Low"], errors="coerce")
    w = min(25, len(df_local))
    if w < 5: return float(lows.dropna().tail(10).min())
    high_idx = highs.tail(w).idxmax()
    leg_lows = lows.loc[high_idx:].dropna()
    return float(leg_lows.min()) if not leg_lows.empty else float(lows.dropna().tail(10).min())

def prior_support_below(series_low, anchor, bars=60):
    s = pd.to_numeric(series_low, errors="coerce").dropna().tail(bars)
    if len(s) < 7 or pd.isna(anchor): return np.nan
    candidates = []
    vals = s.values
    for i in range(2, len(vals)-2):
        v = vals[i]
        if v < vals[i-1] and v < vals[i+1] and v < vals[i-2] and v < vals[i+2]:
            if v < anchor: candidates.append(v)
    return float(max(candidates)) if candidates else np.nan

def get_baseline_report(symbols, strictness="Balanced"):
    cfg = STRICTNESS_CFG[strictness]
    all_data = batch_download(symbols + ["^NSEI", "^NSEBANK"], period="3mo")
    nifty_df = all_data.get("^NSEI")
    bank_df = all_data.get("^NSEBANK")
    
    rows = []
    for sym in symbols:
        df = all_data.get(sym)
        if df is None or len(df) < 80: continue
        try:
            close = df["Close"].dropna()
            price = float(close.iloc[-1])
            vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=False)
            rs = analytics.calculate_relative_strength(df, nifty_df, period=20)
            rs_ema3 = rs_spread_ema3(df, nifty_df)
            rsi = calculate_rsi(df).iloc[-1]
            ema20_series = calculate_ema(df, 20)
            ema20 = ema20_series.iloc[-1]
            ema50 = calculate_ema(df, 50).iloc[-1]
            atr_series = calculate_atr(df, ATR_PERIOD)
            atr14 = atr_series.iloc[-1]
            breakout = analytics.detect_breakout(df)
            nr7 = analytics.detect_nr7(df)
            dist_ema20 = ((price - ema20)/ema20*100)
            inside_day = bool(len(df) >= 2 and (df["High"].iloc[-1] <= df["High"].iloc[-2]) and (df["Low"].iloc[-1] >= df["Low"].iloc[-2]))
            
            # Calibration Logic (Duplicate from 0_NSE_Dashboard.py)
            rel_std = np.nan
            merged = pd.concat([close.rename("s"), nifty_df["Close"].dropna().rename("b")], axis=1).dropna()
            if len(merged) >= 30:
                rel_ret = merged["s"].pct_change() - merged["b"].pct_change()
                rel_std = rel_ret.tail(20).std()
            
            vol_quality = clip01(vol_ratio / 2.0)
            rs_blend = (0.7 * rs) + (0.3 * rs_ema3)
            
            # Shadow standard values for baseline capture
            rs_stability = 0.5
            rs_quality = clip01((rs_blend + 10.0)/20.0)
            
            mom_base = analytics.calculate_momentum_score(df, nifty_df)
            pb_base = analytics.calculate_pullback_score(df, nifty_df)
            
            # Percentile Ranks (Simulated for parity check)
            # In the dashboard these are rank-based; we will capture the raw components
            rows.append({
                "symbol": sym,
                "price": price,
                "vol_ratio": vol_ratio,
                "rs": rs,
                "rs_ema3": rs_ema3,
                "rsi": rsi,
                "ema20": ema20,
                "atr14": atr14,
                "breakout": breakout,
                "nr7": nr7,
                "dist_ema20": dist_ema20,
                "rel_std": rel_std,
                "mom_base": mom_base,
                "pb_base": pb_base
            })
        except: continue
    return pd.DataFrame(rows)

if __name__ == "__main__":
    sample = list(NIFTY_200[:50])
    log_dir = ROOT / "data" / "verification"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Capturing baseline for {len(sample)} stocks...")
    df = get_baseline_report(sample)
    output_path = log_dir / "baseline_scores.parquet"
    df.to_parquet(output_path)
    print(f"Baseline saved to {output_path}")
