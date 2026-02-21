from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from regime_model import load_regime_settings, save_regime_settings

from .schema import canonical_date, canonical_regime, make_input_signature, now_iso, top_regime, validate_probs
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
PI_CFG_FILE = Path("notes/prediction_integrity_config.json")

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


def _score_from_snapshot(snap: dict[str, Any]) -> float:
    regime_score = float(snap.get("regime_score", 0.0))
    breadth = snap.get("breadth", {}) if isinstance(snap.get("breadth"), dict) else {}
    ratio = float(breadth.get("ratio", 1.0)) if breadth else 1.0
    ratio_component = max(-1.0, min(1.0, ratio - 1.0))
    norm = max(-1.0, min(1.0, (0.65 * (regime_score / 2.0)) + (0.35 * ratio_component)))
    return round(norm * 10.0, 2)


def _probs_from_regime(regime: str, score: float, trust_score: float | None = None) -> dict[str, float]:
    regime = canonical_regime(regime)
    mag = min(1.0, abs(score) / 10.0)
    if regime == "RISK_ON":
        base = {"RISK_ON": 0.58 + 0.20 * mag, "SELECTIVE": 0.28 - 0.12 * mag, "DEFENSIVE": 0.10 - 0.05 * mag, "CRISIS": 0.04 - 0.03 * mag}
    elif regime == "CRISIS":
        base = {"RISK_ON": 0.04 - 0.02 * mag, "SELECTIVE": 0.22 - 0.10 * mag, "DEFENSIVE": 0.34 + 0.08 * mag, "CRISIS": 0.40 + 0.04 * mag}
    elif regime == "DEFENSIVE":
        base = {"RISK_ON": 0.08 - 0.03 * mag, "SELECTIVE": 0.28 - 0.05 * mag, "DEFENSIVE": 0.46 + 0.06 * mag, "CRISIS": 0.18 + 0.02 * mag}
    else:
        base = {"RISK_ON": 0.25 + 0.04 * max(0.0, score / 10.0), "SELECTIVE": 0.52 - 0.08 * mag, "DEFENSIVE": 0.18 + 0.04 * max(0.0, -score / 10.0), "CRISIS": 0.05}

    if trust_score is not None and trust_score < 95:
        damp = 1.0 - min(0.25, (95 - trust_score) / 100.0)
        winner = max(base, key=base.get)
        for k in base:
            if k == winner:
                base[k] *= damp
            else:
                base[k] *= (2 - damp) / 2
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
    d = pd.Timestamp(base_dt).normalize() + pd.offsets.BDay(int(days))
    return str(d.date())


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


def issue_predictions(as_of: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    cfg = _load_pi_config()
    version = ensure_model_version()
    snap_path, snap = _latest_snapshot()
    if not snap:
        return {"issued": 0, "reason": "No EOD snapshot found"}

    trust_score = _load_trust_score()
    issued_date = canonical_date(as_of or datetime.now().date())
    regime = canonical_regime(str(snap.get("regime", "SELECTIVE")))
    score = _score_from_snapshot(snap)
    probs = _probs_from_regime(regime, score, trust_score)
    conf = _confidence_label(probs, trust_score)

    input_payload = {
        "snapshot_file": str(snap_path) if snap_path else None,
        "regime": regime,
        "score": score,
        "probs": probs,
        "confidence": conf,
        "trust": trust_score,
        "model_version": version,
    }
    sig = make_input_signature(input_payload)

    rows = []
    for h in cfg.get("horizons_days", [1, 5, 20]):
        h = int(h)
        tgt = _business_add(issued_date, h)
        width = float(cfg.get("score_band_half_width", {}).get(str(h), 2.0))
        low = round(max(-10.0, score - width), 2)
        high = round(min(10.0, score + width), 2)
        pid_seed = f"{issued_date}|{tgt}|{h}|{version}|{sig}"
        pid = hashlib.sha1(pid_seed.encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "prediction_id": pid,
                "date_issued": issued_date,
                "target_date": tgt,
                "horizon_days": h,
                "pred_regime_probs": json.dumps(probs, sort_keys=True),
                "pred_score_range_low": low,
                "pred_score_range_high": high,
                "pred_score_mid": round(score, 2),
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
        "regime": regime,
        "score": score,
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
    return round(sum((probs[k] - y[k]) ** 2 for k in probs) / len(probs), 6)


def _log_loss(probs: dict[str, float], actual: str) -> float:
    p = max(1e-9, min(1.0, probs.get(canonical_regime(actual), 1e-9)))
    return round(float(-math.log(p)), 6)


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

        actual_regime = canonical_regime(str(snap.get("regime", "SELECTIVE")))
        actual_score = _score_from_snapshot(snap)
        probs = _safe_probs(row.get("pred_regime_probs"))
        pred_mid = float(row.get("pred_score_mid", 0.0))
        lo = float(row.get("pred_score_range_low", -10.0))
        hi = float(row.get("pred_score_range_high", 10.0))

        rows.append(
            {
                "prediction_id": pid,
                "evaluated_at": now_iso(),
                "actual_regime": actual_regime,
                "actual_score": round(actual_score, 2),
                "brier_score": _brier(probs, actual_regime),
                "log_loss": _log_loss(probs, actual_regime),
                "score_mae": round(abs(pred_mid - actual_score), 4),
                "in_band": bool(lo <= actual_score <= hi),
                "regime_correct": bool(top_regime(probs) == actual_regime),
            }
        )

    inserted = save_outcomes(pd.DataFrame(rows)) if rows else 0
    return {"evaluated": int(inserted), "as_of": today}


def run_daily_cycle(as_of: str | None = None) -> dict[str, Any]:
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


def generate_monthly_calibration(month: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    now = pd.Timestamp.today().normalize()
    m = month or str((now - pd.offsets.MonthBegin(1)).date())[:7]
    start, end = _month_bounds(m)

    preds = load_predictions()
    outs = load_outcomes()
    if preds.empty or outs.empty:
        payload = {
            "month": m,
            "status": "NO_DATA",
            "message": "Insufficient predictions/outcomes for calibration",
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
                    "reason": "No matured outcomes available. Carry current settings until sufficient sample.",
                }
            ],
            "review_notes": "No-data month. You can approve as NO_OP or request manual parameter adjustment.",
            "approval": {"approved_by": None, "approved_at": None, "comments": None},
        }
        write_json(PROPOSAL_DIR / f"proposal_{m.replace('-', '_')}.json", proposal)
        return payload

    merged = preds.merge(outs, on="prediction_id", how="inner")
    merged["target_date"] = pd.to_datetime(merged["target_date"], errors="coerce")
    mdf = merged[(merged["target_date"] >= pd.Timestamp(start)) & (merged["target_date"] <= pd.Timestamp(end))].copy()

    if mdf.empty:
        payload = {
            "month": m,
            "status": "NO_DATA",
            "message": "No matured outcomes in selected month",
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
                    "reason": "No matured outcomes available in this month. Keep current settings.",
                }
            ],
            "review_notes": "No-data month. Approve as NO_OP or request manual review.",
            "approval": {"approved_by": None, "approved_at": None, "comments": None},
        }
        write_json(PROPOSAL_DIR / f"proposal_{m.replace('-', '_')}.json", proposal)
        return payload

    mdf["regime_correct"] = mdf["regime_correct"].astype(bool)
    mdf["in_band"] = mdf["in_band"].astype(bool)

    overall = {
        "count": int(len(mdf)),
        "avg_brier": round(float(pd.to_numeric(mdf["brier_score"], errors="coerce").mean()), 6),
        "avg_log_loss": round(float(pd.to_numeric(mdf["log_loss"], errors="coerce").mean()), 6),
        "avg_score_mae": round(float(pd.to_numeric(mdf["score_mae"], errors="coerce").mean()), 6),
        "regime_accuracy": round(float(mdf["regime_correct"].mean()), 6),
        "in_band_rate": round(float(mdf["in_band"].mean()), 6),
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
    recs = _recommendations(overall, settings)

    report = {
        "month": m,
        "period_start": start,
        "period_end": end,
        "status": "OK",
        "generated_at": now_iso(),
        "overall": overall,
        "by_horizon": by_horizon,
        "confidence_calibration": conf_table,
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
        if len(parts) < 2:
            continue
        node: Any = settings
        for part in parts[:-1]:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        if not isinstance(node, dict):
            continue
        leaf = parts[-1]
        if leaf not in node:
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
