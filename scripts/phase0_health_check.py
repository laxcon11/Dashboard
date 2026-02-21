"""
Phase 0 health checks for data sanctity and coverage.

Checks:
1) Local parquet availability + schema
2) Universe coverage in parquet
3) Duplicate symbol-date rows
4) Category coverage
5) Staleness summary (business-day age)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from NSE_Config import NIFTY_200, STOCK_CATEGORIES
from config import LOCAL_NSE_HISTORY_PATH, DATA_STALENESS_WARN_DAYS, DATA_STALENESS_ERROR_DAYS


def latest_business_day() -> pd.Timestamp:
    today = pd.Timestamp.today().normalize()
    if today.weekday() < 5:
        return today
    return today - pd.offsets.BDay(1)


def business_day_age(last_date: pd.Timestamp, ref: pd.Timestamp) -> int:
    bdays = pd.bdate_range(last_date.normalize(), ref.normalize())
    return max(0, len(bdays) - 1)


def main() -> None:
    path = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    print(f"[info] parquet_path={path}")
    if not path.exists():
        print("[error] local history parquet not found")
        return

    df = pd.read_parquet(path)
    cols = {c.lower(): c for c in df.columns}
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    missing_cols = sorted(required - set(cols.keys()))
    if missing_cols:
        print(f"[error] missing required columns: {missing_cols}")
        return

    work = pd.DataFrame(
        {
            "date": pd.to_datetime(df[cols["date"]], errors="coerce").dt.normalize(),
            "symbol": df[cols["symbol"]].astype(str).str.upper().str.strip(),
        }
    ).dropna(subset=["date", "symbol"])

    universe = set(NIFTY_200)
    available = set(work["symbol"].unique())
    missing = sorted(universe - available)
    extra = sorted(available - universe)

    print(f"[ok] total_rows={len(work)}")
    print(f"[ok] universe={len(universe)} available={len(available)} missing={len(missing)} extra={len(extra)}")
    if missing:
        print(f"[warn] missing_symbols_sample={missing[:20]}")
    if extra:
        print(f"[warn] extra_symbols_sample={extra[:20]}")

    dup_count = int(work.duplicated(subset=["symbol", "date"]).sum())
    if dup_count:
        print(f"[warn] duplicate_symbol_date_rows={dup_count}")
    else:
        print("[ok] duplicate_symbol_date_rows=0")

    cat_union = set().union(*STOCK_CATEGORIES.values())
    cat_missing = sorted(universe - cat_union)
    print(f"[ok] category_coverage_missing={len(cat_missing)}")
    if cat_missing:
        print(f"[warn] category_missing_sample={cat_missing[:20]}")

    latest = latest_business_day()
    last_dates = work.groupby("symbol")["date"].max()
    ages = last_dates.apply(lambda d: business_day_age(d, latest))
    warn_n = int((ages >= DATA_STALENESS_WARN_DAYS).sum())
    err_n = int((ages >= DATA_STALENESS_ERROR_DAYS).sum())
    print(
        f"[ok] staleness_warn_days={DATA_STALENESS_WARN_DAYS} staleness_error_days={DATA_STALENESS_ERROR_DAYS} "
        f"warn_count={warn_n} error_count={err_n}"
    )
    if err_n:
        top = ages.sort_values(ascending=False).head(20)
        print("[warn] stalest_symbols_top20=")
        for sym, age in top.items():
            print(f"  {sym}: {age} bdays")

    print(
        f"[ok] date_range={work['date'].min().date()} -> {work['date'].max().date()} "
        f"(latest_business_day={latest.date()})"
    )


if __name__ == "__main__":
    main()
