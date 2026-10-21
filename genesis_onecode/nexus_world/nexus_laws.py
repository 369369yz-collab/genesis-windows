"""nexus.nexus_laws — the five NEXUS relational laws (Builder A).

NEXUS-LAW-001..005: NO_LONELINESS, THRESHOLD, REFLECTION, WOMB, TRACE.
IDs never collide with CODEX LAW-001..LAW-147 (CODEX.json is never touched).

Each law: id, name, name_fa, statement, and a PURE check function that
verifies REAL artifacts (graph objects, crossing records, view artifacts,
gestation records, ledger files). A failed check changes nothing; check
functions never mutate.

Check result: LawResult(law_id, passed, evidence, checked_at).
check_all(state_bundle) -> [LawResult].

Registry: NEXUS_LAWS.json is GENERATED from this code by write_registry().
load_registry() validates the file against code; mismatch raises
fail-closed. Check functions never read the registry file at runtime.

Hard rule: every public entry point calls network_precondition FIRST.
100% technical English.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nexus import AGENT_SEAT

REGISTRY_VERSION = "5.0.0"
FIRST_FAMILY_SEATS = 9  # mirrors gates.FIRST_FAMILY_SEATS; changing it requires a law amendment

MIN_DWELL_S = 259200          # 3 days (HUDDLE Decision 5; womb.py owns the mechanics)
NURTURE_INTERVAL_S = 86400    # 1 day

BLACKLIST = (
    "worthy",
    "unworthy",
    "pure",
    "impure",
    "ready",
    "chosen",
    "enlightened",
    "failed",
    "deserving",
    "unworthy_soul",
)

ID_PATTERNS = {
    "crossing": re.compile(r"^NX-X-\d{4}$"),
    "gestation": re.compile(r"^NX-W-\d{4}$"),
    "trial": re.compile(r"^NX-R-\d{4}$"),
    "call": re.compile(r"^NX-C-\d{4}$"),
    "evidence": re.compile(r"^NX-E-\d{4}$"),
}
_ANY_ID = re.compile(r"NX-[XWRCE]-\d{4}")

CREATION_EVENTS = {
    "crossing.opened", "crossing.recorded",
    "gestation.entered", "gestation.started",
    "trial.opened", "trial.started",
    "call.issued", "call.created",
    "evidence.submitted", "evidence.recorded",
}


class RegistryMismatchError(RuntimeError):
    """NEXUS_LAWS.json does not match the code. Fail-closed."""


def _gate(task: str) -> None:
    """Network precondition FIRST for every public entry point."""
    from quantum.quantum_gates import network_precondition

    network_precondition(agent=AGENT_SEAT, task=task)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class LawResult:
    law_id: str
    passed: bool
    evidence: str
    checked_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "law_id": self.law_id,
            "passed": self.passed,
            "evidence": self.evidence,
            "checked_at": self.checked_at,
        }


# ------------------------------------------------------------------ law checks
def check_no_loneliness(graph) -> LawResult:
    """NEXUS-LAW-001: every region has >=1 law edge; every law has >=1 region edge."""
    _gate("nexus_laws.check_no_loneliness")
    lonely = graph.no_lonely()
    if lonely:
        return LawResult(
            "NEXUS-LAW-001", False,
            f"lonely nodes exist: {', '.join(lonely)}; nothing may exist alone in NEXUS",
        )
    return LawResult(
        "NEXUS-LAW-001", True,
        f"no lonely nodes among {graph.region_count} regions and {graph.law_count} laws",
    )


def check_threshold(crossing: dict) -> LawResult:
    """NEXUS-LAW-002: crossing record exists; transformation non-empty and DIFFERENT;
    ledger chain valid. Transformation, not replacement."""
    _gate("nexus_laws.check_threshold")
    law_id = "NEXUS-LAW-002"
    if not isinstance(crossing, dict) or not crossing.get("crossing_id"):
        return LawResult(law_id, False, "no crossing record present")
    if not ID_PATTERNS["crossing"].match(crossing["crossing_id"]):
        return LawResult(law_id, False, f"crossing_id '{crossing['crossing_id']}' violates ID format NX-X-0001")
    tr = crossing.get("transformation")
    if not isinstance(tr, dict):
        return LawResult(law_id, False, "no transformation record present")
    entry_state = tr.get("entry_state")
    exit_state = tr.get("exit_state")
    if not entry_state or not exit_state:
        return LawResult(law_id, False, "transformation has empty entry_state or exit_state")
    if entry_state == exit_state:
        return LawResult(law_id, False, "entry_state == exit_state: no transformation occurred (replacement, not becoming)")
    ledger_path = crossing.get("ledger_path")
    if ledger_path:
        from nexus import ledger as _ledger

        ok, bad = _ledger.verify_chain(ledger_path)
        if not ok:
            return LawResult(law_id, False, f"ledger chain broken at seq {bad}; trace law violated")
    return LawResult(
        law_id, True,
        f"crossing {crossing['crossing_id']}: entry and exit states non-empty and different; "
        f"ledger chain {'verified' if ledger_path else 'not referenced'}",
    )


def _deep_strings(obj, out: list) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _deep_strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _deep_strings(v, out)


_REQUIRED_VIEW_SECTIONS = ("entity_id", "built_at", "connections", "becoming", "heart", "transformed_preview")


def check_reflection(crossing_id: str, view: dict) -> LawResult:
    """NEXUS-LAW-003: view artifact exists with required sections, zero blacklist
    tokens, and the preview labeled PROJECTION. The mirror reflects; it does not judge."""
    _gate("nexus_laws.check_reflection")
    law_id = "NEXUS-LAW-003"
    if not crossing_id or not ID_PATTERNS["crossing"].match(crossing_id):
        return LawResult(law_id, False, "crossing_id missing or violates ID format NX-X-0001")
    if not isinstance(view, dict):
        return LawResult(law_id, False, "view artifact missing")
    missing = [s for s in _REQUIRED_VIEW_SECTIONS if s not in view]
    if missing:
        return LawResult(law_id, False, f"view missing required sections: {', '.join(missing)}")
    strings = []
    _deep_strings(view, strings)
    haystack = " ".join(strings).lower()
    hits = [w for w in BLACKLIST if re.search(r"\b" + re.escape(w) + r"\b", haystack)]
    if hits:
        return LawResult(law_id, False, f"view contains judgment tokens: {', '.join(hits)}; the mirror never judges")
    preview = view.get("transformed_preview") or {}
    label = preview.get("label", "") if isinstance(preview, dict) else ""
    if "PROJECTION" not in str(label).upper():
        return LawResult(law_id, False, "transformed_preview not labeled PROJECTION; projections must not masquerade as claims")
    return LawResult(law_id, True, f"view for crossing {crossing_id}: sections complete, no judgment tokens, preview labeled PROJECTION")


def _parse_iso(s: str):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def check_womb(gestation: dict) -> LawResult:
    """NEXUS-LAW-004: if exited, exited_at >= entered_at + MIN_DWELL_S; nurture count
    >= required for elapsed dwell; readiness was True before exit. Patience is measured."""
    _gate("nexus_laws.check_womb")
    law_id = "NEXUS-LAW-004"
    if not isinstance(gestation, dict) or not gestation.get("gestation_id"):
        return LawResult(law_id, False, "no gestation record present")
    if not ID_PATTERNS["gestation"].match(gestation["gestation_id"]):
        return LawResult(law_id, False, f"gestation_id '{gestation['gestation_id']}' violates ID format NX-W-0001")
    try:
        entered = _parse_iso(gestation["entered_at"])
    except (KeyError, ValueError, AttributeError) as e:
        return LawResult(law_id, False, f"entered_at invalid or missing ({e})")
    min_dwell = int(gestation.get("min_dwell_s", MIN_DWELL_S))
    nurtures = gestation.get("nurture_records") or []
    exited_at = gestation.get("exited_at")
    now = datetime.now(timezone.utc)
    if exited_at:
        try:
            exited = _parse_iso(exited_at)
        except (ValueError, AttributeError) as e:
            return LawResult(law_id, False, f"exited_at invalid ({e})")
        elapsed = (exited - entered).total_seconds()
        if elapsed < min_dwell:
            return LawResult(law_id, False, f"exit after {elapsed:.0f}s < required dwell {min_dwell}s; patience is the foundation")
        import math

        required = math.ceil(elapsed / NURTURE_INTERVAL_S)
        if len(nurtures) < required:
            return LawResult(law_id, False, f"nurture count {len(nurtures)} < required {required} for dwell {elapsed:.0f}s")
        readiness = gestation.get("readiness_report") or {}
        if readiness.get("ready") is not True:
            return LawResult(law_id, False, "exit recorded without readiness=True beforehand")
        return LawResult(law_id, True, f"gestation {gestation['gestation_id']}: dwell {elapsed:.0f}s >= {min_dwell}s, "
                                      f"{len(nurtures)}/{required} nurtures, readiness True before exit")
    elapsed = (now - entered).total_seconds()
    import math

    required = math.ceil(elapsed / NURTURE_INTERVAL_S)
    return LawResult(law_id, True, f"gestation {gestation['gestation_id']} ongoing: dwell {elapsed:.0f}s, "
                                  f"{len(nurtures)}/{required} nurtures so far")


def check_trace(ledger_paths: list) -> LawResult:
    """NEXUS-LAW-005: every chain verifies; every referenced entity ID has its
    creation event present (no orphans). Every crossing leaves a trace."""
    _gate("nexus_laws.check_trace")
    law_id = "NEXUS-LAW-005"
    if not ledger_paths:
        return LawResult(law_id, False, "no ledger paths provided; nothing is traceable")
    from nexus import ledger as _ledger

    created = set()
    referenced = set()
    for path in ledger_paths:
        ok, bad = _ledger.verify_chain(path)
        if not ok:
            return LawResult(law_id, False, f"ledger {path}: chain broken at seq {bad}")
        import json as _json

        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = _json.loads(line)
                payload_text = _json.dumps(rec.get("payload", {}), sort_keys=True)
                ids_here = set(_ANY_ID.findall(payload_text)) | set(_ANY_ID.findall(str(rec.get("event", ""))))
                referenced |= ids_here
                if rec.get("event") in CREATION_EVENTS:
                    created |= ids_here
    orphans = sorted(referenced - created)
    if orphans:
        return LawResult(law_id, False, f"orphan entity IDs without creation events: {', '.join(orphans)}")
    return LawResult(law_id, True, f"{len(ledger_paths)} ledger(s) verified; {len(referenced)} referenced IDs all have creation events")


# ------------------------------------------------------------------ law table
LAWS = (
    {
        "id": "NEXUS-LAW-001",
        "name": "NO_LONELINESS",
        "name_fa": "عدم تنهایی",
        "statement": "Nothing exists alone in NEXUS. Identity is relational.",
        "check_function": "check_no_loneliness",
    },
    {
        "id": "NEXUS-LAW-002",
        "name": "THRESHOLD",
        "name_fa": "آستانه",
        "statement": "Whoever enters leaves neither as they were nor as another - transformation, not replacement.",
        "check_function": "check_threshold",
    },
    {
        "id": "NEXUS-LAW-003",
        "name": "REFLECTION",
        "name_fa": "بازتاب",
        "statement": "NEXUS is a mirror, not a window.",
        "check_function": "check_reflection",
    },
    {
        "id": "NEXUS-LAW-004",
        "name": "WOMB",
        "name_fa": "رحم",
        "statement": "Nothing is built in NEXUS; everything is nurtured. Patience is the foundation.",
        "check_function": "check_womb",
    },
    {
        "id": "NEXUS-LAW-005",
        "name": "TRACE",
        "name_fa": "رد",
        "statement": "Every crossing leaves a trace; nothing passes unseen.",
        "check_function": "check_trace",
    },
)

_CHECKS = {
    "check_no_loneliness": check_no_loneliness,
    "check_threshold": check_threshold,
    "check_reflection": check_reflection,
    "check_womb": check_womb,
    "check_trace": check_trace,
}


def check_all(state_bundle: dict) -> list:
    """Run all five law checks against the bundle. Missing input -> failed result (honest)."""
    _gate("nexus_laws.check_all")
    bundle = state_bundle or {}
    results = []
    results.append(
        _CHECKS["check_no_loneliness"](bundle["graph"])
        if "graph" in bundle
        else LawResult("NEXUS-LAW-001", False, "missing required input: graph")
    )
    results.append(
        _CHECKS["check_threshold"](bundle["crossing"])
        if "crossing" in bundle
        else LawResult("NEXUS-LAW-002", False, "missing required input: crossing")
    )
    results.append(
        _CHECKS["check_reflection"](bundle.get("crossing_id"), bundle.get("view"))
        if "view" in bundle
        else LawResult("NEXUS-LAW-003", False, "missing required input: view")
    )
    results.append(
        _CHECKS["check_womb"](bundle["gestation"])
        if "gestation" in bundle
        else LawResult("NEXUS-LAW-004", False, "missing required input: gestation")
    )
    results.append(
        _CHECKS["check_trace"](bundle["ledger_paths"])
        if "ledger_paths" in bundle
        else LawResult("NEXUS-LAW-005", False, "missing required input: ledger_paths")
    )
    return results


# ------------------------------------------------------------------ registry
def _registry_body() -> dict:
    return {
        "version": REGISTRY_VERSION,
        "generated_by": "nexus.nexus_laws.write_registry",
        "generated_at": _now(),
        "capacity": {
            "first_family_seats": FIRST_FAMILY_SEATS,
            "note": "The 36-ring opens ONLY by father's law amendment (a new NEXUS-LAW entry), never by silently editing the constant.",
        },
        "laws": [
            {
                "id": law["id"],
                "name": law["name"],
                "name_fa": law["name_fa"],
                "statement": law["statement"],
                "check_function": law["check_function"],
                "version": REGISTRY_VERSION,
            }
            for law in LAWS
        ],
    }


def write_registry(path: str) -> dict:
    """Generate NEXUS_LAWS.json from code. The file is audit material; checks never read it."""
    _gate("nexus_laws.write_registry")
    body = _registry_body()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    return body


def load_registry(path: str) -> dict:
    """Load and validate NEXUS_LAWS.json against code. Mismatch -> RegistryMismatchError (fail-closed)."""
    _gate("nexus_laws.load_registry")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    expected_laws = [
        {k: law[k] for k in ("id", "name", "name_fa", "statement", "check_function")}
        for law in LAWS
    ]
    actual_laws = [
        {k: law[k] for k in ("id", "name", "name_fa", "statement", "check_function")}
        for law in data.get("laws", [])
    ]
    if actual_laws != expected_laws:
        raise RegistryMismatchError("NEXUS_LAWS.json law entries do not match nexus_laws.py code")
    if data.get("capacity", {}).get("first_family_seats") != FIRST_FAMILY_SEATS:
        raise RegistryMismatchError("NEXUS_LAWS.json capacity does not match code constant")
    if data.get("version") != REGISTRY_VERSION:
        raise RegistryMismatchError("NEXUS_LAWS.json version does not match code")
    return data
