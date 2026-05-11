import numpy as np
import pandas as pd
from scipy.stats import norm
import math

class ScenarioEngine:
    """
    Institutional Scenario Analysis Engine (V2).
    Generates high-fidelity payoff surfaces using Black-Scholes.
    Includes: Theta Decay, Vega Shocks, and Expiry Curvature.
    """
    
    @staticmethod
    def black_scholes(S, K, T, r, sigma, option_type="CE"):
        """
        Standard BS model for European options.
        """
        if T <= 0:
            return max(0, S - K) if option_type == "CE" else max(0, K - S)
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        if option_type == "CE":
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            
        return price

    @staticmethod
    def generate_scenarios(spot: float, atr: float, legs: list, dte: int, iv: float = 20.0, r: float = 0.07) -> dict:
        """
        Computes projected PnL surfaces.
        Parameters:
            dte: Days to expiry (Intraday = 0.5 or 1)
            iv: Current ATM IV (Percentage)
        """
        if not legs:
            return {"spot_range": [], "payoffs": []}

        # 1. Setup parameters
        T_curr = max(0.001, dte / 365.0)
        T_future = max(0, (dte - 1) / 365.0) # 1-day decay simulation
        sigma = iv / 100.0
        
        # 2. Define Spot Range (±2.5 ATR for institutional breadth)
        spot_range = np.linspace(spot - 2.5 * atr, spot + 2.5 * atr, 60)
        
        # 3. Compute Surfaces
        pnl_t0 = []
        pnl_theta = []
        pnl_vega_plus = []
        pnl_vega_minus = []
        
        for s in spot_range:
            val_t0 = 0
            val_theta = 0
            val_vega_plus = 0
            val_vega_minus = 0
            
            for leg in legs:
                side = 1 if leg["side"] == "buy" else -1
                k = leg["strike"]
                opt_type = leg["type"]
                qty = leg.get("qty", 1)
                
                # BS Prices
                price_t0 = ScenarioEngine.black_scholes(s, k, T_curr, r, sigma, opt_type)
                price_theta = ScenarioEngine.black_scholes(s, k, T_future, r, sigma, opt_type)
                price_vega_plus = ScenarioEngine.black_scholes(s, k, T_curr, r, sigma + 0.02, opt_type)
                price_vega_minus = ScenarioEngine.black_scholes(s, k, T_curr, r, max(0.01, sigma - 0.02), opt_type)
                
                # Entry price fallback
                entry = leg.get("entry_price", price_t0)
                
                val_t0 += (price_t0 - entry) * side * qty
                val_theta += (price_theta - entry) * side * qty
                val_vega_plus += (price_vega_plus - entry) * side * qty
                val_vega_minus += (price_vega_minus - entry) * side * qty
                
            pnl_t0.append(val_t0)
            pnl_theta.append(val_theta)
            pnl_vega_plus.append(val_vega_plus)
            pnl_vega_minus.append(val_vega_minus)
            
        return {
            "spot_range": spot_range.tolist(),
            "payoffs": {
                "current": pnl_t0,
                "theta_1d": pnl_theta,
                "vega_plus_2": pnl_vega_plus,
                "vega_minus_2": pnl_vega_minus
            }
        }
        payoff_t0 = [] # Current Value
        payoff_t1 = [] # Value after 1 day decay (Theta simulation)
        payoff_v_up = [] # Value after +20% Vega shock
        
        for s in spot_range:
            pnl_t0 = 0
            pnl_t1 = 0
            pnl_v_up = 0
            
            for leg in legs:
                strike = leg.get("strike", spot)
                l_type = leg.get("type", "BUY")
                opt = leg.get("opt", "CE")
                mult = 1 if l_type == "BUY" else -1
                
                # Current Price
                v0 = ScenarioEngine.black_scholes(s, strike, T_curr, r, sigma, opt)
                # T+1 Price (Theta Decay)
                v1 = ScenarioEngine.black_scholes(s, strike, T_future, r, sigma, opt)
                # Vega Shock Price (+5 vol points)
                vv = ScenarioEngine.black_scholes(s, strike, T_curr, r, sigma + 0.05, opt)
                
                # We measure PnL relative to entry at spot (approximation)
                # Entry price at original spot
                entry_v = ScenarioEngine.black_scholes(spot, strike, T_curr, r, sigma, opt)
                
                pnl_t0 += (v0 - entry_v) * mult
                pnl_t1 += (v1 - entry_v) * mult
                pnl_v_up += (vv - entry_v) * mult
                
            payoff_t0.append(float(round(pnl_t0, 2)))
            payoff_t1.append(float(round(pnl_t1, 2)))
            payoff_v_up.append(float(round(pnl_v_up, 2)))
            
        return {
            "spot_range": spot_range.tolist(),
            "payoffs_t0": payoff_t0,
            "payoffs_t1": payoff_t1,
            "payoffs_vega_up": payoff_v_up,
            "expected_move": atr,
            "lower_bound": spot - atr,
            "upper_bound": spot + atr,
            "model": "Black-Scholes (Institutional V2)"
        }
