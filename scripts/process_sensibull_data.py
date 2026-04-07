import json
import pandas as pd
import re
from pathlib import Path

def process():
    # v3: Removed hardcoded Desktop path
    input_file = Path(__file__).parent.parent / "data" / "option_chain" / "raw_sensibull_data.md"
    output_dir = Path("data/option_chain")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Sensibull specific filename convention for NDE
    output_file = output_dir / "option-chain-ED-sensi-NIFTY-07-Apr-2026.csv"

    if not input_file.exists():
        print(f"Input file {input_file} does not exist.")
        return

    content = input_file.read_text()
    json_match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
    if not json_match:
        print("No JSON found in scratchpad.")
        return

    data = json.loads(json_match.group(1))
    
    rows = []
    for item in data:
        strike = item["strike"]
        c = item["call"]
        p = item["put"]
        
        # Wide format: [CE OI], [CE IV], [CE LTP], [STRIKE], [PE LTP], [PE IV], [PE OI], Greeks...
        # Note: Sensibull Greeks are often lot-normalized, we preserve them as-is for the engine.
        rows.append({
            "OI": float(c.get("oi_lakh", 0)) * 100000,
            "IV": 15.0, # Dummy IV for BS if needed, Sensibull usually shows it in the UI too
            "LTP": float(c.get("ltp", 0)),
            "STRIKE": strike,
            "LTP.1": float(p.get("ltp", 0)),
            "IV.1": 15.0,
            "OI.1": float(p.get("oi_lakh", 0)) * 100000,
            # Institutional Greeks (pre-calculated from Sensibull Pro)
            "CE_DELTA": c.get("delta"), 
            "CE_THETA": c.get("theta"), 
            "CE_VEGA": c.get("vega"), 
            "CE_GAMMA": c.get("gamma"),
            "PE_DELTA": p.get("delta"), 
            "PE_THETA": p.get("theta"), 
            "PE_VEGA": p.get("vega"), 
            "PE_GAMMA": p.get("gamma")
        })
    
    df = pd.DataFrame(rows)
    header = "EXPIRY DATE: 07-Apr-2026\nVERSION: Sensibull High-Fidelity Override\n"
    csv_str = df.to_csv(index=False)
    output_file.write_text(header + csv_str)
    
    # Update master snapshot for dashboard priority
    master_csv = output_dir / "last_successful_nifty.csv"
    output_file.chmod(0o666) # Ensure writable
    import shutil
    shutil.copy(output_file, master_csv)
    
    print(f"Successfully transformed {len(df)} strikes to {output_file}")
    print(f"Updated master snapshot: {master_csv}")

if __name__ == "__main__":
    process()
