"""test_first_run_seed.py — first-run mother seed + honest third tier.

GENESIS embed step 7, Phase 3 (2026-10-21). Proves:

  * brain/quantum/first_run.ensure_mother_seed() creates a sealed
    local-CSPRNG mother EXACTLY once on a fresh state dir (LAW-099
    sealed, source "local-csprng", quantum False, sidecar with the
    matching seed SHA-256) and reuses it on the second call;
  * a womb birth on that mother records seed_source "local-csprng" —
    drawn through the seed hub under the mother's true source label,
    with the quantum consumer's fail-closed halt on record — NEVER
    "quantum-certified";
  * a pre-existing quantum mother is left untouched by ensure (no
    re-seed, no relabel) and births stay "quantum-certified".

All hub/seal state files are redirected into a temp dir; the mother
seed machinery runs for real (no network: get_mother_seed reads the
sealed cache the tests create).
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.abspath(os.path.join(_HERE, "..", ".."))
_BRAIN = os.path.abspath(os.path.join(_HERE, ".."))
for _p in (_ONECODE, _BRAIN):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import womb
from brain import memory as _memory
from brain.quantum import audit, first_run, qrng, seed_hub, seed_seal


class _FirstRunStateCase(unittest.TestCase):
    """Redirect ALL vendored quantum state files into a temp dir."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="firstrun-")
        state = os.path.join(self._tmp, "state")
        os.makedirs(state)
        self._state = state
        self._saved = {
            "hub_consumers": seed_hub.CONSUMERS_FILE,
            "hub_halts": seed_hub.HALTS_FILE,
            "audit_decisions": audit.DECISIONS,
            "audit_archive": audit.SEED_ARCHIVE,
            "audit_network": audit.NETWORK_LOG,
            "qrng_mother": qrng.MOTHER_FILE,
            "seal_mother": seed_seal.MOTHER_FILE,
            "seal_key": seed_seal.KEY_FILE,
            "seal_log": seed_seal.SEAL_LOG,
        }
        mother = os.path.join(state, "mother_seed.json")
        seed_hub.CONSUMERS_FILE = os.path.join(state, "consumers.json")
        seed_hub.HALTS_FILE = os.path.join(state, "hub_halts.jsonl")
        audit.DECISIONS = os.path.join(state, "decisions.jsonl")
        audit.SEED_ARCHIVE = os.path.join(state, "seed_archive.jsonl")
        audit.NETWORK_LOG = os.path.join(state, "network_checkins.jsonl")
        qrng.MOTHER_FILE = mother
        seed_seal.MOTHER_FILE = mother
        seed_seal.KEY_FILE = os.path.join(state, "seed_seal.key")
        seed_seal.SEAL_LOG = os.path.join(state, "seed_seal.log")
        self._prev_test_env = os.environ.get("SEED_HUB_TEST")
        os.environ["SEED_HUB_TEST"] = "1"  # hub tags these draws as test

    def tearDown(self):
        seed_hub.CONSUMERS_FILE = self._saved["hub_consumers"]
        seed_hub.HALTS_FILE = self._saved["hub_halts"]
        audit.DECISIONS = self._saved["audit_decisions"]
        audit.SEED_ARCHIVE = self._saved["audit_archive"]
        audit.NETWORK_LOG = self._saved["audit_network"]
        qrng.MOTHER_FILE = self._saved["qrng_mother"]
        seed_seal.MOTHER_FILE = self._saved["seal_mother"]
        seed_seal.KEY_FILE = self._saved["seal_key"]
        seed_seal.SEAL_LOG = self._saved["seal_log"]
        if self._prev_test_env is None:
            os.environ.pop("SEED_HUB_TEST", None)
        else:
            os.environ["SEED_HUB_TEST"] = self._prev_test_env


class TestEnsureMotherSeed(_FirstRunStateCase):

    def test_creates_once_then_reuses(self):
        self.assertIsNone(first_run.local_mother_info())
        r1 = first_run.ensure_mother_seed()
        self.assertTrue(r1["created"])
        self.assertEqual(r1["provenance"], "local-csprng")
        # Sealed through the upstream mechanism, honest fields.
        obj = seed_seal.read_sealed()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(obj["date"], today)
        self.assertEqual(obj["source"], "local-csprng")
        self.assertIs(obj["quantum"], False)
        seed = bytes.fromhex(obj["seed_hex"])
        self.assertEqual(len(seed), 64)
        # Sidecar matches the sealed seed.
        with open(first_run.sidecar_path(), encoding="utf-8") as f:
            side = json.load(f)
        self.assertEqual(side["provenance"], "local-csprng")
        self.assertEqual(side["seed_sha256"],
                         hashlib.sha256(seed).hexdigest())
        self.assertEqual(r1["seed_sha256"], side["seed_sha256"])
        info = first_run.local_mother_info()
        self.assertIsNotNone(info)
        self.assertEqual(info["seed_sha256"], side["seed_sha256"])
        # Second call: no re-seed — byte-identical mother file.
        with open(seed_seal.MOTHER_FILE, "rb") as f:
            before = f.read()
        r2 = first_run.ensure_mother_seed()
        self.assertFalse(r2["created"])
        self.assertTrue(r2["exists"])
        self.assertTrue(r2["local_csprng"])
        with open(seed_seal.MOTHER_FILE, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_quantum_mother_is_left_untouched(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        seed_seal.write_sealed({
            "date": today, "seed_hex": bytes(range(64)).hex(),
            "source": "anu_qrng", "quantum": True,
            "fetched_at": "2026-10-21T00:00:00Z"})
        r = first_run.ensure_mother_seed()
        self.assertFalse(r["created"])
        # A quantum mother is NOT the local one — no relabel, no sidecar.
        self.assertIsNone(first_run.local_mother_info())
        self.assertFalse(os.path.exists(first_run.sidecar_path()))


class TestWombLocalCsprngProvenance(_FirstRunStateCase):

    def setUp(self):
        super().setUp()
        self._prev_data_dir = os.environ.get("GENESIS_DATA_DIR")
        os.environ["GENESIS_DATA_DIR"] = os.path.join(self._tmp, "data")
        womb._db = None
        _memory._db = None

    def tearDown(self):
        womb._db = None
        _memory._db = None
        if self._prev_data_dir is None:
            os.environ.pop("GENESIS_DATA_DIR", None)
        else:
            os.environ["GENESIS_DATA_DIR"] = self._prev_data_dir
        super().tearDown()

    def test_birth_records_local_csprng(self):
        first_run.ensure_mother_seed()
        a = womb.birth(seed="first-run local birth")
        self.assertEqual(a["seed_source"], "local-csprng")
        self.assertIn(a["trait"], womb._TRAITS)
        # The draw went through the hub under the true source label.
        draws = [r for r in audit.read_all()
                 if r.get("consumer_id") == womb._WOMB_LOCAL_CONSUMER]
        self.assertEqual(len(draws), 1)
        self.assertEqual(draws[0]["seed_source"], "local-csprng")
        self.assertIs(draws[0]["quantum"], False)
        # And the quantum tier refused first — the halt is on record.
        with open(seed_hub.HALTS_FILE, encoding="utf-8") as f:
            halts = [json.loads(l) for l in f if l.strip()]
        self.assertTrue(any(h["consumer_id"] == womb._WOMB_CONSUMER
                            for h in halts))
        # No draw was ever labelled quantum.
        self.assertFalse(any(r.get("quantum") for r in audit.read_all()))

    def test_birth_with_quantum_mother_stays_certified(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        seed_seal.write_sealed({
            "date": today, "seed_hex": bytes(range(64)).hex(),
            "source": "anu_qrng", "quantum": True,
            "fetched_at": "2026-10-21T00:00:00Z"})
        a = womb.birth(seed="quantum mother birth")
        self.assertEqual(a["seed_source"], "quantum-certified")


if __name__ == "__main__":
    unittest.main()
