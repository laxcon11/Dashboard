import pandas as pd
import numpy as np
from nde_schema import LocalGammaMetrics

def compute_local_gamma_metrics(df_exp: pd.DataFrame, spot: float, atr: float) -> LocalGammaMetrics:
    """
    Standardized Local Gamma Engine (Carmack Refactor).
    Analyzes dealer 'pinning' pressure and structural containment near spot.
    """
    if df_exp is None or df_exp.empty:
        return LocalGammaMetrics(support=spot-atr, resistance=spot+atr)

    # 1. Define Local Window (±1.5 ATR for institutional breadth)
    window = 1.5 * atr
    local_df = df_exp[(df_exp['strike'] >= spot - window) & (df_exp['strike'] <= spot + window)]
    
    if local_df.empty:
        return LocalGammaMetrics(support=spot-atr, resistance=spot+atr)

    # 2. GEX Composition (Assuming 'gex' column from flow_engine)
    pos_gex = local_df[local_df['gex'] > 0]['gex'].sum()
    neg_gex = local_df[local_df['gex'] < 0]['gex'].sum()
    
    # 3. Suppression Strength (Absorption Ratio)
    # Higher pos_gex relative to neg_gex implies volatility dampening (Suppression)
    abs_ratio = pos_gex / (abs(neg_gex) + 1e-9)
    suppression = min(1.0, abs_ratio / 5.0) 
    
    # 4. Local Density (Exposures per unit of price)
    density = (pos_gex + abs(neg_gex)) / (2.0 * window)
    
    # 5. Structural Boundaries (Local Walls)
    # Support: Peak Positive GEX below spot
    # Resistance: Peak Positive GEX above spot
    below = local_df[(local_df['strike'] <= spot) & (local_df['gex'] > 0)]
    above = local_df[(local_df['strike'] >= spot) & (local_df['gex'] > 0)]
    
    support = below.sort_values('gex', ascending=False).iloc[0]['strike'] if not below.empty else spot - atr
    resistance = above.sort_values('gex', ascending=False).iloc[0]['strike'] if not above.empty else spot + atr
    
    # Collapse Risk: High negative gamma density with low absorption
    collapse = (abs(neg_gex) > pos_gex * 2.0) and (density > 0.5)

    return LocalGammaMetrics(
        suppression_strength=suppression,
        gamma_density=density,
        local_walls=[float(support), float(resistance)],
        support=float(support),
        resistance=float(resistance),
        collapse_risk=collapse
    )
