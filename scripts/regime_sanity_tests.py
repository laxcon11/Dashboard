"""
Deterministic sanity tests for regime math primitives.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics import round_percentages_sum_to_100


def test_sum_to_100_random_trials(trials: int = 500) -> None:
    for _ in range(trials):
        vals = [random.random(), random.random(), random.random()]
        total = sum(vals) or 1.0
        vals = [v / total for v in vals]
        out = round_percentages_sum_to_100(vals)
        assert sum(out) == 100, f"sum != 100 for {vals} -> {out}"


def test_order_preservation_basic() -> None:
    out = round_percentages_sum_to_100([0.60, 0.25, 0.15])
    assert out[0] >= out[1] >= out[2], f"ordering broken: {out}"


def main() -> int:
    test_sum_to_100_random_trials()
    test_order_preservation_basic()
    print("PASS: regime sanity tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
