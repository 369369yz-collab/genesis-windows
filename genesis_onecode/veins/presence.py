"""presence.py — signed heartbeats + presence registry (NEXUS §3), as code.

Formula §3 contract:
  - every node sends a SIGNED heartbeat every 30s (HEARTBEAT_INTERVAL_S)
  - a node is marked OFFLINE after 120s without a heartbeat (OFFLINE_AFTER_S)
  - presence registry: in-memory + JSON snapshot

Adapter, not rewrite: envelope construction, HMAC signing, replay semantics
and NodeRecord come from genesis_final.nexus.proto; the relay in
genesis_final/nexus/relay.py stays the live reference. This module is the
SYNC, clock-injectable interface the local core uses — the 30s sender loop
and the WebSocket transport arrive with the live fabric (later per YZ
order), so a heartbeat is built with build_heartbeat() and applied with
apply_heartbeat(); the loop itself is a fabric concern, not coded here.

Security (formula §3): loopback-only binds, per-boot token auth. The boot
token is minted per boot (new_boot_token) and NEVER persisted — snapshot
files carry node records only, never the token. CI asserts no wildcard
bind: this module opens no sockets at all (see tests/test_veins.py).

Stdlib only, zero spend.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from .proto import (HEARTBEAT_INTERVAL_S, NEXUS_VERSION,
                    NodeRecord, OFFLINE, OFFLINE_AFTER_S,
                    ONLINE, atomic_write_json, envelope_valid, make_envelope,
                    node_secret, read_json_tolerant,
                    sign_envelope, verify_envelope)

Clock = Callable[[], float]


class PresenceRegistry:
    """Signed-heartbeat presence registry: in-memory + JSON snapshot.

    boot_token: per-boot token (minted by the relay owner); used to derive
        per-node HMAC keys via node_secret(boot_token, node_id). Never
        persisted to disk.
    clock: injectable time source (seconds, float). Defaults to time.time.
    offline_after: seconds without heartbeat before OFFLINE (120.0, §3).
    """

    def __init__(self, boot_token: str,
                 offline_after: float = OFFLINE_AFTER_S,
                 heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
                 clock: Optional[Clock] = None):
        if not boot_token:
            raise ValueError("boot_token is required (per-boot token auth)")
        self.boot_token = boot_token
        self.offline_after = offline_after
        self.heartbeat_interval = heartbeat_interval
        self.clock: Clock = clock or time.time
        self._nodes: dict[str, NodeRecord] = {}
        self._lock = threading.Lock()
        self._seq = 0

    # ------------------------------------------------------- node (sender)
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def build_heartbeat(self, node_id: str, services: list,
                        path: str = "primary", seq: int | None = None) -> dict:
        """Build + sign a heartbeat envelope for node_id.

        Same wire body as proto.make_heartbeat; seq is injectable for
        deterministic tests (defaults to a local monotonic counter).
        """
        if path not in ("primary", "fallback"):
            raise ValueError("unknown path: %r" % path)
        body = {"services": list(services), "path": path,
                "hb_interval_s": HEARTBEAT_INTERVAL_S,
                "offline_after_s": OFFLINE_AFTER_S}
        env = make_envelope("heartbeat", node_id, body,
                            seq=seq if seq is not None else self._next_seq())
        return sign_envelope(env, node_secret(self.boot_token, node_id))

    # ------------------------------------------------------- relay (apply)
    def register(self, node_id: str, role: str = "service",
                 services: list | None = None, path: str = "primary"
                 ) -> NodeRecord:
        """Register a node (hello accepted). Overwrites any prior record."""
        rec = NodeRecord(node_id=node_id, role=role,
                         services=list(services or []), path=path,
                         last_seen=self.clock(), status=ONLINE)
        with self._lock:
            self._nodes[node_id] = rec
        return rec

    def remove(self, node_id: str) -> None:
        with self._lock:
            self._nodes.pop(node_id, None)

    def get(self, node_id: str) -> Optional[NodeRecord]:
        with self._lock:
            return self._nodes.get(node_id)

    def apply_heartbeat(self, envelope: dict) -> Optional[NodeRecord]:
        """Verify a signed heartbeat and refresh the node's record.

        Returns the updated NodeRecord, or None if the envelope is invalid
        (bad structure, bad signature, wrong kind, unknown node, or a
        replayed/old seq — replayed heartbeats are dropped, never applied).
        """
        ok, _why = envelope_valid(envelope)
        if not ok or envelope.get("kind") != "heartbeat":
            return None
        node_id = envelope.get("from")
        if not isinstance(node_id, str) or not node_id:
            return None
        if not verify_envelope(envelope, node_secret(self.boot_token,
                                                     node_id)):
            return None
        with self._lock:
            rec = self._nodes.get(node_id)
            if rec is None:
                return None  # heartbeat before hello: unknown node
            seq = envelope.get("seq")
            if not isinstance(seq, (int, float)) or seq <= rec.last_seq:
                return None  # replay guard
            rec.last_seq = seq
            body = envelope.get("body") or {}
            services = body.get("services")
            if isinstance(services, list):
                rec.services = [str(s) for s in services]
            path = body.get("path")
            if path in ("primary", "fallback"):
                rec.path = path
            rec.last_seen = self.clock()
            rec.status = ONLINE
            return rec

    # ---------------------------------------------------------------- sweep
    def sweep(self) -> list[str]:
        """Mark nodes OFFLINE after `offline_after` s without heartbeat.

        Returns the ids flipped to OFFLINE by THIS call (mathematical
        precision: only stale-and-not-already-OFFLINE nodes are listed).
        """
        now = self.clock()
        flipped: list[str] = []
        with self._lock:
            for nid, rec in self._nodes.items():
                if rec.status != OFFLINE \
                        and (now - rec.last_seen) >= self.offline_after:
                    rec.status = OFFLINE
                    flipped.append(nid)
        return flipped

    def live_nodes(self) -> list[NodeRecord]:
        now = self.clock()
        with self._lock:
            return [r for r in self._nodes.values()
                    if r.status != OFFLINE
                    and (now - r.last_seen) < self.offline_after]

    # --------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        """Presence snapshot (in-memory). Same shape as the relay's."""
        now = self.clock()
        with self._lock:
            nodes = {nid: {**asdict(rec),
                           "last_seen_age_s": round(now - rec.last_seen, 1)}
                     for nid, rec in self._nodes.items()}
        return {"nexus": NEXUS_VERSION, "ts": now, "nodes": nodes}

    def save_snapshot(self, path: str | Path) -> Path:
        """Persist the registry to a JSON snapshot (atomic, unique tmp).

        The snapshot carries node records ONLY — never the boot token.
        last_seen is stored in this registry's clock domain; a registry
        loaded with a different clock must sweep() on load (load_snapshot
        does this automatically).
        """
        with self._lock:
            records = {nid: asdict(rec) for nid, rec in self._nodes.items()}
        return atomic_write_json(path, {
            "nexus": NEXUS_VERSION,
            "saved_clock_s": self.clock(),
            "offline_after_s": self.offline_after,
            "nodes": records,
        })

    @classmethod
    def load_snapshot(cls, path: str | Path, boot_token: str,
                      clock: Optional[Clock] = None) -> "PresenceRegistry":
        """Restore a registry from a JSON snapshot; sweep() on load so any
        record stale in this clock domain reads OFFLINE honestly."""
        data = read_json_tolerant(path, default=None)
        if not isinstance(data, dict) or not isinstance(
                data.get("nodes"), dict):
            raise ValueError("not a presence snapshot: %s" % path)
        reg = cls(boot_token,
                  offline_after=float(data.get("offline_after_s",
                                               OFFLINE_AFTER_S)),
                  clock=clock)
        nodes = data["nodes"]
        with reg._lock:
            for nid, rec in nodes.items():
                if not isinstance(rec, dict):
                    continue
                try:
                    reg._nodes[nid] = NodeRecord(
                        node_id=str(rec.get("node_id", nid)),
                        role=str(rec.get("role", "service")),
                        services=list(rec.get("services") or []),
                        path=str(rec.get("path", "primary")),
                        last_seq=int(rec.get("last_seq", -1)),
                        last_seen=float(rec.get("last_seen", 0.0)),
                        status=str(rec.get("status", OFFLINE)),
                    )
                except (TypeError, ValueError):
                    continue  # malformed record: skip, never crash the load
        reg._seq = max([r.last_seq for r in reg._nodes.values()] + [0])
        reg.sweep()  # honest: stale records read OFFLINE in this clock domain
        return reg

    # ---------------------------------------------------------------- misc
    def node_ids(self) -> list[str]:
        with self._lock:
            return list(self._nodes.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._nodes)
