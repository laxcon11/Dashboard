import pandas as pd
import numpy as np
import math
import logging

logger = logging.getLogger(__name__)

def compute_realized_volatility_metrics(df: pd.DataFrame, spot: float, atr: float) -> dict:
    """
    Institutional Realized Volatility Engine.
    Computes movement-based metrics to distinguish between Suppressed and Expansive regimes.
    """
    if df is None or df.empty or len(df) < 5:
        return {
            "rv_5d": 15.0,
            "rv_intraday": 15.0,
            "iv_rv_ratio": 1.0,
            "rv_regime": "NORMAL",
            "rv_acceleration": 0.0,
            "atr_normalized_move": 0.0
        }

    try:
        # 1. 5D Realized Volatility (Annualized)
        # Assuming df has 'Close' prices
        returns = np.log(df['Close'] / df['Close'].shift(1)).dropna()
        rv_5d = returns.tail(5).std() * np.sqrt(252) * 100
        
        # 2. Intraday Realized Volatility Proxy
        # High-Low range relative to Open
        intraday_ranges = (df['High'] - df['Low']) / df['Open']
        rv_intraday = intraday_ranges.tail(3).mean() * np.sqrt(252) * 100
        
        # 3. RV Acceleration
        prev_rv = returns.iloc[-10:-5].std() * np.sqrt(252) * 100 if len(returns) >= 10 else rv_5d
        rv_accel = rv_5d - prev_rv
        
        # 4. ATR Normalized Move
        current_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2] if len(df) >= 2 else current_price
        abs_move = abs(current_price - prev_price)
        atr_norm = abs_move / atr if atr > 0 else 0
        
        # 5. Regime Classification
        if rv_5d > 25.0 or rv_accel > 5.0:
            rv_regime = "EXPANSIVE"
        elif rv_5d < 12.0 and abs(rv_accel) < 2.0:
            rv_regime = "SUPPRESSED"
        else:
            rv_regime = "NORMAL"

        # 6. Forward Expectation (Institutional Projection)
        # We blend current RV with acceleration to project the "Forward Realized" path
        forward_rv = rv_5d + (rv_accel * 0.5)
        
        return {
            "rv_5d": float(round(rv_5d, 2)),
            "rv_intraday": float(round(rv_intraday, 2)),
            "rv_regime": rv_regime,
            "rv_acceleration": float(round(rv_accel, 2)),
            "forward_rv_expectation": float(round(forward_rv, 2)),
            "atr_normalized_move": float(round(atr_norm, 2))
        }
    except Exception as e:
        logger.error(f"RV Engine Error: {e}")
        return {
            "rv_5d": 15.0,
            "rv_intraday": 15.0,
            "iv_rv_ratio": 1.0,
            "rv_regime": "NORMAL",
            "rv_acceleration": 0.0,
            "atr_normalized_move": 0.0
        }
