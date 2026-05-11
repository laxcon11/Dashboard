import logging
from typing import Dict, Any
import NSE_Config

logger = logging.getLogger(__name__)

# ==================== STRATEGY SELECTION ENGINE (V5.5) ====================

STRATEGY_CONFIG = {
    "GAMMA_FLIP_THRESHOLD_NORM": 25.0,
    "TREND_DRIFT_THRESHOLD": 0.2,
    "MEAN_REV_STABILITY_THRESHOLD": 65,
    "VANNA_THRESHOLD_NORM": 3.0,
    "CHARM_THRESHOLD_NORM": 0.8,
    "DRIFT_THRESHOLD_MIN": 0.15,
    "DRIFT_THRESHOLD_MAX": 0.50,
    "GAMMA_CONV_THRESHOLD": 5.0
}

STRATEGY_WEIGHTS = {
    "regime": 0.40,
    "strike": 0.30,
    "risk": 0.30
}

def get_strategy_executive_summary(strategy_code: str, spot: float, walls: tuple, gex_norm: float = 0.0) -> dict:
    """Primary Risk & Invalidation logic (Institutional v2.0)."""
    c_wall = walls[0] if walls and len(walls) >= 1 else spot + 500
    p_wall = walls[1] if walls and len(walls) >= 2 else spot - 500
    
    summary = {
        "primary_risk": "Market Noise / Neutral Grind",
        "invalidation": "Thesis holds in current regime."
    }
    
    if strategy_code == "MEAN_REVERSION":
        summary["primary_risk"] = "Delta Breakout (Gamma Expansion)"
        summary["invalidation"] = f"Gamma flips NEGATIVE ({gex_norm:.1f}) or Spot breaks Walls ({int(p_wall)}-{int(c_wall)})."
    elif strategy_code == "GAMMA_FLIP":
        summary["primary_risk"] = "Whipsaw at Pivot"
        summary["invalidation"] = "Spot sustains 0.5% distance away from Flip Level."
    elif strategy_code == "TREND_ACCELERATION":
        summary["primary_risk"] = "Volatility Crash / Mean Reversion"
        summary["invalidation"] = "Drift score reverses sign or GEX flips POSITIVE."
        
    return summary

def select_master_strategy(ctx: dict) -> str:
    """
    Canonical Strategy Selection Logic.
    Maps Market State to structural setups.
    """
    m_state = ctx.get("market_state", {})
    state = m_state.get("state", "NEUTRAL")
    
    if state == "PINNED RANGE":
        return "MEAN_REVERSION"
    elif state == "EXPANSIVE TREND":
        return "TREND_ACCELERATION"
    elif state == "SUPPRESSED TREND":
        return "TREND_ACCELERATION"
    
    return "NO_TRADE"

def get_strategy_details(ctx: dict) -> dict:
    """
    Hydrates the selected strategy with execution parameters and rationale.
    """
    strategy_code = ctx.get("strategy_code", "NO_TRADE")
    m_state = ctx.get("market_state", {})
    spot = ctx.get("spot", 0)
    walls = ctx.get("walls", (spot+500, spot-500))
    gex_norm = ctx.get("flow_metrics", {}).get("gex_norm", 0.0)
    
    summary = get_strategy_executive_summary(strategy_code, spot, walls, gex_norm)
    
    # Phase 5.8: Cockpit Telemetry
    flow = ctx.get("flow_metrics", {})
    auto = ctx.get("auto_metrics", {})
    iv = ctx.get("iv_data", {})
    
    greek_snapshot = [
        {"label": "Net GEX", "value": f"{flow.get('total_gex', 0)/1e3:.2f}B", "color": "green" if flow.get("total_gex", 0) > 0 else "red", "meaning": "Dealer Gamma Positioning"},
        {"label": "Net Delta", "value": f"{flow.get('total_delta', 0)/1e3:.2f}B", "color": "blue" if flow.get("total_delta", 0) > 0 else "red", "meaning": "Directional Dealer Bias"},
        {"label": "Total Vega", "value": f"{flow.get('total_vega', 0):.1f}M", "color": "orange", "meaning": "Volatility Exposure"},
        {"label": "Total Theta", "value": f"{flow.get('total_theta', 0):.1f}M", "color": "green", "meaning": "Daily Time Decay"},
        {"label": "Gamma Flip", "value": f"{int(flow.get('gamma_flip_level', 0))}", "color": "blue", "meaning": "Vol Inflection Pivot"},
        {"label": "ATM IV", "value": f"{iv.get('atm_iv', 15.0):.1f}%", "color": "orange", "meaning": "Current Vol Regime"}
    ]
    
    dealer_behavior = [
        {"label": "Gamma", "state": "SUPPORTIVE" if flow.get("total_gex", 0) > 0 else "AGGRESSIVE", "behavior": "Dealer hedging provides pinning." if flow.get("total_gex", 0) > 0 else "Dealer hedging accelerates moves."},
        {"label": "Vanna", "state": flow.get("vanna_bias", "NEUTRAL"), "behavior": "IV-driven flow supports current bias." if flow.get("vanna_bias") != "NEUTRAL" else "No significant IV-drift detected."},
        {"label": "Charm", "state": "ACTIVE" if flow.get("charm_flow", "NEUTRAL") != "NEUTRAL" else "PASSIVE", "behavior": "Time decay drift is impacting positioning."}
    ]
    
    return {
        "code": strategy_code,
        "name": strategy_code.replace("_", " "),
        "executive_summary": summary,
        "action": m_state.get("action", "WAIT"),
        "confidence": m_state.get("confidence", 0.0),
        "market_state": m_state,
        "expected_move": ctx.get("flow_metrics", {}).get("institutional_iq", {}).get("expected_move", {}),
        "trends": {
            "max_pain_delta": 0, # To be hydrated from history in future
            "pcr_oi_delta": 0,
            "gamma_flip_delta": 0,
            "atm_oi_share_delta": 0
        },
        "bias_conviction": {"bias": "Neutral", "conflict_reason": ""},
        "vol_trend": {"delta_1d": 0.0, "slope_3d": 0.0},
        "cockpit": {
            "greek_snapshot": greek_snapshot,
            "dealer_behavior": dealer_behavior,
            "details": {}
        }
    }
