"""codex.py — the 369 laws that RUN as code.

YZ's standing laws are not decoration text the model reads — they are
guards the machine executes. Every function here is fail-closed: an
unknown action kind is DENIED, never allowed by default.

The brain service exposes this at POST /codex/check so the face and the
GENIUS agents ask permission instead of assuming it:

  {"kind": "chat"}                          -> allowed (local, reversible)
  {"kind": "spend", "amount": 5}             -> denied (zero-spend, no approval)
  {"kind": "spend", "amount": 5, "approved": true} -> allowed (YZ approved)
  {"kind": "publish", "approved": true}      -> allowed
  {"kind": "teleport"}                      -> denied (unknown kind)

Stdlib only. No network. Deterministic — the same action always gets the
same verdict.
"""
from __future__ import annotations

# Action kinds that touch the outside world or move value.
# Anything here needs YZ's explicit approval first (approval-first law).
_APPROVAL_KINDS = frozenset({
    "spend",            # any money movement, any amount
    "publish",          # anything leaving the machine toward the public
    "message_external", # contacting a person/service outside
    "delete_data",      # destroying her own memory or files
    "account_change",   # creating/changing accounts, keys, credentials
})

# Action kinds that are always safe: local, reversible, read-only.
_SAFE_KINDS = frozenset({
    "chat",             # talking to YZ
    "read_memory",      # reading her own memory
    "write_memory",     # remembering (facts/exchanges) — local SQLite
    "compute",          # local reasoning, planning
    "browse_read",      # opening a page and reading it (no side effects)
    # "browse_act" (click/type in the browser): allowed as a KIND — the real
    # gate is the browser governor, which denies its SENSITIVE_ACTIONS
    # (purchase/checkout/pay/send/submit/post/login/...) without YZ approval
    # (fail-closed: no callback => denied), and every action is logged.
    # Clicking a link or typing in a search box is reversible; the
    # irreversible things are fenced by the governor, not by this list.
    "browse_act",
})


def requires_yz_approval(kind: str) -> bool:
    """True when this action kind needs YZ's approval first."""
    return str(kind) in _APPROVAL_KINDS


def check(action: dict) -> dict:
    """Executable verdict for one action. Fail-closed.

    action: {"kind": str, "amount": float = 0, "approved": bool = False}
    Returns {"allowed": bool, "reason": str}.
    """
    if not isinstance(action, dict):
        return {"allowed": False, "reason": "malformed action — denied"}
    kind = str(action.get("kind", "")).strip()
    approved = action.get("approved") is True

    if kind in _SAFE_KINDS:
        return {"allowed": True, "reason": f"{kind}: local and reversible"}

    if kind in _APPROVAL_KINDS:
        if kind == "spend":
            try:
                amount = float(action.get("amount", 0))
            except (TypeError, ValueError):
                return {"allowed": False, "reason": "spend: bad amount — denied"}
            if amount <= 0:
                return {"allowed": True, "reason": "spend: no money moves"}
            # zero-spend law: any real money needs YZ's per-case approval
            if approved:
                return {"allowed": True, "reason": "spend: YZ approved"}
            return {"allowed": False,
                    "reason": "spend: zero-spend law — YZ approval required"}
        if approved:
            return {"allowed": True, "reason": f"{kind}: YZ approved"}
        return {"allowed": False,
                "reason": f"{kind}: approval-first law — YZ approval required"}

    # Unknown kind — fail closed. The law does not know it, so it denies it.
    return {"allowed": False, "reason": f"unknown action kind '{kind}' — denied"}
