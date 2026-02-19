"""
Build and refresh a 230-symbol NSE history parquet from a base parquet source.

Usage:
  .venv/bin/python scripts/build_nse230_history.py
  .venv/bin/python scripts/build_nse230_history.py --no-refresh
  .venv/bin/python scripts/build_nse230_history.py --source-parquet ~/Downloads/nse_eq_data.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import pandas as pd

from NSE_Config import NIFTY_200
from data_fetch import batch_download


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build NSE 230 history parquet and layer missing recent data.")
    parser.add_argument(
        "--source-parquet",
        default=str(Path("~/Downloads/nse_eq_data.parquet").expanduser()),
        help="Path to base parquet file with long history.",
    )
    parser.add_argument(
        "--output-parquet",
        default="data/nse_230_history.parquet",
        help="Destination parquet for project use.",
    )
    parser.add_argument(
        "--refresh",
        dest="refresh",
        action="store_true",
        default=True,
        help="Refresh missing recent rows from market data sources.",
    )
    parser.add_argument(
        "--no-refresh",
        dest="refresh",
        action="store_false",
        help="Only build from base parquet, skip online refresh.",
    )
    parser.add_argument(
        "--period",
        default="1mo",
        help="Yahoo period to use when refreshing recent rows.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=40,
        help="Batch size for refresh calls.",
    )
    return parser.parse_args()


def _normalize_base(df: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    lower_map = {c.lower(): c for c in df.columns}
    if not required.issubset(lower_map):
        missing = sorted(required - set(lower_map))
        raise ValueError(f"Base parquet missing required columns: {missing}")

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(df[lower_map["date"]], errors="coerce").dt.normalize(),
            "symbol": df[lower_map["symbol"]].astype(str).str.upper().str.strip(),
            "open": pd.to_numeric(df[lower_map["open"]], errors="coerce"),
            "high": pd.to_numeric(df[lower_map["high"]], errors="coerce"),
            "low": pd.to_numeric(df[lower_map["low"]], errors="coerce"),
            "close": pd.to_numeric(df[lower_map["close"]], errors="coerce"),
            "volume": pd.to_numeric(df[lower_map["volume"]], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=["date", "symbol", "close"]).copy()
    frame["volume"] = frame["volume"].fillna(0).astype("int64")
    return frame


def _target_symbol_map() -> Dict[str, str]:
    # Source parquet uses bare NSE symbols (e.g., RELIANCE), project uses RELIANCE.NS
    return {s.replace(".NS", ""): s for s in NIFTY_200}


def _build_base_universe(source_parquet: Path) -> pd.DataFrame:
    raw = pd.read_parquet(source_parquet)
    base = _normalize_base(raw)
    symbol_map = _target_symbol_map()

    base = base[base["symbol"].isin(symbol_map.keys())].copy()
    base["symbol"] = base["symbol"].map(symbol_map)
    base = base.sort_values(["symbol", "date"]).drop_duplicates(subset=["symbol", "date"], keep="last")
    return base


def _chunked(items: List[str], n: int) -> List[List[str]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def _refresh_recent_rows(current: pd.DataFrame, period: str, chunk_size: int) -> pd.DataFrame:
    last_dates = current.groupby("symbol")["date"].max().to_dict()
    symbols = sorted(set(current["symbol"].unique()) | set(NIFTY_200))

    new_rows: List[pd.DataFrame] = []
    for group in _chunked(symbols, chunk_size):
        data = batch_download(group, period=period)
        for symbol, df in data.items():
            if df is None or df.empty:
                continue

            cols = {c.lower(): c for c in df.columns}
            if "close" not in cols:
                continue

            # Build normalized update frame
            upd = pd.DataFrame(
                {
                    "date": pd.to_datetime(df.index, errors="coerce").normalize(),
                    "symbol": symbol,
                    "open": pd.to_numeric(df[cols["open"]], errors="coerce") if "open" in cols else pd.NA,
                    "high": pd.to_numeric(df[cols["high"]], errors="coerce") if "high" in cols else pd.NA,
                    "low": pd.to_numeric(df[cols["low"]], errors="coerce") if "low" in cols else pd.NA,
                    "close": pd.to_numeric(df[cols["close"]], errors="coerce"),
                    "volume": pd.to_numeric(df[cols["volume"]], errors="coerce") if "volume" in cols else 0,
                }
            )
            upd = upd.dropna(subset=["date", "close"]).copy()
            upd["volume"] = upd["volume"].fillna(0).astype("int64")

            max_date = last_dates.get(symbol)
            if max_date is not None:
                upd = upd[upd["date"] > max_date]

            if not upd.empty:
                new_rows.append(upd)

    if not new_rows:
        return current

    merged = pd.concat([current] + new_rows, ignore_index=True)
    merged = merged.sort_values(["symbol", "date"]).drop_duplicates(subset=["symbol", "date"], keep="last")
    return merged


def main() -> None:
    args = parse_args()
    source_path = Path(args.source_parquet).expanduser()
    output_path = Path(args.output_parquet)

    if not source_path.exists():
        raise FileNotFoundError(f"Source parquet not found: {source_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    base = _build_base_universe(source_path)

    missing = sorted(set(NIFTY_200) - set(base["symbol"].unique()))
    print(f"Base rows: {len(base)}")
    print(f"Base symbols covered: {base['symbol'].nunique()}/{len(NIFTY_200)}")
    if missing:
        print(f"Missing symbols in base: {len(missing)}")
        print(", ".join(missing[:25]))

    final = base
    if args.refresh:
        final = _refresh_recent_rows(base, period=args.period, chunk_size=args.chunk_size)
        print(f"Rows after refresh: {len(final)}")
        print(f"Symbols after refresh: {final['symbol'].nunique()}/{len(NIFTY_200)}")

    final.to_parquet(output_path, index=False)
    print(f"Wrote: {output_path.resolve()}")
    print(f"Date range: {final['date'].min().date()} -> {final['date'].max().date()}")


if __name__ == "__main__":
    main()
