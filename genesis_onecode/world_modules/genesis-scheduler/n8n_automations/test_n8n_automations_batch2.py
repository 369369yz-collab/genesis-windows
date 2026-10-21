#!/usr/bin/env python3
"""Batch-2 triple-test for genesis-scheduler n8n automations (batch-2 workflows only).

Same TRIPLE-TEST LAW as batch-1: three independent runs, all green.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from n8n_runner import run_workflow, validate_workflow, MockLLM
from registry import REGISTRY

WORKFLOWS = ['0970_HTTP_Schedule_Create_Webhook',
 '1239_Googlecontacts_Schedule_Send_Scheduled',
 '1392_Telegram_Googleanalytics_Automation_Scheduled',
 '1406_Schedule_Slack_Automation_Scheduled',
 '1679_Telegram_GoogleCalendar_Automation_Scheduled',
 '1751_Filter_Schedule_Automation_Scheduled',
 '1905_Telegram_Googleanalytics_Automation_Webhook']
DISPOSITIONS = {'0970_HTTP_Schedule_Create_Webhook': 'SLOTS',
 '1239_Googlecontacts_Schedule_Send_Scheduled': 'SLOTS',
 '1392_Telegram_Googleanalytics_Automation_Scheduled': 'SLOTS',
 '1406_Schedule_Slack_Automation_Scheduled': 'SLOTS',
 '1679_Telegram_GoogleCalendar_Automation_Scheduled': 'SLOTS',
 '1751_Filter_Schedule_Automation_Scheduled': 'SLOTS',
 '1905_Telegram_Googleanalytics_Automation_Webhook': 'SLOTS'}


def _mock_http(method, url, body, headers):
    return {
        "items": [{"id": 1, "title": "Mock Title", "text": "Mock text",
                   "url": "https://example.com/1", "message": {"content": "Mock"},
                   "status": "ok"}],
        "output": "Mock output", "text": "Mock text", "status": "ok",
        "images": [{"url": "https://example.com/mock.jpg"}],
    }


def test_workflow(wid):
    p = Path(__file__).parent / "workflows" / f"{wid}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    wf = raw.get("workflow", raw)
    disp = DISPOSITIONS[wid]
    issues = validate_workflow(wf)
    if issues:
        return False, f"validation: {issues}"
    results = []
    for _ in range(3):
        try:
            r = run_workflow(wf, llm=MockLLM(), http_transport=_mock_http)
            results.append((r.status, r.blocked_at))
        except Exception as e:
            results.append(("RAISED", f"{type(e).__name__}: {e}"))
    if len(set(results)) != 1:
        return False, f"inconsistent: {results}"
    status, blocked_at = results[0]
    if disp == "RUNNABLE" and status != "ok":
        return False, f"expected ok, got {status}"
    if disp == "SLOTS" and status not in ("slot_blocked", "ok"):
        if not (status == "error" and blocked_at):
            return False, f"expected slot_blocked/ok, got {status}"
    return True, f"{disp} {status} x3"


def main():
    passed, failed = 0, []
    for wid in sorted(WORKFLOWS):
        ok, detail = test_workflow(wid)
        print(f"  [{'PASS' if ok else 'FAIL'}] {wid}: {detail}")
        if ok:
            passed += 1
        else:
            failed.append(wid)
    print(f"{passed}/{len(WORKFLOWS)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
