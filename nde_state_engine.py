import numpy as np
from typing import List, Dict, Any
from nde_schema import MarketState, FlowMetrics, RVMetrics, LocalGammaMetrics

def compute_thesis_coherence(
    state_label: str, 
    drift: float, 
    gex_net: float
) -> Dict[str, Any]:
    """
    Institutional Thesis Coherence Engine (Carmack Refactor).
    Measures structural alignment across flow and velocity.
    """
    agreements = []
    conflicts = []
    score = 0.5
    
    # 1. Trend Coherence
    if state_label == "EXPANSIVE TREND":
        if abs(drift) > 0.2: 
            score += 0.1
            agreements.append("Trend alignment")
        if abs(gex_net) < 5.0:
            score += 0.1
            agreements.append("Structural clearing")
        else:
            score -= 0.1
            conflicts.append("High GEX blocking expansion")
            
    # 2. Mean Reversion Coherence
    elif state_label == "PINNED RANGE":
        if gex_net > 5.0:
            score += 0.1
            agreements.append("Gamma pinning active")
        if abs(drift) < 0.15:
            score += 0.1
            agreements.append("Velocity compression")
        else:
            score -= 0.1
            conflicts.append("Drift escaping range")
            
    return {
        "coherence_score": float(max(0.0, min(1.0, score))),
        "agreements": agreements,
        "conflicts": conflicts
    }

def classify_market_state(
    flow: FlowMetrics,
    rv: RVMetrics,
    gamma_local: LocalGammaMetrics,
    drift: float,
    stability_20d: float
) -> MarketState:
    """
    Deterministic State Machine for NDE Regime Classification.
    Uses typed metrics to assign a canonical market regime.
    """
    state = "NEUTRAL"
    substate = "NORMAL"
    why = []
    
    gex_net = flow.total_gex
    suppression = gamma_local.suppression_strength
    
    # 1. Classification Logic (Priority-ordered gates)
    if gex_net > 10.0 and abs(drift) < 0.15:
        state = "PINNED RANGE"
        substate = "HIGH_ABSORPTION"
        why.append("Deep Positive GEX absorbing all flow.")
        
    elif gex_net < -5.0 or gamma_local.collapse_risk:
        if gamma_local.collapse_risk and abs(drift) > 0.2:
            state = "EXPANSIVE TREND"
            substate = "COLLAPSE_DRIVEN"
            why.append("Structural suppression failure detected.")
        elif gex_net < -10.0:
            state = "EXPANSIVE TREND"
            substate = "GAMMA_SQUEEZE"
            why.append("Negative GEX accelerating movement.")
        else:
            state = "NEUTRAL"
            substate = "SUPPRESSED"
            why.append("Expansion signal blocked by structural walls.")
            
    elif abs(drift) > 0.3:
        state = "SUPPRESSED TREND"
        substate = "DRIFT_DOMINANT"
        why.append("Trend persists despite dealer containment.")

    # 2. Coherence Scoring
    coherence = compute_thesis_coherence(state, drift, gex_net)
    
    # 3. Volatility Regime
    vol_regime = "NORMAL"
    if rv.rv_5d > 25.0: vol_regime = "EXPANSIVE"
    elif rv.rv_5d < 12.0: vol_regime = "SUPPRESSED"

    return MarketState(
        state=state,
        substate=substate,
        confidence=coherence["coherence_score"],
        coherence_score=coherence["coherence_score"],
        suppression_regime="STABLE" if suppression > 0.6 else "FLUID",
        transition_risk=1.0 - stability_20d / 100.0,
        volatility_regime=vol_regime,
        why=why
    )
