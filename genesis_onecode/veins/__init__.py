"""veins — NEXUS protocol interfaces for the GENESIS one-code build (formula §3).

Interfaces only per YZ order (live TLS-over-Tailscale fabric comes later):
  - guarded_call: GuardedCall / CircuitBreaker — the §3 call contract
  - presence: PresenceRegistry — signed heartbeats, 30s/120s, JSON snapshots
  - degraded_cache: DegradedCache — last-known-good state, honest staleness
  - proto: adapter namespace over genesis_final.nexus.proto

Technical English. Stdlib only, zero spend.
"""
from .proto import (  # noqa: F401
    CIRCUIT_OPEN_S,
    CIRCUIT_THRESHOLD,
    DEGRADED,
    HEARTBEAT_EVERY_S,
    LOOPBACK_HOST,
    NEXUS_VERSION,
    OFFLINE,
    OFFLINE_AFTER_S,
    ONLINE,
)
from .guarded_call import CircuitBreaker, GuardedCall, DEGRADED_KEYS  # noqa: F401
from .presence import PresenceRegistry  # noqa: F401
from .degraded_cache import DegradedCache  # noqa: F401

__all__ = [
    "CircuitBreaker", "GuardedCall", "DEGRADED_KEYS",
    "PresenceRegistry", "DegradedCache",
    "ONLINE", "DEGRADED", "OFFLINE", "LOOPBACK_HOST", "NEXUS_VERSION",
    "HEARTBEAT_EVERY_S", "OFFLINE_AFTER_S",
    "CIRCUIT_THRESHOLD", "CIRCUIT_OPEN_S",
]
