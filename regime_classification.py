import json
from pathlib import Path
from typing import Dict, Any, Optional

REGIME_STATE_FILE = Path("notes/regime_v4_state.json")

# Unified 4-class regime taxonomy (aligned with prediction_integrity/schema.py)
REGIMES = {
    "RISK_ON": "Risk On",
    "SELECTIVE": "Selective",
    "DEFENSIVE": "Defensive",
    "CRISIS": "Crisis"
}

# Backward-compat aliases for legacy code that references old keys
REGIME_ALIASES = {
    "NEUTRAL": "SELECTIVE",
    "RISK_OFF": "DEFENSIVE",
}


def classify_regime(score: float) -> str:
    """
    Score-based classification (4-class unified taxonomy):
    >0.45: Risk On
    0.0 to 0.45: Selective
    -0.30 to 0.0: Defensive
    <-0.30: Crisis
    """
    if score >= 0.45:
        return REGIMES["RISK_ON"]
    if score >= 0.0:
        return REGIMES["SELECTIVE"]
    if score >= -0.30:
        return REGIMES["DEFENSIVE"]
    return REGIMES["CRISIS"]


def calculate_regime_probabilities(score: float, regime: str) -> dict[str, float]:
    """
    Heuristic probability distribution for the dashboard.
    Returns keys: risk_on, selective, defensive, crisis (4-class)
    """
    probs = {"risk_on": 0.0, "selective": 0.0, "defensive": 0.0, "crisis": 0.0}

    if regime == REGIMES["RISK_ON"]:
        on_prob = min(0.95, 0.60 + (score - 0.45))
        probs["risk_on"] = on_prob
        probs["selective"] = (1.0 - on_prob) * 0.65
        probs["defensive"] = (1.0 - on_prob) * 0.25
        probs["crisis"] = 1.0 - probs["risk_on"] - probs["selective"] - probs["defensive"]
    elif regime == REGIMES["SELECTIVE"]:
        dist = abs(score - 0.225)
        sel_prob = max(0.40, 0.70 - dist)
        probs["selective"] = sel_prob
        rem = 1.0 - sel_prob
        if score > 0.225:
            probs["risk_on"] = rem * 0.55
            probs["defensive"] = rem * 0.35
            probs["crisis"] = rem * 0.10
        else:
            probs["risk_on"] = rem * 0.20
            probs["defensive"] = rem * 0.55
            probs["crisis"] = rem * 0.25
    elif regime == REGIMES["DEFENSIVE"]:
        def_prob = min(0.85, 0.50 + abs(score))
        probs["defensive"] = def_prob
        rem = 1.0 - def_prob
        probs["selective"] = rem * 0.50
        probs["crisis"] = rem * 0.35
        probs["risk_on"] = rem * 0.15
    else:  # CRISIS
        crisis_prob = min(0.90, 0.55 + abs(score))
        probs["crisis"] = crisis_prob
        rem = 1.0 - crisis_prob
        probs["defensive"] = rem * 0.60
        probs["selective"] = rem * 0.30
        probs["risk_on"] = rem * 0.10

    return probs

def calculate_regime_confidence(score: float, regime: str) -> float:
    """
    Calculates confidence (0-100%) based on distance from the exit/transition boundaries.
    - Deep in regime: High Confidence (80-95%)
    - Near Zero Line (Exit): Low Confidence (5-20%)
    - Near Threshold (Entry): Fading Confidence
    """
    if regime == REGIMES["RISK_ON"]:
        # Entry at 0.45, Exit at 0.0
        if score >= 0.65: return 0.95
        if score <= 0.10: return 0.10
        # Linear interp between 0.10 (10%) and 0.65 (95%)
        return round(0.10 + (float(score) - 0.10) * (0.85 / 0.55), 3)
        
    elif regime == REGIMES["SELECTIVE"]:
        # Ideal Selective is 0.225
        dist = abs(float(score) - 0.225)
        # 0.0 distance -> 0.85 confidence
        # 0.225 distance (at 0 or 0.45) -> 0.20 confidence
        return round(max(0.05, 0.85 - (dist * (0.65 / 0.225))), 3)
        
    elif regime == REGIMES["DEFENSIVE"]:
        # Entry at -0.30, Exit at 0.0
        a_score = abs(float(score)) # Use absolute for easier math
        if a_score >= 0.50: return 0.90
        if float(score) >= -0.05: return 0.10
        # Linear interp between -0.05 (10%) and -0.50 (90%)
        return round(0.10 + (a_score - 0.05) * (0.80 / 0.45), 3)
        
    elif regime == REGIMES["CRISIS"]:
        # Crisis is exceptional; confidence is high if VIX is extremely high
        a_score = abs(float(score))
        if a_score >= 1.0: return 0.98
        return round(min(0.98, 0.60 + a_score * 0.30), 3)
        
    return 0.50

def check_crisis_overrides(vix_value: Optional[float], credit_spread_z: Optional[float]) -> tuple[bool, str]:
    """
    Overrides normal scoring for extreme events.
    Returns (True, reason) if crisis detected, else (False, "").
    """
    if vix_value is not None and vix_value > 35:
        return True, f"India VIX > 35 ({REGIMES['CRISIS']} Signal)"
    if credit_spread_z is not None and credit_spread_z > 2.0:
        return True, f"Global Credit Spread Z > 2.0 ({REGIMES['CRISIS']} Stress)"
    return False, ""

def load_previous_regime_state() -> Dict[str, Any]:
    if not REGIME_STATE_FILE.exists():
        return {"current_regime": REGIMES["SELECTIVE"], "current_score": 0.0, "persistence_count": 0, "pending_regime": None}
    try:
        return json.loads(REGIME_STATE_FILE.read_text())
    except Exception:
        return {"current_regime": REGIMES["SELECTIVE"], "current_score": 0.0, "persistence_count": 0, "pending_regime": None}

def save_regime_state(state: Dict[str, Any]):
    REGIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGIME_STATE_FILE.write_text(json.dumps(state, indent=2))

def apply_stability_filters(new_score: float, new_regime: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies Persistence and Momentum filtering.
    - Persistence: 3-day hold for regime change.
    - Momentum: Update only if score change > 0.10.
    """
    prev_state = load_previous_regime_state()
    p_score = prev_state.get("current_score", 0.0)
    p_regime = prev_state.get("current_regime", REGIMES["SELECTIVE"])
    p_count = prev_state.get("persistence_count", 0)
    pending = prev_state.get("pending_regime")
    
    momentum_threshold = settings.get("momentum_threshold", 0.10)
    persistence_required = settings.get("persistence_days", 3)
    
    # 1. Momentum Filter (for Score)
    final_score = new_score
    if abs(new_score - p_score) < momentum_threshold:
        final_score = p_score # Lock score to prevent jitter
        
    # 2. Persistence Filter (for Regime)
    final_regime = p_regime
    
    # [NEW] Crisis Re-entry Rule: If we were in Crisis and the override cleared,
    # skip persistence and snap immediately to the raw score-based regime.
    is_crisis_exit = (p_regime == REGIMES["CRISIS"] and new_regime != REGIMES["CRISIS"])
    
    if new_regime != p_regime:
        if is_crisis_exit:
            # Exceptional Exit: Snapshot to current raw signal
            final_regime = new_regime
            p_count = 0
            pending = None
        elif new_regime == pending:
            p_count += 1
        else:
            pending = new_regime
            p_count = 1
            
        if not is_crisis_exit:
            if p_count >= persistence_required or new_regime == REGIMES["CRISIS"]:
                final_regime = new_regime
                p_count = 0
                pending = None
    else:
        p_count = 0
        pending = None
        
    # Calculate Confidence for the Final State
    confidence = calculate_regime_confidence(final_score, final_regime)
        
    new_state = {
        "current_regime": final_regime,
        "current_score": round(float(final_score), 4),
        "confidence": confidence,
        "persistence_count": p_count,
        "pending_regime": pending,
        "raw_score": round(float(new_score), 4),
        "raw_regime": new_regime
    }
    
    save_regime_state(new_state)
    return new_state
