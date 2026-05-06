import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class PositionManager:
    """
    Institutional Position Lifecycle Engine.
    Tracks entry, exit, PnL, and regime-based performance.
    """
    def __init__(self, positions_file="data/active_positions.json"):
        self.positions_file = Path(positions_file)
        self.positions_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_positions = self._load_positions()

    def _load_positions(self):
        if self.positions_file.exists():
            try:
                return json.loads(self.positions_file.read_text())
            except Exception as e:
                logger.error(f"Failed to load positions: {e}")
        return []

    def save_positions(self):
        self.positions_file.write_text(json.dumps(self.active_positions, indent=2))

    def open_position(self, ctx: dict, narrative: dict, execution_plan: dict):
        """Records a new position entry with full context."""
        entry = {
            "pos_id": f"POS_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "entry_timestamp": datetime.now().isoformat(),
            "entry_spot": ctx.get("spot"),
            "regime_at_entry": narrative.get("dominant_state"),
            "strategy": execution_plan.get("template"),
            "legs": execution_plan.get("legs"),
            "confidence": narrative.get("confidence"),
            "status": "OPEN",
            "pnl": 0.0,
            "max_ae": 0.0, # Max Adverse Excursion
            "max_fe": 0.0  # Max Favorable Excursion
        }
        self.active_positions.append(entry)
        self.save_positions()
        logger.info(f"Opened new position: {entry['pos_id']} ({entry['strategy']})")
        return entry['pos_id']

    def update_pnl(self, current_spot: float):
        """Updates PnL and excursions for all open positions."""
        for pos in self.active_positions:
            if pos["status"] == "OPEN":
                # Simplified PnL proxy (directional for now)
                entry_spot = pos["entry_spot"]
                strategy = pos["strategy"]
                
                # Proxy PnL based on spot move
                diff = current_spot - entry_spot
                if strategy == "Straddle":
                    pnl = abs(diff) # Oversimplified
                elif "Debit Spread" in strategy:
                    # Need to know if it was Call or Put spread
                    # For now just log spot move
                    pnl = diff 
                else:
                    pnl = 0
                    
                pos["pnl"] = pnl
                pos["max_ae"] = min(pos["max_ae"], pnl)
                pos["max_fe"] = max(pos["max_fe"], pnl)
        self.save_positions()

    def close_position(self, pos_id: str, exit_spot: float, regime_at_exit: str):
        """Finalizes a position and records exit metrics."""
        for pos in self.active_positions:
            if pos["pos_id"] == pos_id and pos["status"] == "OPEN":
                pos["status"] = "CLOSED"
                pos["exit_timestamp"] = datetime.now().isoformat()
                pos["exit_spot"] = exit_spot
                pos["regime_at_exit"] = regime_at_exit
                # Final PnL calculation would go here
                self.save_positions()
                logger.info(f"Closed position: {pos_id} at {exit_spot}")
                return pos
        return None
