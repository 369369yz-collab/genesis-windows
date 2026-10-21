"""world_data.py — embedded world data for the shipped GENESIS app.

GENESIS embed step 7, Phase 2 (2026-10-21). Static, verbatim snapshots of
world data live in brain/world_data/ so the app carries them inside
itself (YZ law 2026-10-16: the whole 369 world lives inside GENESIS):

  presence_snapshot.json — the 369 seat registry (788 seats), frozen.
      HONESTY LAW: a snapshot, never live. seats_block() says so.
  nexus_laws.json        — NEXUS_LAWS.json from content_team/nexus.
  playbooks.json         — PLAYBOOKS.json from genesis_final/knowledge.

Loaders are strict: a missing or corrupt file raises, so callers decide
how to degrade (service.py catches and reports zeros). Counts are always
computed from the real file structure — never hardcoded — so a refreshed
snapshot changes the numbers truthfully.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "world_data"

_cache: dict[str, object] = {}


def _load(name: str):
    if name not in _cache:
        with open(_DATA_DIR / name, encoding="utf-8") as f:
            _cache[name] = json.load(f)
    return _cache[name]


# ---- 369 seat registry snapshot -------------------------------------------

def _presence() -> dict:
    return _load("presence_snapshot.json")


def seat_count() -> int:
    """Number of seats (agent records) in the presence snapshot."""
    return len(_presence()["agents"])


def presence_snapshot_at() -> str | None:
    """When the snapshot was taken (from the sidecar meta), or None."""
    try:
        return _load("presence_snapshot.meta.json")["snapshot_at"]
    except Exception:
        return None


def snapshot_age_seconds(now_ts: float | None = None) -> float | None:
    """Age of the presence snapshot in seconds, or None if unknown."""
    import time
    from datetime import datetime, timezone
    at = presence_snapshot_at()
    if not at:
        return None
    try:
        taken = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ")
        taken = taken.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    return max(0.0, (now_ts if now_ts is not None else time.time()) - taken)


def seats_block() -> dict:
    """The /world/state seats block. live is False — it is a snapshot."""
    return {
        "count": seat_count(),
        "snapshot_at": presence_snapshot_at(),
        "live": False,
    }


# ---- NEXUS laws -------------------------------------------------------------
# NEXUS_LAWS.json structure (verified at embed time): a dict with 5
# top-level keys — version, generated_by, generated_at, capacity, laws.
# The "laws" value is a list of law records (NEXUS-LAW-001 .. 005 at
# embed time). nexus_law_count() counts those law records;
# nexus_top_level_keys() counts the container's keys. Both happen to
# be 5 today; they are different numbers with different meanings.

def _nexus() -> dict:
    return _load("nexus_laws.json")


def nexus_law_count() -> int:
    """Number of law records in the embedded NEXUS laws list."""
    return len(_nexus()["laws"])


def nexus_top_level_keys() -> int:
    """Number of top-level keys in the NEXUS laws document."""
    return len(_nexus())


def nexus_block() -> dict:
    """The /world/state nexus block."""
    return {
        "laws_present": nexus_law_count() > 0,
        "top_level_keys": nexus_top_level_keys(),
        "law_count": nexus_law_count(),
    }


# ---- knowledge playbooks ----------------------------------------------------
# PLAYBOOKS.json structure (verified at embed time): a dict with "meta"
# and "entries"; "entries" is the list of playbooks (228 at embed time).

def _playbooks() -> dict:
    return _load("playbooks.json")


def playbook_count() -> int:
    """Number of playbook entries in the embedded PLAYBOOKS.json."""
    return len(_playbooks()["entries"])
