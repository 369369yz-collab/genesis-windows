"""nexus — NEXUS world Stage 5 package (Builder A share).

Modules owned by Builder A (seat temp-nexus-builder-a-1012):
    ledger.py           — shared append-only hash-chained records
    connection_graph.py — the relationship web, DISCOVERED from planet/regions.py
    nexus_laws.py       — NEXUS-LAW-001..005 registry + pure check functions

Builders B/C inherit this record as contract (see HUDDLE.md):
    - Every public entry point calls network_precondition(...) FIRST.
    - 100% technical English in code and comments.
    - Cross-module reads ONLY via documented query functions, never privates.
    - Fail-closed gates everywhere; CODEX.json never touched.

Fail-closed exceptions shared across the package (defined once, here):
    LedgerBroken, ThresholdRejected, WombNotReady, UnknownEntity,
    GateFailed, CallRejected, NotAuthorized.
"""

AGENT_SEAT = "temp-nexus-builder-a-1012"
PACKAGE_VERSION = "5.0.0"


class LedgerBroken(RuntimeError):
    """A ledger chain failed verification or is corrupt. Fail-closed."""


class ThresholdRejected(RuntimeError):
    """Entry rejected at the threshold. Fail-closed."""


class WombNotReady(RuntimeError):
    """Exit requested before gestation readiness. Fail-closed."""


class UnknownEntity(RuntimeError):
    """The mirror never invents a face. Fail-closed."""


class GateFailed(RuntimeError):
    """A gate evaluation failed. Fail-closed."""


class CallRejected(RuntimeError):
    """A call answer was rejected. Fail-closed."""


class NotAuthorized(RuntimeError):
    """The caller holds no authority for this action. Fail-closed."""


from nexus.ledger import append, verify_chain  # noqa: E402,F401

__all__ = [
    "AGENT_SEAT",
    "PACKAGE_VERSION",
    "LedgerBroken",
    "ThresholdRejected",
    "WombNotReady",
    "UnknownEntity",
    "GateFailed",
    "CallRejected",
    "NotAuthorized",
    "append",
    "verify_chain",
]
