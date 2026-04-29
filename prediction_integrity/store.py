from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path("data/prediction_integrity")
PREDICTIONS_FILE = BASE_DIR / "predictions.parquet"
OUTCOMES_FILE = BASE_DIR / "outcomes.parquet"
VERSIONS_FILE = BASE_DIR / "model_versions.parquet"
CAL_DIR = BASE_DIR / "calibration"
PROPOSAL_DIR = CAL_DIR / "proposals"


def ensure_dirs() -> None:
    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "model_versions").mkdir(parents=True, exist_ok=True)


def _read_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_parquet(path)
        if df is None:
            return pd.DataFrame(columns=columns)
        for c in columns:
            if c not in df.columns:
                df[c] = pd.NA
        return df[columns].copy()
    except Exception:
        return pd.DataFrame(columns=columns)


def _write_parquet(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def append_immutable(path: Path, rows: pd.DataFrame, key_col: str, columns: list[str]) -> int:
    if rows is None or rows.empty:
        return 0
    base = _read_parquet(path, columns)
    rows = rows.copy()
    for c in columns:
        if c not in rows.columns:
            rows[c] = pd.NA
    rows = rows[columns]
    if not base.empty:
        existing = set(base[key_col].astype(str).tolist())
        rows = rows[~rows[key_col].astype(str).isin(existing)].copy()
    if rows.empty:
        return 0
    out = rows.reset_index(drop=True) if base.empty else pd.concat([base, rows], ignore_index=True)
    _write_parquet(path, out)
    return len(rows)


def load_predictions() -> pd.DataFrame:
    cols = [
        "prediction_id", "date_issued", "target_date", "horizon_days", "pred_regime_probs",
        "pred_score_range_low", "pred_score_range_high", "pred_score_mid", "macro_score", "liquidity_score", "confidence",
        "model_version", "input_signature", "created_at",
    ]
    return _read_parquet(PREDICTIONS_FILE, cols)


def load_outcomes() -> pd.DataFrame:
    cols = [
        "prediction_id", "evaluated_at", "actual_regime", "predicted_regime", 
        "actual_score", "prob_actual", "edge", "brier_score", "log_loss",
        "score_mae", "in_band", "regime_correct", "sharpness",
        "model_version", "horizon_days", "raw_score", "ema_score",
        "macro_weight", "vol_factor", "switch_type", "regime_persistence_age"
    ]
    return _read_parquet(OUTCOMES_FILE, cols)


def load_versions() -> pd.DataFrame:
    cols = ["model_version", "settings_hash", "settings_snapshot", "created_at", "notes"]
    return _read_parquet(VERSIONS_FILE, cols)


def save_predictions(rows: pd.DataFrame) -> int:
    return append_immutable(PREDICTIONS_FILE, rows, "prediction_id", list(load_predictions().columns))


def save_outcomes(rows: pd.DataFrame) -> int:
    return append_immutable(OUTCOMES_FILE, rows, "prediction_id", list(load_outcomes().columns))


def save_model_versions(rows: pd.DataFrame) -> int:
    return append_immutable(VERSIONS_FILE, rows, "model_version", list(load_versions().columns))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def latest_calibration_proposal() -> Path | None:
    files = sorted(PROPOSAL_DIR.glob("proposal_*.json"))
    return files[-1] if files else None
