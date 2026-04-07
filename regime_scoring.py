import pandas as pd
import numpy as np
from typing import Optional, Dict, Any

def clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

def calculate_z_score_sentiment(series: pd.Series, lookback: int = 180, inverse: bool = False, previous_sentiment: str = "Neutral") -> tuple[float, str]:
    """
    Standardizes a value using rolling Z-score and clamps it to [-1, 1].
    Uses Schmitt-trigger hysteresis to prevent whipsaw at boundaries.
    Z = (x - mu) / sigma
    """
    s = series.dropna()
    if len(s) < 20:
        return 0.0, "Neutral"
        
    tail = s.tail(lookback)
    mean = tail.mean()
    std = tail.std()
    
    if std == 0 or pd.isna(std):
        return 0.0, "Neutral"
        
    last_val = s.iloc[-1]
    z = (last_val - mean) / std
    
    score = clip(z / 2.0, -1.0, 1.0)
    if inverse:
        score = -score
    
    # Hysteresis (Schmitt-trigger): wider entry thresholds, narrower exit thresholds
    sentiment = previous_sentiment
    if previous_sentiment == "Neutral":
        # Need stronger signal to ENTER a directional stance
        if score >= 0.30: sentiment = "Bullish"
        elif score <= -0.30: sentiment = "Bearish"
    elif previous_sentiment == "Bullish":
        # Must cross zero to exit Bullish (not just dip below 0.25)
        if score <= 0.0: sentiment = "Neutral"
        elif score <= -0.30: sentiment = "Bearish"
    elif previous_sentiment == "Bearish":
        # Must cross zero to exit Bearish 
        if score >= 0.0: sentiment = "Neutral"
        elif score >= 0.30: sentiment = "Bullish"
    
    return float(score), sentiment

def calculate_impulse_sentiment(series: pd.Series, window: int = 5) -> tuple[float, str]:
    """
    Calculates the rate of change (impulse) and standardizes it.
    """
    s = series.dropna()
    if len(s) < window + 1:
        return 0.0, "Neutral"
        
    change = ((s.iloc[-1] / s.iloc[-(window + 1)]) - 1) * 100
    
    changes = (s.pct_change() * 100).dropna().tail(60)
    vol = changes.std()
    
    if vol == 0 or pd.isna(vol):
        score = clip(change, -1.0, 1.0)
    else:
        score = clip(change / (vol * (window ** 0.5)), -1.0, 1.0)
        
    sentiment = "Neutral"
    if score >= 0.25: sentiment = "Bullish"
    elif score <= -0.25: sentiment = "Bearish"
    
    return float(score), sentiment

def get_fixed_threshold_score(value: float, thresholds: Dict[float, float]) -> float:
    """
    Maps a value to a score based on fixed thresholds.
    thresholds: sorted dict or list of tuples
    Example: {70: 1.0, 55: 0.5, 40: 0.0, 25: -0.5, 0: -1.0}
    """
    sorted_thresholds = sorted(thresholds.items(), key=lambda x: x[0], reverse=True)
    for threshold, score in sorted_thresholds:
        if value >= threshold:
            return score
    return -1.0 # Default fallback


def percentile_score(value: float, history: pd.Series, lookback: int = 500) -> float:
    """
    Adaptive scoring: converts a raw value to [-1, +1] using its rank
    within a rolling history window. Automatically adapts to different
    market eras (bull, bear, recovery).
    """
    s = history.dropna().tail(lookback)
    if len(s) < 30:
        return 0.0  # Not enough history for reliable percentile
    rank = (s < value).mean()  # Fraction of historical values below current
    return float((rank - 0.5) * 2.0)  # Maps [0,1] -> [-1,+1]


def calculate_breadth_score(pct_above_200d: float, history: pd.Series | None = None) -> float:
    """
    Institutional Breadth Scoring.
    If history is provided, uses adaptive percentile scoring.
    Otherwise falls back to fixed thresholds:
    >70% (+1), 55-70% (+0.5), 40-55% (0), 25-40% (-0.5), <25% (-1)
    """
    if history is not None and not history.empty:
        return clip(percentile_score(pct_above_200d, history), -1.0, 1.0)
    # Fixed-threshold fallback
    if pct_above_200d >= 70: return 1.0
    if pct_above_200d >= 55: return 0.5
    if pct_above_200d >= 40: return 0.0
    if pct_above_200d >= 25: return -0.5
    return -1.0


def calculate_vix_score(vix_value: float, history: pd.Series | None = None) -> float:
    """
    India VIX Scoring (inverse: high VIX = bearish).
    If history is provided, uses adaptive percentile scoring.
    Otherwise falls back to fixed thresholds:
    <15 (+1), 15-20 (+0.5), 20-25 (0), 25-30 (-0.5), >30 (-1)
    """
    if history is not None and not history.empty:
        # Inverse: high VIX = low percentile score
        return clip(-percentile_score(vix_value, history), -1.0, 1.0)
    # Fixed-threshold fallback
    if vix_value <= 15: return 1.0
    if vix_value <= 20: return 0.5
    if vix_value <= 25: return 0.0
    if vix_value <= 30: return -0.5
    return -1.0


def calculate_yield_curve_score(spread: float, history: pd.Series | None = None) -> float:
    """
    Yield Curve Scoring.
    If history is provided, uses adaptive percentile scoring.
    Otherwise falls back to fixed thresholds:
    >1.0 (+1), 0.5-1.0 (+0.5), 0-0.5 (-0.5), <0 (-1)
    """
    if history is not None and not history.empty:
        return clip(percentile_score(spread, history), -1.0, 1.0)
    # Fixed-threshold fallback
    if spread >= 1.0: return 1.0
    if spread >= 0.5: return 0.5
    if spread >= 0.0: return -0.5
    return -1.0


def compute_nifty_200_breadth(df: pd.DataFrame, universe: list) -> float:
    """
    Efficiently calculates % of stocks above 200DMA from a broad local history.
    df: Dataframe with [date, symbol, close] columns.
    universe: List of Nifty 200 symbols.
    """
    if df.empty or not universe:
        return 0.0
        
    # Filter for universe
    sub = df[df["symbol"].isin(set(universe))].copy()
    if sub.empty:
        return 0.0
        
    # Ensure data is sorted for rolling window
    sub = sub.sort_values(["symbol", "date"])
    
    # We need enough history for rolling(200)
    # Using min_periods=120 to allow for partial breadth if data is slightly shy of 200 days
    sub["ma200"] = sub.groupby("symbol")["close"].transform(lambda x: x.rolling(window=200, min_periods=120).mean())
    
    # Get latest date available
    latest_date = sub["date"].max()
    latest_snapshot = sub[sub["date"] == latest_date].dropna(subset=["ma200"])
    
    if latest_snapshot.empty:
        return 0.0
        
    above_count = (latest_snapshot["close"] > latest_snapshot["ma200"]).sum()
    total_count = len(latest_snapshot)
    
    return (above_count / total_count) * 100
def compute_nifty_200_breadth_series(df: pd.DataFrame, universe: list) -> pd.Series:
    """
    Calculates % of stocks above 200DMA for ALL dates in the dataframe.
    Returns a pd.Series indexed by date.
    """
    if df.empty or not universe:
        return pd.Series(dtype=float)
        
    sub = df[df["symbol"].isin(set(universe))].copy()
    if sub.empty:
        return pd.Series(dtype=float)
        
    sub = sub.sort_values(["symbol", "date"])
    # Using min_periods=120 to allow for partial breadth if data is slightly shy of 200 days
    sub["ma200"] = sub.groupby("symbol")["close"].transform(lambda x: x.rolling(window=200, min_periods=120).mean())
    sub = sub.dropna(subset=["ma200"])
    
    if sub.empty:
        return pd.Series(dtype=float)

    # Calculate breadth for each date
    def calc_breadth_at_date(group):
        above = (group["close"] > group["ma200"]).sum()
        total = len(group)
        return (above / total) * 100 if total > 0 else 0.0

    series = sub.groupby("date").apply(calc_breadth_at_date, include_groups=False)
    return series
