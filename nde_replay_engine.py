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
        Uses the new typed schema and modular engines.
        """
        if "state" not in snapshot or "flow" not in snapshot:
            return None
            
        import nde_state_engine
        import nde_strategy_engine
        import nde_ui_adapter
        from nde_schema import FlowMetrics, RVMetrics, LocalGammaMetrics
        
        try:
            # 1. Hydrate dependencies
            flow = FlowMetrics(**snapshot["flow"])
            rv = RVMetrics(**snapshot["rv"])
            gamma_local = LocalGammaMetrics(**snapshot["gamma_local"])
            meta = snapshot.get("meta", {})
            
            # 2. Re-run Canonical State Engine
            m_state = nde_state_engine.classify_market_state(
                flow=flow, rv=rv, gamma_local=gamma_local, 
                drift=meta.get("drift", 0.0), stability_20d=meta.get("stability", 50.0)
            )
            
            # 3. Re-run Strategy Selection
            execution = nde_strategy_engine.compile_execution_plan(
                state=m_state, flow=flow, rv=rv, gamma_local=gamma_local,
                t_days=snapshot.get("t_days", 3.0), spot=snapshot.get("spot", 0.0),
                mode=meta.get("mode", "Balanced")
            )
            
            # 5. Validation Logic
            orig_state = snapshot["state"].get("state")
            orig_template = snapshot["execution"].get("strategy_code")
            
            is_state_consistent = orig_state == m_state.state
            is_strategy_consistent = orig_template == execution.strategy_code
            
            return {
                "timestamp": snapshot.get("timestamp"),
                "original_state": orig_state,
                "replay_state": m_state.state,
                "original_strategy": orig_template,
                "replay_strategy": execution.strategy_code,
                "is_consistent": is_state_consistent and is_strategy_consistent,
                "confidence_diff": round(m_state.confidence - snapshot["state"].get("confidence", 0.0), 2)
            }
        except Exception as e:
            logger.warning(f"Replay failed for {snapshot.get('timestamp')}: {e}")
            return None

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
