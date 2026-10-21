"""Single-step runner used by the sandbox path.

Invoked inside a sandbox (or anywhere) as:
    python -m genesis_hands.step_runner <base64url-json-step>

The permission gate is NOT consulted here: hands.py already applied it before
routing the step to the sandbox. The step JSON printed on stdout is the
backend result dict.
"""

from __future__ import annotations

import base64
import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            json.dumps(
                {"status": "error", "reason": "usage",
                 "detail": "expected exactly one base64url argument"}
            )
        )
        return 2
    try:
        step = json.loads(base64.urlsafe_b64decode(argv[1].encode("ascii")))
    except Exception as exc:  # malformed input -> honest error, no execution
        print(json.dumps({"status": "error", "reason": "bad_step_payload",
                          "detail": str(exc)}))
        return 2
    from genesis_hands import hands

    result = hands.run_single_step(step)
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
