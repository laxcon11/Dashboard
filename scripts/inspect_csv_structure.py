import pandas as pd
from pathlib import Path
from io import StringIO

def inspect_csv():
    user_file = Path("data/option_chain/option-chain-ED-NIFTY-30-Mar-2026.csv")
    with open(user_file, 'r') as f:
        lines = f.readlines()
        
    # The header is at index 1 (second line)
    # CALLS,,PUTS
    # ,OI,CHNG IN OI,VOLUME,IV,LTP,CHNG,BID QTY,BID,ASK,ASK QTY,STRIKE,BID QTY,BID,ASK,ASK QTY,CHNG,LTP,IV,VOLUME,CHNG IN OI,OI,
    
    data_body = "".join(lines[1:])
    df = pd.read_csv(StringIO(data_body))
    
    print(f"Columns ({len(df.columns)}):")
    for i, col in enumerate(df.columns):
        print(f"{i}: '{col}'")
        
    print("\nFirst row raw values:")
    first_row = df.iloc[0]
    for i, val in enumerate(first_row):
        print(f"{i}: '{val}'")

if __name__ == "__main__":
    inspect_csv()
