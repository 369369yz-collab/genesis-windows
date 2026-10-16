"""WSGI wrapper for the 369-world bridge (server.py).

Stdlib only. Reuses server.py's auth + SQLite helpers and mirrors its
do_GET/do_POST dispatch exactly (same paths, same JSON shapes, same 401s).
Refuses to serve — loud 500 on EVERY path, never 200 — when BRIDGE_SECRET
is unset (fail-closed, like server.main()'s refuse-to-start).
"""
from __future__ import annotations

import io
import json
import os
import time
from urllib.parse import parse_qs

try:                                   # imported with bridge/ on sys.path
    import server as _srv
except ImportError:                    # imported as a package
    from bridge import server as _srv

_STATUS = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
           404: "Not Found", 405: "Method Not Allowed",
           500: "Internal Server Error"}
_CT = "application/json; charset=utf-8"


def _reply(start_response, obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    start_response(f"{status} {_STATUS[status]}",
                   [("Content-Type", _CT), ("Content-Length", str(len(body)))])
    return [body]


def _auth(environ):
    return _srv._auth({"Authorization": environ.get("HTTP_AUTHORIZATION", "")})


def _body(environ, limit=500_000):
    try:
        n = int(environ.get("CONTENT_LENGTH", "") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0 or n > limit:
        return None
    try:
        return json.loads(environ["wsgi.input"].read(n).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def application(environ, start_response):
    # Fail closed: never serve (even /health) without a secret configured.
    if not os.environ.get("BRIDGE_SECRET", ""):
        return _reply(start_response,
                      {"ok": False, "error": "bridge not configured"}, 500)
    method, path = environ.get("REQUEST_METHOD", ""), environ.get("PATH_INFO", "")
    if method == "GET":
        if path == "/health":
            return _reply(start_response, {"ok": True, "service": "369-bridge",
                                           "ts": time.time()})
        if path == "/v1/pull":
            if not _auth(environ):
                return _reply(start_response, {"ok": False,
                                               "error": "unauthorized"}, 401)
            q = parse_qs(environ.get("QUERY_STRING", ""))
            client = q.get("client_id", [""])[0]
            try:
                since = float(q.get("since", ["0"])[0])
            except ValueError:
                since = 0
            c = _srv._conn()
            with _srv._lock:
                rows = c.execute(
                    "SELECT kind,payload,ts FROM pushes WHERE ts>? "
                    "ORDER BY ts LIMIT 200", (since,)).fetchall()
                beats = c.execute(
                    "SELECT client_id,ts FROM heartbeats WHERE client_id!=?",
                    (client,)).fetchall()
            return _reply(start_response, {"ok": True,
                "pushes": [{"kind": k, "payload": json.loads(p), "ts": t}
                           for k, p, t in rows],
                "peers": [{"client_id": i, "ts": t} for i, t in beats]})
        return _reply(start_response, {"ok": False, "error": "not found"}, 404)
    if method == "POST":
        if path == "/v1/heartbeat":
            if not _auth(environ):
                return _reply(start_response, {"ok": False,
                                               "error": "unauthorized"}, 401)
            body = _body(environ) or {}
            client = str(body.get("client_id", ""))[:64]
            if not client:
                return _reply(start_response, {"ok": False,
                                               "error": "client_id required"}, 400)
            c = _srv._conn()
            with _srv._lock:
                c.execute("INSERT INTO heartbeats(client_id,ts) VALUES(?,?) "
                          "ON CONFLICT(client_id) DO UPDATE SET ts=excluded.ts",
                          (client, time.time()))
                c.commit()
            return _reply(start_response, {"ok": True, "ts": time.time()})
        if path == "/v1/push":
            if not _auth(environ):
                return _reply(start_response, {"ok": False,
                                               "error": "unauthorized"}, 401)
            body = _body(environ) or {}
            client = str(body.get("client_id", ""))[:64]
            kind = str(body.get("kind", ""))[:64]
            payload = body.get("payload")
            if not client or not kind or payload is None:
                return _reply(start_response, {"ok": False, "error":
                    "client_id/kind/payload required"}, 400)
            c = _srv._conn()
            with _srv._lock:
                c.execute("INSERT INTO pushes(client_id,kind,payload,ts)"
                          " VALUES(?,?,?,?)",
                          (client, kind, json.dumps(payload, ensure_ascii=False),
                           time.time()))
                c.execute("DELETE FROM pushes WHERE id NOT IN "
                          "(SELECT id FROM pushes ORDER BY id DESC LIMIT 5000)")
                c.commit()
            return _reply(start_response, {"ok": True})
        return _reply(start_response, {"ok": False, "error": "not found"}, 404)
    return _reply(start_response, {"ok": False, "error": "not found"}, 404)
