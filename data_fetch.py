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
from typing import Dict, List, Optional, Tuple
from config import CACHE_TTL

# ==================== LOGGING SETUP ====================

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s:%(name)s:%(message)s"
)

# Shared session for FRED requests
session = requests.Session()


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
        logger.info(f"Downloading {len(valid_symbols)} symbols")

        # Retry logic for reliability
        data = None
        for attempt in range(2):
            try:
                data = yf.download(
                    tickers=valid_symbols,
                    period=period,
                    group_by="ticker",
                    progress=False,
                    threads=True,
                    auto_adjust=True,  # Better compatibility with indices/forex
                    timeout=20
                )
                break
            except Exception as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                if attempt == 1:
                    raise

        result = {}

        # Handle single symbol case
        if len(valid_symbols) == 1:
            symbol = valid_symbols[0]

            if isinstance(data, pd.DataFrame) and not data.empty:
                if "Close" in data.columns:
                    result[symbol] = data
                else:
                    # Handle multiindex for single ticker
                    try:
                        result[symbol] = data.xs(symbol, axis=1, level=0)
                    except Exception:
                        logger.warning(f"Could not parse data for {symbol}")

            return result

        # Handle multiple symbols
        for symbol in valid_symbols:
            try:
                df = data[symbol]

                if isinstance(df, pd.DataFrame) and not df.empty:
                    close_series = df.get("Close")

                    # Validate Close column has data
                    if close_series is not None and not close_series.dropna().empty:
                        result[symbol] = df
                    else:
                        logger.warning(f"{symbol}: No valid Close data")
                else:
                    logger.warning(f"{symbol}: Empty DataFrame")

            except KeyError:
                logger.warning(f"{symbol}: Not in batch results")
            except Exception as e:
                logger.error(f"{symbol}: Extraction error - {e}")

        logger.info(f"Successfully downloaded {len(result)}/{len(valid_symbols)} symbols")
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

        return None, None, None

    except Exception as e:
        logger.error(f"Ticker info fetch failed for {symbol}: {e}")
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