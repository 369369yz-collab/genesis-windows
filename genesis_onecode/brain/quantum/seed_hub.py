#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# VENDORED COPY - GENESIS embed step 7, Phase 2 (2026-10-21).
# Source: ~/workspace/content_team/quantum/seed_hub.py (369 quantum seed layer, content_team).
# Copied verbatim except where a "VENDORING ADAPTATION" note says
# otherwise. The upstream file remains the canonical world copy; this
# embed exists so the shipped app carries the seed layer inside itself
# (YZ law 2026-10-16: the whole 369 world lives inside GENESIS).
# Runtime state (mother seed, consumers, audit log) lives in the
# sibling state/ directory of THIS copy - separate from the world copy.
# ---------------------------------------------------------------------------
"""
seed_hub.py — central FAIL-CLOSED quantum seed distribution hub for the 369 world.

Authority: SEED_DISTRIBUTION_ARCH.md (huddle SESSION-QWR-1011).
Built: 2026-10-11 by temp-worldbuild100-1011 (WORLD 100% CODING PROGRAM, stream B).

THE rule: this module is the ONLY sanctioned path for seed consumption.
Every consumer registers once (consumer_id) and every draw goes through
hub.consume(), which performs "derive + atomic log" in one step. A draw
without a logged record is a violation, not a shortcut.

Fail-closed guarantees:
  * unknown consumer_id            -> UnregisteredConsumerError (no draw)
  * quantum_required consumer on a
    non-quantum mother seed        -> QuantumRequiredError (no draw);
                                     the halt is logged to hub_halts.jsonl
                                     (a recorded halt is NOT a violation)
  * derive domain outside the consumer's registered namespace
                                   -> DomainNamespaceError (no draw)
  * every record carries consumer_id, YYYY-MM-DD date (the SEED's date,
    never a timestamp), a strictly increasing per-domain counter, and
    everything audit._expected_index needs to replay it.

Record kinds:
  * "index" — pick into an eligible pool (replayable by audit.proof_check).
  * "bytes" — raw derived bytes (round ids, shuffle salts); replayable by
    hub.verify_record() via re-derivation from the archived mother seed.

Consumers registry: state/consumers.json — {"consumers": {id: record},
"history": [all registration records]}. Append-only: re-registration with
identical parameters is a no-op; changed parameters append a new revision.
Retirement is a new revision with status="retired", never a silent edit.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from . import audit
from . import qrng

HUB_VERSION = "1.0"

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
CONSUMERS_FILE = os.path.join(STATE, "consumers.json")
HALTS_FILE = os.path.join(STATE, "hub_halts.jsonl")

PRIORITIES = ("CRITICAL", "IMPORTANT", "ROUTINE")

# Direct seed-call pattern OUTSIDE this module. Sanctioned exceptions:
#   - this hub itself (the only derivation point),
#   - audit.py / test files (replay and verification tooling).
_DIRECT_CALL_RE = re.compile(
    r"qrng\.derive\s*\(|qrng\.draw_int\s*\(|qrng\.get_bytes\s*\(|"
    r"variety\.pick\s*\(|variety\.decide_batch\s*\("
)
_FROM_IMPORT_RE = re.compile(
    r"from\s+quantum\s+import\s+[^\n]*\b(qrng|variety)\b|"
    r"from\s+\.\s+import\s+[^\n]*\b(qrng|variety)\b|"
    r"from\s+quantum\.(qrng|variety)\s+import"
)


class HubError(Exception):
    """Base class for all hub failures. The hub never fails open."""


class UnregisteredConsumerError(HubError):
    """consume() called with an unknown consumer_id. Strict mode: no draw."""


class QuantumRequiredError(HubError):
    """A quantum_required consumer refused a non-quantum mother seed.

    The refusal is logged to hub_halts.jsonl. A recorded halt is NOT a
    violation; silent non-quantum consumption would be."""


class DomainNamespaceError(HubError):
    """The derive domain is outside the consumer's registered namespace."""


class CounterReuseError(HubError):
    """A (domain, counter) pair was already issued. Fail closed."""


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def _load_registry():
    try:
        with open(CONSUMERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("consumers", {})
    data.setdefault("history", [])
    return data


def _save_registry(data):
    tmp = CONSUMERS_FILE + ".tmp"
    os.makedirs(os.path.dirname(CONSUMERS_FILE), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONSUMERS_FILE)


def register_consumer(consumer_id, world_section, domain_namespace,
                      quantum_required=True, priority="IMPORTANT",
                      wired_by="", status="active"):
    """Register (or no-op re-register) a seed consumer. Append-only.

    Returns {"ok": True, "changed": bool, "record": record}.
    Raises HubError on conflicting re-registration of a retired consumer
    or an invalid priority.
    """
    if not consumer_id or not isinstance(consumer_id, str):
        raise HubError("consumer_id must be a non-empty string")
    if not domain_namespace or not isinstance(domain_namespace, str):
        raise HubError("domain_namespace must be a non-empty string")
    if priority not in PRIORITIES:
        raise HubError(f"priority must be one of {PRIORITIES}")
    data = _load_registry()
    record = {
        "consumer_id": consumer_id,
        "world_section": world_section,
        "domain_namespace": domain_namespace,
        "quantum_required": bool(quantum_required),
        "priority": priority,
        "wired_at": _utcnow_iso(),
        "wired_by": wired_by,
        "status": status,
        "hub_version": HUB_VERSION,
    }
    prev = data["consumers"].get(consumer_id)
    if prev is not None:
        same = all(prev.get(k) == record.get(k)
                   for k in ("world_section", "domain_namespace",
                             "quantum_required", "priority", "status"))
        if same:
            return {"ok": True, "changed": False, "record": prev}
        if prev.get("status") == "retired" and status != "retired":
            raise HubError(
                f"consumer {consumer_id!r} is retired — re-activation needs "
                "a new consumer_id (append-only registry)")
        # changed parameters: new revision, history preserved
        data["history"].append(prev)
    data["consumers"][consumer_id] = record
    data["history"].append(dict(record))
    _save_registry(data)
    return {"ok": True, "changed": True, "record": record}


def get_consumer(consumer_id):
    """Return the consumer record or raise UnregisteredConsumerError."""
    data = _load_registry()
    rec = data["consumers"].get(consumer_id)
    if rec is None or rec.get("status") == "retired":
        raise UnregisteredConsumerError(
            f"unknown or retired consumer_id {consumer_id!r} — "
            "register first; strict mode rejects unwired consumers")
    return rec


def list_consumers():
    return _load_registry()["consumers"]


def _check_domain(consumer, domain):
    ns = consumer["domain_namespace"]
    if domain == ns or domain.startswith(ns):
        return domain
    raise DomainNamespaceError(
        f"domain {domain!r} is outside consumer "
        f"{consumer['consumer_id']!r} namespace {ns!r} — "
        "two consumers must never share a derive domain")


def _log_halt(consumer_id, domain, reason, mother):
    os.makedirs(os.path.dirname(HALTS_FILE), exist_ok=True)
    with open(HALTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": _utcnow_iso(),
            "consumer_id": consumer_id,
            "domain": domain,
            "reason": reason,
            "mother_date": mother.get("date"),
            "mother_source": mother.get("source"),
            "mother_quantum": mother.get("quantum"),
            "hub_version": HUB_VERSION,
        }, ensure_ascii=False) + "\n")


def _rejection_index(domain, eligible, start_counter):
    """Unbiased index into eligible, mirroring qrng.draw_int's sampling.

    Returns (index, start_counter). The stored counter is the START counter;
    audit._expected_index replays the rejection loop from it deterministically.
    """
    span = len(eligible)
    bitlen = span.bit_length()
    nbytes = max(4, (bitlen + 7) // 8 + 1)
    limit = (256 ** nbytes) // span * span
    ctr = start_counter
    while True:
        val = int.from_bytes(qrng.derive(domain, nbytes, ctr), "big")
        if val < limit:
            return val % span, start_counter
        ctr += 1  # astronomically rare; deterministic per counter chain


def consume(consumer_id, kind="index", domain=None, eligible=None,
            n_bytes=32, context=""):
    """Draw from the mother seed through the hub. THE sanctioned path.

    kind="index": eligible (non-empty list) required. Returns
        {"index", "choice", "counter", "record"}.
    kind="bytes": n_bytes (1..1024). Returns
        {"bytes", "hex", "counter", "record"}.

    Raises UnregisteredConsumerError / DomainNamespaceError /
    QuantumRequiredError / HubError — never returns a silent draw.
    """
    consumer = get_consumer(consumer_id)
    domain = _check_domain(consumer, domain or consumer["domain_namespace"])

    seed, source, quantum, seed_date = qrng.get_mother_seed()
    is_quantum = quantum is True
    if consumer["quantum_required"] and not is_quantum:
        _log_halt(consumer_id, domain,
                  "quantum_required consumer refused non-quantum mother seed",
                  {"date": seed_date, "source": source, "quantum": quantum})
        raise QuantumRequiredError(
            f"consumer {consumer_id!r} requires a quantum mother seed; "
            f"today's source is {source} (quantum={quantum}) — halt logged, "
            "no draw issued")

    counter = audit.next_counter(domain)
    # Cross-process reuse guard: the counter must not already be logged.
    for rec in audit.read_all():
        if rec.get("domain") == domain and rec.get("counter") == counter:
            _log_halt(consumer_id, domain,
                      f"counter reuse detected: ({domain}, {counter}) already logged",
                      {"date": seed_date, "source": source, "quantum": quantum})
            raise CounterReuseError(
                f"({domain}, {counter}) already issued — refusing reuse")

    base = {
        "domain": domain,
        "counter": counter,
        "seed_source": source,
        "quantum": is_quantum,
        "date": seed_date,  # the SEED's date (YYYY-MM-DD) — never a timestamp
        "ts": _utcnow_iso(),
        "consumer_id": consumer_id,
        "hub": f"seed_hub/{HUB_VERSION}",
        "context": context,
    }
    # Test tagging: firing-test / CI processes set SEED_HUB_TEST=1. Their
    # draws are REAL (well-formed, replayable) but they are not PRODUCTION
    # consumption — quantum_world.section_records() excludes them from QSI
    # so automated test runs can never inflate the coverage index.
    if os.environ.get("SEED_HUB_TEST") == "1":
        base["test"] = True
    if kind == "index":
        if not eligible or not isinstance(eligible, (list, tuple)):
            raise HubError("kind='index' needs a non-empty eligible list")
        eligible = list(eligible)
        index, _ = _rejection_index(domain, eligible, counter)
        record = dict(base, kind="index", eligible=eligible,
                      index=index, choice=eligible[index])
        audit.log(record)  # atomic with derivation in-process
        return {"index": index, "choice": eligible[index],
                "counter": counter, "record": record}
    if kind == "bytes":
        if not (1 <= n_bytes <= 1024):
            raise HubError("n_bytes must be 1..1024")
        raw = qrng.derive(domain, n_bytes, counter)
        record = dict(base, kind="bytes", n_bytes=n_bytes,
                      bytes_hex=raw.hex())
        audit.log(record)
        return {"bytes": raw, "hex": raw.hex(),
                "counter": counter, "record": record}
    raise HubError(f"unknown kind {kind!r} — use 'index' or 'bytes'")


def verify_record(rec):
    """Re-derive a hub record from the archived mother seed.

    Returns {"ok": bool, "reason": str}. Non-hub records are rejected
    (use audit.proof_check for those); legacy malformed records fail
    honestly instead of being silently skipped.
    """
    if not isinstance(rec, dict) or not str(rec.get("hub", "")).startswith("seed_hub/"):
        return {"ok": False, "reason": "not a seed_hub record"}
    seed = audit._seed_for(rec.get("date"))
    if seed is None:
        return {"ok": False,
                "reason": f"mother seed not archived for date {rec.get('date')!r}"}
    kind = rec.get("kind")
    try:
        if kind == "index":
            exp = audit._expected_index(seed, rec)
            if exp != rec["index"] or rec["eligible"][exp] != rec["choice"]:
                return {"ok": False,
                        "reason": f"replay mismatch: expected {exp}, logged {rec.get('index')}"}
            return {"ok": True, "reason": "index re-derives from archived seed"}
        if kind == "bytes":
            n = int(rec["n_bytes"])
            h = hashlib.shake_128()
            h.update(seed)
            h.update(b"|".join([b"369q", rec["date"].encode(),
                                rec["domain"].encode(),
                                str(rec["counter"]).encode()]))
            if h.digest(n).hex() != rec["bytes_hex"]:
                return {"ok": False, "reason": "bytes re-derivation mismatch"}
            return {"ok": True, "reason": "bytes re-derive from archived seed"}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
    return {"ok": False, "reason": f"unknown kind {kind!r}"}


def find_duplicate_counters(records=None):
    """Daily-scan helper: (domain, counter) pairs logged more than once.

    A duplicate means seed reuse — a certification-killing violation
    (arch doc section 3.4, item 5). Returns a list of
    {"domain", "counter", "occurrences"}.
    """
    recs = audit.read_all() if records is None else records
    seen, dupes = {}, []
    for i, r in enumerate(recs):
        key = (r.get("domain"), r.get("counter"))
        if key[0] is None or key[1] is None:
            continue
        if key in seen:
            dupes.append({"domain": key[0], "counter": key[1],
                          "occurrences": [seen[key], i]})
        else:
            seen[key] = i
    return dupes


def scan_direct_calls(paths, allowlist=()):
    """Find direct qrng/variety seed calls outside this hub.

    paths: files or directories (relative to content_team/). allowlist: path
    prefixes explicitly sanctioned during the migration window (the 4 proven
    consumers being re-wired in program phase 1, plus replay/test tooling).
    Returns {"findings": [...], "scanned_files": int}.
    """
    root = os.path.dirname(ROOT)  # content_team/
    findings = []
    scanned = 0
    hub_path = os.path.abspath(__file__)
    for p in paths:
        full = p if os.path.isabs(p) else os.path.join(root, p)
        files = []
        if os.path.isdir(full):
            for dirpath, _d, filenames in os.walk(full):
                if "__pycache__" in dirpath:
                    continue
                files += [os.path.join(dirpath, f) for f in filenames
                          if f.endswith(".py")]
        elif os.path.isfile(full) and full.endswith(".py"):
            files = [full]
        for fp in files:
            if os.path.abspath(fp) == hub_path:
                continue  # the hub IS the sanctioned derivation point
            rel = os.path.relpath(fp, root)
            if any(rel == a or rel.startswith(a.rstrip("/") + "/")
                   for a in allowlist):
                continue
            if os.path.basename(fp).startswith("test_") or \
                    fp.endswith("_test.py"):
                continue  # test fixtures are not active consumption paths
            scanned += 1
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    for ln, line in enumerate(f, 1):
                        code = line.split("#", 1)[0]
                        if _DIRECT_CALL_RE.search(code) or \
                                _FROM_IMPORT_RE.search(code):
                            findings.append(
                                {"file": rel, "line": ln,
                                 "match": line.strip()[:140]})
            except OSError:
                continue
    return {"findings": findings, "scanned_files": scanned}


def status():
    """Hub health snapshot for reports and dashboards."""
    consumers = list_consumers()
    recs = audit.read_all()
    hub_recs = [r for r in recs if str(r.get("hub", "")).startswith("seed_hub/")]
    halts = 0
    try:
        with open(HALTS_FILE, "r", encoding="utf-8") as f:
            halts = sum(1 for line in f if line.strip())
    except OSError:
        pass
    return {
        "hub_version": HUB_VERSION,
        "registered_consumers": len(consumers),
        "consumer_ids": sorted(consumers),
        "hub_records_total": len(hub_recs),
        "recorded_halts": halts,
        "mother": qrng.mother_info(),
    }


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=2))
