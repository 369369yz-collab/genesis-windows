"""test_world_data.py — embedded world data loaders + /world/state shape.

GENESIS embed step 7, Phase 2 (2026-10-21). The loaders must compute
counts from the real file structures; the expected values below were
verified against the source files at embed time (presence.json agents
dict = 788, NEXUS_LAWS.json laws list = 5 records under 5 top-level
keys, PLAYBOOKS.json entries = 228). The endpoint test proves the
/world/state response carries the seats block as a SNAPSHOT
(live: false — honesty law) and the nexus block.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.abspath(os.path.join(_HERE, "..", ".."))
_BRAIN = os.path.abspath(os.path.join(_HERE, ".."))
for _p in (_ONECODE, _BRAIN):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import world_data


def _raw(name):
    with open(os.path.join(_BRAIN, "world_data", name),
              encoding="utf-8") as f:
        return json.load(f)


class TestWorldDataLoaders(unittest.TestCase):

    def test_seat_count_matches_snapshot_structure(self):
        raw = _raw("presence_snapshot.json")
        self.assertEqual(world_data.seat_count(), len(raw["agents"]))
        self.assertEqual(world_data.seat_count(), 788)

    def test_seats_block_is_honest_snapshot(self):
        blk = world_data.seats_block()
        self.assertEqual(blk["count"], 788)
        self.assertIs(blk["live"], False)  # a snapshot, NEVER labelled live
        self.assertEqual(blk["snapshot_at"], "2026-10-21T00:13:41Z")
        age = world_data.snapshot_age_seconds()
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 0)

    def test_nexus_counts(self):
        raw = _raw("nexus_laws.json")
        # law records in the "laws" list vs keys of the container dict:
        # different numbers, both honestly reported.
        self.assertEqual(world_data.nexus_law_count(), len(raw["laws"]))
        self.assertEqual(world_data.nexus_top_level_keys(), len(raw))
        self.assertEqual(world_data.nexus_block(),
                         {"laws_present": True, "top_level_keys": 5,
                          "law_count": 5})

    def test_playbook_count_matches_entries(self):
        raw = _raw("playbooks.json")
        self.assertEqual(world_data.playbook_count(), len(raw["entries"]))
        self.assertEqual(world_data.playbook_count(), 228)


class TestWorldStateEndpoint(unittest.TestCase):

    def setUp(self):
        self._prev_data_dir = os.environ.get("GENESIS_DATA_DIR")
        self._tmp = tempfile.mkdtemp(prefix="worldstate-")
        os.environ["GENESIS_DATA_DIR"] = self._tmp
        from brain import memory as _memory
        _memory._db = None
        import service
        self._service = service
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        self._port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True)
        self._thread.start()

    def tearDown(self):
        self._srv.shutdown()
        self._srv.server_close()
        from brain import memory as _memory
        _memory._db = None
        if self._prev_data_dir is None:
            os.environ.pop("GENESIS_DATA_DIR", None)
        else:
            os.environ["GENESIS_DATA_DIR"] = self._prev_data_dir

    def test_world_state_shape(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self._port}/world/state",
                timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["seats"]["count"], 788)
        self.assertIs(data["seats"]["live"], False)
        self.assertIn("snapshot_at", data["seats"])
        self.assertIs(data["nexus"]["laws_present"], True)
        self.assertEqual(data["nexus"]["top_level_keys"], 5)
        self.assertEqual(data["nexus"]["law_count"], 5)
        # pre-existing blocks are untouched
        self.assertIn("worlds", data)
        self.assertIn("gates", data)
        self.assertIn("live", data)


if __name__ == "__main__":
    unittest.main()
