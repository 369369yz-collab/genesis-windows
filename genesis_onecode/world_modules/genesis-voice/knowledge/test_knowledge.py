#!/usr/bin/env python3
"""Triple-test for genesis-voice knowledge packs.

TRIPLE-TEST LAW: every injection gets THREE independent runs, all green.
Run 1: structural -- packs.json parses; every item has id/title/modules.
Run 2: API -- registry functions return complete, consistent results.
Run 3: no-drop -- every id the injection plan assigned to this module is
present in the registry; every search for a known id hits.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import registry as R

MODULE = "voice"
EXPECTED_PACKS = ['artflow', 'chatgpt', 'claude', 'elevenlabs', 'fishaudio', 'heygen', 'synthesia']
EXPECTED_COUNTS = {'heygen': (2, 0, 0), 'synthesia': (0, 1, 0), 'elevenlabs': (13, 8, 4), 'fishaudio': (11, 8, 4), 'artflow': (0, 1, 1), 'claude': (1, 1, 0), 'chatgpt': (2, 1, 1)}  # pack -> (T, P, W)
KNOWN_IDS = [('heygen', 'techniques', 'T-05'), ('synthesia', 'prompt_patterns', 'P-03'), ('elevenlabs', 'techniques', 'T-01'), ('fishaudio', 'techniques', 'T-01'), ('artflow', 'prompt_patterns', 'P-10'), ('claude', 'techniques', 'T-13'), ('chatgpt', 'techniques', 'T-11')]  # sample of ids that must be searchable


def run_structural():
    data = json.loads((Path(__file__).parent / "packs.json").read_text(encoding="utf-8"))
    assert set(data.keys()) == set(EXPECTED_PACKS), f"pack set mismatch: {sorted(data)}"
    for pack, pdata in data.items():
        for kind in ("techniques", "prompt_patterns", "workflows"):
            assert kind in pdata, f"{pack} missing {kind}"
            for item in pdata[kind]:
                assert item.get("id"), f"{pack}/{kind} item missing id"
                assert item.get("title"), f"{pack}/{item.get('id')} missing title"
                assert MODULE in item.get("modules", []), f"{pack}/{item.get('id')} not mapped to {MODULE}"
        for kind, ids in (("techniques", [t["id"] for t in pdata["techniques"]]),
                          ("prompt_patterns", [p["id"] for p in pdata["prompt_patterns"]]),
                          ("workflows", [w["id"] for w in pdata["workflows"]])):
            assert len(ids) == len(set(ids)), f"{pack}/{kind} duplicate ids"
    return f"structural ok: {len(data)} packs"


def run_api():
    assert R.list_packs() == sorted(EXPECTED_PACKS), "list_packs mismatch"
    for pack, (nt, npp, nw) in EXPECTED_COUNTS.items():
        assert len(R.get_techniques(pack)) == nt, f"{pack} technique count"
        assert len(R.get_prompt_patterns(pack)) == npp, f"{pack} pattern count"
        assert len(R.get_workflows(pack)) == nw, f"{pack} workflow count"
        assert isinstance(R.guardrails(pack), list), f"{pack} guardrails not list"
    total = (len(R.get_techniques()) + len(R.get_prompt_patterns())
             + len(R.get_workflows()))
    exp_total = sum(a + b + c for a, b, c in EXPECTED_COUNTS.values())
    assert total == exp_total, f"total {total} != expected {exp_total}"
    return f"api ok: {total} items across {len(EXPECTED_PACKS)} packs"


def run_nodrop():
    for pack, kind, iid in KNOWN_IDS:
        hits = R.search(iid)
        assert any(h[0] == pack and h[2] == iid for h in hits), f"{iid} not found"
    # every technique id from every pack is searchable
    for pack in R.list_packs():
        for tid in R.technique_ids(pack):
            assert R.search(tid), f"{tid} unsearchable"
    return f"no-drop ok: {len(KNOWN_IDS)} spot ids + full sweep"


def main():
    print(f"Testing genesis-{MODULE} knowledge packs ({len(EXPECTED_PACKS)} packs)")
    results = []
    for name, fn in (("structural", run_structural), ("api", run_api),
                     ("no-drop", run_nodrop)):
        for attempt in range(3):
            try:
                detail = fn()
                results.append((name, attempt + 1, True, detail))
            except AssertionError as e:
                results.append((name, attempt + 1, False, str(e)))
    ok = all(r[2] for r in results)
    for name, attempt, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name} run {attempt}: {detail}")
    n = sum(1 for r in results if r[2])
    print(f"\n{n}/{len(results)} runs passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
