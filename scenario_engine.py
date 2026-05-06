import numpy as np
import pandas as pd

class ScenarioEngine:
    """
    Institutional Scenario Analysis Engine.
    Generates payoff surfaces for Spot ± Expected Move, IV shocks, and Time decay.
    """
    @staticmethod
    def generate_scenarios(spot: float, atr: float, legs: list, dte: int) -> dict:
        """
        Computes projected PnL across a range of spot prices.
        """
        if not legs:
            return {"spot_range": [], "payoffs": []}

        # 1. Define Spot Range (±2 ATR)
        spot_range = np.linspace(spot - 2*atr, spot + 2*atr, 50)
        
        # 2. Compute Payoff for each spot
        # This is a simplified "intrinsic-only" or "black-scholes" approximation
        # For now, let's do a structural intrinsic payoff
        payoffs = []
        for s in spot_range:
            total_pnl = 0
            for leg in legs:
                strike = leg.get("strike", spot)
                l_type = leg.get("type", "BUY")
                opt = leg.get("opt", "CE")
                
                if opt == "CE":
                    val = max(0, s - strike)
                else:
                    val = max(0, strike - s)
                
                if l_type == "BUY":
                    total_pnl += val
                else:
                    total_pnl -= val
            payoffs.append(float(round(total_pnl, 2)))
            
        return {
            "spot_range": spot_range.tolist(),
            "payoffs": payoffs,
            "expected_move": atr, # Placeholder for more complex EM
            "lower_bound": spot - atr,
            "upper_bound": spot + atr
        }
