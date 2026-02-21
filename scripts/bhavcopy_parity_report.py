"""
Daily parity report: local parquet vs latest Bhavcopy for NSE universe.

Outputs:
- logs/bhavcopy_parity_latest.json
- logs/bhavcopy_parity_<YYYYMMDD>.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from NSE_Config import NIFTY_200
from config import LOCAL_NSE_HISTORY_PATH
from data_fetch import get_latest_bhavcopy_snapshot, load_latest_bhavcopy_prices


LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    _ = load_latest_bhavcopy_prices()
    snap = get_latest_bhavcopy_snapshot()
    bhav_prices = snap.get("prices", {}) or {}
    bhav_date = snap.get("trade_date")
    bhav_path = snap.get("path")

    if not bhav_prices:
        print("[error] no bhavcopy data available")
        return 1

    p = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    if not p.exists():
        print(f"[error] parquet not found: {p}")
        return 1

    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    latest_day = pd.to_datetime(bhav_date).normalize() if bhav_date is not None else df["date"].max()
    local_day = df[df["date"] == latest_day][["symbol", "close", "volume"]].copy()
    local_day = local_day.rename(columns={"close": "close_local", "volume": "volume_local"})

    rows = []
    for symbol in sorted(set(NIFTY_200)):
        bh = bhav_prices.get(symbol)
        if not bh:
            continue
        close_b, prev_b, vol_b = bh
        rows.append(
            {
                "symbol": symbol,
                "close_bhav": float(close_b),
                "volume_bhav": float(vol_b or 0.0),
            }
        )
    bhav_df = pd.DataFrame(rows)

    merged = local_day.merge(bhav_df, on="symbol", how="outer")
    merged["close_local"] = pd.to_numeric(merged["close_local"], errors="coerce")
    merged["volume_local"] = pd.to_numeric(merged["volume_local"], errors="coerce")
    merged["close_bhav"] = pd.to_numeric(merged["close_bhav"], errors="coerce")
    merged["volume_bhav"] = pd.to_numeric(merged["volume_bhav"], errors="coerce")

    merged["close_diff_pct"] = ((merged["close_local"] - merged["close_bhav"]) / merged["close_bhav"] * 100.0).abs()
    merged["volume_diff_pct"] = ((merged["volume_local"] - merged["volume_bhav"]) / merged["volume_bhav"] * 100.0).abs()

    close_bad = merged[merged["close_diff_pct"] > 0.2].copy()
    vol_bad = merged[merged["volume_diff_pct"] > 20.0].copy()

    close_top = (
        close_bad.sort_values("close_diff_pct", ascending=False)
        .head(25)[["symbol", "close_local", "close_bhav", "close_diff_pct"]]
        .to_dict(orient="records")
    )
    vol_top = (
        vol_bad.sort_values("volume_diff_pct", ascending=False)
        .head(25)[["symbol", "volume_local", "volume_bhav", "volume_diff_pct"]]
        .to_dict(orient="records")
    )

    report = {
        "generated_at": datetime.now().isoformat(),
        "bhavcopy_path": bhav_path,
        "trade_date": str(latest_day.date()) if pd.notna(latest_day) else None,
        "universe": len(set(NIFTY_200)),
        "local_rows_for_trade_date": int(len(local_day)),
        "close_mismatch_count_gt_0_2pct": int(len(close_bad)),
        "volume_mismatch_count_gt_20pct": int(len(vol_bad)),
        "close_mismatch_top": close_top,
        "volume_mismatch_top": vol_top,
    }

    latest_file = LOG_DIR / "bhavcopy_parity_latest.json"
    dated_file = LOG_DIR / f"bhavcopy_parity_{datetime.now().strftime('%Y%m%d')}.json"
    latest_file.write_text(json.dumps(report, indent=2))
    dated_file.write_text(json.dumps(report, indent=2))

    print(f"[ok] parity report written: {latest_file}")
    print(
        f"[ok] close_mismatch={report['close_mismatch_count_gt_0_2pct']} "
        f"volume_mismatch={report['volume_mismatch_count_gt_20pct']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
