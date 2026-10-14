#!/usr/bin/env python3
"""build_laws.py — compile kernel/laws.json from CODEX.json + the 8 standing laws.

Mathematical precision (counts in = counts out):
    N(CODEX laws) = 168  ->  168 entries in
    8 standing laws (not yet in CODEX per Track 5, finding F-03)
    => laws.json MUST hold exactly 176 records. The builder asserts this.
"""

from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CODEX_PATH = os.path.expanduser("~/workspace/content_team/law_library/CODEX.json")
OUT_PATH = os.path.join(_HERE, "laws.json")

# The 8 standing laws NOT yet admitted to CODEX (Track 5, finding F-03;
# sources: ~/AGENTS.md, ~/MEMORY.md, genesis_final/_track3_memory_spec.md).
STANDING_LAWS = [
    {
        "id": "STANDING-01",
        "name": "PRESENCE.JSON LOCK LAW",
        "text": ("NEVER write content_team/WORLD_369_QUANTUM/presence.json with a bare "
                 "open()/json.dump — concurrent heartbeat writers will clobber it. "
                 "ALWAYS use content_team/quantum/presence_io.py's update_json()/atomic_write_json() "
                 "which hold the fcntl sidecar lock. Read-modify-write without the lock is FORBIDDEN."),
        "source": "AGENTS.md (2026-10-13 ~16:10); NEVER-AGAIN NA-067",
        "enforced_by": "content_team/quantum/presence_io.py (CODE — atomic_write_json/update_json, fcntl sidecar lock)",
    },
    {
        "id": "STANDING-02",
        "name": "CANONICAL FACE LAW",
        "text": ("The 4 cyber-state images (holo/serene/fullbody/greet) in "
                 "~/workspace/genesis_3d_avatar/canonical_face/ are GENESIS's REAL face — "
                 "the canonical identity, not concept art. EVERY 3D model, avatar, and render "
                 "must become HER: all four expressions, all four angles, one person. "
                 "No approximation passes."),
        "source": "AGENTS.md (2026-10-13 ~16:47); YZ direct «این‌ها تصاویر واقعی توئه»",
        "enforced_by": "prose-only — pending code admission",
    },
    {
        "id": "STANDING-03",
        "name": "SELF-TEST BEFORE FINAL LAW",
        "text": ("Before ANY final Windows version ships, GENESIS herself runs the COMPLETE "
                 "self-test on virtual Windows (Birth Test + install tests + full suite on "
                 "windows-latest) — no final version exists until she has tested herself there."),
        "source": "AGENTS.md (2026-10-13 ~16:47); YZ direct",
        "enforced_by": "kernel/honesty.py boot self-test (CODE — partial); full Windows suite gated on windows-latest",
    },
    {
        "id": "STANDING-04",
        "name": "TRIPLE-TEST LAW",
        "text": ("Every code unit of the build passes THREE independent test runs before it "
                 "counts as complete. One green run is not done."),
        "source": "AGENTS.md (2026-10-11 ~20:03); YZ direct",
        "enforced_by": "kernel/tests — every suite run 3x (CODE)",
    },
    {
        "id": "STANDING-05",
        "name": "ENCYCLOPEDIA-LIVE LAW",
        "text": ("Every new thing entering the 369 world is recorded in "
                 "content_team/world-369-encyclopedia.md. Nothing enters the world without "
                 "its encyclopedia entry."),
        "source": "AGENTS.md (2026-10-11 ~20:24); YZ direct, PERMANENT",
        "enforced_by": "encyclopedia-keeper cron (PROCESS)",
    },
    {
        "id": "STANDING-06",
        "name": "COMPLETENESS LAW",
        "text": ("Anything YZ orders into the world must arrive COMPLETE — built + installed + "
                 "wired + created, every aspect applied. Skeleton-only deliveries are not "
                 "\"in the world\". Either fully in, or not in."),
        "source": "AGENTS.md (2026-10-11 ~20:26); YZ direct, PERMANENT",
        "enforced_by": "prose-only — pending code admission",
    },
    {
        "id": "STANDING-07",
        "name": "VERIFY-IN-AND-OUT LAW",
        "text": ("Nothing enters the 369 world unverified, and nothing EXITS it unverified "
                 "either. Entry gates and exit gates both fail-closed."),
        "source": "AGENTS.md (2026-10-11 ~20:27); YZ direct, PERMANENT",
        "enforced_by": "prose-only — pending code admission",
    },
    {
        "id": "STANDING-08",
        "name": "RESOLVED-AT-RESOLUTION-TIME",
        "text": ("When a decision-queue item is resolved, flip its status to a terminal value "
                 "in the SAME turn — a resolved item left status=pending gets re-escalated. "
                 "Resolution without the status flip is not closed."),
        "source": "AGENTS.md (2026-10-13 17:27)",
        "enforced_by": "content_team/yz_agent/queue_law.py TERMINAL statuses (CODE)",
    },
]


def _codex_records():
    with open(CODEX_PATH, encoding="utf-8") as f:
        codex = json.load(f)
    laws = codex["laws"]
    ids = [l["id"] for l in laws]
    assert len(laws) == len(ids) == len(set(ids)), "CODEX ids not unique"
    recs = []
    for law in laws:
        text = law.get("quote") or law.get("rule") or law.get("title") or ""
        enforced_by = (
            law.get("code_paths")
            or law.get("code")
            or law.get("gates")
            or law.get("enforcement")
            or "prose-only"
        )
        if isinstance(enforced_by, list):
            enforced_by = "; ".join(str(x) for x in enforced_by)
        recs.append({
            "id": law["id"],
            "name": law.get("name_en", ""),
            "text": text,
            "source": "CODEX.json chapter %s (status: %s)" % (
                law.get("chapter", "?"), law.get("status", "active")),
            "enforced_by": enforced_by,
        })
    return recs, codex.get("counts", {})


def build():
    codex_recs, codex_counts = _codex_records()
    n_codex = len(codex_recs)
    n_standing = len(STANDING_LAWS)
    total = n_codex + n_standing

    # Reconciliation: CODEX internal counts must match what we read.
    assert codex_counts.get("total") == n_codex, (
        "CODEX self-count mismatch: counts.total=%r vs read %d"
        % (codex_counts.get("total"), n_codex))
    assert n_codex == 168, "expected 168 CODEX laws, read %d" % n_codex
    assert n_standing == 8, "expected 8 standing laws, have %d" % n_standing

    out = codex_recs + [
        {
            "id": s["id"], "name": s["name"], "text": s["text"],
            "source": s["source"], "enforced_by": s["enforced_by"],
        }
        for s in STANDING_LAWS
    ]
    assert len(out) == 176, "counts in != counts out: %d" % len(out)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generated_from": os.path.basename(CODEX_PATH),
            "counts": {"codex": n_codex, "standing": n_standing, "total": total},
            "laws": out,
        }, f, ensure_ascii=False, indent=1)
    return {"codex_in": n_codex, "standing_in": n_standing, "total_out": total,
            "path": OUT_PATH}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=1))
