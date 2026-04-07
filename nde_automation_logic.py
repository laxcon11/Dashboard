from datetime import datetime

def compute_expiry_phase(dte: int) -> str:
    """Classify the current DTE into a structural expiry phase."""
    if dte > 15:
        return "FRESH_OPEN"
    elif dte >= 7:
        return "MID_CYCLE"
    elif dte >= 3:
        return "LATE_CYCLE"
    elif dte >= 1:
        return "PRE_EXPIRY"
    else:
        return "EXPIRY_RISK"

def compute_drift(history: list[dict], spot: float = 0, atr: float = 0) -> tuple[float, float, float]:
    """
    Compute current score vs 5D average, and drift acceleration.
    Phase 40: Normalizes by baseline volatility (ATR/Spot) if provided.
    """
    if len(history) < 5:
        return 0.0, 0.0, 0.0
    
    scores = [float(h.get("score", 0.0)) for h in history]
    current_score = scores[-1]
    
    ma_5_today = sum(scores[-5:]) / 5.0
    drift_today = current_score - ma_5_today
    drift_5d_delta = current_score - scores[-5] if len(scores) >= 5 else 0.0
    
    if len(scores) >= 10:
        import pandas as pd
        s_series = pd.Series(scores)
        ema3 = s_series.ewm(span=3, adjust=False).mean()
        ema5 = s_series.ewm(span=5, adjust=False).mean()
        drift_acceleration = ema3.iloc[-1] - ema5.iloc[-1]
    else:
        drift_acceleration = 0.0
    
    # Phase 40: Normalize by vol-unit (ATR/Spot)
    if spot > 0 and atr > 0:
        vol_unit = atr / spot
        drift_today /= vol_unit
        drift_5d_delta /= vol_unit
        drift_acceleration /= vol_unit
    
    return round(drift_today, 4), round(drift_5d_delta, 4), round(drift_acceleration, 4)

def compute_stability(current_score: float, history: list[dict], persistence: int) -> tuple[int, int, bool]:
    """Compute 20D stability, 5D stability, and 20D fragility."""
    def _calc_window_stab(scores_slice, l):
        if len(scores_slice) < l or l == 0:
            return 50, False, 0.5
        min_s, max_s = min(scores_slice), max(scores_slice)
        range_s = max_s - min_s
        norm_pos = 0.5 if range_s == 0 else (current_score - min_s) / range_s
        
        term1 = min(1.0, persistence / float(l)) * 50.0
        term2 = (1.0 - abs(0.5 - norm_pos) * 2.0) * 50.0
        stability = int(max(0, min(100, term1 + term2)))
        fragility = norm_pos < 0.2 or norm_pos > 0.8
        return stability, fragility, norm_pos

    scores = [float(h.get("score", 0.0)) for h in history]
    stab_20, frag_20, _ = _calc_window_stab(scores[-20:], 20)
    stab_5, _, _ = _calc_window_stab(scores[-5:], 5)
    
    # If history is less than 20 days but more than 5, 20D defaults to 50 but we still have real 5D
    if len(history) < 20:
        stab_20 = 50
        frag_20 = False
        
    return stab_20, stab_5, frag_20

def compute_transition_risk(drift: float, stability: int) -> float:
    """Estimate escalation likelihood."""
    # User Formula: (abs(drift) * 0.5) + ((100 - stability) / 100 * 0.5)
    risk = (abs(drift) * 0.5) + ((100 - stability) / 200.0)
    return round(max(0.0, min(1.0, risk)), 2)

def normalize_regime_name(regime: str) -> str:
    """Standardize regime string to uppercase underscore format."""
    if not regime: return "SELECTIVE"
    return str(regime).upper().replace("-", "_").replace(" ", "_").strip()

def compute_probabilities(regime: str, drift: float, persistence: int = 5) -> dict:
    """Rule-based tactical probabilities with Regime Duration blending."""
    reg = normalize_regime_name(regime)
    
    # Baseline Upside Probabilities
    if reg in ["CRISIS", "STRESS"]:
        base_up = 0.40
    elif reg == "DEFENSIVE":
        base_up = 0.48
    else:
        base_up = 0.55 # Selective/Risk-On
        
    adjustment = -drift * 0.2
    up_prob = max(0.2, min(0.8, base_up + adjustment))
    
    # Phase 37: Blend towards 0.5 based on regime maturity (Base 5 days to confirm)
    blend_factor = min(1.0, persistence / 5.0)
    up_prob = up_prob * blend_factor + 0.5 * (1.0 - blend_factor)
    
    # Forward 5D renormalization
    raw_u = up_prob * 0.9
    raw_d = (1.0 - up_prob) * 1.1
    total = raw_u + raw_d
    
    return {
        "tactical_24h": {
            "upside": round(up_prob, 2), 
            "downside": round(1.0 - up_prob, 2), 
            "tail": 0.05 if up_prob < 0.4 else 0.02
        },
        "forward_5d": {
            "upside": round(raw_u / total, 2), 
            "downside": round(raw_d / total, 2), 
            "vol_expansion": 0.10 if abs(drift) > 0.2 else 0.05
        }
    }

import json
from pathlib import Path

def write_daily_nde_snapshot(
    curr_regime, persistence, stability_20d, stability_5d, drift, drift_accel, fragility,
    probs, escalation, used_expiry, gamma_regime, flip, vanna, charm,
    flow_regime, total_gex, t_bias, s_bias, spot, atr, config_hash
):
    """Save the finalized daily NDE snapshot decoupled from Streamlit UI."""
    AUTOMATION_OUTPUT_DIR = Path(__file__).parent / "data" / "automation"
    AUTOMATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().timestamp(),
        "regime": curr_regime,
        "persistence_days": persistence,
        "stability_20d": stability_20d,
        "stability_5d": stability_5d,
        "drift_score": drift,
        "drift_accel": drift_accel,
        "fragility_flag": fragility,
        "probabilities": probs,
        "escalation_probability": escalation,

        "options_flow": {
            "expiry": used_expiry,
            "gamma_regime": gamma_regime,
            "gamma_flip": flip,
            "vanna_bias": vanna,
            "charm_flow": charm,
            "flow_regime": flow_regime,
            "total_gex": total_gex
        },
        "bias": {"tactical": t_bias, "structural": s_bias},
        "risk_map": {"bull_trigger": spot + atr, "bear_trigger": spot - atr, "invalidation": spot - 1.5 * atr},
        "config_hash": config_hash
    }
    
    # Save Dated Immutable Snapshot
    fname = AUTOMATION_OUTPUT_DIR / f"nde_v12_{datetime.now().strftime('%Y%m%d')}.json"
    fname.write_text(json.dumps(snapshot, indent=2))
    
    # Save 'Latest' Alias for easy linkage
    latest_alias = AUTOMATION_OUTPUT_DIR / "latest_snapshot.json"
    latest_alias.write_text(json.dumps(snapshot, indent=2))
    
    return fname
