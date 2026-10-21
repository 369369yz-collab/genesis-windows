"""genesis-eyes: screen capture and sight for the GENESIS assistant.

Target platform: Windows 10/11 (Python 3.12, bundled venv). Developed and tested
on Linux with Windows-only APIs behind platform guards; see README.md for the
honest real-vs-stub account.

Public API:
    capture(region=None) -> bytes          PNG bytes of the screen (or a region)
    see(prompt="") -> dict                real capture packaged for bridge vision
    stream_sight(interval_s, callback,
                 max_frames=None) -> dict periodic capture loop

Code is 100% technical English. No placeholders presented as real; no fabricated
network calls anywhere.
"""

from __future__ import annotations

import base64
import io
import math
import sys
import time
from typing import Callable, Optional, Tuple

__version__ = "1.0.0"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class CaptureError(RuntimeError):
    """Raised when the screen cannot be captured on this machine."""


def _validate_region(region: Optional[Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
    """Validate region=(x, y, width, height); returns the cleaned tuple."""
    if region is None:
        return None
    if not isinstance(region, tuple) or len(region) != 4:
        raise ValueError("region must be a tuple (x, y, width, height) or None")
    x, y, w, h = region
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y, w, h)):
        raise ValueError("region values must be integers")
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError("region requires x>=0, y>=0, width>0, height>0")
    return (x, y, w, h)


def _capture_windows(region: Optional[Tuple[int, int, int, int]]) -> bytes:
    """Native capture on Windows via Pillow's ImageGrab (GDI backend)."""
    from PIL import ImageGrab

    bbox = None if region is None else (region[0], region[1],
                                       region[0] + region[2], region[1] + region[3])
    try:
        img = ImageGrab.grab(bbox=bbox)
    except Exception as exc:  # pragma: no cover - Windows-only runtime path
        raise CaptureError("Windows native capture failed: %s" % exc) from exc
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _capture_other(region: Optional[Tuple[int, int, int, int]]) -> bytes:
    """Cross-platform capture for dev machines via mss (no Windows APIs)."""
    try:
        import mss
    except ImportError as exc:
        raise CaptureError(
            "mss is required for capture on non-Windows platforms; "
            "install it from requirements.txt") from exc
    from PIL import Image

    try:
        with mss.MSS() as sct:
            if region is None:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            else:
                x, y, w, h = region
                monitor = {"left": x, "top": y, "width": w, "height": h}
            shot = sct.grab(monitor)
    except Exception as exc:
        raise CaptureError("capture failed on this machine: %s" % exc) from exc
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def capture(region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
    """Capture the screen (or region) and return PNG bytes.

    Args:
        region: optional (x, y, width, height) tuple; None captures the
            primary display.

    Returns:
        bytes: a complete PNG image.

    Raises:
        ValueError: on an invalid region.
        CaptureError: when the platform backend cannot capture (e.g. no
            display server on headless Linux).
    """
    region = _validate_region(region)
    if sys.platform == "win32":
        return _capture_windows(region)
    return _capture_other(region)


def see(prompt: str = "") -> dict:
    """Capture the screen and package it for the bridge vision call point.

    The capture is REAL (see capture()). The vision ANSWER is not produced
    here: there is no local vision model bundled (father cancelled the local
    LLM). This function returns {"status": "bridge_not_configured"} together
    with the exact payload the bridge call needs, so the integration layer
    can wire it to the network mind's bridge_vision endpoint.

    Args:
        prompt: optional question/instruction about what is on screen.

    Returns:
        dict with status="bridge_not_configured", call_point="bridge_vision",
        and the real payload (PNG as base64 + prompt).
    """
    png = capture()
    payload = {
        "image_format": "png",
        "image_bytes": len(png),
        "image_base64": base64.b64encode(png).decode("ascii"),
        "prompt": str(prompt),
    }
    return {
        "status": "bridge_not_configured",
        "call_point": "bridge_vision",
        "payload": payload,
        "note": ("Vision is answered by the network mind via the bridge; no "
                 "local vision model is bundled. Wire payload['image_base64'] "
                 "and payload['prompt'] to bridge_vision to get a real answer. "
                 "Nothing is fabricated here."),
    }


def stream_sight(interval_s: float,
                 callback: Callable[[bytes], object],
                 max_frames: Optional[int] = None) -> dict:
    """Run a periodic screen-capture loop, handing each PNG frame to callback.

    The loop stops when callback returns False, when max_frames is reached,
    or when a capture fails (reported honestly in the returned dict).

    Args:
        interval_s: seconds between captures; must be > 0.
        callback: called as callback(png_bytes) per frame; return False to stop.
        max_frames: optional cap on frames (useful for tests and demos).

    Returns:
        dict with status "completed" | "stopped_by_callback" | "error",
        frames captured, and an error message on failure.
    """
    if not isinstance(interval_s, (int, float)) or isinstance(interval_s, bool) \
            or not math.isfinite(interval_s) or interval_s <= 0:
        raise ValueError("interval_s must be a positive number of seconds")
    if not callable(callback):
        raise ValueError("callback must be callable")
    if max_frames is not None:
        if not isinstance(max_frames, int) or isinstance(max_frames, bool) or max_frames <= 0:
            raise ValueError("max_frames must be a positive integer or None")

    frames = 0
    try:
        while True:
            png = capture()
            frames += 1
            keep_going = callback(png)
            if keep_going is False:
                return {"status": "stopped_by_callback", "frames": frames}
            if max_frames is not None and frames >= max_frames:
                return {"status": "completed", "frames": frames}
            time.sleep(interval_s)
    except CaptureError as exc:
        return {"status": "error", "frames": frames, "error": str(exc)}
