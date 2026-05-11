import numpy as np
import pandas as pd
import math
from scipy.stats import norm
from typing import Tuple, Dict, Any, List
from nde_schema import FlowMetrics

# Numerical Constants
EPS = 1e-10
DAYS_PER_YEAR = 365.0
MILLION = 1_000_000.0

def _norm_cdf(x: np.ndarray) -> np.ndarray:
    return norm.cdf(x)

def _norm_pdf(x: np.ndarray) -> np.ndarray:
    return norm.pdf(x)

def compute_all_greeks(
    df: pd.DataFrame, 
    spot: float, 
    r: float = 0.07, 
    q: float = 0.0, 
    lot_size: int = 75
) -> pd.DataFrame:
    """
    Fused Greek Kernel (Carmack Optimization).
    Computes all 1st and 2nd order Greeks in a single vectorized pass,
    sharing intermediate computations (d1, d2, exp_terms) to minimize overhead.
    """
    if df.empty:
        return pd.DataFrame()

    # Pre-extract vectors for memory locality
    K = df["strike"].values.astype(float)
    T = df["t_days"].values.astype(float) / DAYS_PER_YEAR
    IV = df["iv"].values.astype(float) / 100.0
    OI = df["oi"].values.astype(float)
    types = df["type"].values
    is_call = (types == "call")
    
    # Shared variables
    sqrt_T = np.sqrt(T)
    log_SK = np.log(np.maximum(spot / K, EPS))
    vol_sqrt_T = IV * sqrt_T + EPS
    
    # Core BS Components
    d1 = (log_SK + (r - q + 0.5 * IV**2) * T) / vol_sqrt_T
    d2 = d1 - vol_sqrt_T
    
    N_d1 = _norm_cdf(d1)
    N_d2 = _norm_cdf(d2)
    n_d1 = _norm_pdf(d1)
    
    exp_qT = np.exp(-q * T)
    exp_rT = np.exp(-r * T)
    
    # 1. Primary Greeks
    delta = np.where(is_call, exp_qT * N_d1, exp_qT * (N_d1 - 1.0))
    gamma = (exp_qT * n_d1) / (spot * vol_sqrt_T)
    vega = (spot * exp_qT * n_d1 * sqrt_T) / 100.0
    
    # Theta
    term1 = -(spot * exp_qT * n_d1 * IV) / (2 * sqrt_T + EPS)
    theta_call = (term1 - q * spot * exp_qT * N_d1 - r * K * exp_rT * N_d2) / DAYS_PER_YEAR
    theta_put = (term1 + q * spot * exp_qT * _norm_cdf(-d1) + r * K * exp_rT * _norm_cdf(-d2)) / DAYS_PER_YEAR
    theta = np.where(is_call, theta_call, theta_put)
    
    # 2. Cross Greeks (Vanna/Charm)
    vanna = -exp_qT * n_d1 * d2 / (IV + EPS)
    
    term_vc = (r - q) / vol_sqrt_T - d2 / (2 * T + EPS)
    charm_call = -exp_qT * (n_d1 * term_vc - q * N_d1)
    charm_put = exp_qT * (n_d1 * term_vc - q * _norm_cdf(-d1))
    charm = np.where(is_call, charm_call, charm_put)
    
    # 3. Notional Exposures
    # We use "Million INR" as the canonical unit for flow metrics
    flow_sign = np.where(is_call, 1.0, -1.0)
    
    gex_net = (gamma * OI * spot * flow_sign) / MILLION
    dex_net = (delta * OI * spot) / MILLION
    vex_net = (vega * OI) / MILLION
    tex_net = (theta * OI) / MILLION
    van_net = (vanna * OI * flow_sign) / MILLION
    cha_net = (charm * OI) / MILLION
    
    return pd.DataFrame({
        "strike": K, "type": types, "oi": OI, "iv": IV * 100.0, "ltp": df["ltp"].values,
        "delta": delta, "gamma": gamma, "vega": vega, "theta": theta, 
        "vanna": vanna, "charm": charm,
        "gex": gex_net, "dex": dex_net, "vex": vex_net, "tex": tex_net,
        "van": van_net, "cha": cha_net, "t_days": T * 365.0
    })

def compute_max_pain_vectorized(df: pd.DataFrame) -> float:
    """
    O(N) Vectorized Max Pain (Carmack Optimization).
    Uses cumulative sums to compute total loss curves for all strikes in a single pass.
    """
    if df.empty:
        return 0.0
        
    # Standardize data: unique strikes sorted ascending
    strikes = np.sort(df["strike"].unique())
    calls = df[df["type"] == "call"].groupby("strike")["oi"].sum().reindex(strikes, fill_value=0).values
    puts = df[df["type"] == "put"].groupby("strike")["oi"].sum().reindex(strikes, fill_value=0).values
    
    # Call Loss: sum_{K <= X} (X - K) * OI_K = X * sum(OI_K) - sum(K * OI_K)
    c_oi_sum = np.cumsum(calls)
    c_koi_sum = np.cumsum(calls * strikes)
    call_loss = strikes * c_oi_sum - c_koi_sum
    
    # Put Loss: sum_{K >= X} (K - X) * OI_K = sum(K * OI_K) - X * sum(OI_K) (reverse cumsum)
    p_oi_sum = np.cumsum(puts[::-1])[::-1]
    p_koi_sum = np.cumsum((puts * strikes)[::-1])[::-1]
    put_loss = p_koi_sum - strikes * p_oi_sum
    
    total_loss = call_loss + put_loss
    return float(strikes[np.argmin(total_loss)])

def calculate_option_walls(df_exp: pd.DataFrame) -> Tuple[float, float, float, float]:
    """Identifies the primary and secondary structural walls in the option chain."""
    if df_exp.empty:
        return 0.0, 0.0, 0.0, 0.0
        
    c_walls = df_exp[df_exp["type"] == "call"].groupby("strike")["gex"].sum().sort_values(ascending=False).head(2)
    p_walls = df_exp[df_exp["type"] == "put"].groupby("strike")["gex"].sum().sort_values(ascending=True).head(2)
    
    return (
        float(c_walls.index[0] if len(c_walls) > 0 else 0.0),
        float(p_walls.index[0] if len(p_walls) > 0 else 0.0),
        float(c_walls.index[1] if len(c_walls) > 1 else 0.0),
        float(p_walls.index[1] if len(p_walls) > 1 else 0.0)
    )

def detect_high_risk_zones(df_exp: pd.DataFrame) -> List[List[float]]:
    """Identifies strikes with extreme exposure density (Dealer Danger Zones)."""
    if df_exp.empty: return []
    top_gex = df_exp.groupby("strike")["gex"].sum().abs().sort_values(ascending=False).head(5)
    return [[float(s), float(s)] for s in top_gex.index]

def analyze_strike_intelligence(df_exp: pd.DataFrame, spot: float, flow_metrics: FlowMetrics) -> Dict[str, Any]:
    """Aggregates high-fidelity signals for the decision layer."""
    return {
        "dns_zones": detect_high_risk_zones(df_exp),
        "max_pain": compute_max_pain_vectorized(df_exp),
        "pcr_oi": flow_metrics.pcr_oi,
        "pcr_vol": 0.0 # Placeholder
    }

def calculate_flow_metrics(df_exp: pd.DataFrame, spot: float) -> FlowMetrics:
    """Aggregates per-strike exposures into a typed FlowMetrics object."""
    if df_exp.empty:
        return FlowMetrics()
        
    # Net GEX: directional sum
    total_gex = df_exp["gex"].sum()
    
    # Abs GEX: sum of |per-strike net|
    total_gex_abs = df_exp.groupby("strike")["gex"].sum().abs().sum()
    
    # Walls
    c_wall, p_wall, sec_c, sec_p = calculate_option_walls(df_exp)
    
    # PCR Calculation
    c_oi = df_exp[df_exp["type"] == "call"]["oi"].sum()
    p_oi = df_exp[df_exp["type"] == "put"]["oi"].sum()
    pcr_oi = p_oi / (c_oi + EPS)
    
    # Expected Move (Straddle Proxy)
    atm_df = df_exp[np.abs(df_exp["strike"] - spot) <= 100]
    straddle = atm_df["ltp"].sum() if not atm_df.empty else 0.0
    
    # ATM OI Share
    band_half = 200 # +/- 200 points
    atm_band_df = df_exp[(df_exp["strike"] >= spot - band_half) & (df_exp["strike"] <= spot + band_half)]
    atm_oi_share = (atm_band_df["oi"].sum() / max(df_exp["oi"].sum(), 1.0)) * 100.0
    
    # TV Ratio (Theta/Vega Carry Ratio)
    total_vega = df_exp["vex"].sum()
    total_theta = df_exp["tex"].sum()
    t_days = df_exp["t_days"].iloc[0] if "t_days" in df_exp.columns else 3.0
    vega_eff = max(total_vega, 1e-4)
    tv_raw = (abs(total_theta) / math.sqrt(t_days + 1)) / vega_eff
    tv_ratio = min(tv_raw, 10.0)
    
    # TV Label
    if tv_ratio >= 2.5: tv_label = "AVOID"
    elif tv_ratio >= 1.8: tv_label = "LATE"
    elif tv_ratio >= 1.0: tv_label = "CAUTION"
    elif tv_ratio >= 0.5: tv_label = "PREMIUM"
    else: tv_label = "DISCOUNT"
    
    # ── Gamma Flip Level (Zero-Crossing Detection) ──────────────────
    # Net GEX per strike, then find zero-crossing nearest to spot
    df_net = df_exp.groupby("strike")["gex"].sum().sort_index().reset_index()
    df_net.columns = ["strike", "net_gex"]
    
    # Search window: ±2.5% from spot (approximately 2.5 ATR for NIFTY-scale indices)
    window_pct = 0.025
    window_min = spot * (1 - window_pct)
    window_max = spot * (1 + window_pct)
    
    flip_level = 0.0
    crossovers = []
    for i in range(len(df_net) - 1):
        x0, y0 = df_net.iloc[i]["strike"], df_net.iloc[i]["net_gex"]
        x1, y1 = df_net.iloc[i+1]["strike"], df_net.iloc[i+1]["net_gex"]
        if x0 < window_min or x0 > window_max:
            continue
        if (y0 * y1) < 0:  # Sign change = zero-crossing
            cross = x0 + (-y0) * (x1 - x0) / (y1 - y0 + EPS)
            crossovers.append({"level": cross, "dist": abs(cross - spot)})
    
    if crossovers:
        flip_level = min(crossovers, key=lambda x: x["dist"])["level"]
    elif not df_net.empty:
        # Fallback: strike with minimum absolute net GEX in window
        df_window = df_net[(df_net["strike"] >= window_min) & (df_net["strike"] <= window_max)]
        if not df_window.empty:
            flip_level = float(df_window.loc[df_window["net_gex"].abs().idxmin(), "strike"])
    
    # ATM IV Extraction
    atm_iv = 15.0
    if not df_exp.empty:
        atm_iv = float(df_exp.loc[(df_exp["strike"] - spot).abs().idxmin(), "iv"])
    
    total_vex = df_exp["van"].sum()
    total_cex = df_exp["cha"].sum()
    
    # ── Flow Classifications (P0-1 Fix) ──
    gamma_regime = "LONG GAMMA" if total_gex > 0 else "SHORT GAMMA"
    vanna_bias = (
        "Strong Bullish" if total_vex > 500 else
        "Mild Bullish" if total_vex > 0 else
        "Mild Bearish" if total_vex > -500 else
        "Strong Bearish"
    )
    charm_flow = (
        "Strong Bullish Drift" if total_cex > 500 else
        "Mild Bullish Drift" if total_cex > 0 else
        "Mild Bearish Pressure" if total_cex > -500 else
        "Strong Bearish Pressure"
    )
    
    flow_regime = "Passive"
    if not df_exp.empty and "volume" in df_exp.columns:
        mask = (df_exp["strike"] >= spot * 0.985) & (df_exp["strike"] <= spot * 1.015)
        atm_df = df_exp[mask]
        if atm_df.empty:
            df_exp["dist"] = (df_exp["strike"] - spot).abs()
            atm_df = df_exp.sort_values("dist").head(4)
        atm_vol = atm_df["volume"].sum()
        atm_oi = atm_df["oi"].sum()
        ratio = atm_vol / max(atm_oi, 1.0)
        atm_oi_chng = atm_df["oi_chng"].sum() if "oi_chng" in atm_df.columns else 0.0
        
        if ratio > 0.4:
            flow_regime = "Institutional Churn"
        elif ratio > 0.25:
            if abs(atm_oi_chng) / max(atm_oi, 1.0) > 0.05:
                flow_regime = "Active Accumulation" if atm_oi_chng > 0 else "Active Liquidation"
            else:
                flow_regime = "Directional Engagement"
        elif ratio > 0.1:
            if abs(atm_oi_chng) > (atm_oi * 0.02):
                flow_regime = "Directional Engagement"
            else:
                flow_regime = "Tactical Positioning"
        elif ratio < 0.05:
            flow_regime = "Passive / Stale"
        else:
            flow_regime = "Neutral"

    metrics = FlowMetrics(
        total_gex=total_gex,
        total_gex_abs=total_gex_abs,
        total_delta=df_exp["dex"].sum(),
        total_vega=total_vega,
        total_theta=total_theta,
        total_vanna=total_vex,
        total_charm=total_cex,
        gamma_flip_level=float(round(flip_level, 2)),
        atm_iv_current=atm_iv,
        call_wall=c_wall,
        put_wall=p_wall,
        sec_call_wall=sec_c,
        sec_put_wall=sec_p,
        pcr_oi=float(pcr_oi),
        atm_oi_share=float(atm_oi_share),
        tv_ratio=float(tv_ratio),
        tv_label=tv_label,
        gamma_regime=gamma_regime,
        vanna_bias=vanna_bias,
        charm_flow=charm_flow,
        flow_regime_label=flow_regime,
        raw_exposures=df_exp
    )
    
    # Inject intelligence
    from dataclasses import replace
    intel = analyze_strike_intelligence(df_exp, spot, metrics)
    intel["expected_move"] = {"points": straddle, "upper": spot + straddle, "lower": spot - straddle}
    intel["atm_oi_share"] = float(atm_oi_share)
    
    return replace(metrics, intelligence=intel)
