"""
Phase 5 EOD pipeline:
- refresh key datasets
- compute lightweight regime/swing snapshot
- persist snapshot JSON for alerting and audit
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import watchlist_manager as wm
from data_fetch import batch_download, fetch_india_vix
from regime_classification import check_crisis_overrides, REGIMES
from NSE_Config import NIFTY_200, PRESET_WATCHLISTS
from regime_state import load_regime_snapshot, append_regime_history
from prediction_integrity import engine


SNAPSHOT_DIR = Path("data/snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def trend_signal(df: pd.DataFrame | None) -> float:
    if df is None or df.empty or "Close" not in df.columns:
        return 0.0
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 50:
        return 0.0
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    cur = close.iloc[-1]
    if cur > ema20 > ema50:
        return 1.0
    if cur > ema50 and cur <= ema20:
        return 0.5  # Short-term pullback in uptrend
    if cur < ema20 < ema50:
        return -1.0
    if cur < ema50 and cur >= ema20:
        return -0.5 # Short-term bounce in downtrend
    return 0.0


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if df is None or df.empty or len(df) < period + 1:
        return 0.0
    try:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        return float(atr)
    except Exception:
        return 0.0


def main() -> int:
    watchlists = wm.load_watchlists()
    
    # 1. CORE UNIVERSE: NIFTY 200 + Top 20 Market Cap (removes alphabetical bias)
    def _strip(s: str) -> str: return s[:-3] if s.endswith(".NS") else s
    
    top20 = [_strip(s) for s in PRESET_WATCHLISTS.get("Top 20 by Market Cap", [])]
    nifty200 = [_strip(s) for s in NIFTY_200]
    
    # Combine and ensure ^NSEI and ^NSEBANK are present
    core_symbols = sorted(list(set(["^NSEI", "^NSEBANK"] + top20 + nifty200)))

    data = batch_download(core_symbols, period="3mo")
    nifty = data.get("^NSEI")
    bank = data.get("^NSEBANK")

    # 2. BREADTH & MOVERS: Scan the core universe (excluding indices)
    scan_syms = [s for s in core_symbols if not s.startswith("^")]
    
    advances = 0
    declines = 0
    unchanged = 0
    threshold = 0.10  # 0.1% minimum move
    movers = []
    
    for s in scan_syms:
        df = data.get(s)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        c = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(c) < 2 or c.iloc[-2] == 0:
            continue
            
        chg = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100)
        movers.append({"symbol": s, "change_pct": float(chg)})
        
        if chg > threshold:
            advances += 1
        elif chg < -threshold:
            declines += 1
        else:
            unchanged += 1

    # Coverage quality check
    coverage = advances + declines + unchanged
    expected = len(scan_syms)

    if coverage < expected * 0.6:
        print(f"[warn] Breadth coverage low: {coverage}/{expected}")
    
    # Load macro state live from institutional engine
    try:
        from institutional_engine import generate_institutional_regime
        macro_snap_raw = generate_institutional_regime(offset=0)
        from datetime import datetime
        macro_snap = {
            "final_score": macro_snap_raw.get("final_score", 0.0),
            "regime_label": macro_snap_raw.get("regime", "SELECTIVE"),
            "confidence": macro_snap_raw.get("confidence"),
            "probabilities": macro_snap_raw.get("probabilities", {}),
            "pillar_scores": macro_snap_raw.get("pillar_scores", {}),
            "updated_at": datetime.now().isoformat()
        }
        print(f"Generated institutional regime dynamically: score={macro_snap['final_score']:.3f}, regime={macro_snap['regime_label']}")
    except Exception as exc:
        print(f"[warn] Failed to generate institutional regime: {exc}")
        macro_snap = load_regime_snapshot()

    # 3. V4 Prediction Engine Logic (Hierarchical)
    total_ad = advances + declines + unchanged
    regime_score = trend_signal(nifty) + trend_signal(bank)
    
    # Construct transient snapshot for V4 evaluation
    temp_snap = {
        "regime": "SELECTIVE", # Default for lookup
        "regime_score": regime_score,
        "breadth": {"ratio": (advances - declines) / total_ad if total_ad > 0 else 0.0},
        "macro_context": {
            "score": macro_snap.get("final_score", 0.0),
            "updated_at": macro_snap.get("updated_at")
        },
        "indicators": {
            "ATR_14": calculate_atr(nifty),
            "Close": float(nifty["Close"].iloc[-1]) if nifty is not None and not nifty.empty else 0.0
        },
        "price": float(nifty["Close"].iloc[-1]) if nifty is not None and not nifty.empty else 0.0
    }
    
    # 2.5 Fetch India VIX for Crisis Overrides
    from data_fetch import fetch_india_vix
    from regime_classification import check_crisis_overrides, REGIMES
    vix_price, _ = fetch_india_vix()
    is_crisis, crisis_reason = check_crisis_overrides(vix_price, 0.0)

    # ------------------------------------------------------------------
    # 3. Classify Regime (with Stability Filter)
    # ------------------------------------------------------------------
    from regime_classification import apply_stability_filters
    
    # Use V4 Hierarchical Score
    v4_score = engine._score_from_snapshot(temp_snap)
    
    # Raw classification first
    if v4_score >= 6.5:
        raw_regime = "Risk On"
    elif v4_score <= -6.5:
        raw_regime = "Crisis"
    elif v4_score <= -3.0:
        raw_regime = "Defensive"
    else:
        raw_regime = "Selective"

    # Force Crisis if override active
    if is_crisis:
        raw_regime = REGIMES["CRISIS"]

    # Apply Stability Filter (Persistence/Momentum)
    settings = {"persistence_days": 3, "momentum_threshold": 0.05}
    st_result = apply_stability_filters(v4_score, raw_regime, settings)
    
    regime_label = st_result["current_regime"]
    final_score = st_result["current_score"]

    top_movers = sorted(movers, key=lambda x: abs(x["change_pct"]), reverse=True)[:15]

    # 4. Integrate Macro Risk Context (Already loaded for V4 evaluation)
    macro_context = {
        "score": macro_snap.get("final_score", 0.0),
        "label": macro_snap.get("regime_label", "Unknown"),
        "updated_at": macro_snap.get("updated_at")
    }

    # 5. Fix/Finalize History from Bhavcopy (The "Truth" step)
    try:
        print("Finalizing history from Bhavcopy...")
        # repair_parity_direct.py specifically targets the latest Bhavcopy and synchronizes parity.
        rc_repair = subprocess.call([sys.executable, "scripts/repair_parity_direct.py"], cwd=str(ROOT))
        if rc_repair != 0:
            print("[warn] bhavcopy repair step returned non-zero")
    except Exception as exc:
        print(f"[warn] bhavcopy repair error: {exc}")

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "regime": regime_label,
        "regime_score": v4_score, # Store the V4 refined score
        "confidence": st_result.get("confidence", 50.0),
        "breadth": {"advances": advances, "declines": declines, "ratio": (advances - declines) / total_ad if total_ad > 0 else 0.0},
        "macro_context": macro_context,
        "top_movers": top_movers,
        "watchlists_scanned": len(watchlists),
        "symbols_scanned": len(scan_syms),
    }

    fname = SNAPSHOT_DIR / f"eod_{datetime.now().strftime('%Y%m%d')}.json"
    fname.write_text(json.dumps(snapshot, indent=2))
    print(f"Saved EOD snapshot: {fname}")

    # Persist regime history for the 90D timeline
    try:
        append_regime_history({
            "regime_label": macro_context.get("label", "Selective"),
            "final_score": macro_context.get("score", 0.0),
            "probabilities": macro_snap.get("probabilities", {}),
            "pillar_scores": macro_snap.get("pillar_scores", {}),
            "confidence": macro_snap.get("confidence"),
        })
        print("Persisted regime history entry.")
    except Exception as exc:
        print(f"[warn] regime history persist error: {exc}")

    # Run parity report (non-fatal if it fails).
    try:
        rc = subprocess.call([sys.executable, "scripts/bhavcopy_parity_report.py"], cwd=str(ROOT))
        if rc != 0:
            print("[warn] bhavcopy parity report failed")
    except Exception as exc:
        print(f"[warn] bhavcopy parity report error: {exc}")

    # Compute unified trust score (non-fatal).
    try:
        rc = subprocess.call([sys.executable, "scripts/data_trust_score.py"], cwd=str(ROOT))
        if rc != 0:
            print("[warn] data trust score generation failed")
    except Exception as exc:
        print(f"[warn] data trust score error: {exc}")

    # Run prediction integrity cycle (non-fatal).
    try:
        rc = subprocess.call([sys.executable, "scripts/prediction_integrity_cycle.py"], cwd=str(ROOT))
        if rc != 0:
            print("[warn] prediction integrity cycle failed")
    except Exception as exc:
        print(f"[warn] prediction integrity cycle error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
