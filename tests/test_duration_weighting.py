import sys
import pandas as pd
import numpy as np
import math
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import nde_options_logic

def verify_duration_weighting():
    print("🚀 Verifying Duration Weighting (Analytical Depth)...")
    
    spot = 22500
    # Mock data for one strike
    def get_mock_df(t_days):
        return pd.DataFrame([{
            "strike": 22500, "type": "call", "oi": 1000000, "iv": 15.0, 
            "ltp": 200.0, "delta": 0.5, "gamma": 0.0002, "vega": 100.0, 
            "theta": -5.0, "volume": 50000, "oi_chng": 10000, "t_days": t_days
        }])

    # 1 DTE vs 30 DTE
    metrics_1d = nde_options_logic.compute_option_flow_exposures(spot, get_mock_df(1.0))
    metrics_30d = nde_options_logic.compute_option_flow_exposures(spot, get_mock_df(30.0))
    
    tw_1d = metrics_1d["gex_tw_norm"]
    tw_30d = metrics_30d["gex_tw_norm"]
    
    print(f"  1 DTE TW-GEX: {tw_1d:.2f}")
    print(f"  30 DTE TW-GEX: {tw_30d:.2f}")
    
    # Near dated should have MUCH higher TW GEX
    ratio = tw_1d / tw_30d
    print(f"  Gravity Multiplier (1d vs 30d): {ratio:.2f}x")
    
    expected_ratio = math.sqrt(30.0 / 1.0)
    print(f"  Theoretical sqrt(30/1): {expected_ratio:.2f}x")
    
    if abs(ratio - expected_ratio) < 0.1:
        print("✅ Duration Weighting math matches theoretical sqrt(T) scaling.")
        return True
    else:
        print("❌ Duration Weighting scaling mismatch.")
        return False

if __name__ == "__main__":
    success = verify_duration_weighting()
    sys.exit(0 if success else 1)
