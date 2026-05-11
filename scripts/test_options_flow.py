import unittest
import pandas as pd
import sys
import os

# Add Dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nde_options_logic import calculate_greeks, compute_option_flow_exposures

class TestOptionsFlowLogic(unittest.TestCase):
    
    def test_greeks_at_the_money(self):
        # S=22000, K=22000, T=0.019 (approx 7 days), r=0.07, iv=0.15
        S = 22000
        K = 22000
        T = 0.019
        r = 0.07
        iv = 0.15
        
        ce_greeks = calculate_greeks(S, K, T, r, iv, q=0.0, option_type="call")
        pe_greeks = calculate_greeks(S, K, T, r, iv, q=0.0, option_type="put")
        
        # At the money delta should be ~0.5 for calls, ~-0.5 for puts
        self.assertAlmostEqual(ce_greeks["delta"], 0.5, delta=0.1)
        self.assertAlmostEqual(pe_greeks["delta"], -0.5, delta=0.1)
        
        # Gamma should be positive and identical
        self.assertGreater(ce_greeks["gamma"], 0)
        self.assertEqual(ce_greeks["gamma"], pe_greeks["gamma"])

    def test_exposure_aggregation(self):
        spot = 22000
        # Mock chain: One call at 22200, one put at 21800
        data = [
            {"strike": 22200, "type": "call", "oi": 1000, "iv": 15, "t_days": 7},
            {"strike": 21800, "type": "put", "oi": 1000, "iv": 15, "t_days": 7}
        ]
        df = pd.DataFrame(data)
        metrics = compute_option_flow_exposures(spot, df)
        
        # Total GEX should be non-zero
        self.assertNotEqual(metrics.total_gex, 0)
        self.assertIsNotNone(metrics.gamma_regime)
        self.assertIsNotNone(metrics.vanna_bias)

    def test_gamma_flip_detection(self):
        spot = 22000
        # Create a range of strikes where GEX crosses from negative to positive
        data = []
        for strike in range(21500, 22600, 100):
            if strike < 22000:
                data.append({"strike": strike, "type": "put", "oi": 2000, "iv": 15, "t_days": 7})
            else:
                data.append({"strike": strike, "type": "call", "oi": 2000, "iv": 15, "t_days": 7})
        
        df = pd.DataFrame(data)
        metrics = compute_option_flow_exposures(spot, df)
        
        # Flip should be close to 22000
        self.assertGreater(metrics.gamma_flip_level, 21000)
        self.assertLess(metrics.gamma_flip_level, 23000)

if __name__ == '__main__':
    unittest.main()
