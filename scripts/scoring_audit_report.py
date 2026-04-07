"""
Compute daily Scoring Audit report for regime/indicator logic consistency.

Outputs:
- logs/scoring_audit_latest.json
- logs/scoring_audit_YYYYMMDD.json
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import runpy
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regime_model import load_regime_settings

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _safe_sign(x: Any) -> int:
    try:
        v = float(x)
    except Exception:
        return 0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _run_page_vars(path: Path) -> dict[str, Any]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        vars_dict = runpy.run_path(str(path))
    return vars_dict


def _config_checks() -> tuple[float, dict[str, Any], list[str]]:
    settings = load_regime_settings()
    blend = settings.get("blend", {})
    global_f = settings.get("global_factors", {})
    macro = settings.get("macro_factors", {})
    liq = settings.get("liquidity_factors", {})
    risk = settings.get("risk_factors", {})

    checks: dict[str, bool] = {}
    hard_fail: list[str] = []

    gw = float(blend.get("global_weight", 0.0))
    mw = float(blend.get("macro_weight", 0.0))
    lw = float(blend.get("liquidity_weight", 0.0))
    rw = float(blend.get("risk_weight", 0.0))
    
    # Check if sum is close to 1.0 (some users might not perfectly sum to 1.0 but it should be close)
    total_w = gw + mw + lw + rw
    checks["blend_weights_valid"] = (0.95 <= total_w <= 1.05)

    checks["impulse_influence_valid"] = (0.0 <= float(blend.get("impulse_influence", 0.0)) <= 0.6)
    checks["max_factor_weight_valid"] = (0.01 <= float(blend.get("max_factor_weight", 0.0)) <= 0.5)

    caps = blend.get("group_caps", {})
    checks["group_caps_valid"] = all(0 < float(v) <= 1.0 for v in caps.values()) if isinstance(caps, dict) else False

    factor_ok = True
    for f in {**global_f, **macro, **liq, **risk}.values():
        try:
            w = float(f.get("weight", 0.0))
            if w < 0 or w > 1:
                factor_ok = False
                break
        except Exception:
            factor_ok = False
            break
    checks["factor_weights_valid"] = factor_ok

    if not checks["blend_weights_valid"]:
        hard_fail.append("blend_weights_invalid")
    if not checks["factor_weights_valid"]:
        hard_fail.append("factor_weights_invalid")

    score = 100.0 * (sum(1 for v in checks.values() if v) / max(1, len(checks)))
    detail = {
        "checks": checks,
        "global_weight": gw,
        "macro_weight": mw,
        "liquidity_weight": lw,
        "risk_weight": rw,
        "total_weight": total_w
    }
    return score, detail, hard_fail


def _macro_checks(page_vars: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    hard_fail: list[str] = []
    checks: dict[str, bool] = {}

    res = page_vars.get("main_regime_result", {}) or {}
    if not res:
        return 0.0, {"error": "main_regime_result not found"}, ["main_regime_result_missing"]

    pillar_scores = res.get("pillar_scores", {})
    final_score = float(res.get("final_score", 0.0))

    # Corrected Weighting: Pillar scores are already weighted by absolute weights
    recomputed_score = sum(pillar_scores.values())

    checks["final_score_formula"] = abs(final_score - recomputed_score) <= 1e-4
    checks["final_score_range"] = -1.0 <= final_score <= 1.0
    
    rows = res.get("rows", [])
    if rows:
        # Check pillar sums
        for p_name in ["Global", "Growth", "Liquidity", "Risk"]:
            p_rows = [r for r in rows if r.get("Pillar") == p_name]
            p_score_sum = sum(float(r.get("Score", 0.0)) * float(r.get("Weight", 0.0)) for r in p_rows)
            # Growth in rows matches Growth in pillar_scores
            p_key = p_name
            checks[f"{p_name}_sum_match"] = abs(p_score_sum - pillar_scores.get(p_key, 0.0)) <= 1e-4
    else:
        checks["factor_rows_present"] = False

    for k, ok in checks.items():
        if not ok and k in {"final_score_formula", "final_score_range"}:
            hard_fail.append(k)

    score = 100.0 * (sum(1 for v in checks.values() if v) / max(1, len(checks)))

    detail = {
        "checks": checks,
        "pillar_scores": pillar_scores,
        "recomputed_final_score": round(recomputed_score, 4),
        "actual_final_score": round(final_score, 4)
    }
    return score, detail, hard_fail


def _leading_checks(page_vars: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    hard_fail: list[str] = []
    checks: dict[str, bool] = {}

    daily = float(page_vars.get("daily_normalized", 0.0))
    directional = float(page_vars.get("directional_normalized", 0.0))
    daily_values = page_vars.get("daily_values", []) or []
    directional_values = page_vars.get("directional_values", []) or []
    factor_scores = page_vars.get("factor_scores", {}) or {}

    checks["daily_in_range"] = -1.0 <= daily <= 1.0
    checks["directional_in_range"] = -1.0 <= directional <= 1.0
    checks["daily_min_factors"] = len(daily_values) >= 3
    checks["directional_min_factors"] = len(directional_values) >= 3
    checks["factor_score_dict_nonempty"] = isinstance(factor_scores, dict) and len(factor_scores) > 0

    if not checks["factor_score_dict_nonempty"]:
        hard_fail.append("leading_factor_scores_empty")

    score = 100.0 * (sum(1 for v in checks.values() if v) / max(1, len(checks)))
    detail = {
        "checks": checks,
        "daily_impulse": daily,
        "directional_impulse": directional,
        "daily_factor_count": len(daily_values),
        "directional_factor_count": len(directional_values),
    }
    return score, detail, hard_fail


def _cross_page_parity(macro_vars: dict[str, Any], leading_vars: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    hard_fail: list[str] = []
    res = macro_vars.get("main_regime_result", {}) or {}
    macro_rows = res.get("rows", []) or []

    macro_map: dict[str, int] = {}
    for row in macro_rows:
        name = str(row.get("Factor", "")).strip().lower()
        # Macro rows use 'Score' column in the new engine
        macro_map[name] = _safe_sign(row.get("Score"))

    leading_map = {
        "dollar index": _safe_sign(leading_vars.get("dxy_score")),
        "us yield curve (10y-3m)": _safe_sign(leading_vars.get("curve_directional") if "curve_directional" in leading_vars else None),
        "copper/gold ratio": _safe_sign(leading_vars.get("cg_score")),
        "global credit spread": _safe_sign(leading_vars.get("credit_score")),
    }

    comparisons = []
    for k, lsgn in leading_map.items():
        msgn = macro_map.get(k)
        if msgn is None or lsgn == 0:
            continue
        comparisons.append(
            {
                "factor": k,
                "macro_directional_sign": msgn,
                "leading_directional_sign": lsgn,
                "match": bool(msgn == lsgn),
            }
        )

    if not comparisons:
        score = 100.0 # No comparisons possible, so no penalty
        detail = {"comparisons": [], "match_rate": None, "note": "No overlapping factors available for parity."}
        return score, detail, hard_fail

    match_rate = sum(1 for x in comparisons if x["match"]) / len(comparisons)
    score = 100.0 * match_rate
    detail = {"comparisons": comparisons, "match_rate": round(match_rate, 4)}
    return score, detail, hard_fail


import pandas as pd

def _playbook_checks() -> tuple[float, dict[str, Any], list[str]]:
    hard_fail: list[str] = []
    checks: dict[str, bool] = {}
    
    sig_file = ROOT / "data" / "snapshots" / "tradable_signals.parquet"
    if not sig_file.exists():
        return 0.0, {"error": "tradable_signals.parquet missing"}, ["playbook_file_missing"]
    
    try:
        df = pd.read_parquet(sig_file)
    except Exception as e:
        return 0.0, {"error": f"Failed to read parquet: {e}"}, ["playbook_read_error"]

    if df.empty:
        return 100.0, {"note": "No tradable signals found to audit."}, []

    ok_df = df[df["audit_reason"] == "OK"]
    
    # 1. Freshness (within 24h)
    latest_date = pd.to_datetime(df["date"].max())
    now = datetime.now()
    checks["snapshot_freshness"] = bool((now - latest_date).days <= 1)

    if ok_df.empty:
        # If freshness is OK but no signals are 'OK', we still pass freshness
        detail = {
            "checks": {k: bool(v) for k, v in checks.items()},
            "signal_count": int(len(df)),
            "ok_signal_count": 0,
            "note": "Snapshot found, but no signals passed scanner filters."
        }
        return 100.0 if checks["snapshot_freshness"] else 0.0, detail, []

    # 2. Risk Integrity (Entry > Stop for Longs in 'OK' set)
    # Our playbook is currently LONG only
    invalid_risk = ok_df[ok_df["suggested_entry"] <= ok_df["suggested_stop"]]
    checks["risk_integrity"] = bool(len(invalid_risk) == 0)

    # 3. Deterministic Targets (Check if R:R is ~2.0)
    # target = entry + 2 * (entry - stop)
    entry = ok_df["suggested_entry"]
    stop = ok_df["suggested_stop"]
    target = ok_df["target_price"]
    expected_target = entry + 2.0 * (entry - stop)
    # Allow small epsilon for float rounding
    target_errors = (target - expected_target).abs() > 0.01
    checks["target_determinism"] = bool(not target_errors.any())

    # 4. Position Sizing
    checks["position_sizing_present"] = bool((ok_df["position_size"] > 0).all())

    if not checks["risk_integrity"]:
        hard_fail.append("invalid_risk_in_ok_signals")

    score = 100.0 * (sum(1 for v in checks.values() if v) / max(1, len(checks)))
    detail = {
        "checks": {k: bool(v) for k, v in checks.items()},
        "total_signal_count": int(len(df)),
        "ok_signal_count": int(len(ok_df)),
        "latest_signal_date": str(latest_date.date()),
        "invalid_risk_in_ok_count": int(len(invalid_risk))
    }
    return score, detail, hard_fail


def main() -> int:
    macro_vars = _run_page_vars(ROOT / "pages" / "3_Macro_Risk.py")
    leading_vars = _run_page_vars(ROOT / "pages" / "4_Leading_Indicators.py")

    cfg_score, cfg_detail, cfg_fail = _config_checks()
    macro_score, macro_detail, macro_fail = _macro_checks(macro_vars)
    lead_score, lead_detail, lead_fail = _leading_checks(leading_vars)
    parity_score, parity_detail, parity_fail = _cross_page_parity(macro_vars, leading_vars)
    pb_score, pb_detail, pb_fail = _playbook_checks()

    # Weights adjusted to include Playbook (Config: 20%, Macro: 30%, Lead: 15%, Parity: 15%, Playbook: 20%)
    overall = (0.20 * cfg_score) + (0.30 * macro_score) + (0.15 * lead_score) + (0.15 * parity_score) + (0.20 * pb_score)
    hard_fails = cfg_fail + macro_fail + lead_fail + parity_fail + pb_fail

    if hard_fails:
        status = "FAIL"
    elif overall >= 95:
        status = "PASS"
    elif overall >= 80:
        status = "WARN"
    else:
        status = "FAIL"

    p_scores = macro_detail.get("pillar_scores", {})
    
    payload = {
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "overall_score": round(float(overall), 2),
        "hard_fail_reasons": hard_fails,
        "scores": {
            "config": round(float(cfg_score), 2),
            "global": round(float(p_scores.get("Global", 0.0) * 100), 2),
            "growth": round(float(p_scores.get("Growth", 0.0) * 100), 2),
            "liquidity": round(float(p_scores.get("Liquidity", 0.0) * 100), 2),
            "risk": round(float(p_scores.get("Risk", 0.0) * 100), 2),
            "leading": round(float(lead_score), 2),
            "cross_page_parity": round(float(parity_score), 2),
            "playbook": round(float(pb_score), 2),
        },
        "details": {
            "config": cfg_detail,
            "macro": macro_detail,
            "leading": lead_detail,
            "cross_page_parity": parity_detail,
            "playbook": pb_detail,
        },
    }

    latest = LOG_DIR / "scoring_audit_latest.json"
    dated = LOG_DIR / f"scoring_audit_{datetime.now().strftime('%Y%m%d')}.json"
    latest.write_text(json.dumps(payload, indent=2))
    dated.write_text(json.dumps(payload, indent=2))

    print(f"[ok] scoring audit written: {latest}")
    print(
        f"[ok] status={payload['status']} overall={payload['overall_score']:.2f} "
        f"config={payload['scores']['config']:.2f} global={payload['scores']['global']:.2f} "
        f"growth={payload['scores']['growth']:.2f} liquidity={payload['scores']['liquidity']:.2f} "
        f"risk={payload['scores']['risk']:.2f} leading={payload['scores']['leading']:.2f} "
        f"parity={payload['scores']['cross_page_parity']:.2f} playbook={payload['scores']['playbook']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
