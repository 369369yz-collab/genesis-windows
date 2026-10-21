"""Deterministic never-forget gate — pure stdlib, Windows-safe.

No AI judgment: a loop FAILS the gate iff it is open AND
  (now - last_action_ts > STALE_HOURS) OR (deadline passed).
Returns structured results; the server wrapper turns them into
exit codes + P0 escalations.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .store import load_loops, _parse_ts

STALE_HOURS = 24


def check(path, now=None):
    now = now or datetime.now(timezone.utc).astimezone()
    loops = load_loops(path)
    stale, overdue, ok, paused = [], [], [], []
    for lid, st in loops.items():
        if st["status"] == "paused":
            # Intentionally held per YZ order — visible but never a gate failure.
            paused.append({
                "id": lid, "title": st["title"], "owner": st["owner"],
                "evidence": st["evidence"], "paused_ts": st.get("paused_ts"),
            })
            continue
        if st["status"] != "open":
            continue
        opened = _parse_ts(st["opened_ts"]) or now
        last = _parse_ts(st["last_action_ts"]) or opened
        deadline = _parse_ts(st["deadline_ts"])
        age_h = (now - opened).total_seconds() / 3600.0
        idle_h = (now - last).total_seconds() / 3600.0
        rec = {
            "id": lid,
            "title": st["title"],
            "owner": st["owner"],
            "age_h": round(age_h, 1),
            "idle_h": round(idle_h, 1),
            "deadline_ts": st["deadline_ts"],
            "evidence": st["evidence"],
            "source": st["source"],
        }
        is_overdue = bool(deadline and now > deadline)
        is_stale = idle_h > STALE_HOURS
        rec["overdue"] = is_overdue
        rec["stale"] = is_stale
        if is_overdue:
            rec["overdue_by_h"] = round((now - deadline).total_seconds() / 3600.0, 1)
            overdue.append(rec)
        elif is_stale:
            stale.append(rec)
        else:
            ok.append(rec)
    by_age = lambda r: -r["age_h"]
    stale.sort(key=by_age)
    overdue.sort(key=by_age)
    ok.sort(key=by_age)
    return {
        "checked_at": now.isoformat(timespec="seconds"),
        "total_open": len(stale) + len(overdue) + len(ok),
        "stale": stale,
        "overdue": overdue,
        "ok": ok,
        "paused": paused,
        "failed": bool(stale or overdue),
    }


def format_report(result):
    L = []
    L.append("=" * 64)
    L.append("NEVER-FORGET GATE — %s" % result["checked_at"])
    L.append("open loops: %d | STALE(>24h idle): %d | OVERDUE(past deadline): %d"
             % (result["total_open"], len(result["stale"]), len(result["overdue"])))
    L.append("=" * 64)
    def show(rec):
        flag = "OVERDUE" if rec["overdue"] else "STALE"
        extra = (" | overdue_by=%.1fh" % rec["overdue_by_h"]) if rec["overdue"] else ""
        L.append("[%s] %s — %s (owner=%s, age=%.1fh, idle=%.1fh%s)"
                 % (flag, rec["id"], rec["title"], rec["owner"],
                    rec["age_h"], rec["idle_h"], extra))
        if rec["evidence"]:
            L.append("        evidence: %s" % rec["evidence"][:160])
    for rec in result["overdue"] + result["stale"]:
        show(rec)
    if result.get("paused"):
        L.append("-" * 64)
        L.append("PAUSED (YZ-ordered hold — visible, not a failure): %d" % len(result["paused"]))
        for rec in result["paused"]:
            L.append("[PAUSED] %s — %s (owner=%s, since=%s)"
                     % (rec["id"], rec["title"][:80], rec["owner"], rec.get("paused_ts") or "?"))
    if result["failed"]:
        L.append("-" * 64)
        L.append("GATE FAILED — %d loop(s) need action. Forgetting is structural failure."
                 % (len(result["stale"]) + len(result["overdue"])))
    else:
        L.append("GATE PASSED — every open loop has fresh action and no missed deadline.")
    return "\n".join(L)
