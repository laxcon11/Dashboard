"""
Compute daily Data Trust Score (integrity + parity + computation sanity).

Outputs:
- logs/data_trust_latest.json
- logs/data_trust_YYYYMMDD.json
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from NSE_Config import NIFTY_200
from analytics import round_percentages_sum_to_100
from config import DATA_STALENESS_ERROR_DAYS, LOCAL_NSE_HISTORY_PATH
from data_fetch import get_latest_bhavcopy_snapshot, load_latest_bhavcopy_prices
from regime_model import load_regime_settings
from trading_calendar import latest_nse_business_day, nse_business_day_age


LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def integrity_score(df: pd.DataFrame, universe: set[str]) -> tuple[float, dict]:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["symbol"] = work["symbol"].astype(str).str.upper().str.strip()
    work = work.dropna(subset=["date", "symbol"])

    total_rows = max(1, int(len(work)))
    available = set(work["symbol"].unique())
    missing = sorted(universe - available)
    dup = int(work.duplicated(subset=["symbol", "date"]).sum())
    ref = latest_nse_business_day()
    ages = work.groupby("symbol")["date"].max().apply(lambda d: (nse_business_day_age(pd.Timestamp(d), ref) or 0))
    stale_syms = set(ages[ages >= DATA_STALENESS_ERROR_DAYS].index)

    # Bhavcopy fallback: symbols stale in parquet but covered by a recent
    # Bhavcopy file should not be flagged.  This mirrors the runtime
    # behaviour of data_fetch.py which uses Bhavcopy as authoritative
    # source when Yahoo data is lagging.
    bhav_snap = get_latest_bhavcopy_snapshot()
    bhav_prices = bhav_snap.get("prices", {}) or {}
    if bhav_prices:
        bhav_covered = stale_syms & set(bhav_prices.keys())
        stale_syms -= bhav_covered
        # Also reduce missing count for symbols present in Bhavcopy
        missing = [s for s in missing if s not in bhav_prices]

    stale_err = len(stale_syms)
    missing_rate = len(missing) / max(1, len(universe))
    dup_rate = dup / total_rows
    stale_rate = stale_err / max(1, len(universe))

    score = 100.0 * (1.0 - clamp((0.5 * missing_rate) + (0.3 * stale_rate) + (0.2 * dup_rate), 0.0, 1.0))
    detail = {
        "missing_symbols": len(missing),
        "duplicate_rows": dup,
        "stale_error_symbols": stale_err,
        "bhavcopy_rescued": len(bhav_covered) if bhav_prices else 0,
        "missing_rate": missing_rate,
        "duplicate_rate": dup_rate,
        "stale_rate": stale_rate,
    }
    return score, detail


def parity_score(df: pd.DataFrame, universe: set[str]) -> tuple[float, dict]:
    _ = load_latest_bhavcopy_prices()
    snap = get_latest_bhavcopy_snapshot()
    prices = snap.get("prices", {}) or {}
    trade_date = snap.get("trade_date")
    if not prices:
        return 0.0, {
            "close_mismatch_count": len(universe),
            "volume_mismatch_count": len(universe),
            "close_mismatch_rate": 1.0,
            "volume_mismatch_rate": 1.0,
            "trade_date": None,
            "bhavcopy_path": snap.get("path"),
        }

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["symbol"] = work["symbol"].astype(str).str.upper().str.strip()
    if trade_date is None:
        day = work["date"].max()
    else:
        day = pd.to_datetime(trade_date).normalize()

    local = work[(work["date"] == day) & (work["symbol"].isin(universe))][["symbol", "close", "volume"]].copy()
    local = local.rename(columns={"close": "close_local", "volume": "vol_local"})

    rows = []
    for s in sorted(universe):
        row = prices.get(s)
        if not row:
            continue
        close_b, _prev_b, vol_b, _, _, _ = row
        rows.append({"symbol": s, "close_bhav": float(close_b), "vol_bhav": float(vol_b or 0.0)})
    bh = pd.DataFrame(rows)
    merged = local.merge(bh, on="symbol", how="outer")
    merged["close_diff_pct"] = ((merged["close_local"] - merged["close_bhav"]) / merged["close_bhav"] * 100.0).abs()
    merged["vol_diff_pct"] = ((merged["vol_local"] - merged["vol_bhav"]) / merged["vol_bhav"] * 100.0).abs()

    close_bad = int((merged["close_diff_pct"] > 0.2).sum())
    vol_bad = int((merged["vol_diff_pct"] > 20.0).sum())
    close_rate = close_bad / max(1, len(universe))
    vol_rate = vol_bad / max(1, len(universe))
    score = 100.0 * (1.0 - clamp((0.8 * close_rate) + (0.2 * vol_rate), 0.0, 1.0))
    detail = {
        "trade_date": str(day.date()) if pd.notna(day) else None,
        "bhavcopy_path": snap.get("path"),
        "close_mismatch_count": close_bad,
        "volume_mismatch_count": vol_bad,
        "close_mismatch_rate": close_rate,
        "volume_mismatch_rate": vol_rate,
    }
    return score, detail


def computation_score() -> tuple[float, dict]:
    checks: list[tuple[str, bool]] = []

    settings = load_regime_settings()
    blend = settings.get("blend", {})
    macro = settings.get("macro_factors", {})
    liq = settings.get("liquidity_factors", {})

    mw = float(blend.get("macro_weight", 0.0))
    lw = float(blend.get("liquidity_weight", 0.0))
    checks.append(("macro_liquidity_weight_range", (0 <= mw <= 1 and 0 <= lw <= 1 and (mw + lw) > 0)))

    fw = float(blend.get("fast_weight", 0.0))
    sw = float(blend.get("slow_weight", 0.0))
    checks.append(("fast_slow_weight_valid", (0 <= fw <= 1 and 0 <= sw <= 1 and (fw + sw) > 0)))

    max_w = float(blend.get("max_factor_weight", 0.0))
    checks.append(("max_factor_weight_valid", (0.01 <= max_w <= 0.5)))

    caps = blend.get("group_caps", {})
    checks.append(("group_caps_valid", all((0 < float(v) <= 1.0) for v in caps.values())))

    all_f = {**macro, **liq}
    fac_ok = True
    for f in all_f.values():
        w = float(f.get("weight", 0.0))
        if w < 0 or w > 1:
            fac_ok = False
            break
    checks.append(("factor_weights_valid", fac_ok))

    # Probability sum invariance.
    prob_ok = True
    for _ in range(200):
        vals = [random.random(), random.random(), random.random()]
        s = sum(vals) or 1.0
        vals = [v / s for v in vals]
        out = round_percentages_sum_to_100(vals)
        if sum(out) != 100:
            prob_ok = False
            break
    checks.append(("probability_sum_rule", prob_ok))

    # Snapshot consistency check (if EOD snapshot exists).
    snap_files = sorted((Path("data/snapshots")).glob("eod_*.json"))
    if snap_files:
        try:
            payload = json.loads(snap_files[-1].read_text())
            snap_ok = (
                payload.get("regime") is not None
                and isinstance(payload.get("regime_score"), (int, float))
                and isinstance(payload.get("breadth", {}), dict)
            )
        except Exception:
            snap_ok = False
        checks.append(("eod_snapshot_consistency", snap_ok))
    else:
        checks.append(("eod_snapshot_consistency", True))

    failed = [name for name, ok in checks if not ok]
    score = max(0.0, 100.0 - (len(failed) * 12.5))
    detail = {
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "probability_sum_check_passed": prob_ok,
    }
    return score, detail


def main() -> int:
    p = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    if not p.exists():
        print(f"[error] parquet not found: {p}")
        return 1
    df = pd.read_parquet(p)
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    cols = {c.lower() for c in df.columns}
    if not required.issubset(cols):
        print("[error] parquet schema invalid")
        return 1

    universe = set(NIFTY_200)
    integrity, integ_d = integrity_score(df, universe)
    parity, parity_d = parity_score(df, universe)
    compute, comp_d = computation_score()
    trust = (0.4 * integrity) + (0.4 * parity) + (0.2 * compute)

    # Hard-fail rules.  Rate-based so a handful of illiquid / recently
    # changed symbols don't force FAIL on an otherwise 99+ trust score.
    hard_fail_reasons = []
    missing_rate = integ_d["missing_rate"]
    stale_rate = integ_d["stale_rate"]
    if missing_rate > 0.05:                          # >5 % universe missing
        hard_fail_reasons.append("missing_symbols_gt_5pct")
    if stale_rate > 0.05:                            # >5 % universe stale
        hard_fail_reasons.append("stale_error_symbols_gt_5pct")
    if parity_d["close_mismatch_rate"] > 0.02:       # >2 % close mismatches
        hard_fail_reasons.append("close_mismatch_rate_gt_2pct")
    if not comp_d["probability_sum_check_passed"]:
        hard_fail_reasons.append("probability_sum_check_failed")

    if hard_fail_reasons or trust < 85:
        status = "FAIL"
    elif trust < 95:
        status = "WARN"
    else:
        status = "PASS"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "trust_score": round(float(trust), 2),
        "integrity_score": round(float(integrity), 2),
        "parity_score": round(float(parity), 2),
        "computation_score": round(float(compute), 2),
        "hard_fail_reasons": hard_fail_reasons,
        "integrity": integ_d,
        "parity": parity_d,
        "computation": comp_d,
    }

    latest = LOG_DIR / "data_trust_latest.json"
    dated = LOG_DIR / f"data_trust_{datetime.now().strftime('%Y%m%d')}.json"
    latest.write_text(json.dumps(payload, indent=2))
    dated.write_text(json.dumps(payload, indent=2))

    print(f"[ok] data trust written: {latest}")
    print(
        f"[ok] status={payload['status']} trust={payload['trust_score']:.2f} "
        f"integrity={payload['integrity_score']:.2f} parity={payload['parity_score']:.2f} "
        f"compute={payload['computation_score']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
