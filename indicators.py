# indicators.py - FIXED VERSION
# Handles both DataFrame and Series inputs

import pandas as pd
import numpy as np


# ==================== RSI ====================
def calculate_rsi(data, period=14):
    """
    Wilder RSI calculation

    Args:
        data: Either DataFrame with 'Close' column OR Series of close prices
        period: RSI period (default 14)

    Returns:
        Series with RSI values
    """
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    # Handle both DataFrame and Series
    if isinstance(data, pd.DataFrame):
        close = data['Close']
    else:
        close = data  # Already a Series

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


# ==================== EMA ====================
def calculate_ema(data, period=20):
    """
    Exponential Moving Average

    Args:
        data: Either DataFrame with 'Close' column OR Series of close prices
        period: EMA period

    Returns:
        Series with EMA values
    """
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    # Handle both DataFrame and Series
    if isinstance(data, pd.DataFrame):
        close = data['Close']
    else:
        close = data  # Already a Series

    return close.ewm(span=period, adjust=False).mean()


# ==================== ATR ====================
def calculate_atr(data, period=14):
    """
    Average True Range

    Args:
        data: DataFrame with 'High', 'Low', 'Close' columns
        period: ATR period

    Returns:
        Series with ATR values
    """
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    # ATR requires DataFrame with OHLC data
    if not isinstance(data, pd.DataFrame):
        raise ValueError("ATR calculation requires DataFrame with High, Low, Close columns")

    high = data['High']
    low = data['Low']
    close = data['Close'].shift(1)

    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()

    return atr


# ==================== PRICE CHANGE ====================
def calculate_change(df):
    """
    Calculate price change

    Args:
        df: DataFrame with 'Close' column OR Series

    Returns:
        (current_price, change_percent) tuple
    """
    if df is None or len(df) < 2:
        return None, None

    # Handle both DataFrame and Series
    if isinstance(df, pd.DataFrame):
        close = df['Close']
    else:
        close = df

    current = close.iloc[-1]
    prev = close.iloc[-2]

    if prev == 0:
        return current, 0

    change_pct = ((current - prev) / prev) * 100
    return current, change_pct


# ==================== ADDITIONAL INDICATORS ====================

def calculate_sma(data, period=20):
    """
    Simple Moving Average

    Args:
        data: DataFrame with 'Close' OR Series
        period: SMA period

    Returns:
        Series with SMA values
    """
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    if isinstance(data, pd.DataFrame):
        close = data['Close']
    else:
        close = data

    return close.rolling(window=period).mean()


def calculate_bollinger_bands(data, period=20, std_dev=2):
    """
    Bollinger Bands

    Args:
        data: DataFrame with 'Close' OR Series
        period: Period for moving average
        std_dev: Number of standard deviations

    Returns:
        (upper_band, middle_band, lower_band) tuple of Series
    """
    if data is None or len(data) < period:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    if isinstance(data, pd.DataFrame):
        close = data['Close']
    else:
        close = data

    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()

    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    return upper, middle, lower


def calculate_macd(data, fast=12, slow=26, signal=9):
    """
    MACD (Moving Average Convergence Divergence)

    Args:
        data: DataFrame with 'Close' OR Series
        fast: Fast EMA period
        slow: Slow EMA period
        signal: Signal line period

    Returns:
        (macd_line, signal_line, histogram) tuple of Series
    """
    if data is None or len(data) < slow:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    if isinstance(data, pd.DataFrame):
        close = data['Close']
    else:
        close = data

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_stochastic(data, k_period=14, d_period=3):
    """
    Stochastic Oscillator

    Args:
        data: DataFrame with 'High', 'Low', 'Close'
        k_period: %K period
        d_period: %D period (smoothing)

    Returns:
        (k_line, d_line) tuple of Series
    """
    if data is None or len(data) < k_period:
        empty = pd.Series(dtype=float)
        return empty, empty

    if not isinstance(data, pd.DataFrame):
        raise ValueError("Stochastic requires DataFrame with High, Low, Close")

    high = data['High']
    low = data['Low']
    close = data['Close']

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    k_line = 100 * ((close - lowest_low) / (highest_high - lowest_low))
    d_line = k_line.rolling(window=d_period).mean()

    return k_line, d_line