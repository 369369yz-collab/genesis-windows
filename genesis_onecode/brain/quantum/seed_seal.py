#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# VENDORED COPY - GENESIS embed step 7, Phase 2 (2026-10-21).
# Source: ~/workspace/content_team/quantum/seed_seal.py (369 quantum seed layer, content_team).
# Copied verbatim except where a "VENDORING ADAPTATION" note says
# otherwise. The upstream file remains the canonical world copy; this
# embed exists so the shipped app carries the seed layer inside itself
# (YZ law 2026-10-16: the whole 369 world lives inside GENESIS).
# Runtime state (mother seed, consumers, audit log) lives in the
# sibling state/ directory of THIS copy - separate from the world copy.
# ---------------------------------------------------------------------------
"""LAW-099 — MOTHER-SEED TAMPER-EVIDENCE (mother-seed seal law).

state/mother_seed.json is the root of the whole quantum audit chain
(proof_check replays against it). A silent rewrite would invalidate every
replay. This module seals the file with an HMAC-SHA256 tag and a write-audit
log. Tamper -> fail closed (SeedTamperError) + health.log ALERT incident.

The key lives in quantum/state/seed_seal.key (600). This is tamper-EVIDENCE,
not crypto-security against a root attacker: the point is that no silent
rewrite can pass as the real seed.
"""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
MOTHER_FILE = os.path.join(STATE, "mother_seed.json")
KEY_FILE = os.path.join(STATE, "seed_seal.key")
SEAL_LOG = os.path.join(STATE, "seed_seal.log")
LAW = "LAW-099"


class SeedTamperError(RuntimeError):
    """The mother-seed file failed its integrity seal. Fail closed."""


def _key():
    if not os.path.exists(KEY_FILE):
        os.makedirs(STATE, exist_ok=True)
        k = secrets.token_bytes(32)
        with open(KEY_FILE, "wb") as f:
            f.write(k)
        os.chmod(KEY_FILE, 0o600)
        _audit("key-generated", "seed seal key created (600)")
    else:
        with open(KEY_FILE, "rb") as f:
            k = f.read()
    return k


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _audit(event, detail):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(SEAL_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}Z] {event}: {detail}\n")


def seal(obj):
    """Compute the integrity tag for a mother-seed object (dict)."""
    return hmac.new(_key(), _canonical(obj), hashlib.sha256).hexdigest()


def write_sealed(obj):
    """Write mother_seed.json WITH its seal + write-audit entry."""
    tag = seal(obj)
    payload = {"seed": obj, "seal": tag, "law": LAW,
               "sealed_at": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"}
    tmp = MOTHER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, MOTHER_FILE)
    _audit("sealed", f"date={obj.get('date')} source={obj.get('source')} tag={tag[:16]}…")
    return payload


def read_sealed():
    """Read + verify mother_seed.json. Raises SeedTamperError on any mismatch."""
    try:
        with open(MOTHER_FILE, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as e:
        raise SeedTamperError(f"LAW-099: cannot read mother seed: {e}")
    # legacy format (pre-seal plain JSON): seal it in place once, then verify
    if "seal" not in payload:
        _audit("legacy-upgrade", "plain mother_seed.json found — sealing in place")
        payload = write_sealed(payload)
    obj, tag = payload.get("seed"), payload.get("seal")
    if not isinstance(obj, dict) or not isinstance(tag, str):
        _tamper("malformed payload")
    expected = seal(obj)
    if not hmac.compare_digest(expected, tag):
        _tamper(f"seal mismatch (expected {expected[:16]}…, found {tag[:16]}…)")
    return obj


def _tamper(reason):
    _audit("TAMPER", reason)
    _incident(f"mother-seed tamper evidence: {reason}")
    raise SeedTamperError(f"LAW-099: mother-seed integrity failed: {reason}")


def _incident(msg):
    try:
        ct_state = os.path.join(os.path.dirname(ROOT), "state", "health.log")
        with open(ct_state, "a", encoding="utf-8") as f:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            f.write(f"[ALERT {ts}] seed_seal: {msg}\n")
    except Exception:
        pass


def verify_now():
    """Public check: returns (ok, info)."""
    try:
        obj = read_sealed()
        return True, {"date": obj.get("date"), "source": obj.get("source")}
    except SeedTamperError as e:
        return False, {"error": str(e)}
