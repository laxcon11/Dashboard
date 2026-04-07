import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any

# ==================== CONFIG & CALIBRATION (v3) ====================
import NSE_Config
LOT = NSE_Config.NIFTY_LOT_SIZE
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
    "PERSISTENCE_MIN_DAYS": 2
}

STRATEGY_WEIGHTS = {
    "regime": 0.40,
    "strike": 0.30,
    "risk": 0.30
}

# ==================== STATE MANAGEMENT ====================
STATE_FILE = Path("notes/strategy_state.json")
AUDIT_FILE = Path("notes/nde_strategy_log.jsonl")

def load_strategy_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try: 
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                return data
        except: pass
    return {"last_strategy": "NO_TRADE", "persistence_days": 1, "last_update": ""}

def save_strategy_state(state: Dict[str, Any]):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ==================== CORE ENGINES ====================
from nde_automation_logic import normalize_regime_name
import nde_options_logic
import nde_automation_logic

def generate_engine_context(
    raw_chain: pd.DataFrame, spot: float, nifty_df: pd.DataFrame, used_expiry: str,
    regime_history: list, regime_snap: dict, vix_df: pd.DataFrame, meta: dict = None, mode: str = "Balanced",
    source: str = "UNKNOWN"
) -> dict:
    """Unified engine context calculation that abstracts math away from the Streamlit UI."""
    meta = meta or {}
    
    # 1. Advanced Metrics Calculation (Relocated from UI)
    atr = nde_options_logic.calculate_atr_sma(nifty_df)
    t_days = nde_options_logic.calculate_dte_fractional(used_expiry)
    quality_score = meta.get("data_quality_score", 1.0)
    
    # 2. Flow & Walls
    if not raw_chain.empty:
        subset = raw_chain.copy()
        subset["t_days"] = t_days
        flow_metrics = nde_options_logic.compute_option_flow_exposures(spot, subset)
        call_wall, put_wall = nde_options_logic.calculate_option_walls(raw_chain)
        current_atm_iv = nde_options_logic.compute_atm_iv(subset, spot)
    else:
        flow_metrics = {
            "total_gex": 0, "total_gex_abs": 0, "total_vega": 0, "total_theta": 0, "total_delta": 0, 
            "total_volume": 0.0, "total_oi_chng": 0.0, "flow_regime_label": "Unknown",
            "intelligence": {}, "raw_exposures": pd.DataFrame()
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
    
    # 4. IV Rank
    if vix_df is not None and not vix_df.empty:
        iv_data = nde_options_logic.compute_iv_rank(current_atm_iv, vix_df["Close"])
    else:
        iv_data = {"label": "UNKNOWN", "iv_rank": 50.0}

    # 5. Regime Normalization
    if regime_snap and "current_regime" not in regime_snap:
        regime_snap["current_regime"] = regime_snap.get("regime_label", "Unknown")

    # 6. Master Strategy Selection
    strategy_code = select_master_strategy(flow_metrics, auto_metrics, spot, regime_snap, dte=t_days, atr=atr)
    
    # 7. Hydrate Strategy Selection
    intel = flow_metrics.get("intelligence", {}).copy()
    if not raw_chain.empty and "raw_exposures" in flow_metrics:
        intel["optimal_strikes"] = nde_options_logic.select_optimal_strikes(
            flow_metrics["raw_exposures"], spot, 
            flow_metrics={"total_gex": flow_metrics.get("total_gex", 0), "total_vega": flow_metrics.get("total_vega", 0)},
            mode=mode
        )
    flow_metrics["intelligence"] = intel
    
    master_setup = get_strategy_details(
        strategy_code, flow_metrics, auto_metrics, spot, regime_snap, (call_wall, put_wall), atr, dte=t_days, iv_data=iv_data
    )
    
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
            "label": regime_snap.get("current_regime", "Unknown").upper(),
            "color": {"RISK_ON": "#00c853", "SELECTIVE": "#ffd600", "DEFENSIVE": "#ff9100", "CRISIS": "#ff1744"}.get(regime_snap.get("current_regime", ""), "gray")
        },
        "greeks": {
            "delta": nde_options_logic.format_institutional_metric(flow_metrics.get("total_delta", 0), "Cr"),
            "gex_abs": nde_options_logic.format_institutional_metric(flow_metrics.get("total_gex_abs", 0), "Cr"),
            "gex_net": nde_options_logic.format_institutional_metric(flow_metrics.get("total_gex", 0), "Cr"),
            "vega": nde_options_logic.format_institutional_metric(flow_metrics.get("total_vega", 0), "Cr"),
            "theta": nde_options_logic.format_institutional_metric(flow_metrics.get("total_theta", 0), "Cr")
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
        }
    }

    return {
        "flow_metrics": flow_metrics,
        "auto_metrics": auto_metrics,
        "walls": (call_wall, put_wall),
        "iv_data": iv_data,
        "strategy_code": strategy_code,
        "master_setup": master_setup,
        "regime_snap": regime_snap,
        "current_atm_iv": current_atm_iv,
        "atr": atr,
        "t_days": t_days,
        "quality_score": quality_score,
        "ui_display": ui_display
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
    # 2. GST on Brokerage
    gst = brokerage * GST_PCT
    # 3. STT (Sell side only for options)
    stt = premium * STT_SELL_OPT_PCT
    # 4. Slippage (Execution drag)
    slippage = premium * EST_SLIPPAGE_PCT
    # 5. Other (Exchange fees, SEBI, Stamp)
    other = premium * OTHER_CHARGES_PCT
    
    return float(round(brokerage + gst + stt + slippage + other, 2))

def compute_signal_convergence(strategy_code: str, gamma_metrics: dict, auto_metrics: dict, regime_data: dict, iv_data: dict, atr: float = 250.0, spot: float = 22500.0) -> tuple[float, dict]:

    """
    Returns a Convergence Score (0.0 to 1.0) and orthogonal bucket booleans validating independent signals.
    """
    if strategy_code == "NO_TRADE":
        return 0.0, {}

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
        buckets = {"macro": True, "flow": True, "structure": True, "momentum": False, "vol": False}
        
    weights = {
        "macro": 0.30, 
        "flow": 0.25, 
        "structure": 0.20, 
        "momentum": 0.15,  # Phase 40: Cleaned up redundant min(0.15, 0.20)
        "vol": 0.10
    }
    raw_score = sum(weights[k] for k, v in buckets.items() if v)

    # Phase 42: Volume/OI Engagement Boost
    # If we have "Institutional Churn" in the engagement zone, boost convergence
    flow_regime = gamma_metrics.get("flow_regime_label", "Passive")
    if flow_regime == "Institutional Churn":
        raw_score += 0.05
    elif flow_regime in ["Active Accumulation", "Directional Engagement"]:
        raw_score += 0.02
    
    # Risk 1: Nonlinear amplification
    score = (min(raw_score, 1.0)) ** 1.3
    
    # Risk 1: Convergence Saturation Penalty (Autocorrelation)
    state = load_strategy_state()
    prev_conv = state.get("recent_convergence_mean", 0.5)
    if prev_conv > 0.6:
        autocorr_penalty = prev_conv - 0.5
        score *= (1 - 0.1 * autocorr_penalty)
    
    assert 0.0 <= score <= 1.0, f"Integrity Failure: Convergence out of bounds -> {score}"
    
    # Cast buckets to native bools to prevent JSON serialization issues (e.g. numpy.bool_)
    safe_buckets = {k: bool(v) for k, v in buckets.items()}
    
    return float(round(score, 4)), safe_buckets

def calculate_trade_quality(strategy_code, gamma_metrics, auto_metrics, regime_data, iv_data, convergence_data, strike_intel=None):
    """
    Score: 1-10 based on weighted tactical alignment + IV Rank scaling + Convergence verification.
    """
    convergence_score, convergence_buckets = convergence_data
    
    regime = normalize_regime_name(regime_data.get("current_regime", "Unknown"))
    REGIME_MAP = {"RISK_ON": 10, "SELECTIVE": 8, "DEFENSIVE": 6, "CRISIS": 2}
    regime_score = REGIME_MAP.get(regime, 5)
    
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
    
    w = STRATEGY_WEIGHTS
    total_score = (regime_score * w["regime"] + strike_score * w["strike"] + risk_score * w["risk"])
    
    # Phase 37: Convergence & IV Adjustments
    IV_QUALITY_MAP = {"ELEVATED": 1.00, "NORMAL": 0.85, "COMPRESSED": 0.65, "CRUSHED": 0.40}
    iv_multiplier = IV_QUALITY_MAP.get(iv_data.get("label", "NORMAL"), 0.85)
    
    if strategy_code in ("MEAN_REVERSION", "CHARM"):
        total_score *= iv_multiplier
        
    # Convergence Penalty
    if convergence_score < 0.5:
        total_score *= 0.7 # Heavy penalty for low confirmation
        
    total_score = max(0.0, min(10.0, total_score))
    
    breakdown = {
        "regime": float(round(regime_score, 1)),
        "strike": float(round(strike_score, 1)),
        "risk": float(round(risk_score, 1)),
        "convergence": float(round(convergence_score, 2)),
        "convergence_buckets": convergence_buckets,
        "iv_mult": float(round(iv_multiplier, 2))
    }
    
    return float(round(total_score, 1)), breakdown

def calculate_position_sizing(confidence, regime, strategy):
    """
    Sizing: 0.5x to 1.2x
    """
    reg = normalize_regime_name(regime)
    base_size = confidence / 100.0
    
    if strategy == "GAMMA_FLIP":
        size = base_size + 0.2
    elif reg == "CRISIS":
        size = base_size * 0.4
    elif reg == "DEFENSIVE":
        size = base_size * 0.7
    else:
        size = base_size
        
    size = float(int(max(0.5, min(1.2, size)) * 100) / 100.0)
    assert 0.5 <= size <= 1.2 or size == 0, f"Position sizing invariant failed: {size}"
    return size

def validate_regime_consistency(strategy, regime):
    """
    Returns (is_aligned, warning_msg)
    """
    reg = normalize_regime_name(regime)
    if reg == "CRISIS" and strategy == "MEAN_REVERSION":
        return False, "⚠️ Warning: Mean Reversion in CRISIS carries extreme tail risk."
    return True, ""

def apply_term_structure_overrides(strategy_code, term_data, size_mult, warnings, conv_score=1.0):
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
            if conv_score < 0.7:
                is_blocked = True
                warnings.append("🚫 CRITICAL BLOCK: Mid-cycle fragility + Low convergence blocks Mean Reversion.")
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

def generate_trade_template(strategy, spot, call_wall, put_wall, atr, intel=None, raw_exp=None):
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
        
        # Guard against NaN values from missing data or unresolvable walls
        if not sell_c or math.isnan(sell_c): sell_c = call_wall
        if not sell_p or math.isnan(sell_p): sell_p = put_wall
        
        if not sell_c or not sell_p or math.isnan(sell_c) or math.isnan(sell_p): 
            return None
            
        return {
            "execution": enrich_execution(sell_c, sell_p),
            "stop": {"upper": int(sell_c + (0.5 * atr)), "lower": int(sell_p - (0.5 * atr))},
            "position_type": "SHORT_VOL (Neutral)"
        }
    elif strategy == "TREND_ACCELERATION":
        bias = "Bullish" if spot > ( (call_wall + put_wall)/2 ) else "Bearish"
        return {
            "execution": {"type": "ATM Straddle or Breakout", "bias": bias, "vol_edge": "Rising"},
            "stop": {"points": int(1.5 * atr)},
            "position_type": "LONG_VOL (Directional)"
        }
    elif strategy == "GAMMA_FLIP":
        return {
            "execution": {"trigger": "Above Flip: Long, Below Flip: Short", "context": "Hedging Pivot"},
            "stop": {"points": int(1.0 * atr)},
            "position_type": "MOMENTUM_PIVOT"
        }
    elif strategy == "VANNA":
        return {
            "execution": {"type": "Volatility-Weighted Spread", "context": "Vanna/IV Flow"},
            "stop": {"points": int(2.0 * atr)},
            "position_type": "VOL_DIRECTIONAL"
        }
    elif strategy == "NO_TRADE":
        return None
        
    # Default/Charm
    return {
        "execution": {"type": "Passive Intraday Scalp (Charm)"},
        "stop": {"points": int(1.0 * atr)},
        "position_type": "INTRADAY_BIAS"
    }

# ==================== MAIN LOGIC ====================

from nde_automation_logic import compute_expiry_phase

def select_master_strategy(gamma_metrics, auto_metrics, spot, regime_data, dte=30, atr=250.0):
    """
    Deterministic Selection with Priority Logic & Cycle Awareness.
    """
    # Phase 40: Cache state reads (was 3 separate file reads)
    cfg = STRATEGY_CONFIG
    state = load_strategy_state()
    
    flip_level = gamma_metrics.get("gamma_flip_level", None)
    gamma = gamma_metrics.get("total_gex", 0)
    vanna = gamma_metrics.get("total_vex", 0)
    charm = gamma_metrics.get("total_cex", 0)
    
    drift = auto_metrics.get("drift", 0)
    stability = auto_metrics.get("stability", 50)
    
    expiry_phase = compute_expiry_phase(dte)
    adaptive_flip_threshold = max(0.005, (atr / spot) * 0.5) if spot > 0 else cfg["GAMMA_FLIP_THRESHOLD"]
    mean_rev_stab_threshold = 65 + max(0, (5 - dte) * 3) # Scales up to 80 in final 0-days
    
    strategy_code = "NO_TRADE"
    
    # Gamma Flip Hysteresis & Adaptive bounds (v3)
    last_strat = str(state.get("last_strategy", "NO_TRADE"))
    
    # Adaptive Flip Threshold: max(0.5%, (0.5 * ATR / Spot))
    flip_thresh = max(0.005, 0.5 * atr / spot) if spot > 0 else 0.005
    
    # Hysteresis expansion
    active_flip_threshold = flip_thresh * 1.5 if last_strat == "GAMMA_FLIP" else flip_thresh
    
    flip_dist = abs(spot - flip_level) / spot if flip_level is not None and spot > 0 else 1.0
    flip_vel = state.get("flip_velocity", 0.0)
    
    # Velocity Tightening: High velocity = dangerous = tighten the window
    # v3: Unit Calibration - flip_vel is in Million-per-lot, thresh is 1.0 units (1M/lot)
    if flip_vel > 1.0: 
        active_flip_threshold *= 0.7
    
    if flip_level is not None and flip_dist < active_flip_threshold:
        strategy_code = "GAMMA_FLIP"
    elif gamma_metrics.get("gex_norm", 0) < 0 and abs(drift) > cfg["TREND_DRIFT_THRESHOLD"]:
        strategy_code = "TREND_ACCELERATION"
    elif gamma_metrics.get("gex_norm", 0) > 0 and stability > mean_rev_stab_threshold:
        tv_label = gamma_metrics.get("tv_label", "NORMAL")
        if expiry_phase not in ["PRE_EXPIRY", "EXPIRY_RISK"] and tv_label != "AVOID":
            strategy_code = "MEAN_REVERSION"
        else:
            strategy_code = "CHARM"
    elif abs(gamma_metrics.get("vex_norm", 0)) > cfg["VANNA_THRESHOLD_NORM"]:
        strategy_code = "VANNA"
    elif gamma_metrics.get("cex_norm", 0) > cfg["CHARM_THRESHOLD_NORM"]: 
        strategy_code = "CHARM"
        
    state = state  # Already loaded above (Phase 40 caching)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # State tracking expansions: TV EMA (Fast vs Slow) & Flip Velocity (Risks 2 & 3 & 5)
    # v3: Use lot-normalized GEX for velocity to avoid million-vs-point unit mismatch
    current_tv = gamma_metrics.get("tv_ratio", 1.0)
    current_gex_norm = gamma_metrics.get("gex_norm", 0.0)
    
    if state.get("last_update") != today_str:
        # Fast (5d) and Slow (20d) EWMA
        last_tv_fast = state.get("tv_ratio_ema_fast", current_tv)
        last_tv_slow = state.get("tv_ratio_ema_slow", current_tv)
        state["tv_ratio_ema_fast"] = (current_tv * 0.3) + (last_tv_fast * 0.7)
        state["tv_ratio_ema_slow"] = (current_tv * 0.1) + (last_tv_slow * 0.9)
        
        last_gex_norm = state.get("last_gex_norm", current_gex_norm)
        state["flip_velocity"] = abs(current_gex_norm - last_gex_norm)
        state["last_gex_norm"] = current_gex_norm
        
        # Track recent convergence for saturation penalty
        last_conv = state.get("last_convergence", 0.5)
        prev_mean = state.get("recent_convergence_mean", 0.5)
        state["recent_convergence_mean"] = (last_conv * 0.2) + (prev_mean * 0.8)
    
    final_strategy = strategy_code
    if state.get("last_update") == today_str:
        # Phase 40: Allow recomputation but prevent flip-flopping
        if strategy_code != str(state.get("last_strategy", "NO_TRADE")):
            final_strategy = str(state.get("last_strategy", "NO_TRADE"))
        else:
            final_strategy = strategy_code
    else:
        last_strat = str(state.get("last_strategy", "NO_TRADE"))
        p_days = int(state.get("persistence_days", 1))
        
        if strategy_code != last_strat:
            if p_days < cfg["PERSISTENCE_MIN_DAYS"] and strategy_code != "GAMMA_FLIP":
                final_strategy = last_strat
                state["persistence_days"] = p_days + 1
            else:
                final_strategy = strategy_code
                state["persistence_days"] = 1
        else:
            state["persistence_days"] = p_days + 1
            
        state["last_strategy"] = final_strategy
        state["last_update"] = today_str
        save_strategy_state(state)
        
    return final_strategy

def get_strategy_details(strategy_code, gamma_metrics, auto_metrics, spot, regime_data, walls, atr, dte=30, iv_data=None):
    """
    Hydrate strategy with Quality Score, Risk Templates, and Convergence.
    """
    if iv_data is None: iv_data = {"label": "NORMAL", "iv_rank": 50.0}
    
    # Issue 5/7: Exact Explicit Hard Blocks guaranteeing integrity flow
    expiry_phase = compute_expiry_phase(dte)
    tv_label = gamma_metrics.get("tv_label", "NORMAL")
    
    intel = gamma_metrics.get("intelligence", {})
    convergence_data = compute_signal_convergence(strategy_code, gamma_metrics, auto_metrics, regime_data, iv_data, atr, spot)
    quality_score, breakdown = calculate_trade_quality(strategy_code, gamma_metrics, auto_metrics, regime_data, iv_data, convergence_data, strike_intel=intel)
    conv_score = convergence_data[0]

    # Risk 3: Hard Block Override for high conviction (even if AVOID)
    allow_reduced = conv_score > 0.85
    
    # Risk 3: Soften Expiry Block (Institutional Policy Phase 42)
    # T+0 (Expiry Day): Allow ONLY if IV < 12
    # T+1: Always allow (subject to other blocks)
    # T+2+: Always allow
    if expiry_phase == "EXPIRY_RISK":
        current_iv = iv_data.get("atm_iv", 20.0)
        if current_iv < 12.0:
            # Allow but squeeze size and force defensive
            master_setup["mode_override"] = "Defensive"
            master_setup["size"] *= 0.5
            master_setup["rationale"].append(f"⚠️ Expiry Day execution permitted due to low IV ({current_iv:.1f}). Forced Defensive / Squeezed Size.")
        else:
            return {
                "code": "NO_TRADE", 
                "name": "Strategy Blocked (Policy)", 
                "reason": f"Hard Policy: Expiry Eve (IV {current_iv:.1f} > 12 cap)", 
                "quality_score": 0, 
                "size": 0.0
            }

    if tv_label == "AVOID" and not allow_reduced:
        return {"code": "NO_TRADE", "name": "Strategy Blocked (Policy)", "reason": f"TV_Ratio={tv_label} (Structural Carry Risk)", "quality_score": 0, "size": 0.0}
    
    # Risk 4: Low Convergence Floor
    if conv_score < 0.4:
        return {"code": "NO_TRADE", "name": "Strategy Blocked (Trust)", "reason": f"Convergence Collapse ({conv_score:.2f}) - Insufficient Signal Alignment", "quality_score": quality_score, "size": 0.0}

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
        raw_exp=raw_exp
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
            
            # v3: Net-Yield Gating
            if net_prem <= 0:
                return {"code": "NO_TRADE", "name": "Negative Carry", "reason": f"Expected Yield ₹{net_prem:.0f} (Post-Costs) blocks execution.", "quality_score": quality_score, "size": 0.0}

            # Target income scaling...
            if theta_per_lot > 0:
                income_scaler = 500.0 / theta_per_lot
                base_size = min(2.0, base_size * income_scaler)
                
            # Store yields in results
            template["estimated_pnl"] = {"gross": gross_prem, "net": net_prem, "costs": costs}
        except:
            pass
            
    size = float(round(base_size, 2))
    aligned, reg_warning = validate_regime_consistency(strategy_code, regime)
    
    # Apply Greek Overrides & Vol Expansion Guard (Phase 28)
    size_mult, greek_warnings = apply_greek_overrides(strategy_code, gamma_metrics)
    
    # NEW: Multi-Expiry Term Structure Integration
    try:
        from nde_options_logic import compute_term_structure
        # Use cached term data for performance (called by UI normally)
        term_data = compute_term_structure("NIFTY")
        size_mult, greek_warnings, is_ts_blocked = apply_term_structure_overrides(
            strategy_code, term_data, size_mult, greek_warnings, conv_score=float(conv_score)
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
        
    assert 0.0 <= size <= 1.2, f"Production Sizing Invariant Failed: {size}"
    if strategy_code == "NO_TRADE":
        assert size == 0.0, f"Critical Invariant Failure: NO_TRADE resulted in non-zero size ({size})"
                    
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
    rationale = []
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
        
    result = {
        **base,
        "code": strategy_code,
        "quality_score": quality_score,
        "quality_breakdown": breakdown,
        "size": size,
        "template": template,
        "warnings": all_warnings,
        "rationale": rationale,
        "alignment": alignment
    }
    
    # Audit log
    audit_entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": strategy_code,
        "quality": quality_score,
        "size": size,
        "spot": spot,
        "regime": regime,
        "rationale": rationale,
        "breakdown": breakdown
    }
    append_strategy_audit(audit_entry)
    
    return result
