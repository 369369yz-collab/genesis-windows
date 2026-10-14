"""guarded_call.py — the NEXUS §3 call contract, as a code interface.

Call contract (formula §3, authoritative):
  - guarded_call(service, payload, timeout=3s)
  - states ONLINE / DEGRADED / OFFLINE
  - circuit breaker: 5 consecutive failures -> OPEN for 15 minutes
  - failed remote calls return {"ok": False, "degraded": True} — NEVER invented data
  - every extended-mind response carries source: extended-mind

Adapter, not rewrite: degraded shapes and tagging come from
genesis_final.nexus.proto (degraded_result/tag_advisory); the breaker state
machine here mirrors proto.LinkState semantics but takes an INJECTABLE CLOCK
so the 15-minute window is testable without real sleeping.

The live fabric (TLS-over-Tailscale WebSocket transport) comes LATER per
YZ order. This module takes a `transport` callable
    transport(service: str, payload: dict, timeout_s: float) -> dict
so the wire layer can be swapped in without touching the contract.
transport=None means "no network path available" -> OFFLINE (formula W2:
the local core keeps full function when cut; the caller falls back to
degraded_cache).

Sync-only by design: no asyncio, no pytest-asyncio dependency.

Stdlib only, zero spend.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .proto import (CIRCUIT_OPEN_S, CIRCUIT_THRESHOLD, DEGRADED, OFFLINE,
                    ONLINE, tag_advisory)

Clock = Callable[[], float]
Transport = Callable[[str, dict, float], dict]

DEGRADED_KEYS = frozenset(
    {"ok", "degraded", "state", "circuit_open", "reason", "source"})


class CircuitBreaker:
    """5 consecutive failures -> OPEN for 15 minutes (injectable clock).

    - Closed (state ONLINE): calls pass through.
    - After exactly `threshold` consecutive failures: OPEN (state DEGRADED).
      While open, calls short-circuit — the transport is not even attempted.
    - After `open_seconds` elapse on the clock: exactly ONE half-open probe
      is allowed. Probe success closes the breaker (failures reset to 0);
      probe failure re-opens it for a fresh window.
    - Any success resets consecutive_failures to 0 and closes the breaker.
    """

    def __init__(self, threshold: int = CIRCUIT_THRESHOLD,
                 open_seconds: float = CIRCUIT_OPEN_S,
                 clock: Optional[Clock] = None):
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if open_seconds <= 0:
            raise ValueError("open_seconds must be > 0")
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.clock: Clock = clock or time.monotonic
        self.consecutive_failures = 0
        self.open_until = 0.0  # 0.0 = closed
        self.state = ONLINE

    def now(self) -> float:
        return self.clock()

    @property
    def is_open(self) -> bool:
        """True while the breaker is open: short-circuit, do not attempt."""
        return self.now() < self.open_until

    def allow_probe(self) -> bool:
        """After the open window expires, exactly one probe may pass."""
        now = self.now()
        if self.open_until > 0.0 and now >= self.open_until:
            self.open_until = 0.0  # consume: one probe only
            return True
        return False

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.state = ONLINE

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.state = DEGRADED
            self.open_until = self.now() + self.open_seconds


class GuardedCall:
    """The guarded_call(service, payload, timeout=3s) contract.

    On ANY failure — timeout, transport exception, remote degraded reply,
    open circuit, no network — returns {"ok": False, "degraded": True, ...}
    with state in {ONLINE, DEGRADED, OFFLINE} and source: extended-mind.
    It NEVER invents data: a failed call carries no 'result'/'data' payload.
    """

    def __init__(self, breaker: Optional[CircuitBreaker] = None,
                 clock: Optional[Clock] = None):
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self.clock: Clock = clock or time.monotonic

    # ------------------------------------------------------------ contract
    def call(self, service: str, payload: dict, timeout_s: float = 3.0,
             transport: Optional[Transport] = None) -> dict:
        """guarded_call(service, payload, timeout=3s)."""
        if not isinstance(service, str) or not service:
            raise ValueError("service must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")

        # No network path at all -> OFFLINE, honestly. (Formula W2.)
        if transport is None:
            self.breaker.state = OFFLINE
            return self._degraded("no network path available", OFFLINE)

        # Open circuit -> short-circuit, transport NOT attempted.
        if self.breaker.is_open:
            return self._degraded("circuit breaker open", DEGRADED,
                                  circuit_open=True)

        # Window expired -> this call is the single half-open probe.
        if self.breaker.allow_probe():
            return self._probe(service, payload, timeout_s, transport)

        # Closed -> normal guarded attempt.
        return self._attempt(service, payload, timeout_s, transport)

    __call__ = call

    # ------------------------------------------------------------ internals
    def _degraded(self, reason: str, state: str,
                  circuit_open: bool | None = None) -> dict:
        body = {"ok": False, "degraded": True, "state": state,
                "reason": reason,
                "circuit_open": self.breaker.is_open
                if circuit_open is None else circuit_open,
                "source": "extended-mind"}
        return body

    def _probe(self, service: str, payload: dict, timeout_s: float,
               transport: Transport) -> dict:
        ok, value = _invoke(transport, service, payload, timeout_s)
        if not ok:
            # Probe failed -> re-open for a fresh window.
            self.breaker.record_failure()
            reason = value if isinstance(value, str) else "half-open probe failed"
            return self._degraded(reason, DEGRADED, circuit_open=True)
        return self._handle_result(value)

    def _attempt(self, service: str, payload: dict, timeout_s: float,
                 transport: Transport) -> dict:
        ok, value = _invoke(transport, service, payload, timeout_s)
        if not ok:
            self.breaker.record_failure()
            reason = value if isinstance(value, str) else "transport failure"
            return self._degraded(reason, self.breaker.state)
        return self._handle_result(value)

    def _handle_result(self, value) -> dict:
        # A remote-side degraded reply counts as a failure of THIS call.
        if isinstance(value, dict) and value.get("ok") is False \
                and value.get("degraded"):
            self.breaker.record_failure()
            reason = str(value.get("reason", "remote degraded"))
            out = self._degraded(reason, self.breaker.state)
            if "circuit_open" not in out:
                out["circuit_open"] = self.breaker.is_open
            return out
        self.breaker.record_success()
        if isinstance(value, dict):
            # Advisory tagging: every extended-mind response carries
            # source: extended-mind (tag_advisory never overwrites an
            # existing source, e.g. a local_core provider).
            return tag_advisory(dict(value))
        # Non-dict success payloads are wrapped, honestly labeled.
        return tag_advisory({"ok": True, "result": value})


def _invoke(transport: Transport, service: str, payload: dict,
            timeout_s: float):
    """Run transport in a daemon thread; enforce the timeout.

    Returns (True, value) on success, (False, reason_str) on timeout or
    exception. A timed-out thread is abandoned as a daemon (it cannot hold
    the process), never joined past the deadline.
    """
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = transport(service, payload, timeout_s)
        except Exception as e:  # noqa: BLE001 - transport errors are degraded, not raised
            box["error"] = "%s: %s" % (type(e).__name__, e)

    t = threading.Thread(target=run, daemon=True, name="guarded-call-invoke")
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return False, "guarded_call timeout after %.2fs" % timeout_s
    if "error" in box:
        return False, "transport: %s" % box["error"]
    return True, box.get("value")
