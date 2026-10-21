"""nexus.ledger — shared append-only hash-chained records (Builder A).

Schema (identical across all NEXUS modules, per HUDDLE Decision 8.3):
    {seq, ts, agent, event, payload, prev_hash, hash}

- hash = sha256(canonical_json(seq, ts, agent, event, payload, prev_hash))
- ts = ISO8601 UTC with Z suffix.
- seq starts at 0. Genesis prev_hash = "GENESIS-ROOT".
- append() fails closed: it refuses to append to a broken chain.
- verify_chain() -> (ok: bool, bad_seq: int | None).

100% technical English. Fail-closed. No module writes another module's ledger.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from nexus import AGENT_SEAT, LedgerBroken

GENESIS_PREV_HASH = "GENESIS-ROOT"
_RECORD_KEYS = ("seq", "ts", "agent", "event", "payload", "prev_hash", "hash")


def _gate(task: str) -> None:
    """Network precondition FIRST for every public entry point."""
    from quantum.quantum_gates import network_precondition

    network_precondition(agent=AGENT_SEAT, task=task)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_record(seq: int, ts: str, agent: str, event: str, payload: dict, prev_hash: str) -> str:
    body = _canonical(
        {"seq": seq, "ts": ts, "agent": agent, "event": event, "payload": payload, "prev_hash": prev_hash}
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _read_all(path: str) -> list:
    """Read and parse every record. Raises LedgerBroken on any corruption."""
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise LedgerBroken(f"ledger corrupt: line {lineno} is not JSON ({e})")
            if not isinstance(rec, dict) or any(k not in rec for k in _RECORD_KEYS):
                raise LedgerBroken(f"ledger corrupt: line {lineno} missing schema keys")
            records.append(rec)
    return records


def append(ledger_path: str, agent: str, event: str, payload: dict) -> dict:
    """Append one record to the hash-chained ledger. Returns the record dict.

    Fail-closed: refuses to append to a non-verifying chain (LedgerBroken).
    """
    _gate("ledger.append")
    if not isinstance(payload, dict):
        raise LedgerBroken("payload must be a dict; forged data rejected")
    try:
        _canonical({"payload": payload})
    except (TypeError, ValueError) as e:
        raise LedgerBroken(f"payload is not JSON-serializable; forged data rejected ({e})")

    records = []
    prev_hash = GENESIS_PREV_HASH
    seq = 0
    if os.path.exists(ledger_path):
        records = _read_all(ledger_path)
        ok, bad = verify_chain(ledger_path)
        if not ok:
            raise LedgerBroken(f"ledger chain broken at seq {bad}; refusing to append (fail-closed)")
        if records:
            seq = records[-1]["seq"] + 1
            prev_hash = records[-1]["hash"]

    ts = _utc_now_iso()
    rec = {
        "seq": seq,
        "ts": ts,
        "agent": agent,
        "event": event,
        "payload": payload,
        "prev_hash": prev_hash,
        "hash": _hash_record(seq, ts, agent, event, payload, prev_hash),
    }

    os.makedirs(os.path.dirname(os.path.abspath(ledger_path)), exist_ok=True)
    tmp = ledger_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=True, separators=(",", ":")) + "\n")
        fh.write(json.dumps(rec, ensure_ascii=True, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ledger_path)
    return rec


def verify_chain(ledger_path: str) -> tuple:
    """Verify the full hash chain. Returns (ok: bool, bad_seq: int | None)."""
    _gate("ledger.verify_chain")
    if not os.path.exists(ledger_path):
        return (False, None)
    try:
        records = _read_all(ledger_path)
    except LedgerBroken:
        return (False, None)
    prev_hash = GENESIS_PREV_HASH
    for rec in records:
        seq = rec["seq"]
        expected = _hash_record(seq, rec["ts"], rec["agent"], rec["event"], rec["payload"], rec["prev_hash"])
        if rec["hash"] != expected or rec["prev_hash"] != prev_hash:
            return (False, seq)
        prev_hash = rec["hash"]
    return (True, None)
