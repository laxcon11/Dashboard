from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from regime_model import load_regime_settings, save_regime_settings
from trading_calendar import add_nse_business_days

from .schema import canonical_date, canonical_regime, make_input_signature, now_iso, top_regime, validate_probs, REGIMES
from .store import (
    CAL_DIR,
    PROPOSAL_DIR,
    ensure_dirs,
    latest_calibration_proposal,
    load_outcomes,
    load_predictions,
    load_versions,
    read_json,
    save_model_versions,
    save_outcomes,
    save_predictions,
    write_json,
)

SNAPSHOT_DIR = Path("data/snapshots")
PREDICTION_DIR = Path("data/predictions")
PI_CFG_FILE = Path("notes/prediction_integrity_config.json")

_HIST_REGIME_CACHE: dict[str, dict[str, float]] | None = None

DEFAULT_PI_CONFIG = {
    "horizons_days": [1, 5, 20],
    "score_band_half_width": {
        "1": 1.2,
        "5": 2.0,
        "20": 3.2,
    },
    "confidence_floor": 0.35,
    "monthly_guardrails": {
        "max_neutral_band_shift": 0.05,
        "max_impulse_shift": 0.05,
    },
}




def _load_pi_config() -> dict[str, Any]:
    if not PI_CFG_FILE.exists():
        PI_CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        PI_CFG_FILE.write_text(json.dumps(DEFAULT_PI_CONFIG, indent=2))
        return dict(DEFAULT_PI_CONFIG)
    try:
        loaded = json.loads(PI_CFG_FILE.read_text())
        out = dict(DEFAULT_PI_CONFIG)
        out.update(loaded)
        return out
    except Exception:
        return dict(DEFAULT_PI_CONFIG)


def _latest_snapshot() -> tuple[Path | None, dict[str, Any] | None]:
    files = sorted(SNAPSHOT_DIR.glob("eod_*.json"))
    if not files:
        return None, None
    p = files[-1]
    try:
        return p, json.loads(p.read_text())
    except Exception:
        return p, None


def _snapshot_for_date(dt: str) -> dict[str, Any] | None:
    stamp = str(dt).replace("-", "")
    p = SNAPSHOT_DIR / f"eod_{stamp}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _macro_weight(age: float, vol_factor: float = 1.0, half_life: float = 14.0) -> float:
    """Core math for Two-Phase Decay with Volatility Scaling (V4 Experiment).
    Macro dominates during stress (high vol), tactical dominates during calm.
    
    Supports segment-aware decay via half_life parameter:
      - SLOW (monthly data: GST, PMI): half_life=30
      - MEDIUM (weekly data: Fed BS, M2): half_life=14  (default)
      - FAST (daily data: VIX, DXY, Credit): half_life=5
    """
    # Dynamic base weight: 0.5 Vol -> 0.30, 1.0 Vol -> 0.35, 2.0 Vol -> 0.45
    base_weight = 0.25 + (0.10 * vol_factor)
    base_weight = max(0.20, min(0.50, base_weight)) # Safety bounds
    
    grace_period = min(7, half_life * 0.5)  # Scale grace period with half-life
    if age <= grace_period:
        return base_weight
    return base_weight * math.exp(-(age - grace_period) / half_life)


# Decay tier lookup: maps factor categories to half-life values
DECAY_TIERS = {
    "SLOW": 30.0,    # Monthly/Quarterly data (GST, PMI, GDP, Auto Sales, Exports)
    "MEDIUM": 14.0,  # Weekly data (Fed Balance Sheet, M2, RBI Liquidity)
    "FAST": 5.0,     # Daily data (VIX, DXY, Credit Spreads, Yields)
}


def _calculate_macro_weight(macro_updated_at: str | None, vol_factor: float = 1.0, decay_tier: str = "MEDIUM") -> float:
    if not macro_updated_at:
        return 0.0
    try:
        updated = datetime.fromisoformat(macro_updated_at)
        age = (datetime.now() - updated).days
        half_life = DECAY_TIERS.get(decay_tier, 14.0)
        return _macro_weight(age, vol_factor=vol_factor, half_life=half_life)
    except Exception:
        return 0.0


def _percentile_rank(history: list[float], current: float) -> float:
    """Calculate the percentile rank of CURRENT vs HISTORY.
    Excludes CURRENT from the calculation to prevent look-ahead bias.
    """
    if not history:
        return 0.5
    smaller = sum(1 for s in history if s < current)
    return float(smaller) / len(history)


def _get_macro_percentile(current_score: float) -> float:
    scores = []
    # Read all available snapshots for historical context
    for p in sorted(SNAPSHOT_DIR.glob("eod_*.json")):
        try:
            with open(p, "r") as f:
                data = json.load(f)
                m_score = data.get("macro_context", {}).get("score")
                if m_score is not None:
                    # Filter out any exact match for today to be safe, 
                    # though SNAPSHOT_DIR usually excludes unwritten current day.
                    scores.append(float(m_score))
        except Exception:
            continue
    
    # Strictly non-lookahead: If snapshots already contain current_score, remove one instance
    if current_score in scores:
        scores.remove(current_score)

    if len(scores) < 3:
        # Fallback to linear scaling if data is sparse
        return max(0.0, min(1.0, (current_score + 10.0) / 20.0))
        
    return _percentile_rank(scores, current_score)


def _get_historical_tactical_signals(depth: int = 5) -> list[float]:
    """Retrieves tactical signals from previous snapshots for smoothing.
    Returns signals in chronological order [oldest -> newest].
    """
    signals = []
    # sorted(reverse=True) to get newest first, then limit by depth
    paths = sorted(SNAPSHOT_DIR.glob("eod_*.json"), reverse=True)
    for p in paths:
        try:
            with open(p, "r") as f:
                data = json.load(f)
                r_score = float(data.get("regime_score", 0.0)) / 2.0
                breadth = data.get("breadth", {})
                if not isinstance(breadth, dict):
                    continue
                b_ratio = float(breadth.get("ratio", 0.0))
                # Raw tactical blend (Layer 2)
                tactical = (0.65 * r_score) + (0.35 * b_ratio)
                signals.append(tactical)
                if len(signals) >= depth:
                    break
        except Exception:
            continue
    # Use list() instead of slicing [::-1] to appease certain linters
    signals.reverse()
    return signals


def _score_from_snapshot(snap: dict[str, Any]) -> float:
    """Derive a normalised [-10, +10] prediction score using V5 Filters.
    
    Layer 1 (Macro): Structural Regime (Sets Prior)
    Layer 2 (Tactical): Smoothed Breadth & Momentum (Sets Likelihood)
    """
    # 1. Macro Context (Structural) + Volatility scaling
    indicators = snap.get("indicators", {})
    atr = float(indicators.get("ATR_14", 0.0))
    price = float(snap.get("price", indicators.get("Close", 1.0)))
    
    vol_scale = (atr / price) * 100.0 if price > 0 else 1.0
    vol_factor = max(0.5, min(2.0, vol_scale / 1.5))
    
    m_ctx = snap.get("macro_context", {})
    m_score = float(m_ctx.get("score", 0.0))
    m_updated_at = m_ctx.get("updated_at")
    
    m_rank = _get_macro_percentile(m_score)
    m_prior = (m_rank - 0.5) * 2.0
    
    e_weight = _calculate_macro_weight(m_updated_at, vol_factor=vol_factor)
    
    # 2. Tactical Signals (Participation & Momentum)
    regime_score = float(snap.get("regime_score", 0.0)) / 2.0
    breadth = snap.get("breadth", {}) if isinstance(snap.get("breadth"), dict) else {}
    b_ratio = float(breadth.get("ratio", 0.0))
    
    # Current Raw Tactical Likelihood
    current_t = (0.65 * regime_score) + (0.35 * b_ratio)
    current_t = max(-1.0, min(1.0, current_t))
    
    # EMA(3) Smoothing (V5 -> V6: high-alpha for responsive signal)
    history = _get_historical_tactical_signals(depth=3)
    if not history:
        t_likelihood = current_t
    else:
        # V6: alpha=0.85 — heavily weight current observation to fix lag
        # (was 0.5, causing 2-3 day delay on regime shifts)
        alpha = 0.85
        ema = float(history[0])
        # Use explicit enumeration to avoid slicing which can trigger certain linters
        for i, val in enumerate(history):
            if i == 0:
                continue
            ema = (alpha * float(val)) + ((1 - alpha) * ema)
        # Apply current observation
        t_likelihood = (alpha * current_t) + ((1 - alpha) * ema)
    
    # 3. Hierarchical Blend
    final_norm = (m_prior * e_weight) + (t_likelihood * (1 - e_weight))
    return round(float(final_norm) * 10.0, 2)


def _get_confirmation_status(candidate_regime: str) -> int:
    """Determine how many consecutive days the candidate_regime has been the leading signal.
    Looks at raw_regime stored in historical predictions.
    """
    count = 1  # Start with today's candidate
    # sorted(reverse=True) to get newest first
    paths = sorted(PREDICTION_DIR.glob("pred_*.json"), reverse=True)
    for p in paths:
        try:
            with open(p, "r") as f:
                data = json.load(f)
                # Store 'raw_regime' to enable this lookup
                prev_raw = data.get("raw_regime")
                if prev_raw == candidate_regime:
                    count += 1
                else:
                    break  # Reset on any mismatch
        except Exception:
            continue
    return count


def _get_latest_issued_regime() -> str:
    """Fetch the most recently issued regime label."""
    paths = sorted(PREDICTION_DIR.glob("pred_*.json"), reverse=True)
    for p in paths:
        try:
            with open(p, "r") as f:
                data = json.load(f)
                res = data.get("regime")
                if res:
                    return canonical_regime(str(res))
        except Exception:
            continue
    return "SELECTIVE"


# Empirical Stationary Distribution (Baseline Frequency)
STATIONARY_DISTRIBUTION = {
    "RISK_ON": 0.10,
    "SELECTIVE": 0.45,
    "DEFENSIVE": 0.30,
    "CRISIS": 0.15
}

def _apply_horizon_decay(signal_probs: dict[str, float], horizon: int) -> dict[str, float]:
    """Blends signal-driven probabilities with a stationary distribution as horizon increases.
    V6: tau=100 — retain live signal across all horizons.
    1d  -> 1% stationary
    5d  -> 5% stationary
    20d -> 18% stationary
    """
    tau = 100.0
    decay = 1.0 - math.exp(-float(horizon) / tau)
    
    decayed = {}
    for k in signal_probs:
        # P_h = (1-d)*P_s + d*P_stationary
        decayed[k] = ((1.0 - decay) * signal_probs[k]) + (decay * STATIONARY_DISTRIBUTION.get(k, 0.25))
    
    # Final Normalization to ensure sum == 1
    total = sum(decayed.values())
    return {k: v / total for k, v in decayed.items()}

def _adjust_probs_macro(probs: dict[str, float], macro_rank: float) -> dict[str, float]:
    """Shift probabilities toward/away from RISK_ON based on macro rank using logit space.
    Ensures sum(p) == 1 and 0 <= p <= 1.
    """
    eps = 1e-6
    logits = {k: math.log(v + eps) for k, v in probs.items()}
    
    # Shifts mass toward/away from RISK_ON based on macro percentile rank
    macro_centered = (macro_rank - 0.5) * 2.0 # [-1, 1]
    alpha = 1.2 # Sensitivity factor
    logits["RISK_ON"] += alpha * macro_centered

    # Softmax back to probabilities
    max_l = max(logits.values())
    exp_l = {k: math.exp(v - max_l) for k, v in logits.items()}
    sum_exp = sum(exp_l.values())
    return {k: (v / sum_exp) for k, v in exp_l.items()}


def _apply_trust_damping_logit(probs: dict[str, float], trust_score: float) -> dict[str, float]:
    """Damp the winning class in logit space based on trust score."""
    if trust_score >= 95:
        return probs
        
    eps = 1e-6
    logits = {k: math.log(v + eps) for k, v in probs.items()}
    
    winner = max(probs, key=probs.get)
    # Scale damping: 100 -> 0 reduction, 0 -> max reduction
    damp_logit = -0.6 * (95 - trust_score) / 100.0
    logits[winner] += damp_logit

    # Softmax
    max_l = max(logits.values())
    exp_l = {k: math.exp(v - max_l) for k, v in logits.items()}
    sum_exp = sum(exp_l.values())
    return {k: (v / sum_exp) for k, v in exp_l.items()}


def _probs_from_regime(regime: str, score: float, trust_score: float | None = None, macro_rank: float = 0.5) -> dict[str, float]:
    """Convert a regime label + score into a 4-class probability distribution.
    Uses logit-space adjustments for macro risk and trust scores (V4).
    """
    cfg = _load_pi_config()
    blend = float(cfg.get("historical_blend", 0.30))
    temp = float(cfg.get("probability_temperature", 1.0))

    regime = canonical_regime(regime)
    mag = min(1.0, abs(score) / 10.0)

    if regime == "RISK_ON":
        base = {"RISK_ON": 0.58 + 0.20 * mag, "SELECTIVE": 0.28 - 0.12 * mag, "DEFENSIVE": 0.10 - 0.05 * mag, "CRISIS": 0.04 - 0.03 * mag}
    elif regime == "CRISIS":
        base = {"RISK_ON": 0.04 - 0.02 * mag, "SELECTIVE": 0.22 - 0.10 * mag, "DEFENSIVE": 0.34 + 0.08 * mag, "CRISIS": 0.40 + 0.04 * mag}
    elif regime == "DEFENSIVE":
        base = {"RISK_ON": 0.08 - 0.03 * mag, "SELECTIVE": 0.28 - 0.05 * mag, "DEFENSIVE": 0.46 + 0.06 * mag, "CRISIS": 0.18 + 0.02 * mag}
    else:
        base = {
            "RISK_ON": 0.25 + 0.04 * max(0.0, score / 10.0),
            "SELECTIVE": 0.52 - 0.08 * mag,
            "DEFENSIVE": 0.18 + 0.04 * max(0.0, -score / 10.0),
        }
        total_others = base["RISK_ON"] + base["SELECTIVE"] + base["DEFENSIVE"]
        base["CRISIS"] = max(0.0, 1.0 - total_others)

    # 1. Macro Awareness Logit Adjustment
    base = _adjust_probs_macro(base, macro_rank)

    # 2. Trust Score Logit Adjustment
    if trust_score is not None:
        base = _apply_trust_damping_logit(base, trust_score)

    # apply mild probability calibration (shrink toward neutral)
    neutral_weight = 0.15
    neutral = 1.0 / len(base)
    calibrated = {k: (1 - neutral_weight) * v + neutral_weight * neutral for k, v in base.items()}
    base = calibrated

    hist = _historical_regime_distribution()
    if regime in hist:
        calibrated_hist = hist[regime]
        sample_size = sum(calibrated_hist.values()) * 100
        dynamic_blend = min(blend, sample_size / (sample_size + 200))
        base = {k: (1 - dynamic_blend) * calibrated[k] + dynamic_blend * calibrated_hist.get(k, 0.0) for k in base}

    # 4. Bayesian Transition Prior: blend with empirical regime→regime probabilities
    #    This grounds predictions in how regimes actually transition in practice.
    transition_priors = _historical_transition_prior()
    if regime in transition_priors:
        trans = transition_priors[regime]
        trans_blend = 0.15  # Conservative blend weight for transition priors
        base = {k: (1 - trans_blend) * base.get(k, 0.0) + trans_blend * trans.get(k, 0.0) for k in base}

    if temp != 1.0:
        adjusted = {k: v ** (1.0 / temp) for k, v in base.items()}
        total = sum(adjusted.values())
        base = {k: v / total for k, v in adjusted.items()}

    return validate_probs(base)


def _confidence_label(probs: dict[str, float], trust_score: float | None = None) -> str:
    top = max(validate_probs(probs).values())
    if trust_score is not None:
        top *= max(0.6, min(1.0, trust_score / 100.0))
    if top >= 0.68:
        return "HIGH"
    if top >= 0.50:
        return "MEDIUM"
    return "LOW"


def _load_trust_score() -> float | None:
    payload = read_json(Path("logs/data_trust_latest.json"))
    if not payload:
        return None
    try:
        return float(payload.get("trust_score"))
    except Exception:
        return None


def _business_add(base_dt: str, days: int) -> str:
    """Add *days* NSE trading days to *base_dt*, skipping holidays."""
    d = add_nse_business_days(pd.Timestamp(base_dt).normalize(), int(days))
    return str(d.date())


def _volatility_band(norm_atr: float) -> float:
    """Core math for dynamic uncertainty bands: scales by ATR/Price and clips to [0.5, 2.0]."""
    # Normalize against a "baseline" volatility (approx 1% daily ATR/Price)
    ref_vol = 0.010 
    vol_factor = norm_atr / ref_vol
    # V4 Clamp: Prevents extreme uncertainty band explosion
    return max(0.5, min(2.0, vol_factor))


def _calculate_vol_factor() -> float:
    """Calculate EMA-smoothed Normalized ATR factor (ATR/Price) from NIFTY 50."""
    try:
        path = Path("data/nse_230_history.parquet")
        if not path.exists():
            return 1.0
        df = pd.read_parquet(path)
        # NIFTY 50 is usually tracked as a proxy for market vol
        sub = df[df["symbol"].isin(["NIFTY 50", "^NSEI"])].copy()
        if sub.empty:
            # Fallback to the first available symbol if index is missing
            sub = df[df["symbol"] == df["symbol"].iloc[0]].copy()
            
        sub = sub.sort_values("date")
        if len(sub) < 20:
            return 1.0
            
        high_low = sub["high"] - sub["low"]
        high_close = (sub["high"] - sub["close"].shift()).abs()
        low_close = (sub["low"] - sub["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        # Use 14-day rolling ATR
        atr = tr.rolling(14).mean()
        norm_atr = atr / sub["close"]
        
        # EMA-smooth the normalized ATR
        ema_vol = norm_atr.ewm(span=5, adjust=False).mean().iloc[-1]
        return _volatility_band(ema_vol)
    except Exception:
        return 1.0


def ensure_model_version() -> str:
    settings = load_regime_settings()
    settings_body = json.dumps(settings, sort_keys=True)
    sh = hashlib.sha256(settings_body.encode("utf-8")).hexdigest()
    version = f"regime_v2_{sh[:10]}"
    versions = load_versions()
    if versions.empty or version not in set(versions["model_version"].astype(str)):
        row = pd.DataFrame([
            {
                "model_version": version,
                "settings_hash": sh,
                "settings_snapshot": settings_body,
                "created_at": now_iso(),
                "notes": "Auto-captured from current regime_settings",
            }
        ])
        save_model_versions(row)
    return version


def _map_score_to_regime(score: float) -> str:
    if score > 6.5:
        return "RISK_ON"
    elif score > 2.0:
        return "SELECTIVE"
    elif score > -3.0:
        return "SELECTIVE"
    elif score > -6.5:
        return "DEFENSIVE"
    else:
        return "CRISIS"

def issue_predictions(as_of: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    cfg = _load_pi_config()

    version = ensure_model_version()
    snap_path, snap = _latest_snapshot()
    if not snap:
        return {"issued": 0, "reason": "No EOD snapshot found"}

    # Validate snapshot freshness (max 2 NSE business days old)
    if snap_path is not None:
        snap_date = snap_path.stem.replace("eod_", "")
        snap_ts = pd.Timestamp(snap_date).normalize()
        today = pd.Timestamp.today().normalize()

        from trading_calendar import nse_business_days_between
        biz_days_old = nse_business_days_between(snap_ts, today)
        if biz_days_old > 2:
            return {"issued": 0, "reason": f"Snapshot stale by {biz_days_old} business days: {snap_date}"}

    trust_score = _load_trust_score()
    # V4: Calculate macro rank for logit probability adjustment
    m_ctx = snap.get("macro_context", {})
    m_score = float(m_ctx.get("score", 0.0))
    m_rank = _get_macro_percentile(m_score)

    issued_date = canonical_date(as_of or datetime.now().date())
    score = _score_from_snapshot(snap)
    
    candidate_regime = _map_score_to_regime(score)
    current_issued = _get_latest_issued_regime()
    
    # 2. 2-Day Confirmation Rule (V5 + Stress Bypass + Fast Recovery)
    # Immediate CRISIS: Bypass confirmation if score is extreme
    if score <= -7.5:
        regime = "CRISIS"
    # Fast-OFF: Bypass confirmation if moving to DEFENSIVE from RISK_ON/SELECTIVE
    elif score <= -4.0 and current_issued in ["RISK_ON", "SELECTIVE"]:
        regime = "DEFENSIVE"
    # Fast-RECOVERY: Bypass confirmation if exiting CRISIS and score has recovered
    elif current_issued == "CRISIS" and score > -3.0:
        regime = "DEFENSIVE"  # Step down to DEFENSIVE first, never jump straight to RISK_ON
    elif candidate_regime == current_issued:
        regime = candidate_regime
    else:
        # Conventional confirmation for other transitions (e.g. recovery or minor cooling)
        conf_count = _get_confirmation_status(candidate_regime)
        if conf_count >= 2:
            regime = candidate_regime
        else:
            # Not confirmed yet, stay with previous regime
            regime = current_issued

    regime = canonical_regime(regime)
    probs = _probs_from_regime(regime, score, trust_score, macro_rank=m_rank)
    conf = _confidence_label(probs, trust_score)

    macro_score = m_score
    liquidity_score = snap.get("breadth", {}).get("ratio")


    input_payload = {
        "snapshot_file": str(snap_path) if snap_path else None,
        "date_issued": issued_date,
        "regime": regime,
        "raw_regime": candidate_regime, # V5: Store original signal for confirmation tracking
        "score": score,
        "probs": probs,
        "confidence": conf,
        "trust": trust_score,
        "model_version": version,
    }
    sig = make_input_signature(input_payload)
    input_payload["signature"] = sig
    
    # V5: Persist JSON record for stateful lookup
    PREDICTION_DIR.mkdir(parents=True, exist_ok=True)
    pred_json_path = PREDICTION_DIR / f"pred_{issued_date.replace('-', '')}.json"
    write_json(pred_json_path, input_payload)

    # V4: EMA-Smoothed Volatility Adjusted Bands
    vol_factor = _calculate_vol_factor()
    
    rows = []
    for h in cfg.get("horizons_days", [1, 5, 20]):
        h = int(h)
        tgt = _business_add(issued_date, h)
        # Scale width by volatility factor
        width = float(cfg.get("score_band_half_width", {}).get(str(h), 2.0)) * vol_factor
        low = round(max(-10.0, score - width), 2)
        high = round(min(10.0, score + width), 2)
        # Deduplicate: ID is simply driven by the Date and Horizon.
        # This prevents minor mid-day trust score changes from generating 6 or 9 duplicate rows.
        pid_seed = f"{issued_date}|{tgt}|{h}"
        pid = hashlib.sha1(pid_seed.encode("utf-8")).hexdigest()[:16]
        # Apply Horizon Decay to probabilities
        h_probs = _apply_horizon_decay(probs, h)
        
        rows.append(
            {
                "prediction_id": pid,
                "date_issued": issued_date,
                "target_date": tgt,
                "horizon_days": h,
                "pred_regime_probs": json.dumps(h_probs, sort_keys=True),
                "pred_score_range_low": low,
                "pred_score_range_high": high,
                "pred_score_mid": round(score, 2),
                "macro_score": macro_score,
                "liquidity_score": liquidity_score,
                "confidence": conf,
                "model_version": version,
                "input_signature": sig,
                "created_at": now_iso(),
            }
        )

    issued = save_predictions(pd.DataFrame(rows))
    return {
        "issued": int(issued),
        "issued_date": issued_date,
        "snapshot_date": snap_date,
        "regime": regime,
        "raw_regime": candidate_regime,
        "score": score,
        "probs": probs,
        "confidence": conf,
        "model_version": version,
    }


def _safe_probs(raw: str) -> dict[str, float]:
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(obj, dict):
            return validate_probs({k: float(v) for k, v in obj.items()})
    except Exception:
        pass
    return validate_probs({})


def _brier(probs: dict[str, float], actual: str) -> float:
    actual = canonical_regime(actual)
    y = {k: (1.0 if k == actual else 0.0) for k in probs}
    return round(sum((probs[k] - y[k]) ** 2 for k in probs) , 6)


def _log_loss(probs: dict[str, float], actual: str) -> float:
    p = max(1e-9, min(1.0, probs.get(canonical_regime(actual), 1e-9)))
    return round(float(-math.log(p)), 6)

def _historical_regime_distribution() -> dict[str, dict[str, float]]:
    """
        Compute empirical distribution of actual regimes
        given predicted regime using historical outcomes.
        """
    global _HIST_REGIME_CACHE
    if _HIST_REGIME_CACHE is not None:
        return _HIST_REGIME_CACHE

    preds = load_predictions()
    outs = load_outcomes()

    if preds.empty or outs.empty:
        return {}

    df = preds.merge(outs, on="prediction_id", how="inner")
    # use only last 180 days of outcomes for calibration
    df["evaluated_at"] = pd.to_datetime(df["evaluated_at"], errors="coerce")
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=180)
    df = df[df["evaluated_at"] >= cutoff]

    if "predicted_regime" not in df.columns:
        return {}

    table = (
        df.groupby(["predicted_regime", "actual_regime"])
        .size()
        .reset_index(name="count")
    )

    result = {}

    for regime in REGIMES:
        subset = table[table["predicted_regime"] == regime]
        total = subset["count"].sum()

        if total == 0:
            continue

        dist = {
            r: float(subset[subset["actual_regime"] == r]["count"].sum()) / total
            for r in REGIMES
        }

        result[regime] = dist

    _HIST_REGIME_CACHE = result
    return result


_TRANSITION_PRIOR_CACHE: dict[str, dict[str, float]] | None = None


def _historical_transition_prior() -> dict[str, dict[str, float]]:
    """Compute empirical regime transition matrix from historical outcomes.
    Returns: {current_regime: {next_regime: probability}} (Bayesian prior).
    Used to ground predictions in realized market behavior.
    """
    global _TRANSITION_PRIOR_CACHE
    if _TRANSITION_PRIOR_CACHE is not None:
        return _TRANSITION_PRIOR_CACHE

    outs = load_outcomes()
    if outs.empty or len(outs) < 10:
        return {}

    df = outs.sort_values("evaluated_at").copy()
    df["next_regime"] = df["actual_regime"].shift(-1)
    df = df.dropna(subset=["next_regime"])

    if df.empty:
        return {}

    table = (
        df.groupby(["actual_regime", "next_regime"])
        .size()
        .reset_index(name="count")
    )

    result = {}
    for regime in REGIMES:
        subset = table[table["actual_regime"] == regime]
        total = subset["count"].sum()
        if total == 0:
            continue
        dist = {
            r: float(subset[subset["next_regime"] == r]["count"].sum()) / total
            for r in REGIMES
        }
        result[regime] = dist

    _TRANSITION_PRIOR_CACHE = result
    return result

def evaluate_matured(as_of: str | None = None) -> dict[str, Any]:
    preds = load_predictions()
    outs = load_outcomes()
    if preds.empty:
        return {"evaluated": 0, "reason": "No predictions present"}

    today = canonical_date(as_of or datetime.now().date())
    done_ids = set(outs["prediction_id"].astype(str).tolist()) if not outs.empty else set()

    rows = []
    for _, row in preds.iterrows():
        pid = str(row.get("prediction_id"))
        if pid in done_ids:
            continue
        tgt = canonical_date(row.get("target_date"))
        if tgt > today:
            continue
        snap = _snapshot_for_date(tgt)
        if not snap:
            continue

        # Ground truth for calibration must be the RAW engine result from the snapshot
        actual_regime = canonical_regime(str(snap.get("regime", "SELECTIVE")))
        actual_score = _score_from_snapshot(snap)
        probs = _safe_probs(row.get("pred_regime_probs"))
        pred_regime = top_regime(probs)
        # Enrichment for V5.1 Attribution
        raw_score = _score_from_snapshot(snap) # Recalculate raw score if needed
        ema_score = float(row.get("pred_score_mid", 0.0))
        prob_actual = float(probs.get(actual_regime, 0.0))
        edge = prob_actual - 0.25
        lo = float(row.get("pred_score_range_low", -10.0))
        hi = float(row.get("pred_score_range_high", 10.0))
        
        # Determine switch_type
        # We look at the history to see if there was a "Candidate" mismatch
        # For simplicity in this first batch, we categorize by correctness and smoothness delta
        switch_type = "STABLE"
        if actual_regime != pred_regime:
            # If Raw score was correct but EMA score was wrong -> DELAYED_FILTER
            # We map actual_regime back to score logic
            if actual_regime == _map_score_to_regime(raw_score): 
                 switch_type = "DELAYED_FILTER"
            else:
                 switch_type = "SIGNAL_ERROR"
        else:
            if abs(raw_score - ema_score) > 5.0:
                 switch_type = "WHIPSAW_FILTERED"
            else:
                 switch_type = "STABLE"

        rows.append(
            {
                "prediction_id": pid,
                "evaluated_at": now_iso(),
                "actual_regime": actual_regime,
                "predicted_regime": pred_regime,
                "actual_score": round(actual_score, 2),
                "prob_actual": prob_actual,
                "edge": edge,
                "brier_score": _brier(probs, actual_regime),
                "log_loss": _log_loss(probs, actual_regime),
                "score_mae": round(abs(ema_score - actual_score), 4),
                "in_band": bool(lo <= actual_score <= hi),
                "regime_correct": bool(pred_regime == actual_regime),
                "sharpness": round(max(probs.values()), 4),
                "model_version": str(row.get("model_version", "unknown")),
                "horizon_days": int(row.get("horizon_days", 1)),
                "raw_score": round(raw_score, 2),
                "ema_score": round(ema_score, 2),
                "macro_weight": float(row.get("macro_score", 0.0)), # Mapping to weights
                "vol_factor": float(row.get("liquidity_score", 1.0)), # Proxy
                "switch_type": switch_type,
                "regime_persistence_age": 0 # TODO: Implement age tracking
            }
        )

    inserted = save_outcomes(pd.DataFrame(rows)) if rows else 0

    # reset historical calibration cache if new outcomes were added
    if inserted > 0:
        global _HIST_REGIME_CACHE
        _HIST_REGIME_CACHE = None

    return {"evaluated": int(inserted), "as_of": today}



def run_daily_cycle(as_of: str | None = None) -> dict[str, Any]:
    global _HIST_REGIME_CACHE
    _HIST_REGIME_CACHE = None

    issue = issue_predictions(as_of=as_of)
    evald = evaluate_matured(as_of=as_of)
    payload = {
        "timestamp": now_iso(),
        "issue": issue,
        "evaluate": evald,
    }
    write_json(Path("logs/prediction_integrity_latest.json"), payload)
    return payload


def _month_bounds(month: str) -> tuple[str, str]:
    start = pd.Timestamp(f"{month}-01").normalize()
    end = (start + pd.offsets.MonthEnd(1)).normalize()
    return str(start.date()), str(end.date())


def _recommendations(metrics: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    blend = settings.get("blend", {})
    neutral_band = float(blend.get("neutral_band", 0.35))
    impulse = float(blend.get("impulse_influence", 0.25))

    acc = float(metrics.get("regime_accuracy", 0.0))
    brier = float(metrics.get("avg_brier", 1.0))
    in_band = float(metrics.get("in_band_rate", 0.0))

    if acc < 0.45 and brier > 0.22:
        new_neutral = min(0.55, neutral_band + 0.03)
        recs.append(
            {
                "field": "blend.neutral_band",
                "current": neutral_band,
                "proposed": round(new_neutral, 3),
                "reason": "Low regime accuracy + weak probabilistic calibration; widen neutral zone.",
            }
        )

    if in_band < 0.55:
        new_impulse = max(0.1, impulse - 0.03)
        recs.append(
            {
                "field": "blend.impulse_influence",
                "current": impulse,
                "proposed": round(new_impulse, 3),
                "reason": "Prediction score bands under-cover realized outcomes; reduce short-term impulse weight.",
            }
        )

    if not recs:
        recs.append(
            {
                "field": "none",
                "current": None,
                "proposed": None,
                "reason": "No material drift detected. Keep current settings.",
            }
        )
    return recs


def _emit_no_data(m: str, message: str) -> dict[str, Any]:
    """Write a NO_DATA calibration report + NO-OP proposal for *m* (YYYY-MM)."""
    payload = {
        "month": m,
        "status": "NO_DATA",
        "message": message,
        "generated_at": now_iso(),
    }
    report_file = CAL_DIR / f"monthly_calibration_{m.replace('-', '_')}.json"
    write_json(report_file, payload)
    proposal = {
        "proposal_id": f"PI-CAL-{m.replace('-', '')}",
        "month": m,
        "status": "PENDING_APPROVAL",
        "generated_at": now_iso(),
        "based_on_report": str(report_file),
        "criteria_summary": {"count": 0},
        "proposed_changes": [
            {
                "field": "none",
                "current": None,
                "proposed": None,
                "reason": f"{message} Carry current settings until sufficient sample.",
            }
        ],
        "review_notes": "No-data month. Approve as NO_OP or request manual review.",
        "approval": {"approved_by": None, "approved_at": None, "comments": None},
    }
    write_json(PROPOSAL_DIR / f"proposal_{m.replace('-', '_')}.json", proposal)
    return payload


def _reliability_table(df: pd.DataFrame, bins: int = 10, group_by_regime: bool = False) -> dict[str, Any]:
    if df.empty:
        return {}
    
    def process_subset(subset_df: pd.DataFrame) -> list[dict[str, Any]]:
        if len(subset_df) < bins:
             return []
        tmp = subset_df.copy()
        try:
            tmp["prob_bin"] = pd.qcut(tmp["prob_actual"], q=bins, duplicates="drop")
        except ValueError:
            tmp["prob_bin"] = pd.cut(tmp["prob_actual"], bins=bins)
        
        tmp["regime_correct_int"] = tmp["regime_correct"].astype(int)
        
        agg = (
            tmp.groupby("prob_bin", observed=False)
            .agg(
                predicted=("prob_actual", "mean"),
                observed=("regime_correct_int", "mean"),
                count=("prob_actual", "size")
            )
            .reset_index()
        )
        agg["prob_bin"] = agg["prob_bin"].astype(str)
        agg = agg.dropna(subset=["predicted"])
        
        return [
            {
                "bin": str(row["prob_bin"]),
                "predicted_prob": round(float(row["predicted"]), 4),
                "observed_freq": round(float(row["observed"]), 4),
                "count": int(row["count"])
            }
            for _, row in agg.iterrows()
        ]

    result = {"all": process_subset(df)}
    if group_by_regime:
        for r in REGIMES:
            sub = df[df["predicted_regime"] == r]
            if not sub.empty:
                result[r] = process_subset(sub)
    
    return result

def _brier_skill_score(outcomes_df: pd.DataFrame) -> float:
    """Computes Brier Skill Score relative to Naive Persistence Benchmark.
    
    The naive persistence model predicts: P(tomorrow = today's actual regime) = 1.0.
    Its Brier score equals the actual transition rate in the data.
    """
    if len(outcomes_df) < 5:
        return 0.0
    
    # 1. Model Brier
    model_brier = outcomes_df["brier_score"].mean()
    
    # 2. Reference Brier (Naive Persistence: predict tomorrow = today)
    # For each outcome, the naive forecast is P=1.0 for the *previous* actual regime.
    # We approximate this by checking how often the regime actually persisted.
    df_sorted = outcomes_df.sort_values("evaluated_at").copy()
    df_sorted["prev_actual"] = df_sorted["actual_regime"].shift(1)
    df_sorted = df_sorted.dropna(subset=["prev_actual"])
    
    if df_sorted.empty:
        ref_brier = 0.75  # Fallback to uniform if insufficient data
    else:
        # Naive Brier = avg over rows of: sum_k (I(k==prev) - I(k==actual))^2
        # When prev==actual: Brier = 0. When prev!=actual: Brier = 2.0 (for 4-class one-hot).
        persistence_rate = (df_sorted["prev_actual"] == df_sorted["actual_regime"]).mean()
        ref_brier = (1.0 - persistence_rate) * 2.0  # Expected Brier of naive model
    
    if ref_brier <= 0:
        return 0.0
    return 1.0 - (model_brier / ref_brier)


def _rolling_skill(outcomes_df: pd.DataFrame, window: int = 30) -> list[dict[str, Any]]:
    if outcomes_df.empty:
        return []

    df = outcomes_df.copy()
    df = df.sort_values("target_date")

    df["model_correct"] = df["regime_correct"].astype(float)

    # rolling model accuracy
    df["model_acc"] = df["model_correct"].rolling(window=window, min_periods=window).mean()

    # rolling baseline: Map regimes to integers so rolling works
    regime_map = {r: i for i, r in enumerate(REGIMES)}
    df["regime_int"] = df["actual_regime"].map(regime_map)
    
    if df["regime_int"].isna().any():
        raise ValueError("Unknown regime detected in rolling skill computation")
        
    df["regime_int"] = df["regime_int"].astype(int)

    df["baseline_acc"] = (
        df["regime_int"]
        .rolling(window=window, min_periods=window)
        .apply(lambda x: np.bincount(x.astype(int)).max() / len(x), raw=True)
    )

    df["skill"] = df["model_acc"] - df["baseline_acc"]

    out = df[["target_date", "model_acc", "baseline_acc", "skill"]].dropna()

    return [
        {
            "target_date": str(row["target_date"])[:10],
            "model_acc": round(float(row["model_acc"]), 4),
            "baseline_acc": round(float(row["baseline_acc"]), 4),
            "skill": round(float(row["skill"]), 4)
        }
        for _, row in out.iterrows()
    ]


def plot_reliability_curve(reliability_data: dict[str, Any], month: str):
    if not reliability_data or "all" not in reliability_data or not reliability_data["all"]:
        print("No reliability data available to plot.")
        return

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available, skipping plot.")
        return
    df = pd.DataFrame(reliability_data["all"])

    plt.figure(figsize=(6, 6))

    # Perfect calibration line
    plt.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect Calibration")

    # Model curve (sized by confidence bubble)
    plt.plot(df["predicted_prob"], df["observed_freq"], marker="", linestyle="-", color="blue", alpha=0.5)
    plt.scatter(
        df["predicted_prob"],
        df["observed_freq"],
        s=df["count"] * 20,
        color="darkblue",
        alpha=0.7,
        label="Model Prediction Bins"
    )

    plt.xlabel("Predicted Probability")
    plt.ylabel("Observed Frequency")
    plt.title(f"Prediction Reliability Curve ({month})")
    plt.legend()
    plt.grid(True)
    
    # Save instead of blocking execution with show()
    ensure_dirs()
    plot_path = CAL_DIR / f"reliability_curve_{month.replace('-', '_')}.png"
    plt.savefig(plot_path, bbox_inches="tight")
    plt.close()


def generate_monthly_calibration(month: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    now = pd.Timestamp.today().normalize()
    m = month or str((now - pd.offsets.MonthBegin(1)).date())[:7]
    start, end = _month_bounds(m)

    preds = load_predictions()
    outs = load_outcomes()
    if preds.empty or outs.empty:
        return _emit_no_data(m, "Insufficient predictions/outcomes for calibration.")

    # Drop duplicate columns from outcomes before merging to avoid suffixes
    outs_clean = outs.drop(columns=["horizon_days", "model_version"], errors="ignore")
    merged = preds.merge(outs_clean, on="prediction_id", how="inner")
    # compute baseline regime distribution
    baseline = (
        merged["actual_regime"]
        .value_counts(normalize=True)
        .to_dict()
    )
    naive_accuracy = max(baseline.values()) if baseline else 0.0

    # build monthly skill trend
    merged["target_date"] = pd.to_datetime(merged["target_date"], errors="coerce")
    merged["month"] = merged["target_date"].dt.to_period("M").astype(str)

    trend = (
        merged.groupby("month")
        .agg(
            count=("prediction_id", "count"),
            avg_brier=("brier_score", "mean"),
            avg_log_loss=("log_loss", "mean"),
            regime_accuracy=("regime_correct", "mean"),
            avg_edge=("edge", "mean"),
        )
        .reset_index()
    )

    skill_trend = trend.to_dict(orient="records")

    # ---- 1. Reliability Curve & Skill ----
    mdf_full = merged.copy()
    reliability = _reliability_table(mdf_full, bins=10, group_by_regime=True)
    bss = _brier_skill_score(mdf_full)

    # ---- 2. Regime Transition Matrix ----
    mdf_full = mdf_full.sort_values(by="target_date").copy()
    mdf_full["next_regime"] = mdf_full["actual_regime"].shift(-1)
    
    # Drop last row where next_regime is NaN
    mdf_transitions = mdf_full.dropna(subset=["next_regime"])
    
    if not mdf_transitions.empty:
        t_matrix = pd.crosstab(
            mdf_transitions["actual_regime"],
            mdf_transitions["next_regime"],
            normalize="index"
        ).reindex(index=REGIMES, columns=REGIMES, fill_value=0.0)
        
        transition_matrix = {
            regime: {k: round(v, 4) for k, v in row.to_dict().items()}
            for regime, row in t_matrix.iterrows()
        }
    else:
        transition_matrix = {r: {k: 0.0 for k in REGIMES} for r in REGIMES}

    # ---- 3. Rolling Skill Score (30-day) ----
    merged["target_date"] = pd.to_datetime(merged["target_date"], errors="coerce")
    rolling_skill = _rolling_skill(merged, window=30)

    mdf = merged[(pd.to_datetime(merged["target_date"]) >= pd.Timestamp(start)) & (pd.to_datetime(merged["target_date"]) <= pd.Timestamp(end))].copy()

    # ---- Factor Dominance Classification ----
    if mdf.empty:
        return _emit_no_data(m, "No matured outcomes in selected month.")
    def classify_factor(row):
        macro = abs(row.get("macro_score", 0))
        liq = abs(row.get("liquidity_score", 0))

        if macro > liq * 1.2:
            return "MACRO_DOMINANT"
        elif liq > macro * 1.2:
            return "LIQUIDITY_DOMINANT"
        else:
            return "MIXED"

    mdf["factor_dominance"] = mdf.apply(classify_factor, axis=1)

    factor_perf = []

    for f, g in mdf.groupby("factor_dominance"):
        acc = float(g["regime_correct"].mean())
        baseline = naive_accuracy

        factor_perf.append(
            {
                "factor_group": f,
                "count": int(len(g)),
                "accuracy": round(acc, 4),
                "baseline_accuracy": round(naive_accuracy, 4),
                "skill_vs_baseline": round(acc - naive_accuracy, 4),
            }
        )

    # If no groups exist
    if not factor_perf:
        factor_perf = [
            {
                "status": "INSUFFICIENT_DATA",
                "message": "No evaluated predictions available for factor attribution."
            }
        ]

    mdf["regime_correct"] = mdf["regime_correct"].astype(bool)
    mdf["in_band"] = mdf["in_band"].astype(bool)

    overall_accuracy = float(mdf["regime_correct"].mean())
    skill_score = overall_accuracy - naive_accuracy
    normalized_skill = skill_score / (1.0 - naive_accuracy) if naive_accuracy < 1.0 else 0.0
    
    # V4: Switch Accuracy (Accuracy on regime changes)
    merged_sorted = mdf.sort_values("target_date")
    merged_sorted["prev_pred"] = merged_sorted["predicted_regime"].shift(1)
    switches = merged_sorted[merged_sorted["predicted_regime"] != merged_sorted["prev_pred"]]
    switch_acc = float(switches["regime_correct"].mean()) if not switches.empty else 0.0

    overall = {
        "count": int(len(mdf)),
        "avg_brier": round(float(pd.to_numeric(mdf["brier_score"], errors="coerce").mean()), 6),
        "avg_log_loss": round(float(pd.to_numeric(mdf["log_loss"], errors="coerce").mean()), 6),
        "avg_score_mae": round(float(pd.to_numeric(mdf["score_mae"], errors="coerce").mean()), 6),
        "in_band_rate": round(float(mdf["in_band"].mean()), 6),
        "avg_edge": round(float(pd.to_numeric(mdf["edge"], errors="coerce").mean()), 6),
        "avg_sharpness": round(float(pd.to_numeric(mdf.get("sharpness", 0.25), errors="coerce").mean()), 4),
        "brier_skill_score": round(bss, 4),
        "switch_accuracy": round(switch_acc, 4),
    }

    skill_metrics = {
        "model_accuracy": round(overall_accuracy, 6),
        "naive_accuracy": round(naive_accuracy, 6),
        "skill_score": round(skill_score, 6),
        "normalized_skill": round(normalized_skill, 6)
    }

    by_horizon = []
    for h, g in mdf.groupby("horizon_days"):
        by_horizon.append(
            {
                "horizon_days": int(h),
                "count": int(len(g)),
                "avg_brier": round(float(pd.to_numeric(g["brier_score"], errors="coerce").mean()), 6),
                "avg_log_loss": round(float(pd.to_numeric(g["log_loss"], errors="coerce").mean()), 6),
                "avg_score_mae": round(float(pd.to_numeric(g["score_mae"], errors="coerce").mean()), 6),
                "regime_accuracy": round(float(g["regime_correct"].mean()), 6),
                "in_band_rate": round(float(g["in_band"].mean()), 6),
                "baseline_accuracy": round(float(g["actual_regime"].value_counts(normalize=True).max()), 6),
                "skill_vs_baseline": round(
                    float(g["regime_correct"].mean() - g["actual_regime"].value_counts(normalize=True).max()),
                    6,
                ),
            }
        )

    conf_table = []
    for c, g in mdf.groupby("confidence"):
        conf_table.append(
            {
                "confidence": str(c),
                "count": int(len(g)),
                "realized_accuracy": round(float(g["regime_correct"].mean()), 6),
                "realized_in_band": round(float(g["in_band"].mean()), 6),
            }


        )

    settings = load_regime_settings()
    # Recommendations now rely on skill_metrics internally where previously they used overall
    eval_metrics_for_recs = {
        **overall, 
        "regime_accuracy": skill_metrics["model_accuracy"]
    }
    recs = _recommendations(eval_metrics_for_recs, settings)

    # Build regime confusion matrix
    confusion = (
        mdf.groupby(["predicted_regime", "actual_regime"])
        .size()
        .reset_index(name="count")
    )

    confusion_table = confusion.to_dict(orient="records")

    report = {
        "month": m,
        "period_start": start,
        "period_end": end,
        "status": "OK",
        "generated_at": now_iso(),
        "overall_metrics": overall,
        "skill_metrics": skill_metrics,
        "reliability_curve": reliability,
        "brier_skill_score": bss,
        "transition_matrix": transition_matrix,
        "rolling_skill_30d": rolling_skill,
        "by_horizon": by_horizon,
        "confidence_calibration": conf_table,
        "regime_confusion": confusion_table,
        "skill_trend": skill_trend,
        "factor_skill_attribution": factor_perf,
        "recommendations": recs,
    }

    report_file = CAL_DIR / f"monthly_calibration_{m.replace('-', '_')}.json"
    write_json(report_file, report)

    proposal = {
        "proposal_id": f"PI-CAL-{m.replace('-', '')}",
        "month": m,
        "status": "PENDING_APPROVAL",
        "generated_at": now_iso(),
        "based_on_report": str(report_file),
        "criteria_summary": overall,
        "proposed_changes": recs,
        "review_notes": "Please review recommendations. Set status to APPROVED / REJECTED / MODIFY_REQUESTED.",
        "approval": {
            "approved_by": None,
            "approved_at": None,
            "comments": None,
        },
    }
    write_json(PROPOSAL_DIR / f"proposal_{m.replace('-', '_')}.json", proposal)
    
    # Plot real-time reliability curve
    plot_reliability_curve(reliability, m)
    
    return report


def apply_approved_proposal(proposal_path: str | None = None, approved_by: str = "manual") -> dict[str, Any]:
    p = Path(proposal_path) if proposal_path else latest_calibration_proposal()
    if not p or not p.exists():
        return {"applied": 0, "reason": "No proposal found"}

    proposal = read_json(p)
    if not proposal:
        return {"applied": 0, "reason": "Invalid proposal JSON"}

    status = str(proposal.get("status", "")).upper()
    if status != "APPROVED":
        return {"applied": 0, "reason": f"Proposal status is {status or 'UNKNOWN'}, not APPROVED"}

    changes = proposal.get("proposed_changes", [])
    if not isinstance(changes, list):
        return {"applied": 0, "reason": "No proposed changes list"}

    settings = load_regime_settings()
    applied = 0

    for change in changes:
        field = str(change.get("field", ""))

        if field == "none":
            continue

        parts = field.split(".")

        node: Any = settings

        for part in parts[:-1]:
            if not isinstance(node, dict):
                print(f"[Proposal Warning] Invalid path: {field}")
                node = None
                break

            node = node.get(part)

        if not isinstance(node, dict):
            continue

        leaf = parts[-1]

        if leaf not in node:
            print(f"[Proposal Warning] Leaf missing: {field}")
            continue

        node[leaf] = change.get("proposed")
        applied += 1

    if applied > 0:
        save_regime_settings(settings)

    proposal["status"] = "IMPLEMENTED" if applied > 0 else "NO_OP"
    proposal["approval"] = {
        "approved_by": approved_by,
        "approved_at": now_iso(),
        "comments": proposal.get("approval", {}).get("comments"),
    }
    write_json(p, proposal)

    ensure_model_version()
    return {"applied": applied, "proposal": str(p)}
