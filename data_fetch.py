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
import re
import time
import string
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple
try:
    import feedparser
except Exception:  # pragma: no cover - optional dependency guard
    feedparser = None
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
    BHAVCOPY_EOD_RECONCILE_ENABLED,
    BHAVCOPY_EOD_RECONCILE_CUTOFF_IST_HOUR,
    FINNHUB_NSE_PREFIX,
    FINNHUB_METRICS,
    FINNHUB_RATE_LIMIT_PAUSE,
    EODHD_BASE_URL,
    EODHD_NSE_SUFFIX,
    EODHD_RATE_LIMIT_PAUSE,
)
from trading_calendar import latest_nse_business_day, nse_business_day_age

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


_LAST_BHAVCOPY_SNAPSHOT: Dict[str, object] = {"prices": {}, "trade_date": None, "path": None}


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
        elif norm in {"TCKRSYMB", "TICKERSYMBOL"}:
            rename[col] = "SYMBOL"
        elif norm == "CLOSE":
            rename[col] = "CLOSE"
        elif norm in {"CLSPRIC", "CLOSINGPRICE"}:
            rename[col] = "CLOSE"
        elif norm in {"PREVCLOSE", "PREVIOUSECLOSE"}:
            rename[col] = "PREVCLOSE"
        elif norm in {"PRVSCLSGPRIC", "PREVIOUSCLOSINGPRICE"}:
            rename[col] = "PREVCLOSE"
        elif norm == "SERIES":
            rename[col] = "SERIES"
        elif norm == "SCTYSRS":
            rename[col] = "SERIES"
        elif norm in {"VOLUME", "TTLTRADGVOL", "TOTALTRADINGVOLUME"}:
            rename[col] = "VOLUME"
    return df.rename(columns=rename)


def _extract_bhavcopy_prices(df: pd.DataFrame) -> Dict[str, Tuple[float, Optional[float], Optional[float]]]:
    """Return symbol->(close, prev_close, volume) from a bhavcopy-like DataFrame."""
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

    if "TTLTRADGVOL" in local.columns and "VOLUME" not in local.columns:
        local["VOLUME"] = pd.to_numeric(local["TTLTRADGVOL"], errors="coerce")
    elif "VOLUME" in local.columns:
        local["VOLUME"] = pd.to_numeric(local["VOLUME"], errors="coerce")
    else:
        local["VOLUME"] = pd.NA

    prices: Dict[str, Tuple[float, Optional[float], Optional[float]]] = {}
    for _, row in local.iterrows():
        symbol = f"{row['SYMBOL']}.NS"
        close = float(row["CLOSE"])
        prev_close = None if pd.isna(row["PREVCLOSE"]) else float(row["PREVCLOSE"])
        vol = None if pd.isna(row["VOLUME"]) else float(row["VOLUME"])
        prices[symbol] = (close, prev_close, vol)
    return prices


def _read_bhavcopy_file(path: Path) -> Dict[str, Tuple[float, Optional[float], Optional[float]]]:
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


def _extract_bhavcopy_trade_date(df: pd.DataFrame) -> Optional[pd.Timestamp]:
    """Best-effort extraction of trade date from Bhavcopy dataframe."""
    if df is None or df.empty:
        return None
    for col in df.columns:
        norm = str(col).strip().upper().replace(" ", "").replace("_", "")
        if norm in {"TRADDT", "BIZDT", "DATE1", "TIMESTAMP", "TRADEDATE"}:
            s = pd.to_datetime(df[col], errors="coerce").dropna()
            if not s.empty:
                return s.max().normalize()
    return None


def _read_bhavcopy_file_with_meta(path: Path) -> Tuple[Dict[str, Tuple[float, Optional[float], Optional[float]]], Optional[pd.Timestamp]]:
    """Parse Bhavcopy and return (prices, trade_date)."""
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, low_memory=False)
            return _extract_bhavcopy_prices(df), _extract_bhavcopy_trade_date(df)

        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                for member in csv_members:
                    with zf.open(member) as fp:
                        df = pd.read_csv(fp, low_memory=False)
                        prices = _extract_bhavcopy_prices(df)
                        if prices:
                            return prices, _extract_bhavcopy_trade_date(df)
    except Exception as exc:
        logger.debug("Bhavcopy parse(meta) failed for %s: %s", path, exc)
    return {}, None


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

    def _extract_date_hint(p: Path) -> Optional[pd.Timestamp]:
        name = p.name.upper()
        patterns = [
            r"(\d{8})",            # YYYYMMDD or DDMMYYYY (ambiguous)
            r"(\d{2}[A-Z]{3}\d{4})",  # 01FEB2024
            r"(\d{6})",            # DDMMYY
        ]
        for pat in patterns:
            m = re.search(pat, name)
            if not m:
                continue
            token = m.group(1)
            for fmt in ("%Y%m%d", "%d%m%Y", "%d%b%Y", "%d%m%y"):
                try:
                    return pd.to_datetime(token, format=fmt, errors="raise").normalize()
                except Exception:
                    continue
        return None

    # Deduplicate while preserving order
    seen = set()
    unique: List[Path] = []
    for p in candidates:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Prefer latest dated files first; fallback to mtime.
    def _sort_key(p: Path):
        d = _extract_date_hint(p)
        d_ord = int(d.value) if d is not None else -1
        return (d_ord, p.stat().st_mtime)

    unique = sorted(unique, key=_sort_key, reverse=True)
    return unique


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_latest_bhavcopy_prices() -> Dict[str, Tuple[float, Optional[float], Optional[float]]]:
    """
    Load latest available Bhavcopy price map: symbol -> (close, prev_close, volume).
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
        _LAST_BHAVCOPY_SNAPSHOT.update({"prices": {}, "trade_date": None, "path": None})
        return {}

    for path in candidates:
        prices, trade_date = _read_bhavcopy_file_with_meta(path)
        if prices:
            logger.info("Using Bhavcopy fallback file: %s (%d symbols)", path, len(prices))
            _LAST_BHAVCOPY_SNAPSHOT.update({"prices": prices, "trade_date": trade_date, "path": str(path)})
            return prices

    logger.info("Bhavcopy fallback enabled but no valid bhavcopy content parsed.")
    _LAST_BHAVCOPY_SNAPSHOT.update({"prices": {}, "trade_date": None, "path": None})
    return {}


def get_latest_bhavcopy_snapshot() -> Dict[str, object]:
    """Return latest bhavcopy snapshot metadata after load_latest_bhavcopy_prices call."""
    if not _LAST_BHAVCOPY_SNAPSHOT.get("prices"):
        _ = load_latest_bhavcopy_prices()
    return dict(_LAST_BHAVCOPY_SNAPSHOT)


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

    close, prev_close, _ = row
    if prev_close is None or prev_close == 0:
        return close, None, None

    change = close - prev_close
    change_pct = (change / prev_close) * 100
    return close, change, change_pct


def _build_fallback_price_df(
    price: float,
    prev_close: Optional[float],
    trade_date: Optional[pd.Timestamp] = None,
    volume: Optional[float] = None,
) -> pd.DataFrame:
    """
    Build a minimal 2-row OHLCV DataFrame so downstream chart/price code can operate.
    """
    if trade_date is None:
        tday = pd.Timestamp.today().normalize()
    else:
        tday = pd.to_datetime(trade_date).normalize()
    prev_day = (tday - pd.offsets.BDay(1)).normalize()
    if prev_close is None or prev_close <= 0:
        prev_close = price
    vol_today = 0.0 if volume is None or pd.isna(volume) else float(max(0.0, volume))

    df = pd.DataFrame(
        {
            "Open": [prev_close, price],
            "High": [prev_close, price],
            "Low": [prev_close, price],
            "Close": [prev_close, price],
            "Volume": [0.0, vol_today],
        },
        index=pd.to_datetime([prev_day, tday]),
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
    return latest_nse_business_day()


def _is_after_bhav_eod_cutoff_ist() -> bool:
    try:
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        cutoff = int(BHAVCOPY_EOD_RECONCILE_CUTOFF_IST_HOUR)
        # EOD reconcile window:
        # - same-day evening after cutoff (e.g., 20:00+)
        # - post-midnight pre-open (carry forward previous session reconcile window)
        return (now_ist.hour >= cutoff) or (now_ist.hour < 9)
    except Exception:
        # Fallback approximation for environments without tz data
        return False


def _is_nse_market_hours_ist() -> bool:
    """True during regular NSE cash session (Mon-Fri, 09:15-15:30 IST)."""
    try:
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        if now_ist.weekday() >= 5:
            return False
        mins = (now_ist.hour * 60) + now_ist.minute
        return (9 * 60 + 15) <= mins <= (15 * 60 + 30)
    except Exception:
        return False


def _business_day_age(last_date: Optional[pd.Timestamp], ref_date: Optional[pd.Timestamp] = None) -> Optional[int]:
    """Business-day gap between last_date and ref_date."""
    return nse_business_day_age(last_date, ref_date or _latest_business_day())


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


@st.cache_data(ttl=300, show_spinner=False)
def quick_data_health_summary() -> Dict[str, object]:
    """
    Lightweight integrity snapshot for launcher banner.
    """
    summary: Dict[str, object] = {
        "ok": True,
        "missing_symbols": 0,
        "duplicates": 0,
        "stale_warn": 0,
        "stale_error": 0,
        "message": "Data health OK",
    }
    try:
        local = load_local_nse_history()
        if local is None or local.empty:
            summary.update({"ok": False, "message": "Local history unavailable"})
            return summary

        work = local.copy()
        work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
        work["symbol"] = work["symbol"].astype(str).str.upper().str.strip()
        work = work.dropna(subset=["date", "symbol"])

        from NSE_Config import NIFTY_200

        universe = set(NIFTY_200)
        available = set(work["symbol"].unique())
        missing = universe - available
        summary["missing_symbols"] = len(missing)
        summary["duplicates"] = int(work.duplicated(subset=["symbol", "date"]).sum())

        latest_bd = latest_nse_business_day()
        ages = work.groupby("symbol")["date"].max().apply(
            lambda d: (nse_business_day_age(pd.Timestamp(d), latest_bd) or 0)
        )
        summary["stale_warn"] = int((ages >= DATA_STALENESS_WARN_DAYS).sum())
        summary["stale_error"] = int((ages >= DATA_STALENESS_ERROR_DAYS).sum())

        summary["ok"] = (
            summary["missing_symbols"] == 0
            and summary["duplicates"] == 0
            and summary["stale_error"] == 0
        )
        if not summary["ok"]:
            summary["message"] = (
                f"missing={summary['missing_symbols']} | dup={summary['duplicates']} | stale={summary['stale_error']}"
            )
    except Exception as exc:
        summary.update({"ok": False, "message": f"Health check error: {exc}"})
    return summary


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
                elif (
                    _is_nse_equity_symbol(symbol)
                    and max_date == latest_bd
                    and _is_nse_market_hours_ist()
                ):
                    # During live market hours, refresh today's bar from API every cache cycle.
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

        # 5) Bhavcopy fallback for still-missing NSE symbols and stale local-only symbols.
        bhav_prices = load_latest_bhavcopy_prices()
        bhav_snapshot = get_latest_bhavcopy_snapshot()
        bhav_trade_date = bhav_snapshot.get("trade_date")
        bhav_updates: Dict[str, pd.DataFrame] = {}

        missing_nse = [s for s in valid_symbols if s not in result and _is_nse_equity_symbol(s)]
        for symbol in missing_nse:
            row = bhav_prices.get(symbol)
            if not row:
                continue
            close, prev_close, vol = row
            bdf = _build_fallback_price_df(close, prev_close, trade_date=bhav_trade_date, volume=vol)
            result[symbol] = bdf
            source_map[symbol] = "BHAVCOPY"
            bhav_updates[symbol] = bdf
            logger.warning("%s: Using Bhavcopy fallback (missing).", symbol)

        stale_local_nse = [
            s for s in valid_symbols
            if _is_nse_equity_symbol(s)
            and s in result
            and source_map.get(s) == "LOCAL"
            and not result[s].empty
            and result[s].index.max().normalize() < latest_bd
        ]
        for symbol in stale_local_nse:
            row = bhav_prices.get(symbol)
            if not row:
                continue
            close, prev_close, vol = row
            bdf = _build_fallback_price_df(close, prev_close, trade_date=bhav_trade_date, volume=vol)
            merged = pd.concat([result[symbol], bdf], axis=0)
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            result[symbol] = merged
            source_map[symbol] = "LOCAL+BHAVCOPY"
            bhav_updates[symbol] = bdf
            logger.warning("%s: Using Bhavcopy fallback (stale local).", symbol)

        if bhav_updates:
            persist_local_nse_updates(bhav_updates)

        # 6) EOD reconcile: after IST cutoff, if Bhavcopy is for latest business day, use it as final source of truth.
        if (
            BHAVCOPY_EOD_RECONCILE_ENABLED
            and _is_after_bhav_eod_cutoff_ist()
            and isinstance(bhav_trade_date, pd.Timestamp)
            and bhav_trade_date.normalize() >= latest_bd
        ):
            eod_updates: Dict[str, pd.DataFrame] = {}
            for symbol in valid_symbols:
                if not _is_nse_equity_symbol(symbol):
                    continue
                row = bhav_prices.get(symbol)
                if not row:
                    continue
                close, prev_close, vol = row
                bdf = _build_fallback_price_df(close, prev_close, trade_date=bhav_trade_date, volume=vol)
                if symbol in result and not result[symbol].empty:
                    merged = pd.concat([result[symbol], bdf], axis=0)
                    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                    result[symbol] = merged
                else:
                    result[symbol] = bdf
                source_map[symbol] = "BHAVCOPY(EOD)"
                eod_updates[symbol] = bdf
            if eod_updates:
                persist_local_nse_updates(eod_updates)

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


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_fred_batch(series_dict: Dict[str, str], api_key: str, days: int = 180) -> Dict[str, pd.DataFrame]:
    """
    Fetch a batch of FRED series using the existing fetch_fred_series function.
    Returns dict[label] = DataFrame for successful pulls only.
    """
    out: Dict[str, pd.DataFrame] = {}
    if not api_key or not isinstance(series_dict, dict):
        return out

    for label, series_id in series_dict.items():
        try:
            df = fetch_fred_series(series_id, api_key, days=days)
            if df is not None and not df.empty:
                out[str(label)] = df.copy()
        except Exception:
            continue
    return out


def _normalize_title(text: str) -> str:
    txt = str(text or "").lower()
    trans = str.maketrans("", "", string.punctuation)
    txt = txt.translate(trans)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_rss_feed(feed_name: str, url: str, max_items: int = 8) -> List[Dict[str, object]]:
    """
    Fetch and parse a single RSS feed.
    Returns list of dicts with keys: title, link, published, summary, source
    Returns empty list on any failure (never raises).
    """
    if not feed_name or not url:
        return []
    if feedparser is None:
        return []

    try:
        t0 = time.perf_counter()
        resp = session.get(url, timeout=12)
        _latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        if resp.status_code != 200:
            logger.warning("RSS fetch failed [%s]: http_status=%s latency_ms=%s", feed_name, resp.status_code, _latency_ms)
            return []
        parsed = feedparser.parse(resp.content)
        entries = getattr(parsed, "entries", []) or []
        items: List[Dict[str, object]] = []
        for e in entries[:max_items]:
            title = str(getattr(e, "title", "")).strip()
            link = str(getattr(e, "link", "")).strip()
            summary = str(getattr(e, "summary", "") or getattr(e, "description", "")).strip()
            published_raw = (
                getattr(e, "published", None)
                or getattr(e, "updated", None)
                or getattr(e, "created", None)
            )
            published = pd.to_datetime(published_raw, errors="coerce")
            items.append(
                {
                    "title": title,
                    "link": link,
                    "published": None if pd.isna(published) else published,
                    "summary": summary[:300],
                    "source": str(feed_name),
                }
            )
        return items
    except Exception as exc:
        logger.warning("RSS fetch failed [%s]: %s", feed_name, exc)
        return []


@st.cache_data(ttl=600, show_spinner=False)
def fetch_rss_feed_health(feed_name: str, url: str, max_items: int = 8) -> Dict[str, object]:
    """
    Fetch one RSS feed with diagnostics.
    Returns health payload including latency, item count, and parse/fetch error markers.
    Never raises.
    """
    out: Dict[str, object] = {
        "feed": str(feed_name or ""),
        "status": "Error",
        "item_count": 0,
        "latency_ms": None,
        "fetch_errors": 0,
        "parse_errors": 0,
        "error_detail": "",
    }
    if not feed_name or not url:
        out["fetch_errors"] = 1
        out["error_detail"] = "missing_feed_or_url"
        return out
    if feedparser is None:
        out["fetch_errors"] = 1
        out["error_detail"] = "feedparser_not_installed"
        return out

    try:
        t0 = time.perf_counter()
        resp = session.get(url, timeout=12)
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        if resp.status_code != 200:
            out["fetch_errors"] = 1
            out["error_detail"] = f"http_{resp.status_code}"
            return out

        parsed = feedparser.parse(resp.content)
        if getattr(parsed, "bozo", 0):
            out["parse_errors"] = 1
            try:
                out["error_detail"] = str(getattr(parsed, "bozo_exception", "parse_warning"))
            except Exception:
                out["error_detail"] = "parse_warning"

        entries = getattr(parsed, "entries", []) or []
        out["item_count"] = int(min(len(entries), max_items))
        out["status"] = "OK" if out["item_count"] > 0 else "Error"
        if out["status"] == "Error" and not out["error_detail"]:
            out["error_detail"] = "no_entries"
        return out
    except Exception as exc:
        out["fetch_errors"] = 1
        out["error_detail"] = str(exc)
        return out


@st.cache_data(ttl=600, show_spinner=False)
def fetch_rss_feeds(feed_dict: Dict[str, str], max_per_feed: int = 10, max_total: int = 50) -> pd.DataFrame:
    """
    Fetch multiple RSS feeds and merge into a single DataFrame.
    Columns: title, link, published (datetime), summary, source (feed name)
    Sorted by published DESC.
    Deduplicates by title similarity (80%+ overlap).
    Returns empty DataFrame on total failure.
    """
    try:
        items: List[Dict[str, object]] = []
        for source_name, url in (feed_dict or {}).items():
            items.extend(fetch_rss_feed(str(source_name), str(url), max_items=max_per_feed))
        return _build_news_df(items, max_total=max_total)
    except Exception:
        return pd.DataFrame(columns=["title", "link", "published", "summary", "source"])


def _build_news_df(items: List[Dict[str, object]], max_total: int = 60) -> pd.DataFrame:
    """
    Internal: deduplicate, sort, and cap a list of news items into a DataFrame.
    Deduplication: drop if normalized title is 80%+ identical to a seen title.
    """
    if not items:
        return pd.DataFrame(columns=["title", "link", "published", "summary", "source"])

    seen_titles: List[str] = []
    deduped: List[Dict[str, object]] = []
    for item in items:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        duplicate = any(_title_similarity(title, prev) >= 0.80 for prev in seen_titles)
        if duplicate:
            continue
        seen_titles.append(title)
        deduped.append(
            {
                "title": title,
                "link": str(item.get("link", "")).strip(),
                "published": pd.to_datetime(item.get("published"), errors="coerce"),
                "summary": str(item.get("summary", "")).strip(),
                "source": str(item.get("source", "")).strip(),
            }
        )

    if not deduped:
        return pd.DataFrame(columns=["title", "link", "published", "summary", "source"])
    df = pd.DataFrame(deduped)
    df["published"] = pd.to_datetime(df["published"], utc=True, errors="coerce")
    return df.sort_values("published", ascending=False, na_position="last").head(max_total).reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_rss_feeds_by_tag(tag: str, max_per_feed: int = 6, max_total: int = 30) -> pd.DataFrame:
    """
    Fetch all feeds associated with a tag from RSS_FEED_TAGS.
    """
    from config import RSS_FEEDS, RSS_FEED_TAGS

    feed_keys = RSS_FEED_TAGS.get(str(tag), [])
    items: List[Dict[str, object]] = []
    for key in feed_keys:
        url = RSS_FEEDS.get(key)
        if not url:
            continue
        items.extend(fetch_rss_feed(str(key), str(url), max_items=max_per_feed))
    return _build_news_df(items, max_total=max_total)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_rss_feeds_by_keys(feed_keys: List[str], max_per_feed: int = 8, max_total: int = 60) -> pd.DataFrame:
    """
    Fetch feeds by a list of feed name keys from RSS_FEEDS.
    """
    from config import RSS_FEEDS

    items: List[Dict[str, object]] = []
    for key in (feed_keys or []):
        url = RSS_FEEDS.get(str(key))
        if not url:
            continue
        items.extend(fetch_rss_feed(str(key), str(url), max_items=max_per_feed))
    return _build_news_df(items, max_total=max_total)


def _to_finnhub_nse_symbol(symbol_ns: str) -> str:
    base = str(symbol_ns or "").upper().replace(".NS", "").strip()
    return f"{FINNHUB_NSE_PREFIX}{base}" if base else ""


def _to_eodhd_symbol(symbol: str) -> str:
    sym = str(symbol or "").upper().strip()
    if not sym:
        return ""
    if sym.endswith(".NS"):
        return sym.replace(".NS", EODHD_NSE_SUFFIX)
    return sym


def _eodhd_symbol_candidates(symbol: str) -> List[str]:
    sym = str(symbol or "").upper().strip()
    if not sym:
        return []
    base = sym.replace(".NS", "").replace(".NSE", "").replace(".BSE", "")
    candidates = []
    if sym.endswith(".NS"):
        candidates.extend([f"{base}.NSE", f"{base}.BSE", f"{base}.NS"])
    else:
        candidates.extend([sym, f"{base}.NSE", f"{base}.BSE"])
    out = []
    for c in candidates:
        if c not in out:
            out.append(c)
    return out


def _eodhd_base_candidates() -> List[str]:
    primary = EODHD_BASE_URL.rstrip("/")
    fallbacks = ["https://eodhd.com", "https://eodhistoricaldata.com"]
    out = [primary] if primary else []
    for f in fallbacks:
        if f not in out:
            out.append(f)
    return out


def _eodhd_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://eodhd.com/",
    }


def _extract_error_message(resp: requests.Response) -> str:
    try:
        body = resp.json() if resp.content else {}
        if isinstance(body, dict):
            msg = body.get("message") or body.get("error") or body.get("errors")
            if msg:
                return str(msg)
        if isinstance(body, list) and body:
            return str(body[0])
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text[:180] if text else ""


def _is_eodhd_eod_only_message(msg: str) -> bool:
    return "only eod data allowed for free users" in str(msg or "").lower()


@st.cache_data(ttl=1800, show_spinner=False)
def is_eodhd_eod_only(api_key: str) -> bool:
    """
    Detect whether EODHD key is restricted to EOD-only plan (fundamentals/news blocked).
    """
    if not api_key:
        return False
    try:
        for base_url in _eodhd_base_candidates():
            for ticker in ("INFY.NSE", "TCS.NSE", "RELIANCE.NSE"):
                url = f"{base_url}/api/fundamentals/{ticker}"
                r = session.get(
                    url,
                    params={"api_token": api_key.strip(), "fmt": "json"},
                    headers=_eodhd_headers(),
                    timeout=8,
                )
                if r.status_code == 200:
                    return False
                if r.status_code == 403 and _is_eodhd_eod_only_message(_extract_error_message(r)):
                    return True
        return False
    except Exception:
        return False


def _pick_num(d: Dict[str, object], keys: List[str]) -> Optional[float]:
    for k in keys:
        if k in d and d.get(k) not in (None, "", "NA", "N/A"):
            try:
                return float(d.get(k))
            except Exception:
                continue
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_eodhd_fundamentals(symbol: str, api_key: str) -> Dict[str, object]:
    """
    Fetch fundamentals from EODHD and map into FINNHUB_METRICS-compatible keys.
    """
    if not symbol or not api_key:
        return {}
    try:
        payload = None
        for base_url in _eodhd_base_candidates():
            for ticker in _eodhd_symbol_candidates(symbol):
                url = f"{base_url}/api/fundamentals/{ticker}"
                resp = session.get(
                    url,
                    params={"api_token": api_key.strip(), "fmt": "json"},
                    headers=_eodhd_headers(),
                    timeout=12,
                )
                if resp.status_code != 200:
                    continue
                j = resp.json() if resp.content else {}
                if isinstance(j, dict) and j:
                    payload = j
                    break
            if payload is not None:
                break
        if not isinstance(payload, dict):
            return {}
        highlights = payload.get("Highlights", {}) if isinstance(payload.get("Highlights"), dict) else {}
        valuation = payload.get("Valuation", {}) if isinstance(payload.get("Valuation"), dict) else {}
        technicals = payload.get("Technicals", {}) if isinstance(payload.get("Technicals"), dict) else {}

        out = {
            "peBasicExclExtraTTM": _pick_num(highlights, ["PERatio"]) or _pick_num(valuation, ["TrailingPE"]),
            "pbAnnual": _pick_num(highlights, ["PriceBookMRQ"]) or _pick_num(valuation, ["PriceBook"]),
            "epsBasicExclExtraItemsTTM": _pick_num(highlights, ["EarningsShare"]),
            "revenueGrowthTTMYoy": _pick_num(highlights, ["QuarterlyRevenueGrowthYOY"]),
            "grossMarginTTM": _pick_num(highlights, ["GrossProfitMargin"]),
            "debtEquityAnnual": _pick_num(highlights, ["DebtEquity"]),
            "dividendYieldIndicatedAnnual": _pick_num(highlights, ["DividendYield"]),
            "52WeekHigh": _pick_num(highlights, ["52WeekHigh"]) or _pick_num(technicals, ["52WeekHigh"]),
            "52WeekLow": _pick_num(highlights, ["52WeekLow"]) or _pick_num(technicals, ["52WeekLow"]),
            "beta": _pick_num(highlights, ["Beta"]),
        }
        return out
    except Exception:
        return {}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_eodhd_stock_news(symbol: str, api_key: str, days_back: int = 7) -> pd.DataFrame:
    """
    Fetch symbol-level news from EODHD.
    """
    cols = ["datetime", "headline", "summary", "source", "url"]
    if not symbol or not api_key:
        return pd.DataFrame(columns=cols)
    try:
        dt_to = datetime.utcnow().date()
        dt_from = dt_to - timedelta(days=max(1, int(days_back)))
        rows = []
        for base_url in _eodhd_base_candidates():
            for ticker in _eodhd_symbol_candidates(symbol):
                url = f"{base_url}/api/news"
                params = {
                    "api_token": api_key.strip(),
                    "fmt": "json",
                    "s": ticker,
                    "from": str(dt_from),
                    "to": str(dt_to),
                    "limit": 50,
                }
                resp = session.get(url, params=params, headers=_eodhd_headers(), timeout=12)
                if resp.status_code != 200:
                    continue
                j = resp.json() if resp.content else []
                if isinstance(j, list) and len(j) > 0:
                    rows = j
                    break
            if rows:
                break
        if not isinstance(rows, list):
            return pd.DataFrame(columns=cols)
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append(
                {
                    "datetime": pd.to_datetime(r.get("date"), errors="coerce"),
                    "headline": str(r.get("title", "")).strip(),
                    "summary": str(r.get("content", "")).strip(),
                    "source": str(r.get("source", "")).strip(),
                    "url": str(r.get("link", "")).strip(),
                }
            )
        df = pd.DataFrame(out)
        if df.empty:
            return pd.DataFrame(columns=cols)
        return df.sort_values("datetime", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=cols)


@st.cache_data(ttl=900, show_spinner=False)
def fetch_eodhd_market_news(api_key: str, days_back: int = 7) -> pd.DataFrame:
    """
    Fetch broader market news stream from EODHD.
    """
    cols = ["datetime", "headline", "summary", "source", "url", "category"]
    if not api_key:
        return pd.DataFrame(columns=cols)
    try:
        dt_to = datetime.utcnow().date()
        dt_from = dt_to - timedelta(days=max(1, int(days_back)))
        url = f"{EODHD_BASE_URL}/api/news"
        params = {
            "api_token": api_key.strip(),
            "fmt": "json",
            "from": str(dt_from),
            "to": str(dt_to),
            "limit": 80,
        }
        resp = session.get(url, params=params, headers=_eodhd_headers(), timeout=12)
        if resp.status_code != 200:
            return pd.DataFrame(columns=cols)
        rows = resp.json() if resp.content else []
        if not isinstance(rows, list):
            return pd.DataFrame(columns=cols)
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append(
                {
                    "datetime": pd.to_datetime(r.get("date"), errors="coerce"),
                    "headline": str(r.get("title", "")).strip(),
                    "summary": str(r.get("content", "")).strip(),
                    "source": str(r.get("source", "")).strip(),
                    "url": str(r.get("link", "")).strip(),
                    "category": "india",
                }
            )
        df = pd.DataFrame(out)
        if df.empty:
            return pd.DataFrame(columns=cols)
        return df.sort_values("datetime", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=cols)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_finnhub_fundamentals(symbol_ns: str, api_key: str) -> Dict[str, object]:
    """
    Fetch basic financials for one NSE stock from Finnhub.
    Returns metric dict, or {} on any failure.
    """
    if not symbol_ns or not api_key:
        return {}
    try:
        import finnhub

        client = finnhub.Client(api_key=api_key)
        fh_symbol = _to_finnhub_nse_symbol(symbol_ns)
        if not fh_symbol:
            return {}
        payload = client.company_basic_financials(fh_symbol, "all") or {}
        metrics = payload.get("metric", {}) if isinstance(payload, dict) else {}
        if not isinstance(metrics, dict):
            return {}
        return {k: metrics.get(k) for k in FINNHUB_METRICS}
    except Exception:
        return {}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_finnhub_stock_news(symbol_ns: str, api_key: str, days_back: int = 7) -> pd.DataFrame:
    """
    Fetch recent stock-specific news from Finnhub.
    Returns DataFrame sorted by datetime DESC, empty on failure.
    """
    if not symbol_ns or not api_key:
        return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url"])
    try:
        import finnhub

        client = finnhub.Client(api_key=api_key)
        fh_symbol = _to_finnhub_nse_symbol(symbol_ns)
        if not fh_symbol:
            return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url"])
        dt_to = datetime.utcnow().date()
        dt_from = dt_to - timedelta(days=max(1, int(days_back)))
        rows = client.company_news(fh_symbol, _from=str(dt_from), to=str(dt_to)) or []
        data = []
        for r in rows:
            ts = pd.to_datetime(r.get("datetime"), unit="s", errors="coerce")
            data.append(
                {
                    "datetime": ts,
                    "headline": str(r.get("headline", "")).strip(),
                    "summary": str(r.get("summary", "")).strip(),
                    "source": str(r.get("source", "")).strip(),
                    "url": str(r.get("url", "")).strip(),
                }
            )
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url"])
        return df.sort_values("datetime", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url"])


@st.cache_data(ttl=900, show_spinner=False)
def fetch_finnhub_market_news(api_key: str, category: str = "general") -> pd.DataFrame:
    """
    Fetch general market news from Finnhub.
    Returns DataFrame sorted by datetime DESC, empty on failure.
    """
    if not api_key:
        return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url", "category"])
    try:
        import finnhub

        client = finnhub.Client(api_key=api_key)
        rows = client.general_news(category, min_id=0) or []
        data = []
        for r in rows:
            ts = pd.to_datetime(r.get("datetime"), unit="s", errors="coerce")
            data.append(
                {
                    "datetime": ts,
                    "headline": str(r.get("headline", "")).strip(),
                    "summary": str(r.get("summary", "")).strip(),
                    "source": str(r.get("source", "")).strip(),
                    "url": str(r.get("url", "")).strip(),
                    "category": str(category),
                }
            )
        df = pd.DataFrame(data)
        if df.empty:
            return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url", "category"])
        return df.sort_values("datetime", ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["datetime", "headline", "summary", "source", "url", "category"])


def fetch_finnhub_fundamentals_batch(symbols_ns: List[str], api_key: str) -> Dict[str, Dict[str, object]]:
    """
    Fetch fundamentals for multiple NSE symbols.
    Not cached at batch level; individual fetches are cached.
    """
    out: Dict[str, Dict[str, object]] = {}
    if not api_key:
        return out
    for sym in symbols_ns or []:
        try:
            out[sym] = fetch_finnhub_fundamentals(sym, api_key)
            time.sleep(max(0.0, float(FINNHUB_RATE_LIMIT_PAUSE)))
        except Exception:
            out[sym] = {}
    return out


def fetch_equity_fundamentals(symbol: str, finnhub_api_key: str = "", eodhd_api_key: str = "") -> Dict[str, object]:
    """
    Provider router:
    - NSE symbols (.NS): EODHD primary -> Finnhub fallback
    - Others: Finnhub primary -> EODHD fallback
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {}
    if sym.endswith(".NS"):
        if eodhd_api_key and not is_eodhd_eod_only(eodhd_api_key):
            e = fetch_eodhd_fundamentals(sym, eodhd_api_key)
            if e:
                return e
        if finnhub_api_key:
            return fetch_finnhub_fundamentals(sym, finnhub_api_key)
        return {}
    if finnhub_api_key:
        f = fetch_finnhub_fundamentals(sym, finnhub_api_key)
        if f:
            return f
    if eodhd_api_key:
        return fetch_eodhd_fundamentals(sym, eodhd_api_key)
    return {}


def fetch_equity_fundamentals_batch(
    symbols: List[str],
    finnhub_api_key: str = "",
    eodhd_api_key: str = "",
) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for sym in symbols or []:
        out[sym] = fetch_equity_fundamentals(sym, finnhub_api_key=finnhub_api_key, eodhd_api_key=eodhd_api_key)
        # Respect free-tier pacing for both providers.
        pause = max(float(FINNHUB_RATE_LIMIT_PAUSE), float(EODHD_RATE_LIMIT_PAUSE))
        time.sleep(max(0.0, pause))
    return out


def fetch_equity_stock_news(
    symbol: str,
    finnhub_api_key: str = "",
    eodhd_api_key: str = "",
    days_back: int = 7,
) -> pd.DataFrame:
    sym = str(symbol or "").upper().strip()
    cols = ["datetime", "headline", "summary", "source", "url"]
    if not sym:
        return pd.DataFrame(columns=cols)
    if sym.endswith(".NS"):
        if eodhd_api_key and not is_eodhd_eod_only(eodhd_api_key):
            e = fetch_eodhd_stock_news(sym, eodhd_api_key, days_back=days_back)
            if not e.empty:
                return e
        if finnhub_api_key:
            return fetch_finnhub_stock_news(sym, finnhub_api_key, days_back=days_back)
        return pd.DataFrame(columns=cols)
    if finnhub_api_key:
        f = fetch_finnhub_stock_news(sym, finnhub_api_key, days_back=days_back)
        if not f.empty:
            return f
    if eodhd_api_key:
        return fetch_eodhd_stock_news(sym, eodhd_api_key, days_back=days_back)
    return pd.DataFrame(columns=cols)


@st.cache_data(ttl=300, show_spinner=False)
def probe_market_data_providers(
    finnhub_api_key: str = "",
    eodhd_api_key: str = "",
    india_symbol_ns: str = "INFY.NS",
    us_symbol: str = "AAPL",
) -> Dict[str, object]:
    """
    Lightweight provider diagnostics to surface key/network issues in UI.
    """
    out: Dict[str, object] = {
        "finnhub": {"configured": bool(finnhub_api_key), "ok": False, "status_code": None, "message": ""},
        "eodhd": {"configured": bool(eodhd_api_key), "ok": False, "status_code": None, "message": "", "eod_only": False},
    }

    if finnhub_api_key:
        try:
            url = "https://finnhub.io/api/v1/quote"
            r = session.get(url, params={"symbol": us_symbol, "token": finnhub_api_key}, timeout=10)
            out["finnhub"]["status_code"] = int(r.status_code)
            if r.status_code == 200:
                out["finnhub"]["ok"] = True
                out["finnhub"]["message"] = "OK"
            elif r.status_code == 401:
                out["finnhub"]["message"] = "Invalid API key"
            else:
                out["finnhub"]["message"] = f"HTTP {r.status_code}"
        except Exception as exc:
            out["finnhub"]["message"] = f"Network/Error: {exc}"

    if eodhd_api_key:
        try:
            last_status = None
            success_note = None
            last_resp = None
            for base_url in _eodhd_base_candidates():
                for ticker in _eodhd_symbol_candidates(india_symbol_ns):
                    url = f"{base_url}/api/fundamentals/{ticker}"
                    r = session.get(
                        url,
                        params={"api_token": eodhd_api_key.strip(), "fmt": "json"},
                        headers=_eodhd_headers(),
                        timeout=10,
                    )
                    last_resp = r
                    last_status = int(r.status_code)
                    if r.status_code == 200:
                        out["eodhd"]["ok"] = True
                        out["eodhd"]["status_code"] = 200
                        success_note = f"OK via {base_url} / {ticker}"
                        break
                if out["eodhd"]["ok"]:
                    break
            if out["eodhd"]["ok"]:
                out["eodhd"]["message"] = success_note or "OK"
            else:
                out["eodhd"]["status_code"] = last_status
                if last_status == 401:
                    out["eodhd"]["message"] = "Invalid API key"
                elif last_status == 403:
                    detail = _extract_error_message(last_resp) if last_resp is not None else ""
                    out["eodhd"]["eod_only"] = _is_eodhd_eod_only_message(detail)
                    out["eodhd"]["message"] = (
                        "Forbidden (key plan/entitlement or endpoint blocking). "
                        + detail
                    ).strip()
                else:
                    detail = _extract_error_message(last_resp) if last_resp is not None else ""
                    out["eodhd"]["message"] = f"HTTP {last_status}" + (f" - {detail}" if detail else "")
        except Exception as exc:
            out["eodhd"]["message"] = f"Network/Error: {exc}"

    return out


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
