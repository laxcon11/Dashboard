import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import nde_automation_logic
import nde_scripts_bridge

def verify_ingestion_service():
    print("Checking Ingestion Service...")
    
    # 1. Test Bridge Imports
    print("- nde_scripts_bridge: ", end="")
    try:
        raw = nde_scripts_bridge.list_raw_files()
        print(f"OK ({len(raw)} raw files found)")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
        
    # 2. Test Automation Service
    print("- nde_automation_logic.get_ingestion_hub_context(): ", end="")
    try:
        ctx = nde_automation_logic.get_ingestion_hub_context()
        print("OK")
        for k, v in ctx.items():
            print(f"  - {k}: {v}")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
        
    # 3. Test Auto-convert (Safe check)
    print("- nde_automation_logic.auto_convert_raw_files(): ", end="")
    try:
        # Should be safe to run even if empty
        count = nde_automation_logic.auto_convert_raw_files()
        print(f"OK ({count} processed)")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
        
    print("\n✅ Ingestion Service Verification PASSED")
    return True

if __name__ == "__main__":
    success = verify_ingestion_service()
    sys.exit(0 if success else 1)
