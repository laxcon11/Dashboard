from datetime import datetime
from pathlib import Path
import json
import pandas as pd
try:
    import nde_scripts_bridge
except ImportError:
    nde_scripts_bridge = None
import math
import logging
from nde_expiry_helper import get_dte_from_string

logger = logging.getLogger(__name__)


# ── NDE GOVERNANCE AUTHORITY (Institutional v1.5) ──────────────────
class NDEGovernance:
    """
    Central authority for NDE Data Trust, Provenance, and Benchmarking Policy.
    Unifies logic across Automation, Strategy, and UI layers.
    """
    TRUSTED_SOURCES = ["SENSIBULL_VENDOR_GREEKS"]
    FRESHNESS_LIMIT_S = 86400  # 24h benchmark limit
    
    @staticmethod
    def get_trust_level(source_mode: str, meta_age_s: float) -> str:
        """Determines the categorical trust level for the system."""
        if source_mode in NDEGovernance.TRUSTED_SOURCES:
            if meta_age_s < 3600 * 4: return "HIGH"
            if meta_age_s < NDEGovernance.FRESHNESS_LIMIT_S: return "STALE_TRUSTED"
        return "DEGRADED"

    @staticmethod
    def resolve_benchmark_indices(df: pd.DataFrame):
        """
        Policy: Returns (latest_index, previous_dated_index) for 'What Changed' logic.
        Ensures comparison against Yesterday's Close if today has multiple snapshots.
        """
        if df.empty or len(df) < 2:
            return None, None
            
        # Target: Comparison against a different DATE
        latest = df.iloc[-1]
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Walk backwards to find the first snapshot from a PREVIOUS date
        for i in range(len(df)-2, -1, -1):
            if df.iloc[i]["date"].strftime("%Y-%m-%d") != today_str:
                return -1, i
                
        # Fallback to absolute previous if no dated difference found
        return -1, -2

def compute_expiry_phase(dte: float) -> str:
    """Classify the current DTE into a structural expiry phase.
    
    Canonical definition — all callsites must use this function.
    Accepts both integer and fractional DTE values.
    """
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
    flow_regime, total_gex, t_bias, s_bias, spot, atr, config_hash,
    source_mode="UNKNOWN", data_quality_score=1.0, tv_label="UNKNOWN",
    convergence_score=0.0, strategy_code="NO_TRADE",
    inst_iq=None, # Enriched IQ metrics (Phase 46)
    atm_iv=None,  # Phase 47: Enriched Vol Persistence
    requires_warning=False # System Warning Banner Trigger
):
    """Save the finalized daily NDE snapshot with expiry-aware lifecycle."""
    AUTOMATION_OUTPUT_DIR = Path(__file__).parent / "data" / "automation"
    AUTOMATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    iq = inst_iq or {}
    
    snapshot = {
        "snapshot_version": "2.1",
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
            "total_gex": total_gex,
            "tv_label": tv_label,
            # Phase 46 Enriched Metrics
            "max_pain": iq.get("max_pain"),
            "pcr_oi": iq.get("pcr_oi"),
            "atm_oi_share": iq.get("atm_oi_share"),
            "expected_move": iq.get("expected_move"),
            "poc": iq.get("poc"),
            "atm_iv": atm_iv
        },
        "strategy": {
            "code": strategy_code,
            "convergence_score": convergence_score
        },
        "data_provenance": {
            "source_mode": source_mode,
            "data_quality_score": data_quality_score,
            "requires_warning": requires_warning
        },
        "spot": spot,
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
    
    # Garbage Collection: Expiry-Aware Lifecycle (Phase 46)
    # We keep all snapshots where the expiry has NOT passed yet.
    try:
        from nde_scripts_bridge import parse_expiry_date
        all_snaps = list(AUTOMATION_OUTPUT_DIR.glob("nde_v12_*.json"))
        today_date = datetime.now()
        
        for snap_file in all_snaps:
            try:
                with open(snap_file, 'r') as f:
                    data = json.load(f)
                    snap_exp = data.get("options_flow", {}).get("expiry")
                    if snap_exp:
                        exp_dt = parse_expiry_date(snap_exp)
                        # Keep for 2 days post-expiry for "Post-Mortem" analysis, then purge
                        if exp_dt and (today_date - exp_dt).days > 2:
                            snap_file.unlink()
                            logger.info(f"Automation GC (Expiry-Aware): Purged legacy snapshot -> {snap_file.name}")
            except Exception as inner_e:
                logger.warning(f"Failed to check snapshot {snap_file.name} for GC: {inner_e}")
    except Exception as e:
        logger.warning(f"Automation GC Failed: {e}")
        
    return fname

def get_historical_snapshot_df(limit=30, daily_only=True):
    """
    Aggregates historical NDE snapshots into a single DataFrame for trend analysis.
    If daily_only=True, returns only the latest snapshot per unique date.
    Returns: DataFrame indexed by date.
    """
    path = Path(__file__).parent / "data" / "automation"
    files = sorted(list(path.glob("nde_v12_*.json")), reverse=True)
    
    rows = []
    seen_dates = set()
    
    for f in files:
        try:
            with open(f, 'r') as j:
                data = json.load(j)
                date_val = data.get("date")
                
                if daily_only and date_val in seen_dates:
                    continue
                
                row = {
                    "date": date_val,
                    "timestamp": data.get("timestamp"),
                    "regime": data.get("regime"),
                    "total_gex": data.get("options_flow", {}).get("total_gex", 0),
                    "gamma_flip": data.get("options_flow", {}).get("gamma_flip", 0),
                    "max_pain": data.get("options_flow", {}).get("max_pain", 0),
                    "pcr_oi": data.get("options_flow", {}).get("pcr_oi", 0),
                    "atm_iv": data.get("options_flow", {}).get("atm_iv", 0),
                    "atm_oi_share": data.get("options_flow", {}).get("atm_oi_share", 0),
                    "drift_score": data.get("drift_score", 0),
                    "quality_score": data.get("strategy", {}).get("convergence_score", 0) * 10.0
                }
                rows.append(row)
                seen_dates.add(date_val)
                
                if len(rows) >= limit:
                    break
        except Exception:
            continue
            
    if not rows:
        return pd.DataFrame()
        
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date')

# ── INGESTION HUB SERVICE LAYER (Phase 2 Refactor) ──────────────────

def scan_for_raw_files() -> list:
    """Returns a list of raw Sensibull files awaiting conversion."""
    return nde_scripts_bridge.list_raw_files() if nde_scripts_bridge else []

def auto_convert_raw_files() -> int:
    """Automatically converts raw files. Returns count of converted files."""
    raw = scan_for_raw_files()
    if not raw or not nde_scripts_bridge:
        return 0
    return nde_scripts_bridge.run_ingestion_cycle()

def get_ingestion_hub_context() -> dict:
    """
    Returns data for the UI Ingestion Hub: status, counts, and freshness.
    Decouples UI from path logic and datetime math.
    """
    project_root = Path(__file__).parent
    chain_dir = project_root / "data" / "option_chain"
    
    sensi_files = list(chain_dir.glob("option-chain-ED-sensi-NIFTY-*.csv"))
    count = len(sensi_files)
    
    active = False
    age_mins = 0
    latest_ts = "N/A"
    
    if sensi_files:
        latest = max(sensi_files, key=lambda f: f.stat().st_mtime)
        dt_latest = datetime.fromtimestamp(latest.stat().st_mtime)
        age_mins = (datetime.now() - dt_latest).total_seconds() / 60
        latest_ts = dt_latest.strftime("%Y-%m-%d %H:%M")
        
        # 8-hour freshness window
        if age_mins < 480:
            active = True
            
    return {
        "sensi_count": count,
        "is_active": active,
        "age_mins": int(age_mins),
        "latest_file_ts": latest_ts,
        "awaiting_conversion": len(scan_for_raw_files()) > 0
    }

def refresh_macro_regime():
    """Headless Macro Refresh Trigger (v1.0). Updates Global Macro state."""
    try:
        from institutional_engine import generate_institutional_regime
        from regime_state import save_regime_snapshot, append_regime_history
        
        # 1. Execute Engine (Pull Global/Macro/Liquidity/Risk)
        res = generate_institutional_regime()
        
        # 2. Derive Bias and Metadata (Mirroring 3_Macro_Risk.py logic)
        label = res["regime"]
        if "Risk On" in label: 
            bias = "Aggressive Long / Risk Seeking"
        elif "Selective" in label or "Neutral" in label: 
            bias = "Selective Longs / Reduced Position Size"
        elif "Crisis" in label: 
            bias = "Cash / Hedges Only"
        else: 
            bias = "Defensive / Tactical Shorts"
        
        # 3. Persistence Sync
        payload = {
            "regime_label": label,
            "current_regime": label,
            "confidence": round(float(res.get("confidence", 0.5)), 4),
            "final_score": round(float(res["final_score"]), 4),
            "pillar_scores": res["pillar_scores"],
            "probabilities": res.get("probabilities", {}),
            "bias": bias,
            "source": "institutional_v1_auto",
        }
        
        save_regime_snapshot(payload)
        append_regime_history(payload)
        logger.info(f"✅ Macro Regime Refresh Complete: {label} (Score: {payload['final_score']:+.2f})")
        return payload
    except Exception as e:
        logger.error(f"❌ Macro Regime Refresh Failed: {e}")
        return None

def generate_auto_snapshot(force_file=None):
    """
    Headless Analytical Runner (v1.5).
    Loads fresh data, calculates engine context, and saves a summary snapshot.
    Decoupled from Streamlit UI.
    """
    try:
        import nde_options_logic
        import nde_strategy_logic
        from regime_state import load_regime_history, load_regime_snapshot
        
        # 0. Canonical Maintenance (Phase 2 Hardening) review accuracy check review accuracy check review accuracy check
        purged = nde_options_logic.cleanup_expired_chains()
        if purged > 0:
            logger.info(f"🧹 Headless Ops: Purged {purged} expired option chains from disk.")
        
        # 1. Load Data
        if force_file:
            force_path = Path(force_file)
            df = pd.read_csv(force_path)
            df.columns = [c.strip().lower() for c in df.columns]
            filename = force_path.name
            mtime = force_path.stat().st_mtime
            expiry = "UNKNOWN"
        else:
            df, filename, mtime, expiry = nde_options_logic.load_latest_option_chain_csv()
            
        if df.empty:
            logger.warning("Auto-Snapshot: No option chain data found. Skipping.")
            return None
            
        # 2. Get Spot & ATR (Standardized Provenance Fallback)
        OPTION_CHAIN_DIR = nde_options_logic.OPTION_CHAIN_DIR
        
        # Metadata Resolution (v1.5 Institutional)
        # sidecars are named {csv_stem}_meta.json
        meta_filename = Path(filename).stem + "_meta.json"
        meta_file = OPTION_CHAIN_DIR / meta_filename
        
        spot = None
        source_mode = "DEGRADED (Strike Mean)"
        requires_warning = False
        
        # Dashboard Data Trust Logic: Metadata is required for High-Trust resolution
        TRUSTED_SOURCES = ["SENSIBULL_VENDOR_GREEKS"]
        FRESHNESS_THRESHOLD = 86400 # 24 hours preference for stale HIGH trust over live LOW trust
        
        is_high_trust = False 
        is_stale_trust = False
        
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                # Fallback order: spot_at_fetch -> spot -> None
                spot = meta.get("spot_at_fetch") or meta.get("spot")
                
                # Trust Resolution
                m_source = meta.get("source_mode", "UNKNOWN")
                m_time = meta.get("conversion_time", 0)
                m_age = datetime.now().timestamp() - m_time
                
                if m_source in TRUSTED_SOURCES:
                    is_high_trust = True
                    # V5: Distinguish between 'Stale' (4h) and 'Threshold' (24h)
                    if m_age > 14400: # 4 hours
                        is_stale_trust = True
                    
                    if m_age < FRESHNESS_THRESHOLD:
                        if spot:
                            source_mode = "METADATA (Institutional)" + (" [STALE]" if is_stale_trust else "")
                    else:
                        # Beyond 24h, the HIGH trust is ignored as too risky for Greeks sync
                        is_high_trust = False
                        spot = None
                
            except Exception as meta_e:
                logger.warning(f"Failed to parse metadata sidecar: {meta_e}")

        # Secondary: Try Live Spot (batch_download) IF AND ONLY IF we have NO spot and trust is HIGH
        # We prefer a stale HIGH-TRUST spot (within 24h) over a LIVE spot if the live spot is not verified.
        # This prevents 'Analytical Drift' where live price mismatches sensitive Sensibull-derived Greeks.
        if not spot and is_high_trust:
            try:
                from data_fetch import batch_download
                m_data = batch_download(["^NSEI"], period="1d")
                if not m_data.get("^NSEI").empty:
                    spot = m_data.get("^NSEI")["Close"].iloc[-1]
                    source_mode = "LIVE (Trusted)"
            except Exception as live_e:
                logger.warning(f"Live spot fallback failed: {live_e}")

        # Final Fallback preference: Stale (within 24h) vs Degraded
        # If we reached here and still have no spot, but have HIGH trust metadata within 24h, we use it.
        # (This block is technically redundant given the logic above, but enforces the 24h policy)
        
        # Fail-safe: Degraded mode (No metadata AND no/failed live fallback)
        if not spot:
            spot = df["strike"].mean()
            source_mode = "DEGRADED (Strike Mean)"
            requires_warning = True
            logger.warning(f"⚠️ NDE Automation: Using DEGRADED spot ({spot:.0f}) for {filename}")
        
        # 3. Compute Metrics
        metrics = nde_options_logic.compute_option_flow_exposures(spot, df)
        
        # 4. Get Regime Context
        regime_history = load_regime_history()
        regime_snap = load_regime_snapshot()
        if regime_snap is None: regime_snap = {}
        
        # 5. Compute Automation Metrics (V5: Dynamic ATR)
        from nde_options_logic import calculate_atr_sma
        from data_fetch import batch_download
        # Get 14-day ATR for Nifty via live fetch
        try:
            nsei_data = batch_download(["^NSEI"], period="3mo")
            nsei_df = nsei_data.get("^NSEI")
            calc_atr = calculate_atr_sma(nsei_df) if (nsei_df is not None and not nsei_df.empty) else 250.0
        except Exception as atr_e:
            logger.warning(f"ATR calculation failed: {atr_e}. Using fallback 250.")
            calc_atr = 250.0
            
        if not calc_atr or calc_atr < 100: calc_atr = 250.0 # Safety floor
        
        try:
            drift, _, drift_accel = compute_drift(regime_history, spot, atr=calc_atr)
        except Exception as e_drift:
            logger.error(f"❌ Automation Error in compute_drift: {e_drift}")
            raise
            
        try:
            stab_20, stab_5, frag = compute_stability(regime_snap.get("final_score", 0.0), regime_history, regime_snap.get("persistence", 0))
        except Exception as e_stab:
            logger.error(f"❌ Automation Error in compute_stability: {e_stab}")
            raise
            
        curr_reg = regime_snap.get("current_regime", "Selective")
        pers = regime_snap.get("persistence", 0)
        
        try:
            probs = compute_probabilities(curr_reg, drift, pers)
        except Exception as e_prob:
            logger.error(f"❌ Automation Error in compute_probabilities: {e_prob}")
            raise
            
        try:
            escalation = compute_transition_risk(drift, stab_20)
        except Exception as e_risk:
            logger.error(f"❌ Automation Error in compute_transition_risk: {e_risk}")
            raise
        
        # 6. Strategy Engine (Phase 46 Hardening: Call select_master_strategy to get REAL code)
        walls = nde_options_logic.calculate_option_walls(df)
        
        # Identify the correct core logic first
        dte_val = get_dte_from_string(expiry) if isinstance(expiry, str) else expiry.get("dte", 7)
        
        real_code = nde_strategy_logic.select_master_strategy(
            gamma_metrics=metrics, 
            auto_metrics={"drift": drift, "stability": stab_20},
            spot=spot, regime_data=regime_snap, dte=dte_val,
            atr=calc_atr
        )
        
        # Hydrate for snapshot
        master_setup = nde_strategy_logic.get_strategy_details(
            strategy_code=real_code, 
            gamma_metrics=metrics, 
            auto_metrics={"drift": drift, "stability": stab_20},
            spot=spot, regime_data=regime_snap, walls=walls, atr=calc_atr, 
            dte=dte_val
        )
        
        # 7. Write Snapshot
        from NSE_Config import CONFIG_VERSION
        fname = write_daily_nde_snapshot(
            curr_regime=curr_reg,
            persistence=pers,
            stability_20d=stab_20,
            stability_5d=stab_5,
            drift=drift,
            drift_accel=drift_accel,
            fragility=frag,
            probs=probs,
            escalation=escalation,
            used_expiry=expiry,
            gamma_regime=metrics.get("gamma_regime", "UNKNOWN"),
            flip=metrics.get("gamma_flip_level", 0),
            vanna=metrics.get("vanna_bias", "UNKNOWN"),
            charm=metrics.get("charm_flow", "UNKNOWN"),
            flow_regime=metrics.get("flow_regime_label", "UNKNOWN"),
            total_gex=metrics.get("total_gex", 0),
            t_bias="NEUTRAL", s_bias="NEUTRAL",
            spot=spot, atr=calc_atr, config_hash=CONFIG_VERSION,
            source_mode=source_mode,
            data_quality_score=1.0,
            tv_label=metrics.get("tv_label", "UNKNOWN"),
            convergence_score=master_setup.get("quality_score", 0),
            strategy_code=real_code,
            inst_iq=metrics.get("institutional_iq"),
            atm_iv=metrics.get("atm_iv_current"),
            requires_warning=requires_warning
        )
        
        logger.info(f"✅ Automated NDE Snapshot generated: {fname.name}")
        return fname
        
    except Exception as e:
        import traceback
        error_msg = f"❌ Failed to generate automated NDE snapshot: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return None

