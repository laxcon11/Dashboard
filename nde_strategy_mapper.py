def map_strategy(ctx: dict, narrative: dict) -> dict:
    """
    Strategy Mapping Engine
    Translates the dominant state from the narrative into a concrete execution template.
    Returns an execution plan with symbolic strike rules, which the compiler will resolve.
    """
    state = narrative.get("dominant_state", "NEUTRAL")
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

    if state == "PINNED RANGE":
        execution_plan["template"] = "Iron Condor"
        execution_plan["invalidation"] = "Spot closes > 0.5 ATR beyond Wall"
        execution_plan["notes"] = ["Range bound regime. Selling premium at structural walls."]
        execution_plan["legs"] = [
            {"type": "SELL", "opt": "CE", "target": "CALL_WALL"},
            {"type": "BUY",  "opt": "CE", "target": "CALL_WING"},
            {"type": "SELL", "opt": "PE", "target": "PUT_WALL"},
            {"type": "BUY",  "opt": "PE", "target": "PUT_WING"}
        ]
        
    elif state == "VOLATILITY EXPANSION":
        execution_plan["template"] = "Straddle"
        execution_plan["invalidation"] = "IV Crush / Spot remains pinned near entry"
        execution_plan["notes"] = ["Volatility expansion expected. Long gamma setup."]
        execution_plan["legs"] = [
            {"type": "BUY", "opt": "CE", "target": "ATM"},
            {"type": "BUY", "opt": "PE", "target": "ATM"}
        ]
        
    elif state == "LIQUIDITY VACUUM":
        execution_plan["template"] = "Debit Spread"
        execution_plan["invalidation"] = "Momentum failure / Trend reversal"
        execution_plan["notes"] = ["Directional vacuum setup. Using debit spread to define risk."]
        # Assume Call spread if drift is positive, else Put spread
        auto = ctx.get("auto_metrics", {})
        drift = auto.get("drift", 0.0)
        opt_type = "CE" if drift > 0 else "PE"
        
        execution_plan["legs"] = [
            {"type": "BUY",  "opt": opt_type, "target": "DELTA_0_50"},
            {"type": "SELL", "opt": opt_type, "target": "DELTA_0_25"}
        ]
        
    return execution_plan
