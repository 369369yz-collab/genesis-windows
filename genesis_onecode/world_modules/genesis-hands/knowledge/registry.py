#!/usr/bin/env python3
"""Runtime knowledge registry for genesis-hands.

Loads the reverse-engineered AI knowledge packs injected into this module
(YZ RE-QUEUE order 2026-10-13) and exposes them as queryable data.
Verbatim extraction from ~/workspace/genesis_transfer/ai_knowledge/<pack>/;
no invented content.
"""
import json
from pathlib import Path

MODULE = "hands"
_PACKS_PATH = Path(__file__).parent / "packs.json"

_PACKS = None


def _load():
    global _PACKS
    if _PACKS is None:
        _PACKS = json.loads(_PACKS_PATH.read_text(encoding="utf-8"))
    return _PACKS


def list_packs():
    """Sorted names of knowledge packs injected into this module."""
    return sorted(_load().keys())


def guardrails(pack):
    """Standing-law guardrails attached to a pack (e.g. NO AI VOICE)."""
    return list(_load().get(pack, {}).get("guardrails", []))


def get_techniques(pack=None):
    """All techniques, optionally filtered to one pack."""
    packs = _load()
    names = [pack] if pack else sorted(packs)
    out = []
    for n in names:
        for t in packs[n]["techniques"]:
            out.append(dict(t, pack=n))
    return out


def get_prompt_patterns(pack=None):
    """All prompt patterns, optionally filtered to one pack."""
    packs = _load()
    names = [pack] if pack else sorted(packs)
    out = []
    for n in names:
        for p in packs[n]["prompt_patterns"]:
            out.append(dict(p, pack=n))
    return out


def get_workflows(pack=None):
    """All workflow designs, optionally filtered to one pack."""
    packs = _load()
    names = [pack] if pack else sorted(packs)
    out = []
    for n in names:
        for w in packs[n]["workflows"]:
            out.append(dict(w, pack=n))
    return out


def search(query):
    """Case-insensitive search over ids, titles and bodies.

    Returns list of (pack, kind, id, title).
    """
    q = query.lower()
    hits = []
    packs = _load()
    for n in sorted(packs):
        for kind in ("techniques", "prompt_patterns", "workflows"):
            for item in packs[n][kind]:
                hay = " ".join(str(v) for v in item.values()).lower()
                if q in hay:
                    hits.append((n, kind, item["id"], item["title"]))
    return hits


def technique_ids(pack=None):
    return [t["id"] for t in get_techniques(pack)]


def prompt_pattern_ids(pack=None):
    return [p["id"] for p in get_prompt_patterns(pack)]


def workflow_ids(pack=None):
    return [w["id"] for w in get_workflows(pack)]
