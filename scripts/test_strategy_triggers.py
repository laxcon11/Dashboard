from nde_strategy_logic import select_master_strategy, detect_mean_reversion, detect_trend_acceleration

def test_strategy_triggers():
    print("Testing Strategy Triggers...")
    
    # Mock 1: Mean Reversion (Stable + Long Gamma)
    gamma_1 = {"total_gex": 1000000}
    auto_1 = {"stability": 85, "drift": 0.05, "transition_risk": 0.2}
    spot_1 = 22000
    res_1 = detect_mean_reversion(gamma_1, auto_1)
    print(f"Scenario 1 (Stable/Long Gamma) -> {res_1['name'] if res_1 else 'NONE'}")
    assert res_1 and "Mean Reversion" in res_1["name"]
    
    # Mock 2: Trend Acceleration (Unstable + Short Gamma)
    gamma_2 = {"total_gex": -500000}
    auto_2 = {"stability": 30, "drift": 0.3, "transition_risk": 0.7}
    spot_2 = 22000
    res_2 = detect_trend_acceleration(gamma_2, auto_2)
    print(f"Scenario 2 (Unstable/Short Gamma) -> {res_2['name'] if res_2 else 'NONE'}")
    assert res_2 and "Trend" in res_2["name"]
    
    # Mock 3: Gamma Flip (Near Flip)
    gamma_3 = {"total_gex": 50000, "gamma_flip_level": 22100}
    auto_3 = {"stability": 60, "drift": 0.1}
    spot_3 = 22080 # Within 0.5%
    master_3 = select_master_strategy(gamma_3, auto_3, spot_3)
    print(f"Scenario 3 (Near Flip) -> Master: {master_3['name']}")
    assert "Gamma Flip" in master_3["name"]

    print("\nRESULT: ALL TRIGGER TESTS PASSED")

if __name__ == "__main__":
    test_strategy_triggers()
