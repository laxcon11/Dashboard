import math
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import os
from pathlib import Path
import logging
import re

logger = logging.getLogger(__name__)

# ==================== DATE PARSING HARDENING ====================
def _parse_nse_date(date_str):
    """Robustly parse NSE dates like '07-Apr-2026' or '7-Apr-2026' regardless of locale."""
    if not date_str or date_str == "Unknown":
        return None
        
    # Manual month mapping to avoid locale issues with %b
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
    }
    
    try:
        # Regex to split DD-MMM-YYYY
        parts = re.split(r'[-/]', date_str)
        if len(parts) != 3:
            return None
            
        day = int(parts[0])
        month_str = parts[1].upper()
        month = months.get(month_str)
        if not month:
            return None
        year = int(parts[2])
        return datetime(year, month, day)
    except:
        return None

# ==================== PROCESS CONFIG ====================
import NSE_Config
import data_fetch
import nde_expiry_helper
from nse_v3_client import NSEv3Client, parse_v3_chain, clean_chain
import json
LOT = NSE_Config.NIFTY_LOT_SIZE
RISK_FREE_RATE = NSE_Config.RISK_FREE_RATE
DIVIDEND_YIELD = NSE_Config.DIVIDEND_YIELD

OPTION_CHAIN_DIR = Path("data/option_chain")
OPTION_CHAIN_DIR.mkdir(parents=True, exist_ok=True)

EPS = 1e-8

def format_institutional_metric(val: float, unit: str = "Cr") -> str:
    """
    Standardizes raw engine values into human-readable institutional strings.
    Phase 41: Assumes input val is in MILLION INR (Engine Native Unit).
    10 Million = 1 Crore (Cr).
    """
    if unit == "Cr":
        # 1 Cr = 10 Million INR. 
        # Since 'val' is already in Millions, we divide by 10.0.
        scaled = val / 10.0
        return f"{scaled:,.1f} Cr"
    elif unit == "M":
        # Since 'val' is already in Millions, we divide by 1.0.
        scaled = val / 1.0
        return f"{scaled:,.1f} M"
    return f"{val:,.0f}"

def safe_iv(iv):
    return np.maximum(iv, 0.01)

def safe_T(T):
    # vectorized and scalar safe T
    if isinstance(T, (int, float)):
        return max(T, 1/365.0)
    return np.maximum(T, 1/365.0)

def compute_atm_iv(df: pd.DataFrame, spot: float) -> float:
    """3-strike inverse-distance weighted ATM IV (v3 Robust)"""
    if df is None or df.empty: return 15.0
    df_grouped = df.groupby("strike", as_index=False)["iv"].mean()
    df_grouped["dist"] = (df_grouped["strike"] - spot).abs()
    # Get 3 nearest unique strikes
    atm = df_grouped.sort_values("dist").head(3)
    if atm.empty: return 15.0
    
    # inverse distance weighting
    weights = 1.0 / (atm["dist"] + 1.0)
    avg_iv = np.average(atm["iv"], weights=weights)
    return float(avg_iv)

def compute_iv_rank(current_iv: float, history: pd.Series, label_prefix: str = "") -> dict:
    """Compute IV Rank logic (Invariant to lot size)"""
    if len(history) < 20:
        return {"atm_iv": float(current_iv), "iv_rank": 50.0, "iv_pct": 50.0, "label": "UNKNOWN", "reliable": False}
    
    lookback = history.tail(252)
    iv_low  = lookback.min()
    iv_high = lookback.max()
    
    iv_rank = ((current_iv - iv_low) / (iv_high - iv_low + 1e-6)) * 100
    iv_pct = (lookback < current_iv).sum() / len(lookback) * 100
    
    label = (
        "ELEVATED"   if iv_rank >= 60 else
        "NORMAL"     if iv_rank >= 30 else
        "COMPRESSED" if iv_rank >= 15 else
        "CRUSHED"
    )
    
    return {
        "atm_iv": float(current_iv),
        "iv_rank": float(round(np.clip(iv_rank, 0, 100), 1)),
        "iv_pct": float(round(iv_pct, 1)),
        "label": f"{label_prefix} {label} (Approximation)".strip(),
        "low_52w": float(round(iv_low, 2)),
        "high_52w": float(round(iv_high, 2)),
        "reliable": True
    }

def calculate_atr_sma(df: pd.DataFrame, window: int = 20) -> float:
    """Calculate 20-day ATR (Simple Moving Average) for volatility normalization."""
    if df is None or df.empty or len(df) < window:
        return 250.0 # Standard Nifty fallback
    
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window).mean().iloc[-1]
    return float(atr) if pd.notnull(atr) else 250.0

def calculate_dte_fractional(expiry_str: str) -> float:
    """Calculate fractional days to expiry from NSE date string (e.g. '07-Apr-2026')."""
    exp_date = _parse_nse_date(expiry_str)
    if not exp_date:
        return 3.0 # Fallback
    
    now = datetime.now()
    # If it's the day of expiry, return a small floor to avoid div-by-zero
    diff = (exp_date - now).total_seconds() / 86400.0
    return max(0.01, diff)

import re

# ==================== CONFIGURATION ====================
STRIKE_INTEL_CONFIG = {
    "alpha": 0.7,             # Risk weight for Vega in scoring
    "min_distance_pct": 0.005, # Minimum OTM distance (0.5%)
    "max_distance_pct": 0.08,  # Maximum OTM distance (8%)
    "min_theta_m": 0.05,       # Minimum 0.05M INR daily decay floor
    "min_oi": 500,             # Minimum liquidity
    "risk_quantiles": [0.7, 0.9],
    "proximity_penalty": 0.2,
    "vega_percentile": 80,
    "zone_merge_gap": 150,
    "symmetry_weight": 5.0     # Phase 30: Recalibrated down from 12.0
}

# ==================== MATH UTILITIES ====================

def norm_cdf(x):
    """
    High-precision Standard normal CDF using Abramowitz & Stegun 7.1.26.
    Accuracy: |e(x)| < 1.5e-7.
    """
    if x < 0:
        return 1.0 - norm_cdf(-x)
    
    # Coefficients for A&S 7.1.26
    p  =  0.2316419
    b1 =  0.319381530
    b2 = -0.356563782
    b3 =  1.781477937
    b4 = -1.821255978
    b5 =  1.330274429
    
    t = 1.0 / (1.0 + p * x)
    z = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x**2)
    return 1.0 - z * (b1*t + b2*t**2 + b3*t**3 + b4*t**4 + b5*t**5)

def _norm_cdf(x):
    """Vectorized High-precision A&S 7.1.26."""
    ax = np.abs(x)
    p  =  0.2316419
    b1 =  0.319381530
    b2 = -0.356563782
    b3 =  1.781477937
    b4 = -1.821255978
    b5 =  1.330274429
    
    t = 1.0 / (1.0 + p * ax)
    z = (1.0 / np.sqrt(2.0 * np.pi)) * np.exp(-0.5 * ax**2)
    p_x = 1.0 - z * (b1*t + b2*t**2 + b3*t**3 + b4*t**4 + b5*t**5)
    return np.where(x >= 0, p_x, 1.0 - p_x)

def _norm_pdf(x):
    """Vectorized PDF."""
    return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)

def norm_pdf(x):
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x**2)

# ==================== BLACK-SCHOLES GREEKS ====================

def calculate_greeks(S, K, T, r, iv, q=0.0, option_type="call"):
    """
    Standard Black-Scholes Greeks with Dividends (q) and Stability gates.
    """
    T = safe_T(T)
    iv = safe_iv(iv)
    
    # Calculate d1, d2 with dividends
    d1 = (math.log(S / K) + (r - q + 0.5 * iv**2) * T) / (iv * math.sqrt(T) + EPS)
    d2 = d1 - iv * math.sqrt(T)
    
    exp_qT = math.exp(-q * T)
    exp_rT = math.exp(-r * T)

    # Delta
    if option_type.lower() == "call":
        delta = exp_qT * norm_cdf(d1)
    else:
        delta = exp_qT * (norm_cdf(d1) - 1.0)
        
    # Gamma
    gamma = (exp_qT * norm_pdf(d1)) / (S * iv * math.sqrt(T) + EPS)
    
    # Vega (per 1% change)
    vega = (S * exp_qT * norm_pdf(d1) * math.sqrt(T)) / 100.0
    
    # Theta (per day)
    term1 = -(S * exp_qT * norm_pdf(d1) * iv) / (2 * math.sqrt(T) + EPS)
    if option_type.lower() == "call":
        term2 = -q * S * exp_qT * norm_cdf(d1)
        term3 = r * K * exp_rT * norm_cdf(d2)
        theta = (term1 + term2 - term3) / 365.0
    else:
        term2 = q * S * exp_qT * norm_cdf(-d1)
        term3 = r * K * exp_rT * norm_cdf(-d2)
        theta = (term1 + term2 + term3) / 365.0
        
    # Rho (per 1% change)
    if option_type.lower() == "call":
        rho = (K * T * exp_rT * norm_cdf(d2)) / 100.0
    else:
        rho = (-K * T * exp_rT * norm_cdf(-d2)) / 100.0

    # Vanna: d(Delta) / d(sigma)
    vanna = -exp_qT * norm_pdf(d1) * d2 / (iv + EPS)
    
    # Charm: -d(Delta) / d(t)
    # Approx logic:
    charm_base = exp_qT * (norm_pdf(d1) * ( (r-q) / (iv * math.sqrt(T) + EPS) - d2 / (2 * T + EPS)) - q * norm_cdf(d1))
    charm = -charm_base if option_type.lower() == "call" else charm_base
        
    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "vega": float(vega),
        "theta": float(theta),
        "rho": float(rho),
        "vanna": float(vanna),
        "charm": float(charm)
    }

def compute_option_flow_exposures(spot: float, df: pd.DataFrame, r: float = RISK_FREE_RATE, q: float = DIVIDEND_YIELD):
    """
    Compute aggregate GEX, VEX, CEX in Million INR.
    v3: Institutional stability + Normalized metrics (lot-invariant logic).
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {
            "total_gex": 0.0, "total_gex_abs": 0.0, "total_vega": 0.0, 
            "total_theta": 0.0, "total_delta": 0.0, "total_volume": 0.0, "total_oi_chng": 0.0,
            "tv_ratio": 0.0, "tv_label": "N/A", "flow_regime_label": "Unknown",
            "intelligence": {}, "raw_exposures": pd.DataFrame()
        }
        
    # Phase 41: Vectorized Greeks computation with stability guards
    K_arr = df["strike"].values.astype(float)
    T_val = (df["t_days"] if "t_days" in df.columns else df.get("dte", pd.Series([3.0] * len(df)))).values.astype(float)
    T_arr = safe_T(T_val) / 365.0
    iv_arr = safe_iv(df["iv"].values.astype(float) / 100.0)
    oi_arr = df["oi"].values.astype(float)
    types = df["type"].str.lower().values
    ltp_arr = df["ltp"].values.astype(float) if "ltp" in df.columns else np.zeros(len(df))
    
    is_call = (types == "call")
    flow_sign = np.where(is_call, 1.0, -1.0)
    
    # Vectorized BS Greeks with Dividends
    sqrt_T = np.sqrt(T_arr)
    log_SK = np.log(np.maximum(spot / K_arr, 1e-10))
    
    d1 = (log_SK + (r - q + 0.5 * iv_arr**2) * T_arr) / (iv_arr * sqrt_T + EPS)
    d2 = d1 - iv_arr * sqrt_T
    
    N_d1 = _norm_cdf(d1)
    N_d2 = _norm_cdf(d2)
    n_d1 = _norm_pdf(d1)
    
    exp_qT = np.exp(-q * T_arr)
    exp_rT = np.exp(-r * T_arr)

    delta = np.where(is_call, exp_qT * N_d1, exp_qT * (N_d1 - 1.0))
    gamma = (exp_qT * n_d1) / (spot * iv_arr * sqrt_T + EPS)
    vega = (spot * exp_qT * n_d1 * sqrt_T) / 100.0

    # Theta
    term1 = -(spot * exp_qT * n_d1 * iv_arr) / (2 * sqrt_T + EPS)
    theta_call = (term1 - q * spot * exp_qT * N_d1 - r * K_arr * exp_rT * N_d2) / 365.0
    theta_put = (term1 + q * spot * exp_qT * _norm_cdf(-d1) + r * K_arr * exp_rT * _norm_cdf(-d2)) / 365.0
    theta = np.where(is_call, theta_call, theta_put)
    
    # Vanna & Charm
    vanna = -exp_qT * n_d1 * d2 / (iv_arr + EPS)
    charm_call = -exp_qT * (n_d1 * ( (r-q) / (iv_arr * sqrt_T + EPS) - d2 / (2 * T_arr + EPS)) - q * N_d1)
    charm_put = exp_qT * (n_d1 * ( (r-q) / (iv_arr * sqrt_T + EPS) - d2 / (2 * T_arr + EPS)) - q * _norm_cdf(-d1))
    charm = np.where(is_call, charm_call, charm_put)
    
    # ── Exposure calculations ────────────────────────────────────────────────
    # GEX: gamma_per_point × OI_contracts × LOT_shares × spot
    #   = total INR delta change per 1-point NIFTY move (the correct index GEX unit)
    #   Do NOT use spot² — gamma is already per-index-point, not per-dollar.
    gex_signed   = gamma * oi_arr * LOT * spot * flow_sign   # +calls, -puts
    gex_magnitude= gamma * oi_arr * LOT * spot               # always ≥ 0

    # DEX: delta × OI × LOT  (delta is dimensionless 0-1; ×LOT gives shares equivalent)
    # Reporting in ₹-crore: ×spot / 1e7 later during aggregation
    dex      = delta * oi_arr * LOT * spot   # INR notional delta exposure
    vega_exp = vega  * oi_arr * LOT          # INR vega per 1% IV move
    tex      = theta * oi_arr * LOT          # INR theta per day
    cex      = charm * oi_arr * LOT
    vanna_exp= vanna * oi_arr * LOT * flow_sign

    df_exp = pd.DataFrame({
        "strike": K_arr, "type": types, "gamma": gamma, "vanna": vanna,
        "delta": delta, "theta": theta, "vega": vega, "charm": charm,
        "ltp": ltp_arr,
        "gex_signed":    gex_signed,
        "gex_magnitude": gex_magnitude,
        "gex_net": gex_signed,   # alias used downstream
        "gex":     gex_signed,
        "vega_exp": vega_exp, "dex": dex, "tex": tex, "cex": cex,
        "vanna_exp": vanna_exp, "oi": oi_arr
    })

    # ── High-Fidelity Data Capture (Volume & OI Change) ──────────────────────
    if "volume" in df.columns:
        df_exp["volume"] = df["volume"].values.astype(float)
    if "oi_chng" in df.columns:
        df_exp["oi_chng"] = df["oi_chng"].values.astype(float)

    # ── Sensibull Greeks Override ─────────────────────────────────────────────
    greek_cols = ["gamma", "delta", "theta", "vega"]
    for g_col in greek_cols:
        target_col = f"sensi_{g_col}"
        if target_col in df.columns:
            df_exp[g_col] = df[target_col].values.astype(float)
            if g_col == "gamma":
                df_exp["gex_magnitude"] = df_exp[g_col] * df_exp["oi"] * LOT * spot
                df_exp["gex_signed"]    = df_exp["gex_magnitude"] * flow_sign
                df_exp["gex_net"]       = df_exp["gex_signed"]
                df_exp["gex"]           = df_exp["gex_signed"]
            elif g_col == "vega":
                df_exp["vega_exp"] = df_exp[g_col] * df_exp["oi"] * LOT
            elif g_col == "theta":
                df_exp["tex"] = df_exp[g_col] * df_exp["oi"] * LOT
            elif g_col == "delta":
                df_exp["dex"] = df_exp[g_col] * df_exp["oi"] * LOT * spot

    # ── Aggregate Totals (Millions of INR) ───────────────────────────────────
    MILLION = 1_000_000.0   # 1 Million INR

    # Net GEX: directional sum (positive = dealer long gamma → dampens moves)
    total_gex_net = df_exp["gex_signed"].sum() / MILLION

    # Abs GEX: sum of |per-strike net| — true magnitude of exposure
    _strike_net   = df_exp.groupby("strike")["gex_signed"].sum()
    total_gex_abs = _strike_net.abs().sum() / MILLION

    total_delta = df_exp["dex"].sum() / MILLION
    total_vega  = df_exp["vega_exp"].sum() / MILLION
    total_theta = df_exp["tex"].sum() / MILLION
    total_cex   = df_exp["cex"].sum() / MILLION
    total_vex   = df_exp["vanna_exp"].sum() / MILLION

    # Lot-normalized (per-lot crore)
    total_gex_norm   = total_gex_net  / LOT
    total_vega_norm  = total_vega     / LOT
    total_theta_norm = total_theta    / LOT
    total_vex_norm   = total_vex      / LOT
    total_cex_norm   = total_cex      / LOT

    # Aggregate Volume & OI Change (Phase 42: Institutional Flow)
    total_volume = df_exp["volume"].sum() if "volume" in df_exp.columns else 0.0
    total_oi_chng = df_exp["oi_chng"].sum() if "oi_chng" in df_exp.columns else 0.0
    
    # Normalized for regime detection
    vol_oi_ratio = total_volume / max(df_exp["oi"].sum(), 1.0)
    oi_chng_pct = total_oi_chng / max(df_exp["oi"].sum(), 1.0)


    # Gamma Flip Level Identification
    # Cross-over point of cumulative NET GEX
    df_sorted = df_exp.groupby("strike")["gex_net"].sum().sort_index().reset_index()
    df_sorted["cum_gex_net"] = df_sorted["gex_net"].cumsum()
    
    flip_level = 0.0
    # Find where it crosses zero
    for i in range(len(df_sorted)-1):
        if (df_sorted.iloc[i]["cum_gex_net"] * df_sorted.iloc[i+1]["cum_gex_net"]) < 0:
            flip_level = df_sorted.iloc[i]["strike"]
            break
            
    # Vega/Theta Cluster Detection (Phase 29.2: Use pre-computed exposure columns)
    def calculate_greek_clusters(df, greek_field, top_n=5):
        if df.empty:
            return []
        
        # Determine the correct exposure column mapping
        col_map = {"vega": "vega_exp", "theta": "tex", "vanna": "vanna_exp"}
        exp_col = col_map.get(greek_field, greek_field)
        
        if exp_col not in df.columns:
            return []
            
        exposure_sum = df.groupby("strike")[exp_col].sum().abs().sort_values(ascending=False).head(top_n)
        return [{"strike": float(s), "exposure": float(e)} for s, e in exposure_sum.items()]

    vega_clusters = calculate_greek_clusters(df_exp, "vega")
    theta_clusters = calculate_greek_clusters(df_exp, "theta")
    intelligence = analyze_strike_intelligence(df_exp, spot)

    # Phase 37: Continuous Entry Gate (Theta/Vega Carry Ratio)
    import math
    t_days = df_exp["t_days"].iloc[0] if "t_days" in df_exp.columns else 3.0
    
    # TV Ratio Calibration (v3: Normalized units for safety)
    vega_eff = max(total_vega, 1e-9)
    tv_ratio = (abs(total_theta) / math.sqrt(t_days + 1)) / vega_eff
    
    # Risk 2: TV Regime Drift Dual Baseline (Fast 5 EWMA vs Slow 20 EWMA)
    import json
    from pathlib import Path
    state_file = Path("notes/strategy_state.json")
    tv_ema_fast = 1.0
    tv_ema_slow = 1.0
    if state_file.exists():
        try:
            sd = json.loads(state_file.read_text())
            tv_ema_fast = float(sd.get("tv_ratio_ema_fast", tv_ratio) or 1.0)
            tv_ema_slow = float(sd.get("tv_ratio_ema_slow", tv_ratio) or 1.0)
        except: pass
            
    # v2: Absolute Safety Gating (Phase 42 Hardening)
    tv_norm = tv_ratio / max(abs(tv_ema_slow), 0.1)
    tv_norm = min(tv_norm, 5.0)  
    tv_regime_shift = abs(tv_ema_fast - tv_ema_slow)
    
    # Absolute Gates (independent of EMA history)
    if tv_ratio >= 2.5:
        tv_label = "AVOID"
    elif tv_ratio >= 1.8:
        tv_label = "LATE"
    elif tv_norm >= 1.0: 
        tv_label = "CAUTION"
    elif tv_norm >= 0.5:
        tv_label = "NORMAL"
    else:
        tv_label = "PREMIUM"
        
    if tv_regime_shift > 1.5:
        tv_label = "SHIFT_RISK" if tv_label != "AVOID" else "AVOID"

    # classify_flow_regime (Phase 42)
    flow_regime = classify_flow_regime(df_exp, spot, total_volume, total_oi_chng)

    return {
        "total_gex": float(round(total_gex_net, 4)), 
        "total_gex_abs": float(round(total_gex_abs, 4)),
        "total_vex": float(round(total_vex, 4)),
        "total_cex": float(round(total_cex, 4)),
        "total_vega": float(round(total_vega, 4)),
        "total_theta": float(round(total_theta, 4)),
        "total_delta": float(round(total_delta, 4)),
        "total_volume": float(total_volume),
        "total_oi_chng": float(total_oi_chng),
        
        "gex_norm": float(round(total_gex_norm, 4)),
        "vega_norm": float(round(total_vega_norm, 4)),
        "theta_norm": float(round(total_theta_norm, 4)),
        "vex_norm": float(round(total_vex_norm, 4)),
        "cex_norm": float(round(total_cex_norm, 4)),
        
        "tv_ratio": float(round(tv_ratio, 4)),
        "tv_label": tv_label,
        "flow_regime_label": flow_regime,
        "gamma_flip_level": float(round(flip_level, 2)),
        "gamma_regime": "LONG GAMMA (Supportive)" if total_gex_net > 0 else "SHORT GAMMA (Volatile)",
        "vanna_bias": "Positive (Supportive)" if total_vex > 0 else "Negative (Destabilizing)",
        "charm_flow": "Bullish Drift" if total_cex > 0 else "Bearish Pressure",
        "vega_clusters": vega_clusters,
        "theta_clusters": theta_clusters,
        "intelligence": intelligence,
        "raw_exposures": df_exp
    }

def classify_flow_regime(df: pd.DataFrame, spot: float, total_vol: float, total_oi_chng: float) -> str:
    """
    Tiered Flow Classification using User Heuristics (0.1, 0.25, 0.4).
    Weights by Proximity to Spot and Exposure Significance.
    """
    if df.empty or "volume" not in df.columns:
        return "Passive"
        
    # ATM / Engagement Zone (Spot +/- 1.5% for tighter institutional signal)
    mask = (df["strike"] >= spot * 0.985) & (df["strike"] <= spot * 1.015)
    atm_df = df[mask]
    
    if atm_df.empty:
        # Fallback to nearest strikes if zone is empty
        df["dist"] = (df["strike"] - spot).abs()
        atm_df = df.sort_values("dist").head(4)
        
    atm_vol = atm_df["volume"].sum()
    atm_oi = atm_df["oi"].sum()
    
    # Calculate ratio (weighted towards ATM for higher fidelity)
    ratio = atm_vol / max(atm_oi, 1.0)
    
    # 1. Extreme Churn Check (Ratio > 0.4)
    if ratio > 0.4:
        return "Institutional Churn"
        
    # 2. High Activity Buildup / Liquidation (Ratio > 0.25)
    if ratio > 0.25:
        # Check if OI Change is also high (+ or -)
        atm_oi_chng = atm_df["oi_chng"].sum() if "oi_chng" in atm_df.columns else 0.0
        if abs(atm_oi_chng) / max(atm_oi, 1.0) > 0.05:
            return "Active Accumulation" if atm_oi_chng > 0 else "Active Liquidation"
        return "Directional Engagement"
        
    # 3. Normal Active (Ratio > 0.1)
    if ratio > 0.1:
        if abs(atm_oi_chng) > (atm_oi * 0.02):
            return "Directional Engagement"
        return "Tactical Positioning"
        
    # 4. Passive / Stale
    if ratio < 0.05:
        return "Passive / Stale"
        
    return "Neutral"

def analyze_strike_intelligence(df: pd.DataFrame, spot: float, flow_metrics: dict = None, mode: str = "Balanced"):
    """
    Orchestrate strike selection and risk zoning.
    """
    if df.empty:
        return {}
        
    high_risk_zones = detect_high_risk_zones(df)
    optimal = select_optimal_strikes(df, spot, flow_metrics=flow_metrics, mode=mode)
    
    return {
        "dns_zones": high_risk_zones,  # Preserving downstream dict key for UI compatibility
        "optimal_strikes": optimal
    }

def detect_high_risk_zones(df: pd.DataFrame):
    """
    Identify high-Vega clusters (Risk Exposure) and consolidate into zones.
    """
    p = STRIKE_INTEL_CONFIG["vega_percentile"]
    threshold = np.percentile(df["vega_exp"].abs(), p)
    
    high_vega_df = df[df["vega_exp"].abs() >= threshold].sort_values("strike")
    if high_vega_df.empty:
        return []
        
    zones = []
    current_zone = []
    gap_limit = STRIKE_INTEL_CONFIG["zone_merge_gap"]
    
    strikes = sorted(high_vega_df["strike"].unique())
    for s in strikes:
        if not current_zone:
            current_zone = [s]
        elif s - current_zone[-1] <= gap_limit:
            current_zone.append(s)
        else:
            zones.append([float(min(current_zone)), float(max(current_zone))])
            current_zone = [s]
            
    if current_zone:
        zones.append([float(min(current_zone)), float(max(current_zone))])
        
    # Consistency filter: Merge nearby zones even if gap is tight
    return zones

def get_strike_risk_profile(strike: float, df_exp: pd.DataFrame, dns_zones: list) -> str:
    """
    Tiered Risk assessment: LOW, MED, or HIGH.
    """
    if df_exp is None or df_exp.empty: return "UNKNOWN"
    
    # 1. Check if in HIGH risk zone (DNS)
    for z in dns_zones:
        if z[0] <= strike <= z[1]:
            return "HIGH"
            
    # 2. Check Percentile if not in hard zone (Phase 30 precise match)
    strike_row = df_exp.iloc[(df_exp["strike"] - strike).abs().argsort()[:1]]
    if strike_row.empty: return "LOW"
    
    # vega_exp: Volatility Exposure (Phase 30 Fix)
    val = strike_row["vega_exp"].abs().iloc[0]
    all_vals = df_exp["vega_exp"].abs()
    
    p70 = all_vals.quantile(0.7)
    p90 = all_vals.quantile(0.9)
    
    if val >= p90: return "HIGH"
    if val >= p70: return "MED"
    return "LOW"

def select_optimal_strikes(df: pd.DataFrame, spot: float, flow_metrics: dict = None, mode: str = "Balanced"):
    """
    Scoring Engine with Phase 28 Regime Conditioning & Execution Mode support.
    """
    work_df = df.copy()
    if "vega_exp" not in work_df.columns or "tex" not in work_df.columns:
        return None
        
    # Pre-filtering
    min_dist = spot * STRIKE_INTEL_CONFIG["min_distance_pct"]
    max_dist = spot * STRIKE_INTEL_CONFIG["max_distance_pct"]
    min_theta = STRIKE_INTEL_CONFIG["min_theta_m"]
    
    # Phase 30: Explicit scaling implementation
    work_df["tex_m"] = work_df["tex"].abs() / 1_000_000.0
    
    work_df = work_df[
        (abs(work_df["strike"] - spot) >= min_dist) & 
        (abs(work_df["strike"] - spot) <= max_dist) &
        (work_df["oi"] >= STRIKE_INTEL_CONFIG["min_oi"]) &
        (work_df["tex_m"] >= min_theta)
    ]
    
    if work_df.empty:
        # Fallback 1: Return Wall Strikes
        call_wall, put_wall = calculate_option_walls(df)
        return {
            "put": {"strike": float(put_wall), "score": 0.0},
            "call": {"strike": float(call_wall), "score": 0.0}
        }

    # 1. Normalization (Phase 30: Fixed to vega_exp)
    work_df["v_norm"] = work_df["vega_exp"].abs().rank(pct=True)
    t_min, t_max = work_df["tex"].abs().min(), work_df["tex"].abs().max()
    work_df["t_norm"] = (work_df["tex"].abs() - t_min) / (t_max - t_min) if t_max > t_min else 1.0
    
    # 2. Base Score
    alpha = STRIKE_INTEL_CONFIG["alpha"]
    work_df["score"] = work_df["t_norm"] - (alpha * work_df["v_norm"])
    
    # 2.1 Execution Mode Conditioning (Phase 28)
    if mode == "Defensive":
        work_df.loc[work_df["v_norm"] > 0.4, "score"] -= 0.3 # Penalize riskier strikes heavily
        work_df.loc[work_df["v_norm"] <= 0.2, "score"] += 0.1 # Favor deep OTM
    elif mode == "Aggressive":
        work_df.loc[work_df["v_norm"] <= 0.6, "score"] += 0.2 # Favor tighter strikes
    
    # 3. REGIME CONDITIONING (Phase 28)
    if flow_metrics:
        gex = flow_metrics.get("total_gex", 0)
        vega_total = flow_metrics.get("total_vega", 0)
        
        # negative gamma / trending -> penalize closeness (low v_norm strikes)
        if gex < 0:
            work_df.loc[work_df["v_norm"] < 0.5, "score"] -= 0.2
            
        # crowded short vol -> widen
        if vega_total > 300: # 300M INR scale
            work_df.loc[work_df["v_norm"] < 0.4, "score"] -= 0.15

    # 4. HIGH RISK ZONE PENALTY (Phase 32: Deep Penalty)
    high_risk_zones = detect_high_risk_zones(df)
    for z in high_risk_zones:
        # Probabilistic adjustment acting as strong veto for normal pairs
        work_df.loc[
            (work_df["strike"] >= z[0] - 50) & (work_df["strike"] <= z[1] + 50), 
            "score"
        ] -= 2.0
        
    # 4.5. MAX OI WALL BONUS (Phase 35)
    # Dealers heavily defend Max OI strikes (Call/Put Walls), granting them natural intrinsic resistance.
    call_wall, put_wall = calculate_option_walls(df)
    work_df.loc[work_df["strike"] == call_wall, "score"] += 1.5
    work_df.loc[work_df["strike"] == put_wall, "score"] += 1.5

    # 5. STRIKE SELECTION (Phase 28.3: Pair Optimization)
    puts = work_df[work_df["strike"] < spot].sort_values("score", ascending=False).head(10)
    calls = work_df[work_df["strike"] > spot].sort_values("score", ascending=False).head(10)
    
    res = {}
    if puts.empty or calls.empty:
        # Fallback 2: Mixed Fallback
        call_wall, put_wall = calculate_option_walls(df)
        if not puts.empty:
            res["put"] = {"strike": float(puts.iloc[0]["strike"]), "score": float(puts.iloc[0]["score"])}
        else:
            res["put"] = {"strike": float(put_wall), "score": 0.0}
            
        if not calls.empty:
            res["call"] = {"strike": float(calls.iloc[0]["strike"]), "score": float(calls.iloc[0]["score"])}
        else:
            res["call"] = {"strike": float(call_wall), "score": 0.0}
            
        return res

    # Exhaustive Pair Search
    best_pair = (puts.iloc[0], calls.iloc[0])
    sym_weight = STRIKE_INTEL_CONFIG["symmetry_weight"]
    
    # Initial best score
    p_init, c_init = puts.iloc[0], calls.iloc[0]
    p_dist_init = abs(p_init["strike"] - spot) / spot
    c_dist_init = abs(c_init["strike"] - spot) / spot
    # Phase 29: Remove *100 scaling to keep penalty in natural units (-0.7 to 1.0)
    best_pair_score = p_init["score"] + c_init["score"] - (sym_weight * abs(p_dist_init - c_dist_init))

    for pi in range(len(puts)):
        p_row = puts.iloc[pi]
        p_dist = abs(p_row["strike"] - spot) / spot
        for ci in range(len(calls)):
            c_row = calls.iloc[ci]
            c_dist = abs(c_row["strike"] - spot) / spot
            
            pair_score = p_row["score"] + c_row["score"] - (sym_weight * abs(p_dist - c_dist))
            
            if pair_score > best_pair_score:
                best_pair_score = pair_score
                best_pair = (p_row, c_row)

    res["put"] = {"strike": float(best_pair[0]["strike"]), "score": float(best_pair[0]["score"])}
    res["call"] = {"strike": float(best_pair[1]["strike"]), "score": float(best_pair[1]["score"])}
    
    return res

def classify_greek_market_state(metrics):
    """
    Classify market state based on Million INR (M) units.
    """
    gamma_net = metrics.get("total_gex", 0)
    gamma_abs = metrics.get("total_gex_abs", 0)
    theta = metrics.get("total_theta", 0)
    vega = metrics.get("total_vega", 0)
    
    # Thresholds in INR Million (M)
    # GEX > 5000M (5B INR) is strongly supportive
    # VEGA > 400M is high vol sensitivity
    GEX_SUPPORTIVE = 5000.0 
    VEGA_HIGH = 400.0
    
    if gamma_abs > GEX_SUPPORTIVE and theta < 0: # Note: absolute Theta is strictly negative
        state = "Stable / Income Favorable"
        bias = "Short Vol / Neutral"
    elif gamma_net < 0 and vega > VEGA_HIGH:
        state = "Vol Expansion Risk"
        bias = "Long Vol / Hedges Required"
    elif vega > VEGA_HIGH:
        state = "High-Vol Sensitivity"
        bias = "Reduced Size / Passive"
    else:
        state = "Neutral Equilibrium"
        bias = "Standard Positioning"
        
    return {
        "state": state,
        "bias": bias,
        "decay_regime": "Positive Carry" if theta > 0 else "Negative Carry",
        "vol_bias": "Long Vega" if vega > 0 else "Short Vega"
    }


def calculate_option_walls(df: pd.DataFrame) -> tuple[float, float]:
    """
    Find strikes with max OI. Robust case-insensitive comparison (Phase 29.2).
    """
    if df.empty: return 0.0, 0.0
    df_copy = df.copy()
    df_copy["type_lower"] = df_copy["type"].astype(str).str.lower()
    
    call_df = df_copy[df_copy["type_lower"] == "call"]
    put_df = df_copy[df_copy["type_lower"] == "put"]
    
    call_wall = 0.0
    if not call_df.empty:
        # idxmax() returns the first index of the max value. 
        # Using .loc[idx] can return a series if indices are non-unique.
        full_row = call_df.loc[call_df["oi"].idxmax()]
        call_wall = full_row["strike"].iloc[0] if isinstance(full_row, pd.DataFrame) else full_row["strike"]
        
    put_wall = 0.0
    if not put_df.empty:
        full_row = put_df.loc[put_df["oi"].idxmax()]
        put_wall = full_row["strike"].iloc[0] if isinstance(full_row, pd.DataFrame) else full_row["strike"]
        
    return float(call_wall), float(put_wall)

# ==================== CSV PARSING LAYER ====================

def parse_nse_option_chain_csv(file_path: Path) -> tuple[pd.DataFrame, str]:
    """
    Robustly parse the manually downloaded NSE Option Chain CSV.
    Handles dynamic column indexing and fallback expiry from filename.
    """
    try:
        file_name = file_path.name
        with open(file_path, "r") as f:
            lines = f.readlines()
            
        header_row_idx = -1
        expiry_date_str = "Unknown"
        
        # 1. Attempt internal expiry extraction
        for i, line in enumerate(lines):
            clean_line = line.strip()
            if "expiry date" in clean_line.lower():
                import re
                match = re.search(r"(\d{2}-[A-Za-z]{3}-\d{4})", clean_line)
                if match:
                    expiry_date_str = match.group(1)
            
            # Identify the actual table header (Strike, STRIKE, STRIKE PRICE etc)
            if "strike" in clean_line.lower() and "oi" in clean_line.lower():
                header_row_idx = i
                break
        
        # 2. Fallback to filename for expiry
        if expiry_date_str == "Unknown":
            import re
            # look for 27-Mar-2026 or 30-Mar-2026 patterns
            match = re.search(r"(\d{2}-[A-Za-z]{3}-\d{4})", file_name)
            if match:
                expiry_date_str = match.group(1)

        if header_row_idx == -1:
            return pd.DataFrame(), expiry_date_str

        # Parse the data section
        import io
        idx = int(header_row_idx)
        data_body = "".join(lines[idx:])
        df = pd.read_csv(io.StringIO(data_body))
        
        # 3. Dynamic Column Identification
        cols = [str(c).upper().strip() for c in df.columns]
        
        # Find Strike column
        strike_col_idx = -1
        for i, c in enumerate(cols):
            if "STRIKE" in c:
                strike_col_idx = i
                break
        
        if strike_col_idx == -1:
            return pd.DataFrame(), expiry_date_str
            
        # Find all OI and IV and LTP indices
        # Pandas renames duplicates to OI.1, OI.2 or IV.1, IV.2
        oi_indices = [i for i, c in enumerate(cols) if c == "OI" or c.startswith("OI.")]
        iv_indices = [i for i, c in enumerate(cols) if c == "IV" or c.startswith("IV.")]
        ltp_indices = [i for i, c in enumerate(cols) if c == "LTP" or c.startswith("LTP.")]
        
        if not oi_indices or not iv_indices:
            return pd.DataFrame(), expiry_date_str
            
        # Call usually left of Strike (smaller index)
        # Put usually right of Strike (larger index)
        ce_oi_idx, pe_oi_idx = -1, -1
        ce_iv_idx, pe_iv_idx = -1, -1
        ce_ltp_idx, pe_ltp_idx = -1, -1
        
        if strike_col_idx == 0 and len(oi_indices) >= 2:
            # Sensibull layout: Strike is at left, CE is first set, PE is second set
            ce_oi_idx, pe_oi_idx = oi_indices[0], oi_indices[-1]
            if len(iv_indices) >= 2: ce_iv_idx, pe_iv_idx = iv_indices[0], iv_indices[-1]
            if len(ltp_indices) >= 2: ce_ltp_idx, pe_ltp_idx = ltp_indices[0], ltp_indices[-1]
        else:
            # Traditional NSE layout
            for idx in oi_indices:
                if idx < strike_col_idx: ce_oi_idx = idx
                if idx > strike_col_idx: pe_oi_idx = idx
                
            for idx in iv_indices:
                if idx < strike_col_idx: ce_iv_idx = idx
                if idx > strike_col_idx: pe_iv_idx = idx
                
            for idx in ltp_indices:
                if idx < strike_col_idx: ce_ltp_idx = idx
                if idx > strike_col_idx: pe_ltp_idx = idx
                
        processed = []
        for _, row in df.iterrows():
            try:
                # Strike
                val = str(row.iloc[strike_col_idx]).replace(",", "").strip()
                if not val or val.lower() == "nan" or val == "-": continue
                strike = float(val)
                
                # Calls (CE)
                c_oi, c_iv, c_ltp = 0.0, 0.0, 0.0
                if ce_oi_idx != -1:
                    c_oi = float(str(row.iloc[ce_oi_idx]).replace(",", "").replace("-", "0") or 0)
                if ce_iv_idx != -1:
                    c_iv = float(str(row.iloc[ce_iv_idx]).replace(",", "").replace("-", "0") or 0)
                if ce_ltp_idx != -1:
                    c_ltp = float(str(row.iloc[ce_ltp_idx]).replace(",", "").replace("-", "0") or 0)
                
                # Puts (PE)
                p_oi, p_iv, p_ltp = 0.0, 0.0, 0.0
                if pe_oi_idx != -1:
                    p_oi = float(str(row.iloc[pe_oi_idx]).replace(",", "").replace("-", "0") or 0)
                if pe_iv_idx != -1:
                    p_iv = float(str(row.iloc[pe_iv_idx]).replace(",", "").replace("-", "0") or 0)
                if pe_ltp_idx != -1:
                    p_ltp = float(str(row.iloc[pe_ltp_idx]).replace(",", "").replace("-", "0") or 0)
                
                # Capture Institutional Greeks if present
                c_data = {"strike": strike, "type": "call", "oi": c_oi, "iv": c_iv, "ltp": c_ltp}
                p_data = {"strike": strike, "type": "put", "oi": p_oi, "iv": p_iv, "ltp": p_ltp}
                
                # Check for Sensibull columns in the original CSV row
                if "CE_GAMMA" in cols: c_data["sensi_gamma"] = float(row.get("CE_GAMMA", 0))
                if "CE_DELTA" in cols: c_data["sensi_delta"] = float(row.get("CE_DELTA", 0))
                if "CE_THETA" in cols: c_data["sensi_theta"] = float(row.get("CE_THETA", 0))
                if "CE_VEGA" in cols: c_data["sensi_vega"] = float(row.get("CE_VEGA", 0))

                if "PE_GAMMA" in cols: p_data["sensi_gamma"] = float(row.get("PE_GAMMA", 0))
                if "PE_DELTA" in cols: p_data["sensi_delta"] = float(row.get("PE_DELTA", 0))
                if "PE_THETA" in cols: p_data["sensi_theta"] = float(row.get("PE_THETA", 0))
                if "PE_VEGA" in cols: p_data["sensi_vega"] = float(row.get("PE_VEGA", 0))

                processed.append(c_data)
                processed.append(p_data)
            except Exception:
                continue
                
        return pd.DataFrame(processed), expiry_date_str
    except Exception as e:
        logger.error(f"Error parsing NSE CSV {file_path}: {e}")
        return pd.DataFrame(), ""

def load_latest_option_chain_csv(filename: str | None = None) -> tuple[pd.DataFrame, str, datetime, str]:
    """
    Find and load a specific CSV or the intelligently 'Nearest Active' one.
    """
    if filename:
        target_file = OPTION_CHAIN_DIR / filename
        if target_file.exists():
            df, expiry = parse_nse_option_chain_csv(target_file)
            mtime = datetime.fromtimestamp(target_file.stat().st_mtime)
            return df, filename, mtime, expiry
            
    files = list(OPTION_CHAIN_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame(), "", None, ""
    
    # Pre-parse meta to find the dates
    date_pattern = re.compile(r"(\d{1,2}-[a-zA-Z]{3}-\d{4})")
    
    chains = []
    for f in files:
        expiry = "Unknown"
        try:
            with open(f, "r") as src:
                headline = src.readline()
                if "EXPIRY DATE:" in headline:
                    expiry = headline.split(":")[1].strip()
                else:
                    # Fallback: Extract from filename
                    match = date_pattern.search(f.name)
                    if match:
                        expiry = match.group(1)
        except: pass
        chains.append({"file": f, "expiry": expiry})

    # Sort chronological
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    def date_sort(c):
        dt = _parse_nse_date(c["expiry"])
        return dt if dt else datetime.max
        
    chains.sort(key=date_sort)
    
    # Pick first future/current, else finest mtime
    target_chain = None
    for c in chains:
        dt = _parse_nse_date(c["expiry"])
        if dt and dt >= today:
            target_chain = c["file"]
            break
        
    if not target_chain:
        # Fallback to newest modification if no future dates found
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        target_chain = files[0]
    
    df, expiry = parse_nse_option_chain_csv(target_chain)
    mtime = datetime.fromtimestamp(target_chain.stat().st_mtime)
    
    return df, target_chain.name, mtime, expiry

def list_available_option_chains() -> list[dict]:
    """
    Scans data/option_chain/ for NDE-standard CSVs only (sensi/v3 converted files).
    Excludes raw Sensibull downloads (NIFTY_*_option_chain_*.csv).
    De-duplicates by expiry, preferring sensi over v3 over other files.
    """
    if not OPTION_CHAIN_DIR.exists():
        return []

    date_pattern = re.compile(r"(\d{1,2}-[a-zA-Z]{3}-\d{4})")

    # Only include files that have the NDE header format (not raw Sensibull downloads)
    by_expiry: dict[str, dict] = {}

    for f in OPTION_CHAIN_DIR.glob("*.csv"):
        # Skip raw Sensibull downloads — they haven't been converted yet
        if re.match(r"NIFTY_\d{4}-\d{2}-\d{2}_option_chain", f.name):
            continue
        # Skip metadata json / DS_Store etc
        if not f.suffix == ".csv":
            continue

        expiry = None
        try:
            with open(f, "r") as src:
                headline = src.readline()
                if "EXPIRY DATE:" in headline:
                    expiry = headline.split(":")[1].strip()
                else:
                    match = date_pattern.search(f.name)
                    if match:
                        expiry = match.group(1)
        except Exception:
            continue

        if not expiry or not date_pattern.match(expiry):
            continue

        # Freshness Check (Phase 42): Only include 'sensi' files if updated in last 24h
        if "sensi" in f.name:
            age_hrs = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600
            if age_hrs > 24:
                continue

        # Priority: sensi > v3 > anything else
        priority = 0 if "sensi" in f.name else (1 if "v3" in f.name else 2)
        if expiry not in by_expiry or priority < by_expiry[expiry]["_priority"]:
            by_expiry[expiry] = {
                "filename": f.name,
                "expiry":   expiry,
                "type":     nde_expiry_helper.get_expiry_type(expiry),
                "mtime":    datetime.fromtimestamp(f.stat().st_mtime),
                "_priority": priority,
            }

    chains = list(by_expiry.values())
    for c in chains:
        c.pop("_priority", None)

    # Sort chronologically
    try:
        chains.sort(key=lambda x: _parse_nse_date(x["expiry"]) or datetime.max)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for c in chains:
            dt = _parse_nse_date(c["expiry"])
            if dt and dt >= today:
                c["is_near_active"] = True
                break
    except Exception:
        pass

    return chains

def ingest_live_option_chain_v3(symbol: str = "NIFTY", current_atr: float = 250.0, aggressive: bool = False) -> dict:
    """
    Institutional v3 Ingestion:
    1. Fetches full chain via NSEv3Client.
    2. Shards only Weekly Near, Weekly Next, Monthly Near.
    3. Persists results + Metadata sidecars.
    """
    # Phase 43: Sensibull-First Institutional Resilience
    # If NSE API is failing, check if we have a fresh Sensibull extraction already available.
    # We prioritize 'sensi' files as they have high-fidelity Greeks.
    sensi_files = list(OPTION_CHAIN_DIR.glob(f"option-chain-ED-sensi-{symbol}-*.csv"))
    if sensi_files:
        latest_sensi = max(sensi_files, key=lambda f: f.stat().st_mtime)
        mtime = datetime.fromtimestamp(latest_sensi.stat().st_mtime)
        # If 'fresh' (last 1 hour), we can technically treat this as our 'Live' fetch result
        if (datetime.now() - mtime).total_seconds() < 3600:
            logger.info(f"🦅 Sensibull-First: Using fresh override {latest_sensi.name}")
            # We still want to try the API below for other expiries, but we know we have a solid baseline.
    
    client = NSEv3Client()
    raw_json = client.fetch_chain(symbol)
    
    if not raw_json or "records" not in raw_json:
        # Fallback Logic: If API fails but we have a sensi override, report partial success/fallback
        if sensi_files:
            logger.warning("⚠️ NSE API Failed. Falling back to latest Sensibull extraction.")
            return {"status": "success", "files": [f.name for f in sensi_files], "note": "Sensibull Fallback"}
        
        logger.error("❌ v3 Ingestion failed: No data fetched and no Sensibull fallback.")
        return {"status": "error", "files": []}
        
    # Get all available expiries
    expiries = raw_json["records"].get("expiryDates", [])
    if not expiries:
        return {"status": "error", "files": []}
        
    full_df, spot = parse_v3_chain(raw_json)
    
    # Identify Shards
    weekly_near = expiries[0]
    weekly_next = expiries[1] if len(expiries) > 1 else None
    monthly_near = next((e for e in expiries if nde_expiry_helper.is_monthly_expiry(e)), expiries[-1])
    
    shards = filter(None, [weekly_near, weekly_next, monthly_near])
    saved_files = []
    
    for exp in shards:
        df_exp = full_df[full_df["expiry"] == exp].copy()
        
        # Apply Volatility-Dynamic Cleaning
        df_clean = clean_chain(df_exp, spot, atr=current_atr, aggressive=aggressive)
        
        # Meta Preservation
        meta = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expiry": exp,
            "type": nde_expiry_helper.get_expiry_type(exp),
            "spot_at_fetch": spot,
            "atr_at_cleaning": current_atr,
            "aggressive_mode": aggressive
        }
        
        # Save CSV + JSON Metadata
        fname = f"option-chain-ED-v3-{symbol}-{exp}.csv"
        mname = f"option-chain-ED-v3-{symbol}-{exp}_meta.json"
        
        fpath = OPTION_CHAIN_DIR / fname
        mpath = OPTION_CHAIN_DIR / mname
        
        # Legacy-compatible CSV save (header line for parser)
        with open(fpath, "w") as f:
            f.write(f"EXPIRY DATE: {exp}\n")
            f.write(f"VERSION: v3 Institutional\n")
            
        # Transform back to the NSE-Portal style the existing parser expects
        pivoted = df_clean.rename(columns={
            "call_oi": "OI", "call_iv": "IV", "call_ltp": "LTP",
            "strike": "STRIKE",
            "put_ltp": "LTP.1", "put_iv": "IV.1", "put_oi": "OI.1"
        })
        pivoted.to_csv(fpath, mode="a", index=False)
        
        with open(mpath, "w") as f:
            json.dump(meta, f, indent=4)
            
        saved_files.append(fname)
        
        # Also update the Master Snapshot for Fallback (Default to Near Weekly)
        if exp == weekly_near:
            master_csv = OPTION_CHAIN_DIR / "last_successful_nifty.csv"
            master_meta = OPTION_CHAIN_DIR / "last_successful_nifty_meta.json"
            
            # Using copy to avoid file lock issues in some OS
            import shutil
            shutil.copy(fpath, master_csv)
            shutil.copy(mpath, master_meta)
            logger.info("📡 Master v3 Snapshot Updated.")

    return {"status": "success", "files": saved_files, "spot": spot}

def load_nifty_v3_data(filename: str | None = None) -> tuple[pd.DataFrame, str, str, dict, str]:
    """
    Deterministic loading with LIVEv3/CACHED status.
    Returns: (DataFrame, Expiry, SourceLabel, Metadata, Filename)
    """
    # 1. Try Live/Specific file
    df, fname, mtime, expiry = load_latest_option_chain_csv(filename)
    source = "LIVEv3" if "v3" in fname else "MANUAL-NSE"
    
    # 2. Fallback to Master Snapshot
    if df.empty:
        master_csv = OPTION_CHAIN_DIR / "last_successful_nifty.csv"
        if master_csv.exists():
            df, expiry = parse_nse_option_chain_csv(master_csv)
            fname = "last_successful_nifty.csv"
            mtime = master_csv.stat().st_mtime
            source = "CACHED"
        else:
            return pd.DataFrame(), "", "OFFLINE", {}, ""
            
    # 3. Load Metadata Sidecar
    meta_name = fname.replace(".csv", "_meta.json")
    meta_path = OPTION_CHAIN_DIR / meta_name
    meta = {}
    
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except:
            pass

    # Source-mode priority
    if meta and "source_mode" in meta:
        source = meta["source_mode"]
    
    if not meta and mtime:
        # Fallback to file mtime if sidecar metadata is missing or corrupt
        from datetime import datetime
        dt_obj = mtime if isinstance(mtime, datetime) else datetime.fromtimestamp(mtime)
        meta = {
            "timestamp": dt_obj.strftime("%d-%b-%Y %H:%M:%S"),
            "spot_at_fetch": None,
            "source_file": fname,
            "source_mode": source,
            "validation_flags": []
        }
            
    return df, expiry, source, meta, fname

# ==================== TERM STRUCTURE (MULTI-EXPIRY) ====================

def compute_term_structure(symbol: str = "NIFTY", spot: float = None) -> dict:
    """
    Institutional Multi-Expiry Analysis V2 (Hardened):
    1. Scans data/option_chain/ for active expiries.
    2. Batch-computes Greeks with ATM IV extraction.
    3. Calculates Flip Velocity and Delta Migrations (Snap-Persistence).
    4. Normalizes metrics by LOT and scales thresholds by IV regime.
    """
    chains = list_available_option_chains()
    if not chains:
        return {}
    
    # Final Week absolute carry safety
    # spot param to reduce redundant fetch
        
    # Order by DTE
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    chains.sort(key=lambda x: _parse_nse_date(x["expiry"]) or datetime.max)
    
    # Filter for Future/Current only
    active_chains = [c for c in chains if (_parse_nse_date(c["expiry"]) or datetime.min) >= today]
    
    # Limit to next 5 by default for performance
    active_chains = active_chains[:5]
    
    term_data = {}
    
    # Load previous snapshot for Migration Tracking
    snap_path = Path("data/term_structure_snap.json")
    old_snap = {}
    if snap_path.exists():
        try:
            old_snap = json.loads(snap_path.read_text())
        except: pass
    
    # We need a spot price. 
    if spot is None:
        try:
            import data_fetch
            n_df = data_fetch.batch_download(["^NSEI"], period="1d").get("^NSEI")
            spot = n_df["Close"].iloc[-1]
        except:
            spot = 22000.0 # Worst case fallback
            
    for c in active_chains:
        expiry = c["expiry"]
        filename = c["filename"]
        
        # Load Raw
        df_raw, _ = parse_nse_option_chain_csv(OPTION_CHAIN_DIR / filename)
        if df_raw.empty: continue
        
        # Pre-process for Greeks
        exp_dt = _parse_nse_date(expiry)
        if not exp_dt: continue
        dte = max(0.01, (exp_dt - datetime.now()).total_seconds() / 86400.0)
        df_raw["t_days"] = dte
            
        metrics = compute_option_flow_exposures(spot, df_raw)
        
        # V2: Extract ATM IV (Strike closest to spot)
        atm_strike = round(spot / 50) * 50
        atm_rows = df_raw[df_raw["strike"] == atm_strike]
        if not atm_rows.empty:
            c_iv = atm_rows[atm_rows["type"] == "call"]["iv"].iloc[0] if not atm_rows[atm_rows["type"] == "call"].empty else 0.0
            p_iv = atm_rows[atm_rows["type"] == "put"]["iv"].iloc[0] if not atm_rows[atm_rows["type"] == "put"].empty else 0.0
            
            if c_iv > 0 and p_iv > 0:
                avg_iv = (c_iv + p_iv) / 2.0
            else:
                avg_iv = max(c_iv, p_iv) if (c_iv > 0 or p_iv > 0) else 15.0
                
            atm_iv = float(avg_iv)
        else:
            atm_iv = 15.0 # Fallback
            
        # V2: Flip Context
        flip = metrics.get("gamma_flip_level")
        flip_dist = abs(spot - flip) / spot * 100 if flip else 0.0
        
        # Migration Delta Tracking
        delta_gex = 0.0
        delta_flip = 0.0
        if expiry in old_snap:
            delta_gex = metrics["total_gex"] - old_snap[expiry].get("gex_net", metrics["total_gex"])
            old_flip = old_snap[expiry].get("flip")
            if old_flip and flip:
                delta_flip = flip - old_flip
        
        # V2: Adaptive Sensitivity scaling based on IV (Normalized to 15.0 baseline)
        iv_adj = max(0.7, min(1.3, atm_iv / 15.0))
        
        # UI Hydration (Phase 41 Consistency)
        ui_display = {
            "gex_net": format_institutional_metric(metrics["total_gex"], "Cr"),
            "gex_net_norm": f"{metrics['total_gex']/LOT/1_000_000.0:.1f} M/lot",
            "delta_gex": f"({'+' if delta_gex > 0 else ''}{format_institutional_metric(delta_gex, 'Cr')})" if abs(delta_gex) > 100_000 else ""
        }
        
        term_data[expiry] = {
            "dte": int(dte),
            "is_monthly": nde_expiry_helper.is_monthly_expiry(expiry),
            "spot": spot,
            "atm_iv": round(atm_iv, 2),
            "iv_adj": round(iv_adj, 2),
            "ui_display": ui_display,
            
            # Raw Metrics
            "gex_abs": metrics["total_gex_abs"],
            "gex_net": metrics["total_gex"],
            "vega": metrics["total_vega"],
            "theta": metrics["total_theta"],
            
            # Migration Deltas
            "delta_gex": delta_gex,
            "delta_flip": delta_flip,
            
            # Lot-Normalized (Logic Invariant)
            "gex_abs_norm": metrics["total_gex_abs"] / LOT,
            "gex_net_norm": metrics["total_gex"] / LOT,
            "vega_norm": metrics["total_vega"] / LOT,
            "theta_norm": metrics["total_theta"] / LOT,
            
            "flip": flip,
            "flip_dist": round(flip_dist, 2),
            "state": "Unknown",
            "filename": filename,
            "raw_exposures": metrics["raw_exposures"]
        }
        
        # Apply State Classification (Adaptive)
        term_data[expiry]["state"] = classify_term_structure(term_data[expiry], iv_adj)
        
    # Snap-Persistence: Save for next intraday comparison
    try:
        # Create a serializable version (remove non-JSON parts like raw_exposures if existed)
        snap_to_save = {}
        for k, v in term_data.items():
            snap_to_save[k] = {ik: iv for ik, iv in v.items() if ik != "raw_exposures"}
        snap_path.write_text(json.dumps(
            snap_to_save, 
            indent=2,
            default=lambda x: float(x) if hasattr(x, '__float__') else str(x)
        ))
    except: pass
    
    return term_data

def classify_term_structure(row: dict, iv_adj: float = 1.0) -> str:
    """
    Deterministic State Classification using Lot-Invariant Thresholds.
    Adjusted by IV regime: High IV requires more GEX for 'Stability'.
    """
    # GEX-based logic
    gex_net_norm = row["gex_net_norm"]
    gex_abs_norm = row["gex_abs_norm"]
    
    # Baseline Thresholds (Normalized to 1 Lot, in Millions-of-INR)
    # v3 Alignment: 15.0 represents 15M per lot.
    BASE_STABLE = 15.0  
    BASE_ANCHOR = 12.0
    
    # Apply IV Adjustment (Regime Scaling)
    gex_stable_adj = BASE_STABLE * iv_adj
    gex_anchor_adj = BASE_ANCHOR * iv_adj
    
    if row["is_monthly"] and gex_abs_norm > gex_anchor_adj:
        return "Anchor"
        
    if gex_abs_norm > gex_stable_adj and gex_net_norm >= 0:
        return "Stable"
        
    if gex_net_norm < 0:
        return "Fragile"
        
    return "Neutral"
