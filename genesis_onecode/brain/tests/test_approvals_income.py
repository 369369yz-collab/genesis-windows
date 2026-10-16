"""test_approvals_income.py — unittest for brain/approvals.py + brain/income.py.
Run: python3 -m unittest test_approvals_income -v
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))       # brain/ itself (import womb)
sys.path.insert(0, os.path.join(_HERE, "..", ".."))  # genesis_onecode/ (from brain import ...)


def _fresh_db():
    tmp = tempfile.mkdtemp(prefix="apptest-")
    os.environ["GENESIS_DATA_DIR"] = tmp
    import approvals, income
    approvals._db = None
    income._db = None
    return approvals, income


class TestApprovals(unittest.TestCase):
    def setUp(self):
        self.appr, _ = _fresh_db()

    def test_request_and_pending(self):
        aid = self.appr.request_approval("lease1", "submit_form", "post comment",
                                         "genius-abc")
        pend = self.appr.pending()
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["id"], aid)
        self.assertEqual(pend[0]["status"], "pending")

    def test_no_duplicate_requests(self):
        a1 = self.appr.request_approval("lease1", "send", "d1")
        a2 = self.appr.request_approval("lease1", "send", "d2")
        self.assertEqual(a1, a2)
        self.assertEqual(len(self.appr.pending()), 1)

    def test_decide_approve(self):
        aid = self.appr.request_approval("lease1", "pay", "buy X")
        rec = self.appr.decide(aid, True)
        self.assertEqual(rec["status"], "approved")
        self.assertTrue(self.appr.is_approved("lease1", "pay"))
        self.assertEqual(self.appr.pending(), [])

    def test_decide_deny(self):
        aid = self.appr.request_approval("lease1", "pay", "buy X")
        rec = self.appr.decide(aid, False)
        self.assertEqual(rec["status"], "denied")
        self.assertFalse(self.appr.is_approved("lease1", "pay"))

    def test_decide_unknown(self):
        self.assertIsNone(self.appr.decide("appr-nope", True))


class TestIncome(unittest.TestCase):
    def setUp(self):
        _, self.inc = _fresh_db()

    def test_record_needs_evidence(self):
        with self.assertRaises(ValueError):
            self.inc.record_income("genius-abc", 10.0, evidence="")
        with self.assertRaises(ValueError):
            self.inc.record_income("genius-abc", 0.0, evidence="x")

    def test_record_and_ledger(self):
        r = self.inc.record_income("genius-abc", 25.0, "USD",
                                   "article sale", "YZ confirmed 2026-10-16")
        self.assertEqual(r["amount"], 25.0)
        self.assertEqual(r["status"], "confirmed")
        books = self.inc.ledger()
        self.assertEqual(len(books), 1)
        tot = self.inc.total()
        self.assertEqual(tot["USD"]["total"], 25.0)

    def test_hunt_creates_missions(self):
        created = self.inc.hunt()
        self.assertEqual(len(created), 3)
        again = self.inc.hunt()
        self.assertEqual(again, [])  # no duplicates while pending/active


if __name__ == "__main__":
    unittest.main()
