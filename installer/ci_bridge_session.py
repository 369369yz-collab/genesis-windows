"""CI connected-operation proof for GENESIS COMPLETE 1.0.0.

Guardian evidence (d): GENESIS operates ONLINE-FIRST via the 369 bridge.
This script produces that evidence with the PRODUCTION code on both sides:

  1. Starts the repo's real bridge server (bridge/server.py) on localhost
     with a CI-only test secret (the production BRIDGE_SECRET is a deferred
     topic and is never touched by CI).
  2. Drives the app's real sync client (genesis_onecode/brain/sync.py)
     through a live session: heartbeat -> push -> pull round-trip.
  3. Separately GETs the production bridge health endpoint
     (https://369yz.pythonanywhere.com/health) — the public handshake.

Writes a JSON evidence file; exits nonzero if any leg fails.

Usage:
    python installer/ci_bridge_session.py <evidence_out.json>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_BRIDGE = "https://369yz.pythonanywhere.com"
TEST_SECRET = "ci-test-secret-not-production"
PORT = 18741


def get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "GENESIS-CI/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")[:500]


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("bridge_session.json")
    evidence: dict = {"legs": {}, "pass": False}

    # Leg 1: production bridge public handshake (no auth on /health).
    try:
        status, body = get(f"{PROD_BRIDGE}/health")
        evidence["legs"]["production_health"] = {
            "url": f"{PROD_BRIDGE}/health", "status": status, "body": body,
        }
        print(f"[ci-bridge] production /health -> {status} {body[:120]}")
    except Exception as e:  # noqa: BLE001
        evidence["legs"]["production_health"] = {"error": str(e)}
        print(f"[ci-bridge] production /health FAILED: {e}")

    # Leg 2: live session, app sync client <-> repo bridge server.
    env = dict(os.environ)
    env["BRIDGE_SECRET"] = TEST_SECRET
    env["PORT"] = str(PORT)
    env["BRIDGE_DATA"] = str(REPO_ROOT / ".ci_bridge_data")
    server = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "bridge" / "server.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        base = f"http://127.0.0.1:{PORT}"
        up = False
        for _ in range(50):
            try:
                status, _ = get(f"{base}/health", timeout=3)
                up = status == 200
                if up:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
        if not up:
            evidence["legs"]["session"] = {"error": "local bridge never came up"}
            print("[ci-bridge] local bridge FAILED to start")
            return 1
        print("[ci-bridge] local bridge up (repo bridge/server.py)")

        sys.path.insert(0, str(REPO_ROOT / "genesis_onecode"))
        os.environ["BRIDGE_URL"] = base
        os.environ["BRIDGE_SECRET"] = TEST_SECRET
        os.environ.setdefault("GENESIS_DATA_DIR", str(REPO_ROOT / ".ci_bridge_data"))
        from brain import sync  # the app's own sync client

        session: dict = {}
        session["heartbeat"] = sync.heartbeat()
        print(f"[ci-bridge] heartbeat -> {session['heartbeat']}")
        session["push"] = sync._call(
            "POST", "/v1/push",
            {"client_id": sync._client_id, "kind": "ci-proof",
             "payload": {"proof": "genesis-complete-1.0.0"}})
        print(f"[ci-bridge] push -> {session['push']}")
        session["pull"] = sync.pull_updates(0)
        kinds = [u.get("kind") for u in session["pull"].get("pushes", [])]
        session["pull_kinds"] = kinds
        print(f"[ci-bridge] pull -> kinds={kinds}")
        if "ci-proof" not in kinds:
            evidence["legs"]["session"] = {**session, "error": "pushed item not in pull"}
            return 1
        evidence["legs"]["session"] = session
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:  # noqa: BLE001
            server.kill()

    evidence["pass"] = (
        evidence["legs"].get("production_health", {}).get("status") == 200
        and "session" in evidence["legs"]
        and "error" not in evidence["legs"]["session"]
    )
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
    print(f"[ci-bridge] evidence -> {out_path} pass={evidence['pass']}")
    return 0 if evidence["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
