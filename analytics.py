"""
Centralized Analysis Logic for Trading Dashboard Suite
Contains pure calculation functions for technical analysis and signals.
"""

import pandas as pd
import numpy as np
from indicators import calculate_rsi, calculate_ema, calculate_atr
from config import BREAKOUT_WINDOW

def detect_gap(df):
    """Detect gap up/down"""
    if df is None or len(df) < 2:
        return 0, 0

    try:
        prev_close = df['Close'].iloc[-2]
        current_open = df['Open'].iloc[-1]

        if prev_close and current_open and prev_close != 0:
            gap = current_open - prev_close
            gap_pct = (gap / prev_close) * 100
            return gap, gap_pct
    except:
        pass

    return 0, 0


def calculate_volume_ratio(df) -> float:
    """Calculate volume ratio compared to 20-day average"""
    if df is None or len(df) < 20:
        return 0

    try:
        avg_vol = df['Volume'].tail(20).mean()
        latest_vol = df['Volume'].iloc[-1]

        if avg_vol == 0 or pd.isna(avg_vol):
            return 0

        return latest_vol / avg_vol
    except:
        return 0


def calculate_vwap(df):
    """Calculate VWAP (Volume Weighted Average Price)"""
    if df is None or len(df) < 1:
        return None

    try:
        # Typical price
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3

        # VWAP = Cumulative(Typical Price * Volume) / Cumulative(Volume)
        vwap = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()

        return vwap
    except:
        return None


def detect_breakout(df, window: int = BREAKOUT_WINDOW) -> bool:
    """Detect breakout above N-day high"""
    if df is None or len(df) < window + 1:
        return False

    try:
        recent = df['High'].iloc[-(window+1):-1]
        if len(recent) == 0:
            return False
        recent_high = recent.max()
        current = df['Close'].iloc[-1]
        return current > recent_high
    except:
        return False


def detect_nr7(df) -> bool:
    """Detect if today is NR7 (Narrowest Range in 7 days)"""
    if df is None or len(df) < 7:
        return False
        
    try:
        df = df.copy()
        df['Range'] = df['High'] - df['Low']
        
        recent = df.tail(7)
        if len(recent) < 7:
            return False
            
        current_range = recent['Range'].iloc[-1]
        min_range = recent['Range'].min()
        
        return current_range == min_range
    except:
        return False


def calculate_relative_strength(symbol_df, index_df, period: int = 20) -> float:
    """Calculate relative strength vs index over a given period"""
    if symbol_df is None or index_df is None:
        return 0

    try:
        if len(symbol_df) < period or len(index_df) < period:
            return 0

        stock_return = ((symbol_df['Close'].iloc[-1] / symbol_df['Close'].iloc[-period]) - 1) * 100
        index_return = ((index_df['Close'].iloc[-1] / index_df['Close'].iloc[-period]) - 1) * 100

        return stock_return - index_return
    except:
        return 0


def calculate_momentum_score(stock_data, index_data) -> int:
    """Calculate Momentum / Breakout Score (0-10)"""
    if stock_data is None or len(stock_data) < 50:
        return 0
        
    score = 0
    current = stock_data['Close'].iloc[-1]
    
    # 1. Trend Alignment (0-3)
    try:
        ema20 = calculate_ema(stock_data, 20).iloc[-1]
        ema50 = calculate_ema(stock_data, 50).iloc[-1]
        if current > ema20 > ema50:
            score += 3
        elif current > ema20:
            score += 1
    except: pass
    
    # 2. RSI Strength (0-2)
    try:
        rsi = calculate_rsi(stock_data).iloc[-1]
        if rsi > 60: score += 2
        elif rsi > 55: score += 1
    except: pass
    
    # 3. Relative Strength (0-2)
    rs = calculate_relative_strength(stock_data, index_data)
    if rs > 2: score += 2
    elif rs > 0: score += 1
    
    # 4. Breakout / Volume (0-3)
    if detect_breakout(stock_data): score += 3
    elif calculate_volume_ratio(stock_data) > 1.5: score += 1
    
    return score


def calculate_pullback_score(stock_data, index_data) -> int:
    """Calculate Pullback / Value Score (0-10)"""
    if stock_data is None or len(stock_data) < 50:
        return 0
        
    score = 0
    current = stock_data['Close'].iloc[-1]
    
    # 1. Buying the Dip (Near EMA 20) (0-4)
    try:
        ema20 = calculate_ema(stock_data, 20).iloc[-1]
        dist_pct = (current - ema20) / ema20 * 100
        
        if 0 < dist_pct <= 2: score += 4  # Perfect pullback
        elif 0 < dist_pct <= 4: score += 2 # Decent pullback
        elif -2 <= dist_pct <= 0: score += 3 # Slight undercut
    except: pass
    
    # 2. RSI Reset (0-3)
    try:
        rsi = calculate_rsi(stock_data).iloc[-1]
        if 40 <= rsi <= 55: score += 3 # Perfect reset zone
        elif 35 <= rsi < 40: score += 1
        elif 55 < rsi <= 60: score += 1
    except: pass
    
    # 3. Volatility Compression (0-3)
    try:
        if detect_nr7(stock_data):
            score += 3
        elif (stock_data['High'].iloc[-1] - stock_data['Low'].iloc[-1]) < calculate_atr(stock_data).iloc[-1] * 0.7:
             score += 1
    except: pass

    return min(score, 10)



def calculate_liquidity_score(liquidity_data, lookback_days: int = 1) -> int:
    """
    Standardized liquidity score logic:
    Positive score = liquidity improving
    Negative score = liquidity tightening
    
    Args:
        liquidity_data: Dictionary of FRED dataframes
        lookback_days: How many days back to compare (1 for Daily, 7 for Weekly)
    """
    score = 0
    try:
        # Fed Balance Sheet rising = positive
        fed = liquidity_data.get("Fed Balance Sheet")
        if fed is not None and len(fed) > lookback_days:
            if fed["value"].iloc[-1] > fed["value"].iloc[-(lookback_days + 1)]:
                score += 2
            else:
                score -= 2

        # Reverse Repo falling = positive
        rrp = liquidity_data.get("Reverse Repo")
        if rrp is not None and len(rrp) > lookback_days:
            if rrp["value"].iloc[-1] < rrp["value"].iloc[-(lookback_days + 1)]:
                score += 1
            else:
                score -= 1

        # TGA falling = positive
        tga = liquidity_data.get("Treasury General Account")
        if tga is not None and len(tga) > lookback_days:
            if tga["value"].iloc[-1] < tga["value"].iloc[-(lookback_days + 1)]:
                score += 1
            else:
                score -= 1
    except:
        pass

    return score


def get_liquidity_stance(liquidity_data, sofr_spread: float = 0):
    """
    Analyzes Daily vs Weekly convergence to determine the 'Decision POV'
    
    Returns: (regime_name, color, decision_msg)
    """
    if not liquidity_data or not any(df is not None for df in liquidity_data.values()):
        return "Neutral", "gray", "Insufficient liquidity data to generate stance."

    daily_score = calculate_liquidity_score(liquidity_data, lookback_days=1)
    weekly_score = calculate_liquidity_score(liquidity_data, lookback_days=6) # 1 week approx 
    
    # Adjust for SOFR stress if provided
    # SOFR > IORB is a major penalty (tightening)
    if sofr_spread > 5: # Critical stress
        daily_score -= 4
        weekly_score -= 4
    elif sofr_spread > 0: # Light tightening
        daily_score -= 1
        
    # Convergence Analysis
    if daily_score > 0 and weekly_score > 0:
        return "🌊 Expansion", "success", "**High Conviction Risk-On**: Liquidity is rising on all timeframes. The tide is lifting all boats."
    
    if daily_score < 0 and weekly_score < 0:
        return "🌵 Tightening", "error", "**High Conviction Risk-Off**: Liquidity is draining steadily. Prepare for market headwinds and limit risk."
        
    if daily_score > 0 and weekly_score < 0:
        return "🟡 Relief Rally", "warning", "**Short-term Relief**: The weekly plumbing is still tightening, but today show a minor injection. Likely a temporary bounce."
        
    if daily_score < 0 and weekly_score > 0:
        return "⚖️ Healthy Cooling", "warning", "**Structural Support**: The weekly trend remains supportive, but liquidity had a minor daily drain. Potential buy-the-dip zone."
        
    return "Neutral", "gray", "Liquidity plumbing is in a balanced consolidation phase."


def calculate_support_resistance(df, period: int = 20):
    """Calculate support and resistance levels based on recent highs/lows"""
    if df is None or len(df) < period:
        return None, None

    try:
        recent = df.tail(period)
        resistance = recent['High'].max()
        support = recent['Low'].min()
        return support, resistance
    except:
        return None, None


# ==================== LEADING INDICATORS ====================

def calculate_copper_gold_signal(data):
    """Calculate Copper/Gold ratio signal"""
    copper = data.get("HG=F")
    gold = data.get("GC=F")

    if copper is None or gold is None:
        return 0, 0, "No Data"
    if "Close" not in copper.columns or "Close" not in gold.columns:
        return 0, 0, "No Data"

    try:
        df = pd.concat([
            copper["Close"].rename("copper"),
            gold["Close"].rename("gold")
        ], axis=1).ffill().dropna()

        if len(df) < 15:
            return 0, 0, "Insufficient Data"

        ratio = df["copper"] / df["gold"]
        ma = ratio.rolling(10).mean()

        latest_ratio = ratio.iloc[-1]
        latest_ma = ma.iloc[-1]

        score = 1 if latest_ratio > latest_ma else -1
        signal = "Copper/Gold Positive" if score == 1 else "Copper/Gold Defensive"

        return float(latest_ratio), score, signal
    except:
        return 0, 0, "Error"


def calculate_credit_spread_signal(data):
    """Calculate HYG/LQD credit spread signal"""
    hyg = data.get("HYG")
    lqd = data.get("LQD")

    if hyg is None or lqd is None:
        return 0, 0, "No Data"
    if "Close" not in hyg.columns or "Close" not in lqd.columns:
        return 0, 0, "No Data"

    try:
        df = pd.concat([
            hyg["Close"].rename("hyg"),
            lqd["Close"].rename("lqd")
        ], axis=1).ffill().dropna()

        if len(df) < 15:
            return 0, 0, "Insufficient Data"

        ratio = df["hyg"] / df["lqd"]
        ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()

        if len(ratio) < 10:
            return 0, 0, "Insufficient Data"

        ma = ratio.rolling(10).mean()

        latest_ratio = ratio.iloc[-1]
        latest_ma = ma.iloc[-1]

        score = 1 if latest_ratio > latest_ma else -1
        signal = "Credit Risk On" if score == 1 else "Credit Risk Off"

        return float(latest_ratio), score, signal
    except:
        return 0, 0, "Error"


def calculate_dollar_trend_signal(market_data):
    """Calculate Dollar Index trend signal"""
    dxy = market_data.get("DX-Y.NYB")

    if dxy is None or len(dxy) < 10:
        return 0, 0, "No Data"

    try:
        close_series = dxy["Close"].dropna()
        if len(close_series) < 10:
            return 0, 0, "Insufficient Data"
            
        latest = close_series.iloc[-1]
        ma = close_series.rolling(10).mean().iloc[-1]

        score = -1 if latest > ma else 1  # Rising dollar = risk off
        signal = "Dollar Rising" if score == -1 else "Dollar Stable"

        return float(latest), score, signal
    except:
        return 0, 0, "Error"


def calculate_yield_trend_signal(market_data):
    """Calculate 10Y Yield trend signal"""
    y10 = market_data.get("^TNX")

    if y10 is None or len(y10) < 10:
        return 0, 0, "No Data"

    if "Close" not in y10.columns:
        return 0, 0, "No Close Data"

    try:
        # Get clean series
        close_series = y10["Close"].dropna()

        if len(close_series) < 10:
            return 0, 0, "Insufficient Data"

        latest = close_series.iloc[-1]
        ma = close_series.rolling(10).mean().iloc[-1]

        score = -1 if latest > ma else 1  # Rising yields = tightening
        signal = "Yields Rising" if score == -1 else "Yields Stable"

        return float(latest), score, signal
    except:
        return 0, 0, "Error"
