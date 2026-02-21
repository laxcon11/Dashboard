from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prediction_integrity import generate_monthly_calibration


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate monthly calibration report + proposal")
    parser.add_argument("--month", default=None, help="Month in YYYY-MM format")
    args = parser.parse_args()

    payload = generate_monthly_calibration(month=args.month)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
