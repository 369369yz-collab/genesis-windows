"""test_bridge.py — unittest for bridge/server.py + brain/sync.py.

Spins up the real bridge on localhost with a test secret and drives the
full loop: heartbeat -> push -> pull, plus auth failures.
Run: python3 -m unittest test_bridge -v
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))                  # brain/ itself
sys.path.insert(0, os.path.join(_HERE, "..", ".."))            # genesis_onecode/ (from brain import ...)
sys.path.insert(0, os.path.join(_HERE, "..", "..", ".."))      # repo root (bridge/)

_TMP = tempfile.mkdtemp(prefix="bridgetest-")
os.environ["BRIDGE_DATA"] = os.path.join(_TMP, "data")
os.environ["BRIDGE_SECRET"] = "test-secret-123"

from http.server import ThreadingHTTPServer
from bridge import server as _srv


def _start():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _srv.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def _call(port, method, path, payload=None, secret="test-secret-123"):
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {secret}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}


class TestBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.port = _start()

    def test_health(self):
        st, body = _call(self.port, "GET", "/health", secret="wrong")
        self.assertEqual(st, 200)  # health is public
        self.assertTrue(body["ok"])

    def test_unauthorized(self):
        st, _ = _call(self.port, "POST", "/v1/heartbeat",
                      {"client_id": "x"}, secret="wrong")
        self.assertEqual(st, 401)

    def test_heartbeat_push_pull(self):
        st, hb = _call(self.port, "POST", "/v1/heartbeat",
                       {"client_id": "c1"})
        self.assertEqual(st, 200)
        self.assertTrue(hb["ok"])
        st, pu = _call(self.port, "POST", "/v1/push",
                       {"client_id": "c1", "kind": "memory",
                        "payload": {"facts": {"a": "b"}}})
        self.assertEqual(st, 200)
        st, pl = _call(self.port, "GET", "/v1/pull?client_id=c2&since=0")
        self.assertEqual(st, 200)
        self.assertEqual(len(pl["pushes"]), 1)
        self.assertEqual(pl["pushes"][0]["payload"]["facts"], {"a": "b"})
        peers = [p["client_id"] for p in pl["peers"]]
        self.assertIn("c1", peers)

    def test_push_bounded(self):
        for i in range(10):
            _call(self.port, "POST", "/v1/push",
                  {"client_id": "c1", "kind": "k", "payload": {"i": i}})
        st, pl = _call(self.port, "GET", "/v1/pull?client_id=c9&since=0")
        self.assertEqual(st, 200)
        self.assertLessEqual(len(pl["pushes"]), 200)


class TestSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.port = _start()

    def test_disabled_without_config(self):
        for k in ("BRIDGE_URL", "BRIDGE_SECRET"):
            os.environ.pop(k, None)
        tmp = tempfile.mkdtemp(prefix="synctest-")
        os.environ["GENESIS_DATA_DIR"] = tmp
        from brain import sync as _sync
        self.assertFalse(_sync.enabled())
        self.assertFalse(_sync.start())

    def test_enabled_flow(self):
        os.environ["BRIDGE_URL"] = f"http://127.0.0.1:{self.port}"
        os.environ["BRIDGE_SECRET"] = "test-secret-123"
        tmp = tempfile.mkdtemp(prefix="synctest-")
        os.environ["GENESIS_DATA_DIR"] = tmp
        from brain import sync as _sync
        import importlib
        importlib.reload(_sync)
        self.assertTrue(_sync.enabled())
        hb = _sync.heartbeat()
        self.assertTrue(hb["ok"])
        pu = _sync.push_memory()
        self.assertTrue(pu["ok"])
        pl = _sync.pull_updates(0)
        self.assertTrue(pl["ok"])
        for k in ("BRIDGE_URL", "BRIDGE_SECRET"):
            os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
