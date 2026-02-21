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
    macro = settings.get("macro_factors", {})
    liq = settings.get("liquidity_factors", {})

    checks: dict[str, bool] = {}
    hard_fail: list[str] = []

    mw = float(blend.get("macro_weight", 0.0))
    lw = float(blend.get("liquidity_weight", 0.0))
    checks["blend_weights_valid"] = (0.0 <= mw <= 1.0 and 0.0 <= lw <= 1.0 and (mw + lw) > 0)

    fw = float(blend.get("fast_weight", 0.0))
    sw = float(blend.get("slow_weight", 0.0))
    checks["fast_slow_weights_valid"] = (0.0 <= fw <= 1.0 and 0.0 <= sw <= 1.0 and (fw + sw) > 0)

    impulse_influence = float(blend.get("impulse_influence", 0.0))
    checks["impulse_influence_valid"] = (0.0 <= impulse_influence <= 0.6)

    max_w = float(blend.get("max_factor_weight", 0.0))
    checks["max_factor_weight_valid"] = (0.01 <= max_w <= 0.5)

    caps = blend.get("group_caps", {})
    checks["group_caps_valid"] = all(0 < float(v) <= 1.0 for v in caps.values()) if isinstance(caps, dict) else False

    factor_ok = True
    for f in {**macro, **liq}.values():
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
        "macro_weight": mw,
        "liquidity_weight": lw,
        "fast_weight": fw,
        "slow_weight": sw,
        "impulse_influence": impulse_influence,
        "max_factor_weight": max_w,
    }
    return score, detail, hard_fail


def _macro_checks(page_vars: dict[str, Any]) -> tuple[float, dict[str, Any], list[str]]:
    hard_fail: list[str] = []
    checks: dict[str, bool] = {}

    mr = page_vars.get("macro_result", {}) or {}
    lr = page_vars.get("liquidity_result", {}) or {}

    macro_dir = float(mr.get("directional_norm", 0.0))
    liq_dir = float(lr.get("directional_norm", 0.0))
    macro_imp = float(mr.get("impulse_norm", 0.0))
    liq_imp = float(lr.get("impulse_norm", 0.0))

    mw = float(page_vars.get("macro_weight", 0.0))
    lw = float(page_vars.get("liquidity_weight", 0.0))
    ii = float(page_vars.get("impulse_influence", 0.0))

    final_dir = float(page_vars.get("final_directional", 0.0))
    final_imp = float(page_vars.get("final_impulse", 0.0))
    final_score = float(page_vars.get("final_score", 0.0))

    recomputed_dir = (macro_dir * mw) + (liq_dir * lw)
    recomputed_imp = (macro_imp * mw) + (liq_imp * lw)
    recomputed_score = (recomputed_dir * (1.0 - ii)) + (recomputed_imp * ii)

    checks["final_directional_formula"] = abs(final_dir - recomputed_dir) <= 1e-6
    checks["final_impulse_formula"] = abs(final_imp - recomputed_imp) <= 1e-6
    checks["final_score_formula"] = abs(final_score - recomputed_score) <= 1e-6

    probs = [
        float(page_vars.get("p_risk_on", 0.0)),
        float(page_vars.get("p_neutral", 0.0)),
        float(page_vars.get("p_risk_off", 0.0)),
    ]
    checks["probability_sum_1"] = abs(sum(probs) - 1.0) <= 1e-6

    for key, result in (("macro", mr), ("liquidity", lr)):
        rows = result.get("rows", []) if isinstance(result, dict) else []
        if rows:
            eff_sum = sum(float(r.get("Eff W", 0.0)) for r in rows if r.get("Eff W") is not None)
            checks[f"{key}_eff_weight_sum_close_1"] = abs(eff_sum - 1.0) <= 0.03
        else:
            checks[f"{key}_eff_weight_sum_close_1"] = False

    checks["final_directional_range"] = -1.0 <= final_dir <= 1.0
    checks["final_score_range"] = -1.0 <= final_score <= 1.0

    for k, ok in checks.items():
        if not ok and k in {"final_directional_formula", "final_score_formula", "probability_sum_1"}:
            hard_fail.append(k)

    score = 100.0 * (sum(1 for v in checks.values() if v) / max(1, len(checks)))

    sensitivity = {
        "final_directional": round(final_dir, 6),
        "final_impulse": round(final_imp, 6),
        "final_score": round(final_score, 6),
    }

    try:
        # weight sensitivity (+/- 10% relative on macro weight, renormalized with liquidity)
        up_mw = _clamp(mw * 1.10, 0.01, 0.99)
        up_lw = 1.0 - up_mw
        dn_mw = _clamp(mw * 0.90, 0.01, 0.99)
        dn_lw = 1.0 - dn_mw
        s_up = ((macro_dir * up_mw) + (liq_dir * up_lw))
        s_dn = ((macro_dir * dn_mw) + (liq_dir * dn_lw))
        sensitivity["dir_macro_weight_up10pct"] = round(float(s_up), 6)
        sensitivity["dir_macro_weight_dn10pct"] = round(float(s_dn), 6)
        sensitivity["dir_shift_abs_max"] = round(max(abs(s_up - final_dir), abs(s_dn - final_dir)), 6)
    except Exception:
        pass

    detail = {
        "checks": checks,
        "macro_directional": macro_dir,
        "liquidity_directional": liq_dir,
        "recomputed_final_directional": recomputed_dir,
        "recomputed_final_score": recomputed_score,
        "sensitivity": sensitivity,
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
    macro_rows = (macro_vars.get("macro_result", {}) or {}).get("rows", []) or []

    macro_map: dict[str, int] = {}
    for row in macro_rows:
        name = str(row.get("Factor", "")).strip().lower()
        macro_map[name] = _safe_sign(row.get("Slow"))

    leading_map = {
        "dollar index": _safe_sign(leading_vars.get("dxy_score")),
        "us 10y yield": _safe_sign(leading_vars.get("yield_score")),
        "copper/gold ratio": _safe_sign(leading_vars.get("cg_score")),
        "credit spread (hyg/lqd)": _safe_sign(leading_vars.get("credit_score")),
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
        score = 70.0
        detail = {"comparisons": [], "match_rate": None, "note": "No overlapping factors available for parity."}
        return score, detail, hard_fail

    match_rate = sum(1 for x in comparisons if x["match"]) / len(comparisons)
    score = 100.0 * match_rate
    detail = {"comparisons": comparisons, "match_rate": round(match_rate, 4)}
    return score, detail, hard_fail


def main() -> int:
    macro_vars = _run_page_vars(ROOT / "pages" / "3_Macro_Risk.py")
    leading_vars = _run_page_vars(ROOT / "pages" / "4_Leading_Indicators.py")

    cfg_score, cfg_detail, cfg_fail = _config_checks()
    macro_score, macro_detail, macro_fail = _macro_checks(macro_vars)
    lead_score, lead_detail, lead_fail = _leading_checks(leading_vars)
    parity_score, parity_detail, parity_fail = _cross_page_parity(macro_vars, leading_vars)

    overall = (0.30 * cfg_score) + (0.35 * macro_score) + (0.20 * lead_score) + (0.15 * parity_score)
    hard_fails = cfg_fail + macro_fail + lead_fail + parity_fail

    if hard_fails:
        status = "FAIL"
    elif overall >= 95:
        status = "PASS"
    elif overall >= 85:
        status = "WARN"
    else:
        status = "FAIL"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "overall_score": round(float(overall), 2),
        "hard_fail_reasons": hard_fails,
        "scores": {
            "config": round(float(cfg_score), 2),
            "macro": round(float(macro_score), 2),
            "leading": round(float(lead_score), 2),
            "cross_page_parity": round(float(parity_score), 2),
        },
        "details": {
            "config": cfg_detail,
            "macro": macro_detail,
            "leading": lead_detail,
            "cross_page_parity": parity_detail,
        },
    }

    latest = LOG_DIR / "scoring_audit_latest.json"
    dated = LOG_DIR / f"scoring_audit_{datetime.now().strftime('%Y%m%d')}.json"
    latest.write_text(json.dumps(payload, indent=2))
    dated.write_text(json.dumps(payload, indent=2))

    print(f"[ok] scoring audit written: {latest}")
    print(
        f"[ok] status={payload['status']} overall={payload['overall_score']:.2f} "
        f"config={payload['scores']['config']:.2f} macro={payload['scores']['macro']:.2f} "
        f"leading={payload['scores']['leading']:.2f} parity={payload['scores']['cross_page_parity']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
