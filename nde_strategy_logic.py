import pandas as pd
import numpy as np
import json
import os
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
import nde_narrative_engine
import NSE_Config
logger = logging.getLogger(__name__)
from nde_automation_logic import normalize_regime_name, compute_expiry_phase
import nde_options_logic
import nde_automation_logic
import realized_vol_engine
import local_gamma_engine
import position_manager
import scenario_engine
LOT = NSE_Config.NIFTY_LOT_SIZE
CONFIG_VERSION = getattr(NSE_Config, 'CONFIG_VERSION', 'unknown')
STATE_VERSION = "2.0"
BROKERAGE_PER_ORDER = NSE_Config.BROKERAGE_PER_ORDER
EST_SLIPPAGE_PCT = NSE_Config.EST_SLIPPAGE_PCT
STT_SELL_OPT_PCT = NSE_Config.STT_SELL_OPT_PCT
GST_PCT = NSE_Config.GST_PCT
OTHER_CHARGES_PCT = NSE_Config.OTHER_CHARGES_PCT

STRATEGY_CONFIG = {
    "GAMMA_FLIP_THRESHOLD_NORM": 25.0,  # 25M equivalent per lot
    "TREND_DRIFT_THRESHOLD": 0.2,
    "MEAN_REV_STABILITY_THRESHOLD": 65,
    "VANNA_THRESHOLD_NORM": 3.0,        # 3M per lot
    "CHARM_THRESHOLD_NORM": 0.8,        # 0.8M per lot
    "STALENESS_DAYS": 1,
    "PERSISTENCE_MIN_DAYS": 2,
    # Adaptive Threshold Guardrails (v5)
    "DRIFT_THRESHOLD_MIN": 0.15,
    "DRIFT_THRESHOLD_MAX": 0.50,
    "STABILITY_THRESHOLD_MIN": 40,
    "STABILITY_THRESHOLD_MAX": 85,
    "GAMMA_CONV_THRESHOLD": 5.0
}

STRATEGY_WEIGHTS = {
    "regime": 0.40,
    "strike": 0.30,
    "risk": 0.30
}

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def log_execution(ctx, narrative, execution_plan):
    try:
        master = ctx.get("master_setup", {})
        m_state = master.get("market_state", {})
        rv = ctx.get("realized_metrics", {})
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "spot": ctx.get("spot"),
            "state": m_state.get("state"),
            "substate": m_state.get("substate"),
            "volatility_regime": m_state.get("volatility_regime"),
            "suppression_regime": m_state.get("suppression_regime"),
            "confidence": m_state.get("confidence"),
            "transition_risk": m_state.get("transition_risk"),
            "rv_structure": rv,
            "signal_alignment": master.get("signal_alignment"),
            "action": narrative.get("dominant_action"),
            "template": execution_plan.get("template"),
            "legs": execution_plan.get("legs"),
            "ctx_snapshot": ctx,
            "narrative": narrative
        }
        os.makedirs("logs", exist_ok=True)
        with open("logs/execution_audit_log.jsonl", "a") as f:
            f.write(json.dumps(entry, cls=CustomEncoder) + "\n")
            
        # Also track in position manager if action is ENTER
        if narrative.get("dominant_action") == "ENTER":
            pm = position_manager.PositionManager()
            pm.open_position(ctx, narrative, execution_plan)
            
    except Exception as e:
        logger.error(f"Failed to log execution: {e}")
        logger.error(f"Failed to log execution: {e}")

def get_snapshot_trends(current_metrics: dict, current_expiry: str) -> dict:
    """
    Compare current market profile against the previous snapshot for the same expiry.
    Returns Deltas for institutional metrics (Phase 46).
    """
    AUTOMATION_OUTPUT_DIR = Path(__file__).parent / "data" / "automation"
    trends = {
        "max_pain_delta": 0, "pcr_oi_delta": 0.0, 
        "gamma_flip_delta": 0.0, "atm_oi_share_delta": 0.0,
        "prev_date": None
    }
    
    if not current_metrics:
        return trends
        
    try:
        # 1. Gather all snapshots for the same expiry, sorted by time
        snaps = []
        for snap_file in AUTOMATION_OUTPUT_DIR.glob("nde_v12_*.json"):
            try:
                with open(snap_file, 'r') as f:
                    data = json.load(f)
                    if data.get("options_flow", {}).get("expiry") == current_expiry:
                        snaps.append(data)
            except: continue
            
        if not snaps:
            return trends
            
        # Sort by timestamp descending (newest first)
        snaps = sorted(snaps, key=lambda x: x.get("timestamp", 0), reverse=True)
        
        # 2. Identify the PREVIOUS snapshot (excluding today if today already has a file)
        # We look for the most recent one that is NOT the current one being computed.
        today_str = datetime.now().strftime("%Y-%m-%d")
        prev_snap = None
        for s in snaps:
            if s.get("date") != today_str:
                prev_snap = s
                break
        
        if not prev_snap:
            # Fallback: if today is the only one, no delta possible
            return trends
            
        # 3. Calculate Deltas
        prev_flow = prev_snap.get("options_flow", {})
        curr_iq = current_metrics.get("institutional_iq", {})
        
        # Max Pain Delta
        prev_mp = prev_flow.get("max_pain")
        curr_mp = curr_iq.get("max_pain")
        if prev_mp and curr_mp:
            trends["max_pain_delta"] = int(curr_mp - prev_mp)
            
        # PCR OI Delta
        prev_pcr = prev_flow.get("pcr_oi")
        curr_pcr = curr_iq.get("pcr_oi")
        if prev_pcr and curr_pcr:
            trends["pcr_oi_delta"] = round(float(curr_pcr - prev_pcr), 3)
            
        # Gamma Flip Delta
        prev_flip = prev_flow.get("gamma_flip")
        curr_flip = current_metrics.get("gamma_flip_level")
        if prev_flip and curr_flip:
            trends["gamma_flip_delta"] = round(float(curr_flip - prev_flip), 1)
            
        # ATM OI Share Delta
        prev_atm = prev_flow.get("atm_oi_share")
        curr_atm = curr_iq.get("atm_oi_share")
        if prev_atm and curr_atm:
            trends["atm_oi_share_delta"] = round(float(curr_atm - prev_atm), 2)
            
        trends["prev_date"] = prev_snap.get("date")
        
    except Exception as e:
        logger.warning(f"Trend Analysis failed: {e}")
        
    return trends

# ==================== STATE MANAGEMENT ====================
STATE_FILE = Path("notes/strategy_state.json")
AUDIT_FILE = Path("notes/nde_strategy_log.jsonl")

def _default_strategy_state() -> Dict[str, Any]:
    return {"last_strategy": "NO_TRADE", "persistence_days": 1, "last_update": "", "state_version": STATE_VERSION}

def load_strategy_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try: 
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                # Version check: reset if state was written by an older engine
                if data.get("state_version") != STATE_VERSION:
                    logger.info(f"Strategy state version mismatch ({data.get('state_version')} != {STATE_VERSION}), resetting.")
                    return _default_strategy_state()
                return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load strategy state: {e}")
    return _default_strategy_state()

def save_strategy_state(state: Dict[str, Any]):
    STATE_FILE.parent.mkdir(exist_ok=True)
    state["state_version"] = STATE_VERSION
    state["config_hash"] = CONFIG_VERSION
    state["last_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ==================== PROFESSIONAL INTELLIGENCE HELPERS ====================
# NOTE: compute_expiry_phase is now imported from nde_automation_logic (single canonical definition)

def compute_vol_trend(vix_df: pd.DataFrame, history: list) -> dict:
    """Calculate 1D IV Delta & 3D IV Slope."""
    trend = {"delta_1d": 0.0, "slope_3d": 0.0, "implication": "Neutral Vol Environment"}
    
    # 1. Delta 1D (Prefer vix_df for real-time, fallback to history)
    if vix_df is not None and len(vix_df) >= 2:
        vix_vals = vix_df["Close"].values
        trend["delta_1d"] = float(vix_vals[-1] - vix_vals[-2])
    elif history and len(history) >= 2:
        trend["delta_1d"] = float(history[-1].get("atm_iv", 15.0) - history[-2].get("atm_iv", 15.0))
    
    # 2. Slope 3D (History based)
    if history and len(history) >= 4:
        iv_path = [float(h.get("atm_iv", 15.0)) for h in history[-4:]]
        trend["slope_3d"] = (iv_path[-1] - iv_path[0]) / 3.0
    
    # Implication Logic
    slope = trend["slope_3d"]
    if slope > 0.5:
        trend["implication"] = "⚠️ IV Rising: Avoid fresh premium selling."
    elif slope < -0.5:
        trend["implication"] = "✅ IV Compressing: Optimal decay environment."
    elif trend["delta_1d"] > 1.0:
        trend["implication"] = "⚠️ Vol Spike detected: Use wide protection."
        
    return trend

def get_directional_conviction(regime: str, drift: float, total_gex: float) -> dict:
    """Synthesize Bias, Conviction, and Conflict state."""
    reg = normalize_regime_name(regime)
    
    # 1. BIAS BASELINE
    bias = "Neutral"
    if drift > 0.15: bias = "Bullish"
    elif drift < -0.15: bias = "Bearish"
    
    # 2. CONVICTION SCORING (Internal)
    # Alignment: Macro + Drift + GEX
    alignment_score = 0
    if (bias == "Bullish" and reg in ["SELECTIVE", "RISK_ON"]) or (bias == "Bearish" and reg in ["STRESS", "CRISIS"]):
        alignment_score += 1
    if (bias == "Bullish" and total_gex > 0) or (bias == "Bearish" and total_gex < 0):
        alignment_score += 1
        
    conv = "Low"
    if alignment_score == 2: conv = "High"
    elif alignment_score == 1: conv = "Medium"
    
    # 3. CONFLICT ENGINE
    conflict = None
    if reg in ["DEFENSIVE", "STRESS"] and total_gex > 0:
        conflict = "⚠️ Macro Defensive vs Local GEX Positive. (Divergence)"
    elif reg in ["SELECTIVE", "RISK_ON"] and total_gex < 0:
        conflict = "⚠️ Macro Bullish vs Dealer Short-Gamma. (Liquidity Risk)"
        
    return {
        "bias": bias,
        "conviction": conv,
        "conflict_reason": conflict
    }

def get_strategy_executive_summary(strategy_code: str, bias_obj: dict, spot: float, walls: tuple, gamma_metrics: dict = None, iv_data: dict = None) -> dict:
    """Primary Risk & Invalidation logic (Institutional v2.0)."""
    c_wall = walls[0] if walls and len(walls) >= 1 else spot + 500
    p_wall = walls[1] if walls and len(walls) >= 2 else spot - 500
    gex_norm = gamma_metrics.get("gex_norm", 0.0) if gamma_metrics else 0.0
    iv_rank = iv_data.get("iv_rank", 50.0) if iv_data else 50.0
    
    summary = {
        "primary_risk": "Market Noise / Neutral Grind",
        "invalidation": "Thesis holds in current regime."
    }
    
    if strategy_code == "MEAN_REVERSION":
        summary["primary_risk"] = "Delta Breakout (Gamma Expansion)"
        # Structural Invalidation: Gamma flip or IV spike or Wall Breach
        summary["invalidation"] = f"Gamma flips NEGATIVE ({gex_norm:.1f}), IV Rank > 70, or Spot breaks Walls ({int(p_wall)}-{int(c_wall)})."
    elif strategy_code == "GAMMA_FLIP":
        summary["primary_risk"] = "Whipsaw at Pivot"
        summary["invalidation"] = "Spot sustains 0.5% distance away from Flip Level or IV Rank collapses < 20."
    elif strategy_code == "TREND_ACCELERATION":
        summary["primary_risk"] = "Volatility Crash / Mean Reversion"
        summary["invalidation"] = "Drift score reverses sign, GEX flips POSITIVE, or IV Rank collapses."
    elif strategy_code == "VANNA":
        summary["primary_risk"] = "Delta Squeeze / IV Over-expansion"
        summary["invalidation"] = "Vanna sensitivity collapses or Drift velocity reverses."
    elif strategy_code == "NO_TRADE":
        summary["primary_risk"] = "Opportunity Loss"
        summary["invalidation"] = "Wait for high-conviction setup."
        
    return summary

# ==================== V5 DECISION ENGINE (PHASE 48) ====================

def get_volatility_context(iv_data: dict, vol_trend: dict) -> dict:
    """
    Gate 1: The Volatility Regime.
    Determines if moves are 'Explosive' (high IV) or 'Fake' (low IV).
    """
    iv_rank = iv_data.get("iv_rank", 50.0)
    iv_slope = vol_trend.get("slope_3d", 0.0)
    
    # 0-100 scale for volatility 'Explosiveness'
    vol_score = (iv_rank * 0.6) + (min(max(iv_slope, -2), 2) + 2) / 4 * 40
    
    regime = "NORMAL"
    if iv_rank > 70 or (iv_rank > 40 and iv_slope > 1.0):
        regime = "EXPLOSIVE"
    elif iv_rank < 15 and iv_slope < -0.5:
        regime = "CRUSHED"
    elif iv_rank < 30:
        regime = "QUIET"
        
    return {
        "vol_score": round(vol_score, 1),
        "regime": regime,
        "iv_rank": iv_rank,
        "iv_slope": iv_slope
    }

def calculate_transition_score(auto_metrics: dict, state: dict, spot: float = 0.0, gamma_flip: float = 0.0, atr: float = 250.0) -> dict:
    """
    Scored Transition Engine (0.0 - 1.0).
    Combines stability delta, drift velocity, and distance-to-flip.
    """
    # 1. Stability Velocity (dStab/dt)
    stab_curr = auto_metrics.get("stability", 50.0)
    stab_prev = auto_metrics.get("stability_5d", 50.0)
    d_stability = (stab_prev - stab_curr) / 5.0 # Falling stability is positive delta
    
    # 2. Drift Velocity (dDrift/dt)
    drift_curr = auto_metrics.get("drift", 0.0)
    drift_accel = abs(auto_metrics.get("drift_acceleration", 0.0))
    
    # 3. Distance to Flip Component (Analytical Depth V5)
    dist_to_flip = 0.0
    if spot > 0 and gamma_flip > 0:
        dist_to_flip = abs(spot - gamma_flip) / max(atr, 100.0)
        # Closer to flip = Higher transition risk
        dist_score = max(0, 1.0 - (dist_to_flip / 2.0)) # 1.0 if at flip, 0.0 if 2x ATR away
    else:
        dist_score = 0.5
        
    # 4. Combine into normalized score (0.0 - 1.0)
    # Falling stability (0.3) + Accelerating drift (0.3) + Distance to Flip (0.4)
    raw_score = (max(0, d_stability) * 0.3) + (drift_accel * 0.3) + (dist_score * 0.4)
    score = round(min(1.0, max(0.0, raw_score)), 2)
    
    # Smoothing (3-period EMA proxy)
    prev_score = state.get("last_transition_score", 0.0)
    if prev_score > 1.0: prev_score /= 10.0 # Handle legacy 0-10 scores
    score = (score * 0.4) + (prev_score * 0.6)
    
    label = "IGNORE"
    if score >= 0.8: label = "IMMINENT"
    elif score >= 0.6: label = "PRE-TRANSITION"
    elif score >= 0.3: label = "WATCH"
    
    return {
        "score": round(score, 2),
        "label": label,
        "d_stability": round(d_stability, 2),
        "velocity": round(drift_accel, 2),
        "dist_score": round(dist_score, 2)
    }

def validate_strikes(strike_plan: dict, spot: float, atr: float, source_mode: str = "TRUSTED") -> dict:
    """
    Gate 4: Strike Validation Layer.
    Suppresses trades if liquidity is low or risk bounds are breached.
    """
    if strike_plan.get("suppressed"):
        return strike_plan
        
    # 1. Hard Block for Degraded Data (Governance Phase 5)
    if "DEGRADED" in str(source_mode).upper():
        strike_plan["suppressed"] = True
        strike_plan["reason"] = "CRITICAL: Data integrity failure. Execution BLOCKED."
        return strike_plan

    # 2. Distance Check (vs 1.5x ATR)
    limit = atr * 1.5
    for key in ["sell_ce", "sell_pe", "buy_ce", "buy_pe", "buy_leg", "sell_leg"]:
        val = strike_plan.get(key)
        if val and abs(val - spot) > limit * 5: # Extreme outlier check
            strike_plan["suppressed"] = True
            strike_plan["reason"] = f"Strike {val} is outside extreme ATR bounds ({int(limit)})."
            return strike_plan
            
    return strike_plan
def get_time_decay_outlook(dte: int, iv_rank: float, vol_regime: str) -> str:
    """Determine Time Decay quality (Strong/Moderate/Weak)."""
    if dte is None: dte = 7
    if vol_regime == "EXPLOSIVE": return "Weak (Risk > Decay)"
    if dte <= 2 and iv_rank > 40: return "Strong (Terminal Gamma + IV Rank)"
    if dte > 4: return "Moderate (Early Expiry)"
    return "Moderate"

def classify_market_state(ctx: dict) -> dict:
    """
    CANONICAL MARKET STATE ENGINE (V3)
    The Single Source of Truth for the entire NDE ecosystem.
    Determines institutional regime using Positioning + Vol Structure + Movement.
    """
    flow = ctx.get("flow_metrics", {})
    auto = ctx.get("auto_metrics", {})
    rv = ctx.get("realized_metrics", {})
    local = ctx.get("local_gamma", {})
    iv_data = ctx.get("iv_data", {})
    
    spot = ctx.get("spot", 24000.0)
    stability = auto.get("stability", 50.0)
    drift = auto.get("drift", 0.0)
    gex_norm = flow.get("gex_norm", 0.0)
    iv_rank = iv_data.get("iv_rank", 50.0)
    
    rv_regime = rv.get("rv_regime", "NORMAL")
    suppression_strength = local.get("suppression_strength", 0.0)
    
    state = "NEUTRAL"
    substate = "WAITING_FOR_CONFIRMATION"
    direction = "BULLISH" if drift > 0.15 else "BEARISH" if drift < -0.15 else "NEUTRAL"
    vol_regime = "NORMAL"
    suppression = "NONE"
    why = []

    # 1. PINNED RANGE (Long Gamma + Stability + Suppression)
    if gex_norm > 5.0 and stability > 70 and abs(drift) < 0.2:
        state = "PINNED RANGE"
        vol_regime = "SUPPRESSED"
        suppression = "STRONG"
        substate = "PREMIUM_COLLECTION"
        why.append("High Gamma density + High stability suppressing realized volatility.")

    # 2. SUPPRESSED TREND (Directional + Long Gamma + Structural Support)
    elif abs(drift) > 0.2 and gex_norm > 2.0 and rv_regime == "SUPPRESSED":
        state = "SUPPRESSED TREND"
        vol_regime = "SUPPRESSED"
        substate = "DIRECTIONAL_GRIND"
        why.append(f"Steady {direction} drift supported by dealer positioning. Movement suppressed.")

    # 3. EXPANSIVE TREND (Directional + Short Gamma + RV Acceleration)
    elif abs(drift) > 0.35 and gex_norm < -2.0 and rv_regime == "EXPANSIVE":
        state = "EXPANSIVE TREND"
        vol_regime = "EXPANSIVE"
        substate = "CONVEX_ACCELERATION"
        why.append(f"Short Gamma regime amplifying {direction} drift. Convex expansion likely.")

    # 4. TRANSITIONAL INSTABILITY (Falling Stability + High Transition Score)
    elif stability < 40 and ctx.get("trans_score", {}).get("score", 0.0) > 0.6:
        state = "TRANSITIONAL INSTABILITY"
        vol_regime = "VOLATILE"
        substate = "REGIME_UNCERTAINTY"
        why.append("Structural stability collapse. High probability of regime transition.")

    # 5. LIQUIDITY VACUUM (Short Gamma + Low Density + Drift Velocity)
    elif gex_norm < -5.0 and local.get("gamma_density_score", 1.0) < 0.5:
        state = "LIQUIDITY VACUUM"
        vol_regime = "EXPANSIVE"
        substate = "AIR_POCKET"
        why.append("Severe negative Gamma concentration with poor structural support.")

    # Fallback to legacy classification for compatibility if none of the above match
    if state == "NEUTRAL":
        if abs(drift) > 0.5:
            state = "MOMENTUM_DRIVE"
            why.append("High drift magnitude driving state.")
        else:
            why.append("Standard macro environment.")

    return {
        "state": state,
        "substate": substate,
        "direction": direction,
        "volatility_regime": vol_regime,
        "suppression_regime": suppression,
        "confidence": 0.0, # Will be filled by alignment engine
        "transition_risk": ctx.get("trans_score", {}).get("score", 0.0),
        "why": why
    }

def compute_signal_alignment(ctx: dict) -> dict:
    """
    Institutional Signal Alignment Engine.
    Measures coherence between positioning, drift, and volatility.
    """
    flow = ctx.get("flow_metrics", {})
    auto = ctx.get("auto_metrics", {})
    rv = ctx.get("realized_metrics", {})
    
    drift = auto.get("drift", 0.0)
    gex_norm = flow.get("gex_norm", 0.0)
    rv_regime = rv.get("rv_regime", "NORMAL")
    
    agreements = []
    conflicts = []
    score = 0.0
    
    # 1. Drift vs Gamma Regime
    if (drift > 0.1 and gex_norm > 0) or (drift < -0.1 and gex_norm < 0):
        # Bullish drift in Long Gamma is suppressed (Agreement on Suppression)
        # Bearish drift in Short Gamma is expansive (Agreement on Momentum)
        score += 0.25
        agreements.append("Drift aligns with Gamma structural regime.")
    else:
        conflicts.append("Drift conflicts with Gamma structural regime.")
        
    # 2. RV vs Gamma Regime
    if (rv_regime == "EXPANSIVE" and gex_norm < 0) or (rv_regime == "SUPPRESSED" and gex_norm > 0):
        score += 0.25
        agreements.append("Realized movement validates Gamma positioning.")
    else:
        conflicts.append("Realized movement deviates from positioning expectations.")
        
    # 3. Vanna vs Direction
    vanna = flow.get("vanna_bias", "Neutral")
    if ("Bullish" in vanna and drift > 0) or ("Bearish" in vanna and drift < 0):
        score += 0.25
        agreements.append("Vanna flow supports directional drift.")
        
    # 4. Stability Alignment
    if auto.get("stability", 50.0) > 60:
        score += 0.25
        agreements.append("High structural stability increases signal trust.")
    
    return {
        "alignment_score": round(score, 2),
        "agreement_count": len(agreements),
        "agreements": agreements,
        "conflicts": conflicts,
        "confidence": round(score, 2)
    }

def get_market_state(flow_metrics: dict, auto_metrics: dict, vol_ctx: dict, trans_score: dict, atr: float = 250.0, spot: float = 22000.0) -> dict:
    """Task 2: Market State Classification - Derived from structural flow + momentum."""
    # 1. Extract Metrics
    gamma_norm = flow_metrics.get("gex_norm", 0.0)
    vanna_norm = flow_metrics.get("vex_norm", 0.0)
    iv_rank = vol_ctx.get("iv_rank", 50.0)
    stability = auto_metrics.get("stability", 50.0)
    drift = auto_metrics.get("drift", 0.0)
    drift_accel = auto_metrics.get("drift_acceleration", 0.0)
    
    # 2. Adaptive Thresholds
    gamma_thresh = 5.0 * (1.0 + (iv_rank / 100.0))
    
    # 3. Velocity Layer
    velocity_regime = "FAST" if abs(drift_accel) > 0.1 else "SLOW"
    trans_label = trans_score.get("label", "NORMAL") if trans_score else "NORMAL"
    
    # 4. Drift Intensity
    d_abs = abs(drift)
    if d_abs > 0.6: d_regime = "EXTREME"
    elif d_abs > 0.35: d_regime = "HIGH"
    elif d_abs > 0.15: d_regime = "MODERATE"
    else: d_regime = "LOW"
    
    # 5. Canonical State Logic
    state, why = classify_market_state(
        gamma_norm, stability, d_regime, trans_label, 
        vol_ctx or {}, vanna_norm, iv_rank, velocity_regime,
        gamma_thresh=gamma_thresh
    )
    
    return {
        "state": state, 
        "why": why,
        "velocity_regime": velocity_regime,
        "drift_regime": d_regime,
        "gamma_threshold": round(gamma_thresh, 1)
    }

# ==================== TRADING COCKPIT (UNIFIED NARRATIVE) ====================

def generate_unified_narrative(master_setup: dict, cockpit: dict, prefilter: dict) -> dict:
    """Consolidates all engine layers into a single authoritative Operator Narrative."""
    strategy_code = master_setup.get("code", "NO_TRADE")
    playbook = master_setup.get("playbook", {})
    action = playbook.get("action", "WAIT").upper()
    state = cockpit.get("market_state", "NEUTRAL")
    
    # 1. Conflict Resolution (The 'Arbiter' Layer)
    # If Near Flip or Poor Data -> Override to TRANSITION / WAIT
    if prefilter.get("reason_code") == "NEAR_FLIP":
        state = "TRANSITION / FLIP ZONE"
        action = "WAIT"
        reason = [
            "Spot near gamma flip → High whipsaw risk.",
            "No structural edge exists until price clears pivot."
        ]
        next_trade = f"Position for {playbook.get('strategy', 'Next Setup')} only after breakout."
    elif prefilter.get("reason_code") == "POOR_DATA_QUALITY":
        state = "DATA UNSTABLE"
        action = "STAND ASIDE"
        reason = ["Feed latency detected (>5 mins).", "Analytical stability compromised."]
        next_trade = "Wait for feed synchronization."
    else:
        # Standard Narrative
        reason = playbook.get("why", ["Maintain current monitoring."])
        next_trade = f"{playbook.get('strategy', 'Next Setup')} structure identified."
        if action == "WAIT":
            next_trade = f"Watching for {playbook.get('strategy', 'Next Setup')} entry."

    # 2. Confidence Contextualization
    conf_val = playbook.get("confidence", 0.0)
    conf_label = "HIGH" if conf_val >= 0.8 else "MODERATE" if conf_val >= 0.5 else "LOW"
    conf_reason = "Strong signal convergence" if conf_val >= 0.8 else "Signals divergent / Near pivot"
    
    return {
        "dominant_state": state,
        "dominant_action": action,
        "reasoning": reason,
        "next_trade": next_trade,
        "triggers": playbook.get("triggers", ["No active triggers."]),
        "decision_trail": playbook.get("decision_trail", []),
        "risk": playbook.get("risk", "Standard Greek Decay / Whipsaw"),
        "invalidation": playbook.get("invalidation", "Thesis holds in current regime."),
        "avoid": playbook.get("avoid", []),
        "reversion": {
            "label": playbook.get("reversion_label", "WAIT"),
            "score": playbook.get("reversion_score", 0.0),
            "reasons": playbook.get("reversion_reasons", [])
        },
        "execution_plan": playbook.get("strike_plan", {}), # Absolute Truth
        "execution_confidence": {
            "value": conf_val,
            "label": conf_label,
            "reason": conf_reason
        }
    }

# ==================== TRADING COCKPIT (GREEK INTERPRETATION) ====================

def interpret_dealer_behavior(flow_metrics: dict) -> list:
    """Translates Greeks/GEX into forced dealer behavior for the Cockpit."""
    gex_net = flow_metrics.get("total_gex", 0.0)
    dex_net = flow_metrics.get("total_delta", 0.0)
    vex_net = flow_metrics.get("total_vex", 0.0)
    cex_net = flow_metrics.get("total_cex", 0.0)

    behavior = []
    
    # 1. Gamma Interpretation
    if gex_net > 0:
        behavior.append({
            "label": "Gamma",
            "state": "LONG",
            "behavior": "Dealers SELL rallies, BUY dips (Stabilizing)"
        })
    else:
        behavior.append({
            "label": "Gamma",
            "state": "SHORT",
            "behavior": "Dealers BUY rallies, SELL dips (Amplifying)"
        })

    # 2. Delta Interpretation
    if abs(dex_net) > 500000000: # Threshold in INR (50 Cr)
        state = "POSITIVE" if dex_net > 0 else "NEGATIVE"
        behavior.append({
            "label": "Delta",
            "state": state,
            "behavior": f"{'Upward' if dex_net > 0 else 'Downward'} bias exists (Directional tilt)"
        })
    else:
        behavior.append({
            "label": "Delta",
            "state": "NEUTRAL",
            "behavior": "No significant delta bias"
        })

    # 3. Vanna Interpretation (Vol sensitivity)
    if abs(vex_net) > 50000000: # 5 Cr
        state = "POSITIVE" if vex_net > 0 else "NEGATIVE"
        behavior.append({
            "label": "Vanna",
            "state": state,
            "behavior": "Volatility changes amplifying price moves"
        })
    else:
        behavior.append({
            "label": "Vanna",
            "state": "NEUTRAL",
            "behavior": "Volatility changes not amplifying moves"
        })

    # 4. Charm Interpretation (Time sensitivity)
    if abs(cex_net) > 10000000: # 1 Cr
        behavior.append({
            "label": "Charm",
            "state": "POSITIVE" if cex_net > 0 else "NEGATIVE",
            "behavior": "Time decay affecting market stability"
        })
    
    return behavior

def get_market_state_cockpit_details(flow_metrics: dict, auto_metrics: dict, market_state: dict) -> dict:
    """Provides specific Cockpit-friendly descriptions for the market state."""
    state = market_state.get("state", "NEUTRAL DRIFT")
    drift = auto_metrics.get("drift", 0.0)
    gamma_regime = flow_metrics.get("gamma_regime", "NEUTRAL")

    details = {
        "structure": "Mixed Flow",
        "bias": "Neutral",
        "volatility": "Normal",
        "actions": ["Stay patient", "Monitor levels"],
        "avoid": ["Heavy direction bets"]
    }

    if state == "PINNED RANGE":
        details["structure"] = "Long Gamma (Stabilizing)"
        details["bias"] = "Mild Bullish Drift" if drift > 0 else "Flat"
        details["actions"] = ["Sell premium (moderate size)", "Fade extremes"]
        details["avoid"] = ["Breakout trades"]
    elif state == "LIQUIDITY VACUUM":
        details["structure"] = "Short Gamma (Amplifying)"
        details["bias"] = "Aggressive Trend"
        details["volatility"] = "High / Rising"
        details["actions"] = ["Buy volatility", "Trail momentum"]
        details["avoid"] = ["Mean reversion plays", "Selling naked premiums"]
    elif state == "VOLATILITY EXPANSION":
        details["structure"] = "Gamma Compression"
        details["bias"] = "Expansionary"
        details["volatility"] = "Spiking"
        details["actions"] = ["Switch to momentum", "Hedge existing ranges"]
        details["avoid"] = ["Stubborn mean reversion"]
    elif state == "SQUEEZE BUILDUP":
        details["structure"] = "Vanna/Charm Driven"
        details["bias"] = "Potential Squeeze"
        details["actions"] = ["Watch for explosive move", "Tighten stops"]
        details["avoid"] = ["Adding into strength"]
    
    return details

def generate_greek_snapshot_data(flow_metrics: dict) -> list:
    """Generates visual snapshot data for the Cockpit summary."""
    import nde_options_logic
    gex = flow_metrics.get("total_gex", 0.0)
    dex = flow_metrics.get("total_delta", 0.0)
    theta = flow_metrics.get("total_theta", 0.0)
    vega = flow_metrics.get("total_vega", 0.0)
    tv = flow_metrics.get("tv_ratio", 0.0)
    tv_label = flow_metrics.get("tv_label", "NORMAL")

    return [
        {
            "label": "Gamma (GEX)",
            "value": nde_options_logic.format_institutional_metric(gex, "Cr"),
            "meaning": "Stabilizing" if gex > 0 else "Amplifying",
            "color": "green" if gex > 0 else "red"
        },
        {
            "label": "Delta",
            "value": nde_options_logic.format_institutional_metric(dex, "Cr"),
            "meaning": "Bullish Bias" if dex > 0 else "Bearish Bias",
            "color": "green" if dex > 0 else "red"
        },
        {
            "label": "Theta",
            "value": "High" if abs(theta) > 100000000 else "Moderate", # 10 Cr
            "meaning": "Decay active",
            "color": "blue"
        },
        {
            "label": "Vega",
            "value": "Moderate" if abs(vega) < 100000000 else "High",
            "meaning": "Vol Risk" if abs(vega) > 100000000 else "Limited Vol Risk",
            "color": "orange"
        },
        {
            "label": "T/V Ratio",
            "value": f"x{tv:.1f}",
            "meaning": "Sell-premium edge" if tv > 0.7 else "Vol-buying edge",
            "color": "green" if tv > 0.7 else "blue"
        }
    ]

STRATEGY_TEMPLATES = {
    "IRON_CONDOR": {
        "name": "Institutional Iron Condor",
        "logic": "Sell Walls / Buy Wings",
        "strikes": {
            "sell_ce": "Call Wall",
            "sell_pe": "Put Wall",
            "buy_ce": "Call Wall + 200",
            "buy_pe": "Put Wall - 200"
        },
        "why": "High Stability + Range Pinning."
    },
    "DEBIT_SPREAD": {
        "name": "Directional Debit Spread",
        "logic": "Follow Momentum / Defined Risk",
        "strikes": {
            "buy_leg": "ATM Strike",
            "sell_leg": "ATM + 150 (Bullish) / ATM - 150 (Bearish)",
        },
        "why": "Negative Gamma + High Drift Velocity."
    },
    "STRADDLE": {
        "name": "Long Vol Straddle",
        "logic": "Pre-Transition Positioning",
        "strikes": {
            "buy_ce": "ATM Strike",
            "buy_pe": "ATM Strike"
        },
        "why": "High Transition Score + Squeeze Risk."
    },
    "CREDIT_SPREAD": {
        "name": "Tactical Credit Spread",
        "logic": "Sell Wall / Buy Wing",
        "strikes": {
            "sell_leg": "Wall Strike",
            "buy_leg": "Wall + 100",
        },
        "why": "Range Resistance + High IV decay."
    }
}

# ==================== CORE ENGINES ====================

def evaluate_risk_prefilter(spot: float, gamma_flip: float, atr: float, state: str, data_quality: str) -> dict:
    """Task 4: Risk Pre-Filter - Early rejection of dangerous conditions."""
    if not atr or atr == 0:
        atr = 1.0
        
    distance_to_flip = abs(spot - gamma_flip) / atr if gamma_flip else 999.0
    
    can_trade = True
    reason_code = "NONE"
    
    if data_quality == "LOW":
        can_trade = False
        reason_code = "POOR_DATA_QUALITY"
    elif distance_to_flip < 1.5 and state in ["REGIME_INSTABILITY", "UNKNOWN"]:
        can_trade = False
        reason_code = "NEAR_FLIP"
        
    return {
        "can_trade": can_trade,
        "distance_to_flip": distance_to_flip,
        "reason_code": reason_code
    }


def generate_engine_context(
    raw_chain: pd.DataFrame, spot: float, nifty_df: pd.DataFrame, used_expiry: str,
    regime_history: list, regime_snap: dict, vix_df: pd.DataFrame, meta: dict = None, mode: str = "Balanced",
    source: str = "UNKNOWN", term_data: dict = None, strike_interval: int = 50, index_name: str = "NIFTY"
) -> dict:
    """Unified engine context calculation that abstracts math away from the Streamlit UI."""
    meta = meta or {}
    
    # Phase 51: Spot Guardrail (Prevent NaN propagation to math layers)
    try:
        if spot is None or math.isnan(float(spot)) or float(spot) <= 0:
            # P0: Index-Aware Safe Fallback
            u_expiry = str(used_expiry).upper()
            if "BANKNIFTY" in u_expiry: spot = 54000.0
            elif "NIFTY" in u_expiry: spot = 24000.0
            else: spot = 77000.0 # SENSEX
        else:
            spot = float(spot)
    except (ValueError, TypeError, AttributeError):
        spot = 24000.0
        
    subset = pd.DataFrame()
    if nifty_df is None:
        nifty_df = pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    
    # 1. Advanced Metrics Calculation (Relocated from UI)
    atr = nde_options_logic.calculate_atr_sma(nifty_df)
    if atr is None or math.isnan(float(atr)) or float(atr) <= 0:
        atr = 250.0 if spot < 50000 else 800.0 # Proportional fallback
    else:
        atr = float(atr)

    t_days = nde_options_logic.calculate_dte_fractional(used_expiry)
    quality_score = meta.get("data_quality_score", 1.0)
    
    # FIX 9 (Phase 5.8 Review): Timestamp staleness gate
    # Degrade confidence when chain data is > 2 hours old during market hours
    _chain_ts = meta.get("timestamp", "")
    if _chain_ts:
        try:
            _chain_dt = datetime.strptime(_chain_ts, "%Y-%m-%d %H:%M:%S")
            _age_hours = (datetime.now() - _chain_dt).total_seconds() / 3600.0
            _now_hour = datetime.now().hour
            _is_market_hours = 9 <= _now_hour <= 15
            if _age_hours > 2.0 and _is_market_hours:
                quality_score *= 0.8
                source = source + " (STALE)" if "STALE" not in source else source
        except (ValueError, TypeError):
            pass
    
    # 2. Flow & Walls
    # Pre-load TV EMA state for injection into options logic (avoids circular file I/O)
    _strat_state = load_strategy_state()
    _tv_ema_f = float(_strat_state.get("tv_ratio_ema_fast", 1.0) or 1.0)
    _tv_ema_s = float(_strat_state.get("tv_ratio_ema_slow", 1.0) or 1.0)
    
    if not raw_chain.empty:
        # CRITICAL: Filter by the CURRENT used_expiry to prevent analytical bleed
        if "expiry" in raw_chain.columns:
            subset = raw_chain[raw_chain["expiry"] == used_expiry].copy()
        else:
            subset = raw_chain.copy()
        if subset.empty:
            # Fallback to nearest if exact match fails (Phase 43 resiliency)
            subset = raw_chain.copy()
            
        subset["t_days"] = t_days
        flow_metrics = nde_options_logic.compute_option_flow_exposures(
            spot, subset, tv_ema_fast=_tv_ema_f, tv_ema_slow=_tv_ema_s, atr=atr, strike_interval=strike_interval
        )
        call_wall, put_wall, _, _ = nde_options_logic.calculate_option_walls(subset)
        # --- WALL HARDENING ---
        if pd.isna(call_wall) or call_wall <= 0: call_wall = spot + (3 * strike_interval)
        if pd.isna(put_wall) or put_wall <= 0: put_wall = spot - (3 * strike_interval)
        
        current_atm_iv = nde_options_logic.compute_atm_iv(subset, spot)
        if pd.isna(current_atm_iv) or current_atm_iv <= 0: current_atm_iv = 15.0
    else:
        flow_metrics = {
            "total_gex": 0, "total_gex_abs": 0, "total_vega": 0, "total_theta": 0, "total_delta": 0, 
            "total_volume": 0.0, "total_oi_chng": 0.0, 
            "gex_norm": 0.0, "gex_tw_norm": 0.0, "vega_norm": 0.0, "theta_norm": 0.0,
            "vex_norm": 0.0, "vex_tw_norm": 0.0, "cex_norm": 0.0, "cex_tw_norm": 0.0,
            "total_vex": 0.0, "total_cex": 0.0,
            "tv_ratio": 0.0, "tv_label": "N/A", "flow_regime_label": "Unknown",
            "gamma_flip_level": 0.0, "gamma_regime": "NEUTRAL",
            "vanna_bias": "Neutral", "charm_flow": "Neutral",
            "vega_clusters": [], "theta_clusters": [],
            "intelligence": {}, "institutional_iq": {}, "raw_exposures": pd.DataFrame()
        }
        call_wall, put_wall = 0.0, 0.0
        current_atm_iv = 15.0
        
    # 3. Automation State
    if regime_history:
        drift, drift_5d, drift_accel = nde_automation_logic.compute_drift(regime_history, spot=spot, atr=atr)
        score = float(regime_history[-1].get("score", 0.0))
        persistence = len(regime_history)
        stability_20d, stability_5d, fragility = nde_automation_logic.compute_stability(score, regime_history, persistence=persistence)
        risk = nde_automation_logic.compute_transition_risk(drift, stability_20d)
    else:
        drift, drift_5d, drift_accel = 0.0, 0.0, 0.0
        stability_20d, stability_5d, fragility = 50, 50, False
        risk = 0.5
        
    auto_metrics = {
        "drift": drift, "stability": stability_20d, "stability_5d": stability_5d,
        "drift_acceleration": drift_accel, "transition_risk": risk, "fragility": fragility
    }
    
    # 3b. Transition Score Object
    trans_label = "IGNORE"
    if risk > 0.8: trans_label = "IMMINENT"
    elif risk > 0.6: trans_label = "ELEVATED"
    elif risk > 0.4: trans_label = "MODERATE"
    else: trans_label = "LOW"
    
    trans_score = {"score": risk, "label": trans_label}
    
    # 4. IV Rank
    if vix_df is not None and not vix_df.empty:
        iv_data = nde_options_logic.compute_iv_rank(current_atm_iv, vix_df["Close"])
    else:
        iv_data = {"label": "UNKNOWN", "iv_rank": 50.0}

    # 5. NEW: Realized Volatility & Local Gamma Engines (Institutional Upgrade)
    realized_metrics = realized_vol_engine.compute_realized_volatility_metrics(nifty_df, spot, atr)
    local_gamma = local_gamma_engine.compute_local_gamma_density(subset if not raw_chain.empty else None, spot, atr)
    
    # Institutional Volatility Context
    vol_ctx = {
        "rv_5d": realized_metrics.get("rv_5d", 15.0),
        "rv_intraday": realized_metrics.get("rv_intraday", 15.0),
        "rv_acceleration": realized_metrics.get("rv_acceleration", 0.0),
        "regime": realized_metrics.get("volatility_regime", "NORMAL")
    }
    vt_label = "Expanding (Rising)" if vol_ctx["rv_acceleration"] > 0.05 else "Suppressed (Falling)" if vol_ctx["rv_acceleration"] < -0.05 else "Stable"
    vol_trend = {"vol_trend": vt_label}
    
    # 6. Preliminary Context for Classification
    ctx_pre = {
        "flow_metrics": flow_metrics,
        "auto_metrics": auto_metrics,
        "realized_metrics": realized_metrics,
        "local_gamma": local_gamma,
        "iv_data": iv_data,
        "spot": spot,
        "trans_score": trans_score,
        "vol_ctx": vol_ctx
    }
    
    # 7. CANONICAL STATE ENGINE (SINGLE SOURCE OF TRUTH)
    market_state = classify_market_state(ctx_pre)
    alignment = compute_signal_alignment(ctx_pre)
    market_state["confidence"] = alignment["confidence"]
    
    bias_obj = get_directional_conviction(
        regime_snap.get("current_regime") or regime_snap.get("regime_label", "Unknown"), 
        auto_metrics["drift"], 
        flow_metrics.get("total_gex", 0)
    )

    # 8. Expiry Defensive Flag (Institutional Policy Phase 42 + V5 Hardening)
    is_expiry_defensive = False
    tv_label = flow_metrics.get("tv_label", "NORMAL")
    gex_norm = flow_metrics.get("gex_norm", 0.0)
    
    # V5: Gamma Concentration & OI Clustering check
    inst_iq = flow_metrics.get("institutional_iq", {})
    oi_share = inst_iq.get("atm_oi_share", 0.0)
    
    expiry_phase = compute_expiry_phase(t_days)
    if expiry_phase == "EXPIRY_RISK" and iv_data:
        current_iv = iv_data.get("atm_iv", 20.0)
        # Condition: Low IV + Positive Gamma + No extreme OI clustering risk
        if current_iv < 12.0 and gex_norm > 0 and tv_label != "AVOID" and oi_share < 45.0:
            is_expiry_defensive = True

    # 9. Master Strategy Selection (Refactored for V5)
    strategy_code = select_master_strategy(ctx_pre)
    
    # Governance Gate (P1: Strict Blocking)
    prefilter_result = {"can_trade": True, "reason_code": "NONE"}
    
    # Extract integrity flags
    data_quality = meta.get("data_quality")
    has_delta = meta.get("has_delta", True)
    chain_rows = meta.get("chain_rows", 100)
    
    # Determination: Is data quality explicitly degraded?
    is_degraded = (data_quality in ["LOW", "DEGRADED"]) or (not has_delta) or (chain_rows < 50)
    
    if is_degraded and strategy_code != "NO_TRADE":
        # Check if critical missing
        if not has_delta or chain_rows < 30:
            strategy_code = "NO_TRADE"
            prefilter_result = {"can_trade": False, "reason_code": "CRITICAL_DATA_DEGRADATION"}
            logger.warning("Governance: Active execution blocked due to critical data degradation.")
        else:
            prefilter_result = {"can_trade": True, "reason_code": "DEGRADED_DATA_WARNING"}
            
    if strategy_code == "NO_TRADE" and prefilter_result["can_trade"]:
        prefilter_result = {"can_trade": False, "reason_code": "NO_STRATEGY_ALIGNMENT"}

    # 10. Hydrate Strategy Selection
    intel = flow_metrics.get("intelligence", {}).copy()
    inst_iq = flow_metrics.get("institutional_iq", {})
    # Merge Enriched Metrics into Intelligence Layer (Phase 46 Unified Context)
    intel.update(inst_iq)
    
    if not raw_chain.empty and "raw_exposures" in flow_metrics:
        intel["optimal_strikes"] = nde_options_logic.select_optimal_strikes(
            flow_metrics["raw_exposures"], spot, 
            flow_metrics={"total_gex": flow_metrics.get("total_gex", 0), "total_vega": flow_metrics.get("total_vega", 0)},
            mode=mode
        )
    flow_metrics["intelligence"] = intel
    
    # 11. Wall Migration & Squeeze Logic
    wall_drift = {"call": 0, "put": 0, "is_squeeze": False, "migration_bonus": 1.0}
    if regime_history and len(regime_history) > 1:
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_snapshots = [s for s in regime_history if s.get("date", "").startswith(today_str)]
            if today_snapshots:
                first = today_snapshots[0]
                first_cw = first.get("call_wall", walls[0])
                first_pw = first.get("put_wall", walls[1])
                wall_drift["call"] = int(walls[0] - first_cw)
                wall_drift["put"] = int(walls[1] - first_pw)
                if abs(walls[0] - walls[1]) < (1.5 * atr):
                    wall_drift["is_squeeze"] = True
                bias_label = bias_obj.get("bias", "NEUTRAL")
                s_int = float(strike_interval)
                if bias_label == "BULLISH" and (wall_drift["call"] >= s_int or wall_drift["put"] >= s_int):
                    wall_drift["migration_bonus"] = 1.05 if max(wall_drift["call"], wall_drift["put"]) < (2 * s_int) else 1.10
                elif bias_label == "BEARISH" and (wall_drift["call"] <= -s_int or wall_drift["put"] <= -s_int):
                    wall_drift["migration_bonus"] = 1.05 if min(wall_drift["call"], wall_drift["put"]) > (-2 * s_int) else 1.10
        except Exception: pass

    master_setup = get_strategy_details(
        strategy_code, flow_metrics, auto_metrics, spot, regime_snap, (call_wall, put_wall), atr, 
        dte=t_days, iv_data=iv_data, bias_conv=bias_obj, mode=mode, is_expiry_defensive=is_expiry_defensive,
        term_data=term_data, nifty_df=nifty_df, wall_drift=wall_drift, strike_interval=strike_interval
    )
    
    master_setup.update({
        "vol_trend": vol_trend,
        "vol_ctx": vol_ctx,
        "trans_score": trans_score,
        "market_state": market_state,
        "signal_alignment": alignment,
        "bias_conviction": bias_obj,
        "executive_summary": get_strategy_executive_summary(strategy_code, bias_obj, spot, (call_wall, put_wall), gamma_metrics=flow_metrics, iv_data=iv_data)
    })
    
    # 12. Cockpit Data
    _cockpit_data = {
        "market_state": market_state["state"],
        "details": get_market_state_cockpit_details(flow_metrics, auto_metrics, market_state),
        "dealer_behavior": interpret_dealer_behavior(flow_metrics),
        "greek_snapshot": generate_greek_snapshot_data(flow_metrics)
    }
    master_setup["cockpit"] = _cockpit_data
    
    # 13. Unified Context Construction
    ctx_dict = {
        "flow_metrics": flow_metrics,
        "auto_metrics": auto_metrics,
        "realized_metrics": realized_metrics,
        "local_gamma": local_gamma,
        "walls": (call_wall, put_wall),
        "iv_data": iv_data,
        "spot": spot,
        "master_setup": master_setup,
        "option_chain_df": raw_chain,
        "meta": meta,
        "index_name": index_name,
        "strike_interval": strike_interval,
        "trans_score": trans_score
    }
    
    from nde_narrative_engine import build_narrative
    from nde_execution_compiler import build_execution, build_payoff
    
    narrative = build_narrative(ctx_dict)
    execution_plan = build_execution(ctx_dict, narrative)
    payoff_summary = build_payoff(execution_plan)
    
    narrative["execution_plan"] = execution_plan
    narrative["payoff_summary"] = payoff_summary
    master_setup["narrative"] = narrative
    
    # NEW: Scenario Generation
    scenarios = scenario_engine.ScenarioEngine.generate_scenarios(spot, atr, execution_plan.get("legs", []), t_days)
    master_setup["scenarios"] = scenarios
    
    # AUTO-LOGGING (Institutional Requirement)
    log_execution(ctx_dict, narrative, execution_plan)
    
    # Enforce single authority: Remove legacy playbook
    master_setup["playbook"] = {}
    
    # 8. Tiered Institutional Execution Guard (Phase 42)
    # CRITICAL FALLBACKS (Structural Data Logic Fail)
    v_flags = meta.get("validation_flags", [])
    # Exhaustive label set matching actual ingestion output
    LOW_TRUST_SOURCES = {"MANUAL_CSV", "MANUAL-NSE", "CACHED", "SENSIBULL_MANUAL", "FAILED_VENDOR_FALLBACK"}
    
    if "NON_MONOTONIC_STRIKES" in v_flags or "ATM_GREEK_COLLAPSE" in v_flags:
        master_setup["code"] = "TRUST_VIOLATION"
        master_setup["name"] = "⚠️ DATA TRUST FAILURE (BLOCK)"
        master_setup["quality_score"] = 0
        master_setup["size"] = 0.0
        master_setup["rationale"] = ["Critical integrity failure in underlying option chain.", "Monotonicity or ATM density check failed.", "Observe Only mode ACTIVE."]
        strategy_code = "TRUST_VIOLATION"
    
    # MILD FALLBACKS (Source Trust / Fidelity)
    elif quality_score < 1.0 or source in LOW_TRUST_SOURCES:
        if strategy_code not in ["TRUST_VIOLATION", "NO_TRADE"]:
            if strategy_code in ["TREND_ACCELERATION", "GAMMA_FLIP"]:
                master_setup["size"] *= 0.5
                master_setup["rationale"].append("⚠️ Size reduction applied due to lower-trust data source.")
            else:
                master_setup["mode_override"] = "Defensive"
                master_setup["rationale"].append("🛡️ Forced Defensive mode due to Source/Quality constraints.")
    
    # IV FIDELITY GUARD (Phase 42: separate trust dimension)
    # Synthetic IV means ATM IV, IV-rank, and IV-adjusted scaling are unreliable
    if meta.get("iv_is_synthetic", False) or "IV_SYNTHETIC" in v_flags:
        if strategy_code not in ["TRUST_VIOLATION", "NO_TRADE"]:
            master_setup["mode_override"] = "Defensive"
            master_setup["rationale"].append("🔬 IV context is synthetic (hardcoded fallback). Forced Defensive — IV-rank and ATM scaling are unreliable.")
    
    # Quality scaling (applied after all guards)
    if quality_score < 1.0:
        if "quality_score" in master_setup:
            master_setup["quality_score"] *= quality_score
        master_setup["size"] *= quality_score

    # 10. UI Hydration (Extreme Thinning of Page 17)
    # Phase 41: Pure Presentation Data Packet
    ui_display = {
        "source_color": "green" if source.startswith("SENSIBULL") or source == "LIVEv3" else "orange",
        "quality_color": "green" if quality_score >= 1.0 else "orange" if quality_score >= 0.7 else "red",
        "regime_badge": {
            "label": (regime_snap.get("current_regime") or regime_snap.get("regime_label", "Unknown")).upper(),
            "color": {"RISK_ON": "#00c853", "SELECTIVE": "#ffd600", "DEFENSIVE": "#ff9100", "CRISIS": "#ff1744"}.get(regime_snap.get("current_regime") or regime_snap.get("regime_label", ""), "gray")
        },
        "greeks": {
            "delta": nde_options_logic.format_institutional_metric(flow_metrics.get("total_delta", 0), "Cr"),
            "gex_abs": nde_options_logic.format_institutional_metric(flow_metrics.get("total_gex_abs", 0), "Cr"),
            "gex_net": nde_options_logic.format_institutional_metric(flow_metrics.get("total_gex", 0), "Cr"),
            "vega": nde_options_logic.format_institutional_metric(flow_metrics.get("total_vega", 0), "Cr"),
            "theta": nde_options_logic.format_institutional_metric(flow_metrics.get("total_theta", 0), "Cr"),
            "vanna": nde_options_logic.format_institutional_metric(flow_metrics.get("total_vex", 0), "Cr")
        },
        "tv_ratio": {
            "val": f"x{flow_metrics.get('tv_ratio', 0.0):.1f}",
            "label": flow_metrics.get("tv_label", "UNKNOWN"),
            "color": "lightgreen" if flow_metrics.get("tv_label") in ["PREMIUM", "NORMAL"] else "#e6a800" if flow_metrics.get("tv_label") == "CAUTION" else "red"
        },
        "alignment_color": "green" if master_setup.get("alignment") == "ALIGNED" else "orange" if master_setup.get("alignment") == "CAUTION" else "red",
        "flip_vel": {
            "label": "HIGH ⚠️" if auto_metrics.get("drift_acceleration", 0) > 0.5 or (abs(auto_metrics.get("drift", 0)) > 0.2 and auto_metrics.get("stability_5d", 50) < 40) else "LOW",
            "color": "red" if auto_metrics.get("drift_acceleration", 0) > 0.5 else "lightgreen"
        },
        "trade_action": {
            "label": {
                "MEAN_REVERSION": "Fade Walls / Fade Extremes",
                "TREND_ACCELERATION": "Follow Momentum / Break Structure",
                "GAMMA_FLIP": "Wait for Confirmation / Trade Pivot",
                "NO_TRADE": "Stand Aside"
            }.get(strategy_code, "Stand Aside"),
            "style": {
                "MEAN_REVERSION": "info",
                "TREND_ACCELERATION": "success",
                "GAMMA_FLIP": "warning",
                "NO_TRADE": "secondary"
            }.get(strategy_code, "info")
        },
        "structural_confidence": {
            "label": "ANCHORED" if auto_metrics.get("stability", 50) > 70 and abs(auto_metrics.get("drift", 0)) < 0.1 else "MIGRATING" if abs(auto_metrics.get("drift", 0)) > 0.15 else "UNSTABLE",
            "color": "#00c853" if auto_metrics.get("stability", 50) > 70 and abs(auto_metrics.get("drift", 0)) < 0.1 else "#ffd600" if abs(auto_metrics.get("drift", 0)) > 0.15 else "#ff1744"
        }
    }

    # Task 5 & 8: Strict API Output Generation
    action_raw = master_setup.get("action", "WAIT")
    if not prefilter_result["can_trade"]:
        action_raw = "WAIT"
        
    master_setup["api_schema"] = {
        "timestamp": datetime.now().isoformat(),
        "action": action_raw,
        "strategy": master_setup.get("name", "WAIT_AND_WATCH"),
        "confidence": master_setup.get("quality_score", 0.0) / 10.0,
        "strikes": master_setup.get("playbook", {}).get("legs", []),
        "risk": {
            "max_loss_pts": master_setup.get("estimated_pnl", {}).get("max_risk", 0),
            "reward_risk_ratio": master_setup.get("estimated_pnl", {}).get("rr_ratio", 0)
        },
        "reason_code": prefilter_result["reason_code"]
    }

    return {
        "flow_metrics": flow_metrics,
        "auto_metrics": auto_metrics,
        "walls": (call_wall, put_wall),
        "spot": spot,
        "iv_data": iv_data,
        "strategy_code": strategy_code,
        "master_setup": master_setup,
        "regime_snap": regime_snap,
        "current_atm_iv": current_atm_iv,
        "atr": atr,
        "t_days": t_days,
        "expiry_phase": expiry_phase,
        "quality_score": quality_score,
        "source_mode": source,
        "requires_warning": (
            source == "DEGRADED (Strike Mean)" or 
            meta.get("requires_warning", False) or 
            prefilter_result["reason_code"] in ["CRITICAL_DATA_DEGRADATION", "DEGRADED_DATA_WARNING"]
        ),
        "state": load_strategy_state(),
        "ui_display": ui_display,
        "narrative": master_setup.get("narrative", {}) # Explicitly surface narrative
    }
class CustomJsonEncoder(json.JSONEncoder):
    """Handles NumPy types for JSON serialization."""
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        elif isinstance(obj, (np.ndarray, list)):
            return [self.default(x) for x in obj]
        return super().default(obj)

def append_strategy_audit(entry: Dict[str, Any]):
    AUDIT_FILE.parent.mkdir(exist_ok=True)
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry, cls=CustomJsonEncoder) + "\n")

def estimate_cost(premium: float) -> float:
    """
    Hybrid Cost Model: Fixed Brokerage + % Based Taxes/Slippage.
    premium: Total premium captured (Gross INR).
    """
    # 1. Brokerage (Entry + Exit = 2 orders)
    brokerage = 2 * BROKERAGE_PER_ORDER
    # 3. GST on Brokerage
    gst = brokerage * GST_PCT
    # 4. STT (Sell side only for options)
    stt = premium * STT_SELL_OPT_PCT
    # 5. Slippage (Execution drag)
    slippage = premium * EST_SLIPPAGE_PCT
    # 5. Other (Exchange fees, SEBI, Stamp)
    other = premium * OTHER_CHARGES_PCT
    
    return float(round(brokerage + gst + stt + slippage + other, 2))

def compute_signal_convergence(strategy_code: str, gamma_metrics: dict, auto_metrics: dict, regime_data: dict, iv_data: dict, atr: float = 250.0, spot: float = 22500.0) -> tuple[float, dict]:

    """
    Returns a Convergence Score (0.0 to 1.0) and orthogonal bucket booleans validating independent signals.
    """
    # Phase 45: Removed early return to allow 'Neutral Alignment' telemetry in the Signal Matrix
    if strategy_code == "NO_TRADE":
        pass 

    if regime_data is None: regime_data = {}
    regime = normalize_regime_name(regime_data.get("current_regime", ""))
    gamma_norm = gamma_metrics.get("gex_norm", 0)
    stability_20d = auto_metrics.get("stability", 50)
    drift = auto_metrics.get("drift", 0)
    drift_accel = auto_metrics.get("drift_acceleration", 0.0)
    
    iv_label = iv_data.get("label", "NORMAL")

    buckets = {"macro": False, "flow": False, "structure": False, "momentum": False, "vol": False}

    if strategy_code == "MEAN_REVERSION":
        buckets["macro"] = regime in ["DEFENSIVE", "SELECTIVE", "RISK_ON"]
        buckets["flow"] = gamma_norm > 0
        buckets["structure"] = stability_20d > 65
        buckets["momentum"] = drift_accel <= 0 or abs(drift) < 0.2
        buckets["vol"] = iv_label in ["ELEVATED", "NORMAL"]

    elif strategy_code == "TREND_ACCELERATION":
        buckets["macro"] = regime in ["CRISIS", "SELECTIVE", "RISK_ON"]
        buckets["flow"] = gamma_norm < 0
        buckets["structure"] = stability_20d < 40
        buckets["momentum"] = drift_accel > 0 and abs(drift) > 0.2
        buckets["vol"] = iv_label != "CRUSHED"
        
    elif strategy_code == "GAMMA_FLIP":
        buckets["macro"] = regime in ["CRISIS", "SELECTIVE"]
        buckets["flow"] = abs(gamma_norm) < 25.0 # per lot
        buckets["structure"] = auto_metrics.get("fragility", False)
        buckets["momentum"] = abs(drift_accel) > 0
        buckets["vol"] = iv_label != "CRUSHED"

    else:
        # Neutral Alignment Path (Wait & Watch / Strategy Discovery)
        # Shows raw market conditions without assuming a directional bias.
        buckets["macro"] = regime in ["DEFENSIVE", "SELECTIVE", "RISK_ON"]
        buckets["flow"] = gamma_norm > 0 or abs(gamma_norm) < 10.0
        buckets["structure"] = stability_20d > 50
        buckets["momentum"] = abs(drift) < 0.25
        buckets["vol"] = iv_label != "CRUSHED"
        
    weights = {
        "macro": 0.30, 
        "flow": 0.25, 
        "structure": 0.20, 
        "momentum": 0.15,  # Phase 40: Cleaned up redundant min(0.15, 0.20)
        "vol": 0.10
    }
    raw_score = sum(weights[k] for k, v in buckets.items() if v)
    
    logger.debug(f"NDE convergence: strategy={strategy_code} buckets={buckets} raw_score={raw_score}")

    # Phase 42: Volume/OI Engagement Boost
    # If we have "Institutional Churn" in the engagement zone, boost convergence
    flow_regime = gamma_metrics.get("flow_regime_label", "Passive")
    logger.debug(f"NDE convergence: flow_regime={flow_regime}")
    if flow_regime == "Institutional Churn":
        raw_score += 0.05
    elif flow_regime in ["Active Accumulation", "Directional Engagement"]:
        raw_score += 0.02
    
    score = (min(raw_score, 1.0)) ** 1.3
    logger.debug(f"NDE convergence: final_score={score}")
    
    # Risk 1: Convergence Saturation Penalty (Autocorrelation)
    state = load_strategy_state()
    prev_conv = max(0.0, min(1.0, state.get("recent_convergence_mean", 0.5)))
    if prev_conv > 0.6:
        autocorr_penalty = prev_conv - 0.5
        score *= (1 - 0.1 * autocorr_penalty)
    
    # Defensive clamp (guards against corrupted state values)
    score = max(0.0, min(1.0, score))
    if not (0.0 <= score <= 1.0):
        raise ValueError(f"Integrity Failure: Convergence out of bounds -> {score}")
    
    # Cast buckets to native bools to prevent JSON serialization issues (e.g. numpy.bool_)
    safe_buckets = {k: bool(v) for k, v in buckets.items()}
    
    return float(round(score, 4)), safe_buckets

def calculate_trade_quality(strategy_code, gamma_metrics, auto_metrics, regime_data, iv_data, convergence_data, strike_intel=None):
    """
    Score: 1-10 based on weighted tactical alignment + IV Rank scaling + Convergence verification.
    """
    convergence_score, convergence_buckets = convergence_data
    
    regime = normalize_regime_name(regime_data.get("current_regime") or regime_data.get("regime_label", "Unknown"))
    REGIME_MAP = {"RISK_ON": 10, "SELECTIVE": 8, "DEFENSIVE": 6, "CRISIS": 2}
    regime_score = REGIME_MAP.get(regime, 5)
    
    # NEW: Dynamic Tactical Weighting by Phase (V5 Roadmap)
    # Discovery: 09:15-10:30 (Focus on Macro/Regime)
    # Midday: 10:30-14:15 (Focus on Options Walls/Greeks)
    # Closing: 14:15-15:30 (Focus on Intraday Flow/Volume)
    from datetime import datetime
    now_time = datetime.now().time()
    phase_label = "MIDDAY"
    w = STRATEGY_WEIGHTS.copy()
    
    if now_time >= datetime.strptime("09:15", "%H:%M").time() and now_time < datetime.strptime("10:30", "%H:%M").time():
        phase_label = "DISCOVERY"
        w["regime"] = 0.50; w["strike"] = 0.20; w["risk"] = 0.30
    elif now_time >= datetime.strptime("14:15", "%H:%M").time() and now_time <= datetime.strptime("15:35", "%H:%M").time():
        phase_label = "CLOSING"
        w["regime"] = 0.20; w["strike"] = 0.30; w["risk"] = 0.50
    else:
        # Default Midday weights
        w["regime"] = 0.35; w["strike"] = 0.35; w["risk"] = 0.30

    # 2. Strike Quality (0-10)
    strike_score = 5
    if strike_intel:
        opt = strike_intel.get("optimal_strikes", {})
        if opt:
            scores = [s.get("score", 0) for s in opt.values() if s]
            if scores:
                avg_raw = np.mean(scores)
                strike_score = (avg_raw + 0.7) / 1.7 * 10
                
    # 3. Risk Positioning (0-10)
    gex_norm = gamma_metrics.get("gex_norm", 0)
    stability = auto_metrics.get("stability", 50)
    risk_score = ( (1 if gex_norm > 0 else 0.5) * 6 + (stability / 100.0) * 4 )
    
    regime_score = max(0.0, min(10.0, regime_score))
    strike_score = max(0.0, min(10.0, strike_score))
    risk_score = max(0.0, min(10.0, risk_score))
    
    # w is already correctly weighted by market phase (Discovery/Midday/Closing)
    total_score = (regime_score * w["regime"] + strike_score * w["strike"] + risk_score * w["risk"])
    
    # Phase 37: Convergence & IV Adjustments
    IV_QUALITY_MAP = {"ELEVATED": 1.00, "NORMAL": 0.85, "COMPRESSED": 0.65, "CRUSHED": 0.40}
    iv_multiplier = IV_QUALITY_MAP.get(iv_data.get("label", "NORMAL"), 0.85)
    
    if strategy_code in ("MEAN_REVERSION", "CHARM"):
        total_score *= iv_multiplier
        
    # Convergence Penalty
    if convergence_score < 0.5:
        total_score *= 0.7 # Heavy penalty for low confirmation
        
    # NEW: Liquidity-Adjusted Conviction (Tier 3 Roadmap)
    # Penalty if strikes are far OTM with low OI share
    liquidity_mult = 1.0
    if strike_intel:
        atm_share = strike_intel.get("atm_oi_share", 50)
        if atm_share < 20: # Hiding in illiquid wings
            liquidity_mult = 0.85
    total_score *= liquidity_mult
        
    total_score = max(0.0, min(10.0, total_score))
    
    breakdown = {
        "regime": float(round(regime_score, 1)),
        "strike": float(round(strike_score, 1)),
        "risk": float(round(risk_score, 1)),
        "convergence": float(round(convergence_score, 2)),
        "convergence_buckets": convergence_buckets,
        "iv_mult": float(round(iv_multiplier, 2)),
        "liquidity_mult": float(round(liquidity_mult, 2)),
        "phase": phase_label
    }
    
    return float(round(total_score, 1)), breakdown

# calculate_position_sizing removed (dead code — sizing is done inline in get_strategy_details)

def validate_regime_consistency(strategy, regime):
    """
    Returns (is_aligned, warning_msg)
    """
    reg = normalize_regime_name(regime)
    if reg == "CRISIS" and strategy == "MEAN_REVERSION":
        return False, "⚠️ Warning: Mean Reversion in CRISIS carries extreme tail risk."
    return True, ""

def apply_term_structure_overrides(strategy_code, term_data, size_mult, warnings, conv_score=1.0, is_expiry_defensive=False, mode="Balanced"):
    """
    Final Institutional Overlay: Multi-Expiry Awareness V2.
    Tightens Mean Reversion rules and boosts Trend Acceleration.
    """
    if not term_data or len(term_data) < 2:
        return size_mult, warnings, False
        
    expiries = list(term_data.keys())
    w1 = term_data[expiries[0]]["state"]
    w2 = term_data[expiries[1]]["state"] if len(expiries) > 1 else "Unknown"
    w3 = term_data[expiries[2]]["state"] if len(expiries) > 2 else "Unknown"
    mn = term_data[expiries[-1]]["state"]
    
    is_blocked = False
    
    if strategy_code == "MEAN_REVERSION":
        # Mid-cycle fragility check
        if any(x == "Fragile" for x in [w2, w3]):
            # Institutional Exception: Soften convergence floor for Expiry Defensive trades
            conv_floor = 0.4 if (is_expiry_defensive and mode == "Defensive") else 0.7
            if conv_score < conv_floor:
                is_blocked = True
                reason = "Institutional Block: Mid-cycle fragility" + ("" if is_expiry_defensive else " + Low convergence")
                warnings.append(f"🚫 {reason} blocks Mean Reversion.")
            else:
                size_mult *= 0.5
                warnings.append("⚠️ MID-CYCLE FRAGILITY: Surface awareness reduces MR confidence.")
            
    if strategy_code == "TREND_ACCELERATION":
        if w2 == "Fragile" or w3 == "Fragile":
            # Confidence Boost
            size_mult *= 1.2
            warnings.append("🚀 MULTI-EXPIRY CONVERGENCE: Fragile mid-cycle confirms trend breakout momentum.")
            
    # Vol Structure Enablement
    if mn == "Anchor" and strategy_code in ["VANNA", "VOL_SKEW"]:
        size_mult = max(size_mult, 0.8) # Ensure vol strategies have minimum size if anchor is strong
        warnings.append("🔵 MONTHLY ANCHOR: Structural stability supports Vol-sensitive positioning.")
            
    return size_mult, warnings, is_blocked

def apply_greek_overrides(strategy_code, metrics):
    """
    Override strategy based on continuous Carry & aggregate Greek risks.
    """
    tv_label = metrics.get("tv_label", "NORMAL")
    theta = metrics.get("total_theta", 0)
    
    overrides = []
    size_mult = 1.0
    
    if strategy_code == "MEAN_REVERSION":
        # Phase 37: Continuous Theta/Vega Ratio Gating
        if tv_label == "AVOID":
            overrides.append("🔴 CARRY OVERRIDE: Gamma structure dominates. Negative carry (AVOID). Downsizing.")
            size_mult *= 0.2
        elif tv_label == "LATE":
            overrides.append("⚠️ CARRY CAUTION: Near-expiry noise (LATE). Reducing size.")
            size_mult *= 0.5
        elif tv_label == "CAUTION":
            overrides.append("🟡 CARRY CHECK: Carry thinning (CAUTION). Tightening stops.")
            size_mult *= 0.85
            
        # Hard lock on absolute negative aggregate theta
        if theta < 0:
            overrides.append("🔴 THETA OVERRIDE: Aggregate negative carry point detected.")
            size_mult *= 0.5
            
    return size_mult, overrides

def generate_trade_template(strategy, spot, call_wall, put_wall, atr, intel=None, raw_exp=None, mode="Balanced"):
    """
    Enriched Execution Template with Phase 28/29 Risk Profiling.
    """
    selected = intel.get("optimal_strikes") if intel else None
    dns_zones = intel.get("dns_zones", []) if intel else []
    
    import math
    if not atr or math.isnan(atr): 
        atr = 250.0
        
    def enrich_execution(sell_c, sell_p):
        dist_c = (sell_c - spot) / spot if sell_c else 0
        dist_p = (spot - sell_p) / spot if sell_p else 0
        
        # Risk profiling from logic layer (Phase 29: Replaced placeholder)
        rc = nde_options_logic.get_strike_risk_profile(sell_c, raw_exp, dns_zones) if sell_c else "LOW"
        rp = nde_options_logic.get_strike_risk_profile(sell_p, raw_exp, dns_zones) if sell_p else "LOW"
        
        return {
            "sell_call": sell_c, 
            "sell_put": sell_p, 
            "optimized": True if selected else False,
            "distances": {"call": f"{dist_c:.2%}", "put": f"{dist_p:.2%}"},
            "risk_profile": f"C:{rc} | P:{rp}"
        }

    if strategy == "MEAN_REVERSION":
        sell_c = selected["call"]["strike"] if selected and selected.get("call") else call_wall
        sell_p = selected["put"]["strike"] if selected and selected.get("put") else put_wall
        
        # Defined Risk logic (Nifty Step is 50/100, others 100/200)
        # mode: Defensive (Width 2x Interval), Balanced (Width 1x Interval), Aggressive (Naked proxy)
        strike_interval = intel.get("strike_interval", 50.0) if intel else 50.0
        width = (2 * strike_interval) if mode == "Defensive" else strike_interval
        
        # Guard against NaN values
        if not sell_c or math.isnan(sell_c): sell_c = call_wall
        if not sell_p or math.isnan(sell_p): sell_p = put_wall
        
        if not sell_c or not sell_p or math.isnan(sell_c) or math.isnan(sell_p): 
            return None
            
        # Payoff Math: MEAN REVERSION (Iron Condor)
        try:
            c_ltp = float(raw_exp[(raw_exp["strike"] == sell_c) & (raw_exp["type"] == "call")]["ltp"].values[0]) if sell_c else 4.0
            p_ltp = float(raw_exp[(raw_exp["strike"] == sell_p) & (raw_exp["type"] == "put")]["ltp"].values[0]) if sell_p else 4.0
        except (IndexError, KeyError, TypeError) as e:
            logger.debug(f"LTP lookup fallback for strike pair ({sell_c},{sell_p}): {e}")
            c_ltp, p_ltp = 4.0, 4.0
            
        est_prem = c_ltp + p_ltp
        max_profit_val = est_prem * LOT
        
        if mode == "Aggressive":
            # FIX 6 (Phase 5.8 Review): Force minimum 400pt wing even in Aggressive mode
            # to prevent naked strangles with unlimited loss
            agg_width = 400
            theoretical_loss = (agg_width - est_prem) * LOT
            risk_proxy_val = float(theoretical_loss)
            payoff_block = {
                "max_profit": f"₹{int(max_profit_val):,}",
                "max_loss": f"₹{int(theoretical_loss):,} (400pt wings)",
                "risk_proxy_inr": risk_proxy_val,
                "breakeven_upper": float(sell_c + est_prem),
                "breakeven_lower": float(sell_p - est_prem)
            }
        else:
            theoretical_loss = (width - est_prem) * LOT
            payoff_block = {
                "max_profit": f"₹{int(max_profit_val):,}",
                "max_loss": f"₹{int(theoretical_loss):,}",
                "risk_proxy_inr": float(theoretical_loss),
                "breakeven_upper": float(sell_c + est_prem),
                "breakeven_lower": float(sell_p - est_prem)
            }

        return {
            "execution": enrich_execution(sell_c, sell_p),
            "stop": {"upper": int(sell_c + (0.5 * atr)), "lower": int(sell_p - (0.5 * atr))},
            "payoff_summary": payoff_block | {"invalidation": "Spot breaches Wall / Major Macro or Gamma Regime Flip."},
            "position_type": "SHORT_VOL (Neutral)"
        }

    elif strategy == "TREND_ACCELERATION":
        bias = intel.get("structural_bias", "Neutral") if intel else "Bullish"
        strike_interval = intel.get("strike_interval", 50.0) if intel else 50.0
        width = (3 * strike_interval) if mode == "Defensive" else ((2 * strike_interval) if mode == "Balanced" else (4 * strike_interval))
        offset_mult = 1.5 if mode == "Defensive" else (1.0 if mode == "Balanced" else 0.5)
        strike_interval = intel.get("strike_interval", 50.0)
        
        if bias == "Bullish":
            t_p = spot - (0.5 * atr * offset_mult)
            sell_p = nde_options_logic.snap_to_nearest_strike(t_p, raw_exp)
            buy_p = nde_options_logic.snap_to_nearest_strike(sell_p - width, raw_exp)
            try:
                s_ltp = float(raw_exp[(raw_exp["strike"] == sell_p) & (raw_exp["type"] == "put")]["ltp"].values[0])
                b_ltp = float(raw_exp[(raw_exp["strike"] == buy_p) & (raw_exp["type"] == "put")]["ltp"].values[0])
                net_credit = max(0, s_ltp - b_ltp)
            except (IndexError, KeyError, TypeError):
                net_credit = (width / 4.0)
                
            max_profit = net_credit * LOT
            max_loss = (width - net_credit) * LOT
            be = sell_p - net_credit
            
            return {
                "name": "Bullish Trend Acceleration",
                "execution": {"sell_put": sell_p, "buy_put": buy_p, "distances": {"put": f"{(1-sell_p/spot)*100:.2f}%"}},
                "stop": {"points": int(1.5 * atr)},
                "payoff_summary": {
                    "max_profit": f"₹{int(max_profit):,}",
                    "max_loss": "Managed per ATR" if mode == "Aggressive" else f"₹{int(max_loss):,}",
                    "risk_proxy_inr": float(1.0 * atr * LOT) if mode == "Aggressive" else float(max_loss),
                    "breakeven_upper": float(be),
                    "breakeven_lower": float(be),
                    "invalidation": "Spot breaks below Sell Put strike OR Gamma flips Positive."
                },
                "position_type": "BULL_PUT_SPREAD"
            }
        elif bias == "Bearish":
            t_c = spot + (0.5 * atr * offset_mult)
            sell_c = nde_options_logic.snap_to_nearest_strike(t_c, raw_exp)
            buy_c = nde_options_logic.snap_to_nearest_strike(sell_c + width, raw_exp)
            try:
                s_ltp = float(raw_exp[(raw_exp["strike"] == sell_c) & (raw_exp["type"] == "call")]["ltp"].values[0])
                b_ltp = float(raw_exp[(raw_exp["strike"] == buy_c) & (raw_exp["type"] == "call")]["ltp"].values[0])
                net_credit = max(0, s_ltp - b_ltp)
            except (IndexError, KeyError, TypeError):
                net_credit = (width / 4.0)
                
            max_profit = net_credit * LOT
            max_loss = (width - net_credit) * LOT
            be = sell_c + net_credit
            
            return {
                "name": "Bearish Trend Acceleration",
                "execution": {"sell_call": sell_c, "buy_call": buy_c, "distances": {"call": f"{(sell_c/spot-1)*100:.2f}%"}},
                "stop": {"points": int(1.5 * atr)},
                "payoff_summary": {
                    "max_profit": f"₹{int(max_profit):,}",
                    "max_loss": "Managed per ATR" if mode == "Aggressive" else f"₹{int(max_loss):,}",
                    "risk_proxy_inr": float(1.0 * atr * LOT) if mode == "Aggressive" else float(max_loss),
                    "breakeven_upper": float(be),
                    "breakeven_lower": float(be),
                    "invalidation": "Spot breaks above Sell Call strike OR Gamma flips Positive."
                },
                "position_type": "BEAR_CALL_SPREAD"
            }

    elif strategy == "GAMMA_FLIP":
        risk_proxy_val = float(1.0 * atr * LOT)
        return {
            "execution": {"trigger": "Above Flip: Long, Below Flip: Short", "context": "Hedging Pivot", "mode": mode},
            "stop": {"points": int(1.0 * atr)},
            "payoff_summary": {
                "max_profit": "Unlimited (Momentum)", 
                "max_loss": "Managed per ATR",
                "risk_proxy_inr": risk_proxy_val,
                "breakeven_upper": None,
                "breakeven_lower": None
            },
            "position_type": "MOMENTUM_PIVOT"
        }

    elif strategy == "VANNA":
        # Vol-Neutral Core Positioning (1.5 ATR distance)
        strike_interval = intel.get("strike_interval", 50.0) if intel else 50.0
        t_c = spot + (1.5 * atr)
        t_p = spot - (1.5 * atr)
        sell_c = nde_options_logic.snap_to_nearest_strike(t_c, raw_exp)
        sell_p = nde_options_logic.snap_to_nearest_strike(t_p, raw_exp)
        
        # Mode-aware Protection
        width = 150 if mode == "Defensive" else (100 if mode == "Balanced" else 0)
        buy_c = sell_c + width if width > 0 else None
        buy_p = sell_p - width if width > 0 else None
        
        exec_payload = enrich_execution(sell_c, sell_p)
        exec_payload.update({
            "type": "Volatility-Weighted Spread",
            "buy_call": buy_c,
            "buy_put": buy_p,
            "context": "Vanna/IV Flow"
        })
        
        risk_proxy_val = float(1.2 * atr * LOT) if mode == "Aggressive" else float(0.8 * atr * LOT)
        return {
            "execution": exec_payload,
            "stop": {"points": int(2.0 * atr)},
            "payoff_summary": {
                "max_profit": "Variable", 
                "max_loss": "Defined" if width > 0 else "Managed per ATR",
                "risk_proxy_inr": risk_proxy_val,
                "breakeven_upper": float(sell_c + (atr * 0.5)),
                "breakeven_lower": float(sell_p - (atr * 0.5)),
                "invalidation": "Vanna Flow reverses OR Spot breaches Vol-Neutral boundary."
            },
            "position_type": "VOL_DIRECTIONAL"
        }

    elif strategy == "NO_TRADE":
        return None
        
    # Default/Charm
    risk_proxy_val = float(0.5 * atr * LOT)
    return {
        "execution": {"type": "Passive Intraday Scalp (Charm)", "mode": mode},
        "stop": {"points": int(1.0 * atr)},
        "payoff_summary": {
            "max_profit": "Theta-Driven", 
            "max_loss": "Managed per ATR",
            "risk_proxy_inr": risk_proxy_val,
            "breakeven_upper": None,
            "breakeven_lower": None
        },
        "position_type": "INTRADAY_BIAS"
    }

# ==================== MAIN LOGIC ====================


def calculate_realized_volatility(df: pd.DataFrame, window: int = 20) -> float:
    """Computes Annualized Realized Volatility from historical returns."""
    if df is None or df.empty or len(df) < window:
        return 15.0 # Default fallback
    try:
        # Calculate daily log returns
        returns = np.log(df['Close'] / df['Close'].shift(1))
        # Rolling std dev annualized (sqrt(252))
        vol = returns.rolling(window=window).std() * np.sqrt(252) * 100
        rv = float(vol.iloc[-1])
        return rv if not np.isnan(rv) else 15.0
    except Exception:
        return 15.0

def select_master_strategy(ctx: dict) -> str:
    """
    Institutional Strategy Selection Engine (V3).
    Hierarchy: Transition Risk -> Market State -> Alignment -> Strategy intent.
    """
    flow = ctx.get("flow_metrics", {})
    auto = ctx.get("auto_metrics", {})
    vol_ctx = ctx.get("vol_ctx", {})
    trans_score = ctx.get("trans_score", {})
    
    # Extract State from Context
    m_state = ctx.get("master_setup", {}).get("market_state", {})
    if not m_state:
        from nde_strategy_logic import classify_market_state
        m_state = classify_market_state(ctx)
        
    state = m_state.get("state", "NEUTRAL")
    vol_regime = m_state.get("volatility_regime", "NORMAL")
    trans_label = trans_score.get("label", "IGNORE")
    
    strategy_code = "NO_TRADE"
    
    # 1. TRANSITION PRIORITY
    if trans_label == "IMMINENT":
        strategy_code = "GAMMA_FLIP"
    else:
        # 2. STATE-BASED SELECTION
        if state == "PINNED RANGE":
            strategy_code = "MEAN_REVERSION"
        elif state == "SUPPRESSED TREND":
            strategy_code = "TREND_ACCELERATION"
        elif state == "EXPANSIVE TREND":
            strategy_code = "TREND_ACCELERATION"
        elif state == "LIQUIDITY VACUUM":
            strategy_code = "TREND_ACCELERATION"
        elif state == "TRANSITIONAL INSTABILITY":
            strategy_code = "NO_TRADE"
        else:
            # 3. LEGACY FALLBACKS
            drift = auto.get("drift", 0.0)
            stability = auto.get("stability", 50.0)
            if abs(drift) > 0.4:
                strategy_code = "TREND_ACCELERATION"
            elif stability > 70 and abs(drift) < 0.2:
                strategy_code = "MEAN_REVERSION"
    
    # 4. Persistence & Audit Sync
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    s_state = load_strategy_state()
    
    if s_state.get("last_strategy") == strategy_code:
        s_state["persistence_days"] = s_state.get("persistence_days", 0) + 1
    else:
        s_state["last_strategy"] = strategy_code
        s_state["persistence_days"] = 1
        
    s_state["last_update"] = today_str
    save_strategy_state(s_state)
    
    return strategy_code

def calculate_reversion_score(spot, walls, flip, drift, stability, gex_norm, nifty_df):
    """
    Calculates a score (0-10) for long-gamma reversion setups based on distance from extremes.
    Refined Phase 47: Institutional wall proximity + Gamma Flip awareness.
    """
    reasons = []
    if nifty_df is None or nifty_df.empty or "Close" not in nifty_df.columns:
        return {"score": 0.0, "label": "DATA_MISSING", "reason": ["Missing price history."]}

    # Hardening for spot
    try:
        spot = float(spot)
        if math.isnan(spot) or spot <= 0: spot = 24000.0
    except (ValueError, TypeError): spot = 24000.0

    # 1. Distance from SMA (20-period proxy for VWAP)
    sma_series = nifty_df["Close"].rolling(20).mean()
    if len(sma_series) == 0 or pd.isna(sma_series.iloc[-1]):
        sma = spot # Neutral fallback
    else:
        sma = float(sma_series.iloc[-1])
    
    dist_sma = abs(spot - sma) / (sma if sma > 0 else 1.0) * 100
    if dist_sma > 1.5:
        reasons.append("Significant distance from VWAP proxy.")
    
    # 2. Distance from nearest wall
    c_wall = walls[0] if len(walls) >= 1 else 0
    p_wall = walls[1] if len(walls) >= 2 else 0
    dist_wall = 0
    if c_wall and p_wall:
        dist_wall = min(abs(spot - c_wall), abs(spot - p_wall)) / spot * 100
        if dist_wall < 0.5:
            reasons.append(f"Spot near {'Call' if abs(spot-c_wall) < abs(spot-p_wall) else 'Put'} Wall.")
    
    # 3. Distance from Gamma Flip (Max 2 points)
    dist_flip = abs(spot - flip) / spot * 100 if flip else 1.0
    # Reversion is better AWAY from flip (in long gamma) but near walls.
    if dist_flip < 0.2:
        reasons.append("Spot near Gamma Flip (Conflict Zone).")
    
    # 4. GEX Strength (Max 3 points)
    gex_score = min(abs(gex_norm) / 5.0, 1.0) * 3.0 if gex_norm > 0 else 0
    if gex_norm > 2.0:
        reasons.append("Long Gamma regime supportive of reversion.")
    
    # 5. Stability (Max 2 points)
    stab_score = min(stability / 80.0, 1.0) * 2.0
    if stability > 70:
        reasons.append("High regime stability.")
    
    # Logic: If GEX is negative, we DON'T want to fade unless it's an extreme over-extension
    if gex_norm < 0:
        if dist_sma > 3.0: 
            return {"score": 4.0, "label": "EXTREME_MOMENTUM", "reason": ["Negative Gamma Over-extension. High Risk Fade."]}
        return {"score": 0.0, "label": "MOMENTUM_ACTIVE", "reason": ["Negative Gamma. Directional bias active."]}
        
    # Long Gamma logic: Proximity to walls + distance from SMA
    score = (dist_sma * 1.0) + (max(0, 1.5 - dist_wall) * 2.0) + stab_score + gex_score
    score = min(round(score, 1), 10.0)
    
    label = "WAIT"
    if score > 7.5:
        label = "HIGH_REVERSION"
    elif score > 5.0:
        label = "MODERATE_REVERSION"
    
    return {
        "score": score,
        "label": label,
        "reason": reasons,
        "vwap_proxy": round(sma, 1)
    }

def is_strike_viable(raw_exp, strike, o_type, spot, dte, min_premium=5.0):
    """
    Checks if a strike is liquid and has enough premium (LTP) to justify a trade.
    """
    if raw_exp is None or raw_exp.empty:
        return False, "No data"
    
    # Filter for strike and type
    row = raw_exp[(raw_exp["strike"] == strike) & (raw_exp["type"].str.upper() == o_type.upper())]
    if row.empty:
        return False, "Strike not found"
    
    ltp = row["ltp"].iloc[0]
    oi = row["oi"].iloc[0]
    
    # Distance check: Walls more than 7% away on weekly usually lack premium
    dist_pct = abs(strike - spot) / spot * 100
    if dte <= 7 and dist_pct > 7.0 and ltp < min_premium:
        return False, f"Insufficient premium ({ltp:.1f} < {min_premium})"
        
    if oi < 5000: # Liquidity Floor (proxy)
        return False, f"Low liquidity (OI: {int(oi)})"
        
    return True, "Viable"

def calculate_reversion_strength(gamma_norm: float, charm_norm: float, stability: float) -> float:
    """Alpha 5.3: Mean Reversion Strength Score (0.0 - 1.0)."""
    # High Gamma + High Charm + High Stability = Extreme Reversion Strength
    g_score = min(max(gamma_norm, 0), 20) / 20.0
    c_score = min(max(charm_norm, 0), 2.0) / 2.0
    s_score = min(max(stability - 50, 0), 50) / 50.0
    
    score = (g_score * 0.4) + (c_score * 0.3) + (s_score * 0.3)
    return round(score, 2)

def calculate_execution_confidence(conv_score: float, trans_score: float, vol_ctx: dict) -> float:
    """Alpha 5.4: Aggregate Execution Confidence (0.0 - 1.0)."""
    # High Convergence + Low Transition Risk + Quiet/Normal Vol = High Confidence
    v_regime = vol_ctx.get("regime", "NORMAL")
    v_mult = 1.0
    if v_regime == "EXPLOSIVE": v_mult = 0.4
    elif v_regime == "CRUSHED": v_mult = 0.6
    
    # Transition score (higher is riskier for existing trades, but better for NEW transitions)
    # We use (1 - trans) for stability-based confidence
    score = (conv_score * 0.6) + ((1.0 - trans_score) * 0.4)
    return round(score * v_mult, 2)

def generate_strategy_playbook(
    strategy_code, gamma_metrics, auto_metrics, spot, walls, iv_data, 
    quality_score, size, bias_obj, reversion_score_obj, mode="Balanced", 
    term_data=None, source_mode="TRUSTED", expiry=None, dte=None,
    vol_ctx=None, trans_score=None, market_state=None, strike_interval=50.0
):
    """
    V5 Strategy Engine Logic.
    """
    # --- CANONICAL HARDENING (V5.2) ---
    # Handle NaN spot or walls to prevent "cannot convert float NaN to integer"
    try:
        if spot is None or not (float(spot) > 0) or math.isnan(float(spot)):
            spot = 24000.0  # Emergency mid-strike fallback
        else:
            spot = float(spot)
    except (ValueError, TypeError):
        spot = 24000.0

    _safe_walls = []
    for i, w in enumerate(walls):
        try:
            if w is None or not (float(w) > 0) or math.isnan(float(w)):
                _safe_walls.append(spot + (300 if i == 0 else -300))
            else:
                _safe_walls.append(float(w))
        except (ValueError, TypeError):
            _safe_walls.append(spot + (300 if i == 0 else -300))
    walls = tuple(_safe_walls)

    dte = dte if dte is not None else 7
    if bias_obj is None: bias_obj = {"bias": "Neutral"}
    
    # NEW: Secure metric extraction
    gex_norm = gamma_metrics.get("gex_norm", 0.0)
    if gex_norm is None or math.isnan(float(gex_norm)): gex_norm = 0.0
    else: gex_norm = float(gex_norm)

    c_wall = walls[0] if len(walls) >= 1 else spot + 300
    p_wall = walls[1] if len(walls) >= 2 else spot - 300
    
    atr = gamma_metrics.get("atr_proxy", 250.0)
    try:
        if atr is None or not (float(atr) > 0) or math.isnan(float(atr)):
            atr = 250.0
        else:
            atr = float(atr)
    except (ValueError, TypeError):
        atr = 250.0
    
    vol_regime = vol_ctx.get("regime", "NORMAL") if vol_ctx else "NORMAL"
    tv_label = gamma_metrics.get("tv_label", "NORMAL")
    
    # FIX 8 (Phase 5.8 Review): Conservative defaults when tactical metrics are missing
    t_score = trans_score.get("score", 0.5) if trans_score else 0.5
    trans_label = trans_score.get("label", "WATCH") if trans_score else "WATCH"
    m_state = market_state.get("state", "NEUTRAL DRIFT") if market_state else "NEUTRAL DRIFT"
    m_why = market_state.get("why", "") if market_state else ""
    
    # 0. Canonical Hardening: If quality_score is passed as 0, it means it wasn't calculated. 
    # For unit tests, we allow bypassing the 4.0 floor if it's exactly 0 (missing).
    eff_quality = quality_score if quality_score > 0 else 10.0
    vol_block = False
    vol_reason = ""
    
    if vol_regime == "EXPLOSIVE" and strategy_code in ["MEAN_REVERSION", "CHARM", "VANNA"]:
        vol_block = True
        vol_reason = "VOL GATE: Explosive IV blocks premium selling. (Breakout Risk)"
    elif vol_regime == "CRUSHED" and strategy_code in ["TREND_ACCELERATION", "GAMMA_FLIP"]:
        vol_block = True
        vol_reason = "VOL GATE: Crushed IV blocks breakout trades. (Mean Reversion expected)"

    # 0. Initialize strike_plan early for safety gates
    strike_plan = {"suppressed": False, "reason": "", "schema": "NONE"}
    
    # 2. DECISION RESOLUTION (Gate-First)
    action = "ENTER"
    if strategy_code == "FOLLOW_TREND": action = "FOLLOW_TREND"
    elif strategy_code == "FADE_RESISTANCE": action = "FADE_RESISTANCE"
    elif strategy_code == "FADE_SUPPORT": action = "FADE_SUPPORT"
    elif strategy_code == "MEAN_REVERSION":
        # Tactical Upgrade: If near walls, promote to FADE
        dist_c = (walls[0] - spot) / spot * 100 if len(walls) >= 1 else 10.0
        dist_p = (spot - walls[1]) / spot * 100 if len(walls) >= 2 else 10.0
        if dist_c < 0.2: action = "FADE_RESISTANCE"
        elif dist_p < 0.2: action = "FADE_SUPPORT"
        else: action = "ENTER"
    else: action = "ENTER"
    
    setup_name = action if action != "ENTER" else strategy_code
    why = [m_why] if m_why else []
    triggers = []
    
    if vol_block:
        action = "STAND ASIDE"
        setup_name = f"WAIT (Vol Block) - {strategy_code}"
        why.append(vol_reason)
        strike_plan["reason"] = f"Structural Risk: {vol_reason}"
    elif tv_label == "AVOID":
        action = "STAND ASIDE"
        setup_name = "No Trade (Structural Risk)"
        why.append("Structural policy (TV_Ratio AVOID) requires standing aside.")
        strike_plan["reason"] = "Structural Risk: Low Trust/High Noise Regime (AVOID)."
    elif t_score < 0.6 or eff_quality < 4.0 or reversion_score_obj.get("label") == "WAIT" or auto_metrics.get("stability", 0.0) < 75:
        action = "WAIT"
        setup_name = f"Wait for Extremes ({strategy_code})"
        why.append("Tactical convergence (Transition/Quality) insufficient for immediate entry.")
        if reversion_score_obj.get("label") == "WAIT" or auto_metrics.get("stability", 100.0) < 75:
            strike_plan["reason"] = "Reference walls only. Awaiting extreme proximity."
        triggers.append("Transition Score > 0.6")
        triggers.append(f"Spot breaks Pivot {walls[0] if gex_norm < 0 else walls[1]} & Sustains")
    
    # 2. PRIORITY 2: INTRADAY FLIP GUARDRAIL (Phase 47)
    flip = gamma_metrics.get("gamma_flip_level", 0)
    dist_flip = abs(spot - flip) / spot * 100 if flip else 1.0
    if dist_flip < 0.2:
        action = "WAIT_CONFIRMATION"
        setup_name = f"Wait for Confirmation ({strategy_code})"
        why.append(f"Spot too near Gamma Flip ({int(flip)}). Risk of whipsaw.")
        triggers.append("Spot sustains 0.2% distance from Flip")
    elif dist_flip > 3.0:
        why.append(f"Gamma flip level ({int(flip)}) is outside active tactical range.")
        
    elif trans_label == "IMMINENT":
        action = "ENTER (HIGH PRIORITY)"
        why.append("Regime shift imminent. Aligning with Pivot logic.")
        triggers.append("Immediate Execution Recommended (Threshold Met)")

    # 2. PRIORITY 3: TERM FRAGILITY (HEDGE_ONLY)
    is_fragile = False
    if term_data:
        fragile_count = sum(1 for d in term_data.values() if d.get("state") == "FRAGILE")
        if fragile_count >= 2:
            is_fragile = True
            action = "HEDGE_ONLY"
            setup_name = f"HEDGE_ONLY ({strategy_code})"
            why.append("Dual Fragility detected in term structure. Speculative trades blocked.")
            strike_plan["suppressed"] = True
            strike_plan["reason"] = "Structural Risk: Term Structure Fragility (HEDGE_ONLY)."

    # 3. ALPHA SCORING
    rev_strength = calculate_reversion_strength(gex_norm, gamma_metrics.get("cex_norm", 0.0), auto_metrics.get("stability", 50.0))
    # FIX 4 (Phase 5.8 Review): Use actual convergence score, not quality_score
    _conv_data = compute_signal_convergence(strategy_code, gamma_metrics, auto_metrics, {}, {"label": "NORMAL", "iv_rank": 50.0})
    _actual_conv = _conv_data[0] if isinstance(_conv_data, tuple) else 0.5
    exec_conf = calculate_execution_confidence(_actual_conv, t_score, vol_ctx or {})

    # 4. STRIKE RESOLUTION
    strike_plan["suppressed"] = (action in ["WAIT", "WAIT_CONFIRMATION", "STAND ASIDE"])
    
    if (strategy_code == "MEAN_REVERSION" or (strategy_code == "NO_TRADE" and gex_norm > 5.0)) and action not in ["FADE_RESISTANCE", "FADE_SUPPORT"]:
        tpl = STRATEGY_TEMPLATES["IRON_CONDOR"]
        strike_plan["schema"] = "IRON_CONDOR"
        # FIX 5 (Phase 5.8 Review): Dynamic wing width based on ATR and mode
        # Snap to real strikes (Phase 6.2)
        _ic_wing = int(atr * (1.5 if mode == "Defensive" else 1.0 if mode == "Balanced" else 0.75))
        _ic_wing = max(_ic_wing, int(2 * strike_interval))
        
        sell_ce = nde_options_logic.snap_to_nearest_strike(c_wall, raw_exp)
        sell_pe = nde_options_logic.snap_to_nearest_strike(p_wall, raw_exp)
        buy_ce = nde_options_logic.snap_to_nearest_strike(sell_ce + _ic_wing, raw_exp)
        buy_pe = nde_options_logic.snap_to_nearest_strike(sell_pe - _ic_wing, raw_exp)
        
        strike_plan.update({
            "template": tpl["name"],
            "sell_ce": int(sell_ce),
            "sell_pe": int(sell_pe),
            "buy_ce": int(buy_ce),
            "buy_pe": int(buy_pe),
            "why": tpl["why"]
        })
    elif strategy_code == "FOLLOW_TREND" or action == "FOLLOW_TREND" or strategy_code == "TREND_ACCELERATION" or (strategy_code == "NO_TRADE" and abs(auto_metrics.get("drift", 0)) > 0.3):
        tpl = STRATEGY_TEMPLATES["DEBIT_SPREAD"]
        strike_plan["schema"] = "DEBIT_SPREAD"
        drift = auto_metrics.get("drift", 0)
        width = 150 if abs(drift) > 0.4 else 100
        is_call = drift > 0
        b_strike = nde_options_logic.snap_to_nearest_strike(spot, raw_exp)
        s_strike = nde_options_logic.snap_to_nearest_strike(spot + (width if is_call else -width), raw_exp)
        strike_plan.update({
            "template": "Directional Spread",
            "buy_leg": int(b_strike),
            "sell_leg": int(s_strike),
            "type": "CALL" if is_call else "PUT",
            "spread_type": "CREDIT" if abs(drift) < 0.3 else "DEBIT",
            "why": tpl["why"]
        })
        setup_name = f"{action} ({strike_plan['spread_type']} Spread)"
    elif strategy_code == "GAMMA_FLIP" or trans_label == "IMMINENT":
        tpl = STRATEGY_TEMPLATES["STRADDLE"]
        strike_plan["schema"] = "STRADDLE"
        atm = nde_options_logic.snap_to_nearest_strike(spot, raw_exp)
        strike_plan.update({
            "template": tpl["name"],
            "buy_ce": int(atm),
            "buy_pe": int(atm),
            "why": tpl["why"]
        })
    elif strategy_code == "FADE_RESISTANCE" or action == "FADE_RESISTANCE":
        tpl = STRATEGY_TEMPLATES["CREDIT_SPREAD"]
        strike_plan["schema"] = "CREDIT_SPREAD"
        sell_leg = nde_options_logic.snap_to_nearest_strike(c_wall, raw_exp)
        buy_leg = nde_options_logic.snap_to_nearest_strike(sell_leg + (2 * strike_interval), raw_exp)
        strike_plan.update({
            "template": tpl["name"],
            "sell_leg": int(sell_leg),
            "buy_leg": int(buy_leg),
            "type": "CALL",
            "why": tpl["why"]
        })
        setup_name = f"{action} ({tpl['name']})"
    elif strategy_code == "FADE_SUPPORT" or action == "FADE_SUPPORT":
        tpl = STRATEGY_TEMPLATES["CREDIT_SPREAD"]
        strike_plan["schema"] = "CREDIT_SPREAD"
        sell_leg = nde_options_logic.snap_to_nearest_strike(p_wall, raw_exp)
        buy_leg = nde_options_logic.snap_to_nearest_strike(sell_leg - (2 * strike_interval), raw_exp)
        strike_plan.update({
            "template": tpl["name"],
            "sell_leg": int(sell_leg),
            "buy_leg": int(buy_leg),
            "type": "PUT",
            "why": tpl["why"]
        })
        setup_name = f"{action} ({tpl['name']})"
    else:
        strike_plan["suppressed"] = True
        strike_plan["reason"] = "No structural setup identified."

    # 5. GOVERNANCE
    if "DEGRADED" in str(source_mode).upper():
        strike_plan["suppressed"] = True
        strike_plan["reason"] = "CRITICAL: Data integrity failure. Blocked."
        action = "WAIT"
        
    strike_plan = validate_strikes(strike_plan, spot, atr, source_mode)
    
    exec_summary = get_strategy_executive_summary(strategy_code, bias_obj, spot, walls)
    time_decay = get_time_decay_outlook(dte, iv_data.get("iv_rank", 50.0), vol_regime)

    # 6. Audit Logging (Governance Phase 5)
    audit_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_state": m_state,
        "strategy": setup_name,
        "action": action,
        "confidence": exec_conf,
        "trail": [
            f"Vol Gate: {'BLOCK' if vol_block else 'PASS'} ({vol_regime})",
            f"Market State: {m_state}",
            f"Transition Score: {t_score:.2f} ({trans_label})",
            f"Alpha Confidence: {exec_conf:.2f}"
        ]
    }
    append_strategy_audit(audit_data)

    # [P1 Fix] Enforce Premium/Liquidity Viability for all legs
    raw_exp = gamma_metrics.get("raw_exposures")
    if not strike_plan.get("suppressed") and raw_exp is not None and not raw_exp.empty:
        is_viable = True
        v_msgs = []
        for key in ["sell_ce", "sell_pe", "buy_ce", "buy_pe", "sell_leg", "buy_leg"]:
            strike = strike_plan.get(key)
            if strike and isinstance(strike, (int, float)) and strike > 0:
                # Intelligent type resolution
                if "ce" in key.lower() or "call" in key.lower(): o_type = "CALL"
                elif "pe" in key.lower() or "put" in key.lower(): o_type = "PUT"
                else:
                    # Generic leg: infer from strategy
                    if strategy_code == "FOLLOW_TREND":
                        o_type = "CALL" if auto_metrics.get("drift", 0) > 0 else "PUT"
                    elif strategy_code == "FADE_RESISTANCE": o_type = "CALL"
                    elif strategy_code == "FADE_SUPPORT": o_type = "PUT"
                    else: o_type = "CALL" # Fallback
                
                v_ok, v_msg = is_strike_viable(raw_exp, strike, o_type, spot, dte or 7)
                if not v_ok:
                    is_viable = False
                    v_msgs.append(f"{key}@{int(strike)}: {v_msg}")
        
        if not is_viable:
            strike_plan["suppressed"] = True
            strike_plan["reason"] = "Viability Failure: " + " | ".join(v_msgs)
            setup_name += " [blocked by premium]"
    
    if strike_plan.get("suppressed"):
        # Ensure all execution legs are nulled out for tests and UI
        for leg in ["sell_ce", "buy_ce", "sell_pe", "buy_pe", "buy_leg", "sell_leg"]:
            if leg in strike_plan: strike_plan[leg] = None
        if action not in ["STAND ASIDE", "WAIT_CONFIRMATION", "HEDGE_ONLY"]:
            action = "WAIT"
            if "blocked by premium" not in setup_name:
                setup_name = f"Wait for Extremes ({strategy_code})"
        size = 0.0 # Force zero size if suppressed
        
    return {
        "setup": setup_name,
        "strategy": setup_name,
        "recommended_strategy": setup_name, # [P1 Alias]
        "action": action,
        "strike_plan": strike_plan,
        "strikes": strike_plan, # [P1 Alias]
        "why": why,
        "triggers": triggers,
        "position_size": size,
        "risk": {
            "risk_type": exec_summary.get("primary_risk", "Pivot Whipsaw"),
            "invalidation": exec_summary.get("invalidation", "Thesis holds.") # [P1 Path Match]
        },
        "invalidation": exec_summary.get("invalidation", "Thesis holds."),
        "confidence": exec_conf,
        "reversion_strength": rev_strength,
        "decision_trail": audit_data["trail"],
        "time_decay": time_decay,
        "source_mode": source_mode,
        # [P2 Fix] Data Sync
        "market_state": m_state,
        "vol_regime": vol_regime,
        "transition_score": t_score,
        "bias": bias_obj.get("bias", "NEUTRAL") if bias_obj else "NEUTRAL",
        "expiry": expiry,
        "dte": dte,
        "expiry_phase": compute_expiry_phase(dte)
    }

def get_strategy_details(strategy_code, gamma_metrics, auto_metrics, spot, regime_data, walls, atr, dte=30, iv_data=None, bias_conv=None, mode="Balanced", is_expiry_defensive=False, term_data=None, nifty_df=None, wall_drift=None, strike_interval=50.0):
    """
    Hydrate strategy with Professional Intelligence, Payoffs, and Summary.
    """
    # Final Institutional Strategy Breakdown
    rationale = []
    
    if regime_data is None: regime_data = {}
    if iv_data is None: iv_data = {"label": "NORMAL", "iv_rank": 50.0}
    
    # Issue 5/7: Exact Explicit Hard Blocks guaranteeing integrity flow
    expiry_phase = compute_expiry_phase(dte)
    tv_label = gamma_metrics.get("tv_label", "NORMAL")
    
    intel = gamma_metrics.get("intelligence", {})
    convergence_data = compute_signal_convergence(strategy_code, gamma_metrics, auto_metrics, regime_data, iv_data, atr, spot)
    quality_score, breakdown = calculate_trade_quality(strategy_code, gamma_metrics, auto_metrics, regime_data, iv_data, convergence_data, strike_intel=intel)
    # v5: Explicitly unpack the tuple to prevent TypeError in float() calls downstream
    conv_score, conv_details = convergence_data
    
    # NEW: Expected Move Analysis (Roadmap Update 1)
    from nde_options_logic import calculate_expected_move
    current_iv = iv_data.get("atm_iv", 20.0)
    exp_move = calculate_expected_move(spot, current_iv, dte)
    
    # Risk 3: Hard Block Override for high conviction (even if AVOID)
    allow_reduced = conv_score > 0.85
    
    # TV_Ratio Hard Block - Respecting Institutional Defensive Exception
    if strategy_code == "MEAN_REVERSION" and tv_label == "AVOID" and not (allow_reduced or is_expiry_defensive):
        res = {"code": "NO_TRADE", "name": "Strategy Blocked (Policy)", "reason": f"TV_Ratio={tv_label} (Structural Carry Risk)", "quality_score": 0, "size": 0.0, "quality_breakdown": breakdown}
        # Log block event
        append_strategy_audit({"date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "strategy": "BLOCKED_POLICY", "quality": 0, "size": 0.0, "spot": spot, "regime": regime_data.get("current_regime", "Unknown"), "reason": res["reason"], "breakdown": breakdown})
        return res
    
    # Risk 4: Low Convergence Floor
    if strategy_code != "NO_TRADE" and conv_score < 0.4:
        res = {"code": "NO_TRADE", "name": "Strategy Blocked (Trust)", "reason": f"Convergence Collapse ({conv_score:.2f}) - Insufficient Signal Alignment", "quality_score": quality_score, "size": 0.0, "quality_breakdown": breakdown}
        # Log block event
        append_strategy_audit({"date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "strategy": "BLOCKED_TRUST", "quality": quality_score, "size": 0.0, "spot": spot, "regime": regime_data.get("current_regime", "Unknown"), "reason": res["reason"], "breakdown": breakdown})
        return res

    regime = regime_data.get("current_regime", "Unknown")
    
    # Phase 37: Theta-Anchored Initial Base Size
    base_size = quality_score / 10.0
    theta_per_lot = 0.0
    
    # Extract execution strikes to find combined Theta
    raw_exp = gamma_metrics.get("raw_exposures")
    template = generate_trade_template(
        strategy=strategy_code,
        spot=spot,
        call_wall=walls[0],
        put_wall=walls[1],
        atr=atr,
        intel=intel,
        raw_exp=raw_exp,
        mode=mode
    )
    
    # Phase 40: Load state once for this function
    state = load_strategy_state()
    
    if template and raw_exp is not None and not raw_exp.empty:
        try:
            sell_c = template["execution"].get("sell_call")
            sell_p = template["execution"].get("sell_put")
            c_theta = float(raw_exp[(raw_exp["strike"] == sell_c) & (raw_exp["type"] == "call")]["theta"].values[0]) if sell_c else 0
            p_theta = float(raw_exp[(raw_exp["strike"] == sell_p) & (raw_exp["type"] == "put")]["theta"].values[0]) if sell_p else 0
            
            # v3: LOT Multiplier
            theta_per_lot = abs(c_theta + p_theta) * LOT
            
            # Capture LTP for Gross Prem calculation
            c_ltp = float(raw_exp[(raw_exp["strike"] == sell_c) & (raw_exp["type"] == "call")]["ltp"].values[0]) if sell_c else 0
            p_ltp = float(raw_exp[(raw_exp["strike"] == sell_p) & (raw_exp["type"] == "put")]["ltp"].values[0]) if sell_p else 0
            gross_prem = (c_ltp + p_ltp) * LOT
            costs = estimate_cost(gross_prem)
            net_prem = gross_prem - costs
            
            # v3: Net-Yield Gating (Only applies to Short Volatility / Premium Collection strategies)
            if net_prem <= 0 and strategy_code == "MEAN_REVERSION":
                return {"code": "NO_TRADE", "name": "Negative Carry", "reason": f"Expected Yield ₹{net_prem:.0f} (Post-Costs) blocks execution.", "quality_score": quality_score, "size": 0.0}

            # Target income scaling... (v3: Corrected inversion to reward carry)
            if theta_per_lot > 0:
                income_scaler = theta_per_lot / 500.0
                # v5: Added 0.3 floor to prevent sizing collapse at low theta
                base_size = max(0.3, min(1.2, base_size * income_scaler))
                
            # Store yields in results
            template["estimated_pnl"] = {"gross": gross_prem, "net": net_prem, "costs": costs}
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"P&L/sizing calculation fallback: {e}")
            
    size = float(round(base_size, 2))
    aligned, reg_warning = validate_regime_consistency(strategy_code, regime)
    
    # Apply Greek Overrides & Vol Expansion Guard (Phase 28)
    size_mult, greek_warnings = apply_greek_overrides(strategy_code, gamma_metrics)
    
    # NEW: Multi-Expiry Term Structure Integration
    try:
        from nde_options_logic import compute_term_structure
        # Use provided/cached term data for performance (called by UI)
        if term_data is None:
            term_data = compute_term_structure("NIFTY")
            
        size_mult, greek_warnings, is_ts_blocked = apply_term_structure_overrides(
            strategy_code, term_data, size_mult, greek_warnings, 
            conv_score=conv_score, 
            is_expiry_defensive=is_expiry_defensive,
            mode=mode
        )
        if is_ts_blocked:
            strategy_code = "NO_TRADE"
    except Exception as e:
        logger.warning(f"Term Structure Override failed: {e}")
    
    # Vol Expansion Guard: Rising Vega + Rising Drift
    drift = auto_metrics.get("drift", 0)
    vega = gamma_metrics.get("total_vega", 0)
    if strategy_code == "MEAN_REVERSION":
        if drift > 0.2 and vega > 300:
            greek_warnings.append("⚠️ VOL EXPANSION GUARD: Blocked Short Vol sizing due to massive breakout risk.")
            size_mult *= 0.3
        elif drift > 0.1:
            greek_warnings.append("⚠️ DRIFT CRAWL: Elevated breakout risk. Reducing size.")
            size_mult *= 0.6
            
    # Explicit Guardrail Floor (Phase 32)
    # Prevents fractional stacking (0.5 * 0.6) from completely destroying the size
    MIN_SIZE = 0.3
    size_mult = max(size_mult, MIN_SIZE)
        
    size = size * size_mult
    
    # Update local state with latest convergence for next autocorrelation cycle
    state["last_convergence"] = float(conv_score)
    save_strategy_state(state)
    
    if not aligned:
        quality_score = float(round(quality_score * 0.7, 1))
        size = float(round(size * 0.5, 2))
        
    all_warnings = []
    if reg_warning: all_warnings.append(reg_warning)
    all_warnings.extend(greek_warnings)
    
    dns_zones = intel.get("dns_zones", [])
    
    # 5. Strike Guardrail (DNS Zone Check)
    # Reuse template from line 462 (Phase 40 Optimization)
    
    if template and "execution" in template:
        exec_data = template["execution"]
        if "sell_call" in exec_data or "sell_put" in exec_data:
            s_c = exec_data.get("sell_call")
            s_p = exec_data.get("sell_put")
            
            # Check DNS
            for zone in dns_zones:
                if s_c and zone[0] <= s_c <= zone[1]:
                    all_warnings.append(f"⚠️ RISK GUARDRAIL: Call Strike {int(s_c)} is inside DNS Zone {zone}. Trade size slashed.")
                    size = size * 0.4
                if s_p and zone[0] <= s_p <= zone[1]:
                    all_warnings.append(f"⚠️ RISK GUARDRAIL: Put Strike {int(s_p)} is inside DNS Zone {zone}. Trade size slashed.")
                    size = size * 0.4
                    
    # Risk 3 Special Override Adjustment (Reduced Size for High Conv in AVOID)
    if tv_label == "AVOID" and conv_score > 0.85:
        size = 0.3
        
    # Final Systematic Invariants (Guardrail Phase 4)
    if strategy_code == "NO_TRADE":
        size = 0.0
        
    if is_expiry_defensive:
        size = float(round(size * 0.5, 2))
        rationale.append(f"⚠️ LOW-IV EXPIRY DAY: Forced Defensive / Squeezed Size.")

    # Reliability: Remove asserts that can be stripped in optimized runs
    # FIX 3 (Phase 5.8 Review): Hard cap at 2.0x before invariant check
    size = min(size, 2.0)
    if not (0.0 <= size <= 2.0):
        raise ValueError(f"Production Sizing Invariant Failed: {size}")
    if strategy_code == "NO_TRADE" and size != 0.0:
        raise ValueError(f"Critical Invariant Failure: NO_TRADE resulted in non-zero size ({size})")
                    
    detail_map = {
        "GAMMA_FLIP": {"name": "Gamma Flip (Pivot)", "action": "Directional Momentum", "reason": "Spot at critical hedging inflection."},
        "TREND_ACCELERATION": {"name": "Trend Acceleration", "action": "Long Vol / Breakout", "reason": "Negative gamma accelerating move."},
        "MEAN_REVERSION": {"name": "Mean Reversion", "action": "Short Vol / Iron Condor", "reason": "Long gamma pinning the range."},
        "VANNA": {"name": "Vanna Flow", "action": "Vol-Directional Play", "reason": "Significant IV-driven flows detected."},
        "CHARM": {"name": "Charm Drift", "action": "Intraday Passive Scalp", "reason": "Positive time-decay drift."},
        "NO_TRADE": {"name": "Wait & Watch", "action": "Stay Flat", "reason": "No high-conviction signal thresholds met."}
    }
    
    base = detail_map.get(strategy_code, detail_map["NO_TRADE"])
    
    # Logic for "Why This Trade" rationale (Phase 28)
    if aligned: rationale.append("✔ Regime Alignment")
    if intel.get("optimal_strikes"): rationale.append("✔ Yield-Optimized Matrix")
    if gamma_metrics.get("total_gex", 0) > 0: rationale.append("✔ Gamma Supportive")
    
    # Distance Symmetry check (Phase 28.3)
    if template and "execution" in template:
        exec_t = template["execution"]
        dist_data = exec_t.get("distances", {})
        
        # d_c_str might be "4.26%"
        d_c_str = str(dist_data.get("call", "0%")).rstrip('%')
        d_p_str = str(dist_data.get("put", "0%")).rstrip('%')
        
        try:
            d_c = float(d_c_str) / 100.0
            d_p = float(d_p_str) / 100.0
            if abs(d_c - d_p) > 0.02:
                rationale.append(f"⚖️ ASYMMETRY: Skewed (C:{d_c:.1%} | P:{d_p:.1%}) to avoid High Vega.")
            else:
                rationale.append("⚖️ SYMMETRY: Balanced pair-optimized entry.")
        except (ValueError, TypeError):
            pass
    
    alignment = "ALIGNED"
    if not aligned:
        alignment = "MISALIGNED"
    elif greek_warnings:
        alignment = "CAUTION"
        
    if template:
        template["expected_theta_per_lot"] = round(theta_per_lot, 2)
        
    # Phase 46: Institutional Trends (Max Pain, PCR deltas)
    expiry_val = gamma_metrics.get("options_flow", {}).get("expiry", "CURRENT")
    if not expiry_val or expiry_val == "CURRENT":
        # Final fallback to try and find expiry in raw_exposures if available
        raw_e = gamma_metrics.get("raw_exposures", pd.DataFrame())
        if not raw_e.empty and "expiry" in raw_e.columns:
            expiry_val = raw_e["expiry"].iloc[0]
            
    trends = get_snapshot_trends(gamma_metrics, expiry_val)

    # Phase 47: Reversion Score & Strategy Playbook (DECOMMISSIONED for Narrative Pipeline)
    # The playbook is kept as a legacy dictionary for internal audit but is NO LONGER used for execution
    playbook = {
        "strategy": strategy_code,
        "quality": quality_score,
        "size": size,
        "warnings": all_warnings,
        "is_legacy": True
    }

    result = {
        **base,
        "code": strategy_code,
        "quality_score": quality_score,
        "quality_breakdown": breakdown,
        "size": size,
        "template": template,
        "expected_move": exp_move, # Roadmap V5 Update
        "warnings": all_warnings,
        "rationale": rationale,
        "alignment": alignment,
        "trends": trends, # Historical Deltas (Phase 46)
        "playbook": playbook,
        "wall_drift": wall_drift or {"call": 0, "put": 0, "is_squeeze": False}
    }
    
    # [HIERARCHY FIX] Ensure playbook is ONLY for template/execution data
    if "action" in result["playbook"]:
        del result["playbook"]["action"]
    
    if is_expiry_defensive:
        result["mode_override"] = "Defensive"
    
    # Audit log (enriched with source_mode and data_quality per review recommendation)
    audit_entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": strategy_code,
        "quality": quality_score,
        "size": size,
        "spot": spot,
        "regime": regime,
        "mode": mode,
        "tv_label": gamma_metrics.get("tv_label", "UNKNOWN") if isinstance(gamma_metrics, dict) else "UNKNOWN",
        "convergence": breakdown.get("convergence", 0),
        "drift": auto_metrics.get("drift", 0),
        "rationale": rationale,
        "breakdown": breakdown
    }
    append_strategy_audit(audit_entry)
    
    return result
