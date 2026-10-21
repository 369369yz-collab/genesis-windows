# genesis-eyes v1.0.0

GENESIS's eyes: screen capture + sight for the Windows assistant.

## What it does

- `capture(region=None)` — grabs the screen (or a `(x, y, width, height)`
  region) and returns complete **PNG bytes**.
- `see(prompt="")` — takes a real screenshot and packages it with the prompt
  for the bridge vision call point. Returns an explicit
  `{"status": "bridge_not_configured"}` envelope — never a fabricated answer.
- `stream_sight(interval_s, callback, max_frames=None)` — periodic capture
  loop; each frame's PNG bytes go to `callback`. Stops when the callback
  returns `False`, when `max_frames` is reached, or on capture failure
  (reported honestly in the returned dict).

## Architecture

```
genesis-eyes/
  eyes.py                 public API: capture / see / stream_sight
  tests/test_eyes.py      pytest suite (11 tests)
  test_logs/              three independent green pytest runs
  windows_smoke_test.py   quick API check for the Windows runner
  requirements.txt        mss, pillow (both free/open-source)
```

Platform dispatch is in `eyes.py`: `capture()` routes to `_capture_windows`
on `sys.platform == "win32"` and to `_capture_other` everywhere else.
Validation (region shape, interval positivity, callable checks) runs before
any backend is touched. Failures surface as `ValueError` (bad input) or
`CaptureError` (the machine cannot capture).

## Bridge call points

- `bridge_vision` (used by `see()`): payload = PNG image (base64) + prompt.
  **Status: documented and stubbed.** `see()` returns
  `{"status": "bridge_not_configured", "call_point": "bridge_vision",
  "payload": {...real capture...}}`. The integration layer wires the payload
  to the network mind; this module never invents a vision answer.

## What's real vs what's stub

| Piece | Status |
|---|---|
| `capture()` on Windows | REAL — Pillow `ImageGrab` (native GDI). Not yet run on Windows; mock-tested on Linux, smoke test provided. |
| `capture()` on Linux/dev | REAL — mss backend, exercised against a virtual display in tests. |
| PNG encoding | REAL — full PNG bytes verified by magic bytes + Pillow round-trip. |
| Region validation, error paths | REAL — covered by tests. |
| `see()` vision answer | STUB — returns `bridge_not_configured`; the capture inside it is real. |
| `stream_sight()` loop | REAL — timing, stop conditions, and error reporting tested. |

Nothing in this module fakes a network call. There is no local vision model
bundled (per father's decision).

## Windows-only notes

- On Windows, `capture()` uses `PIL.ImageGrab.grab()` — no extra native
  dependency beyond Pillow. Multi-monitor: `region=None` captures the primary
  display; pass an explicit region for other monitors.
- On the Windows runner, run `windows_smoke_test.py` with the bundled venv
  Python. It prints PASS/SKIP per check and never claims success it did not
  measure.

## API reference

```python
from eyes import capture, see, stream_sight, CaptureError

png: bytes = capture()                      # full primary display, PNG bytes
png: bytes = capture((100, 100, 800, 600))   # region (x, y, w, h)

result: dict = see("what is on the screen?")
# {"status": "bridge_not_configured", "call_point": "bridge_vision",
#  "payload": {"image_format": "png", "image_bytes": N,
#              "image_base64": "...", "prompt": "..."}, "note": "..."}

result: dict = stream_sight(2.0, my_callback, max_frames=10)
# {"status": "completed" | "stopped_by_callback" | "error",
#  "frames": N}  (+ "error": msg when status == "error")
```

All public functions return plain dicts (with a `status` key) or bytes.
Raises: `ValueError` on invalid arguments, `CaptureError` when the machine
cannot capture.
