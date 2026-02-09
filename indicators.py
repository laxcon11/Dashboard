# indicators.py

import pandas as pd
import numpy as np


# ==================== RSI ====================
def calculate_rsi(data, period=14):
    """Wilder RSI"""
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    delta = data['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


# ==================== EMA ====================
def calculate_ema(data, period=20):
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    return data['Close'].ewm(span=period, adjust=False).mean()


# ==================== ATR ====================
def calculate_atr(data, period=14):
    if data is None or len(data) < period:
        return pd.Series(dtype=float)

    high = data['High']
    low = data['Low']
    close = data['Close'].shift(1)

    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    return atr


# ==================== PRICE CHANGE ====================
def calculate_change(df):
    if df is None or len(df) < 2:
        return None, None

    current = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2]

    change_pct = ((current - prev) / prev) * 100
    return current, change_pct
