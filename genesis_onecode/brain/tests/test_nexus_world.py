"""test_nexus_world.py — NEXUS world code embed: presence, honestly.

GENESIS embed step 7, Phase 3 (2026-10-21) + pre-push fix pass.
The NEXUS package is vendored verbatim into genesis_onecode/nexus_world/
— all 9 files of the source package's code+data (7 modules, the package
__init__.py, and the NEXUS_LAWS.json registry) — for presence +
importability (three-worlds sequencing: NEXUS stays design/spec until
369 completes — nothing is wired live).

Import reality, re-measured 2026-10-21 after __init__.py was vendored
and recorded in nexus_world/README.md: loaded under its true package
name `nexus` (importlib spec with submodule_search_locations pointing
at the vendored dir — the package-layout fact the modules were written
against), **4 of 7 modules import**: nexus_laws, gates,
connection_graph, ledger. The other three (reflection, threshold,
womb) import the WORLD's `quantum` package at top level
(`from quantum.quantum_gates import network_precondition`) — that
package (content_team/quantum) is not the app's brain.quantum and is
deliberately not vendored or faked, so those three stay documented
skips with the exact error. The four importable modules still carry
LAZY quantum imports inside functions (the network precondition),
which would fail at call time; nothing calls them.
"""

import hashlib
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.abspath(os.path.join(_HERE, "..", ".."))
_NEXUS_WORLD = os.path.join(_ONECODE, "nexus_world")
_SOURCE = os.path.expanduser("~/workspace/content_team/nexus")

MODULES = ("nexus_laws", "gates", "connection_graph", "reflection",
           "threshold", "womb", "ledger")
VENDORED_FILES = tuple(n + ".py" for n in MODULES) + (
    "__init__.py", "NEXUS_LAWS.json")

# Modules that import cleanly under the package name (measured).
EXPECTED_OK = ("nexus_laws", "gates", "connection_graph", "ledger")

# The exact standalone-import failure per still-blocked module.
DOCUMENTED_FAILURES = {
    "reflection": "No module named 'quantum'",
    "threshold": "No module named 'quantum'",
    "womb": "No module named 'quantum'",
}

_PROBE = r"""
import importlib
import importlib.util
import os
import sys

root, name = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location(
    "nexus", os.path.join(root, "__init__.py"),
    submodule_search_locations=[root])
pkg = importlib.util.module_from_spec(spec)
sys.modules["nexus"] = pkg
spec.loader.exec_module(pkg)
if name == "__package__":
    print("PACKAGE OK seat=%s" % pkg.AGENT_SEAT)
else:
    importlib.import_module("nexus." + name)
    print("IMPORT OK " + name)
"""


def _probe(name):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-c", _PROBE, _NEXUS_WORLD, name],
        capture_output=True, text=True, timeout=60, env=env)


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class TestNexusWorldPresence(unittest.TestCase):

    def test_all_seven_modules_vendored(self):
        for name in MODULES:
            p = os.path.join(_NEXUS_WORLD, name + ".py")
            self.assertTrue(os.path.isfile(p), p)
            self.assertGreater(os.path.getsize(p), 0)

    def test_package_init_and_registry_vendored(self):
        for fname in ("__init__.py", "NEXUS_LAWS.json"):
            p = os.path.join(_NEXUS_WORLD, fname)
            self.assertTrue(os.path.isfile(p), p)
            self.assertGreater(os.path.getsize(p), 0)

    def test_provenance_and_readme_present(self):
        for doc in ("PROVENANCE.md", "README.md"):
            p = os.path.join(_NEXUS_WORLD, doc)
            self.assertTrue(os.path.isfile(p), p)
        with open(os.path.join(_NEXUS_WORLD, "PROVENANCE.md"),
                  encoding="utf-8") as f:
            prov = f.read()
        for fname in VENDORED_FILES:
            self.assertIn(fname, prov)

    @unittest.skipUnless(os.path.isdir(_SOURCE),
                         "world source tree not present on this machine")
    def test_copies_are_verbatim(self):
        for fname in VENDORED_FILES:
            self.assertEqual(
                _md5(os.path.join(_NEXUS_WORLD, fname)),
                _md5(os.path.join(_SOURCE, fname)),
                f"{fname} differs from source")


class TestNexusWorldImports(unittest.TestCase):

    def test_package_init_imports(self):
        proc = _probe("__package__")
        out = (proc.stdout + proc.stderr).strip()
        self.assertIn("PACKAGE OK", out, out)

    def test_module_imports(self):
        for name in MODULES:
            with self.subTest(module=name):
                proc = _probe(name)
                out = (proc.stdout + proc.stderr).strip()
                if "IMPORT OK" in out:
                    self.assertIn(
                        name, EXPECTED_OK,
                        f"{name} now imports but is not in EXPECTED_OK "
                        f"— update the test and nexus_world/README.md")
                    continue
                if name in EXPECTED_OK:
                    self.fail(f"{name} REGRESSED — expected importable, "
                              f"got:\n{out}")
                expected = DOCUMENTED_FAILURES[name]
                if expected in out:
                    self.skipTest(
                        f"{name}: documented import failure ({expected}) "
                        f"— the world's quantum package is not vendored; "
                        f"see nexus_world/README.md")
                self.fail(f"{name}: UNEXPECTED import failure:\n{out}")


if __name__ == "__main__":
    unittest.main()
