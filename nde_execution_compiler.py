import math
import pandas as pd
from nde_strategy_mapper import map_strategy

def select_strike_by_delta(df_chain, opt_type: str, target_abs_delta: float, spot: float):
    """
    Select strike closest to target delta.
    df_chain: normalized option chain with columns:
        ["strike","type","delta","oi","bid","ask"] (bid/ask optional)
    opt_type: "CE" or "PE"
    target_abs_delta: e.g., 0.25, 0.50
    """
    if df_chain is None or len(df_chain) == 0:
        return None
        
    # normalize type labels
    t = "call" if opt_type == "CE" else "put"
    sub = df_chain[df_chain["type"] == t].copy()
    
    if sub.empty or "delta" not in sub.columns:
        return None
        
    sub = sub.dropna(subset=["delta"])
    if sub.empty:
        return None
        
    # --- sign handling ---
    # calls: delta ~ + (0→1), puts: delta ~ − (0→−1)
    if opt_type == "CE":
        sub["delta_abs"] = sub["delta"].clip(lower=0)
    else:
        sub["delta_abs"] = (-sub["delta"]).clip(lower=0)
        
    # --- basic liquidity filter ---
    if "oi" in sub.columns:
        sub = sub[sub["oi"] >= sub["oi"].quantile(0.30)]  # drop illiquid tail
        
    # optional spread filter
    if {"bid", "ask"}.issubset(sub.columns):
        sub["spread"] = (sub["ask"] - sub["bid"]).abs()
        sub = sub[sub["spread"] <= sub["spread"].quantile(0.70)]
        
    if sub.empty:
        return None
        
    # --- distance to target ---
    sub["score"] = (sub["delta_abs"] - target_abs_delta).abs()
    
    # prefer strikes not too far from spot
    sub["dist"] = (sub["strike"] - spot).abs()
    sub = sub.sort_values(["score", "dist"])
    
    return int(sub.iloc[0]["strike"])

def resolve_strike(target: str, opt: str, spot: float, call_wall: float, put_wall: float, atr: float, df_chain=None) -> int:
    """
    Strike Selection Engine
    Resolves symbolic targets into concrete strike prices based on structural and volatility rules.
    """
    # Safety rounding function
    def nearest_50(val):
        try:
            return int(round(float(val) / 50.0) * 50)
        except (ValueError, TypeError):
            return int(round(spot / 50.0) * 50)

    atm = nearest_50(spot)
    wing_width = max(50, nearest_50(atr * 0.75)) # approx 0.75 ATR for wings

    # -------------------------
    # REAL DELTA PATH (NEW)
    # -------------------------
    if target in ("DELTA_0_25", "DELTA_0_50") and df_chain is not None:
        tgt = 0.25 if target == "DELTA_0_25" else 0.50
        strike = select_strike_by_delta(df_chain, opt, tgt, spot)
        if strike:
            return nearest_50(strike)
            
    # -------------------------
    # EXISTING LOGIC (fallback)
    # -------------------------
    if target == "ATM" or target == "DELTA_0_50":
        return atm
        
    elif target == "CALL_WALL":
        # Short strike ≈ walls
        return nearest_50(call_wall if call_wall and call_wall > spot else spot + atr)
        
    elif target == "PUT_WALL":
        # Short strike ≈ walls
        return nearest_50(put_wall if put_wall and put_wall < spot else spot - atr)
        
    elif target == "CALL_WING":
        # Wings ≈ 0.5–1 ATR beyond shorts
        base_wall = call_wall if call_wall and call_wall > spot else spot + atr
        return nearest_50(base_wall + wing_width)
        
    elif target == "PUT_WING":
        # Wings ≈ 0.5–1 ATR beyond shorts
        base_wall = put_wall if put_wall and put_wall < spot else spot - atr
        return nearest_50(base_wall - wing_width)
        
    elif target == "DELTA_0_25":
        # Approximation: 0.25 delta is roughly 0.5 ATR OTM
        offset = nearest_50(atr * 0.5)
        return atm + offset if opt == "CE" else atm - offset

    # Fallback
    return atm

def compute_position_size(confidence: float, vol_regime: str) -> str:
    base = 1.0
    if confidence < 0.5:
        base *= 0.5
    if vol_regime == "EXPLOSIVE" or vol_regime == "VOLATILITY EXPANSION":
        base *= 0.5
    return f"{round(base, 2)}R"

def build_execution(ctx: dict, narrative: dict) -> dict:
    """
    Execution Compiler
    Orchestrates the Strategy Mapper and Strike Selection Engine.
    Ensures a valid execution plan dictionary is ALWAYS returned.
    """
    confidence = narrative.get("confidence", 0)
    dominant_action = narrative.get("dominant_action", "")
    dominant_state = narrative.get("dominant_state", "")
    
    if confidence < 0.35 or dominant_action == "WAIT":
        return {
            "template": "No Trade",
            "legs": [],
            "size": "0R",
            "invalidation": "Low confidence or degraded data",
            "notes": ["Execution suppressed due to low confidence or WAIT action."]
        }

    # 1. Map strategy blueprint
    execution_plan = map_strategy(ctx, narrative)
    
    # Validation safety
    if not isinstance(execution_plan, dict):
        execution_plan = {"template": "No Trade", "legs": [], "size": "0R", "invalidation": "N/A", "notes": ["Invalid mapping output"]}
        
    # Extract Context
    spot = ctx.get("spot", 0)
    if not isinstance(spot, (int, float)) or math.isnan(float(spot)) or spot <= 0:
        spot = 24000.0

    walls = ctx.get("walls", (None, None))
    call_wall, put_wall = walls[0], walls[1]
    
    auto = ctx.get("auto_metrics", {})
    atr = auto.get("atr_proxy", 250.0)
    if atr is None or math.isnan(float(atr)) or atr <= 0:
        atr = 250.0

    # 👉 NEW: pass chain
    df_chain = ctx.get("option_chain_df")  # IMPORTANT: attach this in engine

    # 2. Strike Selection
    resolved_legs = []
    for leg in execution_plan.get("legs", []):
        try:
            target = leg.pop("target", "ATM")
            opt_type = leg.get("opt", "CE")
            
            # Resolve strike based on rules
            concrete_strike = resolve_strike(
                target, opt_type, spot, call_wall, put_wall, atr,
                df_chain=df_chain
            )
            leg["strike"] = concrete_strike
            resolved_legs.append(leg)
        except Exception:
            continue # Skip invalid legs safely
            
    execution_plan["legs"] = resolved_legs
    execution_plan["size"] = compute_position_size(confidence, dominant_state)
    
    return execution_plan

def build_payoff(execution_plan: dict) -> dict:
    """
    Payoff Engine
    Generates a structural payoff summary aligned perfectly with the execution plan.
    """
    template = execution_plan.get("template", "No Trade")
    legs = execution_plan.get("legs", [])
    
    payoff_summary = {
        "max_risk": "N/A",
        "max_reward": "N/A",
        "breakevens": [],
        "structure": template
    }
    
    if template == "No Trade" or not legs:
        return payoff_summary
        
    try:
        if template == "Iron Condor":
            # 4 legs. Defined risk and reward.
            sell_ce = next((l["strike"] for l in legs if l["type"] == "SELL" and l["opt"] == "CE"), 0)
            sell_pe = next((l["strike"] for l in legs if l["type"] == "SELL" and l["opt"] == "PE"), 0)
            payoff_summary["max_risk"] = "Defined (Wing Width - Premium)"
            payoff_summary["max_reward"] = "Defined (Net Premium Received)"
            if sell_ce and sell_pe:
                payoff_summary["breakevens"] = [f"<{sell_pe}", f">{sell_ce}"]
                
        elif template == "Straddle":
            atm = next((l["strike"] for l in legs), 0)
            payoff_summary["max_risk"] = "Defined (Debit Paid)"
            payoff_summary["max_reward"] = "Unlimited"
            if atm:
                payoff_summary["breakevens"] = [f"<{atm} - Debit", f">{atm} + Debit"]
                
        elif template == "Debit Spread":
            buy_leg = next((l["strike"] for l in legs if l["type"] == "BUY"), 0)
            sell_leg = next((l["strike"] for l in legs if l["type"] == "SELL"), 0)
            payoff_summary["max_risk"] = "Defined (Net Debit Paid)"
            payoff_summary["max_reward"] = "Defined (Spread Width - Debit)"
            if buy_leg and sell_leg:
                direction = ">" if sell_leg > buy_leg else "<"
                payoff_summary["breakevens"] = [f"{direction} {buy_leg} +/- Debit"]
                
    except Exception:
        pass # Graceful degradation
        
    return payoff_summary
