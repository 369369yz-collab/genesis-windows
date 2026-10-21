#!/usr/bin/env python3
"""Triple-test for genesis-scheduler n8n automations.

TRIPLE-TEST LAW: every injection gets THREE independent runs, all green.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from n8n_runner import run_workflow, validate_workflow, MockLLM
from registry import REGISTRY

MODULE = "scheduler"
WORKFLOWS = ['2063', '2088', '2110', '2137', '2139', '2273', '2324', '2605', '2722', '2783', '2803', '3121', '3442', '3790', '3791', '3840', '4352', '4573', '4846', '4968', '5035', '5110', '5139', '5338', '5841', '5906', '5962', '6239', '8642']


def _mock_http(method, url, body, headers):
    """Deterministic mock HTTP (no real network in tests)."""
    return {
        "items": [{"id": 1, "title": "Mock Title", "text": "Mock text",
                   "url": "https://example.com/1", "essay": "Mock essay",
                   "name": "Mock", "email": "m@e.com", "output": "Mock output",
                   "message": {"content": "Mock"}, "data": {"status": "ok"},
                   "status": "ok"}],
        "output": "Mock output", "text": "Mock text", "status": "ok",
        "images": [{"url": "https://example.com/mock.jpg"}],
    }


def _load(wid):
    p = Path(__file__).parent / "workflows" / f"{wid}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw.get("workflow", raw)


def test_workflow(wid):
    """Run triple-test for one workflow. Returns (passed, detail)."""
    wf = _load(wid)
    meta = REGISTRY.get(wid, {})
    disp = meta.get("disposition", "UNKNOWN")

    # 1. Structural validation
    issues = validate_workflow(wf)
    # 5385 has a documented duplicate-node-name issue (workflow authoring)
    real_issues = [i for i in issues if not (wid == "5385" and "duplicate" in i)]
    if real_issues:
        return False, f"validation: {real_issues}"

    # 2. Three independent runs
    results = []
    for run in range(3):
        kwargs = dict(llm=MockLLM(), http_transport=_mock_http)
        # 585 needs a work_dir with a PDF
        if wid == "585":
            import tempfile, os
            wd = Path(tempfile.mkdtemp())
            pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                   b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                   b"3 0 obj<</Type/Page/Parent 2 0 R/Contents 4 0 R>>endobj\n"
                   b"4 0 obj<</Length 44>>stream\n"
                   b"BT /F1 12 Tf 72 712 Td (Hello GENESIS) Tj ET\nendstream\nendobj\n"
                   b"trailer<</Root 1 0 R>>\n")
            (wd / "pdf.pdf").write_bytes(pdf)
            kwargs["work_dir"] = wd
        try:
            r = run_workflow(wf, **kwargs)
            results.append((r.status, r.blocked_at))
        except Exception as e:
            results.append(("RAISED", f"{type(e).__name__}: {e}"))

    # 3. All three must be consistent
    if len(set(results)) != 1:
        return False, f"inconsistent runs: {results}"
    status, blocked_at = results[0]

    # 4. Assert per disposition
    if disp == "RUNNABLE":
        if status != "ok":
            return False, f"expected ok, got {status} at {blocked_at}"
    elif disp == "NEEDS_LLM":
        if status not in ("ok", "slot_blocked"):
            return False, f"expected ok/slot_blocked, got {status}"
    elif disp == "SLOTS":
        # slot_blocked at credential, ok (main flow), or intentional stopAndError
        if status == "slot_blocked":
            pass  # correct fail-closed
        elif status == "ok":
            pass  # main flow completes; tools are ai_tool slots
        elif status == "error" and blocked_at:
            # 1978: intentional stopAndError ("AI did fail us1")
            wf2 = _load(wid)
            node = next((n for n in wf2.get("nodes", [])
                         if n.get("name") == blocked_at), None)
            if node and node.get("type") == "n8n-nodes-base.stopAndError":
                pass  # designed halt point
            else:
                return False, f"unexpected error at {blocked_at}"
        else:
            return False, f"expected slot_blocked/ok, got {status}"
    else:
        return False, f"unknown disposition {disp}"

    return True, f"{disp} {status} x3"


def main():
    print(f"Testing genesis-{MODULE} n8n automations ({len(WORKFLOWS)} workflows)")
    passed, failed = 0, []
    for wid in sorted(WORKFLOWS):
        ok, detail = test_workflow(wid)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {wid}: {detail}")
        if ok:
            passed += 1
        else:
            failed.append(wid)
    print(f"\n{passed}/{len(WORKFLOWS)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
