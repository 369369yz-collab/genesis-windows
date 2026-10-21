"""NEXUS reflection — the mirror. Views, never judgments.

Owned by: Builder B (seat temp-nexus-builder-b-1012), NEXUS Stage 5.
Huddle contract: ~/workspace/content_team/nexus/HUDDLE.md (Decisions 1, 6, 8).

What this module answers: "What do I look like from the graph?"

Rules (from the huddle):
- The mirror reflects; it never judges. No emitted view may contain any token
  from JUDGMENT_BLACKLIST — enforced by test, case-insensitively.
- Unknown entity -> raise UnknownEntity. The mirror NEVER invents a face:
  an entity must be known from the graph snapshot (or have explicitly supplied
  regions); otherwise the build is refused, fail-closed.
- The mirror never writes ledgers. It emits view artifacts only.
- transformed_preview is a BFS projection (depth <= 2) computed from the graph
  and is always labeled "PROJECTION — not a claim".
- becoming reflects the evidence summary as given, or "NO_EVIDENCE_RECORDED".
- heart never carries a score or a verdict on the heart; a sealed heart report
  is reflected only as the reference token "REPORT_SEALED_REFERRED_TO_FATHER".

Expected graph snapshot shape (produced by connection_graph.snapshot()):
{
  "regions": {name: {"laws": [...]}}  or {name: [law_ids]},
  "laws": {law_id: {"regions": [...]}}  or {law_id: [region_names]},
  "entities": {entity_id: {"regions": [...]}}   (optional),
  "region_count": int                            (optional)
}
"""

import json
import os
import re
from collections import deque
from datetime import datetime, timezone

from quantum.quantum_gates import network_precondition


AGENT = "temp-nexus-builder-b-1012"

DEFAULT_STATE_DIR = os.path.expanduser("~/workspace/content_team/nexus/state")
REFLECTION_STATE = "reflection_state.json"

VIEW_PREFIX = "NX-RV-"
# NOTE: trials own the NX-R- namespace (Builder C, huddle Decision 8.5); views
# use NX-RV- so the two namespaces can never collide.
PROJECTION_LABEL = "PROJECTION \u2014 not a claim"

JUDGMENT_BLACKLIST = (
    "worthy",
    "unworthy",
    "pure",
    "impure",
    "ready",
    "chosen",
    "enlightened",
    "failed",
    "deserving",
    "unworthy_soul",
)

_BLACKLIST_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in JUDGMENT_BLACKLIST) + r")\b",
    re.IGNORECASE,
)


class UnknownEntity(Exception):
    """Raised, fail-closed, when the mirror is asked to reflect an unknown entity."""


# Prefer the package-shared exception (defined once in nexus/__init__.py) so
# cross-module `except` clauses catch the same identity; fall back locally if
# the package surface is unavailable.
try:
    from nexus import UnknownEntity as _SharedUnknownEntity  # type: ignore
    UnknownEntity = _SharedUnknownEntity
except Exception:  # pragma: no cover - package surface normally present
    pass


# ---------------------------------------------------------------- snapshot maps
def _region_laws_map(snapshot):
    """Normalize the snapshot's region->laws mapping to {region: [law_id]}."""
    regions = snapshot.get("regions", {})
    out = {}
    for name, spec in regions.items():
        if isinstance(spec, dict):
            laws = spec.get("laws", [])
        else:
            laws = spec
        out[str(name)] = [str(l) for l in (laws or [])]
    return out


def _law_regions_map(snapshot, region_laws):
    """Normalize the snapshot's law->regions mapping to {law_id: [region]}.
    Rebuilt from the region map when the snapshot carries only one side."""
    laws = snapshot.get("laws")
    if laws:
        out = {}
        for law_id, spec in laws.items():
            if isinstance(spec, dict):
                regs = spec.get("regions", [])
            else:
                regs = spec
            out[str(law_id)] = [str(r) for r in (regs or [])]
        return out
    out = {}
    for region, law_ids in region_laws.items():
        for law_id in law_ids:
            out.setdefault(law_id, []).append(region)
    return out


def _adjacency(region_laws, law_regions):
    """region -> [(neighbor_region, [shared_law_ids])] over shared-law edges."""
    adjacency = {region: [] for region in region_laws}
    for law_id, regions in law_regions.items():
        for i, a in enumerate(regions):
            for b in regions[i + 1:]:
                adjacency.setdefault(a, []).append((b, law_id))
                adjacency.setdefault(b, []).append((a, law_id))
    return adjacency


def _project(entity_regions, adjacency, depth=2):
    """BFS depth<=2 from the entity's regions. Returns
    (reachable_regions_sorted, via_law_ids_sorted)."""
    starts = set(entity_regions)
    visited = set(starts)
    via_laws = set()
    reached = set()
    queue = deque((region, 0) for region in starts)
    while queue:
        region, d = queue.popleft()
        if d >= depth:
            continue
        for neighbor, law_id in adjacency.get(region, []):
            via_laws.add(law_id)
            if neighbor not in visited:
                visited.add(neighbor)
                reached.add(neighbor)
                queue.append((neighbor, d + 1))
    return sorted(reached), sorted(via_laws)


# ---------------------------------------------------------------- mirror
class Reflection:
    """The mirror: read-only reflected views of an entity's position in the web."""

    def __init__(self, state_dir=DEFAULT_STATE_DIR, agent=AGENT):
        self.state_dir = state_dir
        self.agent = agent
        self.state_path = os.path.join(state_dir, REFLECTION_STATE)
        os.makedirs(state_dir, exist_ok=True)

    def _pre(self, task):
        """HARD PRECONDITION: the network is checked before anything else."""
        return network_precondition(agent=self.agent, task=task)

    def _load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {"view_seq": 0}

    def _save_state(self, state):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.state_path)

    def build(self, entity_id, snapshot, evidence_summary=None,
              heart_report_ref=None, regions=None):
        """Build the mirror view for entity_id. Raises UnknownEntity for an
        unknown entity; never invents data. Emits zero judgment tokens."""
        self._pre("nexus.reflection.build")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise UnknownEntity("entity_id is required.")
        entity_id = entity_id.strip()
        if not isinstance(snapshot, dict) or "regions" not in snapshot:
            raise UnknownEntity("the graph snapshot cannot be read; nothing to reflect.")

        region_laws = _region_laws_map(snapshot)
        law_regions = _law_regions_map(snapshot, region_laws)
        region_count = int(snapshot.get("region_count", len(region_laws)))

        if regions is not None:
            entity_regions = [str(r) for r in regions]
        else:
            entities = snapshot.get("entities", {}) or {}
            spec = entities.get(entity_id)
            entity_regions = [str(r) for r in (spec or {}).get("regions", [])] if spec else []
        if not entity_regions:
            raise UnknownEntity(
                f"entity '{entity_id}' is unknown to the graph; the mirror invents no face."
            )
        unknown_regions = [r for r in entity_regions if r not in region_laws]
        if unknown_regions:
            raise UnknownEntity(
                f"entity '{entity_id}' claims regions outside the graph {unknown_regions}."
            )

        entity_laws = sorted({law for r in entity_regions for law in region_laws[r]})
        universal_backbone = sorted(
            law for law in entity_laws if len(law_regions.get(law, [])) == region_count
        )
        unique_signature = sorted(
            law for law in entity_laws if len(law_regions.get(law, [])) == 1
        )

        adjacency = _adjacency(region_laws, law_regions)
        reachable, via_laws = _project(entity_regions, adjacency, depth=2)

        becoming = evidence_summary if evidence_summary is not None else "NO_EVIDENCE_RECORDED"
        heart = (
            heart_report_ref
            if heart_report_ref is not None
            else "REPORT_SEALED_REFERRED_TO_FATHER"
        )

        state = self._load_state()
        state["view_seq"] += 1
        view_id = f"{VIEW_PREFIX}{state['view_seq']:04d}"
        self._save_state(state)

        view = {
            "view_id": view_id,
            "entity_id": entity_id,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "connections": {
                "laws": entity_laws,
                "regions": sorted(entity_regions),
                "universal_backbone": universal_backbone,
                "unique_signature": unique_signature,
            },
            "becoming": becoming,
            "heart": heart,
            "transformed_preview": {
                "label": PROJECTION_LABEL,
                "reachable_regions": reachable,
                "via_laws": via_laws,
            },
        }
        self._assert_no_judgment(view)
        return view

    def _assert_no_judgment(self, view):
        """Fail-closed self-check: the mirror never emits judgment words."""
        text = json.dumps(view, ensure_ascii=False)
        hit = _BLACKLIST_RE.search(text)
        if hit:
            raise ValueError(
                f"mirror integrity violation: judgment token '{hit.group(0)}' in view."
            )

    def save_view(self, view, path):
        """Persist a view artifact (for nexus_laws check_reflection)."""
        self._pre("nexus.reflection.save_view")
        self._assert_no_judgment(view)
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(view, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return path

    def load_view(self, path):
        """Load a persisted view artifact."""
        self._pre("nexus.reflection.load_view")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)


def contains_judgment(text):
    """Public helper: True if text contains any blacklisted judgment token."""
    return _BLACKLIST_RE.search(text or "") is not None
