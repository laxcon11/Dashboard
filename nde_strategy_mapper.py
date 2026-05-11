def map_strategy(ctx: dict, narrative: dict) -> dict:
    """
    Institutional Strategy Mapping Engine (V3).
    Translates canonical market state into concrete execution templates.
    Structural Logic:
    - SUPPRESSED: Define risk via spreads, avoid long gamma.
    - EXPANSIVE: Favor convexity (straddles/strangles), dealer amplification.
    - PINNED: premium selling (Iron Condor).
    """
    state = narrative.get("dominant_state", "NEUTRAL")
    substate = narrative.get("substate", "NORMAL")
    action = narrative.get("dominant_action", "WAIT")
    
    execution_plan = {
        "template": "No Trade",
        "legs": [],
        "size": narrative.get("risk", {}).get("size", "0R"),
        "invalidation": "N/A",
        "notes": ["Awaiting tradeable regime"]
    }

    if action != "ENTER":
        return execution_plan

    # 1. PINNED RANGE (Dealer Suppression / Neutral Stability)
    if state == "PINNED RANGE":
        execution_plan["template"] = "Iron Condor"
        execution_plan["invalidation"] = "Spot sustains 0.5 ATR beyond structural walls."
        execution_plan["notes"] = ["Range bound regime. Dealer suppression active. Favoring premium collection."]
        execution_plan["legs"] = [
            {"type": "SELL", "opt": "CE", "target": "CALL_WALL"},
            {"type": "BUY",  "opt": "CE", "target": "CALL_WING"},
            {"type": "SELL", "opt": "PE", "target": "PUT_WALL"},
            {"type": "BUY",  "opt": "PE", "target": "PUT_WING"}
        ]
        
    # 2. SUPPRESSED TREND (Long Gamma Directional Grind)
    elif state == "SUPPRESSED TREND":
        execution_plan["template"] = "Debit Spread"
        execution_plan["invalidation"] = "Structural drift reversal or GEX flip."
        execution_plan["notes"] = ["Institutional directional grind. Movement suppressed by dealer positioning."]
        
        direction = narrative.get("dominant_state_direction", "BULLISH")
        if hasattr(ctx, "meta"):
            drift = ctx.meta.get("drift", 0.0)
        else:
            auto = ctx.get("auto_metrics", {})
            drift = auto.get("drift", 0.0)
        opt_type = "CE" if drift > 0 else "PE"
        
        execution_plan["legs"] = [
            {"type": "BUY",  "opt": opt_type, "target": "ATM"},
            {"type": "SELL", "opt": opt_type, "target": "DELTA_0_25"}
        ]
        
    # 3. EXPANSIVE TREND (Short Gamma Breakout)
    elif state == "EXPANSIVE TREND":
        execution_plan["template"] = "Straddle"
        execution_plan["invalidation"] = "Volatility crush (IV < RV shift) or mean reversion."
        execution_plan["notes"] = ["Gamma expansion regime. Dealer amplification active. Favoring convexity."]
        execution_plan["legs"] = [
            {"type": "BUY", "opt": "CE", "target": "ATM"},
            {"type": "BUY", "opt": "PE", "target": "ATM"}
        ]
        
    # 4. LIQUIDITY VACUUM (Momentum / Air-Pocket)
    elif state == "LIQUIDITY VACUUM":
        execution_plan["template"] = "Debit Spread"
        execution_plan["invalidation"] = "Velocity reversal or Wall recapture."
        execution_plan["notes"] = ["Directional vacuum. Air-pocket movement expected. High momentum."]
        
        if hasattr(ctx, "meta"):
            drift = ctx.meta.get("drift", 0.0)
        else:
            auto = ctx.get("auto_metrics", {})
            drift = auto.get("drift", 0.0)
        opt_type = "CE" if drift > 0 else "PE"
        
        # More aggressive target for vacuum
        execution_plan["legs"] = [
            {"type": "BUY",  "opt": opt_type, "target": "ATM"},
            {"type": "SELL", "opt": opt_type, "target": "DELTA_0_25"}
        ]
        
    return execution_plan
