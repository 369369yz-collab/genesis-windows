# ---------------------------------------------------------------------------
# first_run.py — first-boot mother-seed creation for fresh installs.
# GENESIS embed step 7, Phase 3 (2026-10-21). New code, written for the
# vendored brain.quantum package (not a vendored copy).
#
# THE GAP IT FIXES: upstream qrng.get_mother_seed() re-raises
# seed_seal.SeedTamperError when state/mother_seed.json does not exist
# yet (seed_seal raises on an unreadable file), and the seed hub's
# fail-closed gate then refuses every draw — so on a brand-new install
# EVERY womb birth degraded to stdlib random until a mother seed file
# somehow appeared. First-run seeding is an install/boot step, not a
# hub change (Phase 2 report, flagged item 2).
#
# WHAT IT DOES: if (and only if) no mother seed exists in the quantum
# state dir, create one from secrets.token_bytes(64) — the local CSPRNG —
# and store it through the exact upstream mechanism: seed_seal.
# write_sealed({date, seed_hex, source, quantum, fetched_at}), the same
# record shape qrng.get_mother_seed() itself writes after a fetch.
#
# HONESTY (QUANTUM-NAME INTEGRITY, YZ 2026-10-11): this mother is NOT
# quantum and is never labelled quantum. Its source is "local-csprng",
# its quantum flag is False, and a sidecar record
# (state/first_run_mother.json) marks its provenance "local-csprng"
# with the seed's SHA-256. Womb births drawn from it record
# seed_source "local-csprng" — the "quantum-certified" label stays
# reserved for mothers whose provenance is a real quantum source.
# If a network source (ANU QRNG etc.) answers on a later day,
# qrng.get_mother_seed() rotates to that mother by its own rules and
# this local mother is simply history.
# ---------------------------------------------------------------------------
"""First-run mother seed: create a sealed local-CSPRNG mother iff none exists."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone

from . import seed_seal

PROVENANCE_LOCAL = "local-csprng"
SIDECAR_NAME = "first_run_mother.json"
_SEED_BYTES = 64


def _state_dir() -> str:
    # Derived from seed_seal's MOTHER_FILE at call time (single source of
    # truth for where the sealed mother lives; tests redirect it there).
    return os.path.dirname(os.path.abspath(seed_seal.MOTHER_FILE))


def sidecar_path() -> str:
    return os.path.join(_state_dir(), SIDECAR_NAME)


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def mother_exists() -> bool:
    return os.path.exists(seed_seal.MOTHER_FILE)


def ensure_mother_seed() -> dict:
    """Create today's mother seed from the local CSPRNG iff none exists.

    Idempotent: when a mother seed file already exists (any provenance),
    nothing is written and the returned dict says so. Never overwrites —
    a tampered or stale mother is the hub/seal layer's business, not a
    silent re-seed. Returns a status dict; raises only on genuine I/O
    failure while creating (the service calls this fail-soft).
    """
    if mother_exists():
        return {"created": False, "exists": True,
                "local_csprng": local_mother_info() is not None}
    os.makedirs(_state_dir(), exist_ok=True)
    seed = secrets.token_bytes(_SEED_BYTES)
    obj = {
        "date": _utc_today(),
        "seed_hex": seed.hex(),
        "source": PROVENANCE_LOCAL,
        "quantum": False,
        "fetched_at": _now_iso(),
    }
    # Store through the upstream seal mechanism, exact upstream format.
    seed_seal.write_sealed(obj)
    sidecar = {
        "provenance": PROVENANCE_LOCAL,
        "date": obj["date"],
        "seed_sha256": hashlib.sha256(seed).hexdigest(),
        "created_at": _now_iso(),
        "created_by": "genesis_onecode/brain/quantum/first_run.py",
        "note": ("First-run local mother seed, drawn from the local "
                 "CSPRNG (secrets). NOT quantum: quantum=False, and womb "
                 "births from it are labelled 'local-csprng', never "
                 "'quantum-certified'."),
    }
    tmp = sidecar_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)
    os.replace(tmp, sidecar_path())
    return {"created": True, "provenance": PROVENANCE_LOCAL,
            "date": obj["date"], "seed_sha256": sidecar["seed_sha256"]}


def local_mother_info() -> dict | None:
    """Provenance check: is TODAY's sealed mother the first-run local one?

    Returns {"date", "seed_sha256", "source"} only when ALL of these
    hold: the sealed mother verifies (LAW-099), its date is today, its
    source is "local-csprng", its quantum flag is False, and the sidecar
    record exists with a matching seed SHA-256. Otherwise None.
    Never raises.
    """
    try:
        obj = seed_seal.read_sealed()
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("source") != PROVENANCE_LOCAL or obj.get("quantum") is not False:
        return None
    if obj.get("date") != _utc_today() or not obj.get("seed_hex"):
        return None
    try:
        seed = bytes.fromhex(obj["seed_hex"])
    except (TypeError, ValueError):
        return None
    digest = hashlib.sha256(seed).hexdigest()
    try:
        with open(sidecar_path(), encoding="utf-8") as f:
            side = json.load(f)
    except (OSError, ValueError):
        return None
    if side.get("provenance") != PROVENANCE_LOCAL:
        return None
    if side.get("seed_sha256") != digest:
        return None
    return {"date": obj["date"], "seed_sha256": digest,
            "source": obj["source"]}
