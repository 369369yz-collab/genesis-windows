"""build_manifest.py — ONE-CODE build manifest generator.

Generates ~/workspace/genesis_onecode/manifest/build_manifest.json with:
  1. Timestamped 369-network connection proof (NETWORK-CONNECTION ABSOLUTE
     LAW: network_precondition() is the FIRST call of every entry point;
     offline -> the generator STOPS, never writes a manifest).
  2. SHA-256 of every file in the one-code tree (chunked reads).
  3. Pins verification: SHA-256 (+ size) of
     genesis_final/brain/models/Qwen3-8B-Q4_K_M.gguf against
     genesis_final/brain/pins.json — reported as MATCH or MISMATCH, honestly.
  4. Gate table: T1-T13 + Birth Test, each PENDING / window-only
     (they require windows-latest; they are GATED, not skipped, never faked).

Exclusions from the tree hash (documented, stable): the manifest output
files themselves (build_manifest.json), *.lock sidecars, *.tmp files,
__pycache__/ and .pytest_cache/ (generated artifacts).

Technical English. Zero spend. Part of the GENESIS ONE-CODE tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ONECODE_ROOT = os.path.dirname(_HERE)
HOME = os.path.expanduser("~")
QUANTUM_DIR = os.path.join(HOME, "workspace", "content_team", "quantum")
GENESIS_FINAL = os.path.join(HOME, "workspace", "genesis_final")

MANIFEST_OUT = os.path.join(_HERE, "build_manifest.json")
EXCLUDED_NAMES = {"build_manifest.json"}
EXCLUDED_SUFFIXES = (".lock", ".tmp")
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache"}

CHUNK = 1024 * 1024

# Formula section 9: self-test gates (enumeration proposed by Track 4).
GATES = [
    ("T1", "fresh install"),
    ("T2", "reinstall/upgrade"),
    ("T3", "first-boot cold start"),
    ("T4", "voice loop (Persian digits/mixed script)"),
    ("T5", "memory persistence (kill -9 + corruption)"),
    ("T6", "network drop (degraded mode, no invented results)"),
    ("T7", "update + rollback (+ tampered pkg)"),
    ("T8", "resource exhaustion (8 GB VM + game load, no OOM kill)"),
    ("T9", "anti-fabrication battery (50 traps, zero uncited numbers)"),
    ("T10", "wakeword (true/false rates, TV noise)"),
    ("T11", "sleep/hibernate resume"),
    ("T12", "non-ASCII path (C:\\Users\\... )"),
    ("T13", "uninstall-clean (no orphans, data export offered)"),
    ("BIRTH", "Birth Test: GENESIS herself, 30-60 min on virtual Windows"),
]


def network_proof(agent: str, task: str) -> dict:
    """FIRST call of this entry point. Raises -> caller stops, no manifest."""
    sys.path.insert(0, QUANTUM_DIR)
    from quantum_gates import network_precondition
    return network_precondition(agent=agent, task=task,
                                purpose="one-code build manifest")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def hash_tree(root: str) -> dict:
    """SHA-256 of every file under root. Returns {relpath: sha256}."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fn in sorted(filenames):
            if fn in EXCLUDED_NAMES or fn.endswith(EXCLUDED_SUFFIXES):
                continue
            full = os.path.join(dirpath, fn)
            if not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root)
            out[rel] = sha256_file(full)
    return out


def verify_pins(gguf_path: str | None = None,
                pins_path: str | None = None) -> dict:
    """Verify the vendored brain model against genesis_final/brain/pins.json.

    Returns a dict with verdict MATCH or MISMATCH (or ERROR with a reason).
    Never fakes: a missing file or hash divergence is reported as-is.
    """
    gguf_path = gguf_path or os.path.join(
        GENESIS_FINAL, "brain", "models", "Qwen3-8B-Q4_K_M.gguf")
    pins_path = pins_path or os.path.join(GENESIS_FINAL, "brain", "pins.json")
    try:
        with open(pins_path, "r", encoding="utf-8") as f:
            pins = json.load(f)
    except Exception as e:
        return {"verdict": "ERROR", "reason": "pins.json unreadable: %s" % e}
    want = ((pins.get("local_llm") or {}).get("sha256") or "").strip().lower()
    want_size = (pins.get("local_llm") or {}).get("size_bytes")
    if not want:
        return {"verdict": "ERROR", "reason": "pins.json has no local_llm.sha256"}
    if not os.path.isfile(gguf_path):
        return {"verdict": "MISMATCH",
                "reason": "model file absent: %s" % gguf_path,
                "expected_sha256": want, "expected_size_bytes": want_size,
                "actual_sha256": None, "actual_size_bytes": None}
    actual_size = os.path.getsize(gguf_path)
    actual = sha256_file(gguf_path)
    size_ok = (want_size is None) or (actual_size == want_size)
    match = (actual.lower() == want) and size_ok
    return {
        "verdict": "MATCH" if match else "MISMATCH",
        "expected_sha256": want,
        "actual_sha256": actual,
        "expected_size_bytes": want_size,
        "actual_size_bytes": actual_size,
        "size_match": size_ok,
        "model": os.path.basename(gguf_path),
        "pins_source": pins_path,
    }


def gate_table() -> list[dict]:
    """T1-T13 + Birth Test: PENDING, windows-latest only. Marked, not faked."""
    return [{"gate": g, "name": n, "status": "PENDING",
             "window": "windows-latest",
             "note": "cannot run on Linux; gated, not skipped"}
            for g, n in GATES]


def generate(agent: str = "temp-onecode-body",
             task: str = "genesis-one-code-body",
             gguf_path: str | None = None,
             pins_path: str | None = None,
             out_path: str | None = None) -> dict:
    """Build the manifest. network_precondition FIRST; offline -> raises."""
    proof = network_proof(agent, task)  # raises NetworkOfflineError if offline
    tree = hash_tree(ONECODE_ROOT)
    pins = verify_pins(gguf_path, pins_path)
    manifest = {
        "generator": "genesis_onecode/manifest/build_manifest.py",
        "generated_at_utc": proof.get("checkin_utc"),
        "connection_proof": proof,   # timestamped 369-network proof (law)
        "tree_root": ONECODE_ROOT,
        "tree_files": len(tree),
        "tree_sha256": tree,
        "pins_verification": pins,
        "gates": gate_table(),
        "notes": [
            "T1-T13 + Birth Test require windows-latest; marked PENDING, never faked.",
            "cargo check (Linux target) is reported separately; the Windows binary cannot build on this VM.",
        ],
    }
    out_path = out_path or MANIFEST_OUT
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return manifest


def main() -> int:
    try:
        m = generate()
    except Exception as e:
        print("MANIFEST ABORTED: %s: %s" % (type(e).__name__, e))
        return 1
    pv = m["pins_verification"]
    print("manifest written: %s" % MANIFEST_OUT)
    print("connection proof: %s @ %s" % (
        m["connection_proof"].get("network"), m["generated_at_utc"]))
    print("tree files hashed: %d" % m["tree_files"])
    print("pins verification: %s (model %s)" % (
        pv.get("verdict"), pv.get("model")))
    print("gates: %d marked PENDING (windows-latest only)" % len(m["gates"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
