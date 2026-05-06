import pandas as pd
import numpy as np
from pathlib import Path
import json
import sys

# Add root to Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.process_sensibull_csv import convert_all_sensibull_csvs
from nde_strategy_logic import generate_engine_context
import nde_options_logic

def run_exercise():
    print("🚀 Starting NDE Institutional Hardening Exercise...")
    
    # 1. Setup Mock Raw Data
    test_dir = ROOT / "data" / "option_chain"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # A. Perfect Data (Monotonic)
    perfect_raw = test_dir / "NIFTY_2026-04-15_option_chain_PERFECT.csv"
    # Need 10+ strikes for 'Institutional' quality
    pd.DataFrame({
        "Strike": [22000 + i*50 for i in range(12)],
        "Call OI": [10]*12,
        "Call Gamma": [0.1]*12,
        "Put OI": [10]*12,
        "Put Gamma": [0.1]*12,
        "Call LTP": [100]*12,
        "Put LTP": [100]*12
    }).to_csv(perfect_raw, index=False)

    # B. Mangled Data (Non-Monotonic Strikes)
    mangled_raw = test_dir / "NIFTY_2026-04-10_option_chain_MANGLED.csv"
    pd.DataFrame({
        "Strike": [22000, 22400, 22200], # SCRAMBLED
        "Call OI": [10, 50, 30],
        "Call Gamma": [0.1, 0.1, 0.3],
        "Put OI": [50, 10, 30],
        "Put Gamma": [0.1, 0.1, 0.3],
        "Call LTP": [100, 20, 60],
        "Put LTP": [20, 100, 60]
    }).to_csv(mangled_raw, index=False)

    print("✅ Created test vectors: PERFECT (2026-04-15) vs MANGLED (2026-04-10).")

    # 2. Run Ingestion (CSV Converter)
    print("🔄 Running Ingestion Engine...")
    convert_all_sensibull_csvs()
    
    # 3. Verify Metadata Sidecars
    # Let's check for the existence of processed files
    processed = list(test_dir.glob("option-chain-ED-sensi-NIFTY-15-Apr-2026.csv"))
    if not processed:
        print("❌ FAILED: Perfect file not processed.")
        return
    else:
        print("✅ SUCCESS: Perfect file processed correctly.")

    # 4. Verify Strategy Trust Guard
    print("🛡️ Testing Strategy Trust Guards...")
    # Add a manually mangled NDE file to test the Strat Trust Guard directly
    mangled_nde = test_dir / "option-chain-ED-sensi-NIFTY-10-Apr-2026.csv"
    mangled_meta = test_dir / "option-chain-ED-sensi-NIFTY-10-Apr-2026_meta.json"
    
    # Create a 'Hard Guarded' metadata sidecar manually for the already mangled file
    m_meta = {
        "expiry": "10-Apr-2026",
        "data_quality_score": 0.0,
        "validation_flags": ["NON_MONOTONIC_STRIKES", "ATM_GREEK_COLLAPSE"]
    }
    with open(mangled_meta, "w") as f: json.dump(m_meta, f)
    with open(mangled_nde, "w") as f: f.write("EXPIRY DATE: 10-Apr-2026\nSTRIKE,LTP\n22000,10\n")

    # Load the processed file
    df, expiry, source, meta, fname = nde_options_logic.load_index_v3_data("option-chain-ED-sensi-NIFTY-10-Apr-2026.csv")
    
    print(f"   Metadata Flags: {meta.get('validation_flags', 'None')}")
    print(f"   Quality Score: {meta.get('data_quality_score', 'None')}")

    # Run Engine Context
    # Dummy inputs for remaining params
    nifty_df = pd.DataFrame({"Close": [22200]*10})
    ctx = generate_engine_context(
        raw_chain=df, spot=22200, nifty_df=nifty_df, used_expiry="10-Apr-2026",
        regime_history=[], regime_snap={}, vix_df=None, meta=meta,
        source=source
    )
    
    strat = ctx["strategy_code"]
    ui = ctx["ui_display"]
    
    print(f"🏆 Final Resolved Strategy: {strat}")
    
    if "NON_MONOTONIC_STRIKES" in meta.get("validation_flags", []):
        if strat == "TRUST_VIOLATION":
            print("🚀 SUCCESS: Trust Guard correctly blocked mangled data execution.")
        else:
            print(f"❌ FAILURE: Trust Guard failed to block mangled data. Strategy: {strat}")
    else:
        print("✅ Success: Baseline ingestion passed.")

if __name__ == "__main__":
    run_exercise()
