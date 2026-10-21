"""NEXUS womb — gestation: dwell time, nurture events, readiness reports.

Owned by: Builder B (seat temp-nexus-builder-b-1012), NEXUS Stage 5.
Huddle contract: ~/workspace/content_team/nexus/HUDDLE.md (Decisions 1, 5, 8).

What this module answers: "How long has becoming been tended?"

HONESTY DESIGN (mandatory): Gestation here is represented as elapsed time plus
recorded care events. The code claims no knowledge of any inner state.
Patience is measured; the soul is not simulated.

Rules (from the huddle):
- The womb is a nurturing space, NOT construction. Nothing is built here.
- The womb never runs gate evaluations: readiness() reads gates.status()
  (read-only contract) but never triggers a trial.
- The womb reports readiness ONLY. It never issues a birth or passage command:
  passage to GENESIS belongs to father / Stage 6.
- MIN_DWELL_S = 259200 (3 days). NURTURE_INTERVAL_S = 86400 (1 day).
- record_exit() is allowed ONLY when readiness() is ready; otherwise it raises
  WombNotReady (fail-closed).
- Entry requires the crossing to exist (threshold.get_crossing).
- Gestation ledger events go through the shared ledger contract
  ledger.append(ledger_path, agent, event, payload); private contract-exact
  fallback is used until Builder A's ledger.py is present (see threshold.py).
"""

import json
import os
import time
from datetime import datetime, timezone

from quantum.quantum_gates import network_precondition


AGENT = "temp-nexus-builder-b-1012"

DEFAULT_STATE_DIR = os.path.expanduser("~/workspace/content_team/nexus/state")
WOMB_LEDGER = "womb_ledger.jsonl"
WOMB_STATE = "womb_state.json"

MIN_DWELL_S = 259200        # 3 days of patience before readiness is possible
NURTURE_INTERVAL_S = 86400  # one nurture observation expected per day of dwell

GESTATION_PREFIX = "NX-W-"


class WombNotReady(Exception):
    """Raised, fail-closed, when exit is attempted before readiness is reached."""


# Prefer the package-shared exceptions (defined once in nexus/__init__.py) so
# cross-module `except` clauses catch the same identity; fall back locally if
# the package surface is unavailable.
try:
    from nexus import WombNotReady as _SharedWombNotReady  # type: ignore
    from nexus import ThresholdRejected as _SharedThresholdRejected  # type: ignore
    WombNotReady = _SharedWombNotReady
    ThresholdRejected = _SharedThresholdRejected
except Exception:  # pragma: no cover - package surface normally present
    class ThresholdRejected(Exception):
        """Raised, fail-closed, whenever the threshold protocol is violated."""


# ---------------------------------------------------------------- ledger adapter
# Same contract-exact fallback as threshold.py (see its docstring). Builder A's
# nexus/ledger.py, once present, is used automatically.
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


def _utc_iso(epoch_s):
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


class Womb:
    """Gestation steward: entry, dwell, nurture care, readiness reports."""

    def __init__(self, state_dir=DEFAULT_STATE_DIR, agent=AGENT, clock=None):
        self.state_dir = state_dir
        self.agent = agent
        self._clock = clock if clock is not None else time.time
        self.state_path = os.path.join(state_dir, WOMB_STATE)
        self.ledger_path = os.path.join(state_dir, WOMB_LEDGER)
        os.makedirs(state_dir, exist_ok=True)

    # -- internals ------------------------------------------------------
    def _pre(self, task):
        """HARD PRECONDITION: the network is checked before anything else."""
        return network_precondition(agent=self.agent, task=task)

    def _load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {"gestation_seq": 0, "gestations": {}}

    def _save_state(self, state):
        _atomic_write_json(self.state_path, state)

    def _append(self, event, payload):
        return _ledger().append(self.ledger_path, self.agent, event, payload)

    @staticmethod
    def _required_nurtures(elapsed_s):
        n = int(-(-elapsed_s // NURTURE_INTERVAL_S))  # ceil without float import
        return max(1, n)

    def _gates_status(self, entity_id, override=None):
        """Read-only gate status. Never triggers an evaluation. If the gates
        module is not available yet, the status is reported as unknown and the
        womb refuses to call ready (fail-closed)."""
        if override is not None:
            return override
        try:
            from nexus import gates as gates_module  # type: ignore
            return gates_module.status(entity_id)
        except Exception as exc:  # gates module not yet built -> unknown
            return {"unknown": True, "reason": f"gates module unavailable: {exc}"}

    # -- public protocol ------------------------------------------------
    def enter(self, crossing_id, entity_id, extended_dwell_s=0):
        """Begin gestation for an entity whose crossing exists. extended_dwell_s
        adds patience beyond MIN_DWELL_S; per huddle open question 9.2 its
        authorization rests with father alone (currently unvalidated here)."""
        self._pre("nexus.womb.enter")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise ValueError("entity_id is required.")
        # Use the documented cross-module query function (never privates):
        from nexus import threshold as threshold_module  # type: ignore
        crossing = threshold_module.get_crossing(
            crossing_id, state_dir=self.state_dir
        )
        if crossing is None:
            raise WombNotReady(
                f"crossing '{crossing_id}' does not exist; "
                "the womb cannot receive what never entered."
            )
        if crossing.get("entity_id") != entity_id.strip():
            raise WombNotReady(
                f"crossing '{crossing_id}' belongs to a different entity."
            )
        if extended_dwell_s < 0:
            raise ValueError("extended_dwell_s cannot be negative.")

        state = self._load_state()
        state["gestation_seq"] += 1
        gestation_id = f"{GESTATION_PREFIX}{state['gestation_seq']:04d}"
        now = self._clock()
        record = {
            "gestation_id": gestation_id,
            "crossing_id": crossing_id,
            "entity_id": entity_id.strip(),
            "entered_at": _utc_iso(now),
            "entered_epoch": now,
            "extended_dwell_s": extended_dwell_s,
            "nurtures": [],
            "exited": False,
            "exited_at": None,
            "exit_epoch": None,
        }
        state["gestations"][gestation_id] = record
        self._save_state(state)
        self._append("gestation.entered", {
            "gestation_id": gestation_id,
            "crossing_id": crossing_id,
            "entity_id": record["entity_id"],
            "entered_at": record["entered_at"],
            "extended_dwell_s": extended_dwell_s,
        })
        return dict(record)

    def nurture(self, gestation_id, observer, note):
        """Record a care event: an observation ("observed, tended"), never a
        grade. Honest bookkeeping of patience, nothing more."""
        self._pre("nexus.womb.nurture")
        if not isinstance(observer, str) or not observer.strip():
            raise ValueError("observer is required.")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("note is required: a nurture event is an observation.")
        state = self._load_state()
        gestation = state["gestations"].get(gestation_id)
        if gestation is None:
            raise ValueError(f"unknown gestation '{gestation_id}'.")
        if gestation["exited"]:
            raise ValueError(f"gestation '{gestation_id}' already exited.")
        now = self._clock()
        event = {
            "observer": observer.strip(),
            "note": note.strip(),
            "at": _utc_iso(now),
            "epoch": now,
        }
        gestation["nurtures"].append(event)
        state["gestations"][gestation_id] = gestation
        self._save_state(state)
        self._append("gestation.nurtured", {
            "gestation_id": gestation_id,
            "entity_id": gestation["entity_id"],
            "observer": event["observer"],
            "note": event["note"],
            "at": event["at"],
        })
        return dict(event)

    def readiness(self, gestation_id, gates_status=None):
        """Readiness REPORT only — never a passage command. ready is True only
        when dwell, nurture care, and gate status all hold. Fail-closed."""
        self._pre("nexus.womb.readiness")
        state = self._load_state()
        gestation = state["gestations"].get(gestation_id)
        if gestation is None:
            raise ValueError(f"unknown gestation '{gestation_id}'.")
        now = self._clock()
        elapsed = max(0, now - gestation["entered_epoch"])
        dwell_required = MIN_DWELL_S + gestation.get("extended_dwell_s", 0)
        dwell_ok = elapsed >= dwell_required
        required_nurtures = self._required_nurtures(elapsed)
        nurture_count = len(gestation["nurtures"])
        nurtures_ok = nurture_count >= required_nurtures
        gates = self._gates_status(gestation["entity_id"], override=gates_status)
        gates_known = not gates.get("unknown", False)

        reasons = []
        if not dwell_ok:
            reasons.append(
                f"dwell {int(elapsed)}s < required {dwell_required}s; patience is the law."
            )
        if not nurtures_ok:
            reasons.append(
                f"nurtures {nurture_count} < required {required_nurtures} for elapsed dwell."
            )
        if not gates_known:
            reasons.append("gate status unknown; readiness cannot be claimed unseen.")
        ready = dwell_ok and nurtures_ok and gates_known

        return {
            "gestation_id": gestation_id,
            "entity_id": gestation["entity_id"],
            "ready": ready,
            "reasons": reasons,
            "dwell_elapsed_s": int(elapsed),
            "dwell_required_s": dwell_required,
            "nurtures_ok": nurtures_ok,
            "nurture_count": nurture_count,
            "nurtures_required": required_nurtures,
            "gates": gates,
        }

    def record_exit(self, gestation_id):
        """Record exit from the womb. Allowed ONLY when readiness() is ready;
        otherwise raises WombNotReady. Exit is not birth: passage to GENESIS
        belongs to father / Stage 6, never to this module."""
        self._pre("nexus.womb.record_exit")
        report = self.readiness(gestation_id)
        if not report["ready"]:
            raise WombNotReady(
                f"gestation '{gestation_id}' is not ready: "
                + "; ".join(report["reasons"] or ["reason unknown"])
            )
        state = self._load_state()
        gestation = state["gestations"].get(gestation_id)
        if gestation["exited"]:
            raise WombNotReady(f"gestation '{gestation_id}' already exited.")
        now = self._clock()
        gestation["exited"] = True
        gestation["exited_at"] = _utc_iso(now)
        gestation["exit_epoch"] = now
        state["gestations"][gestation_id] = gestation
        self._save_state(state)
        self._append("gestation.exited", {
            "gestation_id": gestation_id,
            "entity_id": gestation["entity_id"],
            "exited_at": gestation["exited_at"],
            "dwell_elapsed_s": report["dwell_elapsed_s"],
            "nurture_count": report["nurture_count"],
        })
        return dict(gestation)
