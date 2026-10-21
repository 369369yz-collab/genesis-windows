"""Tests for the never-forget core. Run: python -m pytest test_never_forget.py -q
or: python test_never_forget.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from never_forget import store, gate  # noqa: E402
from never_forget.store import open_loop, record_action, close_loop, load_loops, open_ids  # noqa: E402
from never_forget.gate import check  # noqa: E402


def fresh():
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.unlink(p)
    return p


def test_open_and_load():
    p = fresh()
    open_loop(p, "l1", "Test loop", "tester", deadline_ts=None, evidence="seed", source="test")
    loops = load_loops(p)
    assert "l1" in loops and loops["l1"]["status"] == "open"
    assert loops["l1"]["title"] == "Test loop"


def test_action_updates_idle():
    p = fresh()
    open_loop(p, "l2", "Action loop", "tester")
    record_action(p, "l2", note="did a thing")
    loops = load_loops(p)
    assert "did a thing" in loops["l2"]["evidence"]


def test_close_requires_evidence():
    p = fresh()
    open_loop(p, "l3", "Close loop", "tester")
    try:
        close_loop(p, "l3", evidence="")
        assert False, "must raise"
    except ValueError:
        pass
    close_loop(p, "l3", evidence="done, see proof.txt", closed_by="tester")
    assert "l3" not in open_ids(p)


def test_history_never_deleted():
    p = fresh()
    open_loop(p, "l4", "Hist loop", "tester")
    close_loop(p, "l4", evidence="done")
    lines = [l for l in open(p) if l.strip()]
    assert len(lines) == 2  # open + close both retained


def test_gate_passes_fresh():
    p = fresh()
    open_loop(p, "l5", "Fresh loop", "tester")
    r = check(p)
    assert r["failed"] is False and r["total_open"] == 1


def test_gate_fails_stale_and_overdue():
    import json
    from datetime import datetime, timedelta, timezone
    p = fresh()
    now = datetime.now(timezone.utc)
    # stale: opened + last action 30h ago, no deadline
    old = (now - timedelta(hours=30)).isoformat()
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": "open", "id": "stale1", "opened_ts": old,
                            "title": "Stale loop", "owner": "tester",
                            "deadline_ts": None, "status": "open",
                            "last_action_ts": old,
                            "evidence": "", "source": "test"}) + "\n")
    # overdue: deadline in the past
    past = (now - timedelta(hours=2)).isoformat()
    open_loop(p, "od1", "Overdue loop", "tester", deadline_ts=past)
    r = check(p)
    assert r["failed"] is True
    assert any(x["id"] == "stale1" for x in r["stale"])
    assert any(x["id"] == "od1" for x in r["overdue"])
    rep = gate.format_report(r)
    assert "GATE FAILED" in rep and "stale1" in rep and "od1" in rep


if __name__ == "__main__":
    test_open_and_load()
    test_action_updates_idle()
    test_close_requires_evidence()
    test_history_never_deleted()
    test_gate_passes_fresh()
    test_gate_fails_stale_and_overdue()
    print("never_forget core: 6/6 tests green")
