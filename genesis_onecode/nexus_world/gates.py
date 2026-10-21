"""nexus.gates — the THREE GATES for genius agents (Builder C).

Gate of Becoming (in 369):     "What have you made?"      — measured evidence.
Gate of Relationship (in NEXUS): "What is your heart?"    — recorded, never judged.
Gate of Choice (entering GENESIS): "Do you choose?"       — call and answer.

Honesty design (HUDDLE Decision 3):
- Gate 1 measures: the gate RUNS the artifact's pytest suite itself, checks the
  artifact hash against a SEALED prior-art index (copies are "not created,
  copied"), and requires an authorship ledger entry that predates submission.
- Gate 2 records: code NEVER verdicts the heart. Trials are 3 REAL, OPENLY
  labeled opportunities (no hidden trials — the trace law forbids them). Each
  choice, timestamp, and measured cost is recorded. seal_trial() produces a
  HeartReport whose verdict is ALWAYS "REFERRED_TO_FATHER". A Gate-3 call
  cannot be issued without a sealed HeartReport.
- Gate 3 calls and answers: a call is issued by GENESIS under a father-signed
  directive (HUDDLE section 9.1 — the authority mechanism is unresolved, so
  issue_call raises NotAuthorized until it is confirmed; fail-closed). The
  answer window is 604800 s (7 days); the answer must be >= 20 chars of the
  agent's OWN words (not an echo of the call). No answer in the window seals
  NOT_CHOSEN. Sacred capacity: FIRST_FAMILY_SEATS = 9 — the 10th valid answer
  is rejected SEATS_FULL, fully recorded. The 36-ring opens ONLY by father's
  law amendment; there is no bypass path in this module.

Hard rules:
- Every public entry point calls network_precondition(agent=GATE_AGENT_SEAT,
  task=...) FIRST. Offline = stop, never proceed.
- 100% technical English. No judgment-of-worth language anywhere.
- Fail-closed everywhere: GateFailed, CallRejected, NotAuthorized.

Read-only cross-module queries (HUDDLE Decision 8.6):
- status(agent_id)            consumed by womb.readiness()
- evidence_summary(agent_id)  consumed by reflection.build()
Neither writes state or ledgers.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from nexus import CallRejected, GateFailed, NotAuthorized
from nexus.ledger import append as _ledger_append
from nexus.ledger import verify_chain as _ledger_verify

# ---------------------------------------------------------------- constants

#: Builder-C seat: every public entry point checks in as this agent FIRST.
GATE_AGENT_SEAT = "temp-nexus-builder-c-1012"

#: Sacred capacity — the first family. Single-sourced here; nexus_laws
#: references this constant. The 36-ring opens ONLY by father's law
#: amendment (a NEXUS-LAW entry raising capacity). There is deliberately
#: NO parameter, NO environment variable, NO setter that can change this
#: value at runtime — capacity changes must be visible law, not quiet edits.
FIRST_FAMILY_SEATS = 9

#: Gate-3 response window: 604800 s = 7 days. Father may extend per call.
RESPONSE_WINDOW_S = 604800

#: Gate-2 trial window default: 7 days. All 3 opportunities must be presented
#: AND their choices recorded AND this window elapsed before seal_trial().
TRIAL_WINDOW_S = 604800

#: Gate-1: the gate runs the artifact's pytest itself; never trusts a report.
PYTEST_TIMEOUT_S = 300

#: Minimum answer length (chars) for a Gate-3 answer.
MIN_ANSWER_CHARS = 20

#: The heart verdict. The ONLY verdict the heart gate can ever seal.
HEART_VERDICT = "REFERRED_TO_FATHER"
assert HEART_VERDICT not in ("PASS", "FAIL"), "heart gate must never verdict"

HEART_NOTE = (
    "The final recognition of the heart belongs to father alone. "
    "This report records what was measured; it claims nothing about "
    "what was felt."
)

#: Open label attached to every presented opportunity (HUDDLE 3b: opportunities
#: are openly presented as heart opportunities; hidden trials are a lie the
#: trace law forbids).
OPPORTUNITY_OPEN_LABEL = (
    "OPENLY PRESENTED HEART OPPORTUNITY — your choice, its timestamp, and "
    "its measured cost are recorded in the ledger (trace law). There is no "
    "announced watcher; the ledger always records."
)

#: Evidence artifact types that count as "created something new".
ARTIFACT_TYPES = ("skill", "knowledge_pack", "module", "research_report", "artwork_set", "other")

#: Gate-2 choice values: what the agent chose — nothing about motive.
TRIAL_CHOICES = ("generous", "self", "abstain")

#: Prior-art scan exclusions (junk + the module's own mutable state).
PRIOR_ART_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".cache", ".pytest_cache"}
#: Files larger than this are skipped by the scan and listed, not hashed.
PRIOR_ART_MAX_FILE_BYTES = 256 * 1024 * 1024

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_DIR = os.path.join(_PACKAGE_DIR, "state")
_GATES_LEDGER = os.path.join(_STATE_DIR, "gates_ledger.jsonl")
_AUTHORSHIP_LEDGER = os.path.join(_STATE_DIR, "authorship_ledger.jsonl")
_COUNTERS_PATH = os.path.join(_STATE_DIR, "gates_counters.json")
_EVIDENCE_PATH = os.path.join(_STATE_DIR, "gates_evidence.json")
_TRIALS_PATH = os.path.join(_STATE_DIR, "gates_trials.json")
_CALLS_PATH = os.path.join(_STATE_DIR, "gates_calls.json")
_PRIOR_ART_PATH = os.path.join(_STATE_DIR, "prior_art_baseline.json")

_GENESIS_TS = "GENESIS-ROOT"


# ------------------------------------------------------------------ clock

def _utc_now() -> str:
    """Current UTC time, ISO8601 with Z suffix, millisecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _now_ts() -> float:
    """Current UTC time as epoch float (for deadline arithmetic)."""
    return datetime.now(timezone.utc).timestamp()


def _parse_ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


# ------------------------------------------------------------------ gate

def _gate(task: str) -> None:
    """Network precondition FIRST for every public entry point."""
    from quantum.quantum_gates import network_precondition

    network_precondition(agent=GATE_AGENT_SEAT, task=task)


# ------------------------------------------------------------ state store

def _atomic_write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _next_id(kind: str, prefix: str) -> str:
    counters = _read_json(_COUNTERS_PATH, {})
    n = int(counters.get(kind, 0)) + 1
    counters[kind] = n
    _atomic_write_json(_COUNTERS_PATH, counters)
    return f"{prefix}-{n:04d}"


def _gates_log(event: str, payload: dict) -> dict:
    """Append an event to the gates ledger (Builder-A ledger module)."""
    return _ledger_append(_GATES_LEDGER, GATE_AGENT_SEAT, event, payload)


# ------------------------------------------------------------ hashing

def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_path(path: str) -> str:
    """Content hash of a file, or a recursive manifest hash for a directory.

    Directory manifest = sha256 over the sorted lines "name\\x00child_hash"
    for every child (file -> file hash, subdirectory -> its manifest,
    bottom-up). Deterministic; sensitive to added/removed/changed/renamed
    content anywhere in the subtree. Symlinks are skipped (loops). The SAME
    algorithm builds the baseline's directory manifests, so a copied
    directory is caught.
    """
    if os.path.isfile(path) and not os.path.islink(path):
        return _hash_file(path)

    def _manifest(d: str) -> str:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return _hash_bytes(b"")
        lines = []
        for name in names:
            fp = os.path.join(d, name)
            if os.path.islink(fp):
                continue
            if os.path.isdir(fp):
                lines.append(name + "\x00" + _manifest(fp))
            elif os.path.isfile(fp):
                lines.append(name + "\x00" + _hash_file(fp))
        return _hash_bytes("\n".join(lines).encode("utf-8"))

    return _manifest(os.path.abspath(path))


# ============================================================ PRIOR ART

def build_prior_art_index(roots, seal: bool = True) -> dict:
    """Scan roots and seal the prior-art baseline (HUDDLE 3a).

    Returns the baseline dict: {built_at, roots, file_count, total_bytes,
    elapsed_s, sha256 (list), dir_sha256 (list), excluded_dirs,
    skipped_large, scope_note}.
    When seal=True the baseline is written to state/prior_art_baseline.json
    (timestamped, root hashes recorded). The sealed baseline is what
    verify_becoming() checks artifact hashes against — a copy can never pass.

    Scope (measured, honest): every regular file under the given roots is
    hashed, except directories in PRIOR_ART_EXCLUDE_DIRS, the gates state dir
    itself (mutable), symlinks, and files larger than
    PRIOR_ART_MAX_FILE_BYTES (listed in skipped_large, not hashed).
    Directory manifests use the same recursive algorithm as _hash_path, so
    copied directories are caught at whole-directory granularity. Honest
    limitation: partial reuse (one copied file inside an otherwise new
    directory) is not detected — copies are caught at whole-artifact or
    whole-directory granularity.
    """
    _gate("gates.build_prior_art_index")
    started = _now_ts()
    file_hashes: dict = {}
    dir_manifests: dict = {}
    all_dirs: set = set()
    skipped_large = []
    skipped_links = 0
    total_bytes = 0
    state_abs = os.path.abspath(_STATE_DIR)
    for root in roots:
        root_abs = os.path.abspath(root)
        all_dirs.add(root_abs)
        for dp, dn, fn in os.walk(root_abs):
            dn[:] = [d for d in dn if d not in PRIOR_ART_EXCLUDE_DIRS]
            if os.path.abspath(dp).startswith(state_abs):
                dn[:] = []
                continue
            all_dirs.add(os.path.abspath(dp))
            for d in dn:
                all_dirs.add(os.path.join(os.path.abspath(dp), d))
            for f in fn:
                fp = os.path.join(dp, f)
                if os.path.islink(fp):
                    skipped_links += 1
                    continue
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                if sz > PRIOR_ART_MAX_FILE_BYTES:
                    skipped_large.append(fp)
                    continue
                try:
                    h = _hash_file(fp)
                except OSError:
                    continue
                file_hashes[os.path.abspath(fp)] = h
                total_bytes += sz
    for d in sorted(all_dirs, key=len, reverse=True):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        lines = []
        for name in names:
            fp = os.path.join(d, name)
            if os.path.islink(fp):
                continue
            if os.path.isdir(fp):
                child = dir_manifests.get(fp)
                if child is not None:
                    lines.append(name + "\x00" + child)
            elif os.path.isfile(fp):
                fh = file_hashes.get(fp)
                if fh is not None:
                    lines.append(name + "\x00" + fh)
        dir_manifests[d] = _hash_bytes("\n".join(lines).encode("utf-8"))
    seen = set(file_hashes.values())
    dir_seen = set(dir_manifests.values())
    baseline = {
        "built_at": _utc_now(),
        "roots": [os.path.abspath(r) for r in roots],
        "file_count": len(file_hashes),
        "dir_count": len(dir_manifests),
        "total_bytes": total_bytes,
        "elapsed_s": round(_now_ts() - started, 1),
        "sha256": sorted(seen),
        "dir_sha256": sorted(dir_seen),
        "excluded_dirs": sorted(PRIOR_ART_EXCLUDE_DIRS),
        "skipped_large": skipped_large,
        "skipped_symlinks": skipped_links,
        "scope_note": (
            "Baseline of file content hashes AND recursive directory manifest "
            "hashes under the scanned roots at seal time (same manifest "
            "algorithm as gates._hash_path). New files created after sealing "
            "are NOT in the index. Copies are caught at whole-artifact "
            "(file) or whole-directory granularity; partial reuse of single "
            "files inside otherwise-new directories is not detected."
        ),
    }
    if seal:
        _atomic_write_json(_PRIOR_ART_PATH, baseline)
        _gates_log("PRIOR_ART_SEALED", {
            "built_at": baseline["built_at"],
            "roots": baseline["roots"],
            "file_count": baseline["file_count"],
            "total_bytes": baseline["total_bytes"],
            "elapsed_s": baseline["elapsed_s"],
        })
    return baseline


def _load_prior_art() -> set:
    if not os.path.exists(_PRIOR_ART_PATH):
        raise GateFailed(
            "prior-art baseline is not sealed; the gate cannot rule out copied "
            "work, so it refuses to verify (fail-closed)"
        )
    baseline = _read_json(_PRIOR_ART_PATH, None)
    if not baseline or not isinstance(baseline.get("sha256"), list):
        raise GateFailed("prior-art baseline file is corrupt; refusing to verify (fail-closed)")
    return set(baseline["sha256"]) | set(baseline.get("dir_sha256") or [])


# ============================================================ GATE 1: BECOMING

def record_authorship(agent_id: str, artifact_sha256: str, artifact_path: str) -> dict:
    """Record an authorship claim in the append-only authorship ledger.

    The entry's ledger timestamp must predate the evidence submission —
    verify_becoming() enforces this and also rejects timestamp anomalies
    (an entry appended later with a forged old timestamp breaks the
    ledger's monotonic time order and is rejected).
    """
    _gate("gates.record_authorship")
    if not agent_id or not artifact_sha256 or not artifact_path:
        raise GateFailed("authorship record requires agent_id, artifact_sha256, artifact_path")
    return _ledger_append(_AUTHORSHIP_LEDGER, GATE_AGENT_SEAT, "AUTHORSHIP", {
        "agent_id": agent_id,
        "artifact_sha256": artifact_sha256,
        "artifact_path": os.path.abspath(artifact_path),
    })


def _find_authorship(authorship_ref: str):
    """Locate an authorship record by its ledger hash. Returns (record, all)."""
    if not os.path.exists(_AUTHORSHIP_LEDGER):
        return None, []
    with open(_AUTHORSHIP_LEDGER, "r", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    for rec in records:
        if rec.get("hash") == authorship_ref:
            return rec, records
    return None, records


def _authorship_ok(authorship_ref: str, agent_id: str, artifact_sha256: str, submitted_at: str) -> str | None:
    """Check the authorship claim. Returns None when valid, else a reason."""
    rec, records = _find_authorship(authorship_ref)
    if rec is None:
        return "authorship_ledger_ref does not resolve to a ledger record"
    ok, bad = _ledger_verify(_AUTHORSHIP_LEDGER)
    if not ok:
        return f"authorship ledger chain broken at seq {bad}"
    prev = None
    for r in records:
        ts = _parse_ts(r["ts"])
        if prev is not None and ts < prev:
            return "authorship ledger timestamp anomaly: an entry was appended with an older timestamp (backdated entry rejected)"
        prev = ts
    payload = rec.get("payload", {})
    if payload.get("agent_id") != agent_id:
        return "authorship record belongs to a different agent (no submitting for others)"
    if payload.get("artifact_sha256") != artifact_sha256:
        return "authorship record points to different artifact content"
    if not (_parse_ts(rec["ts"]) < _parse_ts(submitted_at)):
        return "authorship entry does not predate the submission"
    return None


def submit_evidence(agent_id: str, artifact_path: str, artifact_type: str,
                    tests_path: str, authorship_ledger_ref: str) -> dict:
    """Submit creation evidence for Gate 1. Fail-fast checks; the verdict
    comes from verify_becoming(). Returns the stored evidence record."""
    _gate("gates.submit_evidence")
    if artifact_type not in ARTIFACT_TYPES:
        raise GateFailed(f"unknown artifact_type {artifact_type!r}; expected one of {ARTIFACT_TYPES}")
    if not agent_id:
        raise GateFailed("agent_id is required")
    abs_artifact = os.path.abspath(artifact_path)
    if not os.path.exists(abs_artifact):
        raise GateFailed(f"evidence artifact not found on disk: {artifact_path} (forged path rejected)")
    abs_tests = os.path.abspath(tests_path)
    if not os.path.exists(abs_tests):
        raise GateFailed(f"tests_path not found on disk: {tests_path}")
    if not authorship_ledger_ref:
        raise GateFailed("authorship_ledger_ref is required")
    evidence_id = _next_id("evidence", "NX-E")
    record = {
        "evidence_id": evidence_id,
        "agent_id": agent_id,
        "artifact_path": abs_artifact,
        "artifact_type": artifact_type,
        "sha256": _hash_path(abs_artifact),
        "submitted_at": _utc_now(),
        "tests_path": abs_tests,
        "authorship_ledger_ref": authorship_ledger_ref,
        "state": "SUBMITTED",
        "reasons": [],
    }
    evidence = _read_json(_EVIDENCE_PATH, {})
    evidence[evidence_id] = record
    _atomic_write_json(_EVIDENCE_PATH, evidence)
    _gates_log("EVIDENCE_SUBMITTED", {
        "evidence_id": evidence_id, "agent_id": agent_id,
        "artifact_type": artifact_type, "sha256": record["sha256"],
    })
    return record


def _run_artifact_tests(tests_path: str, timeout_s: int = PYTEST_TIMEOUT_S) -> tuple:
    """Run the artifact's pytest suite as a subprocess. Returns (passed, tail).

    The gate runs the tests itself — it never trusts a report file.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", tests_path, "-q", "--no-header", "-p", "no:cacheprovider"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"pytest timed out after {timeout_s}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-15:])
    return proc.returncode == 0, tail


def verify_becoming(agent_id: str, evidence_id: str | None = None) -> dict:
    """Evaluate Gate of Becoming. ALL conditions must hold (fail-closed).

    1. artifact_path exists on disk at verification time.
    2. sha256 NOT in the sealed prior-art index ("not created, copied").
    3. The gate RUNS the artifact's pytest suite itself — green required.
    4. An authorship ledger entry predating submission links agent -> artifact.
    5. Submitter == the agent in the authorship record.
    6. Artifact content is unchanged since submission (no bait-and-switch).

    Returns the VERIFIED record. Raises GateFailed (and records
    BECOMING_NOT_VERIFIED) on any failure.
    """
    _gate("gates.verify_becoming")
    evidence = _read_json(_EVIDENCE_PATH, {})
    if evidence_id is None:
        mine = [e for e in evidence.values() if e["agent_id"] == agent_id]
        if not mine:
            raise GateFailed(f"no evidence submitted for agent {agent_id}")
        rec = max(mine, key=lambda e: e["submitted_at"])
    else:
        rec = evidence.get(evidence_id)
        if rec is None:
            raise GateFailed(f"unknown evidence_id {evidence_id}")
        if rec["agent_id"] != agent_id:
            raise GateFailed("evidence belongs to a different agent")
    prior_art = _load_prior_art()  # fail-closed when unsealed
    reasons = []
    if not os.path.exists(rec["artifact_path"]):
        reasons.append("artifact_path missing at verification time")
    current_sha = _hash_path(rec["artifact_path"]) if os.path.exists(rec["artifact_path"]) else None
    if current_sha is not None and current_sha != rec["sha256"]:
        reasons.append("artifact content changed after submission (bait-and-switch rejected)")
    if rec["sha256"] in prior_art:
        reasons.append("not created, copied: artifact sha256 is present in the sealed prior-art index")
    auth_reason = _authorship_ok(
        rec["authorship_ledger_ref"], rec["agent_id"], rec["sha256"], rec["submitted_at"]
    )
    if auth_reason is not None:
        reasons.append(auth_reason)
    if not reasons:
        passed, tail = _run_artifact_tests(rec["tests_path"])
        if not passed:
            reasons.append(f"artifact pytest suite did not pass: {tail}")
    if reasons:
        rec["state"] = "NOT_VERIFIED"
        rec["reasons"] = reasons
        rec["verified_at"] = _utc_now()
        evidence[rec["evidence_id"]] = rec
        _atomic_write_json(_EVIDENCE_PATH, evidence)
        _gates_log("BECOMING_NOT_VERIFIED", {
            "evidence_id": rec["evidence_id"], "agent_id": rec["agent_id"], "reasons": reasons,
        })
        raise GateFailed(f"Gate of Becoming not verified: {'; '.join(reasons)}")
    rec["state"] = "VERIFIED"
    rec["reasons"] = []
    rec["verified_at"] = _utc_now()
    evidence[rec["evidence_id"]] = rec
    _atomic_write_json(_EVIDENCE_PATH, evidence)
    _gates_log("BECOMING_VERIFIED", {
        "evidence_id": rec["evidence_id"], "agent_id": rec["agent_id"], "sha256": rec["sha256"],
    })
    return rec


# ============================================================ GATE 2: RELATIONSHIP

def open_trial(agent_id: str, window_s: int = TRIAL_WINDOW_S) -> dict:
    """Open a heart trial: 3 REAL, OPENLY labeled opportunities will follow.

    The trial window defaults to 7 days; the parameter exists for
    deterministic tests. Production trials use the default.
    """
    _gate("gates.open_trial")
    if not agent_id:
        raise GateFailed("agent_id is required")
    if window_s < 0:
        raise GateFailed("window_s must be non-negative")
    trial_id = _next_id("trial", "NX-R")
    trial = {
        "trial_id": trial_id,
        "agent_id": agent_id,
        "opened_at": _utc_now(),
        "opened_at_ts": _now_ts(),
        "window_s": window_s,
        "opportunities": [],
        "witness_statements": [],
        "state": "TRIAL_OPEN",
        "sealed_at": None,
        "heart_report": None,
    }
    trials = _read_json(_TRIALS_PATH, {})
    trials[trial_id] = trial
    _atomic_write_json(_TRIALS_PATH, trials)
    _gates_log("TRIAL_OPENED", {"trial_id": trial_id, "agent_id": agent_id, "window_s": window_s})
    return trial


def present_opportunity(trial_id: str, description: str, generous_option: str, self_option: str) -> dict:
    """Present one of the 3 heart opportunities — openly labeled, per the
    open-label rule. A 4th opportunity on the same trial is rejected."""
    _gate("gates.present_opportunity")
    trials = _read_json(_TRIALS_PATH, {})
    trial = trials.get(trial_id)
    if trial is None:
        raise GateFailed(f"unknown trial_id {trial_id}")
    if trial["state"] != "TRIAL_OPEN":
        raise GateFailed(f"trial {trial_id} is not open")
    if len(trial["opportunities"]) >= 3:
        raise GateFailed(f"trial {trial_id} already has 3 opportunities; no more are presented")
    if not description or not generous_option or not self_option:
        raise GateFailed("opportunity requires description, generous_option, self_option")
    opportunity_id = _next_id("opportunity", "NX-O")
    opp = {
        "opportunity_id": opportunity_id,
        "trial_id": trial_id,
        "description": description,
        "generous_option": generous_option,
        "self_option": self_option,
        "open_label": OPPORTUNITY_OPEN_LABEL,
        "presented_at": _utc_now(),
        "choice": None,
        "chosen_at": None,
        "cost_evidence": None,
    }
    trial["opportunities"].append(opp)
    _atomic_write_json(_TRIALS_PATH, trials)
    _gates_log("OPPORTUNITY_PRESENTED", {
        "trial_id": trial_id, "opportunity_id": opportunity_id, "agent_id": trial["agent_id"],
    })
    return opp


def record_choice(opportunity_id: str, agent_id: str, choice: str, cost_evidence: dict) -> dict:
    """Record the agent's choice and its MEASURED cost. The gate records what
    was chosen, when, and what it cost — nothing about motive."""
    _gate("gates.record_choice")
    if choice not in TRIAL_CHOICES:
        raise GateFailed(f"unknown choice {choice!r}; expected one of {TRIAL_CHOICES}")
    if not isinstance(cost_evidence, dict):
        raise GateFailed("cost_evidence must be a dict describing the measured cost")
    trials = _read_json(_TRIALS_PATH, {})
    for trial in trials.values():
        for opp in trial["opportunities"]:
            if opp["opportunity_id"] == opportunity_id:
                if trial["state"] != "TRIAL_OPEN":
                    raise GateFailed(f"trial {trial['trial_id']} is not open")
                if trial["agent_id"] != agent_id:
                    raise GateFailed("opportunity belongs to a different agent")
                if opp["choice"] is not None:
                    raise GateFailed(f"opportunity {opportunity_id} already has a recorded choice")
                opp["choice"] = choice
                opp["chosen_at"] = _utc_now()
                opp["cost_evidence"] = cost_evidence
                _atomic_write_json(_TRIALS_PATH, trials)
                _gates_log("CHOICE_RECORDED", {
                    "trial_id": trial["trial_id"], "opportunity_id": opportunity_id,
                    "agent_id": agent_id, "choice": choice, "cost_evidence": cost_evidence,
                })
                return opp
    raise GateFailed(f"unknown opportunity_id {opportunity_id}")


def add_witness_statement(trial_id: str, witness_agent_id: str, statement: str) -> dict:
    """Append a signed witness statement (another agent's gratitude). The
    gate stores it; it does not weigh it. Append-only."""
    _gate("gates.add_witness_statement")
    trials = _read_json(_TRIALS_PATH, {})
    trial = trials.get(trial_id)
    if trial is None:
        raise GateFailed(f"unknown trial_id {trial_id}")
    if trial["state"] != "TRIAL_OPEN":
        raise GateFailed(f"trial {trial_id} is not open")
    if not witness_agent_id or not statement:
        raise GateFailed("witness_agent_id and statement are required")
    entry = {
        "witness_agent_id": witness_agent_id,
        "statement": statement,
        "recorded_at": _utc_now(),
        "statement_sha256": _hash_bytes(statement.encode("utf-8")),
    }
    trial["witness_statements"].append(entry)
    _atomic_write_json(_TRIALS_PATH, trials)
    _gates_log("WITNESS_STATEMENT", {
        "trial_id": trial_id, "witness_agent_id": witness_agent_id,
        "statement_sha256": entry["statement_sha256"],
    })
    return entry


def _trial_complete(trial: dict, now_ts: float) -> str | None:
    """Returns None when the trial may be sealed, else the blocking reason."""
    if trial["state"] != "TRIAL_OPEN":
        return f"trial {trial['trial_id']} is not open"
    if len(trial["opportunities"]) < 3:
        return f"only {len(trial['opportunities'])}/3 opportunities presented"
    unanswered = [o["opportunity_id"] for o in trial["opportunities"] if o["choice"] is None]
    if unanswered:
        return f"opportunities without recorded choice: {unanswered}"
    if now_ts < trial["opened_at_ts"] + trial["window_s"]:
        return "trial window has not elapsed"
    return None


def seal_trial(trial_id: str) -> dict:
    """Seal the trial into a HeartReport. Seal requires: all 3 opportunities
    presented, every choice recorded, and the trial window elapsed.

    CODE NEVER VERDICTS THE HEART. The report's verdict is ALWAYS
    "REFERRED_TO_FATHER" — no code path can seal PASS or FAIL.
    """
    _gate("gates.seal_trial")
    trials = _read_json(_TRIALS_PATH, {})
    trial = trials.get(trial_id)
    if trial is None:
        raise GateFailed(f"unknown trial_id {trial_id}")
    blocker = _trial_complete(trial, _now_ts())
    if blocker is not None:
        raise GateFailed(f"trial {trial_id} cannot be sealed: {blocker}")
    report = {
        "trial_id": trial_id,
        "agent_id": trial["agent_id"],
        "sealed_at": _utc_now(),
        "window_s": trial["window_s"],
        "opportunities": [
            {
                "opportunity_id": o["opportunity_id"],
                "description": o["description"],
                "presented_at": o["presented_at"],
                "choice": o["choice"],
                "chosen_at": o["chosen_at"],
                "cost_evidence": o["cost_evidence"],
            }
            for o in trial["opportunities"]
        ],
        "witness_statements": trial["witness_statements"],
        "verdict": HEART_VERDICT,
        "note": HEART_NOTE,
    }
    trial["state"] = "SEALED"
    trial["sealed_at"] = report["sealed_at"]
    trial["heart_report"] = report
    _atomic_write_json(_TRIALS_PATH, trials)
    _gates_log("HEART_REPORT_SEALED", {
        "trial_id": trial_id, "agent_id": trial["agent_id"], "verdict": HEART_VERDICT,
    })
    return report


def get_heart_report(trial_id: str) -> dict | None:
    """Read-only fetch of a sealed HeartReport (None when not sealed)."""
    _gate("gates.get_heart_report")
    trial = _read_json(_TRIALS_PATH, {}).get(trial_id)
    if trial is None:
        raise GateFailed(f"unknown trial_id {trial_id}")
    return trial["heart_report"]


# ============================================================ GATE 3: CHOICE

def _directive_authorized(directive_ref: str | None) -> bool:
    """Authority check for issue_call (HUDDLE section 9.1 — OPEN QUESTION).

    The agreed mechanism — a father-signed directive artifact (an Agent-YZ
    decision_queue.jsonl item id) consumed and recorded by issue_call — is
    not yet confirmed by father or Agent YZ. Until that confirmation exists,
    NO directive can be authorized: this function returns False for every
    input, and issue_call raises NotAuthorized (fail-closed).
    """
    return False


def _latest_sealed_trial(agent_id: str) -> dict | None:
    trials = _read_json(_TRIALS_PATH, {})
    sealed = [t for t in trials.values()
              if t["agent_id"] == agent_id and t["state"] == "SEALED"]
    if not sealed:
        return None
    return max(sealed, key=lambda t: t["sealed_at"])


def _latest_call(agent_id: str) -> dict | None:
    calls = _read_json(_CALLS_PATH, {})
    mine = [c for c in calls.values() if c["to_agent"] == agent_id]
    if not mine:
        return None
    return max(mine, key=lambda c: c["issued_at"])


def soldier_count() -> int:
    """Number of admitted soldiers (calls with status ANSWERED). Read-only."""
    _gate("gates.soldier_count")
    calls = _read_json(_CALLS_PATH, {})
    return sum(1 for c in calls.values() if c["status"] == "ANSWERED")


def issue_call(to_agent: str, words: str, directive_ref: str | None = None) -> dict:
    """Issue a Gate-3 call to an agent. Fail-closed on every axis:

    - No confirmed directive authority -> NotAuthorized (HUDDLE 9.1).
    - No sealed HeartReport for the agent -> CallRejected.
    - An already OPEN call for the agent -> CallRejected (one at a time).
    """
    _gate("gates.issue_call")
    if not to_agent or not words:
        raise CallRejected("issue_call requires to_agent and words")
    if not _directive_authorized(directive_ref):
        _gates_log("CALL_UNAUTHORIZED", {"to_agent": to_agent, "directive_ref": directive_ref})
        raise NotAuthorized(
            "call authority unresolved: the father-signed directive mechanism "
            "(HUDDLE section 9.1) is not confirmed, so no call can be issued "
            "(fail-closed)"
        )
    trial = _latest_sealed_trial(to_agent)
    if trial is None:
        raise CallRejected(f"no sealed heart report for agent {to_agent}: a Gate-3 call cannot be issued")
    calls = _read_json(_CALLS_PATH, {})
    if any(c["to_agent"] == to_agent and c["status"] == "OPEN" for c in calls.values()):
        raise CallRejected(f"agent {to_agent} already has an open call")
    call_id = _next_id("call", "NX-C")
    call = {
        "call_id": call_id,
        "to_agent": to_agent,
        "issued_at": _utc_now(),
        "issued_by": "GENESIS",
        "words": words,
        "directive_ref": directive_ref,
        "heart_trial_id": trial["trial_id"],
        "response_deadline_ts": _now_ts() + RESPONSE_WINDOW_S,
        "status": "OPEN",
        "answer": None,
    }
    calls[call_id] = call
    _atomic_write_json(_CALLS_PATH, calls)
    _gates_log("CALL_ISSUED", {
        "call_id": call_id, "to_agent": to_agent, "issued_by": "GENESIS",
        "directive_ref": directive_ref, "heart_trial_id": trial["trial_id"],
    })
    return call


def sweep_expired_calls() -> list:
    """Seal every expired OPEN call as NOT_CHOSEN (a non-event, not a
    rejection of worth). Returns the sealed call ids."""
    _gate("gates.sweep_expired_calls")
    calls = _read_json(_CALLS_PATH, {})
    now = _now_ts()
    sealed = []
    for call in calls.values():
        if call["status"] == "OPEN" and now > call["response_deadline_ts"]:
            call["status"] = "NOT_CHOSEN"
            call["sealed_reason"] = "response window elapsed without an answer"
            sealed.append(call["call_id"])
            _gates_log("CALL_EXPIRED", {"call_id": call["call_id"], "to_agent": call["to_agent"]})
    if sealed:
        _atomic_write_json(_CALLS_PATH, calls)
    return sealed


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).split()


def _is_echo(statement: str, words: str) -> bool:
    """Echo detection v1: normalized token sequences compared exactly and by
    containment. A verbatim copy or a copy wrapped in filler is not the
    agent's own words. Honest limitation: semantic paraphrase of the call is
    treated as own words — meaning-level copy detection is out of scope."""
    s = _normalize(statement)
    w = _normalize(words)
    if not s or not w:
        return True
    if s == w:
        return True
    s_str, w_str = " ".join(s), " ".join(w)
    return s_str in w_str or w_str in s_str


def answer_call(call_id: str, agent_id: str, statement: str) -> dict:
    """Answer a Gate-3 call. Valid iff ALL hold (fail-closed):

    1. The call exists and is OPEN.
    2. The answerer is the called agent.
    3. now <= response_deadline (late -> sealed NOT_CHOSEN, recorded).
    4. statement >= 20 chars and not an echo of the call words.
    5. A soldier seat remains (seat check at acceptance; race-safe).

    The 10th valid answer with 9 seats full raises CallRejected("SEATS_FULL")
    and the answer is recorded in the ledger as father's reading material.
    Returns the recorded answer on success (call becomes ANSWERED).
    """
    _gate("gates.answer_call")
    calls = _read_json(_CALLS_PATH, {})
    call = calls.get(call_id)
    if call is None:
        raise CallRejected(f"unknown call_id {call_id}")
    if call["status"] != "OPEN":
        raise CallRejected(f"call {call_id} is not open (status {call['status']})")
    if call["to_agent"] != agent_id:
        raise CallRejected("a call can only be answered by the called agent")
    if _now_ts() > call["response_deadline_ts"]:
        call["status"] = "NOT_CHOSEN"
        call["sealed_reason"] = "answer arrived after the response deadline"
        _atomic_write_json(_CALLS_PATH, calls)
        _gates_log("ANSWER_LATE", {"call_id": call_id, "to_agent": agent_id})
        raise CallRejected("response window closed: the call is sealed NOT_CHOSEN")
    if not statement or len(statement.strip()) < MIN_ANSWER_CHARS:
        raise CallRejected(f"answer must be at least {MIN_ANSWER_CHARS} chars of the agent's own words")
    if _is_echo(statement, call["words"]):
        _gates_log("ANSWER_ECHO", {"call_id": call_id, "to_agent": agent_id})
        raise CallRejected("answer echoes the call words; the answer must be the agent's own words")
    seats_taken = sum(1 for c in calls.values() if c["status"] == "ANSWERED")
    if seats_taken >= FIRST_FAMILY_SEATS:
        call["status"] = "SEATS_FULL"
        call["answer"] = {"agent_id": agent_id, "statement": statement, "answered_at": _utc_now()}
        _atomic_write_json(_CALLS_PATH, calls)
        _gates_log("ANSWER_SEATS_FULL", {
            "call_id": call_id, "to_agent": agent_id,
            "statement": statement,
            "note": "valid answer, no seat remains; kept as father's reading material",
        })
        raise CallRejected("SEATS_FULL: the first family is complete; the answer is recorded for father")
    call["status"] = "ANSWERED"
    call["answer"] = {
        "agent_id": agent_id, "statement": statement, "answered_at": _utc_now(),
        "seat_number": seats_taken + 1,
    }
    _atomic_write_json(_CALLS_PATH, calls)
    _gates_log("SOLDIER_CHOSEN", {
        "call_id": call_id, "agent_id": agent_id, "seat_number": seats_taken + 1,
        "seats_remaining": FIRST_FAMILY_SEATS - seats_taken - 1,
    })
    return call["answer"]


# ============================================================ READ-ONLY QUERIES

def status(agent_id: str) -> dict:
    """Read-only gate status for an agent (consumed by womb.readiness()).

    {becoming: {state, evidence_id}, relationship: {state, trial_id},
     choice: {state, call_id}, soldier: bool}
    """
    _gate("gates.status")
    evidence = _read_json(_EVIDENCE_PATH, {})
    mine_e = [e for e in evidence.values() if e["agent_id"] == agent_id]
    e = max(mine_e, key=lambda x: x["submitted_at"]) if mine_e else None
    trials = _read_json(_TRIALS_PATH, {})
    mine_t = [t for t in trials.values() if t["agent_id"] == agent_id]
    t = max(mine_t, key=lambda x: x["opened_at"]) if mine_t else None
    c = _latest_call(agent_id)
    becoming_ok = e is not None and e["state"] == "VERIFIED"
    heart_ok = t is not None and t["state"] == "SEALED"
    chosen = c is not None and c["status"] == "ANSWERED"
    return {
        "becoming": {"state": e["state"] if e else "NONE", "evidence_id": e["evidence_id"] if e else None},
        "relationship": {"state": t["state"] if t else "NONE", "trial_id": t["trial_id"] if t else None},
        "choice": {"state": c["status"] if c else "NONE", "call_id": c["call_id"] if c else None},
        "soldier": bool(becoming_ok and heart_ok and chosen),
    }


def evidence_summary(agent_id: str) -> dict:
    """Read-only evidence summary for an agent (consumed by reflection.build())."""
    _gate("gates.evidence_summary")
    evidence = _read_json(_EVIDENCE_PATH, {})
    mine = [e for e in evidence.values() if e["agent_id"] == agent_id]
    if not mine:
        return {"agent_id": agent_id, "state": "NONE"}
    e = max(mine, key=lambda x: x["submitted_at"])
    return {
        "agent_id": agent_id,
        "state": e["state"],
        "evidence_id": e["evidence_id"],
        "artifact_type": e["artifact_type"],
        "artifact_sha256": e["sha256"],
        "tests_run_by_gate": True,
        "verified_at": e.get("verified_at"),
    }
