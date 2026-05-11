import logging
import math
import pandas as pd
from typing import Tuple, Any, Dict
import NSE_Config
import nde_options_logic

logger = logging.getLogger(__name__)

STRATEGY_TEMPLATES = {
    "IRON_CONDOR": {"name": "Iron Condor", "why": "Delta-neutral income setup."},
    "DEBIT_SPREAD": {"name": "Debit Spread", "why": "Directional breakout setup."},
    "CREDIT_SPREAD": {"name": "Credit Spread", "why": "Income-focused fade setup."},
    "STRADDLE": {"name": "Long Straddle", "why": "Pure volatility expansion play."}
}

def is_strike_viable(raw_exp: pd.DataFrame, strike: float, o_type: str, spot: float, dte: int, min_premium=5.0) -> Tuple[bool, str]:
    """Enforce Premium/Liquidity Viability for a specific strike."""
    if raw_exp is None or raw_exp.empty:
        return False, "No chain data"
        
    row = raw_exp[(raw_exp["strike"] == strike) & (raw_exp["type"].str.upper() == o_type.upper())]
    if row.empty:
        return False, f"Strike {strike} {o_type} not found"
        
    ltp = float(row["ltp"].iloc[0])
    if ltp < min_premium:
        return False, f"Premium too low ({ltp:.1f} < {min_premium})"
        
    return True, "OK"

def validate_strikes(plan: dict, spot: float, atr: float, source_mode: str) -> dict:
    """Institutional Guardrail: Final safety check on execution strikes."""
    if "DEGRADED" in str(source_mode).upper():
        plan["suppressed"] = True
        plan["reason"] = "Data integrity failure. Blocked."
    return plan

def generate_trade_template(strategy: str, spot: float, walls: tuple, atr: float, raw_exp: pd.DataFrame = None) -> dict:
    """
    Generates tactical strike selection templates based on structural walls.
    """
    c_wall, p_wall, sec_c, sec_p = walls
    
    if strategy == "MEAN_REVERSION":
        sell_c = nde_options_logic.snap_to_nearest_strike(c_wall, raw_exp)
        sell_p = nde_options_logic.snap_to_nearest_strike(p_wall, raw_exp)
        return {
            "template": "IRON_CONDOR",
            "sell_ce": sell_c,
            "sell_pe": sell_p,
            "buy_ce": sell_c + 100,
            "buy_pe": sell_p - 100
        }
    
    if strategy == "TREND_ACCELERATION":
        atm = nde_options_logic.snap_to_nearest_strike(spot, raw_exp)
        return {
            "template": "STRADDLE",
            "buy_ce": atm,
            "buy_pe": atm
        }
        
    return {"template": "NONE"}

def generate_strategy_playbook(ctx: dict) -> dict:
    """
    Execution Orchestrator.
    Constructs the final trade playbook with strikes and confidence.
    """
    strategy_code = ctx.get("strategy_code", "NO_TRADE")
    spot = ctx.get("spot", 0)
    walls = ctx.get("walls", (spot+500, spot-500))
    atr = ctx.get("flow_metrics", {}).get("atr_proxy", 250.0)
    raw_exp = ctx.get("flow_metrics", {}).get("raw_exposures", pd.DataFrame())
    
    template = generate_trade_template(strategy_code, spot, walls, atr, raw_exp)
    
    return {
        "strategy": strategy_code,
        "template": template,
        "confidence": ctx.get("master_setup", {}).get("confidence", 0.0),
        "action": ctx.get("master_setup", {}).get("action", "WAIT")
    }
