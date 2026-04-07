import pandas as pd
from pathlib import Path
from nde_options_logic import parse_nse_option_chain_csv

def test_user_file():
    user_file = Path("data/option_chain/option-chain-ED-NIFTY-30-Mar-2026.csv")
    if not user_file.exists():
        print(f"ERROR: File {user_file} not found. Please ensure it is in the correct directory.")
        return

    print(f"Testing parsing for: {user_file}")
    df, expiry = parse_nse_option_chain_csv(user_file)
    
    print(f"Extracted Expiry: {expiry}")
    if df.empty:
        print("RESULT: FAILURE - DataFrame is empty")
    else:
        print(f"RESULT: SUCCESS - Parsed {len(df)} rows")
        print("\nFirst 5 rows:")
        print(df.head())
        
        # Verify columns
        expected_cols = {"strike", "type", "oi", "iv"}
        if set(df.columns) == expected_cols:
            print("RESULT: SUCCESS - Columns match expected schema")
        else:
            print(f"RESULT: FAILURE - Columns mismatch: {df.columns}")

if __name__ == "__main__":
    test_user_file()
