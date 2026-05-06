import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def system_health_check(ctx: dict) -> list:
    issues = []
    if ctx.get("spot", 0) <= 0:
        issues.append("Invalid spot")
    chain = ctx.get("option_chain_df")
    if chain is None or len(chain) < 50:
        issues.append("Weak option chain")
    elif "delta" not in chain.columns:
        issues.append("Missing delta")
    return issues

def build_narrative(ctx: dict) -> dict:
    """
    Deterministic Institutional Narrative Engine (V3).
    Consumes canonical market state and signal alignment from the Decision Engine.
    """
    # Safe extraction
    flow = ctx.get("flow_metrics") or {}
    auto = ctx.get("auto_metrics") or {}
    walls = ctx.get("walls") or (None, None)
    iv = ctx.get("iv_data") or {}
    spot = ctx.get("spot", 0)
    master_setup = ctx.get("master_setup", {})
    m_state = master_setup.get("market_state", {})
    
    # 1. State & Action Authority (Strictly Consumer Only)
    state = m_state.get("state", "NEUTRAL")
    substate = m_state.get("substate", "NORMAL")
    action = m_state.get("action", "WAIT")
    confidence = m_state.get("confidence", 0.0)
    why_list = m_state.get("why", ["Standard market regime."])
    
    decision_trail = [f"Canonical State: {state} ({substate})", f"Pre-Computed Action: {action}"]
    for w in why_list:
        decision_trail.append(f"Reason: {w}")

    # 3. Confidence Labeling
    if confidence >= 0.75: conf_label = "HIGH"
    elif confidence >= 0.5: conf_label = "MEDIUM"
    else: conf_label = "LOW"

    # 4. Reasoning (Contextualized)
    reasons = [
        f"Institutional regime classified as {state} ({substate}).",
        f"Signal alignment score is {confidence * 100:.0f}%.",
        f"Gamma regime: {flow.get('gamma_regime', 'UNKNOWN')}.",
        f"Drift velocity: {auto.get('drift', 0.0):.2f}."
    ]

    # 5. Data Quality & Gating
    meta = ctx.get("meta", {})
    trust_level = meta.get("data_quality", "HIGH")
    issues = system_health_check(ctx)
    
    if trust_level in ["DEGRADED", "LOW"]:
        action = "WAIT"
        reasons.append(f"EXECUTION BLOCKED: Data quality is {trust_level}.")
        decision_trail.append(f"Policy Override: WAIT (Data Quality {trust_level})")

    # 6. Next Trade Mapping
    trade_map = {
        "PINNED RANGE": "Iron Condor / Strangle (Suppressed Vol)",
        "SUPPRESSED TREND": "Directional Debit Spread (Institutional Grind)",
        "EXPANSIVE TREND": "Long Straddle / Strangle (Gamma Expansion)",
        "LIQUIDITY VACUUM": "Aggressive Debit Spread / Momentum Drive",
        "TRANSITIONAL INSTABILITY": "Wait for structural pivot confirmation"
    }
    next_trade = trade_map.get(state, "Observe for high-conviction structural setup")

    # 7. Triggers
    call_wall, put_wall = walls
    flip = flow.get("gamma_flip_level")
    triggers = []
    if call_wall: triggers.append(f"Break above Call Wall ({int(call_wall)})")
    if put_wall: triggers.append(f"Break below Put Wall ({int(put_wall)})")
    if flip: triggers.append(f"Spot crosses Gamma Flip ({int(flip)})")
    triggers.append("Significant shift in realized volatility acceleration")

    # 8. Risk Parameters
    risk = {
        "risk_type": "Volatility Compression / Theta Decay" if state == "PINNED RANGE" else "Volatility Expansion / Momentum Risk",
        "invalidation": "Spot sustains beyond key structural boundary (Wall/Flip)",
        "size": "0.5R" if confidence < 0.7 else "1R"
    }

    # 9. Reversion Scoring
    drift = auto.get("drift", 0.0)
    stability = auto.get("stability", 50.0)
    rev_score = max(0.0, min(10.0, (1 - abs(drift)) * (stability / 100) * 10))
    if rev_score > 7: rev_label = "HIGH_REVERSION"
    elif rev_score > 4: rev_label = "MODERATE_REVERSION"
    else: rev_label = "LOW_REVERSION"

    reversion = {
        "label": rev_label,
        "score": round(rev_score, 1),
        "reasons": ["Reversion probability derived from institutional stability vs drift."]
    }

    # Final Output Schema
    return {
        "dominant_state": state,
        "substate": substate,
        "dominant_action": action,
        "confidence": confidence,
        "execution_confidence": {
            "value": confidence,
            "label": conf_label,
            "reason": "Institutional signal alignment score"
        },
        "reasoning": reasons,
        "next_trade": next_trade,
        "triggers": triggers,
        "risk": risk,
        "reversion": reversion,
        "decision_trail": decision_trail,
        "data_quality": {
            "trust_level": trust_level,
            "issues": issues
        }
    }
