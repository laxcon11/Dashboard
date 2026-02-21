"""
Repair stale NSE parquet rows directly from latest Bhavcopy.

Usage:
  .venv/bin/python scripts/repair_stale_from_bhavcopy.py
  .venv/bin/python scripts/repair_stale_from_bhavcopy.py --symbols STLTECH.NS,LGEINDIA.NS
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from NSE_Config import NIFTY_200
from config import DATA_STALENESS_ERROR_DAYS, LOCAL_NSE_HISTORY_PATH
from data_fetch import load_latest_bhavcopy_prices


def latest_business_day() -> pd.Timestamp:
    today = pd.Timestamp.today().normalize()
    if today.weekday() < 5:
        return today
    return today - pd.offsets.BDay(1)


def business_day_age(last_date: pd.Timestamp, ref: pd.Timestamp) -> int:
    bdays = pd.bdate_range(last_date.normalize(), ref.normalize())
    return max(0, len(bdays) - 1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Repair stale local NSE rows from Bhavcopy.")
    p.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbol list. If empty, auto-detect stale symbols from parquet.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    parquet_path = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    if not parquet_path.exists():
        print(f"[error] parquet not found: {parquet_path}")
        return 1

    df = pd.read_parquet(parquet_path)
    cols = {c.lower(): c for c in df.columns}
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    missing_cols = sorted(required - set(cols.keys()))
    if missing_cols:
        print(f"[error] missing required columns: {missing_cols}")
        return 1

    work = pd.DataFrame(
        {
            "date": pd.to_datetime(df[cols["date"]], errors="coerce").dt.normalize(),
            "symbol": df[cols["symbol"]].astype(str).str.upper().str.strip(),
            "open": pd.to_numeric(df[cols["open"]], errors="coerce"),
            "high": pd.to_numeric(df[cols["high"]], errors="coerce"),
            "low": pd.to_numeric(df[cols["low"]], errors="coerce"),
            "close": pd.to_numeric(df[cols["close"]], errors="coerce"),
            "volume": pd.to_numeric(df[cols["volume"]], errors="coerce").fillna(0).astype("int64"),
        }
    ).dropna(subset=["date", "symbol", "close"])

    latest_bd = latest_business_day()

    if args.symbols.strip():
        target_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        universe = set(NIFTY_200)
        last_dates = work.groupby("symbol")["date"].max()
        ages = last_dates.apply(lambda d: business_day_age(d, latest_bd))
        stale = ages[ages >= DATA_STALENESS_ERROR_DAYS].index.tolist()
        target_symbols = [s for s in stale if s in universe]

    if not target_symbols:
        print("[ok] no stale symbols to repair")
        return 0

    bhav = load_latest_bhavcopy_prices()
    if not bhav:
        print("[error] no bhavcopy prices available")
        return 1

    rows = []
    for sym in target_symbols:
        if not sym.endswith(".NS"):
            continue
        row = bhav.get(sym)
        if not row:
            continue
        close, prev_close, vol = row
        prev_close = prev_close if prev_close is not None and prev_close > 0 else close
        prev_day = latest_bd - pd.offsets.BDay(1)
        # two-row shape keeps downstream delta logic safe
        rows.append(
            {
                "date": pd.to_datetime(prev_day).normalize(),
                "symbol": sym,
                "open": float(prev_close),
                "high": float(prev_close),
                "low": float(prev_close),
                "close": float(prev_close),
                "volume": 0,
            }
        )
        rows.append(
            {
                "date": pd.to_datetime(latest_bd).normalize(),
                "symbol": sym,
                "open": float(close),
                "high": float(close),
                "low": float(close),
                "close": float(close),
                "volume": int(max(0, vol or 0)),
            }
        )

    if not rows:
        print("[warn] no matching stale symbols found in latest bhavcopy")
        return 0

    patch_df = pd.DataFrame(rows)
    merged = pd.concat([work, patch_df], ignore_index=True)
    merged = merged.sort_values(["symbol", "date"]).drop_duplicates(subset=["symbol", "date"], keep="last")
    merged.to_parquet(parquet_path, index=False)

    repaired = sorted(set(patch_df["symbol"]))
    print(f"[ok] repaired {len(repaired)} symbols from bhavcopy")
    print("[ok] symbols:", ", ".join(repaired))
    print(f"[ok] parquet updated: {parquet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
