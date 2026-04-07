"""
Phase 5 Recovery tools:
- run health checks
- rebuild local history
- backfill latest market windows
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import watchlist_manager as wm
from data_fetch import batch_download


def run_cmd(args: list[str]) -> int:
    print("Running:", " ".join(args))
    return subprocess.call(args, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true", help="Run phase0 health checks.")
    parser.add_argument("--rebuild-history", action="store_true", help="Rebuild local NSE history parquet.")
    parser.add_argument("--backfill-days", type=int, default=0, help="Backfill recent windows via batch download.")
    parser.add_argument("--repair-stale-bhavcopy", action="store_true", help="Repair stale symbols from latest Bhavcopy.")
    parser.add_argument("--parity-report", action="store_true", help="Run Bhavcopy parity report.")
    parser.add_argument("--trust-score", action="store_true", help="Run unified data trust score report.")
    parser.add_argument("--backfill-regime-history", action="store_true", help="Backfill 90D timeline from existing EOD snapshots.")
    args = parser.parse_args()

    rc = 0
    if args.health:
        rc |= run_cmd([sys.executable, "scripts/phase0_health_check.py"])

    if args.rebuild_history:
        rc |= run_cmd([sys.executable, "scripts/build_nse230_history.py"])

    if args.backfill_days > 0:
        watchlists = wm.load_watchlists()
        symbols = sorted(set(sum((v for v in watchlists.values() if isinstance(v, list)), [])))
        # Backfill pull through existing data stack (parquet + fallback)
        period = "6mo" if args.backfill_days > 90 else ("3mo" if args.backfill_days > 30 else "1mo")
        print(f"Backfilling ~{args.backfill_days}D using period={period} for {len(symbols)} symbols")
        _ = batch_download(symbols[:400], period=period)
        print("Backfill completed.")

    if args.repair_stale_bhavcopy:
        rc |= run_cmd([sys.executable, "scripts/repair_stale_from_bhavcopy.py"])

    if args.parity_report:
        rc |= run_cmd([sys.executable, "scripts/bhavcopy_parity_report.py"])

    if args.trust_score:
        rc |= run_cmd([sys.executable, "scripts/data_trust_score.py"])

    if args.backfill_regime_history:
        rc |= run_cmd([sys.executable, "scripts/backfill_regime_history.py"])

    if not (
        args.health
        or args.rebuild_history
        or args.backfill_days > 0
        or args.repair_stale_bhavcopy
        or args.parity_report
        or args.trust_score
        or args.backfill_regime_history
    ):
        parser.print_help()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
