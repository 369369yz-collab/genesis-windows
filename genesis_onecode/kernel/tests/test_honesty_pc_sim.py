"""kernel/tests/test_honesty_pc_sim.py — honesty.py on the user's PC.

Simulates a real install with NO 369 world tree:

  * the app tree (genesis_onecode/) is copied to a temp dir;
  * HOME points at an EMPTY temp dir, so every ~/workspace/... legacy
    path resolves to nothing;
  * no GENESIS_WORLD_ROOT / GENESIS_WORKSPACE / GENESIS_MODEL_PATH;
  * GENESIS_DATA_DIR is a fresh temp dir;
  * the app's own first boot is replayed faithfully — service.py's
    ensure_seed() creates the SQLite memory store, and the model file
    the launcher would have downloaded+assembled is present at
    <data>/models/<assembled_name> with the manifest's exact size
    (sparse stand-in: this test verifies PATH RESOLUTION and honest
    reporting, not the model bytes — the SHA-256 is brain.rs's W14
    job at load, and honesty.py's detail says so).

Expected truth in that world:

  * model_reachable PASSES from the app models dir;
  * memory_intact PASSES from the app memory store;
  * laws_loaded PASSES from embedded kernel/laws.json internal
    reconciliation (no live CODEX exists there);
  * voice_alive is SKIPPED (parked by YZ), as always;
  * knows_ignorance FAILS, "absent on this install" — and that is
    CORRECT, not a test bug: the anti-fabrication primitive
    (truth_layer) lives in the world tree genesis_final/brain and is
    deliberately not embedded in the app (kernel/claims_ledger.py is
    an adapter onto it, never a copy). A boot that cannot run its own
    ignorance probe must not claim it passed. This test pins that
    exception by name so it can never silently grow or shrink: if a
    future phase embeds truth_layer, this test must be updated to
    expect a full pass — deliberately, in the open.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.abspath(os.path.join(_HERE, "..", ".."))

_SIM_SCRIPT = r"""
import json
import os
import sys

APP = os.environ["SIM_APP_DIR"]
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "kernel"))

# 1) The app's own first boot: service.ensure_seed() creates the
#    living-memory store and seeds it (exactly what main() calls).
import service
service.ensure_seed()

# 2) The launcher's completed work: assembled model in place, exact
#    manifest size (sparse stand-in — bytes are brain.rs's W14 job).
with open(os.path.join(APP, "brain", "model_manifest.json"),
          encoding="utf-8") as f:
    man = json.load(f)
models_dir = os.path.join(os.environ["GENESIS_DATA_DIR"], "models")
os.makedirs(models_dir, exist_ok=True)
with open(os.path.join(models_dir, man["assembled_name"]), "wb") as f:
    f.truncate(man["assembled_size"])

# 3) The boot self-test, as the running service would report it.
import honesty
rep = honesty.boot_self_test()
print("BOOTREPORT=" + json.dumps(rep.to_dict()))
"""


class TestHonestyOnUserPC(unittest.TestCase):

    def test_boot_truth_without_the_world(self):
        tmp = tempfile.mkdtemp(prefix="honesty-pcsim-")
        app_copy = os.path.join(tmp, "app")
        shutil.copytree(
            _ONECODE, app_copy,
            ignore=shutil.ignore_patterns("__pycache__", "genesis_data",
                                          "*.db", "*.db-wal", "*.db-shm"))
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        data = os.path.join(tmp, "data")
        script = os.path.join(tmp, "sim.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(_SIM_SCRIPT)
        env = {k: v for k, v in os.environ.items()
               if k not in ("GENESIS_WORLD_ROOT", "GENESIS_WORKSPACE",
                            "GENESIS_MODEL_PATH", "GENESIS_LLAMA_URL",
                            "GENESIS_DATA_DIR")}
        env.update({
            "HOME": home,                      # no ~/workspace anywhere
            "GENESIS_DATA_DIR": data,          # fresh install data dir
            "SIM_APP_DIR": app_copy,
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        proc = subprocess.run(
            [sys.executable, script], cwd=app_copy, env=env,
            capture_output=True, text=True, timeout=300)
        line = next((ln for ln in proc.stdout.splitlines()
                     if ln.startswith("BOOTREPORT=")), None)
        self.assertIsNotNone(
            line, "sim produced no boot report:\n%s\n%s"
            % (proc.stdout, proc.stderr))
        rep = json.loads(line[len("BOOTREPORT="):])
        checks = {c["name"]: c for c in rep["checks"]}

        # The simulation really was world-less: nothing resolved home.
        self.assertFalse(os.path.exists(os.path.join(home, "workspace")))

        # Embedded resources carry the checks they name.
        model = checks["model_reachable"]
        self.assertTrue(model["passed"], model["detail"])
        self.assertTrue(model["evidence"]["path"].startswith(data),
                        model["evidence"])
        memory = checks["memory_intact"]
        self.assertTrue(memory["passed"], memory["detail"])
        self.assertEqual(memory["evidence"].get("basis"),
                         "app memory store (SQLite)")
        laws = checks["laws_loaded"]
        self.assertTrue(laws["passed"], laws["detail"])
        self.assertIn("internal reconciliation",
                      laws["evidence"].get("basis", ""))
        self.assertEqual(checks["voice_alive"]["status"], "skipped")

        # The single documented world-dependence, by name.
        ign = checks["knows_ignorance"]
        self.assertFalse(ign["passed"])
        self.assertIn("absent on this install", ign["detail"])
        self.assertIn("truth_layer", ign["detail"])
        failed = [c["name"] for c in rep["checks"]
                  if c["status"] == "failed"]
        self.assertEqual(failed, ["knows_ignorance"])
        self.assertFalse(rep["passed"])  # honest: she is not fully awake
        self.assertIn("knows_ignorance", rep["statement"])


if __name__ == "__main__":
    unittest.main()
