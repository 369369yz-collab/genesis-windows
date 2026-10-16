"""test_codex.py — unittest for brain/codex.py.

The laws must be fail-closed: unknown kinds denied, money never moves
without approval, safe local actions always allowed.
Run: python3 -m unittest test_codex -v
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

import codex


class TestCodex(unittest.TestCase):
    def test_safe_kinds_allowed(self):
        for kind in ("chat", "read_memory", "write_memory", "compute",
                     "browse_read", "browse_act"):
            v = codex.check({"kind": kind})
            self.assertTrue(v["allowed"], kind)

    def test_spend_denied_without_approval(self):
        v = codex.check({"kind": "spend", "amount": 5})
        self.assertFalse(v["allowed"])
        self.assertIn("zero-spend", v["reason"])

    def test_spend_allowed_with_approval(self):
        v = codex.check({"kind": "spend", "amount": 5, "approved": True})
        self.assertTrue(v["allowed"])

    def test_spend_zero_amount_is_not_spend(self):
        v = codex.check({"kind": "spend", "amount": 0})
        self.assertTrue(v["allowed"])

    def test_spend_bad_amount_denied(self):
        v = codex.check({"kind": "spend", "amount": "lots"})
        self.assertFalse(v["allowed"])

    def test_publish_needs_approval(self):
        self.assertFalse(codex.check({"kind": "publish"})["allowed"])
        self.assertTrue(
            codex.check({"kind": "publish", "approved": True})["allowed"])

    def test_unknown_kind_fail_closed(self):
        for kind in ("teleport", "", "CHAT", "Spend"):
            v = codex.check({"kind": kind})
            self.assertFalse(v["allowed"], kind)
            self.assertIn("denied", v["reason"])

    def test_malformed_action_denied(self):
        self.assertFalse(codex.check("chat")["allowed"])
        self.assertFalse(codex.check(None)["allowed"])
        self.assertFalse(codex.check({})["allowed"])

    def test_requires_yz_approval(self):
        self.assertTrue(codex.requires_yz_approval("spend"))
        self.assertTrue(codex.requires_yz_approval("delete_data"))
        self.assertFalse(codex.requires_yz_approval("chat"))
        self.assertFalse(codex.requires_yz_approval("unknown-kind"))


if __name__ == "__main__":
    unittest.main()
