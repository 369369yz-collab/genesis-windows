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
  last_tick REAL NOT NULL DEFAULT 0
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
            _db.commit()
        return _db


def _mutate_trait(parent_trait: str) -> str:
    """Small mutation: keep the parent's trait or drift to a neighbor."""
    if random.random() < 0.7:
        return parent_trait
    choices = [t for t in _TRAITS if t != parent_trait]
    return random.choice(choices)


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
        trait = _mutate_trait(parent["trait"]) if parent else random.choice(_TRAITS)
        generation = (parent["generation"] + 1) if parent else 1
        aid = "genius-" + uuid.uuid4().hex[:8]
        name = f"Genius-{aid[-4:]}"
        now = time.time()
        c.execute(
            "INSERT INTO agents(id,name,trait,born_at,parent_id,generation,"
            "fitness,missions_done,missions_ok,income,status,last_tick)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, name, trait, now, parent_id, generation,
             0.5, 0, 0, 0.0, "alive", now),
        )
        c.commit()
    try:
        from brain import memory as _mem
        _mem.remember(f"agent_{aid}_born",
                      f"{name} was born (gen {generation}, trait: {trait}). "
                      f"Seed: {seed[:200]}")
    except Exception:
        pass
    return get_agent(aid)


def get_agent(agent_id: str) -> dict | None:
    c = _conn()
    with _lock:
        row = c.execute(
            "SELECT id,name,trait,born_at,parent_id,generation,fitness,"
            "missions_done,missions_ok,income,status FROM agents WHERE id=?",
            (agent_id,)).fetchone()
    if not row:
        return None
    keys = ("id", "name", "trait", "born_at", "parent_id", "generation",
            "fitness", "missions_done", "missions_ok", "income", "status")
    return dict(zip(keys, row))


def living_agents() -> list[dict]:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT id,name,trait,born_at,parent_id,generation,fitness,"
            "missions_done,missions_ok,income,status FROM agents"
            " WHERE status='alive' ORDER BY born_at").fetchall()
    keys = ("id", "name", "trait", "born_at", "parent_id", "generation",
            "fitness", "missions_done", "missions_ok", "income", "status")
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
    return get_agent(agent_id)


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


