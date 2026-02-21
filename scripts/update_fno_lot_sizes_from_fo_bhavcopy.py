from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def read_fo(path: Path) -> pd.DataFrame:
    p = str(path)
    if p.lower().endswith('.zip'):
        return pd.read_csv(path, compression='zip')
    return pd.read_csv(path)


def next_month_start(ts: pd.Timestamp) -> pd.Timestamp:
    m = ts.month + 1
    y = ts.year
    if m == 13:
        m = 1
        y += 1
    return pd.Timestamp(year=y, month=m, day=1)


def build_lot_map(df: pd.DataFrame) -> tuple[dict[str, int], str]:
    required = {"TradDt", "TckrSymb", "XpryDt", "NewBrdLotQty", "FinInstrmTp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    work = df.copy()
    work["TradDt"] = pd.to_datetime(work["TradDt"], errors="coerce")
    work["XpryDt"] = pd.to_datetime(work["XpryDt"], errors="coerce")
    work["TckrSymb"] = work["TckrSymb"].astype(str).str.upper().str.strip()
    work["NewBrdLotQty"] = pd.to_numeric(work["NewBrdLotQty"], errors="coerce")
    work["FinInstrmTp"] = work["FinInstrmTp"].astype(str).str.upper().str.strip()

    work = work.dropna(subset=["TradDt", "XpryDt", "TckrSymb", "NewBrdLotQty"]).copy()
    work = work[work["NewBrdLotQty"] > 0].copy()
    work = work[work["FinInstrmTp"].isin(["STF", "STO", "FUTSTK", "OPTSTK"])].copy()

    if work.empty:
        return {}, ""

    trade_date = pd.Timestamp(work["TradDt"].max()).normalize()
    nm = next_month_start(trade_date)

    lot_map: dict[str, int] = {}
    for sym, g in work.groupby("TckrSymb", dropna=False):
        g = g.copy()
        # Rule 1: pick next month contract rows
        g_nm = g[(g["XpryDt"].dt.year == nm.year) & (g["XpryDt"].dt.month == nm.month)]
        if g_nm.empty:
            # Rule 2: nearest future expiry rows
            g_future = g[g["XpryDt"] >= trade_date].sort_values("XpryDt")
            if g_future.empty:
                continue
            nearest_exp = g_future["XpryDt"].iloc[0]
            g_sel = g_future[g_future["XpryDt"] == nearest_exp]
        else:
            # If multiple next-month expiries exist, use earliest next-month expiry
            nearest_exp = g_nm["XpryDt"].min()
            g_sel = g_nm[g_nm["XpryDt"] == nearest_exp]

        # Resolve conflicts by mode lot size within selected bucket.
        vc = g_sel["NewBrdLotQty"].round().astype(int).value_counts()
        if vc.empty:
            continue
        lot = int(vc.index[0])
        lot_map[f"{sym}.NS"] = lot

    return lot_map, str(trade_date.date())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build F&O lot-size map from NSE FO Bhavcopy CSV/ZIP")
    parser.add_argument(
        "--file",
        default="/Users/laxmanacharya/Downloads/BhavCopy_NSE_FO_0_0_0_20260220_F_0000.csv",
        help="Path to NSE FO bhavcopy CSV or CSV.ZIP",
    )
    parser.add_argument("--out", default="notes/fno_lot_sizes.json", help="Output JSON path")
    args = parser.parse_args()

    src = Path(args.file).expanduser()
    if not src.exists() and src.with_suffix(src.suffix + ".zip").exists():
        src = src.with_suffix(src.suffix + ".zip")
    if not src.exists():
        print(f"[error] file not found: {src}")
        return 1

    df = read_fo(src)
    lot_map, trade_date = build_lot_map(df)
    if not lot_map:
        print("[error] no lot sizes parsed")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(src),
        "trade_date": trade_date,
        "rule": "Prefer next-month expiry; fallback nearest future expiry; conflict resolved by mode lot size.",
        "symbols": len(lot_map),
        "lot_sizes": dict(sorted(lot_map.items())),
    }
    out.write_text(json.dumps(payload, indent=2))

    sample = list(payload["lot_sizes"].items())[:10]
    print(f"[ok] wrote lot map: {out}")
    print(f"[ok] symbols={len(lot_map)} sample={sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
