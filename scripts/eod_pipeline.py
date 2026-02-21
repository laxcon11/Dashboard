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
from data_fetch import batch_download


SNAPSHOT_DIR = Path("data/snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def trend_signal(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "Close" not in df.columns:
        return 0
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 50:
        return 0
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    cur = close.iloc[-1]
    if cur > ema20 > ema50:
        return 1
    if cur < ema20 < ema50:
        return -1
    return 0


def main() -> int:
    watchlists = wm.load_watchlists()
    symbols = sorted(set(sum((v for v in watchlists.values() if isinstance(v, list)), [])))
    core_symbols = ["^NSEI", "^NSEBANK"] + symbols[:250]  # keep bounded for EOD speed

    data = batch_download(sorted(set(core_symbols)), period="3mo")
    nifty = data.get("^NSEI")
    bank = data.get("^NSEBANK")

    # Breadth on top-100 universe for stable snapshot
    breadth_syms = symbols[:100]
    advances = 0
    declines = 0
    for s in breadth_syms:
        df = data.get(s)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        c = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(c) < 2:
            continue
        chg = ((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100) if c.iloc[-2] != 0 else 0.0
        if chg > 0.1:
            advances += 1
        elif chg < -0.1:
            declines += 1

    breadth_ratio = (advances / declines) if declines > 0 else float(advances)
    regime_score = trend_signal(nifty) + trend_signal(bank)
    if regime_score >= 1 and breadth_ratio >= 1.1:
        regime = "🟢 Risk On"
    elif regime_score <= -1 and breadth_ratio <= 0.9:
        regime = "🔴 Risk Off"
    else:
        regime = "🟡 Neutral"

    # Simple trigger list: biggest daily movers
    movers = []
    for s in symbols[:200]:
        df = data.get(s)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        c = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(c) < 2 or c.iloc[-2] == 0:
            continue
        chg = (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100
        movers.append({"symbol": s, "change_pct": float(chg)})
    top_movers = sorted(movers, key=lambda x: abs(x["change_pct"]), reverse=True)[:15]

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "regime": regime,
        "regime_score": regime_score,
        "breadth": {"advances": advances, "declines": declines, "ratio": breadth_ratio},
        "top_movers": top_movers,
        "watchlists_scanned": len(watchlists),
        "symbols_scanned": len(symbols),
    }

    fname = SNAPSHOT_DIR / f"eod_{datetime.now().strftime('%Y%m%d')}.json"
    fname.write_text(json.dumps(snapshot, indent=2))
    print(f"Saved EOD snapshot: {fname}")

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
