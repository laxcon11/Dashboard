import pandas as pd
import numpy as np
import analytics
from indicators import calculate_rsi, calculate_ema, calculate_atr

# ==================== CONSTANTS ====================
ATR_PERIOD = 14

# ==================== CONFIGURATION ====================
STRICTNESS_CFG = {
    "Conservative": {
        "tier_a_plus": 8.8,
        "tier_a": 8.0,
        "tier_b": 7.2,
        "min_vol_ratio": 1.0,
        "min_rs": -1.0,
        "rs_floor_penalty": 0.15,
        "risk_on_breadth": 1.2,
        "risk_off_breadth": 0.85,
        "risk_off_min_score": 9.4,
        "top_n": 2,
        "watchlist_n": 4,
    },
    "Balanced": {
        "tier_a_plus": 8.5,
        "tier_a": 7.5,
        "tier_b": 6.5,
        "min_vol_ratio": 0.8,
        "min_rs": -3.0,
        "rs_floor_penalty": 0.10,
        "risk_on_breadth": 1.1,
        "risk_off_breadth": 0.9,
        "risk_off_min_score": 9.0,
        "top_n": 3,
        "watchlist_n": 5,
    },
    "Aggressive": {
        "tier_a_plus": 8.2,
        "tier_a": 7.0,
        "tier_b": 6.0,
        "min_vol_ratio": 0.6,
        "min_rs": -5.0,
        "rs_floor_penalty": 0.08,
        "risk_on_breadth": 1.0,
        "risk_off_breadth": 0.95,
        "risk_off_min_score": 8.6,
        "top_n": 4,
        "watchlist_n": 8,
    },
}

# ==================== CORE HELPERS ====================

def clamp_score(value):
    return max(0.0, min(10.0, value))

def clip01(v):
    return max(0.0, min(1.0, v))

def setup_tier(score, config):
    if score >= config["tier_a_plus"]:
        return "A+"
    if score >= config["tier_a"]:
        return "A"
    if score >= config["tier_b"]:
        return "B"
    return "C"

def drawdown_penalty(curr_price, high_20d) -> float:
    """Penalty for sharp corrections from recent highs."""
    if not high_20d or high_20d <= 0:
        return 0.0
    dd_pct = (high_20d - curr_price) / high_20d
    if dd_pct >= 0.10:
        return 4.0
    if dd_pct >= 0.05:
        return 2.0
    return 0.0

def streak_penalty(consecutive_red_days) -> float:
    """Penalty for sustained negative momentum (red-day streaks)."""
    if consecutive_red_days >= 5:
        return 1.0
    if consecutive_red_days >= 3:
        return 0.5
    return 0.0

def rs_spread_ema3(symbol_df, benchmark_df) -> float:
    if symbol_df is None or benchmark_df is None:
        return 0.0
    if "Close" not in symbol_df.columns or "Close" not in benchmark_df.columns:
        return 0.0
    s_close = pd.to_numeric(symbol_df["Close"], errors="coerce").dropna()
    b_close = pd.to_numeric(benchmark_df["Close"], errors="coerce").dropna()
    merged = pd.concat([s_close.rename("s"), b_close.rename("b")], axis=1).dropna()
    if len(merged) < 8:
        return 0.0
    spread = (merged["s"].pct_change() - merged["b"].pct_change()) * 100.0
    spread = spread.dropna()
    if spread.empty:
        return 0.0
    return float(spread.ewm(span=3, adjust=False).mean().iloc[-1])

def trend_signal(df):
    if df is None or len(df) < 50:
        return 0
    close = df['Close'].dropna()
    if len(close) < 50:
        return 0
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    current = close.iloc[-1]
    if current > ema20 > ema50:
        return 1
    if current < ema20 < ema50:
        return -1
    return 0

# ==================== LEG & SUPPORT HELPERS ====================

def recent_swing_low(series_low, lookback=20):
    if series_low is None:
        return np.nan
    s = pd.to_numeric(series_low, errors="coerce").dropna()
    if s.empty:
        return np.nan
    return float(s.tail(lookback).min())

def momentum_leg_low(close_series, ema_series, low_series, fallback_lookback=20):
    c = pd.to_numeric(close_series, errors="coerce")
    e = pd.to_numeric(ema_series, errors="coerce")
    l = pd.to_numeric(low_series, errors="coerce")
    df_leg = pd.concat([c.rename("c"), e.rename("e"), l.rename("l")], axis=1).dropna()
    if len(df_leg) < 5:
        return recent_swing_low(low_series, lookback=fallback_lookback)
    start_idx = None
    vals_c = df_leg["c"].values
    vals_e = df_leg["e"].values
    for i in range(len(df_leg) - 2, 2, -1):
        if (vals_c[i - 2] <= vals_e[i - 2]) and (vals_c[i - 1] <= vals_e[i - 1]) and (vals_c[i] > vals_e[i]):
            start_idx = i
            break
    if start_idx is None:
        return recent_swing_low(low_series, lookback=fallback_lookback)
    leg_low = df_leg["l"].iloc[start_idx:].min()
    if pd.isna(leg_low):
        return recent_swing_low(low_series, lookback=fallback_lookback)
    return float(leg_low)

def pullback_leg_low(df_local):
    if df_local is None or df_local.empty or "High" not in df_local.columns or "Low" not in df_local.columns:
        return np.nan
    highs = pd.to_numeric(df_local["High"], errors="coerce")
    lows = pd.to_numeric(df_local["Low"], errors="coerce")
    w = min(25, len(df_local))
    if w < 5:
        return float(lows.dropna().tail(10).min()) if not lows.dropna().empty else np.nan
    high_window = highs.tail(w)
    if high_window.dropna().empty:
        return float(lows.dropna().tail(10).min()) if not lows.dropna().empty else np.nan
    high_idx = high_window.idxmax()
    leg_lows = lows.loc[high_idx:].dropna()
    if leg_lows.empty:
        return float(lows.dropna().tail(10).min()) if not lows.dropna().empty else np.nan
    return float(leg_lows.min())

def prior_support_below(series_low, anchor, bars=60):
    s = pd.to_numeric(series_low, errors="coerce").dropna().tail(bars)
    if len(s) < 7 or pd.isna(anchor):
        return np.nan
    candidates = []
    vals = s.values
    for i in range(2, len(vals) - 2):
        v = vals[i]
        if v < vals[i - 1] and v < vals[i + 1] and v < vals[i - 2] and v < vals[i + 2]:
            if v < anchor:
                candidates.append(v)
    if not candidates:
        return np.nan
    return float(max(candidates))

def get_unified_stop_loss(entry: float, structural_stop: float, atr14: float, side: str = "LONG") -> float:
    """
    Apply a risk ceiling to structural stops to prevent 20%+ risk distances.
    Ceiling = 3 * ATR14 from entry.
    """
    if pd.isna(entry) or entry <= 0:
        return structural_stop
        
    atr_cap = 3.0 * atr14 if not pd.isna(atr14) else 0.10 * entry
    
    if side.upper() == "LONG":
        # Stop should be structural low, but no further than 3 ATRs from entry
        if pd.isna(structural_stop):
            return entry - atr_cap
        return max(structural_stop, entry - atr_cap)
    else:
        if pd.isna(structural_stop):
            return entry + atr_cap
        return min(structural_stop, entry + atr_cap)

def get_trailing_stop_loss(
    side: str,
    entry_price: float,
    initial_stop: float,
    current_price: float,
    high_since_entry: float,
    atr14: float,
    ema20: float,
    trail_type: str = "OFF"
) -> float:
    """
    Calculate the dynamic trailing stop-loss price.
    - Global: Always respects the get_unified_stop_loss (3x ATR) ceiling.
    - OFF: Static unified stop.
    - EMA: max(unified_stop, ema20 - 0.2*atr14).
    - ATR: max(unified_stop, high_since_entry - 2.5*atr14).
    """
    side_txt = str(side).upper()
    
    # Ensure the initial stop respects the system risk ceiling (3x ATR)
    unified_stop = get_unified_stop_loss(entry_price, initial_stop, atr14, side_txt)
    
    if trail_type == "OFF":
        return unified_stop
        
    current_stop = unified_stop
    
    if side_txt == "LONG":
        if trail_type == "EMA":
            # Trail below EMA with a tiny buffer to avoid noise
            ema_stop = ema20 - (0.2 * atr14 if not pd.isna(atr14) else 0.0)
            current_stop = max(unified_stop, ema_stop)
        elif trail_type == "ATR":
            atr_val = atr14 if not pd.isna(atr14) else (0.05 * entry_price)
            current_stop = max(unified_stop, high_since_entry - 2.5 * atr_val)
    else: # SHORT
        if trail_type == "EMA":
            ema_stop = ema20 + (0.2 * atr14 if not pd.isna(atr14) else 0.0)
            current_stop = min(unified_stop, ema_stop)
        elif trail_type == "ATR":
            atr_val = atr14 if not pd.isna(atr14) else (0.05 * entry_price)
            current_stop = min(unified_stop, high_since_entry + 2.5 * atr_val)
            
    return round(float(current_stop), 2)

# ==================== HIGH LEVEL CALCULATION ====================

def calculate_quality_metrics(df, benchmark_df):
    """Returns a dict of metrics used for quality filtering"""
    try:
        close = df["Close"].dropna()
        price = float(close.iloc[-1])
        vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=False)
        rs = analytics.calculate_relative_strength(df, benchmark_df, period=20)
        rs_ema3 = rs_spread_ema3(df, benchmark_df)
        
        rel_std = np.nan
        if benchmark_df is not None and "Close" in benchmark_df.columns:
            merged = pd.concat([close.rename("s"), benchmark_df["Close"].dropna().rename("b")], axis=1).dropna()
            if len(merged) >= 30:
                rel_ret = merged["s"].pct_change() - merged["b"].pct_change()
                rel_std = rel_ret.tail(20).std()
        
        rs_blend = (0.7 * rs) + (0.3 * rs_ema3)
        rs_quality = clip01((rs_blend + 10.0)/20.0)
        
        return {
            "price": price,
            "vol_ratio": vol_ratio,
            "rs": rs,
            "rs_ema3": rs_ema3,
            "rs_blend": rs_blend,
            "rs_quality": rs_quality,
            "rel_std": rel_std
        }
    except Exception as exc:
        return None
