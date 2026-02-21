from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

REGIMES = ["RISK_ON", "SELECTIVE", "DEFENSIVE", "CRISIS"]
CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class PredictionRecord:
    prediction_id: str
    date_issued: str
    target_date: str
    horizon_days: int
    pred_regime_probs: dict[str, float]
    pred_score_range_low: float
    pred_score_range_high: float
    pred_score_mid: float
    confidence: str
    model_version: str
    input_signature: str
    created_at: str


@dataclass(frozen=True)
class OutcomeRecord:
    prediction_id: str
    evaluated_at: str
    actual_regime: str
    actual_score: float
    brier_score: float
    log_loss: float
    score_mae: float
    in_band: bool
    regime_correct: bool


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def canonical_date(value: Any) -> str:
    return str(pd.Timestamp(value).date())


def canonical_regime(value: str) -> str:
    v = str(value or "").upper().strip().replace(" ", "_")
    if "RISK" in v and "ON" in v:
        return "RISK_ON"
    if "RISK" in v and "OFF" in v:
        return "CRISIS"
    if v in REGIMES:
        return v
    return "SELECTIVE"


def validate_probs(probs: dict[str, float]) -> dict[str, float]:
    out = {k: float(probs.get(k, 0.0)) for k in REGIMES}
    total = sum(max(0.0, x) for x in out.values())
    if total <= 0:
        return {"RISK_ON": 0.25, "SELECTIVE": 0.5, "DEFENSIVE": 0.2, "CRISIS": 0.05}
    out = {k: max(0.0, v) / total for k, v in out.items()}
    # stable rounding + exact sum=1
    running = 0.0
    rounded: dict[str, float] = {}
    for k in REGIMES[:-1]:
        rv = round(out[k], 6)
        rounded[k] = rv
        running += rv
    rounded[REGIMES[-1]] = round(max(0.0, 1.0 - running), 6)
    return rounded


def make_input_signature(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def top_regime(probs: dict[str, float]) -> str:
    normalized = validate_probs(probs)
    return max(normalized.items(), key=lambda kv: kv[1])[0]
