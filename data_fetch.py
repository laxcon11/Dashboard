"""
Shared data fetching utilities
Used by:
- NSE Dashboard
- Global Markets Dashboard
- Liquidity Dashboard
"""

import yfinance as yf
import pandas as pd
import streamlit as st
import logging
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ==================== SYMBOL VALIDATION ====================

def validate_symbol(symbol: str) -> bool:
    """Accept all reasonable symbols"""
    if not symbol or not isinstance(symbol, str):
        return False

    symbol = symbol.strip().upper()
    return len(symbol) > 0 and len(symbol) < 20  # Accept anything reasonable


# ==================== BATCH DOWNLOAD ====================

@st.cache_data(ttl=300, show_spinner=False)
def batch_download(symbols: List[str], period: str = "1mo") -> Dict[str, pd.DataFrame]:
    """
    Batch download multiple symbols efficiently.

    Returns:
        Dict[symbol -> DataFrame]
    """

    valid_symbols = [s for s in symbols if validate_symbol(s)]

    if not valid_symbols:
        logger.warning("No valid symbols provided for download")
        return {}

    try:
        logger.info(f"Downloading {len(valid_symbols)} symbols")

        # FIXED: Use auto_adjust=True for better compatibility with indices/forex/commodities
        data = yf.download(
            valid_symbols,
            period=period,
            group_by="ticker",
            progress=False,
            threads=True,
            auto_adjust=True  # Changed from False - better for non-stock symbols
        )

        result = {}

        # Single symbol case
        if len(valid_symbols) == 1:
            symbol = valid_symbols[0]
            if isinstance(data, pd.DataFrame) and not data.empty:
                result[symbol] = data
            return result

        # Multiple symbols case
        for symbol in valid_symbols:
            try:
                # Access the symbol's data
                df = data[symbol]

                # Verify it's valid
                if isinstance(df, pd.DataFrame) and not df.empty:
                    # Check if Close column has actual data (not all NaN)
                    if 'Close' in df.columns and not df['Close'].isna().all():
                        result[symbol] = df
                    else:
                        logger.warning(f"Symbol {symbol} has no valid Close data")
                else:
                    logger.warning(f"Symbol {symbol} returned empty DataFrame")

            except KeyError:
                logger.warning(f"Symbol {symbol} not in batch results")
                continue
            except Exception as e:
                logger.error(f"Error extracting {symbol}: {e}")
                continue

        logger.info(f"Downloaded {len(result)}/{len(valid_symbols)} symbols successfully")
        return result

    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        return {}


# ==================== PRICE EXTRACTION ====================

def extract_price_data(df: Optional[pd.DataFrame]):
    """
    Extract latest price and percent change
    Handles cases with insufficient historical data
    Works with both 'Close' and 'Adj Close' columns
    """
    if df is None or len(df) == 0:
        return None, None, None

    try:
        # Try 'Close' first, then 'Adj Close' (depends on auto_adjust setting)
        if 'Close' in df.columns:
            close_col = 'Close'
        elif 'Adj Close' in df.columns:
            close_col = 'Adj Close'
        else:
            logger.error(f"No Close or Adj Close column. Columns: {df.columns.tolist()}")
            return None, None, None

        current = df[close_col].iloc[-1]

        # Check if current price is valid
        if pd.isna(current):
            logger.warning(f"Current price is NaN for column {close_col}")
            return None, None, None

        # If we have at least 2 data points, calculate change
        if len(df) >= 2:
            prev = df[close_col].iloc[-2]

            if prev == 0 or pd.isna(prev):
                return current, 0, 0

            change = current - prev
            change_pct = (change / prev) * 100

            return current, change, change_pct
        else:
            # Only 1 data point - return price without change
            return current, None, None

    except Exception as e:
        logger.error(f"Price extraction failed: {e}")
        return None, None, None


def get_ticker_price(symbol: str):
    """
    Fallback: Get current price from ticker info
    Use when historical data fails
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


# ==================== LAST N DAYS HELPER ====================

def get_last_n_days(df: pd.DataFrame, days: int = 5) -> pd.DataFrame:
    """Safely slice last N rows"""
    if df is None or len(df) == 0:
        return df
    return df.tail(days)


# ==================== FRED DATA FETCH ====================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred_series(series_id: str, api_key: str, days: int = 30):
    """
    Fetch FRED series as DataFrame with date + value

    Returns:
        DataFrame(date, value)
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
            "&limit=500"
        )

        response = requests.get(url, timeout=10)
        data = response.json()

        observations = data.get("observations", [])
        if not observations:
            return None

        df = pd.DataFrame(observations)

        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])

        df = df.dropna().sort_values("date")

        return df.tail(days)

    except Exception as e:
        logger.error(f"FRED fetch failed for {series_id}: {e}")
        return None

# ==================== CHART PREPARATION (Macro Dashboards) ====================



def prepare_timeseries_for_chart(df):
    """
    Prepare dataframe for smooth plotting:
    - Ensures datetime index
    - Fills missing calendar days
    - Forward fills Close values
    Safe helper for macro dashboards.
    """

    if df is None or len(df) == 0:
        return df

    try:
        df = df.copy()

        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Build continuous calendar index
        full_index = pd.date_range(
            start=df.index.min(),
            end=df.index.max(),
            freq="D"
        )

        df = df.reindex(full_index)

        # Forward fill numeric columns safely
        numeric_cols = df.select_dtypes(include=["number"]).columns
        df[numeric_cols] = df[numeric_cols].ffill()

        return df

    except Exception:
        return df


def fetch_india_vix():
    """Fetch India VIX from NSE API"""
    try:
        url = "https://www.nseindia.com/api/allIndices"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/"
        }

        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)

        response = session.get(url, headers=headers, timeout=5)
        data = response.json()

        for item in data.get("data", []):
            if item.get("index") == "INDIA VIX":
                price = float(item.get("last"))
                change_pct = float(item.get("percentChange"))
                return price, change_pct

        return None, None

    except Exception as e:
        logger.error(f"India VIX fetch failed: {e}")
        return None, None
