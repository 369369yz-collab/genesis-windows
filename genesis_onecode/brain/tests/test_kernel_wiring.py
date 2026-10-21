"""test_kernel_wiring.py — the kernel is REAL runtime code (Phase 3).

GENESIS embed step 7, Phase 3 (2026-10-21). Before this phase,
kernel/honesty.py, kernel/arbitration.py and kernel/claims_ledger.py
had ZERO consumers in service.py — test-only code. These tests drive
the actual HTTP service layer (a real ThreadingHTTPServer running
service.Handler) and prove each module is reached through it:

  * honesty      — GET /status carries the kernel block whose boot
                   self-test matches a direct honesty.boot_self_test()
                   call (same checks, same statement).
  * arbitration  — a lived memory fact that contradicts a seed fact is
                   resolved through kernel/arbitration.py on the /chat
                   context path: the decision-queue record lands in the
                   DATA DIR, and /status reports the yz_direct winner.
  * claims       — POST /agents/birth and a mission completion through
                   /agents/tick write claims + evidence into the kernel
                   claims ledger in the data dir; /status stats agree.
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.abspath(os.path.join(_HERE, "..", ".."))
_BRAIN = os.path.abspath(os.path.join(_HERE, ".."))
_KERNEL = os.path.join(_ONECODE, "kernel")
for _p in (_ONECODE, _BRAIN, _KERNEL):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import service
from brain import memory as _memory
from brain import womb as _womb


class _ServiceCase(unittest.TestCase):
    """Boot the real service Handler on an ephemeral port, temp data dir."""

    def setUp(self):
        self._prev_data_dir = os.environ.get("GENESIS_DATA_DIR")
        self._tmp = tempfile.mkdtemp(prefix="kernelwiring-")
        os.environ["GENESIS_DATA_DIR"] = self._tmp
        _memory._db = None
        _womb._db = None
        service._KERNEL_BOOT = None
        service._last_arbitration = {"conflicts_resolved": 0, "last": None}
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        self._port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True)
        self._thread.start()

    def tearDown(self):
        self._srv.shutdown()
        self._srv.server_close()
        _memory._db = None
        _womb._db = None
        if self._prev_data_dir is None:
            os.environ.pop("GENESIS_DATA_DIR", None)
        else:
            os.environ["GENESIS_DATA_DIR"] = self._prev_data_dir

    # -- tiny HTTP client -------------------------------------------------
    def _get(self, path):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self._port}{path}", timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path, obj):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}{path}",
            data=json.dumps(obj).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class TestHonestyThroughService(_ServiceCase):

    def test_status_kernel_boot_matches_direct_kernel_call(self):
        data = self._get("/status")
        self.assertTrue(data["ok"])
        boot = data["kernel"]["boot"]
        # Same code path as a direct kernel call: same checks, same verdict.
        import honesty as _honesty
        direct = _honesty.boot_self_test().to_dict()
        self.assertEqual([c["name"] for c in boot["checks"]],
                         [c["name"] for c in direct["checks"]])
        self.assertEqual(boot["statement"], direct["statement"])
        self.assertIs(boot["passed"], direct["passed"])
        for chk in boot["checks"]:
            self.assertIn(chk["status"], ("passed", "failed", "skipped"))
            self.assertIsInstance(chk["passed"], bool)
        by_name = {c["name"]: c for c in boot["checks"]}
        # The parked voice is reported as skipped — never hidden, never green.
        self.assertEqual(by_name["voice_alive"]["status"], "skipped")


class TestArbitrationThroughService(_ServiceCase):

    def test_conflict_resolved_on_chat_context_path(self):
        # A seed fact exists for yz_call in brain/seed_facts.json; YZ's
        # lived memory now contradicts it.
        seed = service._seed_fact_items()
        self.assertIn("yz_call", seed)
        override = "TEST OVERRIDE: call him Captain for this test"
        code, _ = self._post("/memory/remember",
                             {"key": "yz_call", "value": override})
        self.assertEqual(code, 200)
        # Drive the real /chat path: context assembly (and therefore
        # arbitration) runs before the model call. The model is not
        # required for this proof — 200 or 502 both pass through it.
        code, _ = self._post("/chat", {"message": "سلام"})
        self.assertIn(code, (200, 502))
        # The conflict was logged to the DATA DIR decision queue (never
        # to the VM world path) with the yz_direct winner.
        qpath = os.path.join(self._tmp, "kernel", "decision_queue.jsonl")
        with open(qpath, encoding="utf-8") as f:
            records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["kind"], "law_conflict_flag")
        self.assertEqual(rec["detail"]["topic"], "yz_call")
        self.assertEqual(rec["detail"]["winner"]["source"], "yz_direct")
        self.assertEqual(rec["detail"]["auto_rejected"][0]["source"],
                         "local_law")
        # /status reports the same arbitration outcome.
        data = self._get("/status")
        arb = data["kernel"]["arbitration"]
        self.assertGreaterEqual(arb["conflicts_resolved"], 1)
        self.assertEqual(arb["last"]["winner"]["source"], "yz_direct")
        self.assertEqual(arb["last"]["winner"]["topic"], "yz_call")
        # And the winning value is what the context assembly now serves.
        self.assertEqual(service.arbitrated_facts()["yz_call"], override)


class TestClaimsThroughService(_ServiceCase):

    def _claims_rows(self):
        db = os.path.join(self._tmp, "kernel", "claims_ledger.db")
        con = sqlite3.connect(db)
        try:
            return con.execute(
                "SELECT claim, evidence_hash, verdict FROM claims_ledger"
                " ORDER BY id").fetchall()
        finally:
            con.close()

    def test_birth_and_mission_completion_are_ledgered(self):
        code, body = self._post("/agents/birth", {})
        self.assertEqual(code, 200)
        agent = body["agent"]
        self.assertIn(agent["seed_source"],
                      ("quantum-certified", "local-csprng",
                       "degraded-stdlib", "legacy-unknown"))
        code, body = self._post("/missions",
                                {"title": "claims wiring probe"})
        self.assertEqual(code, 200)
        mission_id = body["mission"]["id"]
        # Execute through the real tick path (model unreachable here, so
        # the mission completes as a failure — a completion either way,
        # and completions are what the ledger records).
        code, body = self._post("/agents/tick", {"execute": True})
        self.assertEqual(code, 200)
        self.assertTrue(body["events"]["executed"])
        rows = self._claims_rows()
        # The mission claim also names the agent, so births are matched
        # on the birth wording, missions on the mission id.
        birth_rows = [r for r in rows
                      if agent["id"] in r[0] and " born " in r[0]]
        mission_rows = [r for r in rows if mission_id in r[0]]
        self.assertEqual(len(birth_rows), 1)
        self.assertEqual(len(mission_rows), 1)
        for claim, ev_hash, verdict in birth_rows + mission_rows:
            self.assertEqual(verdict, "completion_accepted")
            # Evidence was really supplied: a 64-char hash, never "none"
            # (evidence-less completions are refused by the kernel).
            self.assertEqual(len(ev_hash), 64)
            self.assertNotEqual(ev_hash, "none")
        # /status stats agree with the ledger the womb wrote to.
        data = self._get("/status")
        stats = data["kernel"]["claims"]
        self.assertTrue(stats["available"])
        self.assertEqual(stats["total"], len(rows))
        self.assertEqual(stats["accepted"], len(rows))
        self.assertEqual(stats["blocked"], 0)


if __name__ == "__main__":
    unittest.main()
