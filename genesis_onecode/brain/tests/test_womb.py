"""test_womb.py — unittest for brain/womb.py.

Proves the evolution cycle: birth -> mission -> learn -> selection.
Run: python3 -m unittest test_womb -v
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

import womb


class TestWomb(unittest.TestCase):
    def setUp(self):
        # fresh womb per test — evolution runs in isolation
        tmp = tempfile.mkdtemp(prefix="wombtest-")
        os.environ["GENESIS_DATA_DIR"] = tmp
        womb._db = None

    def test_birth(self):
        a = womb.birth(seed="test seed")
        self.assertTrue(a["id"].startswith("genius-"))
        self.assertEqual(a["status"], "alive")
        self.assertEqual(a["generation"], 1)
        self.assertIn(a["trait"], womb._TRAITS)

    def test_mission_lifecycle(self):
        a = womb.birth(seed="worker")
        m = womb.add_mission("test mission", "do the thing")
        self.assertEqual(m["status"], "pending")
        taken = womb.take_mission(a["id"])
        self.assertEqual(taken["id"], m["id"])
        self.assertEqual(taken["agent_id"], a["id"])
        done = womb.complete_mission(a["id"], m["id"], True, "did it", 0.0)
        self.assertEqual(done["missions_done"], 1)
        self.assertEqual(done["missions_ok"], 1)
        self.assertGreater(done["fitness"], 0.5)

    def test_failure_lowers_fitness(self):
        a = womb.birth(seed="failer")
        m = womb.add_mission("doomed mission")
        womb.take_mission(a["id"])
        done = womb.complete_mission(a["id"], m["id"], False, "failed")
        self.assertLess(done["fitness"], 0.5)

    def test_selection_replicates_winner(self):
        a = womb.birth(seed="winner")
        for i in range(3):
            m = womb.add_mission(f"win {i}")
            womb.take_mission(a["id"])
            womb.complete_mission(a["id"], m["id"], True, "ok")
        before = {x["id"] for x in womb.living_agents()}
        res = womb.selection()
        self.assertEqual(len(res["replicated"]), 1)
        child = womb.get_agent(res["replicated"][0])
        self.assertEqual(child["parent_id"], a["id"])
        self.assertEqual(child["generation"], 2)
        self.assertNotIn(child["id"], before)

    def test_selection_kills_loser(self):
        a = womb.birth(seed="loser")
        for i in range(3):
            m = womb.add_mission(f"loss {i}")
            womb.take_mission(a["id"])
            womb.complete_mission(a["id"], m["id"], False, "bad")
        res = womb.selection()
        self.assertEqual(len(res["died"]), 1)
        self.assertEqual(womb.get_agent(a["id"])["status"], "dead")
        # the dead are remembered, not erased
        self.assertIsNotNone(womb.get_agent(a["id"]))

    def test_young_agents_spared(self):
        a = womb.birth(seed="young")
        res = womb.selection()
        self.assertEqual(res["replicated"], [])
        self.assertEqual(res["died"], [])
        self.assertEqual(womb.get_agent(a["id"])["status"], "alive")


if __name__ == "__main__":
    unittest.main()


def _fake_llama_ok(messages):
    return "Did the research. RESULT: SUCCESS"


def _fake_llama_fail(messages):
    return "Missing access. RESULT: FAILED"


def _fake_codex_allow(action):
    return {"allowed": True, "reason": "test"}


def _fake_codex_deny(action):
    return {"allowed": False, "reason": "test denial"}


class TestWombExecution(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="wombtest-")
        os.environ["GENESIS_DATA_DIR"] = tmp
        womb._db = None
        womb._tick_count = 0

    def test_execute_success(self):
        a = womb.birth(seed="x")
        womb.add_mission("research topic")
        rec = womb.tick(llama_fn=_fake_llama_ok, codex_fn=_fake_codex_allow)
        self.assertEqual(len(rec["executed"]), 1)
        self.assertEqual(rec["executed"][0]["agent"], a["id"])
        ag = womb.get_agent(a["id"])
        self.assertEqual(ag["missions_done"], 1)
        self.assertEqual(ag["missions_ok"], 1)

    def test_execute_failure_recorded(self):
        a = womb.birth(seed="x")
        womb.add_mission("impossible mission")
        womb.tick(llama_fn=_fake_llama_fail, codex_fn=_fake_codex_allow)
        ag = womb.get_agent(a["id"])
        self.assertEqual(ag["missions_ok"], 0)
        self.assertLess(ag["fitness"], 0.5)

    def test_codex_denial_stops_execution(self):
        a = womb.birth(seed="x")
        womb.add_mission("risky mission")
        womb.tick(llama_fn=_fake_llama_ok, codex_fn=_fake_codex_deny)
        ag = womb.get_agent(a["id"])
        self.assertEqual(ag["missions_done"], 1)
        self.assertEqual(ag["missions_ok"], 0)

    def test_firstborn_on_pending_mission(self):
        self.assertEqual(womb.living_agents(), [])
        womb.add_mission("someone must do this")
        rec = womb.tick()
        self.assertEqual(len(rec["born"]), 1)
        self.assertEqual(len(womb.living_agents()), 1)

    def test_tick_without_llama_assigns_only(self):
        womb.add_mission("waiting mission")
        rec = womb.tick()
        self.assertEqual(len(rec["born"]), 1)
        self.assertEqual(rec["executed"], [])
