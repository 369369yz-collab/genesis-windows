"""test_voice_config.py — unittest: voice stays parked behind one flag.

Covers: voice_enabled defaults to false; the re-activation path is a
single-flag flip; required asset paths are declared.
Run: python3 -m unittest test_voice_config -v
"""

import json
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(_HERE, "..", "voice_config.json")


class TestVoiceConfig(unittest.TestCase):
    def _load(self):
        with open(CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_voice_flag_default_off(self):
        cfg = self._load()
        self.assertIn("voice_enabled", cfg)
        self.assertIs(cfg["voice_enabled"], False)

    def test_single_flag_reactivation_path(self):
        cfg = self._load()
        reactivated = dict(cfg)
        reactivated["voice_enabled"] = True  # the ONE flag flip
        # schema stays valid after the flip: nothing else required to change
        for key in ("primary_model", "primary_model_path",
                    "fallback_model", "fallback_model_path",
                    "engine", "lipsync_engine", "note"):
            self.assertIn(key, reactivated)
        self.assertTrue(reactivated["voice_enabled"])

    def test_asset_paths_declared(self):
        cfg = self._load()
        self.assertTrue(cfg["primary_model_path"].endswith(
            "fa_IR-mana-medium.onnx"))
        self.assertTrue(cfg["fallback_model_path"].endswith(
            "fa_IR-amir-medium.onnx"))
        self.assertEqual(cfg["engine"], "piper-v1.2.0")
        self.assertEqual(cfg["lipsync_engine"], "rhubarb-1.14.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
