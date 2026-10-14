"""test_extended_mind.py — unittest for brain/extended_mind.py.

Covers: guarded import with missing world code (never raises), unknown
module names, local-fallback degraded flag when veins is absent, and the
3s guarded-call timeout via a fake slow module.
Run: python3 -m unittest test_extended_mind -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

import extended_mind as extmod


class TestGuardedImport(unittest.TestCase):
    def test_missing_modules_dir_never_raises(self):
        em = extmod.ExtendedMind(modules_dir="/tmp/definitely-not-here-xyz-123")
        mods = em.list_modules()
        self.assertEqual(len(mods), 14)
        for m in mods:
            self.assertFalse(m["loaded"])
            self.assertTrue(m["degraded"])
        res = em.call_module("genesis-memory", {"q": "test"})
        self.assertFalse(res["ok"])
        self.assertTrue(res["degraded"])
        self.assertEqual(res["reason"], "module-unavailable")
        self.assertIn("route", res)

    def test_unknown_module_name(self):
        em = extmod.ExtendedMind(modules_dir="/tmp/definitely-not-here-xyz-123")
        res = em.call_module("not-a-real-module", {})
        self.assertFalse(res["ok"])
        self.assertTrue(res["degraded"])
        self.assertEqual(res["reason"], "unknown-module")

    def test_veins_present_routes_guarded(self):
        # veins/guarded_call.py landed mid-mission (veins specialist).
        em = extmod.ExtendedMind()
        self.assertEqual(em.route, "veins-guarded")
        self.assertTrue(em.status()["veins_guarded_call_available"])

    def test_veins_absent_falls_back_to_local(self):
        import unittest.mock as mock
        with mock.patch.object(extmod, "_try_veins_guarded_call",
                               return_value=None):
            em = extmod.ExtendedMind()
        self.assertEqual(em.route, "local-fallback")
        self.assertFalse(em.status()["veins_guarded_call_available"])
        res = em.call_module("genesis-memory", {"q": "x"})
        # modules dir itself is also missing here -> unavailable, still dict
        self.assertIsInstance(res, dict)
        self.assertIn("route", res)


class TestRealModulesDir(unittest.TestCase):
    def test_call_never_raises_regardless_of_load(self):
        em = extmod.ExtendedMind()  # real modules dir
        for m in em.list_modules():
            self.assertIn("loaded", m)
            self.assertIn("degraded", m)
        # call one module; whatever happens, we get a dict, never an exception
        res = em.call_module("genesis-memory", {"op": "ping"})
        self.assertIsInstance(res, dict)
        self.assertIn("ok", res)
        self.assertIn("degraded", res)
        self.assertIn("route", res)
        self.assertIn(res["route"], ("veins-guarded", "local-fallback"))

    def test_local_fallback_route_still_marks_degraded(self):
        import unittest.mock as mock
        with mock.patch.object(extmod, "_try_veins_guarded_call",
                               return_value=None):
            em = extmod.ExtendedMind()
        res = em.call_module("genesis-memory", {"op": "ping"})
        self.assertEqual(res["route"], "local-fallback")
        if res["ok"]:
            # without veins, any successful local call is explicitly degraded
            self.assertTrue(res["degraded"])


class TestTimeout(unittest.TestCase):
    def _slow_module_dir(self):
        d = tempfile.mkdtemp(prefix="extmind-")
        moddir = os.path.join(d, "fake-slow")
        os.makedirs(moddir)
        with open(os.path.join(moddir, "manifest.json"), "w") as f:
            json.dump({"name": "fake-slow", "version": "0.0.1",
                       "entry": "facade.py", "factory": "SlowModule"}, f)
        with open(os.path.join(moddir, "facade.py"), "w") as f:
            f.write("import time\n"
                    "class SlowModule:\n"
                    "    def handle(self, payload):\n"
                    "        time.sleep(30)\n"
                    "        return {'never': True}\n")
        return d

    def test_slow_module_hits_3s_timeout_via_veins(self):
        d = self._slow_module_dir()
        old = extmod.MODULE_NAMES
        extmod.MODULE_NAMES = ("fake-slow",)
        try:
            em = extmod.ExtendedMind(modules_dir=d)
            self.assertEqual(em.route, "veins-guarded")
            t0 = time.monotonic()
            res = em.call_module("fake-slow", {})
            dt = time.monotonic() - t0
        finally:
            extmod.MODULE_NAMES = old
        # veins contract shape: never invented data, honest degraded result
        self.assertFalse(res["ok"])
        self.assertTrue(res["degraded"])
        self.assertEqual(res["route"], "veins-guarded")
        self.assertIn(res.get("state"), ("ONLINE", "DEGRADED", "OFFLINE"))
        self.assertLess(dt, 15)  # 3s contract honored (generous VM bound)

    def test_slow_module_hits_3s_timeout_local_fallback(self):
        import unittest.mock as mock
        d = self._slow_module_dir()
        old = extmod.MODULE_NAMES
        extmod.MODULE_NAMES = ("fake-slow",)
        try:
            with mock.patch.object(extmod, "_try_veins_guarded_call",
                                   return_value=None):
                em = extmod.ExtendedMind(modules_dir=d)
            t0 = time.monotonic()
            res = em.call_module("fake-slow", {})
            dt = time.monotonic() - t0
        finally:
            extmod.MODULE_NAMES = old
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "timeout")
        self.assertTrue(res["degraded"])
        self.assertEqual(res["route"], "local-fallback")
        self.assertLess(dt, 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
