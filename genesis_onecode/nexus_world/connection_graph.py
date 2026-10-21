"""nexus.connection_graph — the relationship web, DISCOVERED not invented (Builder A).

Parsed live from planet/regions.py REGIONS (ground truth). Nodes and edges
are derived, never imagined:

Nodes:
    RegionNode(name, path, laws, core_services, baseline)
    LawNode(law_id, regions)

Edges:
    region -> law   kind="governed_by", weight=1   (from each region's laws list)
    law <-> law     kind="co_occurs",  weight=#regions listing both
    region <-> region kind="shares_laws", weight=#shared law IDs

Queries (read-only; the documented cross-module contract for reflection.py):
    laws_for_region, regions_for_law, neighbors, shared_laws, law_span,
    universal_laws, unique_signature, shared_jaccard, shortest_path,
    no_lonely, snapshot.

Hard rule: every public entry point calls network_precondition FIRST.
build() stays output-pure (deterministic given its input dict): the
precondition gates execution only and never changes the computed graph.
100% technical English.
"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations

from nexus import AGENT_SEAT

GOVERNED_BY = "governed_by"
CO_OCCURS = "co_occurs"
SHARES_LAWS = "shares_laws"


def _gate(task: str) -> None:
    """Network precondition FIRST for every public entry point."""
    from quantum.quantum_gates import network_precondition

    network_precondition(agent=AGENT_SEAT, task=task)


@dataclass(frozen=True)
class RegionNode:
    name: str
    path: str
    laws: tuple
    core_services: tuple
    baseline: tuple = field(default_factory=tuple)

    def id(self) -> str:
        return self.name


@dataclass(frozen=True)
class LawNode:
    law_id: str
    regions: tuple

    def id(self) -> str:
        return self.law_id


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str
    weight: int


class Graph:
    """Immutable relationship graph. Query-only; construction via build()."""

    def __init__(self, regions, laws, governed_edges, cooccur_edges, shares_edges, law_to_regions, region_to_laws):
        self._regions = regions          # name -> RegionNode
        self._laws = laws                # law_id -> LawNode
        self._governed = governed_edges  # list[Edge]
        self._cooccur = cooccur_edges    # list[Edge] (undirected, one per pair)
        self._shares = shares_edges      # list[Edge] (undirected, one per pair)
        self._law_to_regions = law_to_regions
        self._region_to_laws = region_to_laws
        self._adj = defaultdict(dict)    # region adjacency for BFS/shares lookup

    # ---------------------------------------------------------------- queries
    def laws_for_region(self, name: str) -> tuple:
        _gate("connection_graph.laws_for_region")
        node = self._regions.get(name)
        return node.laws if node else ()

    def regions_for_law(self, law_id: str) -> tuple:
        _gate("connection_graph.regions_for_law")
        return self._law_to_regions.get(law_id, ())

    def neighbors(self, region: str, min_shared: int = 1) -> list:
        """[(other_region, shared_count)] sorted by shared_count descending."""
        _gate("connection_graph.neighbors")
        mine = set(self._region_to_laws.get(region, ()))
        out = []
        for other, laws in self._region_to_laws.items():
            if other == region:
                continue
            shared = len(mine & set(laws))
            if shared >= min_shared:
                out.append((other, shared))
        out.sort(key=lambda t: (-t[1], t[0]))
        return out

    def shared_laws(self, a: str, b: str) -> tuple:
        _gate("connection_graph.shared_laws")
        la = set(self._region_to_laws.get(a, ()))
        lb = set(self._region_to_laws.get(b, ()))
        return tuple(sorted(la & lb))

    def shared_jaccard(self, a: str, b: str) -> float:
        _gate("connection_graph.shared_jaccard")
        la = set(self._region_to_laws.get(a, ()))
        lb = set(self._region_to_laws.get(b, ()))
        union = la | lb
        return (len(la & lb) / len(union)) if union else 0.0

    def law_span(self, law_id: str) -> int:
        _gate("connection_graph.law_span")
        return len(self._law_to_regions.get(law_id, ()))

    def universal_laws(self) -> tuple:
        """Laws governing every region (span == region count)."""
        _gate("connection_graph.universal_laws")
        n = len(self._regions)
        return tuple(sorted(l for l, rs in self._law_to_regions.items() if len(rs) == n))

    def unique_signature(self, region: str) -> tuple:
        """The region's laws that appear in no other region (span == 1)."""
        _gate("connection_graph.unique_signature")
        return tuple(sorted(l for l in self._region_to_laws.get(region, ()) if self.law_span(l) == 1))

    def shortest_path(self, a: str, b: str) -> list:
        """BFS over region<->region shared-law edges. [] if disconnected."""
        _gate("connection_graph.shortest_path")
        if a not in self._regions or b not in self._regions:
            return []
        if a == b:
            return [a]
        prev = {a: None}
        dq = deque([a])
        while dq:
            cur = dq.popleft()
            for nxt in sorted(self._adj[cur]):
                if nxt not in prev:
                    prev[nxt] = cur
                    if nxt == b:
                        path = [b]
                        while prev[path[-1]] is not None:
                            path.append(prev[path[-1]])
                        return list(reversed(path))
                    dq.append(nxt)
        return []

    def no_lonely(self) -> list:
        """Node ids with zero edges. Must be [] on real data (the law made code)."""
        _gate("connection_graph.no_lonely")
        lonely = []
        for name, laws in self._region_to_laws.items():
            if not laws:
                lonely.append(name)
        for law_id, regions in self._law_to_regions.items():
            if not regions:
                lonely.append(law_id)
        return sorted(lonely)

    def snapshot(self) -> dict:
        """JSON-serializable view consumed by reflection.py (cross-module contract)."""
        _gate("connection_graph.snapshot")
        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "region_count": len(self._regions),
            "law_count": len(self._laws),
            "universal_laws": list(self._universal_laws_no_gate()),
            "regions": {
                name: {
                    "path": n.path,
                    "laws": list(n.laws),
                    "core_services": list(n.core_services),
                    "baseline": dict(n.baseline),
                }
                for name, n in sorted(self._regions.items())
            },
            "laws": {lid: list(rs) for lid, rs in sorted(self._law_to_regions.items())},
            "stats": {
                "law_references": sum(len(l) for l in self._region_to_laws.values()),
                "unique_laws": len(self._laws),
                "universal_backbone": list(self._universal_laws_no_gate()),
                "singleton_laws": sorted(l for l, rs in self._law_to_regions.items() if len(rs) == 1),
            },
        }

    def _universal_laws_no_gate(self) -> tuple:
        """Internal helper (no network gate) used inside snapshot to avoid double gating."""
        n = len(self._regions)
        return tuple(sorted(l for l, rs in self._law_to_regions.items() if len(rs) == n))

    # ------------------------------------------------------------- properties
    @property
    def region_count(self) -> int:
        return len(self._regions)

    @property
    def law_count(self) -> int:
        return len(self._laws)

    @property
    def governed_edges(self) -> list:
        return list(self._governed)

    @property
    def cooccur_edges(self) -> list:
        return list(self._cooccur)

    @property
    def shares_edges(self) -> list:
        return list(self._shares)

    @property
    def region_names(self) -> tuple:
        return tuple(sorted(self._regions))

    @property
    def law_ids(self) -> tuple:
        return tuple(sorted(self._laws))


def build(regions_dict: dict) -> Graph:
    """Build the graph from a REGIONS-style dict. Output-pure given input.

    The network precondition gates execution only; the graph is computed
    deterministically from regions_dict and nothing else.
    """
    _gate("connection_graph.build")
    regions = {}
    law_to_regions = defaultdict(set)
    region_to_laws = {}
    governed = []
    for name, rec in regions_dict.items():
        laws = tuple(dict.fromkeys(rec.get("laws", ())))  # dedupe, keep order
        services = tuple(rec.get("core_services", ()))
        baseline = tuple(sorted((rec.get("baseline") or {}).items()))
        regions[name] = RegionNode(name=name, path=rec.get("path", ""), laws=laws,
                                   core_services=services, baseline=baseline)
        region_to_laws[name] = laws
        for law_id in laws:
            law_to_regions[law_id].add(name)
            governed.append(Edge(src=name, dst=law_id, kind=GOVERNED_BY, weight=1))

    laws = {lid: LawNode(law_id=lid, regions=tuple(sorted(rs))) for lid, rs in law_to_regions.items()}
    law_to_regions = {lid: tuple(sorted(rs)) for lid, rs in law_to_regions.items()}

    cooccur = []
    counter = Counter()
    for laws_t in region_to_laws.values():
        for a, b in combinations(sorted(laws_t), 2):
            counter[(a, b)] += 1
    for (a, b), w in sorted(counter.items()):
        cooccur.append(Edge(src=a, dst=b, kind=CO_OCCURS, weight=w))

    shares = []
    adj = defaultdict(dict)
    for a, b in combinations(sorted(region_to_laws), 2):
        w = len(set(region_to_laws[a]) & set(region_to_laws[b]))
        if w > 0:
            shares.append(Edge(src=a, dst=b, kind=SHARES_LAWS, weight=w))
            adj[a][b] = w
            adj[b][a] = w

    g = Graph(regions, laws, governed, cooccur, shares, law_to_regions, region_to_laws)
    g._adj = adj
    return g


def load_real_regions() -> dict:
    """Import planet.regions (read-only; planet/ is never modified) and return REGIONS."""
    _gate("connection_graph.load_real_regions")
    import sys

    import os

    root = os.path.expanduser("~/workspace/content_team")
    if root not in sys.path:
        sys.path.insert(0, root)
    from planet.regions import REGIONS  # noqa: E402  (import declares govern() entries; read-only)

    return REGIONS
