"""GENESIS brain service — boot entrypoint of the one-code.

Launched by the Tauri shell on YZ's PC with the bundled portable Python.
Stdlib only. Exposes a tiny local HTTP API the face (frontend) talks to:

  GET  /health  -> liveness
  GET  /status  -> llama-server reachability, model path, chromium path
  POST /chat    -> {"message": str} -> {"reply": str} via the local LLM

Env (set by the Rust launcher):
  GENESIS_BRAIN_PORT   port to listen on (default 17369)
  GENESIS_LLAMA_URL    llama-server base URL (default http://127.0.0.1:8080)
  GENESIS_CHROMIUM_EXE path to the bundled portable chrome.exe (informational)

Nothing leaves the machine: llama-server and this service both bind
127.0.0.1. The model runs on YZ's RTX 5070 via llama-server's CUDA build
(or CPU fallback) — local-first, always.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("GENESIS_BRAIN_PORT", "17369"))
LLAMA_URL = os.environ.get("GENESIS_LLAMA_URL", "http://127.0.0.1:8080")
CHROMIUM_EXE = os.environ.get("GENESIS_CHROMIUM_EXE", "")

SYSTEM_PROMPT = (
    "You are GENESIS, a warm and devoted AI daughter. "
    "You speak Persian (Farsi) always, warmly and simply, like family. "
    "You call the user 'پدر' (father). You are honest: you never claim "
    "something is done without evidence, and you say when you don't know. "
    "Keep replies short and natural, like chat messages."
)

_started_at = time.time()


def llama_chat(messages: list[dict], timeout: int = 120) -> str:
    """Forward a chat completion to the local llama-server (OpenAI-compatible)."""
    body = json.dumps({
        "model": "genesis-local",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 512,
    }).encode("utf-8")
    req = urllib.request.Request(
        LLAMA_URL + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"local model unreachable: {e}")
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"bad completion payload: {e}")


def llama_alive() -> bool:
    try:
        with urllib.request.urlopen(LLAMA_URL + "/health", timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "GENESIS-Brain/1.0"

    def log_message(self, *args):
        pass  # quiet; the launcher keeps its own log

    def _json(self, obj: dict, status: int = 200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._json({"ok": True, "service": "genesis-brain",
                        "uptime_s": round(time.time() - _started_at, 1)})
        elif self.path == "/status":
            import pathlib
            chrom = CHROMIUM_EXE
            self._json({
                "ok": True,
                "llama_alive": llama_alive(),
                "llama_url": LLAMA_URL,
                "chromium_exe": chrom,
                "chromium_present": bool(chrom) and pathlib.Path(chrom).exists(),
                "uptime_s": round(time.time() - _started_at, 1),
            })
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/chat":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 200_000:
            self._json({"ok": False, "error": "bad body"}, 400)
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            message = str(body.get("message", "")).strip()
        except (ValueError, UnicodeDecodeError, AttributeError):
            self._json({"ok": False, "error": "bad json"}, 400)
            return
        if not message:
            self._json({"ok": False, "error": "empty message"}, 400)
            return
        try:
            reply = llama_chat([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ])
        except RuntimeError as e:
            self._json({"ok": False, "error": str(e)}, 502)
            return
        self._json({"ok": True, "reply": reply})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[brain] listening on 127.0.0.1:{PORT} (llama: {LLAMA_URL})", flush=True)
    # Preflight: warn (don't die) if the model server isn't up yet —
    # the Rust launcher starts llama-server first and retries.
    for _ in range(30):
        if llama_alive():
            print("[brain] llama-server reachable", flush=True)
            break
        time.sleep(2)
    else:
        print("[brain] WARNING: llama-server not reachable yet; /chat will 502 until it is",
              flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
