import numpy as np
from scipy.stats import norm
from typing import Dict, List, Any

# Numerical Constants
DAYS_PER_YEAR = 365.0

def black_scholes(S: np.ndarray, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> np.ndarray:
    """Standard BS model for European options (Vectorized over S)."""
    if T <= 0:
        return np.maximum(0, S - K) if option_type == "CE" else np.maximum(0, K - S)
    
    # Avoid log(0) or div by zero
    sigma = max(0.01, sigma)
    sqrt_T = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    
    if option_type == "CE":
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
    return price

def generate_payoff_scenarios(
    spot: float, 
    atr: float, 
    legs: List[Dict[str, Any]], 
    dte: float, 
    iv: float = 20.0, 
    r: float = 0.07
) -> Dict[str, Any]:
    """
    Computes projected PnL surfaces for the execution legs.
    Optimized to compute full grids in vectorized passes.
    """
    if not legs:
        return {"spot_range": [], "payoffs": {}}

    # 1. Setup Time and Vol parameters
    T_curr = max(0.001, dte / DAYS_PER_YEAR)
    T_future = max(0, (dte - 1) / DAYS_PER_YEAR) 
    sigma = iv / 100.0
    
    # 2. Define Spot Range (±3 ATR for institutional breadth)
    spot_range = np.linspace(spot - 3.0 * atr, spot + 3.0 * atr, 60)
    
    pnl_t0 = np.zeros_like(spot_range)
    pnl_theta = np.zeros_like(spot_range)
    pnl_vega_plus = np.zeros_like(spot_range)
    
    for leg in legs:
        side = 1 if leg.get("side", "buy").lower() == "buy" else -1
        k = float(leg["strike"])
        opt_type = "CE" if leg["type"].upper() == "CE" or "CALL" in leg["type"].upper() else "PE"
        qty = float(leg.get("qty", 1))
        
        # Current Value across range
        v0 = black_scholes(spot_range, k, T_curr, r, sigma, opt_type)
        # T+1 Value (Theta simulation)
        v1 = black_scholes(spot_range, k, T_future, r, sigma, opt_type)
        # Vega Shock (+2.5 vol points)
        v_plus = black_scholes(spot_range, k, T_curr, r, sigma + 0.025, opt_type)
        
        # Entry price at current spot (fair value approximation)
        entry_v = black_scholes(np.array([spot]), k, T_curr, r, sigma, opt_type)[0]
        
        pnl_t0 += (v0 - entry_v) * side * qty
        pnl_theta += (v1 - entry_v) * side * qty
        pnl_vega_plus += (v_plus - entry_v) * side * qty
        
    return {
        "spot_range": spot_range.tolist(),
        "payoffs": {
            "current": pnl_t0.tolist(),
            "theta_1d": pnl_theta.tolist(),
            "vega_shock": pnl_vega_plus.tolist()
        }
    }
