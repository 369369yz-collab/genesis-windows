"""NEXUS threshold — entry protocol, transformation records, sealed passages.

Owned by: Builder B (seat temp-nexus-builder-b-1012), NEXUS Stage 5.
Huddle contract: ~/workspace/content_team/nexus/HUDDLE.md (Decisions 1, 4, 8).

What this module answers: "May I enter, and what changed?"

Rules (from the huddle):
- The threshold RECORDS entry; it never evaluates worthiness.
- Every public entry point calls network_precondition() FIRST. Any failure
  stops the task before anything is touched.
- Fail-closed: any violation raises ThresholdRejected. A rejected entry
  seals nothing and appends nothing.
- Transformation rule (NEXUS-LAW-002 shape): exit_state must be recorded,
  non-empty, and DIFFERENT from entry_state. Transformation, not replacement.
- Double entry: an entity with an open (unsealed) crossing may not enter again.
- Cross-module reads happen only through the documented query function
  get_crossing(); this module never reads another module's privates.
- Entry ledger events go through the shared ledger contract
  ledger.append(ledger_path, agent, event, payload). Builder A owns ledger.py;
  until it is present this module uses a private fallback that implements the
  documented schema EXACTLY (drop-in compatible).
"""

import json
import os
import time
from datetime import datetime, timezone

from quantum.quantum_gates import network_precondition


AGENT = "temp-nexus-builder-b-1012"

DEFAULT_STATE_DIR = os.path.expanduser("~/workspace/content_team/nexus/state")
THRESHOLD_LEDGER = "threshold_ledger.jsonl"
THRESHOLD_STATE = "threshold_state.json"

CROSSING_PREFIX = "NX-X-"


class ThresholdRejected(Exception):
    """Raised, fail-closed, whenever the threshold protocol is violated."""


# Prefer the package-shared exception (defined once in nexus/__init__.py) so
# cross-module `except` clauses catch the same identity; fall back to the
# local definition if the package surface is unavailable.
try:
    from nexus import ThresholdRejected as _SharedThresholdRejected  # type: ignore
    ThresholdRejected = _SharedThresholdRejected
except Exception:  # pragma: no cover - package surface normally present
    pass


# ---------------------------------------------------------------- ledger adapter
# Builder A owns nexus/ledger.py. Until it lands, this private fallback keeps
# the threshold usable while honoring the documented ledger contract EXACTLY:
# append(ledger_path, agent, event, payload) -> record;
# verify_chain(ledger_path) -> (ok, bad_seq).
# Record schema: {seq, ts, agent, event, payload, prev_hash, hash}
# hash = sha256(canonical_json(seq, ts, agent, event, payload, prev_hash)).
class _FallbackLedger:
    @staticmethod
    def _canonical(seq, ts, agent, event, payload, prev_hash):
        return json.dumps(
            [seq, ts, agent, event, payload, prev_hash],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _read_records(ledger_path):
        records = []
        if os.path.exists(ledger_path):
            with open(ledger_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        return records

    @classmethod
    def append(cls, ledger_path, agent, event, payload):
        import hashlib

        records = cls._read_records(ledger_path)
        seq = len(records) + 1
        prev_hash = records[-1]["hash"] if records else "GENESIS"
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        digest = hashlib.sha256(
            cls._canonical(seq, ts, agent, event, payload, prev_hash).encode("utf-8")
        ).hexdigest()
        record = {
            "seq": seq,
            "ts": ts,
            "agent": agent,
            "event": event,
            "payload": payload,
            "prev_hash": prev_hash,
            "hash": digest,
        }
        with open(ledger_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    @classmethod
    def verify_chain(cls, ledger_path):
        records = cls._read_records(ledger_path)
        prev_hash = "GENESIS"
        for rec in records:
            import hashlib

            expected = hashlib.sha256(
                cls._canonical(
                    rec["seq"], rec["ts"], rec["agent"], rec["event"],
                    rec["payload"], rec["prev_hash"],
                ).encode("utf-8")
            ).hexdigest()
            if rec["prev_hash"] != prev_hash or rec["hash"] != expected:
                return (False, rec["seq"])
            prev_hash = rec["hash"]
        return (True, None)


def _ledger():
    """Return the shared ledger module if present, else the contract-exact fallback."""
    try:
        from nexus import ledger as shared_ledger  # type: ignore
        if hasattr(shared_ledger, "append") and hasattr(shared_ledger, "verify_chain"):
            return shared_ledger
    except Exception:
        pass
    return _FallbackLedger


# ---------------------------------------------------------------- persistence
def _atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Threshold:
    """The NEXUS gate architecture: entry records, transformation records, seals."""

    def __init__(self, state_dir=DEFAULT_STATE_DIR, agent=AGENT):
        self.state_dir = state_dir
        self.agent = agent
        self.state_path = os.path.join(state_dir, THRESHOLD_STATE)
        self.ledger_path = os.path.join(state_dir, THRESHOLD_LEDGER)
        os.makedirs(state_dir, exist_ok=True)

    # -- internals ------------------------------------------------------
    def _pre(self, task):
        """HARD PRECONDITION: the network is checked before anything else."""
        return network_precondition(agent=self.agent, task=task)

    def _load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {"crossing_seq": 0, "crossings": {}}

    def _save_state(self, state):
        _atomic_write_json(self.state_path, state)

    def _append(self, event, payload):
        return _ledger().append(self.ledger_path, self.agent, event, payload)

    @staticmethod
    def _require_nonempty_state(value, what):
        if value is None:
            raise ThresholdRejected(f"{what} is missing; the threshold records what enters.")
        if isinstance(value, (str, bytes)) and not value.strip():
            raise ThresholdRejected(f"{what} is empty; the threshold records what enters.")
        if isinstance(value, dict) and not value:
            raise ThresholdRejected(f"{what} is empty; the threshold records what enters.")
        return value

    @staticmethod
    def _same_state(a, b):
        def canon(v):
            if isinstance(v, dict):
                return json.dumps(v, sort_keys=True, ensure_ascii=False)
            return str(v)
        return canon(a) == canon(b)

    # -- public protocol ------------------------------------------------
    def enter(self, entity_id, entry_state):
        """Record what entered NEXUS and its prior state. Fail-closed."""
        self._pre("nexus.threshold.enter")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise ThresholdRejected("entity_id is required.")
        entity_id = entity_id.strip()
        self._require_nonempty_state(entry_state, "entry_state")

        state = self._load_state()
        for crossing in state["crossings"].values():
            if crossing["entity_id"] == entity_id and not crossing["sealed"]:
                raise ThresholdRejected(
                    f"entity '{entity_id}' already holds open crossing "
                    f"{crossing['crossing_id']}; double entry refused."
                )

        state["crossing_seq"] += 1
        crossing_id = f"{CROSSING_PREFIX}{state['crossing_seq']:04d}"
        record = {
            "crossing_id": crossing_id,
            "entity_id": entity_id,
            "entered_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "entry_state": entry_state,
            "exit_state": None,
            "sealed": False,
            "sealed_at": None,
        }
        state["crossings"][crossing_id] = record
        self._save_state(state)
        self._append("crossing.entered", {
            "crossing_id": crossing_id,
            "entity_id": entity_id,
            "entered_at": record["entered_at"],
            "entry_state": entry_state,
        })
        return dict(record)

    def transform(self, crossing_id, exit_state):
        """Apply the transformation rule: exit_state recorded, non-empty, DIFFERENT
        from entry_state. A crossing that was sealed cannot be transformed again."""
        self._pre("nexus.threshold.transform")
        state = self._load_state()
        crossing = state["crossings"].get(crossing_id)
        if crossing is None:
            raise ThresholdRejected(f"unknown crossing '{crossing_id}'.")
        if crossing["sealed"]:
            raise ThresholdRejected(f"crossing '{crossing_id}' is sealed; no further change.")
        self._require_nonempty_state(exit_state, "exit_state")
        if self._same_state(crossing["entry_state"], exit_state):
            raise ThresholdRejected(
                f"crossing '{crossing_id}': exit_state identical to entry_state; "
                "transformation means change, not replacement and not sameness."
            )
        crossing["exit_state"] = exit_state
        state["crossings"][crossing_id] = crossing
        self._save_state(state)
        self._append("crossing.transformed", {
            "crossing_id": crossing_id,
            "entity_id": crossing["entity_id"],
            "exit_state": exit_state,
        })
        return dict(crossing)

    def seal(self, crossing_id):
        """Seal the passage. Requires a recorded transformation; fail-closed otherwise."""
        self._pre("nexus.threshold.seal")
        state = self._load_state()
        crossing = state["crossings"].get(crossing_id)
        if crossing is None:
            raise ThresholdRejected(f"unknown crossing '{crossing_id}'.")
        if crossing["sealed"]:
            raise ThresholdRejected(f"crossing '{crossing_id}' is already sealed.")
        if crossing["exit_state"] is None:
            raise ThresholdRejected(
                f"crossing '{crossing_id}' has no recorded transformation; "
                "the passage cannot be sealed before change is recorded."
            )
        crossing["sealed"] = True
        crossing["sealed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        state["crossings"][crossing_id] = crossing
        self._save_state(state)
        self._append("crossing.sealed", {
            "crossing_id": crossing_id,
            "entity_id": crossing["entity_id"],
            "sealed_at": crossing["sealed_at"],
        })
        return dict(crossing)

    def get_crossing(self, crossing_id):
        """Read-only cross-query consumed by gates.py. Returns a copy, or None."""
        self._pre("nexus.threshold.get_crossing")
        state = self._load_state()
        crossing = state["crossings"].get(crossing_id)
        return dict(crossing) if crossing is not None else None


def get_crossing(crossing_id, state_dir=DEFAULT_STATE_DIR):
    """Module-level read-only cross-query (huddle Decision 8.6):
    threshold.get_crossing(crossing_id) -> dict | None.

    The optional state_dir routes callers that share a state directory
    (e.g. womb, which passes its own); the contract signature
    get_crossing(crossing_id) stays valid. Network precondition still runs.
    """
    return Threshold(state_dir=state_dir).get_crossing(crossing_id)
