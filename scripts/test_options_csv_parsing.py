import unittest
import pandas as pd
import os
from pathlib import Path
import sys

# Add Dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nde_options_logic import parse_nse_option_chain_csv

class TestOptionChainCSVParsing(unittest.TestCase):
    
    def setUp(self):
        self.test_csv = Path("data/option_chain/test_nifty_oc.csv")
        os.makedirs(self.test_csv.parent, exist_ok=True)
        
        content = [
            "NIFTY Option Chain",
            "Underlying Index: NIFTY  Spot: 22000.00  Expiry Date: 27-Mar-2026",
            "OI,CHNG,VOL,IV,LTP,CHNG,STRIKE PRICE,BID,ASK,LTP,IV,VOL,CHNG,OI",
            "100,10,1000,15,200,5,22000,10,10,200,15,1000,10,100",
            "50,5,500,16,100,2,22100,5,5,100,16,500,5,50"
        ]
        with open(self.test_csv, "w") as f:
            for line in content:
                f.write(line + "\n")

    def tearDown(self):
        if self.test_csv.exists():
            self.test_csv.unlink()

    def test_parse_csv_header_and_data(self):
        df, expiry = parse_nse_option_chain_csv(self.test_csv)
        
        self.assertEqual(expiry, "27-Mar-2026")
        self.assertFalse(df.empty)
        # Filter out empty strikes if any
        df = df.dropna(subset=["strike"])
        self.assertGreaterEqual(len(df), 4) # 2 strikes * 2 (CE/PE)
        
        # Verify specific data point
        ce_22000 = df[(df["strike"] == 22000) & (df["type"] == "call")].iloc[0]
        self.assertEqual(ce_22000["oi"], 100)
        self.assertEqual(ce_22000["iv"], 15)

if __name__ == '__main__':
    unittest.main()
