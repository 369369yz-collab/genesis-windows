"""Browser profiles: one isolated Chromium profile dir per agent/owner.

Each agent (GENESIS herself + every worker agent) gets its own persistent
profile directory under the app data dir. Cookies, logins and storage never
leak between agents. The governor owns profile lifecycle.
"""
from __future__ import annotations

import re
from pathlib import Path

_OWNER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def profile_dir(base: Path, owner: str) -> Path:
    """Return (creating) the profile directory for an owner id."""
    if not _OWNER_RE.match(owner):
        raise ValueError(f"invalid owner id: {owner!r}")
    d = base / "browser_profiles" / owner
    d.mkdir(parents=True, exist_ok=True)
    return d


def quarantine_dir(base: Path) -> Path:
    """Downloads land here first; nothing executes from quarantine."""
    d = base / "browser_quarantine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_owners(base: Path) -> list[str]:
    root = base / "browser_profiles"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
