"""kernel/tests/test_honesty_resolution.py — honesty.py path resolution.

The boot self-test must tell the truth on the user's PC, not only on
the world VM. These tests pin the resolution semantics (2026-10-21):

  * env override (GENESIS_WORLD_ROOT / GENESIS_MODEL_PATH) wins;
  * the app-embedded equivalent is verified where one exists (SQLite
    memory store, assembled model named by brain/model_manifest.json,
    kernel/laws.json internal reconciliation without a live CODEX);
  * the legacy VM path is the last resort;
  * "absent on this install" and "present but broken" are both
    failures, with distinct detail text — never a fall-through pass.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_KERNEL = os.path.dirname(_HERE)
_ONECODE = os.path.dirname(_KERNEL)
if _KERNEL not in sys.path:
    sys.path.insert(0, _KERNEL)

import honesty  # noqa: E402

_WORLD_ENV = ("GENESIS_WORLD_ROOT", "GENESIS_WORKSPACE",
              "GENESIS_MODEL_PATH", "GENESIS_LLAMA_URL")


def _clean_env(**overrides):
    """An env dict with every world override removed, plus overrides."""
    env = {k: v for k, v in os.environ.items()
           if k not in _WORLD_ENV and k != "GENESIS_DATA_DIR"}
    env.update(overrides)
    return mock.patch.dict(os.environ, env, clear=True)


def _manifest():
    with open(os.path.join(_ONECODE, "brain", "model_manifest.json"),
              encoding="utf-8") as f:
        return json.load(f)


class TestMemoryResolution(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="honesty-mem-")

    def _make_store(self, data_dir, corrupt=False):
        mem_dir = os.path.join(data_dir, "memory")
        os.makedirs(mem_dir, exist_ok=True)
        db = os.path.join(mem_dir, "genesis.db")
        if corrupt:
            with open(db, "wb") as f:
                f.write(b"this is not a sqlite database at all")
            return db
        con = sqlite3.connect(db)
        con.executescript(
            "CREATE TABLE facts(key TEXT PRIMARY KEY, value TEXT NOT NULL,"
            " updated_at REAL NOT NULL);"
            "CREATE TABLE exchanges(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " role TEXT NOT NULL, content TEXT NOT NULL, ts REAL NOT NULL);")
        con.commit()
        con.close()
        return db

    def test_absent_store_and_no_substrates_is_absent_failure(self):
        with _clean_env(GENESIS_DATA_DIR=self.tmp), \
                mock.patch.object(honesty, "_MEM_FILES",
                                  [os.path.join(self.tmp, "nope.md")]):
            c = honesty._check_memory()
        self.assertFalse(c.passed)
        self.assertEqual(c.status, "failed")
        self.assertIn("absent on this install", c.detail)

    def test_corrupt_store_is_broken_not_absent(self):
        self._make_store(self.tmp, corrupt=True)
        with _clean_env(GENESIS_DATA_DIR=self.tmp):
            c = honesty._check_memory()
        self.assertFalse(c.passed)
        self.assertIn("present but broken", c.detail)

    def test_valid_store_passes_via_embedded_basis(self):
        self._make_store(self.tmp)
        with _clean_env(GENESIS_DATA_DIR=self.tmp):
            c = honesty._check_memory()
        self.assertTrue(c.passed, c.detail)
        self.assertEqual(c.evidence.get("basis"), "app memory store (SQLite)")

    def test_world_root_substrates_win_over_store(self):
        root = os.path.join(self.tmp, "workspace")
        os.makedirs(os.path.join(root, "content_team", "yz_agent"))
        for p in (os.path.join(self.tmp, "MEMORY.md"),
                  os.path.join(root, "content_team", "yz_agent",
                               "YZ_DIALOGUE.md"),
                  os.path.join(root, "mission_ledger.md")):
            with open(p, "w", encoding="utf-8") as f:
                f.write("x")
        with _clean_env(GENESIS_DATA_DIR=self.tmp,
                        GENESIS_WORLD_ROOT=root):
            c = honesty._check_memory()
        self.assertTrue(c.passed, c.detail)
        self.assertIn("GENESIS_WORLD_ROOT", c.evidence.get("basis", ""))

    def test_partial_world_substrates_are_broken_not_skipped(self):
        root = os.path.join(self.tmp, "workspace")
        os.makedirs(root)
        with open(os.path.join(root, "mission_ledger.md"), "w") as f:
            f.write("x")
        with _clean_env(GENESIS_DATA_DIR=self.tmp,
                        GENESIS_WORLD_ROOT=root):
            c = honesty._check_memory()
        self.assertFalse(c.passed)
        self.assertIn("present but broken", c.detail)


class TestModelResolution(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="honesty-model-")
        self.man = _manifest()

    def _candidate(self):
        return os.path.join(self.tmp, "models", self.man["assembled_name"])

    def test_absent_everywhere_is_absent_failure(self):
        with _clean_env(GENESIS_DATA_DIR=self.tmp), \
                mock.patch.object(honesty, "_MODEL_PATH",
                                  os.path.join(self.tmp, "nope.gguf")):
            c = honesty._check_model()
        self.assertFalse(c.passed)
        self.assertIn("absent on this install", c.detail)

    def test_manifest_sized_model_passes_via_app_models_dir(self):
        dest = self._candidate()
        os.makedirs(os.path.dirname(dest))
        with open(dest, "wb") as f:
            f.truncate(self.man["assembled_size"])  # sparse, exact size
        with _clean_env(GENESIS_DATA_DIR=self.tmp):
            c = honesty._check_model()
        self.assertTrue(c.passed, c.detail)
        self.assertEqual(c.evidence.get("path"), dest)

    def test_wrong_size_model_is_broken(self):
        dest = self._candidate()
        os.makedirs(os.path.dirname(dest))
        with open(dest, "wb") as f:
            f.write(b"tiny")
        with _clean_env(GENESIS_DATA_DIR=self.tmp):
            c = honesty._check_model()
        self.assertFalse(c.passed)
        self.assertIn("present but broken", c.detail)
        self.assertIn("size mismatch", c.detail)

    def test_env_override_wins(self):
        custom = os.path.join(self.tmp, "custom.gguf")
        with open(custom, "wb") as f:
            f.write(b"gguf-bytes")
        with _clean_env(GENESIS_DATA_DIR=self.tmp,
                        GENESIS_MODEL_PATH=custom):
            c = honesty._check_model()
        self.assertTrue(c.passed, c.detail)
        self.assertEqual(c.evidence.get("path"), custom)


class TestLawsResolution(unittest.TestCase):

    def test_internal_reconciliation_without_live_codex(self):
        with _clean_env(), \
                mock.patch.object(honesty, "_CODEX_PATH",
                                  "/nonexistent/CODEX.json"):
            c = honesty._check_laws()
        self.assertTrue(c.passed, c.detail)
        self.assertIn("internal reconciliation",
                      c.evidence.get("basis", ""))

    def test_live_codex_crosscheck_when_present(self):
        # On the world VM the real CODEX resolves and cross-checks.
        if not os.path.exists(honesty._CODEX_PATH):
            self.skipTest("live CODEX not present on this machine")
        with _clean_env():
            c = honesty._check_laws()
        self.assertTrue(c.passed, c.detail)
        self.assertEqual(c.evidence.get("basis"), "live CODEX cross-check")


if __name__ == "__main__":
    unittest.main()
