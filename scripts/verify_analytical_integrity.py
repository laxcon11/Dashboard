import pandas as pd
import numpy as np
from datetime import datetime
import nde_options_logic
import nde_strategy_logic
import nde_automation_logic

def run_analytical_integrity_check():
    print("🚀 Starting NDE Analytical Integrity Verification (Phase 42)...")
    passed = 0
    failed = 0
    
    # Mock Data Setup
    spot = 22500
    strikes = [22400, 22450, 22500, 22550, 22600]
    data = []
    for s in strikes:
        # Expiry 07-Apr-2026 (T-0 for test)
        data.append({
            "strike": s, "type": "call", "oi": 100000, "iv": 20.0, 
            "delta": 0.5, "gamma": 0.0001, "vega": 10.0, "theta": -5.0,
            "volume": 5000, "oi_chng": 1000, "expiry": "07-Apr-2026", "t_days": 0.05
        })
        data.append({
            "strike": s, "type": "put", "oi": 100000, "iv": 20.0, 
            "delta": -0.4, "gamma": 0.0001, "vega": 10.0, "theta": -5.0,
            "volume": 5000, "oi_chng": 1000, "expiry": "07-Apr-2026", "t_days": 0.05
        })
    df = pd.DataFrame(data)
    
    # Setup for 14-Apr-2026 as well
    data_next = []
    for s in strikes:
        data_next.append({
            "strike": s, "type": "call", "oi": 100000, "iv": 15.0, 
            "delta": 0.5, "gamma": 0.0001, "vega": 10.0, "theta": -5.0,
            "volume": 5000, "oi_chng": 1000, "expiry": "14-Apr-2026", "t_days": 3.0
        })
        data_next.append({
            "strike": s, "type": "put", "oi": 100000, "iv": 15.0, 
            "delta": -0.4, "gamma": 0.0001, "vega": 10.0, "theta": -5.0,
            "volume": 5000, "oi_chng": 1000, "expiry": "14-Apr-2026", "t_days": 3.0
        })
    df = pd.concat([df, pd.DataFrame(data_next)])
    
    nifty_df = pd.DataFrame({"Close": [22400, 22450, 22500]}, index=pd.date_range(end=datetime.now(), periods=3))
    regime_hist = [{"score": 65.0, "regime": "SELECTIVE"}] * 5
    regime_s = {"current_regime": "SELECTIVE", "persistence": 5}
    vix_df = pd.DataFrame({"Close": [15, 14, 13]}, index=pd.date_range(end=datetime.now(), periods=3))
    vix_long = pd.concat([vix_df["Close"]] * 10).reset_index(drop=True)

    # ============================================================
    # 1. EXPIRY DAY POLICY (T-0, IV < 12)
    # ============================================================
    print("\n--- TEST 1: Expiry Day Policy (T-0, IV < 12) ---")
    df_t0 = df.copy()
    # Force ALL strikes to iv < 12 to pass the weighted average check
    df_t0.loc[df_t0["expiry"] == "07-Apr-2026", "iv"] = 10.0
    
    ctx_t0_low_iv = nde_strategy_logic.generate_engine_context(
        df_t0, spot, nifty_df, "07-Apr-2026", regime_hist, regime_s, vix_long,
        meta={"validation_flags": [], "data_quality_score": 1.0}, source="SENSIBULL_VENDOR_GREEKS"
    )
    
    strat = ctx_t0_low_iv["master_setup"]
    if strat["code"] != "NO_TRADE" and "Defensive" in strat.get("mode_override", ""):
        print(f"  ✅ T-0, IV < 12: Allowed in Defensive mode (Strategy: {ctx_t0_low_iv['strategy_code']})")
        passed += 1
    else:
        print(f"  ❌ T-0, IV < 12: Expected Defensive trade, got {strat['code']} ({strat.get('reason')})")
        failed += 1

    # ============================================================
    # 2. EXPIRY DAY POLICY (T-0, IV > 12)
    # ============================================================
    print("\n--- TEST 2: Expiry Day Policy (T-0, IV > 12) ---")
    df_t0_high = df.copy()
    df_t0_high.loc[df_t0_high["expiry"] == "07-Apr-2026", "iv"] = 15.0
    
    ctx_t0_high_iv = nde_strategy_logic.generate_engine_context(
        df_t0_high, spot, nifty_df, "07-Apr-2026", regime_hist, regime_s, vix_long,
        meta={"validation_flags": [], "data_quality_score": 1.0}, source="SENSIBULL_VENDOR_GREEKS"
    )
    
    strat_h = ctx_t0_high_iv["master_setup"]
    if strat_h["code"] == "NO_TRADE" and "IV" in strat_h.get("reason", ""):
        print(f"  ✅ T-0, IV > 12: Correctly blocked by Policy")
        passed += 1
    else:
        print(f"  ❌ T-0, IV > 12: Expected Block, got {strat_h['code']} ({strat_h.get('reason')})")
        failed += 1

    # ============================================================
    # 3. FLOW REGIME: Institutional Churn
    # ============================================================
    print("\n--- TEST 3: Flow Regime - Institutional Churn (Ratio > 0.4) ---")
    df_churn = df.copy()
    # Mask strikes roughly at spot
    df_churn.loc[df_churn["strike"] == 22500, "volume"] = 600000 
    
    flow = nde_options_logic.compute_option_flow_exposures(spot, df_churn)
    regime_label = flow.get("flow_regime_label")
    if regime_label == "Institutional Churn":
        print(f"  ✅ Aggregated Ratio > 0.4 -> {regime_label}")
        passed += 1
    else:
        print(f"  ❌ Aggregated Ratio > 0.4 -> Expected Institutional Churn, got {regime_label}")
        failed += 1

    # ============================================================
    # 4. FLOW REGIME: Active Accumulation
    # ============================================================
    print("\n--- TEST 4: Flow Regime - Active Accumulation (Ratio > 0.25, OI Change > 0.05) ---")
    df_acc = df.copy()
    # Isolate Strike 22500 as the sole engagement focus
    df_acc.loc[df_acc["strike"] != 22500, "volume"] = 0
    df_acc.loc[df_acc["strike"] == 22500, "volume"] = 35000
    df_acc.loc[df_acc["strike"] == 22500, "oi_chng"] = 20000 
    
    # Use 22500 as spot to ensure Strike 22500 is the absolute ATM center
    flow_acc = nde_options_logic.compute_option_flow_exposures(22500, df_acc)
    regime_acc = flow_acc.get("flow_regime_label")
    if regime_acc == "Active Accumulation":
        print(f"  ✅ Ratio ~0.35 + OI Change > 0 -> {regime_acc}")
        passed += 1
    else:
        print(f"  ❌ Expected Active Accumulation, got {regime_acc}")
        failed += 1

    # ============================================================
    # 5. CONVERGENCE BOOST
    # ============================================================
    print("\n--- TEST 5: Convergence Score Boost ---")
    # Base case (Passive) - uses 14-Apr to avoid expiry block
    ctx_base = nde_strategy_logic.generate_engine_context(
        df, spot, nifty_df, "14-Apr-2026", regime_hist, regime_s, vix_long,
        meta={"validation_flags": [], "data_quality_score": 1.0}, source="SENSIBULL_VENDOR_GREEKS"
    )
    score_base = ctx_base["master_setup"]["quality_score"]
    
    # Churn case (Boost)
    df_boost = df.copy()
    df_boost.loc[df_boost["strike"] == 22500, "volume"] = 500000
    ctx_boost = nde_strategy_logic.generate_engine_context(
        df_boost, spot, nifty_df, "14-Apr-2026", regime_hist, regime_s, vix_long,
        meta={"validation_flags": [], "data_quality_score": 1.0}, source="SENSIBULL_VENDOR_GREEKS"
    )
    score_boost = ctx_boost["master_setup"]["quality_score"]
    
    if score_boost > score_base:
        print(f"  ✅ Convergence Score Boost: Base {score_base:.2f} -> Churn {score_boost:.2f}")
        passed += 1
    else:
        print(f"  ❌ No boost detected: Base {score_base:.2f} -> Churn {score_boost:.2f}")
        failed += 1

    print("\n" + "="*50)
    print(f"🏁 INTEGRITY VERIFICATION COMPLETE: {passed} passed, {failed} failed")
    if failed > 0:
        print("⚠️  FIDELITY GAPS DETECTED. Review output above.")
    else:
        print("🎯 ALL ANALYTICAL SYSTEMS GREEN.")
    print("="*50)

if __name__ == "__main__":
    run_analytical_integrity_check()
