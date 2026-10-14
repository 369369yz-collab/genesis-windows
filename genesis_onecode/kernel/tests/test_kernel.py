"""kernel/tests/test_kernel.py — the kernel test suite (unittest, zero spend).

Coverage:
  1. arbitration precedence: yz_direct > local_law > extended_mind
  2. extended-mind response without the source tag -> rejected
  3. FabricationError on evidence-less report_completion (kernel claims_ledger)
  4. honesty.py failure honesty: a failing check surfaces as FAILED, never a
     silent pass
  5. laws.json count reconciliation: 168 CODEX in + 8 standing = 176 out
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_KERNEL = os.path.dirname(_HERE)
if _KERNEL not in sys.path:
    sys.path.insert(0, _KERNEL)

from arbitration import (  # noqa: E402
    ArbitrationError, Instruction, arbitrate, EXTENDED_MIND_SOURCE_TAG)
from claims_ledger import ClaimsLedger, FabricationError, report_completion  # noqa: E402
import honesty  # noqa: E402

CODEX_PATH = os.path.expanduser("~/workspace/content_team/law_library/CODEX.json")
LAWS_PATH = os.path.join(_KERNEL, "laws.json")


def _yz(topic, action):
    return Instruction(id="i-yz", topic=topic, action=action,
                       source="yz_direct", provenance={"verbatim": True})


def _law(topic, action):
    return Instruction(id="i-law", topic=topic, action=action,
                       source="local_law", provenance={"law_id": "LAW-004"})


def _mind(topic, action, tagged=True):
    prov = {"source": EXTENDED_MIND_SOURCE_TAG} if tagged else {}
    return Instruction(id="i-mind", topic=topic, action=action,
                       source="extended_mind", provenance=prov)


class TestArbitrationPrecedence(unittest.TestCase):
    def test_yz_direct_beats_local_law(self):
        d = arbitrate([_law("publish", "hold"), _yz("publish", "go now")],
                      queue_path=_tmp_queue())
        self.assertEqual(d.winner.source, "yz_direct")
        self.assertTrue(any(i.id == "i-law" for i, _ in d.rejected))

    def test_local_law_beats_extended_mind(self):
        d = arbitrate([_mind("tone", "joking"), _law("tone", "serious")],
                      queue_path=_tmp_queue())
        self.assertEqual(d.winner.source, "local_law")
        self.assertTrue(any(i.id == "i-mind" for i, _ in d.rejected))

    def test_yz_direct_beats_extended_mind(self):
        d = arbitrate([_mind("x", "a"), _yz("x", "b")],
                      queue_path=_tmp_queue())
        self.assertEqual(d.winner.source, "yz_direct")

    def test_conflict_logged_to_queue(self):
        qp = _tmp_queue()
        d = arbitrate([_law("publish", "hold"), _yz("publish", "go now")],
                      queue_path=qp)
        self.assertEqual(len(d.conflicts_logged), 1)
        with open(qp, encoding="utf-8") as f:
            rec = json.loads(f.read().strip().splitlines()[-1])
        self.assertEqual(rec["kind"], "law_conflict_flag")
        self.assertEqual(rec["status"], "pending")
        self.assertEqual(rec["owner"], "yz_agent")
        self.assertIn("deadline", rec)
        self.assertIn("auto_rejected", rec["detail"])

    def test_same_rank_tie_all_rejected_and_logged(self):
        qp = _tmp_queue()
        a = Instruction(id="a", topic="t", action="go", source="local_law")
        b = Instruction(id="b", topic="t", action="stop", source="local_law")
        d = arbitrate([a, b], queue_path=qp)
        self.assertIsNone(d.winner)
        self.assertEqual(len(d.rejected), 2)
        self.assertEqual(len(d.conflicts_logged), 1)

    def test_agreement_silent_winner(self):
        d = arbitrate([_mind("x", "rest"), _law("x", "rest")],
                      queue_path=_tmp_queue())
        self.assertEqual(d.winner.source, "local_law")
        self.assertEqual(len(d.conflicts_logged), 0)

    def test_unknown_source_raises(self):
        bad = Instruction(id="bad", topic="t", action="x", source="ghost")
        with self.assertRaises(ArbitrationError):
            arbitrate([bad], queue_path=_tmp_queue())


class TestExtendedMindTag(unittest.TestCase):
    def test_missing_source_tag_rejected(self):
        d = arbitrate([_mind("tone", "playful", tagged=False),
                       _yz("tone", "warm")],
                      queue_path=_tmp_queue())
        rej = {i.id: r for i, r in d.rejected}
        self.assertIn("i-mind", rej)
        self.assertIn(EXTENDED_MIND_SOURCE_TAG, rej["i-mind"])

    def test_all_untagged_nothing_trusted(self):
        d = arbitrate([_mind("tone", "playful", tagged=False)],
                      queue_path=_tmp_queue())
        self.assertIsNone(d.winner)
        self.assertIn("untrusted", d.reason)

    def test_tagged_mind_advises_when_alone(self):
        d = arbitrate([_mind("tip", "stretch first")],
                      queue_path=_tmp_queue())
        self.assertEqual(d.winner.source, "extended_mind")


class TestFabricationError(unittest.TestCase):
    def _tmp_db(self):
        fd, p = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(p) and os.unlink(p))
        return p

    def test_evidence_less_completion_raises(self):
        ledger = ClaimsLedger(db_path=self._tmp_db())
        with self.assertRaises(FabricationError):
            ledger.report_completion("kernel built")
        with self.assertRaises(FabricationError):
            ledger.report_completion("kernel built", None)
        with self.assertRaises(FabricationError):
            ledger.report_completion("kernel built", {})

    def test_blocked_completion_is_ledgered(self):
        ledger = ClaimsLedger(db_path=self._tmp_db())
        try:
            ledger.report_completion("kernel built")
        except FabricationError:
            pass
        stats = ledger.stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["blocked"], 1)
        self.assertEqual(stats["accepted"], 0)

    def test_evidenced_completion_passes_and_ledgers(self):
        ledger = ClaimsLedger(db_path=self._tmp_db())
        h = ledger.report_completion(
            "kernel built", {"files": ["honesty.py"], "tests": "12 passed"})
        self.assertTrue(isinstance(h, str) and len(h) == 64)
        stats = ledger.stats()
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(stats["blocked"], 0)
        row = ledger.audit(limit=1)[0]
        self.assertEqual(row["evidence_hash"], h)

    def test_module_level_report_completion(self):
        db = self._tmp_db()
        with self.assertRaises(FabricationError):
            report_completion("shipped", db_path=db)
        h = report_completion("shipped", {"build": "green"}, db_path=db)
        self.assertEqual(len(h), 64)


class TestHonestyFailure(unittest.TestCase):
    def test_failure_is_never_silent(self):
        # Sabotage the laws check by pointing at a nonexistent path.
        orig = honesty._LAWS_PATH
        honesty._LAWS_PATH = "/nonexistent/laws.json"
        try:
            rep = honesty.boot_self_test()
        finally:
            honesty._LAWS_PATH = orig
        self.assertFalse(rep.passed)
        law_check = next(c for c in rep.checks if c.name == "laws_loaded")
        self.assertFalse(law_check.passed)
        self.assertEqual(law_check.status, "failed")
        self.assertIn("FAILED", rep.statement)
        self.assertTrue(rep.statement)  # a real statement, not silence

    def test_boot_report_structure(self):
        rep = honesty.boot_self_test()
        names = {c.name for c in rep.checks}
        self.assertEqual(names, {"model_reachable", "memory_intact",
                                 "voice_alive", "laws_loaded",
                                 "knows_ignorance"})
        for c in rep.checks:
            self.assertIn(c.status, ("passed", "failed", "skipped"))
            self.assertEqual(c.passed, c.status == "passed")

    def test_voice_parked_is_reported_not_hidden(self):
        rep = honesty.boot_self_test()
        v = next(c for c in rep.checks if c.name == "voice_alive")
        self.assertEqual(v.status, "skipped")
        self.assertIn("parked", v.detail.lower())


class TestLawsReconciliation(unittest.TestCase):
    def test_counts_in_equal_counts_out(self):
        with open(CODEX_PATH, encoding="utf-8") as f:
            codex = json.load(f)
        with open(LAWS_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        n_codex = len(codex["laws"])
        counts = doc["counts"]
        self.assertEqual(n_codex, 168, "CODEX law count changed — reconcile before shipping")
        self.assertEqual(counts["codex"], n_codex)
        self.assertEqual(counts["standing"], 8)
        self.assertEqual(counts["total"], 176)
        self.assertEqual(len(doc["laws"]), 176)
        self.assertEqual(counts["codex"] + counts["standing"], counts["total"])

    def test_ids_unique_and_ordered(self):
        with open(LAWS_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        ids = [l["id"] for l in doc["laws"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[:168], ["LAW-%03d" % i for i in range(1, 169)])
        self.assertEqual(ids[168:], ["STANDING-%02d" % i for i in range(1, 9)])

    def test_each_record_has_required_fields(self):
        with open(LAWS_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        for rec in doc["laws"]:
            for k in ("id", "name", "text", "source", "enforced_by"):
                self.assertIn(k, rec, "record %s missing %s" % (rec.get("id"), k))
            self.assertTrue(rec["text"], "record %s has empty text" % rec["id"])


def _tmp_queue():
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    # cleanup handled by caller-process exit; keep it simple and explicit:
    return p


if __name__ == "__main__":
    unittest.main(verbosity=2)
