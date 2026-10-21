"""Documented sync of local memory with the network mind (the MIND).

Local-first privacy: NOTHING here uploads anything by itself. The only path
data leaves the machine is through an explicit bridge call, and the bridge
is not implemented in this module -- it belongs to the bridge integration
layer. This file provides:

  - export_manifest(): serialize the local store into a portable manifest.
  - import_manifest(d): validate and merge a manifest INTO this machine.
  - send_to_mind(manifest): THE bridge call point. Honestly stubbed: returns
    {"status": "bridge_not_configured"} unless a real bridge callable is
    registered via register_bridge().

No fake syncing. No network traffic is ever attempted from this module.
"""

import hashlib
import json
import math
import time

import memory

_MANIFEST_VERSION = 1

# Upper plausibility bound for every epoch this module accepts, in seconds
# since the Unix epoch: 4102444800.0 == 2100-01-01 00:00:00 UTC.
#
# Rationale: genuine Unix timestamps today are ~1.8e9. Legitimate use of this
# module includes far-future scheduled manifests (updated/created stamps
# deliberately set decades ahead), so the bound must comfortably exceed any
# real scheduling horizon. Year 2100 is 70+ years out -- far beyond it --
# while still infinitesimal compared to the finite-but-absurd band (>= ~1e300)
# an attacker can reach through plain JSON numbers (1e308, 10**300, 2**1000)
# to permanently freeze a key under newer_wins. Anything outside
# [0, MAX_EPOCH] is rejected with a clean error dict and never stored.
MAX_EPOCH = 4102444800.0

_bridge_send = None  # registered by the bridge integration layer (bridge module)


def _safe_epoch(value, default):
    """Parse an epoch value without ever raising.

    Accepts ONLY finite real numbers inside [0, MAX_EPOCH]: int/float within
    that range, or strings that parse to finite floats within that range.
    NaN, inf, -inf, negatives, inputs that overflow float() (e.g. huge ints),
    and finite-but-absurd magnitudes (1e308, 10**300, 2**1000 ...) all return
    None -- they are rejected, never stored. Returns a float, or None when
    the value is present but not an acceptable epoch (None/empty falls back
    to `default`)."""
    if value is None or value == "":
        return float(default)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result):
        return None
    if result < 0 or result > MAX_EPOCH:
        return None
    return result


def register_bridge(send_callable):
    """Register the real bridge send function.

    send_callable(manifest: dict) -> dict with a "status" key.
    Called by the bridge integration layer on Windows, NOT by this module.
    """
    global _bridge_send
    if not callable(send_callable):
        raise TypeError("send_callable must be callable")
    _bridge_send = send_callable


def export_manifest(db_path=None):
    """Build a portable, checksummed manifest of the local memory store.

    This does NOT transmit anything. It produces the payload that an
    explicit bridge call may send later.
    Returns: {"status": "ok", "manifest": {...}}.
    """
    conn = memory._connect(db_path)
    try:
        rows = conn.execute(
            "SELECT key, value_json, tags_json, created_utc, updated_utc "
            "FROM memories ORDER BY key"
        ).fetchall()
    finally:
        conn.close()
    entries = [
        {
            "key": r["key"],
            "value": json.loads(r["value_json"]),
            "tags": json.loads(r["tags_json"]),
            "created_utc": r["created_utc"],
            "updated_utc": r["updated_utc"],
        }
        for r in rows
    ]
    manifest = {
        "manifest_version": _MANIFEST_VERSION,
        "exported_utc": time.time(),
        "entry_count": len(entries),
        "entries": entries,
    }
    body = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
    manifest["sha256"] = hashlib.sha256(body).hexdigest()
    return {"status": "ok", "manifest": manifest}


def _validate_manifest(d):
    if not isinstance(d, dict):
        return "manifest must be a dict"
    if d.get("manifest_version") != _MANIFEST_VERSION:
        return "unsupported manifest_version (expected %d)" % _MANIFEST_VERSION
    entries = d.get("entries")
    if not isinstance(entries, list):
        return "entries must be a list"
    for entry in entries:
        if not isinstance(entry, dict) or "key" not in entry or "value" not in entry:
            return "each entry must be a dict with at least 'key' and 'value'"
        if not isinstance(entry["key"], str):
            return "entry 'key' must be a string, got %s" % type(entry["key"]).__name__
    body = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if hashlib.sha256(body).hexdigest() != d.get("sha256"):
        return "sha256 checksum mismatch -- manifest rejected"
    return None


def import_manifest(d, db_path=None, policy="newer_wins"):
    """Merge a manifest into the local store. Import-only; never uploads.

    policy: "newer_wins" (default) -- an incoming entry replaces the local one
            only if its updated_utc is newer; "overwrite" -- incoming always wins.
    Returns: {"status": "ok", "imported": N, "skipped": M} or {"status":"error"}.
    """
    err = _validate_manifest(d)
    if err:
        return {"status": "error", "error": err}
    if policy not in ("newer_wins", "overwrite"):
        return {"status": "error", "error": "unknown policy: %s" % policy}
    imported = 0
    skipped = 0
    conn = memory._connect(db_path)
    try:
        for entry in d["entries"]:
            key = entry["key"]
            row = conn.execute(
                "SELECT updated_utc FROM memories WHERE key = ?", (key,)
            ).fetchone()
            incoming_utc = _safe_epoch(entry.get("updated_utc"), 0)
            if incoming_utc is None:
                return {"status": "error",
                        "error": "entry %r has non-numeric or out-of-range updated_utc" % (key,)}
            if policy == "newer_wins" and row and row["updated_utc"] >= incoming_utc:
                skipped += 1
                continue
            tags = entry.get("tags", [])
            created = _safe_epoch(entry.get("created_utc"), time.time())
            if created is None:
                return {"status": "error",
                        "error": "entry %r has non-numeric or out-of-range created_utc" % (key,)}
            now = time.time()
            conn.execute(
                """INSERT INTO memories (key, value_json, tags_json, created_utc, updated_utc)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value_json=excluded.value_json,
                     tags_json=excluded.tags_json,
                     updated_utc=excluded.updated_utc""",
                (
                    key,
                    json.dumps(entry["value"], ensure_ascii=False),
                    json.dumps(tags if isinstance(tags, list) else [], ensure_ascii=False),
                    created,  # kept as-is on conflict: created_utc is never updated
                    max(incoming_utc, now) if incoming_utc else now,
                ),
            )
            imported += 1
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "imported": imported, "skipped": skipped}


def send_to_mind(manifest):
    """BRIDGE CALL POINT (honest stub).

    The real bridge integration registers itself via register_bridge().
    Until then, this returns {"status": "bridge_not_configured"} and sends
    NOTHING -- it never fakes a transmission.
    """
    if _bridge_send is None:
        return {
            "status": "bridge_not_configured",
            "error": (
                "No bridge registered. The MIND sync path is not wired on this "
                "machine. Register one with genesis-memory.sync.register_bridge(). "
                "Nothing was transmitted."
            ),
        }
    return _bridge_send(manifest)
