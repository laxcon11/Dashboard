from typing import Dict, Any
from nde_schema import ExecutionPlan, MarketState, FlowMetrics

def select_strategy(state: MarketState) -> str:
    """Canonical mapping of market regime to strategy code."""
    label = state.state
    if label == "PINNED RANGE":
        return "MEAN_REVERSION"
    elif label == "EXPANSIVE TREND":
        return "TREND_ACCELERATION"
    elif label == "SUPPRESSED TREND":
        return "TREND_ACCELERATION"
    return "NO_TRADE"

def get_risk_parameters(strategy_code: str, spot: float, flow: FlowMetrics) -> Dict[str, str]:
    """Returns primary risk and thesis invalidation criteria."""
    summary = {
        "primary_risk": "Market Noise / Neutral Grind",
        "invalidation": "Thesis holds in current regime."
    }
    
    c_wall = flow.call_wall
    p_wall = flow.put_wall
    
    if strategy_code == "MEAN_REVERSION":
        summary["primary_risk"] = "Delta Breakout (Gamma Expansion)"
        summary["invalidation"] = f"Gamma flips NEGATIVE ({flow.total_gex:.1f}) or Spot breaks Walls ({int(p_wall)}-{int(c_wall)})."
    elif strategy_code == "GAMMA_FLIP":
        summary["primary_risk"] = "Whipsaw at Pivot"
        summary["invalidation"] = "Spot sustains 0.5% distance away from Flip Level."
    elif strategy_code == "TREND_ACCELERATION":
        summary["primary_risk"] = "Volatility Crash / Mean Reversion"
        summary["invalidation"] = "Drift score reverses sign or GEX flips POSITIVE."
        
    return summary

def compile_execution_plan(
    state: MarketState, 
    flow: FlowMetrics, 
    spot: float,
    t_days: float = 7.0,
    mode: str = "Balanced"
) -> ExecutionPlan:
    """Assembles the primary strategy and its risk profile with Expiry Policy enforcement."""
    code = select_strategy(state)
    
    # Expiry Risk Policy (Phase 45 Hardening)
    # If T-0, block all trades unless IV < 12 and mode is Defensive.
    if t_days <= 1.0:
        iv = flow.atm_iv_current
        if iv > 12.0:
            code = "NO_TRADE"
        elif mode != "Defensive":
            code = "NO_TRADE"
            
    risk = get_risk_parameters(code, spot, flow)
    
    # Action Logic: Default to WAIT if confidence is low or state is NEUTRAL
    action = "WAIT"
    if code != "NO_TRADE" and state.confidence > 0.4:
        action = "TRADE_READY"

    return ExecutionPlan(
        strategy_code=code,
        action=action,
        confidence=state.confidence,
        primary_risk=risk["primary_risk"],
        invalidation_point=0.0, # To be determined by strike selection
        expected_move=flow.intelligence.get("expected_move", {}) if flow.intelligence else {}
    )
