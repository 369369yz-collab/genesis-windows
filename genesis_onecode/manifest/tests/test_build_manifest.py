"""test_build_manifest.py — unittest for manifest/build_manifest.py.

Covers: pins verification logic (MATCH / MISMATCH / absent file),
the T1-T13 + Birth Test gate table (all PENDING, window-only),
tree hashing determinism + exclusion rules, and an end-to-end generate()
with a small stand-in model file (the real 5GB GGUF is NOT hashed here).
Run: python3 -m unittest test_build_manifest -v
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

import build_manifest as bm


def _write(path, data: bytes):
    with open(path, "wb") as f:
        f.write(data)


class TestPinsVerification(unittest.TestCase):
    def _pins(self, d, content: bytes, size=None):
        h = hashlib.sha256(content).hexdigest()
        pins = {"local_llm": {"name": "Qwen3-8B-Q4_K_M.gguf",
                              "sha256": h,
                              "size_bytes": size if size is not None
                              else len(content)}}
        pp = os.path.join(d, "pins.json")
        with open(pp, "w") as f:
            json.dump(pins, f)
        return pp

    def test_match(self):
        d = tempfile.mkdtemp(prefix="pins-")
        content = b"fake-gguf-bytes-12345"
        gp = os.path.join(d, "model.gguf")
        _write(gp, content)
        res = bm.verify_pins(gp, self._pins(d, content))
        self.assertEqual(res["verdict"], "MATCH")
        self.assertTrue(res["size_match"])

    def test_mismatch_content(self):
        d = tempfile.mkdtemp(prefix="pins-")
        gp = os.path.join(d, "model.gguf")
        _write(gp, b"tampered-bytes")
        res = bm.verify_pins(gp, self._pins(d, b"original-bytes"))
        self.assertEqual(res["verdict"], "MISMATCH")
        self.assertNotEqual(res["actual_sha256"], res["expected_sha256"])

    def test_mismatch_size(self):
        d = tempfile.mkdtemp(prefix="pins-")
        content = b"abc"
        gp = os.path.join(d, "model.gguf")
        _write(gp, content)
        res = bm.verify_pins(gp, self._pins(d, content, size=999))
        self.assertEqual(res["verdict"], "MISMATCH")
        self.assertFalse(res["size_match"])

    def test_absent_model_file(self):
        d = tempfile.mkdtemp(prefix="pins-")
        res = bm.verify_pins(os.path.join(d, "nope.gguf"),
                             self._pins(d, b"x"))
        self.assertEqual(res["verdict"], "MISMATCH")
        self.assertIsNone(res["actual_sha256"])
        self.assertIn("absent", res["reason"])


class TestGateTable(unittest.TestCase):
    def test_all_gates_pending_window_only(self):
        gates = bm.gate_table()
        ids = [g["gate"] for g in gates]
        self.assertEqual(len(gates), 14)
        for i in range(1, 14):
            self.assertIn("T%d" % i, ids)
        self.assertIn("BIRTH", ids)
        for g in gates:
            self.assertEqual(g["status"], "PENDING")
            self.assertEqual(g["window"], "windows-latest")
        # spot-check grounded names (formula section 9)
        by_id = {g["gate"]: g["name"] for g in gates}
        self.assertIn("fresh install", by_id["T1"])
        self.assertIn("Birth Test", by_id["BIRTH"])


class TestHashTree(unittest.TestCase):
    def test_deterministic_and_excludes_manifest_outputs(self):
        d = tempfile.mkdtemp(prefix="tree-")
        _write(os.path.join(d, "a.txt"), b"hello")
        os.makedirs(os.path.join(d, "__pycache__"))
        _write(os.path.join(d, "__pycache__", "x.pyc"), b"junk")
        _write(os.path.join(d, "build_manifest.json"), b"old manifest")
        t1 = bm.hash_tree(d)
        t2 = bm.hash_tree(d)
        self.assertEqual(t1, t2)
        self.assertIn("a.txt", t1)
        self.assertNotIn("build_manifest.json", t1)
        self.assertFalse(any("__pycache__" in k for k in t1))
        self.assertEqual(t1["a.txt"], hashlib.sha256(b"hello").hexdigest())


class TestGenerateEndToEnd(unittest.TestCase):
    def test_generate_with_standin_model(self):
        d = tempfile.mkdtemp(prefix="manifest-")
        content = b"stand-in-model"
        gp = os.path.join(d, "model.gguf")
        _write(gp, content)
        pins = {"local_llm": {"name": "Qwen3-8B-Q4_K_M.gguf",
                              "sha256": hashlib.sha256(content).hexdigest(),
                              "size_bytes": len(content)}}
        pp = os.path.join(d, "pins.json")
        with open(pp, "w") as f:
            json.dump(pins, f)
        out = os.path.join(d, "build_manifest.json")
        m = bm.generate(agent="temp-onecode-body",
                        task="genesis-one-code-body",
                        gguf_path=gp, pins_path=pp, out_path=out)
        # timestamped 369-network connection proof embedded (absolute law)
        self.assertIn("connection_proof", m)
        self.assertEqual(m["connection_proof"]["network"], "369-quantum")
        self.assertEqual(m["connection_proof"]["agent"], "temp-onecode-body")
        self.assertTrue(m["tree_files"] > 0)
        self.assertIn("body/avatar2d/avatar2d.js", m["tree_sha256"])
        self.assertEqual(m["pins_verification"]["verdict"], "MATCH")
        self.assertEqual(len(m["gates"]), 14)
        self.assertTrue(os.path.isfile(out))
        with open(out) as f:
            disk = json.load(f)
        self.assertEqual(disk["pins_verification"]["verdict"], "MATCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
