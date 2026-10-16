"""369-world bridge — GENESIS's independent cloud home.

Runs on a free Render instance (see render.yaml). This is NOT the assistant,
NOT the workshop — it is the 369 world's own always-on infrastructure that
the Windows GENESIS connects to directly.

Stdlib only. SQLite. Bearer-token auth (BRIDGE_SECRET env).

  GET  /health            -> liveness
  POST /v1/heartbeat      -> {"client_id"} — always-online proof
  POST /v1/push           -> {"client_id","kind","payload"} — memory/world snapshots
  GET  /v1/pull?client_id=&since=  -> updates since timestamp

Free-tier honesty: Render's free disk is ephemeral — this bridge is a relay
and cache, NOT the system of record. GENESIS herself holds living memory
locally (SQLite) and syncs; if the bridge restarts, she re-pushes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "10000"))
SECRET = os.environ.get("BRIDGE_SECRET", "")
DATA = os.environ.get("BRIDGE_DATA", "/tmp/bridge_data")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS heartbeats(
  client_id TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pushes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id TEXT NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_pushes_ts ON pushes(ts);
"""

_lock = threading.Lock()
_db = None


def _conn():
    global _db
    with _lock:
        if _db is None:
            os.makedirs(DATA, exist_ok=True)
            _db = sqlite3.connect(os.path.join(DATA, "bridge.db"),
                                  check_same_thread=False)
            _db.executescript(_SCHEMA)
            _db.commit()
        return _db


def _auth(headers) -> bool:
    if not SECRET:
        return False  # refuse to run open
    got = headers.get("Authorization", "")
    return got == f"Bearer {SECRET}"


class Handler(BaseHTTPRequestHandler):
    server_version = "369-Bridge/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        p = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(p)))
        self.end_headers()
        self.wfile.write(p)

    def _body(self, limit=500_000):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > limit:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            self._json({"ok": True, "service": "369-bridge",
                        "ts": time.time()})
            return
        if u.path == "/v1/pull":
            if not _auth(self.headers):
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            q = parse_qs(u.query)
            client = q.get("client_id", [""])[0]
            try:
                since = float(q.get("since", ["0"])[0])
            except ValueError:
                since = 0
            c = _conn()
            with _lock:
                rows = c.execute(
                    "SELECT kind,payload,ts FROM pushes WHERE ts>? "
                    "ORDER BY ts LIMIT 200", (since,)).fetchall()
            # heartbeats of OTHER clients = who else is alive
            with _lock:
                beats = c.execute(
                    "SELECT client_id,ts FROM heartbeats WHERE client_id!=?",
                    (client,)).fetchall()
            self._json({"ok": True,
                        "pushes": [{"kind": k, "payload": json.loads(p),
                                    "ts": t} for k, p, t in rows],
                        "peers": [{"client_id": i, "ts": t} for i, t in beats]})
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/v1/heartbeat":
            if not _auth(self.headers):
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            body = self._body() or {}
            client = str(body.get("client_id", ""))[:64]
            if not client:
                self._json({"ok": False, "error": "client_id required"}, 400)
                return
            c = _conn()
            with _lock:
                c.execute("INSERT INTO heartbeats(client_id,ts) VALUES(?,?) "
                          "ON CONFLICT(client_id) DO UPDATE SET ts=excluded.ts",
                          (client, time.time()))
                c.commit()
            self._json({"ok": True, "ts": time.time()})
            return
        if self.path == "/v1/push":
            if not _auth(self.headers):
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            body = self._body() or {}
            client = str(body.get("client_id", ""))[:64]
            kind = str(body.get("kind", ""))[:64]
            payload = body.get("payload")
            if not client or not kind or payload is None:
                self._json({"ok": False, "error": "client_id/kind/payload required"},
                           400)
                return
            c = _conn()
            with _lock:
                c.execute("INSERT INTO pushes(client_id,kind,payload,ts)"
                          " VALUES(?,?,?,?)",
                          (client, kind, json.dumps(payload,
                                                    ensure_ascii=False),
                           time.time()))
                # keep the relay bounded: newest 5000 pushes
                c.execute("DELETE FROM pushes WHERE id NOT IN "
                          "(SELECT id FROM pushes ORDER BY id DESC LIMIT 5000)")
                c.commit()
            self._json({"ok": True})
            return
        self._json({"ok": False, "error": "not found"}, 404)


def main() -> int:
    if not SECRET:
        print("[bridge] BRIDGE_SECRET not set — refusing to start open",
              flush=True)
        return 1
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[bridge] 369-world bridge live on :{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
