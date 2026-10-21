"""test_quantum_seeds.py — vendored quantum seed layer + womb provenance.

GENESIS embed step 7, Phase 2 (2026-10-21). Proves:

  (a) brain.quantum imports and the fail-closed seed-hub certify path is
      exercised with a STUBBED mother-seed source (tests never touch the
      network): a genuinely-quantum mother seed yields a certified draw
      whose record replays via seed_hub.verify_record; a non-quantum
      mother seed is REFUSED (QuantumRequiredError), the halt is logged,
      and no draw is recorded.
  (b) womb.birth records seed provenance in the agent record in both
      modes: "quantum-certified" when the hub certifies, and
      "degraded-stdlib" when the mother seed is not quantum or the hub
      is unavailable. Never a silent quantum claim.
"""

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.abspath(os.path.join(_HERE, "..", ".."))
_BRAIN = os.path.abspath(os.path.join(_HERE, ".."))
for _p in (_ONECODE, _BRAIN):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import womb
from brain import memory as _memory
from brain.quantum import audit, qrng, seed_hub

_STUB_DATE = "2026-10-21"
_STUB_SEED = bytes(range(64))


def _stub_mother(quantum):
    return (_STUB_SEED, "anu_qrng" if quantum else "os_urandom",
            quantum, _STUB_DATE)


class _QuantumStateCase(unittest.TestCase):
    """Redirect ALL vendored-hub state files into a temp dir."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="qseed-")
        state = os.path.join(self._tmp, "state")
        os.makedirs(state)
        self._saved_paths = {
            "hub_consumers": seed_hub.CONSUMERS_FILE,
            "hub_halts": seed_hub.HALTS_FILE,
            "audit_decisions": audit.DECISIONS,
            "audit_archive": audit.SEED_ARCHIVE,
            "audit_network": audit.NETWORK_LOG,
            "qrng_mother": qrng.MOTHER_FILE,
        }
        seed_hub.CONSUMERS_FILE = os.path.join(state, "consumers.json")
        seed_hub.HALTS_FILE = os.path.join(state, "hub_halts.jsonl")
        audit.DECISIONS = os.path.join(state, "decisions.jsonl")
        audit.SEED_ARCHIVE = os.path.join(state, "seed_archive.jsonl")
        audit.NETWORK_LOG = os.path.join(state, "network_checkins.jsonl")
        qrng.MOTHER_FILE = os.path.join(state, "mother_seed.json")
        # Flat legacy mother-seed file so audit._archive_seed can archive
        # it and seed_hub.verify_record can replay draws against it.
        with open(qrng.MOTHER_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": _STUB_DATE, "seed_hex": _STUB_SEED.hex(),
                       "source": "anu_qrng", "quantum": True}, f)
        self._real_mother = qrng.get_mother_seed
        self._prev_test_env = os.environ.get("SEED_HUB_TEST")
        os.environ["SEED_HUB_TEST"] = "1"  # hub tags these draws as test

    def tearDown(self):
        qrng.get_mother_seed = self._real_mother
        seed_hub.CONSUMERS_FILE = self._saved_paths["hub_consumers"]
        seed_hub.HALTS_FILE = self._saved_paths["hub_halts"]
        audit.DECISIONS = self._saved_paths["audit_decisions"]
        audit.SEED_ARCHIVE = self._saved_paths["audit_archive"]
        audit.NETWORK_LOG = self._saved_paths["audit_network"]
        qrng.MOTHER_FILE = self._saved_paths["qrng_mother"]
        if self._prev_test_env is None:
            os.environ.pop("SEED_HUB_TEST", None)
        else:
            os.environ["SEED_HUB_TEST"] = self._prev_test_env


class TestQuantumPackage(_QuantumStateCase):

    def test_package_imports(self):
        from brain.quantum import qrng as _q, seed_seal, audit as _a, seed_hub as _h
        self.assertEqual(seed_seal.LAW, "LAW-099")
        self.assertTrue(hasattr(_h, "consume"))
        self.assertTrue(hasattr(_q, "get_mother_seed"))
        self.assertTrue(hasattr(_a, "log"))

    def test_certified_draw_with_stubbed_quantum_mother(self):
        qrng.get_mother_seed = lambda: _stub_mother(True)
        seed_hub.register_consumer("test-consumer", "brain/tests",
                                   "test:draw", quantum_required=True)
        out = seed_hub.consume("test-consumer", kind="bytes",
                               domain="test:draw", n_bytes=32,
                               context="pytest certify path")
        self.assertEqual(len(out["bytes"]), 32)
        rec = out["record"]
        self.assertIs(rec["quantum"], True)
        self.assertEqual(rec["seed_source"], "anu_qrng")
        self.assertIs(rec["test"], True)  # SEED_HUB_TEST tagging works
        # The draw is on the audit log and replays from the archived seed.
        logged = [r for r in audit.read_all()
                  if r.get("consumer_id") == "test-consumer"]
        self.assertEqual(len(logged), 1)
        verdict = seed_hub.verify_record(rec)
        self.assertTrue(verdict["ok"], verdict)

    def test_fail_closed_on_non_quantum_mother(self):
        qrng.get_mother_seed = lambda: _stub_mother(False)
        seed_hub.register_consumer("test-strict", "brain/tests",
                                   "test:strict", quantum_required=True)
        with self.assertRaises(seed_hub.QuantumRequiredError):
            seed_hub.consume("test-strict", kind="bytes",
                             domain="test:strict", n_bytes=32)
        # Fail-closed means: halt logged, NO draw recorded.
        with open(seed_hub.HALTS_FILE, encoding="utf-8") as f:
            halts = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(halts), 1)
        self.assertEqual(halts[0]["consumer_id"], "test-strict")
        self.assertEqual(audit.read_all(), [])


class TestWombSeedProvenance(_QuantumStateCase):

    def setUp(self):
        super().setUp()
        self._prev_data_dir = os.environ.get("GENESIS_DATA_DIR")
        os.environ["GENESIS_DATA_DIR"] = os.path.join(self._tmp, "data")
        womb._db = None
        _memory._db = None
        self._real_load_hub = womb._load_seed_hub

    def tearDown(self):
        womb._load_seed_hub = self._real_load_hub
        womb._db = None
        _memory._db = None
        if self._prev_data_dir is None:
            os.environ.pop("GENESIS_DATA_DIR", None)
        else:
            os.environ["GENESIS_DATA_DIR"] = self._prev_data_dir
        super().tearDown()

    def test_birth_records_quantum_certified(self):
        qrng.get_mother_seed = lambda: _stub_mother(True)
        a = womb.birth(seed="certified birth")
        self.assertEqual(a["seed_source"], "quantum-certified")
        self.assertIn(a["trait"], womb._TRAITS)
        # The certified draw is on the vendored hub's audit log.
        draws = [r for r in audit.read_all()
                 if r.get("consumer_id") == womb._WOMB_CONSUMER]
        self.assertEqual(len(draws), 1)
        self.assertIs(draws[0]["quantum"], True)
        # Replication births draw (and record) their own provenance.
        child = womb.birth(parent_id=a["id"], seed="replication")
        self.assertEqual(child["generation"], 2)
        self.assertEqual(child["seed_source"], "quantum-certified")

    def test_birth_records_degraded_when_mother_not_quantum(self):
        qrng.get_mother_seed = lambda: _stub_mother(False)
        a = womb.birth(seed="degraded birth")
        self.assertEqual(a["seed_source"], "degraded-stdlib")
        self.assertIn(a["trait"], womb._TRAITS)
        # No quantum draw was issued or claimed.
        draws = [r for r in audit.read_all()
                 if r.get("consumer_id") == womb._WOMB_CONSUMER]
        self.assertEqual(draws, [])

    def test_birth_records_degraded_when_hub_unavailable(self):
        womb._load_seed_hub = lambda: None
        a = womb.birth(seed="no hub")
        self.assertEqual(a["seed_source"], "degraded-stdlib")
        self.assertEqual(a["status"], "alive")


if __name__ == "__main__":
    unittest.main()
