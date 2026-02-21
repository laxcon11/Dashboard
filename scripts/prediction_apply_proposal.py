from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prediction_integrity import apply_approved_proposal


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply approved monthly calibration proposal")
    parser.add_argument("--proposal", default=None, help="Path to proposal JSON")
    parser.add_argument("--approved-by", default="cli", help="Approver identity")
    args = parser.parse_args()

    payload = apply_approved_proposal(proposal_path=args.proposal, approved_by=args.approved_by)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
