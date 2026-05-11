from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
import hashlib
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

def compute_hash(data: Any) -> str:
    """Generates a deterministic SHA-256 hash for any serializable object."""
    from nde_schema import EngineEncoder
    serialized = json.dumps(data, cls=EngineEncoder, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]

class EngineEncoder(json.JSONEncoder):
    """Custom JSON encoder for NDE Dataclasses and NumPy types."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        if isinstance(obj, pd.Series):
            return obj.tolist()
        return super().default(obj)

@dataclass(slots=True, frozen=True)
class FlowMetrics:
    total_gex: float = 0.0
    total_gex_abs: float = 0.0
    total_delta: float = 0.0
    total_vega: float = 0.0
    total_theta: float = 0.0
    total_vanna: float = 0.0
    total_charm: float = 0.0
    gamma_flip_level: float = 0.0
    atm_iv_current: float = 0.0
    pcr_oi: float = 0.0
    pcr_vol: float = 0.0
    vwap_gex: float = 0.0
    concentration_ratio: float = 0.0
    skew_slope: float = 0.0
    call_wall: float = 0.0
    put_wall: float = 0.0
    sec_call_wall: float = 0.0
    sec_put_wall: float = 0.0
    atm_oi_share: float = 0.0
    tv_ratio: float = 0.0
    tv_label: str = "N/A"
    flow_regime_label: str = "Passive"
    gamma_regime: str = "NEUTRAL"
    vanna_bias: str = "Neutral"
    charm_flow: str = "Neutral"
    tv_ema_fast: float = 0.0
    tv_ema_slow: float = 0.0
    gex_tw_norm: float = 0.0
    vex_tw_norm: float = 0.0
    cex_tw_norm: float = 0.0
    intelligence: Dict[str, Any] = field(default_factory=dict)
    raw_exposures: pd.DataFrame = field(default_factory=pd.DataFrame)

@dataclass(slots=True, frozen=True)
class RVMetrics:
    rv_5d: float = 0.0
    rv_intraday: float = 0.0
    rv_acceleration: float = 0.0
    iv_rv_ratio: float = 0.0
    parkinson_vol: float = 0.0
    vol_of_vol: float = 0.0

@dataclass(slots=True, frozen=True)
class LocalGammaMetrics:
    suppression_strength: float = 0.0
    gamma_density: float = 0.0
    local_walls: List[float] = field(default_factory=list)
    support: float = 0.0
    resistance: float = 0.0
    collapse_risk: bool = False

@dataclass(slots=True, frozen=True)
class MarketState:
    state: str = "NEUTRAL"
    substate: str = "NORMAL"
    confidence: float = 0.0
    coherence_score: float = 0.0
    suppression_regime: str = "NORMAL"
    transition_risk: float = 0.0
    volatility_regime: str = "NORMAL"
    bias_tactical: str = "NEUTRAL"
    bias_structural: str = "NEUTRAL"
    why: List[str] = field(default_factory=list)

@dataclass(slots=True, frozen=True)
class ExecutionPlan:
    strategy_code: str = "NO_TRADE"
    action: str = "WAIT"
    template: Dict[str, Any] = field(default_factory=dict)
    legs: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    primary_risk: str = "N/A"
    invalidation_point: float = 0.0
    expected_move: Dict[str, float] = field(default_factory=dict)

@dataclass(slots=True, frozen=True)
class EngineTelemetry:
    flow_ms: float = 0.0
    rv_ms: float = 0.0
    state_ms: float = 0.0
    exec_ms: float = 0.0
    total_ms: float = 0.0

@dataclass(slots=True, frozen=True)
class ReplayMetadata:
    snapshot_hash: str = ""
    state_hash: str = ""
    execution_hash: str = ""
    engine_version: str = "V12.C"

@dataclass(slots=True, frozen=True)
class Narrative:
    dominant_action: str = "WAIT"
    dominant_state: str = "NEUTRAL"
    confidence: float = 0.0
    reasoning: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    next_trade: str = "NONE"
    invalidation: str = "Thesis holds in current regime."
    avoid: List[str] = field(default_factory=list)
    execution_confidence: Dict[str, Any] = field(default_factory=dict)
    reversion: Dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True, frozen=True)
class UISnapshot:
    """Pre-formatted, deterministic visual state for the dumb UI layer."""
    hero_action: str = "WAIT"
    hero_state: str = "NEUTRAL"
    action_color: str = "gray"
    confidence_label: str = "NORMAL"
    confidence_color: str = "gray"
    reasons_html: str = ""
    triggers_text: str = ""
    is_tradeable: bool = False
    quality_score: float = 0.0
    execution_summary: str = ""
    behavior_html: str = ""
    greeks_html: str = ""
    levels_html: str = ""
    threat_html: str = ""
    pcr_display: str = "N/A"
    suppression_display: str = "NORMAL"
    max_pain_display: str = "0"
    expected_move_display: str = "0"
    audit_score: float = 0.0

@dataclass(slots=True, frozen=True)
class EngineContext:
    timestamp: datetime
    index_name: str
    spot: float
    atr: float
    t_days: float
    flow: FlowMetrics
    rv: RVMetrics
    gamma_local: LocalGammaMetrics
    state: MarketState
    execution: ExecutionPlan
    narrative: Narrative = field(default_factory=Narrative)
    telemetry: EngineTelemetry = field(default_factory=EngineTelemetry)
    replay: ReplayMetadata = field(default_factory=ReplayMetadata)
    ui: UISnapshot = field(default_factory=UISnapshot)
    meta: Dict[str, Any] = field(default_factory=dict)
    raw_chain_timestamp: Optional[str] = None
    source: str = "TRUSTED"
