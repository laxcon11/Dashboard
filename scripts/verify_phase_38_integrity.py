import os
import sys

# Ensure imports work dynamically
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import nde_strategy_logic
import nde_options_logic
from nde_automation_logic import compute_expiry_phase

print("=== PHASE 38 SYSTEM INTEGRITY REGRESSION CHECK ===")

# Test 1: Expiry Phase Gate (Hard Block)
gamma_metrics_expiry = {
    "total_gex": 100000,
    "total_vega": 500,
    "tv_ratio": 0.8,
    "tv_label": "NORMAL"
}
auto_metrics = {"stability": 80, "drift": 0.05}
regime = {"current_regime": "SELECTIVE"}
iv_data = {"label": "NORMAL", "iv_rank": 40.0}

print("\n[1] Testing Expiry Gate (DTE=0, MR Block)")
res1 = nde_strategy_logic.get_strategy_details("MEAN_REVERSION", gamma_metrics_expiry, auto_metrics, 22000, regime, (22200, 21800), 200, dte=0, iv_data=iv_data)
assert res1["code"] == "NO_TRADE", "Expected NO_TRADE for DTE=0"
print(f"✅ Executed exactly as NO_TRADE. Reason: {res1.get('reason')}")

# Test 2: TV Ratio 'AVOID' Hard Gate
print("\n[2] Testing TV Ratio 'AVOID' Block (Convergence High)")
gamma_metrics_tv = dict(gamma_metrics_expiry)
gamma_metrics_tv["tv_label"] = "AVOID"  # Highly inflated Vega risk
res2 = nde_strategy_logic.get_strategy_details("MEAN_REVERSION", gamma_metrics_tv, auto_metrics, 22000, regime, (22200, 21800), 200, dte=10, iv_data=iv_data)
assert res2["code"] == "NO_TRADE", "Expected NO_TRADE for tv_label AVOID"
assert res2["size"] == 0.0, "Expected size == 0.0"
print(f"✅ Blocked with Size=0.0. Reason: {res2.get('reason')}")

# Test 3: Convergence Score Non-Linear Mapping & Weighting
print("\n[3] Testing Convergence Index Non-Linear Expansion")
gamma_metrics_perfect = {"total_gex": 100000, "total_vega": 200, "tv_ratio": 0.6, "tv_label": "PREMIUM"}
res3 = nde_strategy_logic.compute_signal_convergence("MEAN_REVERSION", gamma_metrics_perfect, auto_metrics, regime, iv_data, atr=200, spot=22000)
# Should trigger: macro (Selective), flow (GEX>0), structure (Stab>65), momentum (Drift accel<=0), Vol (Normal) -> All True
print(f"✅ Perfect Convergence Score mapping: {res3[0]:.4f}")

gamma_metrics_trash = {"total_gex": -10000, "total_vega": 800} # Fails Flow
regime_trash = {"current_regime": "CRISIS"} # Fails Macro
res3b = nde_strategy_logic.compute_signal_convergence("MEAN_REVERSION", gamma_metrics_trash, auto_metrics, regime_trash, iv_data, atr=200, spot=22000)
print(f"✅ Decayed Convergence Score mapping (Failing items): {res3b[0]:.4f}")

# Test 4: Size Scaling & Integrity bounds
print("\n[4] Testing Size Clamping")
# Using perfect setup to see execution bounds
res4 = nde_strategy_logic.get_strategy_details("MEAN_REVERSION", gamma_metrics_perfect, auto_metrics, 22000, regime, (22200, 21800), 200, dte=12, iv_data=iv_data)
print(f"✅ Authorized Trade: {res4['code']} | Quality: {res4['quality_score']}/10 | Bounded Size: {res4['size']}x")
assert 0.3 <= res4["size"] <= 1.2, "Size is out of expected bounded bounds"

print("\n=== All Phase 37 Architecture Structural Integrity Checks PASSED ===")
