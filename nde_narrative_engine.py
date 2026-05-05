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
    Deterministic Narrative Engine (V2 - Strict Hierarchy)
    Inputs: ctx (from generate_engine_context)
    Output: narrative dict (complete, UI-safe, deterministic decision authority)
    """

    # Safe extraction
    flow = ctx.get("flow_metrics") or {}
    auto = ctx.get("auto_metrics") or {}
    walls = ctx.get("walls") or (None, None)
    iv = ctx.get("iv_data") or {}
    spot = ctx.get("spot", 0)

    call_wall, put_wall = walls

    # Core Metrics
    gamma_regime = flow.get("gamma_regime", "UNKNOWN")
    drift = auto.get("drift", 0.0)
    drift_acc = auto.get("drift_acceleration", 0.0)
    stability = auto.get("stability", 50.0)
    vanna = flow.get("vanna_bias", "Neutral")
    charm = flow.get("charm_flow", "Neutral")
    iv_rank = iv.get("iv_rank", 50.0)
    flip = flow.get("gamma_flip_level")

    decision_trail = []

    # 1. State Classification (Deterministic)
    state = "NEUTRAL"
    if gamma_regime.startswith("LONG") and stability >= 55 and abs(drift) < 0.25:
        state = "PINNED RANGE"
        decision_trail.append("State Classified: PINNED RANGE (Long Gamma + High Stability + Low Drift)")
    elif gamma_regime.startswith("SHORT") and abs(drift) > 0.3 and drift_acc > 0:
        state = "VOLATILITY EXPANSION"
        decision_trail.append("State Classified: VOLATILITY EXPANSION (Short Gamma + High Drift + Acceleration)")
    elif gamma_regime.startswith("SHORT") and abs(drift) > 0.2:
        state = "LIQUIDITY VACUUM"
        decision_trail.append("State Classified: LIQUIDITY VACUUM (Short Gamma + Moderate Drift)")
    else:
        decision_trail.append("State Classified: NEUTRAL (No dominant structural regime)")

    # 2. Action Logic
    if state == "PINNED RANGE":
        action = "ENTER"
        decision_trail.append("Action Decided: ENTER (Sell Premium)")
    elif state == "VOLATILITY EXPANSION":
        action = "ENTER"
        decision_trail.append("Action Decided: ENTER (Long Volatility)")
    elif state == "LIQUIDITY VACUUM":
        action = "ENTER"
        decision_trail.append("Action Decided: ENTER (Directional)")
    else:
        action = "WAIT"
        decision_trail.append("Action Decided: WAIT (Awaiting structural confirmation)")

    # 3. Confidence Scoring
    conf = 0.0
    conf += 0.3 if gamma_regime.startswith("LONG") else 0.1
    conf += min(0.3, abs(drift))
    conf += 0.2 if stability > 60 else 0.05
    conf += 0.2 if vanna in ("POSITIVE", "NEGATIVE") else 0.05
    confidence = round(min(1.0, conf), 2)

    if confidence >= 0.7: conf_label = "HIGH"
    elif confidence >= 0.4: conf_label = "MEDIUM"
    else: conf_label = "LOW"

    # 4. Reasoning (ALWAYS FILLED)
    reasons = [
        f"Gamma regime is {gamma_regime}.",
        f"Drift measured at {drift:.2f} with acceleration {drift_acc:.2f}.",
        f"Structural stability score is {stability:.0f}/100."
    ]
    if vanna != "Neutral": reasons.append(f"Vanna bias is {vanna}.")
    if charm != "Neutral": reasons.append(f"Charm flow indicates {charm}.")

    # --- NEW: Data Quality Gating ---
    meta = ctx.get("meta", {})
    trust_level = meta.get("data_quality", "HIGH")
    df_chain = ctx.get("option_chain_df")
    
    data_quality = {
        "trust_level": trust_level,
        "chain_rows": len(df_chain) if df_chain is not None else 0,
        "has_delta": "delta" in df_chain.columns if df_chain is not None else False
    }
    
    issues = system_health_check(ctx)
    if trust_level in ["DEGRADED", "LOW"]:
        action = "WAIT"
        reasons.append(f"Execution blocked due to {trust_level} data quality.")
        decision_trail.append(f"Action Overridden: WAIT (Data Quality {trust_level})")

    # 5. Next Trade (NEVER None)
    if state == "PINNED RANGE":
        next_trade = "Iron Condor / Strangle (Mean Reversion)"
    elif state == "VOLATILITY EXPANSION":
        next_trade = "ATM Straddle / Strangle (Breakout)"
    elif state == "LIQUIDITY VACUUM":
        next_trade = "Directional Debit Spread"
    else:
        next_trade = "Observe for structural breakout or mean reversion setup"

    # 6. Triggers (ALWAYS FILLED)
    triggers = []
    if call_wall: triggers.append(f"Break above Call Wall ({int(call_wall)})")
    if put_wall: triggers.append(f"Break below Put Wall ({int(put_wall)})")
    if flip: triggers.append(f"Spot deviates from Gamma Flip ({int(flip)}) by >0.5%")
    triggers.append("IV Rank shifts > 10 points")
    triggers.append("Significant change in Drift Acceleration")

    if not triggers: # Safety fallback
        triggers = ["Awaiting institutional flow shift", "Awaiting volatility expansion"]

    # 7. Risk Parameters
    risk = {
        "risk_type": "Whipsaw / Noise" if state == "NEUTRAL" else "Trend Volatility",
        "invalidation": "Spot sustains beyond key structural boundary (Wall/Flip)",
        "size": "0.5R" if confidence < 0.5 else "1R"
    }

    # 8. Reversion Scoring
    rev_score = max(0.0, min(10.0, (1 - abs(drift)) * (stability / 100) * 10))
    if rev_score > 7: rev_label = "HIGH_REVERSION"
    elif rev_score > 4: rev_label = "MODERATE_REVERSION"
    else: rev_label = "LOW_REVERSION"

    reversion = {
        "label": rev_label,
        "score": round(rev_score, 1),
        "reasons": ["Reversion probability derived from cross-asset stability vs intraday drift"]
    }

    # Final Output Schema
    return {
        "dominant_state": state,
        "dominant_action": action,
        "confidence": confidence,
        "execution_confidence": {
            "value": confidence,
            "label": conf_label,
            "reason": "Multi-factor convergence score"
        },
        "reasoning": reasons,
        "next_trade": next_trade,
        "triggers": triggers,
        "risk": risk,
        "reversion": reversion,
        "decision_trail": decision_trail,
        "data_quality": data_quality,
        "warnings": issues
    }
