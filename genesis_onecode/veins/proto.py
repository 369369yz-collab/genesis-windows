"""veins.proto — NEXUS §3 protocol namespace for the veins system.

Adapter, not rewrite: re-exports the wire contract from
genesis_final.nexus.proto (envelopes, signing, constants, degraded shapes,
ONLINE/DEGRADED/OFFLINE states) and adds the small atomic snapshot-write
helper used by presence.py and degraded_cache.py.

Never-again tmp-name law: every registry/cache snapshot goes through
atomic_write_json() below — unique tmp name (pid + thread + uuid), fsync,
os.replace. Shared ".tmp" names are forbidden.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path

def _find_workspace() -> Path:
    """Locate the workspace that holds genesis_final/nexus/proto.py.

    Resolution order:
      1. GENESIS_WORKSPACE env var (explicit override).
      2. Walk upward from this file — the tree may be checked out at any
         depth (e.g. genesis_creation/repo/genesis_onecode/veins/), so a
         fixed parents[N] is wrong; search for the real marker instead.
      3. Legacy fallback: parents[3] (the original ~/workspace layout).
    """
    env = os.environ.get("GENESIS_WORKSPACE")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "genesis_final" / "nexus" / "proto.py").is_file():
            return parent
    return here.parents[3]


_WORKSPACE = _find_workspace()
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

# Adapter: everything the veins system needs from the existing wire protocol.
from genesis_final.nexus.proto import (  # noqa: E402,F401
    CIRCUIT_FAILURE_THRESHOLD,
    CIRCUIT_OPEN_MINUTES,
    DEGRADED,
    HEARTBEAT_INTERVAL_S,
    KINDS,
    LOOPBACK_HOST,
    NEXUS_VERSION,
    OFFLINE,
    OFFLINE_AFTER_S,
    ONLINE,
    NodeRecord,
    degraded_result,
    envelope_valid,
    make_envelope,
    make_heartbeat,
    new_boot_token,
    node_secret,
    sign_envelope,
    tag_advisory,
    utcnow_iso,
    verify_envelope,
)

HEARTBEAT_EVERY_S = HEARTBEAT_INTERVAL_S          # 30.0  — formula §3
OFFLINE_AFTER_S = OFFLINE_AFTER_S                # 120.0 — formula §3
CIRCUIT_THRESHOLD = CIRCUIT_FAILURE_THRESHOLD    # 5     — formula §3
CIRCUIT_OPEN_S = CIRCUIT_OPEN_MINUTES * 60.0     # 900.0 — formula §3


def atomic_write_json(path: str | Path, obj: dict) -> Path:
    """Atomically write a JSON snapshot. Unique tmp + fsync + os.replace.

    Same durability guarantees as the 369 network's presence_io, local to
    the veins system (no cross-registry lock needed for these files).
    """
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        "%s.tmp.%d.%d.%s" % (path.name, os.getpid(),
                             threading.get_ident(), uuid.uuid4().hex))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        try:  # fsync the directory so the rename itself is durable
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def read_json_tolerant(path: str | Path, default=None):
    """Read a JSON snapshot, tolerating a missing or torn file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
