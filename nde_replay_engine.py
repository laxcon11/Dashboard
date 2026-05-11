import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import logging
import nde_strategy_logic
import nde_narrative_engine
from nde_execution_compiler import build_execution

logger = logging.getLogger(__name__)

class NDEReplayEngine:
    """
    Institutional Replay & Validation Engine (V3).
    Validates classification consistency, trade quality, and execution fidelity.
    """
    def __init__(self, log_path="logs/execution_audit_log.jsonl"):
        self.log_path = Path(log_path)
        
    def load_snapshots(self):
        if not self.log_path.exists():
            return []
        snapshots = []
        with open(self.log_path, "r") as f:
            for line in f:
                try:
                    snapshots.append(json.loads(line))
                except Exception as e:
                    logger.warning(f"Failed to parse replay snapshot: {e}")
                    continue
        return snapshots

    def replay_snapshot(self, snapshot):
        """
        Re-executes the analytical pipeline for a given historical context.
        """
        ctx = snapshot.get("ctx_snapshot")
        if not ctx: return None
            
        # 1. Restore DataFrames
        if "option_chain_df" in ctx and isinstance(ctx["option_chain_df"], list):
            ctx["option_chain_df"] = pd.DataFrame(ctx["option_chain_df"])
        
        # 2. Re-run Canonical State Engine
        # We simulate the context hydration to verify logic consistency
        from nde_strategy_logic import classify_market_state, select_master_strategy, compute_signal_alignment
        
        # Ensure ctx has all required nested metrics
        m_state = classify_market_state(ctx)
        alignment = compute_signal_alignment(ctx)
        m_state["confidence"] = alignment["confidence"]
        
        # 3. Re-run Strategy Selection
        ctx["master_setup"] = {"market_state": m_state} # Temporary injection
        strategy_code = select_master_strategy(ctx)
        
        # 4. Re-run Narrative & Execution
        narrative = nde_narrative_engine.build_narrative(ctx)
        execution = build_execution(ctx, narrative)
        
        # 5. Validation Logic
        is_state_consistent = snapshot.get("state") == m_state.get("state")
        is_strategy_consistent = snapshot.get("template") == execution.get("template")
        
        return {
            "timestamp": snapshot.get("timestamp"),
            "original_state": snapshot.get("state"),
            "replay_state": m_state.get("state"),
            "original_strategy": snapshot.get("template"),
            "replay_strategy": execution.get("template"),
            "is_consistent": is_state_consistent and is_strategy_consistent,
            "confidence_diff": round(m_state.get("confidence", 0.0) - snapshot.get("confidence", 0.0), 2)
        }

    def run_full_audit(self):
        snapshots = self.load_snapshots()
        if not snapshots:
            print("No audit logs found.")
            return
            
        print(f"--- NDE INSTITUTIONAL AUDIT: Processing {len(snapshots)} snapshots ---")
        results = []
        for i, snap in enumerate(snapshots):
            res = self.replay_snapshot(snap)
            if res:
                results.append(res)
                status = "PASS" if res["is_consistent"] else "FAIL"
                print(f"[{i:03}] {res['timestamp']} | {status} | {res['original_state']} -> {res['replay_state']}")
        
        df = pd.DataFrame(results)
        if not df.empty:
            print(f"\n--- AUDIT SUMMARY ---")
            print(f"Total Processed: {len(df)}")
            print(f"Consistency Accuracy: {df['is_consistent'].mean()*100:.1f}%")
            print(f"Mean Confidence Drift: {df['confidence_diff'].mean():.4f}")
        else:
            print("Audit failed to produce results.")

if __name__ == "__main__":
    audit = NDEReplayEngine()
    audit.run_full_audit()
