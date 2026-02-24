"""Unit tests for regime settings load/merge/reset behavior."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import regime_model as rm


class TestRegimeModel(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_settings_file = rm.SETTINGS_FILE
        rm.SETTINGS_FILE = Path(self._tmp.name) / "regime_settings.json"

    def tearDown(self) -> None:
        rm.SETTINGS_FILE = self._orig_settings_file
        self._tmp.cleanup()

    def test_load_defaults_when_file_missing(self) -> None:
        settings = rm.load_regime_settings()
        self.assertIn("blend", settings)
        self.assertEqual(settings["blend"]["macro_weight"], 0.60)
        self.assertIn("macro_factors", settings)
        self.assertIn("liquidity_factors", settings)

    def test_partial_override_deep_merge(self) -> None:
        rm.SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "blend": {"neutral_band": 0.28},
                    "macro_factors": {"nifty50": {"weight": 0.20}},
                }
            )
        )
        settings = rm.load_regime_settings()
        self.assertEqual(settings["blend"]["neutral_band"], 0.28)
        self.assertEqual(settings["macro_factors"]["nifty50"]["weight"], 0.20)
        # Unspecified defaults must remain intact.
        self.assertIn("risk_on_threshold", settings["blend"])
        self.assertIn("nasdaq", settings["macro_factors"])

    def test_reset_writes_defaults(self) -> None:
        out = rm.reset_regime_settings()
        self.assertTrue(rm.SETTINGS_FILE.exists())
        saved = json.loads(rm.SETTINGS_FILE.read_text())
        self.assertEqual(saved["blend"]["macro_weight"], 0.60)
        self.assertEqual(out["blend"]["liquidity_weight"], 0.40)


if __name__ == "__main__":
    unittest.main()
