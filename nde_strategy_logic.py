import logging
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd

# Core Schema
from nde_schema import EngineContext, FlowMetrics, RVMetrics, MarketState, ExecutionPlan

# Modular Engines (Carmack Pass)
import nde_flow_engine
import nde_rv_engine
import nde_local_gamma_engine
import nde_state_engine
import nde_strategy_engine
import nde_execution_engine
import nde_scenario_engine
import nde_persistence_engine

logger = logging.getLogger(__name__)

def generate_engine_context(
    raw_chain: pd.DataFrame,
    spot: float,
    nifty_df: pd.DataFrame = None,
    used_expiry: str = "CURRENT",
    regime_history: list = None,
    regime_snap: dict = None,
    vix_df: pd.DataFrame = None,
    meta: dict = None,
    mode: str = "Balanced",
    source: str = "TRUSTED",
    term_data: dict = None,
    strike_interval: float = 50.0,
    index_name: str = "NIFTY"
) -> EngineContext:
    """
    Deterministic Orchestration Pipeline (Carmack Pass).
    Transforms raw market data into a structured EngineContext.
    """
    # 0. Cache Lookup
    snapshot_id = (meta or {}).get("timestamp", "LIVE")
    import nde_cache
    cached_flow = nde_cache.get_cached_result(snapshot_id, "flow")
    
    # 1. Temporal & Flow Analysis
    t0 = datetime.now()
    
    # P0: Time-to-Expiry (t_days) Injection
    # Deterministic calculation required for Institutional Greek parity
    t_days = 7.0
    try:
        if used_expiry and used_expiry != "CURRENT":
            exp_dt = None
            for fmt in ["%d-%b-%Y", "%Y-%m-%d"]:
                try:
                    exp_dt = datetime.strptime(used_expiry, fmt)
                    break
                except ValueError: continue
            
            if exp_dt:
                diff = (exp_dt - datetime.now()).days + 1
                t_days = max(0.5, float(diff))
    except Exception as e:
        logger.warning(f"T-Days calculation fallback: {e}")

    # 1.1 Expiry Phase (Institutional temporal logic)
    import nde_automation_logic
    expiry_phase = nde_automation_logic.compute_expiry_phase(t_days)
    if meta is None: meta = {}
    meta["expiry_phase"] = expiry_phase

    if cached_flow:
        df_exp, flow = cached_flow
    else:
        raw_chain["t_days"] = t_days
        df_exp = nde_flow_engine.compute_all_greeks(raw_chain, spot)
        flow = nde_flow_engine.calculate_flow_metrics(df_exp, spot)
        nde_cache.set_cached_result(snapshot_id, "flow", (df_exp, flow))
    t1 = datetime.now()
    
    # 2. Realized Intelligence (Full Precision)
    atr = (meta or {}).get("atr", 250.0)
    rv = nde_rv_engine.compute_rv_metrics(nifty_df, spot, atr, atm_iv=flow.atm_iv_current)
    t2 = datetime.now()
    
    # 3. Local Structure (Suppression & Density)
    gamma_local = nde_local_gamma_engine.compute_local_gamma_metrics(df_exp, spot, atr)
    
    # 4. Canonical State Machine
    drift = (regime_snap or {}).get("drift_score", 0.0)
    stability = (regime_snap or {}).get("stability_20d", 50.0)
    
    state = nde_state_engine.classify_market_state(
        flow=flow, 
        rv=rv, 
        gamma_local=gamma_local, 
        drift=drift, 
        stability_20d=stability
    )
    if meta is None: meta = {}
    meta["drift"] = drift
    meta["drift_accel"] = (regime_snap or {}).get("drift_accel", 0.0)
    meta["stability"] = stability
    
    t3 = datetime.now()
    
    # 5. Strategy Selection
    exec_plan = nde_strategy_engine.compile_execution_plan(state, flow, spot, t_days=t_days, mode=mode)
    
    # 6. Execution Compilation (Strike Selection)
    exec_plan = nde_execution_engine.hydrate_execution_plan(exec_plan, spot, flow, df_exp, atr=atr, strike_interval=strike_interval)
    t4 = datetime.now()
    
    # 7. Telemetry & Hashing
    from nde_schema import EngineTelemetry, ReplayMetadata, compute_hash
    telemetry = EngineTelemetry(
        flow_ms=(t1-t0).total_seconds() * 1000,
        rv_ms=(t2-t1).total_seconds() * 1000,
        state_ms=(t3-t2).total_seconds() * 1000,
        exec_ms=(t4-t3).total_seconds() * 1000,
        total_ms=(t4-t0).total_seconds() * 1000
    )
    
    replay = ReplayMetadata(
        state_hash=compute_hash(state),
        execution_hash=compute_hash(exec_plan)
    )

    # 8. Final Context Assembly (Dataclass Core)
    ctx_obj = EngineContext(
        timestamp=datetime.now(),
        index_name=index_name,
        spot=spot,
        atr=atr,
        t_days=float(t_days),
        flow=flow,
        rv=rv,
        gamma_local=gamma_local,
        state=state,
        execution=exec_plan,
        telemetry=telemetry,
        replay=replay,
        meta=meta or {},
        raw_chain_timestamp=(meta or {}).get("timestamp"),
        source=source
    )
    
    # 8. Persistence (Atomic JSONL Stream)
    nde_persistence_engine.persist_context(ctx_obj)
    
    # 8.1 Auto-Snapshot (Daily Idempotent Save)
    # Ensures "What Changed" always has historical data without requiring manual save.
    try:
        import nde_automation_logic as _auto
        _drift = (regime_snap or {}).get("drift_score", 0.0)
        _persistence = (meta or {}).get("persistence", 0)
        _stability = (regime_snap or {}).get("stability_20d", 50.0)
        _probs = _auto.compute_probabilities(state.state, _drift, _persistence)
        _escalation = _auto.compute_transition_risk(_drift, _stability)
        _auto.write_daily_nde_snapshot(
            curr_regime=state.state, persistence=_persistence,
            stability_20d=_stability,
            stability_5d=(regime_snap or {}).get("stability_5d", 50.0),
            drift=_drift,
            drift_accel=(regime_snap or {}).get("drift_acceleration", 0.0),
            fragility=(regime_snap or {}).get("fragility", False),
            probs=_probs, escalation=_escalation,
            used_expiry=used_expiry, gamma_regime=flow.gamma_regime,
            flip=flow.gamma_flip_level, vanna=flow.vanna_bias,
            charm=flow.charm_flow, flow_regime=flow.flow_regime_label,
            total_gex=flow.total_gex, t_bias=state.bias_tactical,
            s_bias=state.bias_structural, spot=spot, atr=atr,
            config_hash="V12.C", source_mode=source,
            data_quality_score=state.confidence, tv_label=flow.tv_label,
            convergence_score=state.coherence_score,
            strategy_code=exec_plan.strategy_code,
            inst_iq=flow.intelligence, atm_iv=flow.atm_iv_current,
            index_name=index_name
        )
    except Exception as _snap_err:
        logger.warning(f"Auto-snapshot failed (non-critical): {_snap_err}")
    
    # 9. UI Adapter Layer (Backward Compatibility Bridge)
    # This transforms the typed context into the dictionary format expected by the UI.
    import nde_ui_adapter
    return nde_ui_adapter.adapt_context_for_ui(ctx_obj)

def compute_vol_trend(vix_df: pd.DataFrame, regime_history: list) -> Dict[str, Any]:
    """
    Computes the institutional volatility trend.
    v3: Uses VIX EMA cross + Regime persistence.
    """
    if vix_df.empty or len(vix_df) < 20:
        return {"trend": "Neutral", "implication": "Insufficient data"}
        
    vix_close = vix_df["Close"]
    ema5 = vix_close.ewm(span=5).mean().iloc[-1]
    ema20 = vix_close.ewm(span=20).mean().iloc[-1]
    
    if ema5 < ema20:
        return {"trend": "Falling", "implication": "Compressing Volatility (Mean Reversion Favored)"}
    elif ema5 > ema20 * 1.1:
        return {"trend": "Spiking", "implication": "Explosive Volatility (Tail Risk Escalation)"}
    else:
        return {"trend": "Rising", "implication": "Expanding Volatility (Trend Following Favored)"}

def get_directional_conviction(regime: str, drift: float, gex: float) -> Dict[str, Any]:
    """
    Standardized Directional Conviction Logic.
    """
    bias = "Neutral"
    conviction = "Low"
    conflict = ""
    
    if "RISK_ON" in regime or "SELECTIVE" in regime:
        if gex > 0:
            bias = "Bullish"
            conviction = "High" if drift > 0 else "Moderate"
        else:
            bias = "Bullish"
            conviction = "Low"
            conflict = "Macro Bullish vs Negative GEX"
    elif "CRISIS" in regime or "DEFENSIVE" in regime:
        if gex < 0:
            bias = "Bearish"
            conviction = "High"
        else:
            bias = "Bearish"
            conviction = "Moderate"
            conflict = "Macro Bearish vs Positive GEX"
            
    return {"bias": bias, "conviction": conviction, "conflict_reason": conflict}
