import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def compute_local_gamma_density(df_chain: pd.DataFrame, spot: float, atr: float) -> dict:
    """
    Local Gamma Density Engine.
    Analyzes dealer positioning structure within ±1 ATR of spot to determine suppression strength.
    """
    if df_chain is None or df_chain.empty:
        return {
            "local_pos_gex": 0.0,
            "local_neg_gex": 0.0,
            "gamma_density_score": 0.0,
            "suppression_strength": 0.0,
            "nearest_support": spot - atr,
            "nearest_resistance": spot + atr
        }

    try:
        # Define local window
        lower_bound = spot - (1.0 * atr)
        upper_bound = spot + (1.0 * atr)
        
        # Filter local chain
        local_chain = df_chain[(df_chain['strike'] >= lower_bound) & (df_chain['strike'] <= upper_bound)].copy()
        
        if local_chain.empty:
            return {
                "local_pos_gex": 0.0, "local_neg_gex": 0.0,
                "gamma_density_score": 0.0, "suppression_strength": 0.0,
                "nearest_support": spot - atr, "nearest_resistance": spot + atr
            }

        # Compute GEX (assume columns 'gex' exists from nde_options_logic processing)
        # If 'gex' doesn't exist, we fallback to a simplified proxy or return zeros
        if 'gex' not in local_chain.columns:
            # We might need to compute GEX here if it's not pre-computed, 
            # but usually compute_option_flow_exposures adds it.
            return {
                "local_pos_gex": 0.0, "local_neg_gex": 0.0,
                "gamma_density_score": 0.0, "suppression_strength": 0.0,
                "nearest_support": spot - atr, "nearest_resistance": spot + atr
            }

        pos_gex = local_chain[local_chain['gex'] > 0]['gex'].sum()
        neg_gex = local_chain[local_chain['gex'] < 0]['gex'].sum()
        
        # 1. Suppression Strength: High positive gamma near spot suppresses movement
        # 2. Absorption Ratio: pos_gex vs absolute neg_gex
        absorption_ratio = pos_gex / (abs(neg_gex) + 1.0)
        suppression = min(1.0, absorption_ratio / 5.0) # Normalized 0-1
        
        # 3. Density Score: Structural density in local window
        density = (pos_gex + abs(neg_gex)) / (2.0 * atr)
        
        # 4. Local Walls (Institutional Logic)
        # Support = Strongest Positive GEX level BELOW spot
        # Resistance = Strongest Positive GEX level ABOVE spot
        below_spot = local_chain[(local_chain['strike'] < spot) & (local_chain['gex'] > 0)]
        above_spot = local_chain[(local_chain['strike'] > spot) & (local_chain['gex'] > 0)]
        
        nearest_support = below_spot.sort_values('gex', ascending=False).iloc[0]['strike'] if not below_spot.empty else spot - atr
        nearest_resistance = above_spot.sort_values('gex', ascending=False).iloc[0]['strike'] if not above_spot.empty else spot + atr

        return {
            "local_pos_gex": float(pos_gex),
            "local_neg_gex": float(neg_gex),
            "absorption_ratio": float(round(absorption_ratio, 2)),
            "gamma_density_score": float(round(density, 4)),
            "suppression_strength": float(round(suppression, 2)),
            "nearest_support": float(nearest_support),
            "nearest_resistance": float(nearest_resistance),
            "is_contained": suppression > 0.6
        }
    except Exception as e:
        logger.error(f"Local Gamma Engine Error: {e}")
        return {
            "local_pos_gex": 0.0, "local_neg_gex": 0.0,
            "gamma_density_score": 0.0, "suppression_strength": 0.0,
            "nearest_support": spot - atr, "nearest_resistance": spot + atr
        }
