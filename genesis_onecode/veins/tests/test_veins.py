"""test_veins.py — unit tests for the veins/ NEXUS §3 interfaces.

SYNC ONLY, with injectable clocks — no asyncio, no pytest-asyncio, no real
sleeping through 15-minute windows (the coordinator audit flagged that the
legacy genesis_final/nexus/test_relay.py fails 7/12 under pytest for exactly
that reason; this suite does not inherit it).

Run:  python3 test_veins.py        (stdlib only, exit 0 = all green)
   or pytest test_veins.py          (when pytest is available)

Technical English. Zero spend.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_VEINS = _THIS_DIR.parent
_WORKSPACE = _VEINS.parent
for _p in (str(_WORKSPACE), str(_VEINS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from veins.guarded_call import CircuitBreaker, DEGRADED_KEYS, GuardedCall  # noqa: E402
from veins.presence import PresenceRegistry  # noqa: E402
from veins.degraded_cache import DegradedCache  # noqa: E402
from veins import proto as vproto  # noqa: E402
from genesis_final.nexus.cache import RelayCache  # noqa: E402

# ------------------------------------------------------------------- helpers
BOOT = "boot-token-for-tests-only"


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class BoomTransport:
    """Transport that always fails; counts how often it was ATTEMPTED."""

    def __init__(self, exc=RuntimeError("boom")):
        self.exc = exc
        self.attempts = 0

    def __call__(self, service, payload, timeout_s):
        self.attempts += 1
        raise self.exc


class ScriptedTransport:
    """Fails `fails` times, then returns `result`."""

    def __init__(self, fails: int, result: dict):
        self.fails = fails
        self.result = result
        self.attempts = 0

    def __call__(self, service, payload, timeout_s):
        self.attempts += 1
        if self.attempts <= self.fails:
            raise RuntimeError("scripted failure %d" % self.attempts)
        return dict(self.result)


def _tmpfile(suffix=".json") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix)
    import os
    os.close(fd)
    Path(name).unlink()
    return Path(name)


def _assert_degraded_shape(resp: dict, state: str) -> None:
    assert isinstance(resp, dict), "response must be a dict"
    assert resp.get("ok") is False, "ok must be False: %r" % resp
    assert resp.get("degraded") is True, "degraded must be True: %r" % resp
    assert resp.get("state") == state, "state must be %r: %r" % (state, resp)
    assert resp.get("source") == "extended-mind", \
        "every extended-mind response carries source: extended-mind"
    # NEVER invented data: a failed call carries no result/data payload.
    assert set(resp.keys()) <= set(DEGRADED_KEYS), \
        "failed call leaked keys: %r" % (set(resp) - set(DEGRADED_KEYS),)
    assert "result" not in resp and "data" not in resp, \
        "failed call invented data: %r" % resp


# ------------------------------------------------------------- guarded_call
def test_breaker_opens_after_exactly_five_failures():
    clock = FakeClock()
    breaker = CircuitBreaker(clock=clock)
    gc = GuardedCall(breaker=breaker)
    boom = BoomTransport()

    for i in range(4):  # failures 1..4: still closed, every call attempted
        resp = gc.call("svc", {"i": i}, timeout_s=1.0, transport=boom)
        assert not breaker.is_open, "breaker opened too early at %d" % (i + 1)
        assert breaker.state == "ONLINE"
        assert boom.attempts == i + 1, "call %d was not attempted" % (i + 1)
        _assert_degraded_shape(resp, "ONLINE")

    resp = gc.call("svc", {}, timeout_s=1.0, transport=boom)  # failure #5
    assert breaker.consecutive_failures == 5
    assert breaker.is_open, "breaker did not open at exactly 5 failures"
    assert breaker.state == "DEGRADED"
    assert boom.attempts == 5
    _assert_degraded_shape(resp, "DEGRADED")
    assert resp["circuit_open"] is True

    resp = gc.call("svc", {}, timeout_s=1.0, transport=boom)  # short-circuit
    assert boom.attempts == 5, "transport attempted while circuit open"
    _assert_degraded_shape(resp, "DEGRADED")


def test_breaker_closes_after_15_minutes():
    clock = FakeClock()
    gc = GuardedCall(breaker=CircuitBreaker(clock=clock))
    boom = BoomTransport()
    for _ in range(5):
        gc.call("svc", {}, timeout_s=1.0, transport=boom)
    assert gc.breaker.is_open

    # 899 s later: still open (window is 900 s).
    clock.advance(899.0)
    resp = gc.call("svc", {}, timeout_s=1.0, transport=boom)
    assert boom.attempts == 5, "window expired early"
    _assert_degraded_shape(resp, "DEGRADED")

    # 15 min + 1 s: window expired -> the single half-open probe is allowed.
    clock.advance(2.0)
    ok_transport = ScriptedTransport(0, {"answer": 42})
    resp = gc.call("svc", {}, timeout_s=1.0, transport=ok_transport)
    assert ok_transport.attempts == 1, "probe was not attempted"
    assert resp.get("answer") == 42, "probe result lost: %r" % resp
    assert resp.get("source") == "extended-mind"
    assert gc.breaker.state == "ONLINE"
    assert gc.breaker.consecutive_failures == 0
    assert not gc.breaker.is_open

    # Normal calls pass through again after close.
    resp = gc.call("svc", {}, timeout_s=1.0, transport=ok_transport)
    assert ok_transport.attempts == 2
    assert resp.get("answer") == 42


def test_probe_failure_reopens_breaker():
    clock = FakeClock()
    gc = GuardedCall(breaker=CircuitBreaker(clock=clock))
    boom = BoomTransport()
    for _ in range(5):
        gc.call("svc", {}, timeout_s=1.0, transport=boom)
    clock.advance(901.0)
    resp = gc.call("svc", {}, timeout_s=1.0, transport=boom)  # probe fails
    assert boom.attempts == 6, "probe was not attempted"
    assert gc.breaker.is_open, "failed probe did not re-open the breaker"
    assert gc.breaker.consecutive_failures == 6
    _assert_degraded_shape(resp, "DEGRADED")

    # After another full window a successful probe closes it.
    clock.advance(901.0)
    ok_transport = ScriptedTransport(0, {"answer": 7})
    resp = gc.call("svc", {}, timeout_s=1.0, transport=ok_transport)
    assert resp.get("answer") == 7
    assert gc.breaker.state == "ONLINE"
    assert not gc.breaker.is_open


def test_success_resets_failure_count():
    clock = FakeClock()
    gc = GuardedCall(breaker=CircuitBreaker(clock=clock))

    pattern = ["fail"] * 4 + ["ok"] + ["fail"] * 4

    class PatternTransport:
        def __init__(self):
            self.attempts = 0

        def __call__(self, service, payload, timeout_s):
            i = self.attempts
            self.attempts += 1
            if pattern[i] == "fail":
                raise RuntimeError("pattern fail")
            return {"answer": i}

    t = PatternTransport()
    for _ in range(4):   # 4 failures
        gc.call("svc", {}, timeout_s=1.0, transport=t)
    assert not gc.breaker.is_open
    gc.call("svc", {}, timeout_s=1.0, transport=t)  # 1 success -> reset
    assert gc.breaker.consecutive_failures == 0
    for _ in range(4):   # 4 more failures
        gc.call("svc", {}, timeout_s=1.0, transport=t)
    assert not gc.breaker.is_open, \
        "breaker opened despite a success resetting the count"
    assert gc.breaker.consecutive_failures == 4
    assert t.attempts == 9, "not every call was attempted"


def test_timeout_returns_degraded():
    gc = GuardedCall()
    gate = threading.Event()

    def hanging(service, payload, timeout_s):
        gate.wait(0.4)  # blocks longer than the guarded timeout
        return {"answer": "too late"}

    t0 = time.monotonic()
    resp = gc.call("svc", {}, timeout_s=0.05, transport=hanging)
    elapsed = time.monotonic() - t0
    _assert_degraded_shape(resp, "ONLINE")
    assert "timeout" in resp["reason"], resp["reason"]
    assert elapsed < 0.25, "timeout was not enforced: %.3fs" % elapsed
    gate.set()  # release the abandoned daemon thread


def test_transport_exception_returns_degraded():
    gc = GuardedCall()
    resp = gc.call("svc", {}, timeout_s=1.0,
                   transport=BoomTransport(ValueError("kaput")))
    _assert_degraded_shape(resp, "ONLINE")
    assert "kaput" in resp["reason"]


def test_remote_degraded_reply_counts_as_failure():
    clock = FakeClock()
    gc = GuardedCall(breaker=CircuitBreaker(clock=clock))

    def remote_degraded(service, payload, timeout_s):
        return {"ok": False, "degraded": True, "reason": "provider down",
                "source": "extended-mind"}

    for i in range(5):
        resp = gc.call("svc", {}, timeout_s=1.0, transport=remote_degraded)
        _assert_degraded_shape(resp, "DEGRADED" if i == 4 else "ONLINE")
    assert gc.breaker.is_open
    assert gc.breaker.consecutive_failures == 5


def test_failed_call_never_returns_invented_data():
    gc = GuardedCall()
    for transport in (BoomTransport(), None):
        resp = gc.call("svc", {"q": "x"}, timeout_s=0.5, transport=transport)
        _assert_degraded_shape(resp, "OFFLINE" if transport is None else "ONLINE")


def test_no_transport_means_offline():
    gc = GuardedCall()
    resp = gc.call("svc", {}, timeout_s=3.0, transport=None)
    _assert_degraded_shape(resp, "OFFLINE")
    assert "no network path" in resp["reason"]


def test_successful_call_is_tagged_extended_mind():
    gc = GuardedCall()
    resp = gc.call("svc", {"q": 1}, timeout_s=1.0,
                   transport=ScriptedTransport(0, {"answer": 42}))
    assert resp.get("answer") == 42, "success payload altered: %r" % resp
    assert resp.get("source") == "extended-mind"
    assert gc.breaker.state == "ONLINE"


def test_input_validation():
    gc = GuardedCall()
    for bad in ("", None, 123):
        try:
            gc.call(bad, {}, timeout_s=1.0, transport=ScriptedTransport(0, {}))
        except ValueError:
            pass
        else:
            raise AssertionError("bad service accepted: %r" % (bad,))
    try:
        gc.call("svc", [], timeout_s=1.0, transport=ScriptedTransport(0, {}))
    except ValueError:
        pass
    else:
        raise AssertionError("non-dict payload accepted")


# ----------------------------------------------------------------- presence
def test_heartbeat_marks_node_offline_after_120s():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    reg.register("node-a", services=["svc"])

    clock.advance(119.0)
    assert reg.sweep() == [], "node flipped before 120 s"
    assert reg.get("node-a").status == "ONLINE"

    clock.advance(1.0)  # age == 120 s
    flipped = reg.sweep()
    assert flipped == ["node-a"], "expected exactly one flip: %r" % flipped
    assert reg.get("node-a").status == "OFFLINE"

    assert reg.sweep() == [], "already-OFFLINE node re-listed"


def test_heartbeat_refresh_keeps_node_online():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    reg.register("node-a", services=["svc"])

    clock.advance(90.0)
    hb = reg.build_heartbeat("node-a", ["svc"])
    applied = reg.apply_heartbeat(hb)
    assert applied is not None and applied.status == "ONLINE"

    clock.advance(100.0)  # 190 s since register, 100 s since heartbeat
    assert reg.sweep() == [], "freshly-heartbeated node flipped"

    clock.advance(21.0)   # 121 s since heartbeat
    assert reg.sweep() == ["node-a"]


def test_signed_heartbeat_rejects_tampering():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    reg.register("node-a", services=["svc"])
    before = reg.get("node-a").last_seen

    hb = reg.build_heartbeat("node-a", ["svc"])
    hb["body"]["services"] = ["svc", "forged-service"]  # tamper after signing
    assert reg.apply_heartbeat(hb) is None, "tampered heartbeat accepted"
    assert reg.get("node-a").last_seen == before, "record touched by forgery"

    # Wrong boot token: different signature domain.
    evil = PresenceRegistry("different-boot-token", clock=clock)
    evil.register("node-a", services=["svc"])
    hb2 = reg.build_heartbeat("node-a", ["svc"])
    assert evil.apply_heartbeat(hb2) is None, \
        "heartbeat from another token domain accepted"


def test_replay_guard_rejects_old_seq():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    reg.register("node-a", services=["svc"])
    hb = reg.build_heartbeat("node-a", ["svc"])
    assert reg.apply_heartbeat(hb) is not None
    assert reg.apply_heartbeat(hb) is None, "replayed heartbeat accepted"


def test_heartbeat_from_unknown_node_rejected():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    hb = reg.build_heartbeat("ghost", ["svc"])  # never registered (no hello)
    assert reg.apply_heartbeat(hb) is None


def test_snapshot_roundtrip_counts_reconcile():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    reg.register("node-a", role="service", services=["svc"])
    reg.register("node-b", role="service", services=["svc"], path="fallback")
    path = _tmpfile()

    reg.save_snapshot(path)
    raw = path.read_text(encoding="utf-8")
    assert BOOT not in raw, "boot token leaked into snapshot"

    reg2 = PresenceRegistry.load_snapshot(path, BOOT, clock=clock)
    assert len(reg2) == 2, "snapshot lost nodes: %d" % len(reg2)
    assert sorted(reg2.node_ids()) == ["node-a", "node-b"]
    assert all(reg2.get(n).status == "ONLINE" for n in ("node-a", "node-b"))

    clock.advance(121.0)
    flipped = reg2.sweep()
    assert sorted(flipped) == ["node-a", "node-b"], \
        "sweep after snapshot did not flip both: %r" % flipped


def test_presence_snapshot_shape():
    clock = FakeClock(1000.0)
    reg = PresenceRegistry(BOOT, clock=clock)
    reg.register("node-a", services=["svc"])
    snap = reg.snapshot()
    assert snap["nexus"] == vproto.NEXUS_VERSION
    assert "node-a" in snap["nodes"]
    assert snap["nodes"]["node-a"]["status"] == "ONLINE"


# ------------------------------------------------------------ degraded_cache
def _cache(clock=None, **kw):
    return DegradedCache(path=_tmpfile(), clock=clock, **kw)


def test_degraded_cache_presence_ttl_labels():
    clock = FakeClock(2000.0)
    c = _cache(clock=clock, presence_ttl_s=300.0)
    c.store_presence({"nodes": {"node-a": {"status": "ONLINE"}}})

    clock.advance(100.0)
    got = c.get_presence()
    assert got is not None and got["stale"] is False
    assert got["snapshot"]["nodes"]["node-a"]["status"] == "ONLINE"

    clock.advance(300.0)  # 400 s > 300 s TTL
    got = c.get_presence()
    assert got is not None and got["stale"] is True, \
        "expired presence not labeled stale"
    assert got["snapshot"]["nodes"]["node-a"]["status"] == "ONLINE", \
        "stale presence must still serve last-known-good state"


def test_degraded_cache_advisory_labels_and_tagging():
    clock = FakeClock(2000.0)
    c = _cache(clock=clock, advisory_ttl_s=3600.0)
    c.store_advisory("weather", "tehran", {"summary": "clear"})  # no source

    clock.advance(60.0)
    got = c.get_advisory("weather", "tehran")
    assert got is not None
    assert got["summary"] == "clear", "cached payload altered"
    assert got["cached"] is True
    assert got["stale"] is False
    assert got["source"] == "extended-mind", \
        "cached advisory missing extended-mind tag"

    clock.advance(3601.0)
    got = c.get_advisory("weather", "tehran")
    assert got["stale"] is True, "expired advisory not labeled stale"
    assert got["source"] == "extended-mind"

    assert c.get_advisory("weather", "nowhere") is None


def test_degraded_cache_empty_reads_none():
    c = _cache()
    assert c.get_presence() is None
    assert c.get_advisory("svc", "k") is None
    assert c.has_presence() is False


def test_degraded_cache_compatible_with_relaycache_format():
    path = _tmpfile()
    legacy = RelayCache(path=path)  # writes with the base-class format
    legacy.store_presence({"nodes": {"node-a": {}}})
    legacy.store_advisory("svc", "k", {"answer": 1})

    c = DegradedCache(path=path)
    got = c.get_presence()
    assert got is not None and "stale" in got and "snapshot" in got
    adv = c.get_advisory("svc", "k")
    assert adv is not None and adv["answer"] == 1
    assert adv["cached"] is True and adv["source"] == "extended-mind"


# ------------------------------------------------------------------ security
def test_no_wildcard_bind_in_veins_sources():
    for name in ("proto.py", "guarded_call.py", "presence.py",
                 "degraded_cache.py", "__init__.py"):
        src = (_VEINS / name).read_text(encoding="utf-8")
        assert "0.0.0.0" not in src, "wildcard bind in %s" % name
    assert vproto.LOOPBACK_HOST == "127.0.0.1"


def test_proto_constants_match_formula():
    assert vproto.HEARTBEAT_EVERY_S == 30.0
    assert vproto.OFFLINE_AFTER_S == 120.0
    assert vproto.CIRCUIT_THRESHOLD == 5
    assert vproto.CIRCUIT_OPEN_S == 900.0


# -------------------------------------------------------------------- runner
_TESTS = sorted(
    (name, obj) for name, obj in list(globals().items())
    if name.startswith("test_") and callable(obj))


def main() -> int:
    passed, failed = 0, []
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as e:
            failed.append((name, "ASSERT: %s" % e))
        except Exception as e:  # noqa: BLE001
            failed.append((name, "%s: %s" % (type(e).__name__, e)))
        else:
            passed += 1
    total = passed + len(failed)
    print("veins tests: %d/%d passed" % (passed, total))
    for name, why in failed:
        print("FAIL %s\n      %s" % (name, why))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
