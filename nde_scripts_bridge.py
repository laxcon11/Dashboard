import sys
from pathlib import Path

# Add the scripts directory to sys.path so we can import the ingestion modules
_PROJECT_ROOT = Path(__file__).parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Now we can import the logic from the scripts folder
try:
    from process_sensibull_excel import process_all_downloads
    from process_sensibull_csv import convert_all_sensibull_csvs
except ImportError as e:
    # Fallback to dummy functions if scripts are missing or broken
    def process_all_downloads(*args, **kwargs): return 0
    def convert_all_sensibull_csvs(*args, **kwargs): return 0
    print(f"Warning: Could not import NDE ingestion scripts: {e}")

def run_ingestion_cycle(extra_dir=None):
    """
    Standard entry point for full ingestion.
    1. Converts any existing raw CSVs.
    2. Processes any raw Excel/CSV downloads (including the extra_dir if provided).
    3. Safety: Quarantines any residual raw files that were missed by primary logic.
    """
    import shutil
    
    converted = convert_all_sensibull_csvs()
    processed = process_all_downloads(extra_dir=extra_dir)
    
    # Secondary Safety Guard (Phase 3 Audit Resilience)
    residual = list_raw_files()
    if residual:
        stale_dir = _PROJECT_ROOT / "data" / "archive" / "stale"
        stale_dir.mkdir(parents=True, exist_ok=True)
        for f in residual:
            try:
                shutil.move(str(f), str(stale_dir / f.name))
                print(f"⚠️ Safety Guard: Moved residual raw file {f.name} to stale archive.")
            except Exception: pass
            
    if converted + processed > 0:
        import nde_automation_logic
        # Phase 37: Refresh Global Macro Regime BEFORE taking Strategy Snapshot
        # This ensures the NDE Engine sees the latest persistence-aware regime.
        nde_automation_logic.refresh_macro_regime()
        
        # Phase 45: Generate snapshots for ALL indices to ensure UI toggle works immediately
        for idx in ["NIFTY", "SENSEX", "BANKNIFTY"]:
            nde_automation_logic.generate_auto_snapshot(index_name=idx)
        
    # Phase 45: Archive Garbage Collection
    clean_archive_folder()
            
    return converted + processed

def clean_archive_folder():
    """Deletes raw download files whose target expiry date has mathematically lapsed."""
    import re
    from datetime import datetime
    
    archive_dir = _PROJECT_ROOT / "data" / "archive"
    stale_dir = archive_dir / "stale"
    
    # Matches patterns like: NIFTY_2026-04-07_option_chain_... or SENSEX_2026-05-14_...
    date_pattern = re.compile(r"(?:NIFTY|SENSEX|BANKNIFTY)_(\d{4}-\d{2}-\d{2})_")
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    for d in [archive_dir, stale_dir]:
        if not d.exists():
            continue
        try:
            for f in d.glob("*"):
                if not f.is_file():
                    continue
                match = date_pattern.search(f.name)
                if match:
                    expiry_str = match.group(1)  # Format: YYYY-MM-DD
                    try:
                        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d")
                        # Delete if the expiry date is strictly in the past
                        if expiry_dt < today_start:
                            f.unlink()
                            print(f"🧹 Archive GC: Pruned expired raw download -> {f.name}")
                    except ValueError:
                        pass
        except Exception:
            pass

def list_raw_files():
    """Returns list of raw files in data/option_chain that haven't been processed."""
    target = _PROJECT_ROOT / "data" / "option_chain"
    if not target.exists():
        return []
    
    # Match any Excel/CSV with standard index names
    patterns = ["*NIFTY*", "*SENSEX*", "*BANKNIFTY*"]
    excel = []
    csv = []
    for p in patterns:
        excel.extend(list(target.glob(f"{p}.xlsx")))
        csv.extend(list(target.glob(f"{p}.csv")))
    
    # Filter out files that are already standard processed outputs
    raw = [f for f in excel + csv if not f.name.startswith("option-chain-ED-sensi-")]
    return raw
