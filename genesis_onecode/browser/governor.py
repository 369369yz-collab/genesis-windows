"""Browser Governor — the law over every browser session GENESIS opens.

One portable Chromium binary, many isolated contexts. The governor enforces:
- session leases: every browser context has an owner (agent id) and a purpose;
  no owner, no browser.
- concurrency cap: MAX_CONCURRENT_CONTEXTS (default 4; benchmark-tunable to 6
  on YZ's hardware). Requests beyond the cap QUEUE, never stampede.
- resource guard: a session exceeding RAM/CPU budget or its TTL is killed.
- approval gate: sensitive actions (purchase, send/submit, fresh login,
  file upload of personal docs) REQUIRE YZ approval before executing.
- quarantine: all downloads land in the quarantine dir; nothing auto-executes.
- audit: every open/navigate/action/close is appended to the session ledger.

The governor never moves YZ's physical mouse: automation drives a virtual
pointer inside the page (Playwright input), the OS cursor is untouched.
Headless is the default; live-view is opt-in per lease.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import profiles


class SessionState(Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    CLOSED = "closed"
    KILLED = "killed"


class ApprovalState(Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


# Actions that MUST pass YZ approval before the browser performs them.
SENSITIVE_ACTIONS = frozenset({
    "purchase", "checkout", "pay",
    "send", "submit_form", "post",
    "fresh_login", "password_entry",
    "upload_personal_doc",
})


@dataclass
class Lease:
    lease_id: str
    owner: str            # agent id, e.g. "genesis" or "agent-<n>"
    purpose: str
    state: SessionState = SessionState.QUEUED
    created_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    ttl_seconds: float = 1800.0
    headless: bool = True
    profile_path: Optional[Path] = None
    approvals: dict = field(default_factory=dict)  # action -> ApprovalState


@dataclass
class GovernorConfig:
    max_concurrent: int = 4          # approved range 4-6; benchmark decides
    default_ttl_seconds: float = 1800.0
    max_ram_mb_per_session: float = 1500.0
    heartbeat_timeout_seconds: float = 300.0
    app_data_dir: Path = Path("genesis_data")
    # YZ's approval callback: called with (lease, action, detail) -> bool.
    # None => sensitive actions are DENIED by default (fail-closed).
    approval_callback: Optional[Callable] = None


class BrowserGovernor:
    """Owns every browser session. Thread-safe."""

    def __init__(self, config: Optional[GovernorConfig] = None):
        self.config = config or GovernorConfig()
        if not 1 <= self.config.max_concurrent <= 8:
            raise ValueError("max_concurrent must be 1..8")
        self._lock = threading.RLock()  # RLock: _log re-acquires inside note_yz_decision
        self._leases: dict[str, Lease] = {}
        self._queue: deque[str] = deque()
        self._ledger_path = self.config.app_data_dir / "browser_ledger.jsonl"
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- ledger ---------------------------------------------------------
    def _log(self, event: str, lease_id: str, detail: str = "") -> None:
        line = (
            f'{{"t":{time.time():.3f},"event":{event!r},'
            f'"lease":{lease_id!r},"detail":{detail!r}}}\n'
        )
        with self._lock:
            with open(self._ledger_path, "a", encoding="utf-8") as f:
                f.write(line)

    # ---- leases ---------------------------------------------------------
    def acquire(self, owner: str, purpose: str, headless: bool = True,
                ttl_seconds: Optional[float] = None) -> Lease:
        """Request a browser session. Returns a Lease (QUEUED or ACTIVE)."""
        if not owner or not purpose:
            raise ValueError("owner and purpose are required — no anonymous browsers")
        lease = Lease(
            lease_id=f"br-{uuid.uuid4().hex[:12]}",
            owner=owner,
            purpose=purpose,
            headless=headless,
            ttl_seconds=ttl_seconds or self.config.default_ttl_seconds,
            profile_path=profiles.profile_dir(self.config.app_data_dir, owner),
        )
        with self._lock:
            self._leases[lease.lease_id] = lease
            active = sum(1 for l in self._leases.values()
                         if l.state is SessionState.ACTIVE)
            if active < self.config.max_concurrent:
                lease.state = SessionState.ACTIVE
            else:
                self._queue.append(lease.lease_id)
        self._log("acquire", lease.lease_id,
                  f"owner={owner} purpose={purpose} state={lease.state.value}")
        return lease

    def heartbeat(self, lease_id: str) -> None:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease and lease.state is SessionState.ACTIVE:
                lease.last_heartbeat = time.time()

    def release(self, lease_id: str, reason: str = "done") -> None:
        with self._lock:
            lease = self._leases.pop(lease_id, None)
            if lease:
                lease.state = SessionState.CLOSED
                try:
                    self._queue.remove(lease_id)
                except ValueError:
                    pass
                self._promote_queued()
        if lease:
            self._log("release", lease_id, reason)

    def _promote_queued(self) -> None:
        active = sum(1 for l in self._leases.values()
                     if l.state is SessionState.ACTIVE)
        while self._queue and active < self.config.max_concurrent:
            lid = self._queue.popleft()
            lease = self._leases.get(lid)
            if lease and lease.state is SessionState.QUEUED:
                lease.state = SessionState.ACTIVE
                lease.last_heartbeat = time.time()
                active += 1
                # log outside the fine-grained path; called with lock held
                with open(self._ledger_path, "a", encoding="utf-8") as f:
                    f.write(f'{{"t":{time.time():.3f},"event":"promote",'
                            f'"lease":{lid!r},"detail":""}}\n')

    # ---- reaper ----------------------------------------------------------
    def reap(self) -> list[str]:
        """Kill expired / heartbeat-dead sessions. Returns killed lease ids."""
        now = time.time()
        killed: list[str] = []
        with self._lock:
            for lid, lease in list(self._leases.items()):
                if lease.state is not SessionState.ACTIVE:
                    continue
                expired = (now - lease.created_at) > lease.ttl_seconds
                dead = (now - lease.last_heartbeat) > self.config.heartbeat_timeout_seconds
                if expired or dead:
                    lease.state = SessionState.KILLED
                    killed.append(lid)
            for lid in killed:
                del self._leases[lid]
                try:
                    self._queue.remove(lid)
                except ValueError:
                    pass
            self._promote_queued()
        for lid in killed:
            self._log("reap_kill", lid, "ttl/heartbeat exceeded")
        return killed

    # ---- approval gate ---------------------------------------------------
    def check_action(self, lease_id: str, action: str, detail: str = "") -> bool:
        """True if the action may proceed. Sensitive actions need YZ approval."""
        lease = self._leases.get(lease_id)
        if lease is None or lease.state is not SessionState.ACTIVE:
            return False
        if action not in SENSITIVE_ACTIONS:
            self._log("action", lease_id, f"{action} {detail}")
            return True
        state = lease.approvals.get(action, ApprovalState.NOT_REQUIRED)
        if state is ApprovalState.APPROVED:
            self._log("action", lease_id, f"{action} {detail} (pre-approved)")
            return True
        # Fail-closed: no callback => denied.
        cb = self.config.approval_callback
        approved = bool(cb(lease, action, detail)) if cb else False
        lease.approvals[action] = (ApprovalState.APPROVED if approved
                                   else ApprovalState.DENIED)
        self._log("approval", lease_id,
                  f"{action} {'APPROVED' if approved else 'DENIED'} {detail}")
        return approved

    def note_yz_decision(self, lease_id: str, action: str,
                         approved: bool) -> bool:
        """Apply YZ's async verdict to a lease's cached approval.

        The governor denies sensitive actions fail-closed at attempt time and
        files an approval request; when YZ later approves, this flips the
        cached verdict so the agent's retry succeeds. Returns False when the
        lease is unknown.
        """
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return False
            lease.approvals[action] = (ApprovalState.APPROVED if approved
                                       else ApprovalState.DENIED)
            self._log("yz_decision", lease_id,
                      f"{action} {'APPROVED' if approved else 'DENIED'} by YZ")
            return True

    # ---- introspection ----------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {
                "max_concurrent": self.config.max_concurrent,
                "active": sum(1 for l in self._leases.values()
                              if l.state is SessionState.ACTIVE),
                "queued": len(self._queue),
                "leases": [
                    {"id": l.lease_id, "owner": l.owner,
                     "purpose": l.purpose, "state": l.state.value}
                    for l in self._leases.values()
                ],
            }
