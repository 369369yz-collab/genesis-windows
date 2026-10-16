"""Triple-test target for bridge/wsgi.py (369 network workstream 1/3).

Run mode is driven by the environment at process start (fresh import each run):
  - BRIDGE_SECRET set   -> full flow: health / 401s / heartbeat / push / pull / DB proof
  - BRIDGE_SECRET unset -> refusal mode: loud 500 on EVERY path, never 200 on /v1/*

Each run uses its own temp BRIDGE_DATA (set BEFORE importing wsgi, since
server.py reads BRIDGE_DATA/BRIDGE_SECRET at import time). Stdlib only.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile

SECRET = os.environ.get("BRIDGE_SECRET", "")

# --- temp data dir BEFORE any bridge import ---
tmp = tempfile.mkdtemp(prefix="bridge_wsgi_test_")
os.environ["BRIDGE_DATA"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wsgi  # noqa: E402  (imports server.py underneath)

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'ok' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def call(method, path, body=None, auth=None, query=""):
    data = b"" if body is None else json.dumps(body).encode()
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(data)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(data),
    }
    if auth is not None:
        env["HTTP_AUTHORIZATION"] = auth
    got = {}

    def start_response(status, headers):
        got["status"] = status
        got["headers"] = dict(headers)

    raw = b"".join(wsgi.application(env, start_response))
    code = int(got["status"].split()[0])
    try:
        obj = json.loads(raw.decode())
    except ValueError:
        obj = None
    return code, obj, raw


GOOD = f"Bearer {SECRET}"


def refusal_run():
    print("== refusal mode (BRIDGE_SECRET unset) ==")
    for method, path in [("GET", "/health"), ("GET", "/v1/pull"),
                         ("POST", "/v1/heartbeat"), ("POST", "/v1/push")]:
        code, obj, _ = call(method, path, body={"client_id": "x"})
        check(f"{method} {path} refused loudly",
              code == 500 and obj and obj.get("ok") is False, f"got {code}")
        check(f"{method} {path} never 200", code != 200)
    check("no DB created while refused",
          not os.path.exists(os.path.join(tmp, "bridge.db")))


def full_run():
    print("== full flow (BRIDGE_SECRET set) ==")
    code, obj, _ = call("GET", "/health")
    check("GET /health 200 unauthenticated",
          code == 200 and obj and obj.get("ok") is True
          and obj.get("service") == "369-bridge", f"got {code}")

    code, obj, _ = call("POST", "/v1/heartbeat", {"client_id": "g1"})
    check("POST /v1/heartbeat unauthenticated -> 401", code == 401
          and obj.get("error") == "unauthorized", f"got {code}")

    code, obj, _ = call("POST", "/v1/heartbeat", {"client_id": "g1"},
                        auth="Bearer wrong")
    check("POST /v1/heartbeat wrong bearer -> 401", code == 401, f"got {code}")

    code, obj, _ = call("GET", "/v1/pull", query="client_id=g1", auth=GOOD)
    check("GET /v1/pull authed empty -> ok", code == 200 and obj.get("ok")
          and obj.get("pushes") == [], f"got {code}")

    code, obj, _ = call("POST", "/v1/heartbeat", {"client_id": "g1"}, auth=GOOD)
    check("POST /v1/heartbeat authed -> ok",
          code == 200 and obj.get("ok") is True, f"got {code}")

    code, obj, _ = call("POST", "/v1/heartbeat", {}, auth=GOOD)
    check("POST /v1/heartbeat authed missing client_id -> 400",
          code == 400, f"got {code}")

    payload = {"note": "triple-test", "n": 3, "tags": ["a", "b"]}
    code, obj, _ = call("POST", "/v1/push",
                        {"client_id": "g1", "kind": "memory", "payload": payload},
                        auth=GOOD)
    check("POST /v1/push authed -> ok", code == 200 and obj.get("ok"), f"got {code}")

    code, obj, _ = call("POST", "/v1/push", {"client_id": "g1"}, auth=GOOD)
    check("POST /v1/push authed missing fields -> 400", code == 400, f"got {code}")

    code, obj, _ = call("POST", "/v1/heartbeat", {"client_id": "peer-9"}, auth=GOOD)
    check("second client heartbeat ok", code == 200 and obj.get("ok"))

    code, obj, _ = call("GET", "/v1/pull", query="client_id=g1&since=0", auth=GOOD)
    pushes = obj.get("pushes", []) if obj else []
    peers = obj.get("peers", []) if obj else []
    check("GET /v1/pull returns pushed payload",
          code == 200 and any(p.get("payload") == payload and p.get("kind") == "memory"
                              for p in pushes), f"got {code}, pushes={len(pushes)}")
    check("GET /v1/pull reports peer heartbeat",
          any(r.get("client_id") == "peer-9" for r in peers), f"peers={peers}")

    code, obj, _ = call("GET", "/v1/pull", query="client_id=g1&since=9999999999",
                        auth=GOOD)
    check("GET /v1/pull since=future -> empty",
          code == 200 and obj.get("pushes") == [], f"got {code}")

    code, obj, _ = call("GET", "/v1/pull", auth="Bearer wrong")
    check("GET /v1/pull wrong bearer -> 401", code == 401, f"got {code}")

    code, obj, _ = call("GET", "/nope")
    check("GET /nope -> 404", code == 404, f"got {code}")

    # SQLite behavior identical to server.py: same file, same schema, real rows
    db = os.path.join(tmp, "bridge.db")
    check("bridge.db created under BRIDGE_DATA", os.path.exists(db))
    con = sqlite3.connect(db)
    n_push = con.execute("SELECT COUNT(*) FROM pushes").fetchone()[0]
    n_beat = con.execute("SELECT COUNT(*) FROM heartbeats").fetchone()[0]
    stored = con.execute("SELECT payload FROM pushes ORDER BY id DESC LIMIT 1").fetchone()[0]
    con.close()
    check("pushes row persisted in SQLite", n_push == 1, f"rows={n_push}")
    check("heartbeats rows persisted (g1 + peer-9)", n_beat == 2, f"rows={n_beat}")
    check("payload JSON round-trips byte-identical",
          json.loads(stored) == payload)


def main():
    if SECRET:
        full_run()
    else:
        refusal_run()
    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed "
          f"({'GREEN' if not FAIL else 'RED'})")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
