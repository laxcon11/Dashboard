"""
Shared data fetching utilities - OPTIMIZED VERSION
Used by all dashboards in the suite

Optimizations:
- Symbol validation accepts all formats (HYG, LQD, etc.)
- Better error handling and logging
- Efficient caching with configurable TTL
- Fallback mechanisms for reliability
"""

import yfinance as yf
import pandas as pd
import streamlit as st
import logging
import requests
import zipfile
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
from config import (
    CACHE_TTL,
    DATA_STALENESS_WARN_DAYS,
    DATA_STALENESS_ERROR_DAYS,
    LOCAL_NSE_HISTORY_ENABLED,
    LOCAL_NSE_HISTORY_PATH,
    LOCAL_NSE_HISTORY_WRITEBACK,
    BHAVCOPY_FALLBACK_ENABLED,
    BHAVCOPY_LOCAL_DIR,
    BHAVCOPY_AUTO_DOWNLOAD,
    BHAVCOPY_LOOKBACK_DAYS,
    BHAVCOPY_SCAN_DIRS,
    BHAVCOPY_MAX_FILES_PER_DIR,
)

# ==================== LOGGING SETUP ====================

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s:%(name)s:%(message)s"
)

# Shared session for FRED requests
session = requests.Session()

# Batch telemetry (updated each batch_download call)
_LAST_BATCH_SOURCE_MAP: Dict[str, str] = {}
_LAST_BATCH_DATE_MAP: Dict[str, Optional[pd.Timestamp]] = {}
_LAST_BATCH_AGE_MAP: Dict[str, Optional[int]] = {}
_LAST_BATCH_STALE_MAP: Dict[str, bool] = {}


# ==================== SYMBOL VALIDATION ====================

def validate_symbol(symbol: str) -> bool:
    """
    Accept all reasonable Yahoo Finance symbols

    Supports:
    - Indices: ^NSEI, ^GSPC
    - Stocks/ETFs: AAPL, HYG, LQD
    - Exchanges: RELIANCE.NS
    - Forex: EURUSD=X, USDINR=X
    - Commodities: GC=F, CL=F
    - Crypto: BTC-USD
    """
    if not symbol or not isinstance(symbol, str):
        return False

    symbol = symbol.strip().upper()

    # Accept reasonable length symbols
    return 0 < len(symbol) < 20


# ==================== BHAVCOPY FALLBACK ====================

def _is_nse_equity_symbol(symbol: str) -> bool:
    return isinstance(symbol, str) and symbol.endswith(".NS") and not symbol.startswith("^")


def _nse_archive_url_candidates(d: date) -> List[str]:
    """Generate likely NSE Bhavcopy archive URLs for a given date."""
    ddmmyyyy = d.strftime("%d%m%Y")
    ddmmyy = d.strftime("%d%m%y")
    ymd = d.strftime("%Y%m%d")
    mon = d.strftime("%b").upper()
    yyyy = d.strftime("%Y")
    ddmonyyyy = d.strftime("%d%b%Y").upper()

    return [
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
        f"https://nsearchives.nseindia.com/content/cm/NSE_CM_bhavcopy_{ddmmyyyy}.csv.zip",
        f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{ddmmyy}bhav.csv.zip",
        f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{ddmonyyyy}bhav.csv.zip",
        f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{ddmmyy}bhav.csv.zip",
    ]


def _build_nse_session() -> requests.Session:
    """Create an NSE-friendly session with browser-like headers and warm-up cookies."""
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
        }
    )

    # Warm cookies; failures are expected in restricted/offline environments.
    for url in ("https://www.nseindia.com/", "https://www.nseindia.com/all-reports"):
        try:
            s.get(url, timeout=10)
        except Exception:
            pass
    return s


def _download_bhavcopy_for_date(s: requests.Session, d: date, target_dir: Path) -> Optional[Path]:
    """Try downloading Bhavcopy for a date from known URLs; return saved file path on success."""
    target_dir.mkdir(parents=True, exist_ok=True)

    for url in _nse_archive_url_candidates(d):
        try:
            resp = s.get(url, timeout=20, allow_redirects=True)
            if resp.status_code != 200 or not resp.content or len(resp.content) < 512:
                continue

            # Keep only likely bhavcopy payloads
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if ("zip" not in content_type) and (not url.lower().endswith(".zip")):
                continue

            filename = Path(url.split("?")[0]).name or f"bhavcopy_{d.strftime('%Y%m%d')}.csv.zip"
            out = target_dir / filename
            out.write_bytes(resp.content)
            logger.info("Downloaded Bhavcopy: %s", out)
            return out
        except Exception as exc:
            logger.debug("Bhavcopy download failed for %s: %s", url, exc)

    return None


def auto_download_latest_bhavcopy() -> Optional[Path]:
    """
    Attempt to download the latest available Bhavcopy from NSE archives.
    Returns downloaded file path or None.
    """
    if not BHAVCOPY_AUTO_DOWNLOAD:
        return None

    target_dir = Path(BHAVCOPY_LOCAL_DIR).expanduser()
    s = _build_nse_session()

    for i in range(max(1, BHAVCOPY_LOOKBACK_DAYS)):
        d = (datetime.now() - timedelta(days=i)).date()
        downloaded = _download_bhavcopy_for_date(s, d, target_dir)
        if downloaded is not None:
            return downloaded

    logger.info("Bhavcopy auto-download did not find a valid file in lookback window.")
    return None


def _standardize_bhavcopy_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common Bhavcopy column names to SYMBOL/CLOSE/PREVCLOSE/SERIES."""
    rename = {}
    for col in df.columns:
        norm = str(col).strip().upper().replace(" ", "").replace("_", "")
        if norm == "SYMBOL":
            rename[col] = "SYMBOL"
        elif norm == "CLOSE":
            rename[col] = "CLOSE"
        elif norm in {"PREVCLOSE", "PREVIOUSECLOSE"}:
            rename[col] = "PREVCLOSE"
        elif norm == "SERIES":
            rename[col] = "SERIES"
    return df.rename(columns=rename)


def _extract_bhavcopy_prices(df: pd.DataFrame) -> Dict[str, Tuple[float, Optional[float]]]:
    """Return symbol->(close, prev_close) from a bhavcopy-like DataFrame."""
    if df is None or df.empty:
        return {}

    df = _standardize_bhavcopy_columns(df)
    required = {"SYMBOL", "CLOSE"}
    if not required.issubset(set(df.columns)):
        return {}

    local = df.copy()
    if "SERIES" in local.columns:
        local["SERIES"] = local["SERIES"].astype(str).str.upper().str.strip()
        local = local[local["SERIES"].isin(["EQ", "BE", "SM", "BZ", "BL"])]

    local["SYMBOL"] = local["SYMBOL"].astype(str).str.upper().str.strip()
    local["CLOSE"] = pd.to_numeric(local["CLOSE"], errors="coerce")
    if "PREVCLOSE" in local.columns:
        local["PREVCLOSE"] = pd.to_numeric(local["PREVCLOSE"], errors="coerce")
    else:
        local["PREVCLOSE"] = pd.NA

    local = local.dropna(subset=["CLOSE"])
    if local.empty:
        return {}

    prices: Dict[str, Tuple[float, Optional[float]]] = {}
    for _, row in local.iterrows():
        symbol = f"{row['SYMBOL']}.NS"
        close = float(row["CLOSE"])
        prev_close = None if pd.isna(row["PREVCLOSE"]) else float(row["PREVCLOSE"])
        prices[symbol] = (close, prev_close)
    return prices


def _read_bhavcopy_file(path: Path) -> Dict[str, Tuple[float, Optional[float]]]:
    """Parse bhavcopy CSV or ZIP and return symbol price map."""
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, low_memory=False)
            return _extract_bhavcopy_prices(df)

        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                for member in csv_members:
                    with zf.open(member) as fp:
                        df = pd.read_csv(fp, low_memory=False)
                        prices = _extract_bhavcopy_prices(df)
                        if prices:
                            return prices
    except Exception as exc:
        logger.debug("Bhavcopy parse failed for %s: %s", path, exc)
    return {}


def _list_bhavcopy_candidates() -> List[Path]:
    """Find likely bhavcopy files in configured scan directories."""
    candidates: List[Path] = []
    patterns = (
        "*bhav*.csv", "*BHAV*.csv", "*cm*.csv", "*CM*.csv", "*sec*.csv", "*SEC*.csv",
        "*bhav*.zip", "*BHAV*.zip", "*cm*.zip", "*CM*.zip", "*sec*.zip", "*SEC*.zip",
    )

    for raw_dir in BHAVCOPY_SCAN_DIRS:
        base = Path(raw_dir).expanduser()
        if not base.exists() or not base.is_dir():
            continue

        files: List[Path] = []
        for pattern in patterns:
            files.extend(base.rglob(pattern))
        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
        candidates.extend(files[:BHAVCOPY_MAX_FILES_PER_DIR])

    # Deduplicate while preserving order
    seen = set()
    unique: List[Path] = []
    for p in candidates:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_latest_bhavcopy_prices() -> Dict[str, Tuple[float, Optional[float]]]:
    """
    Load latest available Bhavcopy price map: symbol -> (close, prev_close).
    Returns empty dict if no valid file is found.
    """
    if not BHAVCOPY_FALLBACK_ENABLED:
        return {}

    # Try fetching latest file automatically from NSE archive before scanning local sources.
    if BHAVCOPY_AUTO_DOWNLOAD:
        try:
            auto_download_latest_bhavcopy()
        except Exception as exc:
            logger.debug("Bhavcopy auto-download step failed: %s", exc)

    candidates = _list_bhavcopy_candidates()
    if not candidates:
        logger.info("Bhavcopy fallback enabled but no candidate files found.")
        return {}

    for path in candidates:
        prices = _read_bhavcopy_file(path)
        if prices:
            logger.info("Using Bhavcopy fallback file: %s (%d symbols)", path, len(prices))
            return prices

    logger.info("Bhavcopy fallback enabled but no valid bhavcopy content parsed.")
    return {}


def get_bhavcopy_price(symbol: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (price, change, change_pct) from local Bhavcopy for NSE symbols."""
    if not _is_nse_equity_symbol(symbol):
        return None, None, None

    prices = load_latest_bhavcopy_prices()
    if not prices:
        return None, None, None

    row = prices.get(symbol)
    if not row:
        return None, None, None

    close, prev_close = row
    if prev_close is None or prev_close == 0:
        return close, None, None

    change = close - prev_close
    change_pct = (change / prev_close) * 100
    return close, change, change_pct


def _build_fallback_price_df(price: float, prev_close: Optional[float]) -> pd.DataFrame:
    """
    Build a minimal 2-row OHLCV DataFrame so downstream chart/price code can operate.
    """
    today = datetime.now().date()
    prev_day = today - timedelta(days=1)
    if prev_close is None or prev_close <= 0:
        prev_close = price

    df = pd.DataFrame(
        {
            "Open": [prev_close, price],
            "High": [prev_close, price],
            "Low": [prev_close, price],
            "Close": [prev_close, price],
            "Volume": [0.0, 0.0],
        },
        index=pd.to_datetime([prev_day, today]),
    )
    return df


# ==================== LOCAL PARQUET HISTORY ====================

def _period_to_days(period: str) -> int:
    """Best-effort conversion of yfinance period string to calendar days."""
    p = (period or "").strip().lower()
    mapping = {
        "1d": 2,
        "5d": 10,
        "1mo": 40,
        "3mo": 120,
        "6mo": 240,
        "1y": 420,
        "2y": 840,
        "5y": 2100,
        "10y": 4200,
        "ytd": 420,
        "max": 8000,
    }
    return mapping.get(p, 420)


def _latest_business_day() -> pd.Timestamp:
    today = pd.Timestamp.today().normalize()
    if today.weekday() < 5:
        return today
    return today - pd.offsets.BDay(1)


def _business_day_age(last_date: Optional[pd.Timestamp], ref_date: Optional[pd.Timestamp] = None) -> Optional[int]:
    """Business-day gap between last_date and ref_date."""
    if last_date is None or pd.isna(last_date):
        return None
    if ref_date is None:
        ref_date = _latest_business_day()
    if last_date > ref_date:
        return 0
    bdays = pd.bdate_range(last_date.normalize(), ref_date.normalize())
    return max(0, len(bdays) - 1)


def get_last_batch_telemetry() -> pd.DataFrame:
    """
    Return telemetry from the most recent batch_download call.
    Columns: symbol, source, last_date, age_bdays, is_stale, severity
    """
    rows = []
    for symbol in sorted(_LAST_BATCH_SOURCE_MAP.keys()):
        age = _LAST_BATCH_AGE_MAP.get(symbol)
        is_stale = bool(_LAST_BATCH_STALE_MAP.get(symbol, False))
        if age is None:
            severity = "unknown"
        elif age >= DATA_STALENESS_ERROR_DAYS:
            severity = "error"
        elif age >= DATA_STALENESS_WARN_DAYS:
            severity = "warn"
        else:
            severity = "ok"
        rows.append(
            {
                "symbol": symbol,
                "source": _LAST_BATCH_SOURCE_MAP.get(symbol, "UNKNOWN"),
                "last_date": _LAST_BATCH_DATE_MAP.get(symbol),
                "age_bdays": age,
                "is_stale": is_stale,
                "severity": severity,
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_local_nse_history() -> pd.DataFrame:
    """Load local NSE OHLCV history parquet if available."""
    if not LOCAL_NSE_HISTORY_ENABLED:
        return pd.DataFrame()

    path = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_parquet(path)
        lower_map = {c.lower(): c for c in df.columns}
        required = {"date", "symbol", "open", "high", "low", "close", "volume"}
        if not required.issubset(lower_map):
            return pd.DataFrame()

        out = pd.DataFrame(
            {
                "date": pd.to_datetime(df[lower_map["date"]], errors="coerce").dt.normalize(),
                "symbol": df[lower_map["symbol"]].astype(str).str.upper().str.strip(),
                "open": pd.to_numeric(df[lower_map["open"]], errors="coerce"),
                "high": pd.to_numeric(df[lower_map["high"]], errors="coerce"),
                "low": pd.to_numeric(df[lower_map["low"]], errors="coerce"),
                "close": pd.to_numeric(df[lower_map["close"]], errors="coerce"),
                "volume": pd.to_numeric(df[lower_map["volume"]], errors="coerce").fillna(0).astype("int64"),
            }
        )
        out = out.dropna(subset=["date", "symbol", "close"])
        # Keep parquet aligned with tracked NSE universe only.
        try:
            from NSE_Config import NIFTY_200
            out = out[out["symbol"].isin(set(NIFTY_200))]
        except Exception:
            pass
        return out
    except Exception as exc:
        logger.warning("Failed to load local NSE history parquet: %s", exc)
        return pd.DataFrame()


def _to_market_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dataframe to market schema expected by callers."""
    if df is None or df.empty:
        return pd.DataFrame()

    cols = {c.lower(): c for c in df.columns}
    if "close" not in cols:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "Open": pd.to_numeric(df[cols["open"]], errors="coerce") if "open" in cols else pd.NA,
            "High": pd.to_numeric(df[cols["high"]], errors="coerce") if "high" in cols else pd.NA,
            "Low": pd.to_numeric(df[cols["low"]], errors="coerce") if "low" in cols else pd.NA,
            "Close": pd.to_numeric(df[cols["close"]], errors="coerce"),
            "Volume": pd.to_numeric(df[cols["volume"]], errors="coerce") if "volume" in cols else 0,
        },
        index=pd.to_datetime(df.index if isinstance(df.index, pd.DatetimeIndex) else df.get("date"), errors="coerce"),
    )
    out = out[~out.index.isna()].copy()
    out["Volume"] = out["Volume"].fillna(0).astype("int64")
    return out.sort_index()


def get_local_history_for_symbol(symbol: str, period: str = "1mo") -> pd.DataFrame:
    """Get local parquet history slice for one NSE symbol."""
    if not _is_nse_equity_symbol(symbol):
        return pd.DataFrame()

    full = load_local_nse_history()
    if full.empty:
        return pd.DataFrame()

    sub = full[full["symbol"] == symbol].copy()
    if sub.empty:
        return pd.DataFrame()

    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=_period_to_days(period))
    sub = sub[sub["date"] >= cutoff]
    if sub.empty:
        return pd.DataFrame()

    sub = sub.set_index("date")[["open", "high", "low", "close", "volume"]]
    return _to_market_frame(sub)


def persist_local_nse_updates(updates: Dict[str, pd.DataFrame]) -> None:
    """Append incremental rows to local NSE parquet history."""
    if not LOCAL_NSE_HISTORY_ENABLED or not LOCAL_NSE_HISTORY_WRITEBACK:
        return
    if not updates:
        return

    path = Path(LOCAL_NSE_HISTORY_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    frames: List[pd.DataFrame] = []
    for symbol, df in updates.items():
        if not _is_nse_equity_symbol(symbol) or df is None or df.empty:
            continue
        cols = {c.lower(): c for c in df.columns}
        if "close" not in cols:
            continue
        part = pd.DataFrame(
            {
                "date": pd.to_datetime(df.index, errors="coerce").normalize(),
                "symbol": symbol,
                "open": pd.to_numeric(df[cols["open"]], errors="coerce") if "open" in cols else pd.NA,
                "high": pd.to_numeric(df[cols["high"]], errors="coerce") if "high" in cols else pd.NA,
                "low": pd.to_numeric(df[cols["low"]], errors="coerce") if "low" in cols else pd.NA,
                "close": pd.to_numeric(df[cols["close"]], errors="coerce"),
                "volume": pd.to_numeric(df[cols["volume"]], errors="coerce") if "volume" in cols else 0,
            }
        ).dropna(subset=["date", "close"])
        if not part.empty:
            part["volume"] = part["volume"].fillna(0).astype("int64")
            frames.append(part)

    if not frames:
        return

    incoming = pd.concat(frames, ignore_index=True)
    try:
        existing = load_local_nse_history()
        merged = pd.concat([existing, incoming], ignore_index=True)
        try:
            from NSE_Config import NIFTY_200
            merged = merged[merged["symbol"].isin(set(NIFTY_200))]
        except Exception:
            pass
        merged = merged.sort_values(["symbol", "date"]).drop_duplicates(subset=["symbol", "date"], keep="last")
        merged.to_parquet(path, index=False)
        load_local_nse_history.clear()
        logger.info("Updated local NSE history parquet: %s", path)
    except Exception as exc:
        logger.warning("Failed to persist local NSE history updates: %s", exc)


# ==================== BATCH DOWNLOAD ====================

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def batch_download(symbols: List[str], period: str = "1mo") -> Dict[str, pd.DataFrame]:
    """
    Efficiently download multiple symbols in one API call

    Args:
        symbols: List of Yahoo Finance symbols
        period: Time period (1mo, 3mo, 6mo, 1y, etc.)

    Returns:
        Dictionary mapping symbol to DataFrame

    Features:
    - Automatic retry on failure
    - Deduplication of symbols
    - NaN validation
    - Works with all asset types (stocks, ETFs, indices, forex, crypto)
    """
    # Remove duplicates while preserving order
    valid_symbols = list(dict.fromkeys(s for s in symbols if validate_symbol(s)))

    if not valid_symbols:
        logger.warning("No valid symbols provided for download")
        return {}

    try:
        result: Dict[str, pd.DataFrame] = {}
        source_map: Dict[str, str] = {}
        latest_bd = _latest_business_day()

        # 1) Load local parquet first for NSE symbols.
        symbols_for_api: List[str] = []
        for symbol in valid_symbols:
            local_df = get_local_history_for_symbol(symbol, period=period)
            if not local_df.empty:
                result[symbol] = local_df
                source_map[symbol] = "LOCAL"
                max_date = local_df.index.max().normalize()
                if max_date < latest_bd:
                    symbols_for_api.append(symbol)
            else:
                symbols_for_api.append(symbol)

        logger.info(
            "Local-first fetch: %d symbols from local cache, %d symbols need API.",
            len(result),
            len(symbols_for_api),
        )

        api_updates: Dict[str, pd.DataFrame] = {}

        # 2) Pull only stale/missing symbols from API.
        if symbols_for_api:
            data = None
            for attempt in range(2):
                try:
                    data = yf.download(
                        tickers=symbols_for_api,
                        period=period,
                        group_by="ticker",
                        progress=False,
                        threads=True,
                        auto_adjust=True,
                        timeout=20,
                    )
                    break
                except Exception as e:
                    logger.warning("Download attempt %d failed: %s", attempt + 1, e)
                    if attempt == 1:
                        raise

            if len(symbols_for_api) == 1:
                symbol = symbols_for_api[0]
                if isinstance(data, pd.DataFrame) and not data.empty:
                    if "Close" in data.columns:
                        api_updates[symbol] = data
                    else:
                        try:
                            api_updates[symbol] = data.xs(symbol, axis=1, level=0)
                        except Exception:
                            logger.warning("Could not parse data for %s", symbol)
            else:
                for symbol in symbols_for_api:
                    try:
                        df = data[symbol]
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            close_series = df.get("Close")
                            if close_series is not None and not close_series.dropna().empty:
                                api_updates[symbol] = df
                            else:
                                logger.warning("%s: No valid Close data", symbol)
                        else:
                            logger.warning("%s: Empty DataFrame", symbol)
                    except KeyError:
                        logger.warning("%s: Not in batch results", symbol)
                    except Exception as e:
                        logger.error("%s: Extraction error - %s", symbol, e)

        # 3) Merge local + API (API rows override same-date local rows).
        for symbol, upd in api_updates.items():
            upd_norm = _to_market_frame(upd)
            if upd_norm.empty:
                continue

            if symbol in result and not result[symbol].empty:
                merged = pd.concat([result[symbol], upd_norm], axis=0)
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                result[symbol] = merged
                source_map[symbol] = "LOCAL+API"
            else:
                result[symbol] = upd_norm
                source_map[symbol] = "API"

        # 4) Persist incremental API rows back to local parquet for NSE symbols.
        persist_local_nse_updates(api_updates)

        # 5) Bhavcopy fallback for still-missing NSE symbols.
        missing_nse = [s for s in valid_symbols if s not in result and _is_nse_equity_symbol(s)]
        if missing_nse:
            bhav_prices = load_latest_bhavcopy_prices()
            for symbol in missing_nse:
                row = bhav_prices.get(symbol)
                if not row:
                    continue
                close, prev_close = row
                result[symbol] = _build_fallback_price_df(close, prev_close)
                source_map[symbol] = "BHAVCOPY"
                logger.warning("%s: Using Bhavcopy fallback.", symbol)

        # Mark symbols that ended up local-only and stale (API failed / not refreshed)
        for symbol, df in result.items():
            if source_map.get(symbol) == "LOCAL":
                if not df.empty and df.index.max().normalize() < latest_bd:
                    source_map[symbol] = "LOCAL(STALE)"

        # Publish telemetry for downstream diagnostics/UI.
        global _LAST_BATCH_SOURCE_MAP, _LAST_BATCH_DATE_MAP, _LAST_BATCH_AGE_MAP, _LAST_BATCH_STALE_MAP
        _LAST_BATCH_SOURCE_MAP = {}
        _LAST_BATCH_DATE_MAP = {}
        _LAST_BATCH_AGE_MAP = {}
        _LAST_BATCH_STALE_MAP = {}
        for symbol, df in result.items():
            max_date = None if df is None or df.empty else pd.to_datetime(df.index.max()).normalize()
            age = _business_day_age(max_date, latest_bd)
            _LAST_BATCH_SOURCE_MAP[symbol] = source_map.get(symbol, "UNKNOWN")
            _LAST_BATCH_DATE_MAP[symbol] = max_date
            _LAST_BATCH_AGE_MAP[symbol] = age
            _LAST_BATCH_STALE_MAP[symbol] = (age is None) or (age >= DATA_STALENESS_WARN_DAYS)

        logger.info("Successfully loaded %d/%d symbols", len(result), len(valid_symbols))
        return result

    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        return {}


# ==================== PRICE EXTRACTION ====================

def extract_price_data(df: Optional[pd.DataFrame]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Extract latest price and percentage change from DataFrame

    Args:
        df: DataFrame with Close/Adj Close column

    Returns:
        (current_price, change, change_percent) tuple

    Features:
    - Handles both Close and Adj Close columns
    - NaN validation
    - Works with insufficient data (returns None gracefully)
    """
    if df is None or len(df) == 0:
        return None, None, None

    try:
        # Find appropriate close column
        if 'Close' in df.columns:
            close_col = 'Close'
        elif 'Adj Close' in df.columns:
            close_col = 'Adj Close'
        else:
            logger.error(f"No Close/Adj Close column found. Columns: {df.columns.tolist()}")
            return None, None, None

        # Get valid price series
        series = df[close_col].dropna()
        if len(series) == 0:
            return None, None, None

        current = series.iloc[-1]

        # Validate current price
        if current is None or pd.isna(current):
            logger.warning(f"Current price is NaN")
            return None, None, None

        # Calculate change if we have at least 2 data points
        if len(series) >= 2:
            prev = series.iloc[-2]

            if prev == 0 or pd.isna(prev):
                return current, 0, 0

            change = current - prev
            change_pct = (change / prev) * 100
            return current, change, change_pct
        else:
            # Only 1 data point
            return current, None, None

    except Exception as e:
        logger.error(f"Price extraction failed: {e}")
        return None, None, None


def get_ticker_price(symbol: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Get current price from ticker.info (fallback method)

    Args:
        symbol: Yahoo Finance symbol

    Returns:
        (current_price, change, change_percent) tuple

    Use when:
    - Historical data download fails
    - Need most recent price
    - Faster single-symbol fetch
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Try multiple price fields
        current = (
            info.get('regularMarketPrice') or
            info.get('currentPrice') or
            info.get('price') or
            info.get('previousClose')
        )

        prev = info.get('previousClose')

        if current and prev and prev != 0:
            change = current - prev
            change_pct = (change / prev) * 100
            return current, change, change_pct
        elif current:
            return current, None, None

        # Fallback to local Bhavcopy for NSE symbols at/after EOD
        bhav_price, bhav_change, bhav_change_pct = get_bhavcopy_price(symbol)
        if bhav_price is not None:
            logger.warning("%s: Using Bhavcopy fallback in get_ticker_price.", symbol)
            return bhav_price, bhav_change, bhav_change_pct

        return None, None, None

    except Exception as e:
        logger.error(f"Ticker info fetch failed for {symbol}: {e}")
        bhav_price, bhav_change, bhav_change_pct = get_bhavcopy_price(symbol)
        if bhav_price is not None:
            logger.warning("%s: Using Bhavcopy fallback after ticker error.", symbol)
            return bhav_price, bhav_change, bhav_change_pct
        return None, None, None


# ==================== HELPER FUNCTIONS ====================

def get_last_n_days(df: pd.DataFrame, days: int = 5) -> pd.DataFrame:
    """Safely get last N rows from DataFrame"""
    if df is None or len(df) == 0:
        return df
    return df.tail(days)


def safe_close_series(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    """
    Extract clean Close series from DataFrame

    Returns:
        Series with NaN values dropped, or None if invalid
    """
    if df is None or "Close" not in df.columns:
        return None

    series = df["Close"].dropna()
    return series if len(series) > 0 else None


# ==================== FRED DATA FETCHING ====================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred_series(series_id: str, api_key: str, days: int = 30) -> Optional[pd.DataFrame]:
    """
    Fetch economic data from FRED (Federal Reserve Economic Data)

    Args:
        series_id: FRED series identifier (e.g., "WALCL", "DGS10")
        api_key: FRED API key
        days: Number of observations to return

    Returns:
        DataFrame with columns: date, value
    """
    if not api_key:
        logger.warning("FRED API key missing")
        return None

    try:
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}"
            f"&api_key={api_key}"
            "&file_type=json"
            "&sort_order=desc"
            "&limit=120"
        )

        response = session.get(url, timeout=10)

        if response.status_code != 200:
            logger.warning(f"FRED API returned {response.status_code} for {series_id}")
            return None

        data = response.json()
        observations = data.get("observations", [])

        if not observations:
            logger.warning(f"No observations returned for {series_id}")
            return None

        df = pd.DataFrame(observations)

        # Convert types
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])

        # Clean and sort
        df = df.dropna(subset=["value"]).sort_values("date")

        return df.tail(days)

    except Exception as e:
        logger.error(f"FRED fetch failed for {series_id}: {e}")
        return None


# ==================== INDIA VIX FETCHING ====================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_india_vix() -> Tuple[Optional[float], Optional[float]]:
    """
    Fetch India VIX from NSE API

    Returns:
        (price, change_percent) tuple

    Note: NSE API can be unreliable, returns None on failure
    """
    try:
        url = "https://www.nseindia.com/api/allIndices"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/"
        }

        # Initialize session
        session.get("https://www.nseindia.com", headers=headers, timeout=10)

        # Fetch data
        response = session.get(url, headers=headers, timeout=10)
        data = response.json()

        # Find India VIX
        for item in data.get("data", []):
            if item.get("index") == "INDIA VIX":
                price = float(item.get("last", 0))
                change_pct = float(item.get("percentChange", 0))
                return price, change_pct

        return None, None

    except Exception as e:
        logger.error(f"India VIX fetch failed: {e}")
        return None, None


# ==================== CHART PREPARATION ====================

def prepare_timeseries_for_chart(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare DataFrame for smooth plotting

    Features:
    - Ensures datetime index
    - Fills missing calendar days
    - Forward fills price values

    Args:
        df: DataFrame with price data

    Returns:
        DataFrame ready for charting
    """
    if df is None or len(df) == 0:
        return df

    try:
        df = df.copy()

        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Create continuous date range
        full_index = pd.date_range(
            start=df.index.min(),
            end=df.index.max(),
            freq="D"
        )

        df = df.reindex(full_index)

        # Forward fill numeric columns
        numeric_cols = df.select_dtypes(include=["number"]).columns
        df[numeric_cols] = df[numeric_cols].ffill().bfill()

        return df

    except Exception as e:
        logger.error(f"Chart preparation failed: {e}")
        return df


# ==================== VALIDATION HELPERS ====================

def validate_dataframe(df: Optional[pd.DataFrame], required_columns: List[str] = None) -> bool:
    """
    Validate DataFrame has required structure

    Args:
        df: DataFrame to validate
        required_columns: List of required column names

    Returns:
        True if valid, False otherwise
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return False

    if len(df) == 0:
        return False

    if required_columns:
        return all(col in df.columns for col in required_columns)

    return True


def get_data_status(symbols: List[str], data: Dict[str, pd.DataFrame]) -> Dict[str, str]:
    """
    Get status of downloaded data

    Args:
        symbols: List of requested symbols
        data: Dictionary of downloaded data

    Returns:
        Dictionary mapping symbol to status ('OK', 'Missing', 'Empty', 'Invalid')
    """
    status = {}

    for symbol in symbols:
        if symbol not in data:
            status[symbol] = 'Missing'
        elif data[symbol] is None:
            status[symbol] = 'Invalid'
        elif len(data[symbol]) == 0:
            status[symbol] = 'Empty'
        else:
            status[symbol] = 'OK'

    return status
