#!/usr/bin/env python3
"""Batch-2 triple-test for genesis-eyes n8n automations (batch-2 workflows only).

Same TRIPLE-TEST LAW as batch-1: three independent runs, all green.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from n8n_runner import run_workflow, validate_workflow, MockLLM
from registry import REGISTRY

WORKFLOWS = ['1280_Linkedin_Telegram_Automation_Scheduled',
 '1304_Telegram_Code_Monitor_Webhook',
 '1330_Linkedin_Schedule_Automate_Webhook',
 '1522_Telegram_Schedule_Send_Webhook',
 '1552_Manual_Summarize_Automation_Triggered',
 '1625_Splitout_Schedule_Monitor_Webhook',
 '1697_Schedule_HTTP_Monitor_Scheduled',
 '1772_Filter_Rssfeedread_Monitor_Scheduled',
 '1782_Linkedin_Telegram_Automation_Scheduled',
 '1879_Wait_Slack_Monitor_Triggered',
 '1934_Splitout_Schedule_Create_Scheduled',
 '1982_Telegram_Splitout_Automation_Scheduled']
DISPOSITIONS = {'1280_Linkedin_Telegram_Automation_Scheduled': 'SLOTS',
 '1304_Telegram_Code_Monitor_Webhook': 'SLOTS',
 '1330_Linkedin_Schedule_Automate_Webhook': 'SLOTS',
 '1522_Telegram_Schedule_Send_Webhook': 'SLOTS',
 '1552_Manual_Summarize_Automation_Triggered': 'RUNNABLE',
 '1625_Splitout_Schedule_Monitor_Webhook': 'SLOTS',
 '1697_Schedule_HTTP_Monitor_Scheduled': 'SLOTS',
 '1772_Filter_Rssfeedread_Monitor_Scheduled': 'SLOTS',
 '1782_Linkedin_Telegram_Automation_Scheduled': 'SLOTS',
 '1879_Wait_Slack_Monitor_Triggered': 'SLOTS',
 '1934_Splitout_Schedule_Create_Scheduled': 'SLOTS',
 '1982_Telegram_Splitout_Automation_Scheduled': 'SLOTS'}


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
