"""genesis-cloudburst: honest manual-offload handoff for GPU-heavy jobs.

ZERO SPEND ABSOLUTE. This module NEVER:
  - spends money or touches paid compute,
  - stores provider credentials in the repository,
  - automates against any provider's Terms of Service.

What it DOES (all local, all real):
  - policy check ......... can_offload(job) -> bool
  - manual handoff ....... offload(job) -> dict
      Records the job in a local ledger and returns honest step-by-step
      instructions for a MANUAL free-tier GPU session. Automated submission
      is deliberately NOT implemented: free-tier notebook providers
      (Colab, Kaggle) prohibit bot/automated access in their ToS, and
      automating against them would risk the father's accounts.
  - tracking ............. fetch_result(offload_id) -> dict
  - result intake ........ ingest_result(offload_id, result_path) -> dict
  - config template ...... init_config(path=None) -> dict
  - provider catalog ..... list_providers() -> dict  (documented, static)

Bridge call points: NONE. This module never contacts the network mind;
every offload is executed manually by the father in his own browser session.

100% stdlib. No network calls anywhere in this module (a test enforces this).
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Static, documented free-tier provider catalog.
# Quota reality is stated qualitatively on purpose: free-tier limits change
# frequently and without notice. NEVER promise unlimited quotas.
# ---------------------------------------------------------------------------

PROVIDERS = [
    {
        "id": "colab",
        "name": "Google Colab (free tier)",
        "url": "https://colab.research.google.com",
        "free_tier": "Browser notebooks with limited free GPU access.",
        "quota_reality": (
            "Free GPU availability is limited, varies by demand, and the "
            "limits change without notice. Sessions disconnect on idle "
            "timeout and have a maximum lifetime; there is no SLA. "
            "Check Google's current Colab documentation for the live limits."
        ),
        "tos_note": (
            "Automated or bot-driven access to Colab is prohibited by "
            "Google's Terms of Service. Use only through the normal "
            "browser UI, manually."
        ),
    },
    {
        "id": "kaggle",
        "name": "Kaggle Notebooks (free tier)",
        "url": "https://www.kaggle.com/code",
        "free_tier": "Browser notebooks with limited free GPU/TPU quota.",
        "quota_reality": (
            "Free GPU quota is a limited weekly allowance that Kaggle "
            "adjusts over time; it is not guaranteed and requires an "
            "account (phone verification may apply). Notebooks time out. "
            "Check Kaggle's current documentation for the live quota."
        ),
        "tos_note": (
            "Scripted/automated notebook execution that evades Kaggle's "
            "usage controls violates their Terms. Use only manually in "
            "the browser."
        ),
    },
]

_STATE_AWAITING = "awaiting_manual_run"
_STATE_DONE = "done"

_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS offloads (
    offload_id    TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    job_kind      TEXT NOT NULL,
    job_name      TEXT NOT NULL,
    job_json      TEXT NOT NULL,
    state         TEXT NOT NULL,
    result_path   TEXT,
    created_utc   TEXT NOT NULL,
    ingested_utc  TEXT
);
"""

_CONFIG_TEMPLATE = {
    "offload_enabled": False,
    "default_provider": "colab",
    "providers": {
        "colab": {"session_bookmark": "", "note": "paste your Colab notebook URL here"},
        "kaggle": {"session_bookmark": "", "note": "paste your Kaggle notebook URL here"},
    },
    "_comment": ("Local-only config. NEVER commit this file. "
                 "Bookmarks are convenience URLs, not credentials."),
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _base_dir() -> str:
    override = os.environ.get("GENESIS_CLOUDBURST_CONFIG")
    if override:
        return os.path.dirname(os.path.abspath(override))
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "GENESIS", "cloudburst")
    return os.path.join(os.path.expanduser("~"), ".genesis", "cloudburst")


def config_path() -> str:
    override = os.environ.get("GENESIS_CLOUDBURST_CONFIG")
    if override:
        return override
    return os.path.join(_base_dir(), "cloudburst_config.json")


def _ledger_path() -> str:
    return os.path.join(_base_dir(), "ledger.db")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_config() -> dict | None:
    path = config_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _connect_ledger() -> sqlite3.Connection:
    path = _ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_LEDGER_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_providers() -> dict:
    """Return the documented free-tier provider catalog (static, honest)."""
    return {"status": "ok", "providers": [dict(p) for p in PROVIDERS],
            "note": ("Free-tier quotas are limited, change without notice, and "
                     "carry no SLA. Verify current limits on each provider's "
                     "own documentation page.")}


def init_config(path: str | None = None) -> dict:
    """Write an example local config file. Never overwrites an existing one.

    The file lives outside the repo (LOCALAPPDATA on Windows,
    ~/.genesis/cloudburst elsewhere) and must never be committed.
    """
    target = path or config_path()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(target):
        return {"status": "exists", "path": target,
                "note": "existing config left untouched"}
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(_CONFIG_TEMPLATE, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return {"status": "ok", "path": target,
            "note": "edit offload_enabled + provider bookmarks locally; never commit"}


def _job_problems(job) -> list[str]:
    problems = []
    if not isinstance(job, dict):
        return ["job must be a dict"]
    kind = job.get("kind")
    if kind not in ("render", "produce"):
        problems.append(f"job['kind'] must be 'render' or 'produce', got {kind!r}")
    if not isinstance(job.get("name"), str) or not job["name"].strip():
        problems.append("job['name'] must be a non-empty string")
    params = job.get("params")
    if not isinstance(params, dict):
        problems.append("job['params'] must be a dict")
    return problems


def can_offload(job: dict) -> bool:
    """Policy gate: True only if offload is configured, enabled, and suitable.

    Does NOT claim provider quota availability — free-tier quota cannot be
    known from here and is never promised.
    """
    if _job_problems(job):
        return False
    params = job["params"]
    if params.get("local_only") is True:
        return False
    if params.get("gpu") is not True:
        return False
    cfg = _load_config()
    if not cfg or cfg.get("offload_enabled") is not True:
        return False
    provider = cfg.get("default_provider")
    providers = cfg.get("providers") or {}
    if not isinstance(provider, str) or provider not in providers:
        return False
    if not any(p["id"] == provider for p in PROVIDERS):
        return False
    return True


def _rejection_reason(job) -> str:
    problems = _job_problems(job)
    if problems:
        return "; ".join(problems)
    params = job["params"]
    if params.get("local_only") is True:
        return "job is marked local_only"
    if params.get("gpu") is not True:
        return "job is not GPU-flagged (params['gpu'] must be true)"
    cfg = _load_config()
    if cfg is None:
        return f"no config file at {config_path()}; run init_config() first"
    if cfg.get("offload_enabled") is not True:
        return "offload_enabled is not true in local config"
    provider = cfg.get("default_provider")
    if not isinstance(provider, str) or provider not in (cfg.get("providers") or {}):
        return "default_provider is not configured in local config"
    return "provider not in the documented free-tier catalog"


def offload(job: dict) -> dict:
    """Record a manual offload handoff. NEVER submits anything automatically.

    Returns {"status": "manual_handoff", ...} with step-by-step instructions,
    or {"status": "rejected", "reason": ...}.
    """
    if not can_offload(job):
        return {"status": "rejected", "reason": _rejection_reason(job)}
    cfg = _load_config()  # guaranteed usable by can_offload()
    provider_id = cfg["default_provider"]
    provider = next(p for p in PROVIDERS if p["id"] == provider_id)
    bookmark = (cfg.get("providers", {}).get(provider_id, {})
                .get("session_bookmark", "") or provider["url"])

    offload_id = uuid.uuid4().hex
    conn = _connect_ledger()
    try:
        conn.execute(
            "INSERT INTO offloads (offload_id, provider, job_kind, job_name,"
            " job_json, state, created_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (offload_id, provider_id, job["kind"], job["name"].strip(),
             json.dumps(job, ensure_ascii=False), _STATE_AWAITING, _utcnow()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "manual_handoff",
        "offload_id": offload_id,
        "provider": provider_id,
        "job_summary": {"kind": job["kind"], "name": job["name"].strip()},
        "next_steps": [
            f"1. Open your manual session: {bookmark}",
            "2. Upload the job payload (see job_summary; payload lives in the "
            "local station queue, nothing was sent anywhere).",
            "3. Run it in the free-tier GPU session yourself.",
            "4. Download the result file(s) to this PC.",
            f"5. Register the result: ingest_result({offload_id!r}, result_path).",
        ],
        "quota_notice": provider["quota_reality"],
        "tos_note": provider["tos_note"],
        "note": ("Automated submission is deliberately NOT implemented. "
                 "Free-tier notebook providers prohibit bot/automated access "
                 "in their Terms of Service; automating against them would "
                 "risk account bans. Nothing was transmitted by this call."),
    }


def fetch_result(offload_id: str) -> dict:
    """Check the local ledger for an offload's result state."""
    if not isinstance(offload_id, str) or not offload_id:
        return {"status": "unknown", "offload_id": offload_id}
    conn = _connect_ledger()
    try:
        row = conn.execute("SELECT * FROM offloads WHERE offload_id = ?",
                           (offload_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"status": "unknown", "offload_id": offload_id,
                "reason": "no such offload in the local ledger"}
    base = {
        "offload_id": row["offload_id"],
        "provider": row["provider"],
        "job_kind": row["job_kind"],
        "job_name": row["job_name"],
        "state": row["state"],
        "created_utc": row["created_utc"],
    }
    if row["state"] == _STATE_DONE:
        return {"status": "ok", **base, "result_path": row["result_path"],
                "ingested_utc": row["ingested_utc"]}
    return {"status": "pending", **base,
            "note": "result not yet ingested; run the manual session, "
                    "then call ingest_result()"}


def ingest_result(offload_id: str, result_path: str) -> dict:
    """Register a manually produced result file. The file must exist locally."""
    if not isinstance(offload_id, str) or not offload_id:
        return {"status": "unknown", "offload_id": offload_id}
    conn = _connect_ledger()
    try:
        row = conn.execute("SELECT * FROM offloads WHERE offload_id = ?",
                           (offload_id,)).fetchone()
        if row is None:
            return {"status": "unknown", "offload_id": offload_id,
                    "reason": "no such offload in the local ledger"}
        if not isinstance(result_path, str) or not os.path.isfile(result_path):
            return {"status": "error", "offload_id": offload_id,
                    "reason": f"result file not found: {result_path!r}"}
        abs_path = os.path.abspath(result_path)
        conn.execute(
            "UPDATE offloads SET state = ?, result_path = ?, ingested_utc = ?"
            " WHERE offload_id = ?",
            (_STATE_DONE, abs_path, _utcnow(), offload_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "offload_id": offload_id, "state": _STATE_DONE,
            "result_path": abs_path}


__all__ = ["can_offload", "offload", "fetch_result", "ingest_result",
           "init_config", "list_providers", "config_path", "PROVIDERS"]
