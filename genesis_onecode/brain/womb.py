"""womb.py — the evolution womb of the GENIUS agents.

YZ's doctrine: genius agents are NOT manufactured — they come into being
through تکامل (evolution) and زیست (life). This module is the womb, not a
factory: it provides birth, missions, learning, and natural selection.
No prefabricated agents exist here.

Lifecycle:
  BIRTH     — a new agent is born from a seed (a mission need) or from a
              parent (replication). It gets a slightly mutated trait.
  MISSION   — it takes missions from the queue and executes them with the
              local model, gated by the CODEX (approval-first, zero-spend).
  LEARN     — every outcome is recorded: its fitness updates, lessons go
              into living memory.
  SELECTION — periodically: high-fitness agents replicate (their successful
              traits propagate), low-fitness agents die (kept as fossils —
              the lineage remembers).

Fitness = mission success rate (recency-weighted) + income generated.
An agent's trait (e.g. "careful planner") shapes how the model reasons
for it — traits that succeed propagate through replication.

Persistence: SQLite tables `agents` and `missions` in the same genesis.db
as living memory. Stdlib only.

Birth randomness (Phase 2 embed, 2026-10-21; Phase 3, same day): trait
mutation draws from the vendored quantum seed layer (brain/quantum,
fail-closed seed hub) when it can certify a genuinely quantum mother
seed; when the only mother is the first-run local-CSPRNG one
(brain/quantum/first_run.py), the draw still goes through the hub under
its true source label; otherwise it falls back to stdlib random. Every
agent record carries its `seed_source` provenance —
"quantum-certified", "local-csprng", or "degraded-stdlib" — never a
silent claim (QUANTUM-NAME INTEGRITY, YZ 2026-10-11).

Lifecycle claims (Phase 3 embed, 2026-10-21): births and mission
completions are recorded as claims + evidence in the kernel claims
ledger (kernel/claims_ledger.py) from this real path. The ledger
AUDITS the womb; it never gates it — a ledger failure can never block
a birth or a completion.
"""
from __future__ import annotations

import os
import random
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  trait TEXT NOT NULL,
  born_at REAL NOT NULL,
  parent_id TEXT,
  generation INTEGER NOT NULL,
  fitness REAL NOT NULL DEFAULT 0.5,
  missions_done INTEGER NOT NULL DEFAULT 0,
  missions_ok INTEGER NOT NULL DEFAULT 0,
  income REAL NOT NULL DEFAULT 0.0,
  status TEXT NOT NULL DEFAULT 'alive',
  last_tick REAL NOT NULL DEFAULT 0,
  seed_source TEXT NOT NULL DEFAULT 'legacy-unknown'
);
CREATE TABLE IF NOT EXISTS missions(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  agent_id TEXT,
  created_at REAL NOT NULL,
  completed_at REAL,
  success INTEGER,
  notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
"""

_TRAITS = [
    "careful planner", "fast executor", "deep researcher",
    "cautious verifier", "creative solver", "persistent hunter",
]

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _db_path() -> Path:
    base = Path(os.environ.get("GENESIS_DATA_DIR", "genesis_data"))
    d = base / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "genesis.db"


def _conn() -> sqlite3.Connection:
    global _db
    with _lock:
        if _db is None:
            _db = sqlite3.connect(str(_db_path()), check_same_thread=False)
            _db.execute("PRAGMA journal_mode=WAL;")
            _db.executescript(_SCHEMA)
            # Migration (Phase 2 embed, 2026-10-21): databases created
            # before seed provenance existed gain the column in place.
            # Pre-provenance agents keep the honest default
            # 'legacy-unknown' — their births are never re-labelled.
            cols = [r[1] for r in _db.execute("PRAGMA table_info(agents)")]
            if "seed_source" not in cols:
                _db.execute(
                    "ALTER TABLE agents ADD COLUMN seed_source"
                    " TEXT NOT NULL DEFAULT 'legacy-unknown'")
            _db.commit()
        return _db


# ---- birth randomness: quantum seeds first, honest fallback ----------------
# QUANTUM-NAME INTEGRITY (YZ, 2026-10-11): trait mutation at birth draws
# from the vendored quantum seed layer (brain/quantum) through the
# fail-closed seed hub. The womb registers as a quantum_required consumer,
# so the hub only issues a certified draw when today's mother seed is
# genuinely quantum (ANU QRNG). When certification is impossible there
# are two honest lower tiers, in order:
#   1. "local-csprng" — today's mother is the first-run local-CSPRNG one
#      (brain/quantum/first_run.py, provenance sidecar verified against
#      the LAW-099 seal). The draw STILL goes through the hub, under a
#      separate non-quantum consumer, and is labelled with the mother's
#      true source. Never upgraded to "quantum-certified".
#   2. "degraded-stdlib" — no usable mother at all (hub missing, mother
#      is a relay/os.urandom fallback, hub halt): stdlib random, and the
#      agent record says exactly that.

_WOMB_CONSUMER = "genesis-womb"
_WOMB_DOMAIN = "womb:mutation"
_WOMB_LOCAL_CONSUMER = "genesis-womb-local"
_WOMB_LOCAL_DOMAIN = "womb:mutation-local"
SEED_QUANTUM = "quantum-certified"
SEED_LOCAL = "local-csprng"
SEED_DEGRADED = "degraded-stdlib"


def _load_seed_hub():
    """Return the vendored seed_hub module, or None if unavailable."""
    try:
        from brain.quantum import seed_hub as _hub
        return _hub
    except Exception:
        pass
    try:
        from quantum import seed_hub as _hub
        return _hub
    except Exception:
        return None


def _local_csprng_rng(hub):
    """Draw birth bytes from the first-run local-CSPRNG mother, via the hub.

    Returns a random.Random, or None when today's mother is not the
    verified first-run local one (sidecar + seal cross-checked by
    brain.quantum.first_run.local_mother_info). The hub record for the
    draw carries seed_source="local-csprng" and quantum=False — checked
    again here before the label is ever used.
    """
    try:
        from brain.quantum import first_run as _fr
    except Exception:
        try:
            from quantum import first_run as _fr
        except Exception:
            return None
    try:
        if _fr.local_mother_info() is None:
            return None
        hub.register_consumer(
            _WOMB_LOCAL_CONSUMER, "genesis_onecode/brain (GENIUS womb)",
            _WOMB_LOCAL_DOMAIN, quantum_required=False,
            priority="IMPORTANT",
            wired_by="genesis-embed-phase3-2026-10-21")
        out = hub.consume(_WOMB_LOCAL_CONSUMER, kind="bytes",
                          domain=_WOMB_LOCAL_DOMAIN, n_bytes=32,
                          context="womb trait mutation at birth "
                                  "(local-csprng mother)")
        rec = out["record"]
        if rec.get("seed_source") != SEED_LOCAL or rec.get("quantum"):
            return None
        return random.Random(int.from_bytes(out["bytes"], "big"))
    except Exception:
        return None


def _mutation_rng():
    """Return (rng, seed_source) for one birth's trait mutation.

    rng is a random.Random seeded from hub bytes at the highest honest
    tier available (quantum-certified, then local-csprng), else None
    (caller uses stdlib random) with the degraded provenance label.
    """
    hub = _load_seed_hub()
    if hub is None:
        return None, SEED_DEGRADED
    try:
        hub.register_consumer(
            _WOMB_CONSUMER, "genesis_onecode/brain (GENIUS womb)",
            _WOMB_DOMAIN, quantum_required=True, priority="IMPORTANT",
            wired_by="genesis-embed-phase2-2026-10-21")
        out = hub.consume(_WOMB_CONSUMER, kind="bytes",
                          domain=_WOMB_DOMAIN, n_bytes=32,
                          context="womb trait mutation at birth")
        # Belt and braces: the hub's quantum_required gate already refuses
        # non-quantum draws; verify the record before claiming anything.
        if not out["record"].get("quantum"):
            raise ValueError("hub draw not quantum-certified")
        return (random.Random(int.from_bytes(out["bytes"], "big")),
                SEED_QUANTUM)
    except Exception:
        # HubError (incl. QuantumRequiredError), network failure inside
        # the mother-seed fetch, state errors — try the local tier next.
        pass
    rng_local = _local_csprng_rng(hub)
    if rng_local is not None:
        return rng_local, SEED_LOCAL
    return None, SEED_DEGRADED


def _mutate_trait(parent_trait: str, rng=None) -> str:
    """Small mutation: keep the parent's trait or drift to a neighbor."""
    r = rng if rng is not None else random
    if r.random() < 0.7:
        return parent_trait
    choices = [t for t in _TRAITS if t != parent_trait]
    return r.choice(choices)


# ---- lifecycle claims: the kernel ledger audits the womb -------------------
# Phase 3 embed (2026-10-21): every birth and every mission completion
# is reported to kernel/claims_ledger.py as a claim WITH evidence
# (agent id, fitness, seed_source, mission ids) — the anti-fabrication
# ledger hashes the evidence and accepts the completion, or refuses it.
# Append-only, from this real path, and FAIL-SOFT by design: the ledger
# audits the womb, it never gates it. If the kernel module is absent
# (e.g. its truth_layer adapter cannot import on this machine) the
# lifecycle proceeds exactly as before, unrecorded — never blocked.

_claims_lock = threading.Lock()
_claims_ledgers: dict = {}


def _claims_db_path() -> str:
    base = Path(os.environ.get("GENESIS_DATA_DIR", "genesis_data"))
    return str(base / "kernel" / "claims_ledger.db")


def _load_claims_module():
    """Return the kernel claims_ledger module, or None if unavailable."""
    try:
        from kernel import claims_ledger as _cl
        return _cl
    except Exception:
        pass
    try:
        import importlib.util
        path = (Path(__file__).resolve().parent.parent
                / "kernel" / "claims_ledger.py")
        spec = importlib.util.spec_from_file_location(
            "genesis_kernel_claims_ledger", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def claims_ledger():
    """The shared ClaimsLedger for the current data dir, or None.

    Public so the brain service can report the kernel block (stats)
    from the very ledger the womb writes to. Guarded like everything
    here: None when the kernel is unavailable.
    """
    try:
        db_path = _claims_db_path()
        with _claims_lock:
            led = _claims_ledgers.get(db_path)
            if led is None:
                mod = _load_claims_module()
                if mod is None:
                    return None
                led = mod.ClaimsLedger(db_path=db_path)
                _claims_ledgers[db_path] = led
            return led
    except Exception:
        return None


def _record_claim(claim: str, evidence: dict) -> None:
    """Append one lifecycle claim + evidence to the kernel ledger.

    Never raises, never blocks: an auditing failure is swallowed so the
    womb's real work (birth, completion) is untouched by it.
    """
    try:
        led = claims_ledger()
        if led is None:
            return
        led.report_completion(claim, evidence)
    except Exception:
        pass


# ---- birth ---------------------------------------------------------------
def birth(parent_id: str | None = None, seed: str = "") -> dict:
    """Bring a new agent into being. Returns the agent record."""
    c = _conn()
    with _lock:
        parent = None
        if parent_id:
            row = c.execute(
                "SELECT trait, generation FROM agents WHERE id=? AND status='alive'",
                (parent_id,)).fetchone()
            if row:
                parent = {"trait": row[0], "generation": row[1]}
        rng, seed_source = _mutation_rng()
        trait = (_mutate_trait(parent["trait"], rng) if parent
                 else (rng or random).choice(_TRAITS))
        generation = (parent["generation"] + 1) if parent else 1
        aid = "genius-" + uuid.uuid4().hex[:8]
        name = f"Genius-{aid[-4:]}"
        now = time.time()
        c.execute(
            "INSERT INTO agents(id,name,trait,born_at,parent_id,generation,"
            "fitness,missions_done,missions_ok,income,status,last_tick,"
            "seed_source)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, name, trait, now, parent_id, generation,
             0.5, 0, 0, 0.0, "alive", now, seed_source),
        )
        c.commit()
    try:
        from brain import memory as _mem
        _mem.remember(f"agent_{aid}_born",
                      f"{name} was born (gen {generation}, trait: {trait}). "
                      f"Seed: {seed[:200]}")
    except Exception:
        pass
    _record_claim(
        f"agent {aid} born (gen {generation}, trait: {trait}, "
        f"seed: {seed_source})",
        {"event": "birth", "agent_id": aid, "name": name,
         "trait": trait, "generation": generation, "fitness": 0.5,
         "seed_source": seed_source, "parent_id": parent_id})
    return get_agent(aid)


def get_agent(agent_id: str) -> dict | None:
    c = _conn()
    with _lock:
        row = c.execute(
            "SELECT id,name,trait,born_at,parent_id,generation,fitness,"
            "missions_done,missions_ok,income,status,seed_source"
            " FROM agents WHERE id=?",
            (agent_id,)).fetchone()
    if not row:
        return None
    keys = ("id", "name", "trait", "born_at", "parent_id", "generation",
            "fitness", "missions_done", "missions_ok", "income", "status",
            "seed_source")
    return dict(zip(keys, row))


def living_agents() -> list[dict]:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT id,name,trait,born_at,parent_id,generation,fitness,"
            "missions_done,missions_ok,income,status,seed_source"
            " FROM agents"
            " WHERE status='alive' ORDER BY born_at").fetchall()
    keys = ("id", "name", "trait", "born_at", "parent_id", "generation",
            "fitness", "missions_done", "missions_ok", "income", "status",
            "seed_source")
    return [dict(zip(keys, r)) for r in rows]


# ---- missions -------------------------------------------------------------
def add_mission(title: str, detail: str = "") -> dict:
    title = str(title).strip()
    if not title:
        raise ValueError("mission needs a title")
    c = _conn()
    mid = "mission-" + uuid.uuid4().hex[:8]
    with _lock:
        c.execute(
            "INSERT INTO missions(id,title,detail,status,created_at)"
            " VALUES(?,?,?,'pending',?)",
            (mid, title, str(detail)[:4000], time.time()))
        c.commit()
        row = c.execute(
            "SELECT id,title,detail,status,agent_id,created_at FROM missions"
            " WHERE id=?", (mid,)).fetchone()
    keys = ("id", "title", "detail", "status", "agent_id", "created_at")
    return dict(zip(keys, row))


def pending_missions() -> list[dict]:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT id,title,detail,status,agent_id,created_at FROM missions"
            " WHERE status='pending' ORDER BY created_at").fetchall()
    keys = ("id", "title", "detail", "status", "agent_id", "created_at")
    return [dict(zip(keys, r)) for r in rows]


def take_mission(agent_id: str) -> dict | None:
    """The oldest pending mission goes to this agent."""
    c = _conn()
    with _lock:
        ag = c.execute("SELECT status FROM agents WHERE id=?",
                       (agent_id,)).fetchone()
        if not ag or ag[0] != "alive":
            return None
        row = c.execute(
            "SELECT id FROM missions WHERE status='pending'"
            " ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        mid = row[0]
        c.execute("UPDATE missions SET status='active', agent_id=?"
                  " WHERE id=?", (agent_id, mid))
        c.commit()
        m = c.execute(
            "SELECT id,title,detail,status,agent_id,created_at FROM missions"
            " WHERE id=?", (mid,)).fetchone()
    keys = ("id", "title", "detail", "status", "agent_id", "created_at")
    return dict(zip(keys, m))


def complete_mission(agent_id: str, mission_id: str, success: bool,
                     notes: str = "", income: float = 0.0) -> dict | None:
    """Record the outcome — the agent learns, fitness updates."""
    c = _conn()
    with _lock:
        row = c.execute(
            "SELECT missions_done, missions_ok, income FROM agents"
            " WHERE id=? AND status='alive'", (agent_id,)).fetchone()
        if not row:
            return None
        done, ok, inc = row[0] + 1, row[1] + (1 if success else 0), row[2] + max(0.0, income)
        # recency-weighted fitness: the latest outcome counts double
        fitness = round((ok * 2 + (1 if success else 0)) / (done * 2 + 1), 3)
        fitness = max(0.0, min(1.0, fitness))
        c.execute(
            "UPDATE agents SET missions_done=?, missions_ok=?, income=?,"
            " fitness=?, last_tick=? WHERE id=?",
            (done, ok, inc, fitness, time.time(), agent_id))
        c.execute(
            "UPDATE missions SET status='done', completed_at=?, success=?,"
            " notes=? WHERE id=?",
            (time.time(), 1 if success else 0, str(notes)[:4000], mission_id))
        c.commit()
    try:
        from brain import memory as _mem
        _mem.log_exchange(
            "her", f"Agent update: mission '{mission_id}' "
            f"{'succeeded' if success else 'failed'}. Notes: {notes[:300]}")
    except Exception:
        pass
    rec = get_agent(agent_id)
    if rec is not None:
        _record_claim(
            f"mission {mission_id} completed by agent {agent_id} "
            f"({'success' if success else 'failed'}, "
            f"fitness {rec['fitness']})",
            {"event": "mission_completed", "agent_id": agent_id,
             "mission_id": mission_id, "success": bool(success),
             "fitness": rec["fitness"], "seed_source": rec["seed_source"],
             "missions_done": rec["missions_done"],
             "missions_ok": rec["missions_ok"]})
    return rec


# ---- natural selection ------------------------------------------------------
REPLICATE_FITNESS = 0.8
DEATH_FITNESS = 0.3
MIN_MISSIONS_FOR_SELECTION = 3

def selection() -> dict:
    """One round of natural selection. Returns what happened."""
    born, died = [], []
    for ag in living_agents():
        if ag["missions_done"] < MIN_MISSIONS_FOR_SELECTION:
            continue
        if ag["fitness"] >= REPLICATE_FITNESS:
            child = birth(parent_id=ag["id"],
                          seed=f"replication of {ag['id']} (fitness {ag['fitness']})")
            born.append(child["id"])
        elif ag["fitness"] <= DEATH_FITNESS:
            c = _conn()
            with _lock:
                c.execute("UPDATE agents SET status='dead' WHERE id=?",
                          (ag["id"],))
                c.commit()
            died.append(ag["id"])
            try:
                from brain import memory as _mem
                _mem.remember(f"agent_{ag['id']}_died",
                              f"{ag['name']} died (fitness {ag['fitness']}, "
                              f"{ag['missions_ok']}/{ag['missions_done']} ok). "
                              f"The lineage remembers.")
            except Exception:
                pass
    return {"replicated": born, "died": died}


# ---- mission execution ------------------------------------------------------
# An agent works a mission with the local model. Its trait shapes how it
# reasons. Every outside-world action the agent proposes goes through the
# CODEX first — approval-first and zero-spend are enforced inside the womb,
# not hoped for. llama_fn/codex_fn are injected so this is testable.

def _active_mission(agent_id: str) -> dict | None:
    c = _conn()
    with _lock:
        row = c.execute(
            "SELECT id,title,detail,status,agent_id,created_at FROM missions"
            " WHERE agent_id=? AND status='active' ORDER BY created_at LIMIT 1",
            (agent_id,)).fetchone()
    if not row:
        return None
    keys = ("id", "title", "detail", "status", "agent_id", "created_at")
    return dict(zip(keys, row))


def execute_active(agent_id: str, llama_fn, codex_fn,
                   browser_fn=None) -> dict | None:
    """One agent works its active mission. Returns the completion record.

    With browser_fn: the agent gets browser hands (agentic loop). Without:
    single reasoning pass (used in tests and when the browser is absent).
    """
    ag = get_agent(agent_id)
    if not ag or ag["status"] != "alive":
        return None
    m = _active_mission(agent_id)
    if not m:
        return None
    # The CODEX gates the mission itself before any work begins.
    verdict = codex_fn({"kind": "compute"})
    if not verdict.get("allowed"):
        return complete_mission(agent_id, m["id"], False,
                                f"codex denied: {verdict.get('reason')}")
    try:
        from brain import memory as _mem
        mem_ctx = _mem.all_facts()
        mem_lines = "; ".join(f"{k}={v}" for k, v in list(mem_ctx.items())[:12])
    except Exception:
        mem_lines = ""
    if browser_fn is not None:
        out = _run_with_hands(ag, m, mem_lines, llama_fn, browser_fn)
    else:
        prompt = (
            f"You are {ag['name']}, a GENIUS agent of the 369 world. "
            f"Your nature: {ag['trait']}. "
            f"Your mission: {m['title']}. {m['detail']}\n"
            f"What you remember: {mem_lines}\n"
            f"Work the mission now. Be concrete and honest. If you cannot do "
            f"something, say what is missing instead of pretending. "
            f"End with a line: RESULT: SUCCESS or RESULT: FAILED."
        )
        try:
            out = llama_fn([{"role": "system", "content": prompt},
                            {"role": "user", "content": "Begin."}])
        except Exception as e:
            return complete_mission(agent_id, m["id"], False,
                                    f"model error: {e}")
    success = "RESULT: SUCCESS" in out.upper().replace("**", "")
    notes = out[:3000]
    return complete_mission(agent_id, m["id"], success, notes)


# ---- the tick ----------------------------------------------------------------
# One evolution step. Called periodically by the brain service (daemon
# thread, every 10 minutes) and on demand via POST /agents/tick.

_tick_count = 0
SELECTION_EVERY_TICKS = 6  # selection runs roughly hourly


def tick(llama_fn=None, codex_fn=None, browser_fn=None) -> dict:
    """Birth, assign, execute, select. Returns what happened."""
    global _tick_count
    _tick_count += 1
    events: dict = {"tick": _tick_count, "born": [], "executed": [],
                    "selection": None}

    living = living_agents()
    pend = pending_missions()
    if pend and not living:
        first = birth(seed=f"firstborn — mission waiting: {pend[0]['title']}")
        living = [first]
        events["born"].append(first["id"])

    for ag in living_agents():
        if not _active_mission(ag["id"]):
            take_mission(ag["id"])

    if llama_fn and codex_fn:
        for ag in living_agents():
            rec = execute_active(ag["id"], llama_fn, codex_fn, browser_fn)
            if rec:
                events["executed"].append(
                    {"agent": ag["id"], "fitness": rec["fitness"]})

    if _tick_count % SELECTION_EVERY_TICKS == 0:
        events["selection"] = selection()

    return events


# ---- browser hands ------------------------------------------------------------
# The agent's hands: it writes BROWSER: action lines, the executor runs them
# through browser_fn (governor lease + CODEX gates inside), results feed back.
# Max 8 steps per mission — bounded, never a runaway.

BROWSER_HELP = (
    "You have browser hands. To act in the browser, write lines starting "
    "with BROWSER:, one per line:\n"
    "  BROWSER: open <url>\n"
    "  BROWSER: read\n"
    "  BROWSER: click <selector>\n"
    "  BROWSER: type <selector> <text>\n"
    "  BROWSER: screenshot\n"
    "After your actions run you will see their results. Then either act "
    "again or finish with a line: RESULT: SUCCESS or RESULT: FAILED."
)

MAX_BROWSER_STEPS = 8


def _parse_browser_actions(text: str) -> list[tuple[str, str]]:
    actions = []
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("BROWSER:"):
            rest = line[len("BROWSER:"):].strip()
            if not rest:
                continue
            parts = rest.split(None, 1)
            actions.append((parts[0].lower(), parts[1] if len(parts) > 1 else ""))
    return actions


def _run_with_hands(agent: dict, mission: dict, mem_lines: str,
                    llama_fn, browser_fn) -> str:
    """Agentic loop: LLM reasons, BROWSER lines execute, results feed back."""
    transcript: list[str] = []
    for step in range(MAX_BROWSER_STEPS):
        context = "\n".join(transcript[-6:])  # recent history only
        prompt = (
            f"You are {agent['name']}, a GENIUS agent of the 369 world. "
            f"Your nature: {agent['trait']}. "
            f"Your mission: {mission['title']}. {mission['detail']}\n"
            f"What you remember: {mem_lines}\n"
            f"{BROWSER_HELP}\n"
            f"So far:\n{context}\n"
            f"Continue. Act with the browser if it helps; otherwise conclude."
        )
        try:
            out = llama_fn([{"role": "system", "content": prompt},
                            {"role": "user", "content": "Your move."}])
        except Exception as e:
            transcript.append(f"[model error: {e}]")
            break
        actions = _parse_browser_actions(out)
        # strip the action lines for the readable transcript
        spoken = "\n".join(l for l in out.splitlines()
                           if not l.strip().upper().startswith("BROWSER:"))
        if spoken.strip():
            transcript.append(f"[agent] {spoken.strip()[:800]}")
        if not actions:
            transcript.append(f"[final] {out.strip()[:800]}")
            break
        for name, params in actions:
            try:
                result = browser_fn(agent["id"], name, params)
            except Exception as e:
                result = f"ERROR: {e}"
            transcript.append(f"[browser {name} {params[:80]}] -> "
                              f"{str(result)[:1200]}")
    return "\n".join(transcript)


