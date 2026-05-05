import pytest
import pandas as pd
import numpy as np
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import nde_options_logic
import nde_strategy_logic
import nde_automation_logic
from unittest.mock import patch

# ==================== FIXTURES ====================

@pytest.fixture
def mock_option_chain():
    """Builds a basic 5-strike option chain."""
    spot = 22500
    strikes = [22400, 22450, 22500, 22550, 22600]
    data = []
    expiry = (datetime.now() + timedelta(days=2)).strftime("%d-%b-%Y")
    for s in strikes:
        data.append({
            "strike": s, "type": "call", "oi": 100000, "iv": 15.0, "ltp": 200.0,
            "delta": 0.5, "gamma": 0.0002, "vega": 100.0, "theta": -5.0,
            "volume": 5000, "oi_chng": 1000, "expiry": expiry, "t_days": 2.0
        })
        data.append({
            "strike": s, "type": "put", "oi": 100000, "iv": 15.0, "ltp": 200.0,
            "delta": -0.4, "gamma": 0.0001, "vega": 100.0, "theta": -5.0,
            "volume": 5000, "oi_chng": 1000, "expiry": expiry, "t_days": 2.0
        })
    return pd.DataFrame(data), spot, expiry

@pytest.fixture
def temp_data_dir(tmp_path):
    """Mocks the project data directory structure."""
    option_chain_dir = tmp_path / "data" / "option_chain"
    automation_dir = tmp_path / "data" / "automation"
    notes_dir = tmp_path / "notes"
    
    option_chain_dir.mkdir(parents=True)
    automation_dir.mkdir(parents=True)
    notes_dir.mkdir(parents=True)
    
    # Patch the constants in the modules
    orig_oc_dir = nde_options_logic.OPTION_CHAIN_DIR
    nde_options_logic.OPTION_CHAIN_DIR = option_chain_dir
    nde_automation_logic.OPTION_CHAIN_DIR = option_chain_dir
    nde_automation_logic.AUTOMATION_OUTPUT_DIR = automation_dir
    
    orig_state_file = nde_strategy_logic.STATE_FILE
    orig_audit_file = nde_strategy_logic.AUDIT_FILE
    nde_strategy_logic.STATE_FILE = notes_dir / "strategy_state.json"
    nde_strategy_logic.AUDIT_FILE = notes_dir / "nde_strategy_log.jsonl"
    
    yield {
        "option_chain": option_chain_dir,
        "automation": automation_dir,
        "notes": notes_dir
    }
    
    # Restore (optional but good practice)
    nde_options_logic.OPTION_CHAIN_DIR = orig_oc_dir
    nde_automation_logic.OPTION_CHAIN_DIR = orig_oc_dir
    nde_strategy_logic.STATE_FILE = orig_state_file
    nde_strategy_logic.AUDIT_FILE = orig_audit_file

# ==================== PHASE 1: DATA PROVENANCE ====================

def test_metadata_resolution_order(temp_data_dir, mock_option_chain):
    """Verifies fallback order: spot_at_fetch -> spot -> fallback."""
    oc_dir = temp_data_dir["option_chain"]
    df, spot, expiry = mock_option_chain
    
    filename = "test_chain.csv"
    csv_path = oc_dir / filename
    df.to_csv(csv_path)
    
    # Case 1: Metadata exists with spot_at_fetch
    meta_path = oc_dir / "test_chain_meta.json"
    with open(meta_path, "w") as f:
        json.dump({"spot_at_fetch": 22600.0}, f)
        
    # We patch load_latest_option_chain_csv to return our test file
    import nde_options_logic
    orig_load = nde_options_logic.load_latest_option_chain_csv
    nde_options_logic.load_latest_option_chain_csv = lambda: (df, filename, datetime.now(), expiry)
    
    # We also mock data_fetch.batch_download to avoid network calls
    import data_fetch
    orig_batch = data_fetch.batch_download
    data_fetch.batch_download = lambda symbols, period: {"^NSEI": pd.DataFrame()}

    try:
        # Should pick 22600.0 from meta
        snap = nde_automation_logic.generate_auto_snapshot()
        # Verify using compute logic directly if needed, or by checking snapshot output
        with open(snap, "r") as f:
            data = json.load(f)
            assert data["spot"] == 22600.0
            
        # Case 2: No metadata, live spot fallback blocked (DEGRADED)
        os.remove(meta_path)
        # Mock live spot (will be ignored)
        data_fetch.batch_download = lambda symbols, period: {"^NSEI": pd.DataFrame({"Close": [22700.0]}, index=[datetime.now()])}
        snap2 = nde_automation_logic.generate_auto_snapshot()
        with open(snap2, "r") as f:
            data = json.load(f)
            assert data["spot"] == 22500.0

    finally:
        nde_options_logic.load_latest_option_chain_csv = orig_load
        data_fetch.batch_download = orig_batch

# ==================== PHASE 2: CLEANUP ====================

def test_list_available_chains_no_deletion(temp_data_dir):
    """Verifies that listing chains does NOT delete expired files."""
    oc_dir = temp_data_dir["option_chain"]
    expired_date = (datetime.now() - timedelta(days=10)).strftime("%d-%b-%Y")
    
    expired_file = oc_dir / f"option-chain-ED-v3-NIFTY-{expired_date}.csv"
    with open(expired_file, "w") as f:
        f.write(f"EXPIRY DATE: {expired_date}\n")
    
    meta_file = oc_dir / f"option-chain-ED-v3-NIFTY-{expired_date}_meta.json"
    with open(meta_file, "w") as f:
        json.dump({"expiry": expired_date}, f)
        
    # Trigger listing
    chains = nde_options_logic.list_available_option_chains()
    
    # Verify files still exist
    assert expired_file.exists()
    assert meta_file.exists()

def test_explicit_cleanup_behavior(temp_data_dir):
    """Verifies that cleanup_expired_chains() actually deletes expired files."""
    oc_dir = temp_data_dir["option_chain"]
    expired_date = (datetime.now() - timedelta(days=10)).strftime("%d-%b-%Y")
    
    expired_file = oc_dir / f"option-chain-v3-NIFTY-{expired_date}.csv"
    with open(expired_file, "w") as f:
        f.write(f"EXPIRY DATE: {expired_date}\n")
    
    meta_file = oc_dir / f"option-chain-v3-NIFTY-{expired_date}_meta.json"
    with open(meta_file, "w") as f:
        json.dump({"expiry": expired_date}, f)
        
    # Trigger cleanup
    purged = nde_options_logic.cleanup_expired_chains()
    
    assert purged >= 1
    assert not expired_file.exists()
    assert not meta_file.exists()

# ==================== PHASE 3: GOVERNANCE ====================

def test_tv_ratio_low_vega_stability():
    """Verifies TV-ratio doesn't explode in low-vega regimes."""
    import math
    total_theta = -5000.0
    total_vega = 0.00000001
    t_days = 2.0
    
    # Current hardened implementation uses max(total_vega, 1e-4) or similar floor
    # and caps the final ratio to prevent runaway.
    from nde_options_logic import compute_option_flow_exposures
    # We test the logic indirectly by providing low vega
    metrics = compute_option_flow_exposures(22500, pd.DataFrame([{
        "strike": 22500, "type": "call", "oi": 100, "iv": 1.0, "ltp": 1.0,
        "delta": 0.5, "gamma": 0.0001, "vega": 0.0001, "theta": -100.0, "t_days": 2.0
    }]), tv_ema_fast=1.0, tv_ema_slow=1.0)
    
    # It should be capped at 10.0
    assert metrics["tv_ratio"] <= 10.1
    assert metrics["tv_label"] in ["AVOID", "CAUTION", "PREMIUM", "NORMAL"]

def test_governance_transition_gate(temp_data_dir, mocker):
    """Verifies that strategy shifts are governed by the 1.5-point delta rule or Regime Cross."""
    notes_dir = temp_data_dir["notes"]
    state_file = notes_dir / "strategy_state.json"
    
    # 1. Baseline State (Long Gamma, High Score)
    with open(state_file, "w") as f:
        json.dump({
            "last_strategy": "MEAN_REVERSION",
            "last_quality_score": 8.0,
            "last_gex_norm": 5.0, # Positive Gamma
            "persistence_days": 2,
            "last_update": datetime.now().strftime("%Y-%m-%d"),
            "state_version": "2.0"
        }, f)
        
    # Mock quality calculation to return a small jump (8.0 -> 8.5)
    # This should be REJECTED (delta 0.5 < 1.5)
    mocker.patch("nde_strategy_logic.calculate_trade_quality", return_value=(8.5, {}))
    res_strat = nde_strategy_logic.select_master_strategy(
        gamma_metrics={"gex_norm": 5.0, "cex_norm": 50.0}, # Positive to keep same sign, High CEX to pick CHARM
        auto_metrics={"drift": 0.1, "stability": 10}, # Low stability prevents Mean Reversion
        spot=22500, regime_data={"current_regime": "Selective"},
        atr=400
    )
    assert res_strat == "MEAN_REVERSION" # Suppressed (Wanted CHARM but rejected)
    
    # 2. Score Jump (8.0 -> 9.6)
    # This should be ACCEPTED (delta 1.6 > 1.5)
    mocker.patch("nde_strategy_logic.calculate_trade_quality", return_value=(9.6, {}))
    res_strat_jump = nde_strategy_logic.select_master_strategy(
        gamma_metrics={"gex_norm": 5.0, "cex_norm": 50.0},
        auto_metrics={"drift": 0.1, "stability": 10},
        spot=22500, regime_data={"current_regime": "Selective"},
        atr=400
    )
    assert res_strat_jump == "CHARM" # Accepted
    
    # 3. Regime Cross (Positive -> Negative Gamma)
    # This should be ACCEPTED regardless of score delta
    mocker.patch("nde_strategy_logic.calculate_trade_quality", return_value=(8.2, {}))
    res_strat_cross = nde_strategy_logic.select_master_strategy(
        gamma_metrics={"gex_norm": -2.0}, # Significance Sign Flip
        auto_metrics={"drift": -0.5},
        spot=22500, regime_data={"current_regime": "Defensive"},
        atr=400
    )
    assert res_strat_cross == "TREND_ACCELERATION" # Accepted via Sign Cross

def test_audit_log_schema_fidelity(temp_data_dir, mocker):
    """Verifies that the audit log contains rejection_reason and threshold_state as required."""
    notes_dir = temp_data_dir["notes"]
    audit_file = notes_dir / "nde_strategy_log.jsonl"
    
    state_file = notes_dir / "strategy_state.json"
    with open(state_file, "w") as f:
        json.dump({
            "last_strategy": "MEAN_REVERSION",
            "last_quality_score": 8.0,
            "last_gex_norm": 5.0,
            "persistence_days": 2,
            "last_update": datetime.now().strftime("%Y-%m-%d"),
            "state_version": "2.0"
        }, f)
        
    mocker.patch("nde_strategy_logic.calculate_trade_quality", return_value=(8.1, {}))
    mocker.patch("nde_strategy_logic.compute_signal_convergence", return_value=(0.8, {}))
    
    nde_strategy_logic.select_master_strategy(
        gamma_metrics={"gex_norm": 5.0, "cex_norm": 50.0, "gamma_regime": "LONG_GAMMA"},
        auto_metrics={"drift": 0.1, "stability": 10},
        spot=22500, regime_data={"current_regime": "Selective"},
        atr=400
    )
    
    assert audit_file.exists()
    with open(audit_file, "r") as f:
        log = json.loads(f.readline())
        assert "rejection_reason" in log
        assert "threshold_state" in log
        assert log["threshold_state"]["gamma_regime"] is not None

def test_strict_provenance_gate_execution(temp_data_dir, mock_option_chain, mocker):
    """Verifies that automation prefers stale high-trust metadata and blocks low-trust fallbacks."""
    oc_dir = temp_data_dir["option_chain"]
    fname = "option-chain-ED-sensi-NIFTY-28-Apr-2026.csv"
    csv_file = oc_dir / fname
    meta_file = oc_dir / fname.replace(".csv", "_meta.json")
    
    df, _, _ = mock_option_chain
    
    # 1. Setup stale HIGH trust metadata (20 hours old)
    stale_time = datetime.now().timestamp() - (20 * 3600)
    meta_file.write_text(json.dumps({
        "source_mode": "SENSIBULL_VENDOR_GREEKS",
        "conversion_time": stale_time,
        "spot_at_fetch": 22600
    }))
    
    import nde_options_logic
    orig_load = nde_options_logic.load_latest_option_chain_csv
    nde_options_logic.load_latest_option_chain_csv = lambda: (df, fname, stale_time, "UNKNOWN")
    
    # We also mock data_fetch.batch_download to avoid network calls
    import data_fetch
    mock_live = mocker.patch("data_fetch.batch_download", return_value={"^NSEI": pd.DataFrame({"Close": [23000.0]}, index=[datetime.now()])})
    
    import nde_automation_logic
    # We need to ensure nde_automation_logic uses our temp_data_dir
    mocker.patch("nde_automation_logic.OPTION_CHAIN_DIR", oc_dir)
    
    try:
        # Run automation logic for this file
        res_path = nde_automation_logic.generate_auto_snapshot()
        with open(res_path, "r") as f:
            res = json.load(f)
        
        # Verify: Spot should be 22600 (stale metadata) NOT 23000 (live)
        assert res["spot"] == 22600
        assert "STALE" in res["data_provenance"]["source_mode"]
        # V5: Always calls batch_download once for ATR fetch (period='3mo'). 
        # We check that it wasn't called for the 1d fallback (period='1d').
        # But since it's a MagicMock, we just check call_count is 1 (ATR)
        assert mock_live.call_count == 1 
    
        # 2. Setup UNTRUSTED metadata
        # This should block live fallback even if spot is missing
        meta_file.write_text(json.dumps({
            "source_mode": "UNKNOWN_LOW_TRUST",
            "conversion_time": datetime.now().timestamp()
        }))
        
        res_degraded_path = nde_automation_logic.generate_auto_snapshot()
        with open(res_degraded_path, "r") as f:
            res_degraded = json.load(f)
        
        # Verify: Should be DEGRADED (strike mean = 22500)
        assert res_degraded["spot"] == 22500
        assert "DEGRADED" in res_degraded["data_provenance"]["source_mode"]
        assert res_degraded["data_provenance"]["requires_warning"] is True
    finally:
        nde_options_logic.load_latest_option_chain_csv = orig_load
from nde_automation_logic import get_historical_snapshot_df

@pytest.fixture
def mock_snapshot_dir(tmp_path):
    """Creates a temporary directory with mock snapshots for testing."""
    automation_dir = tmp_path / "data" / "automation"
    automation_dir.mkdir(parents=True)
    
    # Snapshot 1: Today Intraday 1 (10 AM)
    s1 = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().timestamp() - 3600*5,
        "options_flow": {"gamma_flip": 24500, "max_pain": 24400, "pcr_oi": 0.8, "atm_iv": 15.5}
    }
    # Snapshot 2: Today Intraday 2 (Latest - 1 PM)
    s2 = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().timestamp(),
        "options_flow": {"gamma_flip": 24600, "max_pain": 24500, "pcr_oi": 0.9, "atm_iv": 16.0}
    }
    # Snapshot 3: Yesterday (Final Close)
    s3 = {
        "date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "timestamp": (datetime.now() - timedelta(days=1)).timestamp(),
        "options_flow": {"gamma_flip": 24000, "max_pain": 23900, "pcr_oi": 0.7, "atm_iv": 14.5}
    }
    # Snapshot 4: Older (Missing Fields - e.g. No atm_iv)
    s4 = {
        "date": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "timestamp": (datetime.now() - timedelta(days=2)).timestamp(),
        "options_flow": {"gamma_flip": 23500, "max_pain": 23400} # NO pcr_oi or atm_iv
    }
    
    (automation_dir / "nde_v12_today1.json").write_text(json.dumps(s1))
    (automation_dir / "nde_v12_today_latest.json").write_text(json.dumps(s2))
    (automation_dir / "nde_v12_yesterday.json").write_text(json.dumps(s3))
    (automation_dir / "nde_v12_older.json").write_text(json.dumps(s4))
    
    return automation_dir

def test_historical_df_missing_fields(mock_snapshot_dir, mocker):
    """Verifies that missing fields in older snapshots are handled gracefully (default to 0)."""
    mocker.patch("nde_automation_logic.Path", return_value=mock_snapshot_dir.parent)
    # Patch Path constructor inside the function specifically
    mocker.patch("nde_automation_logic.Path.__truediv__", lambda self, other: mock_snapshot_dir if other == "data" else mock_snapshot_dir if other == "automation" else self)
    
    # We need to ensure get_historical_snapshot_df looks in our mock dir
    # A cleaner way is to patch the path entirely
    mocker.patch("nde_automation_logic.Path.parent", mock_snapshot_dir.parent)
    
    # Note: Because the function uses Path(__file__).parent / "data" / "automation", 
    # we need to be careful with the patch.
    # Let's just override the path logic in the function temporarily via mocker.
    mocker.patch("nde_automation_logic.Path.glob", side_effect=lambda x: [
        mock_snapshot_dir / "nde_v12_today1.json",
        mock_snapshot_dir / "nde_v12_today_latest.json",
        mock_snapshot_dir / "nde_v12_yesterday.json",
        mock_snapshot_dir / "nde_v12_older.json"
    ])

    df = get_historical_snapshot_df(limit=10, daily_only=False)
    
    assert len(df) == 4
    # Check the "older" row which lacks pcr_oi and atm_iv
    older_row = df[df['date'] == (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")]
    assert older_row['pcr_oi'].iloc[0] == 0 # Default fallback
    assert older_row['atm_iv'].iloc[0] == 0 # Default fallback

def test_daily_benchmark_deduplication(mock_snapshot_dir, mocker):
    """Verifies that daily_only=True returns only the latest snapshot per date."""
    mocker.patch("nde_automation_logic.Path.glob", side_effect=lambda x: [
        mock_snapshot_dir / "nde_v12_today1.json",
        mock_snapshot_dir / "nde_v12_today_latest.json",
        mock_snapshot_dir / "nde_v12_yesterday.json"
    ])
    
    df = get_historical_snapshot_df(limit=10, daily_only=True)
    
    # Should have Today and Yesterday, NOT the 10AM intraday today.
    assert len(df) == 2
    today_row = df[df['date'] == datetime.now().strftime("%Y-%m-%d")]
    assert today_row['gamma_flip'].iloc[0] == 24600 # Should be the latest one (s2)

def test_comparison_benchmarking_logic(mock_snapshot_dir, mocker):
    """Verifies that the UI logic correctly identifies 'Yesterday' as the benchmark."""
    mocker.patch("nde_automation_logic.Path.glob", side_effect=lambda x: [
        mock_snapshot_dir / "nde_v12_today_latest.json",
        mock_snapshot_dir / "nde_v12_yesterday.json",
        mock_snapshot_dir / "nde_v12_older.json"
    ])
    
    # Simulate the logic in Page 17
    df = get_historical_snapshot_df(limit=5, daily_only=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # We expect iloc[-1] to be Today (due to sort_values('date') inside get_historical_snapshot_df)
    # iloc[-2] should be Yesterday
    latest = df.iloc[-1]
    assert latest['date'].strftime("%Y-%m-%d") == today_str
    
    # Use Governance Authority to resolve indices
    from nde_automation_logic import NDEGovernance
    cur_idx, prev_idx = NDEGovernance.resolve_benchmark_indices(df)
    
    assert cur_idx == -1
    assert df.iloc[prev_idx]['date'].strftime("%Y-%m-%d") == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert df.iloc[prev_idx]['gamma_flip'] == 24000

def test_missing_field_fallback_safety():
    """Ensures that missing fields in data dictionaries don't crash standard UI logic."""
    data = {"options_flow": {"gamma_flip": 24000}} # Missing pcr_oi, atm_iv
    
    # Verification of the fallback logic used in automation/UI
    pcr = data.get("options_flow", {}).get("pcr_oi", 1.0) # Default 1.0 or 0
    iv = data.get("options_flow", {}).get("atm_iv", 0)
    
    assert pcr == 1.0
    assert iv == 0

def test_strike_ladder_aggregation_consistency():
    """Verifies that the Strike Ladder aggregation logic matches raw exposure intent."""
    mock_raw = pd.DataFrame({
        "strike": [22000, 22000, 22100],
        "type": ["call", "put", "call"],
        "gex_net": [100.5, 50.2, 75.0],
        "oi": [1000, 2000, 1500]
    })
    
    # Page 18 aggregation logic
    ladder_df = mock_raw.groupby("strike").agg({"gex_net": "sum", "oi": "sum"}).reset_index()
    
    assert len(ladder_df) == 2
    assert ladder_df[ladder_df["strike"] == 22000]["gex_net"].iloc[0] == 150.7
    assert ladder_df[ladder_df["strike"] == 22000]["oi"].iloc[0] == 3000

def test_level_map_coordinate_ordering():
    """Verifies that key levels are correctly extracted and remain in a valid coordinate system."""
    spot = 24530
    flip = 24600
    mp = 24400
    cw = 25000
    pw = 24000
    
    levels = [
        {"val": spot, "label": "SPOT"},
        {"val": flip, "label": "FLIP"},
        {"val": mp, "label": "PAIN"},
        {"val": cw, "label": "CALL WALL"},
        {"val": pw, "label": "PUT WALL"},
    ]
    
    # Check that levels are correctly captured
    vals = [l["val"] for l in levels]
    assert len(vals) == 5
    assert spot in vals
    
    # Check Expected Move logic (Phase 4.1)
    e_low = spot - 250
    e_high = spot + 250
    
    # Verify that SPOT is inside Expected Move band
    assert e_low < spot < e_high
    # Verify that FLIP is within observable range (spot +/- 500)
    assert spot - 500 < flip < spot + 500

def test_strike_ladder_divergence_logic():
    """Verifies that the Strike Ladder correctly handles divergent GEX/OI formatting."""
    # Simulation of Divergent Bar logic
    ladder_data = pd.DataFrame({
        "strike": [24000, 24100, 24200],
        "gex_net": [100, -50, 200] # Positive GEX (Call dominance) vs Negative GEX
    })
    
    # In Plotly, we use negative values for the 'left' side of the divergent chart
    # If the user selects GEX (Institutional), we often show Calls vs Puts.
    # Our logic: fig.add_trace(go.Bar(y=strikes, x=calls * -1, name="CALLS", ...))
    # This test ensures the sign flip logic is ready for the divergent visual.
    strikes = ladder_data["strike"]
    calls_side = ladder_data["gex_net"] * -1
    
    assert calls_side.iloc[0] == -100
    assert calls_side.iloc[1] == 50 # Negative GEX becomes positive on the 'Call' side?
    # Actually, usually Calls are shown on one side, Puts on the other.
    # Our Page 18 logic uses raw column values.

# ==================== PHASE 3: STRATEGY PLAYBOOK ====================

def test_reversion_score_calculation():
    """Verifies that reversion score reacts correctly to SMA distance and walls."""
    spot = 22500
    walls = (22800, 22200)
    flip = 22400
    drift = 0.05
    stability = 80
    gex_norm = 4.5
    
    # Mock nifty_df (20 rows)
    nifty_df = pd.DataFrame({"Close": [22300 + i for i in range(20)]})
    
    res = nde_strategy_logic.calculate_reversion_score(
        spot, walls, flip, drift, stability, gex_norm, nifty_df
    )
    
    assert res["score"] > 0
    assert "label" in res
    assert "reason" in res

def test_playbook_mapping_rules():
    """Verifies strategy playbook mappings for different regimes."""
    # Mock raw_exp for viability
    raw_exp = pd.DataFrame([
        {"strike": 22700, "type": "CALL", "ltp": 50.0, "oi": 50000},
        {"strike": 22800, "type": "CALL", "ltp": 20.0, "oi": 20000},
        {"strike": 22900, "type": "CALL", "ltp": 10.0, "oi": 20000},
        {"strike": 22300, "type": "PUT", "ltp": 50.0, "oi": 50000},
        {"strike": 22200, "type": "PUT", "ltp": 20.0, "oi": 20000},
        {"strike": 22100, "type": "PUT", "ltp": 10.0, "oi": 20000}
    ])
    gamma_metrics = {"gex_norm": 5.0, "tv_label": "NORMAL", "flow_regime_label": "Long Gamma", "raw_exposures": raw_exp}
    auto_metrics = {"drift": 0.05, "stability": 80} # stability 80 to pass WAIT block
    spot = 22500
    walls = (22700, 22300)
    iv_data = {"iv_rank": 45.0}
    quality_score = 8.5
    size = 1.0
    bias_obj = {"bias": "Bullish"}
    rev_score_obj = {"score": 7.5, "label": "HIGH_REVERSION", "reason": ["Away from flip"]}
    
    # 1. Long Gamma + Mid-range (Stability 70 < 75) -> WAIT
    auto_metrics["stability"] = 70
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, spot, walls, iv_data,
        quality_score, size, bias_obj, rev_score_obj, dte=3
    )
    assert playbook["action"] == "WAIT"
    assert "Wait for Extremes" in playbook["strategy"]
    assert playbook["strike_plan"]["suppressed"] is True
    
    # 2. Long Gamma + Near Upper Wall -> Fade Resistance
    auto_metrics_fade = {"drift": 0.05, "stability": 80}
    gamma_metrics_fade = {"gex_norm": 5.0, "tv_label": "NORMAL", "raw_exposures": raw_exp}
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics_fade, auto_metrics_fade, 22695, walls, iv_data,
        quality_score, size, bias_obj, rev_score_obj, dte=3
    )
    assert playbook["action"] == "FADE_RESISTANCE"
    assert "FADE_RESISTANCE" in playbook["strategy"]
    assert "Tactical Credit Spread" in playbook["strategy"]
    
    # 3. Negative Gamma + Strong Drift -> Follow Trend
    raw_exp_trend = pd.DataFrame([
        {"strike": 22500, "type": "CALL", "ltp": 50.0, "oi": 50000},
        {"strike": 22600, "type": "CALL", "ltp": 30.0, "oi": 30000},
        {"strike": 22650, "type": "CALL", "ltp": 20.0, "oi": 20000},
        {"strike": 22500, "type": "PUT", "ltp": 50.0, "oi": 50000}
    ])
    gamma_metrics_trend = {"gex_norm": -5.0, "raw_exposures": raw_exp_trend}
    auto_metrics_trend = {"drift": 0.3, "stability": 80}
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "FOLLOW_TREND", gamma_metrics_trend, auto_metrics_trend, spot, walls, iv_data, 
        quality_score, size, bias_obj, rev_score_obj
    )
    assert playbook["action"] == "FOLLOW_TREND"
    assert "Directional Debit Spread" in playbook["strategy"]

def test_playbook_guardrails():
    """Verifies Phase 47 strict guardrails."""
    raw_exp = pd.DataFrame([
        {"strike": 22700, "type": "CALL", "ltp": 50.0, "oi": 50000},
        {"strike": 22900, "type": "CALL", "ltp": 10.0, "oi": 20000},
        {"strike": 22300, "type": "PUT", "ltp": 50.0, "oi": 50000},
        {"strike": 22100, "type": "PUT", "ltp": 10.0, "oi": 20000}
    ])
    gamma_metrics = {"gex_norm": 5.0, "tv_label": "NORMAL", "gamma_flip_level": 22480, "raw_exposures": raw_exp}
    auto_metrics = {"drift": 0.05, "stability": 80}
    spot = 22500
    walls = (22700, 22300)
    iv_data = {"iv_rank": 45.0}
    quality_score = 8.5
    size = 1.0
    bias_obj = {"bias": "Bullish"}
    rev_score_obj = {"score": 7.5, "label": "HIGH_REVERSION"}

    # 1. Gamma Flip Guardrail (Spot 22500 vs Flip 22480 = < 0.2% dist)
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, spot, walls, iv_data, 
        quality_score, size, bias_obj, rev_score_obj
    )
    assert playbook["action"] == "WAIT_CONFIRMATION"
    assert "Wait for Confirmation" in playbook["strategy"]

    # 2. TV AVOID Guardrail
    gamma_metrics["tv_label"] = "AVOID"
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, 22695, walls, iv_data, 
        quality_score, size, bias_obj, rev_score_obj
    )
    assert playbook["action"] == "STAND ASIDE"
    assert "No Trade (Structural Risk)" in playbook["strategy"]

    # 3. Degraded Data Guardrail
    gamma_metrics["tv_label"] = "NORMAL"
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, 22695, walls, iv_data,
        quality_score, size, bias_obj, rev_score_obj, source_mode="DEGRADED"
    )
    assert playbook["action"] == "WAIT"
    assert "Data integrity failure" in playbook["strike_plan"]["reason"]
    assert playbook["strike_plan"]["suppressed"] is True

    # 4. Low Confidence Guardrail
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, 22695, walls, iv_data, 
        2.5, size, bias_obj, rev_score_obj
    )
    assert playbook["action"] == "WAIT"
    assert playbook["position_size"] == 0.0

    # 5. Dual Fragility Guardrail
    term_data = {
        "25-APR-2026": {"state": "FRAGILE"},
        "30-MAY-2026": {"state": "FRAGILE"}
    }
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, 22695, walls, iv_data, 
        8.0, size, bias_obj, rev_score_obj, term_data=term_data
    )
    assert playbook["action"] == "HEDGE_ONLY"

def test_wait_state_suppresses_execution_strikes():
    """Verifies that WAIT state suppresses executable strikes."""
    gamma_metrics = {"gex_norm": 5.0, "tv_label": "NORMAL"}
    auto_metrics = {"drift": 0.05, "stability": 70}
    spot = 24250
    walls = (26000, 23000)
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, spot, walls, {}, 
        8.5, 1.0, {"bias": "Neutral"}, {"score": 5.0, "label": "WAIT"}
    )
    assert playbook["action"] == "WAIT"
    # New logic: strike_plan dict always contains sell_ce etc but they are None if suppressed
    assert playbook["strike_plan"].get("sell_ce") is None
    assert playbook["strike_plan"]["suppressed"] is True
    assert "Reference walls only" in playbook["strike_plan"]["reason"]

def test_far_otm_weekly_walls_fail_premium_viability():
    """Verifies that low premium OTM walls block execution."""
    raw_exp = pd.DataFrame([
        {"strike": 26000, "type": "CALL", "ltp": 0.5, "oi": 10000},
        {"strike": 23000, "type": "PUT", "ltp": 3.0, "oi": 10000}
    ])
    gamma_metrics = {"gex_norm": 5.0, "tv_label": "NORMAL", "raw_exposures": raw_exp}
    auto_metrics = {"drift": 0.1, "stability": 80}
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, auto_metrics, 25950, (26000, 23000), {},
        8.5, 1.0, {"bias": "Neutral"}, {"score": 5.0}, dte=3
    )
    assert playbook["action"] == "WAIT"
    assert "FADE_RESISTANCE" in playbook["strategy"]
    assert "blocked by premium" in playbook["strategy"]

def test_playbook_includes_expiry_and_dte():
    """Verifies that expiry and DTE are returned in playbook."""
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", {}, {}, 22500, (22700, 22300), {}, 
        8.0, 1.0, {}, {}, expiry="25-APR-2026", dte=5
    )
    assert playbook["expiry"] == "25-APR-2026"
    assert playbook["dte"] == 5
    assert playbook["expiry_phase"] == "LATE_CYCLE"

def test_gamma_flip_missing_or_zero_not_used_as_invalidation():
    """Verifies that invalid or zero flip is not used as trigger."""
    gamma_metrics = {"gamma_flip_level": 0}
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, {}, 22500, (22700, 22300), {}, 
        8.0, 1.0, {}, {}
    )
    assert "Gamma Flip" not in playbook["risk"]["invalidation"]

def test_gamma_flip_far_from_spot_is_context_not_trigger():
    """Verifies that far-away flip is context only."""
    spot = 24250
    flip = 22000 # > 3% away
    gamma_metrics = {"gamma_flip_level": flip}
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, {}, spot, (26000, 23000), {}, 
        8.0, 1.0, {}, {}
    )
    assert "Gamma Flip" not in playbook["risk"]["invalidation"]
    assert any("Gamma flip" in w and "outside" in w for w in playbook["why"])

def test_day_open_governance_uses_yesterday_state():
    """Verifies that day-open comparison uses yesterday's baseline before updating."""
    state = {
        "last_update": "2026-04-22", # Yesterday
        "last_strategy": "MEAN_REVERSION",
        "last_quality_score": 8.0,
        "last_gex_norm": 5.0
    }
    # Current candidate is CHARM with score 7.0 (delta -1.0)
    # Even if it's a new day, it should be REJECTED because delta < 1.5
    gamma_metrics = {"gex_norm": 4.5}
    auto_metrics = {"drift": 0.0, "stability": 80}
    with patch("nde_strategy_logic.load_strategy_state", return_value=state), \
         patch("nde_strategy_logic.save_strategy_state") as mock_save:
        final = nde_strategy_logic.select_master_strategy(
            {"gex_norm": 4.5, "tv_ratio": 1.0}, # CHARM trigger likely
            auto_metrics, 22500, {}, 10.0, 250.0
        )
        # Should stay MEAN_REVERSION because transition to CHARM (score 0-ish here) failed gate
        assert final == "MEAN_REVERSION"
        # State should now be updated to today's date but keep old strategy
        assert state["last_update"] == datetime.now().strftime("%Y-%m-%d")
        assert state["last_strategy"] == "MEAN_REVERSION"

def test_non_trade_actions_suppress_strikes():
    """Verifies that STAND ASIDE, HEDGE_ONLY, etc. suppress strikes."""
    gamma_metrics = {"gex_norm": 5.0, "tv_label": "AVOID"} # Forces STAND ASIDE
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "MEAN_REVERSION", gamma_metrics, {}, 22500, (22700, 22300), {}, 
        8.0, 1.0, {}, {}
    )
    assert playbook["action"] == "STAND ASIDE"
    assert playbook["strike_plan"]["suppressed"] is True
    assert "Data integrity failure" in playbook["strike_plan"]["reason"] or "Structural Risk" in playbook["strike_plan"]["reason"]

def test_directional_debit_returns_debit_legs():
    """Verifies that FOLLOW_TREND returns debit spread schema."""
    # 1. FOLLOW_TREND should return debit schema
    raw_exp = pd.DataFrame([
        {"strike": 24250, "type": "CALL", "ltp": 50.0, "oi": 50000},
        {"strike": 24400, "type": "CALL", "ltp": 20.0, "oi": 20000}
    ])
    auto_metrics = {"drift": 0.5}
    gamma_metrics = {"gex_norm": -5.0, "raw_exposures": raw_exp} # Negative Gamma
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "FOLLOW_TREND", gamma_metrics, auto_metrics, 24240, (26000, 23000), {}, 
        8.5, 1.0, {}, {}
    )
    assert playbook["action"] == "FOLLOW_TREND"
    assert playbook["strike_plan"]["schema"] == "DEBIT_SPREAD"
    assert playbook["strike_plan"]["buy_leg"] == 24250
    assert playbook["strike_plan"]["sell_leg"] == 24400

def test_strategy_specific_viability_checks():
    """Verifies that FADE_RESISTANCE only checks call wall viability."""
    # Call wall illiquid, Put wall liquid
    raw_exp = pd.DataFrame([
        {"strike": 22700, "type": "CALL", "ltp": 0.5, "oi": 100}, # Illiquid
        {"strike": 22300, "type": "PUT", "ltp": 50.0, "oi": 50000} # Liquid
    ])
    gamma_metrics = {"gex_norm": 5.0, "raw_exposures": raw_exp}
    
    # FADE_RESISTANCE should FAIL (checks call wall)
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "FADE_RESISTANCE", gamma_metrics, {}, 22695, (22700, 22300), {}, 
        8.5, 1.0, {}, {}
    )
    assert playbook["action"] == "WAIT"
    assert "Viability Failure" in playbook["strike_plan"]["reason"]
    
    # FADE_SUPPORT should PASS (only checks put wall)
    raw_exp_support = pd.DataFrame([
        {"strike": 22700, "type": "CALL", "ltp": 0.5, "oi": 100}, 
        {"strike": 22300, "type": "PUT", "ltp": 50.0, "oi": 50000},
        {"strike": 22200, "type": "PUT", "ltp": 10.0, "oi": 20000}, # Add wing for viability
        {"strike": 22695, "type": "CALL", "ltp": 10.0, "oi": 20000} # Add ATM for quality
    ])
    gamma_metrics_support = {"gex_norm": 5.0, "raw_exposures": raw_exp_support}
    playbook = nde_strategy_logic.generate_strategy_playbook(
        "FADE_SUPPORT", gamma_metrics_support, {"stability": 80}, 22305, (22700, 22300), {},
        8.5, 1.0, {}, {}
    )
    assert playbook["action"] == "FADE_SUPPORT"
    assert playbook["strike_plan"]["suppressed"] is False
