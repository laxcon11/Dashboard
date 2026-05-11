import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple
from nde_schema import ExecutionPlan, FlowMetrics

def snap_to_nearest_strike(target: float, df: pd.DataFrame) -> float:
    """Finds the closest available strike in the option chain."""
    if df is None or df.empty:
        return float(round(target / 50) * 50)
    strikes = df["strike"].unique()
    idx = (np.abs(strikes - target)).argmin()
    return float(strikes[idx])

def generate_tactical_legs(
    strategy_code: str, 
    spot: float, 
    flow: FlowMetrics, 
    raw_exp: pd.DataFrame
) -> Dict[str, Any]:
    """Generates the strike-specific legs for the selected strategy."""
    c_wall = flow.call_wall
    p_wall = flow.put_wall
    
    if strategy_code == "MEAN_REVERSION":
        sell_c = snap_to_nearest_strike(c_wall, raw_exp)
        sell_p = snap_to_nearest_strike(p_wall, raw_exp)
        return {
            "template": "IRON_CONDOR",
            "sell_ce": sell_c,
            "sell_pe": sell_p,
            "buy_ce": sell_c + 100,
            "buy_pe": sell_p - 100
        }
    
    if strategy_code == "TREND_ACCELERATION":
        atm = snap_to_nearest_strike(spot, raw_exp)
        return {
            "template": "STRADDLE",
            "buy_ce": atm,
            "buy_pe": atm
        }
        
    return {"template": "NONE"}

def hydrate_execution_plan(
    plan: ExecutionPlan, 
    spot: float, 
    flow: FlowMetrics, 
    raw_exp: pd.DataFrame
) -> ExecutionPlan:
    """Updates the execution plan with specific strikes and legs."""
    template = generate_tactical_legs(plan.strategy_code, spot, flow, raw_exp)
    
    # Extract legs for canonical format
    legs = []
    for k, v in template.items():
        if k in ["sell_ce", "buy_ce", "sell_pe", "buy_pe"]:
            legs.append({"type": k.split("_")[1], "strike": v, "side": k.split("_")[0]})

    # Update invalidation based on strikes
    invalidation = plan.invalidation_point
    if plan.strategy_code == "MEAN_REVERSION":
        # Invalidation is typically a break of the short strikes
        invalidation = template.get("sell_ce", spot + 200)

    # Use dataclass replace for immutability-friendly update
    from dataclasses import replace
    return replace(
        plan, 
        template=template, 
        legs=legs, 
        invalidation_point=float(invalidation)
    )
