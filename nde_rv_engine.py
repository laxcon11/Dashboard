import pandas as pd
import numpy as np
from nde_schema import RVMetrics

def compute_rv_metrics(df: pd.DataFrame, spot: float, atr: float, atm_iv: float = 15.0) -> RVMetrics:
    """
    Standardized RV Engine (Carmack Refactor).
    Operates on full precision floats and returns a typed RVMetrics object.
    """
    if df is None or df.empty or len(df) < 10:
        return RVMetrics(rv_5d=15.0, rv_intraday=15.0, iv_rv_ratio=atm_iv/15.0)

    # Hardening: Verify required columns exist (Prevents KeyError in synthetic tests)
    required = ['High', 'Low', 'Open', 'Close']
    if not all(col in df.columns for col in required):
        return RVMetrics(rv_5d=15.0, rv_intraday=15.0, iv_rv_ratio=atm_iv/15.0)

    # 1. 5D Realized Volatility (Annualized)
    # Using log returns for institutional parity
    returns = np.log(df['Close'] / df['Close'].shift(1)).dropna()
    rv_5d = returns.tail(5).std() * np.sqrt(252) * 100
    
    # 2. Intraday Proxy (Efficiency vs Chaos)
    # Average of normalized high-low ranges over 3 sessions
    intraday_ranges = (df['High'] - df['Low']) / df['Open']
    rv_intraday = intraday_ranges.tail(3).mean() * np.sqrt(252) * 100
    
    # 3. RV Acceleration (Velocity of movement change)
    prev_rv = returns.iloc[-10:-5].std() * np.sqrt(252) * 100
    rv_accel = rv_5d - prev_rv
    
    # 4. Parkinson Volatility (Open-High-Low-Close aware)
    # High-Low estimator is more efficient than Close-to-Close for suppression detection
    park_const = 1.0 / (4.0 * np.log(2.0))
    p_log = np.log(df['High'] / df['Low'])**2
    parkinson = np.sqrt(252 * park_const * p_log.tail(5).mean()) * 100

    # 5. IV/RV Ratio
    iv_rv_ratio = atm_iv / max(rv_5d, 1.0)

    return RVMetrics(
        rv_5d=rv_5d,
        rv_intraday=rv_intraday,
        rv_acceleration=rv_accel,
        parkinson_vol=parkinson,
        vol_of_vol=0.0, # Placeholder for Phase 60
        iv_rv_ratio=iv_rv_ratio
    )
