"""kernel/arbitration.py — instruction precedence.

Precedence (highest first):
    1. yz_direct        — YZ's direct orders. Always win.
    2. local_law        — CODEX + the 8 standing laws (kernel/laws.json).
    3. extended_mind    — advice from the 369 world agent mesh. Advisory only.

Extended-mind responses MUST carry source:"extended-mind" in their provenance
marker; a response claiming extended-mind origin without it is untrusted and
auto-rejected.

Any conflict the kernel cannot resolve automatically is auto-rejected and
recorded to Agent YZ's decision queue
(content_team/yz_agent/decision_queue.jsonl, kind=law_conflict_flag —
schema per content_team/yz_agent/queue_law.py: jsonl, one dict per line with
ts/source/law/kind/subject/detail/status/owner/deadline; TERMINAL statuses
per LAW-093). The queue path is injectable for tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))

# Provenance marker every extended-mind response MUST carry.
EXTENDED_MIND_SOURCE_TAG = "extended-mind"

DEFAULT_QUEUE_PATH = os.path.expanduser(
    "~/workspace/content_team/yz_agent/decision_queue.jsonl")

# Deadline default for conflict flags, mirroring queue_law.DEADLINE_HOURS
# (law_conflict_flag: 48h).
CONFLICT_DEADLINE_HOURS = 48
QUEUE_OWNER = "yz_agent"
KERNEL_LAW_ID = "KERNEL-ARBITRATION"


@dataclass
class Instruction:
    id: str
    topic: str                  # what the instruction is about
    action: str                 # what it orders/advises
    source: str                 # yz_direct | local_law | extended_mind
    provenance: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


@dataclass
class ArbitrationDecision:
    winner: Optional[Instruction]
    rejected: List[Instruction]
    reason: str
    conflicts_logged: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "winner": ({"id": self.winner.id, "source": self.winner.source,
                        "topic": self.winner.topic, "action": self.winner.action}
                       if self.winner else None),
            "rejected": [{"id": i.id, "source": i.source, "reason": r}
                         for i, r in self.rejected],
            "reason": self.reason,
            "conflicts_logged": self.conflicts_logged,
        }


class ArbitrationError(RuntimeError):
    """A malformed instruction or an untrusted provenance marker."""


_RANK = {"yz_direct": 3, "local_law": 2, "extended_mind": 1}


def _norm(action: str) -> str:
    return " ".join(action.strip().lower().split())


def _check_provenance(instr: Instruction) -> Optional[str]:
    """Validate the extended-mind source marker. Returns a rejection reason or None."""
    if instr.source == "extended_mind":
        if instr.provenance.get("source") != EXTENDED_MIND_SOURCE_TAG:
            return ("untrusted: claims extended-mind origin but lacks "
                    "source:'%s' provenance marker" % EXTENDED_MIND_SOURCE_TAG)
    return None


def _log_conflict(queue_path: str, *, subject: str, detail: Dict[str, Any]) -> Dict[str, Any]:
    """Append a law_conflict_flag record to the decision queue (schema = queue_law.py)."""
    now = datetime.now(timezone.utc)
    rec = {
        "ts": now.isoformat(timespec="seconds"),
        "source": "genesis-kernel/arbitration.py",
        "law": KERNEL_LAW_ID,
        "kind": "law_conflict_flag",
        "subject": subject,
        "detail": detail,
        "status": "pending",
        "owner": QUEUE_OWNER,
        "deadline": (now + timedelta(hours=CONFLICT_DEADLINE_HOURS)).isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(queue_path)), exist_ok=True)
    with open(queue_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def arbitrate(instructions: List[Instruction],
              queue_path: str = DEFAULT_QUEUE_PATH) -> ArbitrationDecision:
    """Resolve one topic's competing instructions by precedence.

    - Unknown source -> ArbitrationError.
    - Extended-mind instruction without the source tag -> auto-rejected (untrusted).
    - Same topic, different actions:
        - different precedence ranks -> the highest rank wins; lower ones are
          auto-rejected and the conflict is logged to the decision queue.
        - same rank -> NO automatic winner: all are rejected and the conflict
          is logged (a tie is not a resolution).
    - Same topic, same action -> the highest-ranked instruction wins silently.
    """
    if not instructions:
        return ArbitrationDecision(None, [], "no instructions given")

    for instr in instructions:
        if instr.source not in _RANK:
            raise ArbitrationError(
                "instruction %s carries unknown source %r" % (instr.id, instr.source))

    rejected: List[tuple] = []
    trusted: List[Instruction] = []
    for instr in instructions:
        reason = _check_provenance(instr)
        if reason:
            rejected.append((instr, reason))
        else:
            trusted.append(instr)

    conflicts_logged: List[Dict[str, Any]] = []
    if not trusted:
        return ArbitrationDecision(None, rejected,
                                   "every instruction was rejected (untrusted provenance)",
                                   conflicts_logged)

    # Group by topic.
    by_topic: Dict[str, List[Instruction]] = {}
    for instr in trusted:
        by_topic.setdefault(instr.topic, []).append(instr)

    # Resolve each topic; final winner = winner of the first topic's resolution.
    # (One arbitrate() call = one topic in practice; multi-topic is resolved
    # topic by topic and the highest-ranked topic winner returned.)
    topic_winners: List[Instruction] = []
    for topic, group in by_topic.items():
        actions = {_norm(i.action) for i in group}
        if len(actions) == 1:
            group.sort(key=lambda i: _RANK[i.source], reverse=True)
            topic_winners.append(group[0])
            continue
        ranks = sorted({_RANK[i.source] for i in group}, reverse=True)
        if len(ranks) > 1:
            # Clear precedence winner; everyone below loses and the conflict
            # is auto-rejected + recorded.
            top = ranks[0]
            winners = [i for i in group if _RANK[i.source] == top]
            losers = [i for i in group if _RANK[i.source] < top]
            win = winners[0]
            topic_winners.append(win)
            conflict = _log_conflict(
                queue_path,
                subject="kernel arbitration: %s overrode on topic '%s'" % (
                    win.source, topic),
                detail={
                    "topic": topic,
                    "winner": {"id": win.id, "source": win.source, "action": win.action},
                    "auto_rejected": [
                        {"id": i.id, "source": i.source, "action": i.action}
                        for i in losers
                    ],
                    "rule": "precedence: yz_direct > local_law > extended_mind",
                },
            )
            conflicts_logged.append(conflict)
            for i in losers:
                rejected.append((i, "overruled by higher-precedence %s instruction" % win.source))
        else:
            # Same rank, contradictory actions — a tie is NOT a resolution.
            conflict = _log_conflict(
                queue_path,
                subject="kernel arbitration: UNRESOLVED tie on topic '%s'" % topic,
                detail={
                    "topic": topic,
                    "contenders": [
                        {"id": i.id, "source": i.source, "action": i.action}
                        for i in group
                    ],
                    "rule": "same-precedence contradiction -> all rejected, father decides",
                },
            )
            conflicts_logged.append(conflict)
            for i in group:
                rejected.append((i, "same-precedence contradiction — auto-rejected, father decides"))

    topic_winners.sort(key=lambda i: _RANK[i.source], reverse=True)
    if not topic_winners:
        return ArbitrationDecision(None, rejected,
                                   "no resolvable winner: every instruction was rejected",
                                   conflicts_logged)
    winner = topic_winners[0]
    reason = ("precedence %s wins on topic '%s'"
              % (winner.source, winner.topic))
    return ArbitrationDecision(winner, rejected, reason, conflicts_logged)
