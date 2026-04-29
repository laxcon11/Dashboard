import pandas as pd
from pathlib import Path
from nde_options_logic import parse_nse_option_chain_csv, calculate_option_walls

def test_walls():
    user_file = Path("data/option_chain/option-chain-ED-NIFTY-30-Mar-2026.csv")
    if not user_file.exists():
        print(f"ERROR: File {user_file} not found.")
        return

    print(f"Loading: {user_file}")
    df, expiry = parse_nse_option_chain_csv(user_file)
    
    if df.empty:
        print("FAILURE: DataFrame is empty")
        return
        
    call_wall, put_wall, sec_c, sec_p = calculate_option_walls(df)
    print(f"Extracted Expiry: {expiry}")
    print(f"Detected Call Wall (Max OI): {call_wall}")
    print(f"Detected Put Wall (Max OI): {put_wall}")
    
    # Quick sanity check based on previous head output
    # Strike 23000 had high OI in the view_file output
    if call_wall > 10000 and put_wall > 10000:
        print("RESULT: SUCCESS - Walls detected in reasonable range")
    else:
        print("RESULT: FAILURE - Walls look invalid")

if __name__ == "__main__":
    test_walls()
