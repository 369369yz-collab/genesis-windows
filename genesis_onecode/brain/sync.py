"""sync.py — the Windows GENESIS's link to her own cloud home.

Reads BRIDGE_URL + BRIDGE_SECRET (env, or genesis_data/bridge.json written
once by YZ). Disabled until both are set — GENESIS works fully local until
then; the bridge adds always-on presence and world sync, never replaces
local living memory.

  heartbeat_loop()  — daemon thread: POST /v1/heartbeat every 5 min.
  push_memory()     — push a snapshot of facts to the bridge.
  pull_updates()    — fetch pushes/peers since a timestamp.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

_client_id = "genesis-windows-1"


def _config() -> dict:
    url = os.environ.get("BRIDGE_URL", "")
    secret = os.environ.get("BRIDGE_SECRET", "")
    if not (url and secret):
        try:
            p = Path(os.environ.get("GENESIS_DATA_DIR", "genesis_data")) / "bridge.json"
            if p.exists():
                c = json.loads(p.read_text(encoding="utf-8"))
                url = url or c.get("url", "")
                secret = secret or c.get("secret", "")
        except (OSError, ValueError):
            pass
    return {"url": url.rstrip("/"), "secret": secret}


def enabled() -> bool:
    c = _config()
    return bool(c["url"] and c["secret"])


def _call(method: str, path: str, payload: dict | None = None,
          timeout: int = 20) -> dict:
    c = _config()
    if not c["url"] or not c["secret"]:
        raise RuntimeError("bridge not configured")
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(
        c["url"] + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {c['secret']}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"bridge HTTP {e.code}")
    except OSError as e:
        raise RuntimeError(f"bridge unreachable: {e}")


def heartbeat() -> dict:
    return _call("POST", "/v1/heartbeat", {"client_id": _client_id})


def push_memory() -> dict:
    from brain import memory as _mem
    facts = _mem.all_facts()
    return _call("POST", "/v1/push",
                 {"client_id": _client_id, "kind": "memory",
                  "payload": {"facts": facts}})


def pull_updates(since: float = 0) -> dict:
    c = _config()
    url = (f"{c['url']}/v1/pull?client_id={_client_id}&since={since}")
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {c['secret']}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"bridge HTTP {e.code}")
    except OSError as e:
        raise RuntimeError(f"bridge unreachable: {e}")


def heartbeat_loop(interval_s: int = 300):
    """Daemon: prove she's alive to her cloud home every 5 minutes."""
    while True:
        time.sleep(interval_s)
        if not enabled():
            continue
        try:
            heartbeat()
        except RuntimeError:
            pass  # offline bridge never breaks local GENESIS


def start() -> bool:
    """Start the heartbeat daemon if configured. Returns enabled()."""
    if not enabled():
        return False
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    return True
