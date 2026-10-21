"""genesis-voice — Persian voice assistant. TEXT-FIRST OUTPUT. NO TTS, NO synthetic voice.

Pipeline:
    listen_command(timeout_s)   -> mic capture (sounddevice), audio shipped to the
                                   bridge STT call point (documented, stubbed honestly).
    parse_command(text_fa)      -> Persian text -> structured intent {action, params}.
    run_command(text_fa)        -> parse + execute via genesis_hands (imported from the
                                   sibling staging dir when present; otherwise a clear
                                   "hands_not_available" status - never faked).

Everything this module outputs to father is TEXT. Voice synthesis is forbidden
by standing law (NO AI VOICE LAW); there is deliberately no TTS code anywhere.

On-device STT is out of scope: transcription happens in the bridge (network
mind). This module documents the exact bridge call point but NEVER fabricates
a transcript - when the bridge is not configured it returns
{"status": "bridge_not_configured"}.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional

SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * 20 // 1000  # 20ms int16 frames

# ---------------------------------------------------------------------------
# Bridge call point: speech-to-text.
# The real implementation lives in the GENESIS bridge (network mind) and is
# injected at runtime via the `stt_backend` constructor argument of
# VoiceAssistant. Contract of the backend:
#     backend(audio_bytes: bytes, sample_rate: int, language: str) -> dict
#     -> {"status": "ok", "text": "<persian transcript>"}
# ---------------------------------------------------------------------------


def bridge_stt(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE,
               language: str = "fa") -> Dict:
    """DOCUMENTED BRIDGE CALL POINT (STUB).

    Replace by injecting a real backend into VoiceAssistant(stt_backend=...).
    This stub never fabricates a transcript.
    """
    return {
        "status": "bridge_not_configured",
        "message": ("No STT backend is configured. On the Windows build, the GENESIS "
                    "bridge provides transcription (network mind). Inject it as "
                    "VoiceAssistant(stt_backend=<callable>). No transcript is faked."),
        "audio_bytes": len(audio_bytes),
        "sample_rate": sample_rate,
        "language": language,
    }


# ---------------------------------------------------------------------------
# Jalali (Persian) calendar: pure-stdlib Gregorian -> Jalali conversion.
# Father is Persian, so get_date answers in the Jalali calendar, in Tehran
# local time. Iran abolished DST in 2022 (permanent +03:30), so a fixed
# offset is used instead of zoneinfo/tzdata (which is unavailable on the
# bundled Windows Python).
#
# Algorithm: the jalaali-js kazemi/breaks algorithm (public domain math),
# verified here against jdatetime over EVERY day from 1970-01-01 to
# 2030-12-31 (22,280 days, zero mismatches) before shipping.
# ---------------------------------------------------------------------------

_TEHRAN_TZ = _dt.timezone(_dt.timedelta(hours=3, minutes=30))


def _jdiv(a: int, b: int) -> int:
    """Integer division with truncation toward zero (JS %/div semantics)."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _jmod(a: int, b: int) -> int:
    return a - _jdiv(a, b) * b


def _jal_cal(jy: int):
    breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
              1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]
    gy = jy + 621
    leap_j = -14
    jp = breaks[0]
    jump = 0
    i = 1
    while i < len(breaks):
        jm = breaks[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _jdiv(jump, 33) * 8 + _jdiv(_jmod(jump, 33), 4)
        jp = jm
        i += 1
    n = jy - jp
    leap_j += _jdiv(n, 33) * 8 + _jdiv(_jmod(n, 33) + 3, 4)
    if _jmod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _jdiv(gy, 4) - _jdiv((_jdiv(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _jdiv(jump + 4, 33) * 33
    leap = _jmod(_jmod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = (_jdiv((gy + _jdiv(gm - 8, 6) + 100100) * 1461, 4)
         + _jdiv(_jmod(gm + 9, 12) * 153 + 2, 5)
         + gd - 34840408)
    return d - _jdiv(_jdiv(gy + 100100 + _jdiv(gm - 8, 6), 100) * 3, 4) + 752


def _d2g(jdn: int):
    j = 4 * jdn + 139361631
    j = j + _jdiv(_jdiv(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _jdiv(_jmod(j, 1461), 4) * 5 + 308
    gd = _jdiv(_jmod(i, 153), 5) + 1
    gm = _jmod(_jdiv(i, 153), 12) + 1
    gy = _jdiv(j, 1461) - 100100 + _jdiv(8 - gm, 6)
    return gy, gm, gd


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    """(gy, gm, gd) -> (jy, jm, jd). Verified against jdatetime on all days
    1970-01-01..2030-12-31 (see test suite)."""
    jdn = _g2d(gy, gm, gd)
    gy_full = _d2g(jdn)[0]
    jy = gy_full - 621
    leap, _, march = _jal_cal(jy)
    jdn1f = _g2d(gy_full, 3, march)
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + _jdiv(k, 31), _jmod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _jdiv(k, 30), _jmod(k, 30) + 1


_JALALI_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
# datetime.weekday(): Monday=0 .. Sunday=6
_FA_WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه",
                "یکشنبه")


def format_jalali_fa(gy: int, gm: int, gd: int) -> str:
    """Gregorian date -> Persian Jalali date string, e.g. «سه‌شنبه ۱۳ مهر ۱۴۰۵»."""
    jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
    wd = _FA_WEEKDAYS[_dt.date(gy, gm, gd).weekday()]
    return str(f"{wd} {jd} {_JALALI_MONTHS[jm - 1]} {jy}").translate(_FA_DIGITS)


def today_tehran() -> _dt.date:
    """Current date in Tehran (fixed +03:30; Iran has no DST since 2022)."""
    return _dt.datetime.now(_TEHRAN_TZ).date()


def clean_note_text(text: str) -> str:
    """Strip control characters (incl \\r, \\t, \\x00-\\x1f, DEL) from a note so
    the line-based notes file stays single-line clean. Unicode text (Persian,
    ZWNJ, digits) is untouched."""
    return "".join(ch for ch in (text or "")
                   if ord(ch) >= 32 and ord(ch) != 127).strip()


# ---------------------------------------------------------------------------
# Persian command parser: text -> structured intent {action, params}
# ---------------------------------------------------------------------------

# Each rule: (action, [(regex, param_builder)]). First match wins.
_INTENT_RULES: List = []


def _rule(action: str, patterns: List[str]):
    def deco(fn):
        _INTENT_RULES.append((action, [(re.compile(p), fn) for p in patterns]))
        return fn
    return deco


@_rule("get_time", [r"ساعت\s*(چنده|چند است)?\s*$", r".*\bساعت\b.*چند.*"])
def _p_time(m):
    return {}


@_rule("get_date", [r".*(امروز).*(چه روزی|تاریخ).*", r".*تاریخ امروز.*"])
def _p_date(m):
    return {}


@_rule("open_app", [r"^\s*(باز|اجرا)\s*کن\s+(?P<app>.+?)\s*$",
                   r"^\s*(?P<app>.+?)\s*رو?\s*باز\s*کن\s*$"])
def _p_open(m):
    return {"app": m.group("app").strip()}


@_rule("close_app", [r"^\s*(ببند|خاموش کن)\s+(?P<app>.+?)\s*$",
                     r"^\s*(?P<app>.+?)\s*رو?\s*ببند\s*$"])
def _p_close(m):
    return {"app": m.group("app").strip()}


@_rule("web_search", [r"^\s*(جستجو|سرچ|گوگل)\s*کن\s+(?P<query>.+?)\s*$"])
def _p_search(m):
    return {"query": m.group("query").strip()}


@_rule("screenshot", [r".*(اسکرین[\s‌]*شات|عکس از صفحه|اسنپ[\s‌]*شات|عکس بگیر).*"])
def _p_shot(m):
    return {}


@_rule("volume", [r".*صدا\s*رو?\s*(زیاد|بلند)\s*کن.*", r".*صدا\s*رو?\s*(کم|پایین)\s*کن.*",
                 r".*(بی[\s‌]*صدا|میوت|ساکت).*(کن|شو).*"])
def _p_volume(m):
    text = m.string
    if re.search(r"بی[\s‌]*صدا|میوت|ساکت", text):
        direction = "mute"
    elif re.search(r"زیاد|بلند", text):
        direction = "up"
    else:
        direction = "down"
    return {"direction": direction}


@_rule("note", [r"^\s*یادداشت\s*کن\s+(?P<text>.+?)\s*$"])
def _p_note(m):
    return {"text": m.group("text").strip()}


@_rule("lock_screen", [r".*(قفل|لاک)\s*کن.*", r"^\s*قفل\s*$"])
def _p_lock(m):
    return {}


def parse_command(text_fa: str) -> Dict:
    """Persian command text -> {"status","intent": {"action","params"}, "text"}.

    Unknown input -> action "unknown" (honest; nothing is guessed into an action).
    """
    text = (text_fa or "").strip()
    if not text:
        return {"status": "error", "reason": "empty_text",
                "message": "No command text to parse."}
    for action, patterns in _INTENT_RULES:
        for rx, builder in patterns:
            m = rx.match(text)
            if m:
                return {"status": "ok", "text": text,
                        "intent": {"action": action, "params": builder(m)}}
    return {"status": "ok", "text": text,
            "intent": {"action": "unknown", "params": {"raw": text}}}


# ---------------------------------------------------------------------------
# genesis-hands integration point
# ---------------------------------------------------------------------------

def _find_hands():
    """Locate genesis_hands: (1) sibling staging dir, (2) installed package.

    Returns (execute_callable, source_description) or (None, searched_paths).
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "genesis-hands" / "hands.py",
        here.parent / "genesis-hands" / "__init__.py",
    ]
    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("genesis_hands", str(path))
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                return None, f"sibling file {path} failed to import: {exc}"
            if hasattr(module, "execute"):
                return module.execute, f"sibling staging file: {path}"
    try:
        from genesis_hands import execute  # installed package
        return execute, "installed genesis_hands package"
    except Exception:
        pass
    return None, ("searched: " + ", ".join(str(c) for c in candidates)
                  + " and installed 'genesis_hands' package")


def _intent_to_plan(intent: Dict) -> Optional[Dict]:
    """Map a parsed intent to a genesis-hands plan. None = handled locally (text)."""
    action = intent.get("action")
    params = intent.get("params", {})
    if action == "open_app":
        return {"mode": "local", "steps": [
            {"action": "open_app", "target": params["app"], "risk": "low"}]}
    if action == "close_app":
        return {"mode": "local", "steps": [
            {"action": "close_app", "target": params["app"], "risk": "medium"}]}
    if action == "web_search":
        query = params["query"]
        # Percent-encode the query: a naive whitespace->"+" left & ? = # %
        # to corrupt the search (review-B finding). quote_plus handles all.
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(
            query.strip())
        return {"mode": "web", "steps": [
            {"action": "open_url", "target": url, "risk": "low"}]}
    if action == "screenshot":
        return {"mode": "local", "steps": [
            {"action": "screenshot", "target": "screen", "risk": "low"}]}
    if action == "volume":
        return {"mode": "local", "steps": [
            {"action": "set_volume", "target": params["direction"], "risk": "low"}]}
    if action == "lock_screen":
        return {"mode": "local", "steps": [
            {"action": "lock_screen", "target": "session", "risk": "medium"}]}
    return None  # get_time / get_date / note / unknown handled locally as text


class VoiceAssistant:
    """Persian voice assistant. All output is text (no TTS, by law)."""

    def __init__(self, stt_backend: Optional[Callable] = None,
                 notes_path: Optional[str] = None):
        self.stt_backend = stt_backend or bridge_stt
        default_notes = Path(__file__).resolve().parent / "genesis_notes.txt"
        self.notes_path = Path(notes_path) if notes_path else default_notes

    # ------------------------------------------------------------ capture
    def listen_command(self, timeout_s: float = 8.0) -> Dict:
        """Record from the mic (VAD-gated) and transcribe via the STT backend.

        Returns {"status": "ok", "text": transcript} on success,
        {"status": "mic_unavailable"} when sounddevice/PortAudio is missing,
        {"status": "bridge_not_configured"} when no STT backend is wired,
        {"status": "no_speech"} when only silence was heard.
        """
        try:
            import sounddevice as sd  # local import: optional dependency
        except Exception:
            return {"status": "mic_unavailable",
                    "message": ("sounddevice (and its PortAudio library) is not available. "
                                "Install it, or call parse_command()/run_command() with text."),
                    "requirements": "sounddevice (pip) + PortAudio native library"}
        audio = self._capture(sd, timeout_s)
        if audio is None or len(audio) < FRAME_SAMPLES * 4:
            return {"status": "no_speech",
                    "message": f"No speech detected within {timeout_s}s."}
        return self.stt_backend(audio.tobytes(), SAMPLE_RATE, "fa")

    def _capture(self, sd_module, timeout_s: float):
        """VAD-gated capture: start on first speech frame, stop after 1.2s of
        trailing silence or when timeout_s elapses."""
        try:
            import webrtcvad
            vad = webrtcvad.Vad(2)
        except Exception:
            vad = None
        frames: List = []
        started = False
        trailing_silence = 0
        max_frames = int(timeout_s * SAMPLE_RATE / FRAME_SAMPLES)

        def callback(indata, nframes, time_info, status):
            nonlocal started, trailing_silence
            frame = (indata[:, 0] * 32767).astype("int16")
            speech = self._is_speech(vad, frame)
            if speech:
                started = True
                frames.append(frame)
                trailing_silence = 0
            elif started:
                frames.append(frame)
                trailing_silence += 1

        try:
            with sd_module.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                       dtype="float32", blocksize=FRAME_SAMPLES,
                                       callback=callback):
                for _ in range(max_frames):
                    sd_module.sleep(20)
                    if started and trailing_silence >= 60:  # 1.2s
                        break
        except Exception as exc:
            return None if not frames else np_concat(frames)
        return np_concat(frames) if frames else None

    @staticmethod
    def _is_speech(vad, frame) -> bool:
        if vad is not None:
            try:
                return bool(vad.is_speech(frame.tobytes(), SAMPLE_RATE))
            except Exception:
                pass
        import math
        rms = math.sqrt(float((frame.astype(float) ** 2).mean()) + 1e-12)
        return 20.0 * math.log10(rms) > -45.0

    # ------------------------------------------------------------ pipeline
    def run_command(self, text_fa: str) -> Dict:
        """Full pipeline: parse Persian text -> execute -> text response.

        Returns {"status": ..., "response": "<text for father>", ...}.
        """
        parsed = parse_command(text_fa)
        if parsed["status"] != "ok":
            return {"status": parsed["status"],
                    "response": parsed.get("message", "Could not parse the command."),
                    "reason": parsed.get("reason")}
        intent = parsed["intent"]
        action = intent["action"]

        local = self._handle_local(action, intent["params"])
        if local is not None:
            return local

        plan = _intent_to_plan(intent)
        if plan is None:  # unknown action: honest, no guessing
            return {"status": "ok", "intent": intent,
                    "response": "متأسفم، این دستور را متوجه نشدم."}

        execute, hands_src = _find_hands()
        if execute is None:
            return {"status": "hands_not_available",
                    "response": ("دستور فهمیده شد ولی ماژول hands در دسترس نیست؛ "
                                 "اجرا نشد."),
                    "intent": intent,
                    "integration_point": hands_src}
        try:
            result = execute(plan)
        except Exception as exc:
            return {"status": "hands_error", "intent": intent,
                    "response": "اجرای دستور با خطا مواجه شد.",
                    "error": str(exc)}
        return {"status": "ok", "intent": intent, "hands": hands_src,
                "hands_result": result,
                "response": self._describe_result(action, intent["params"], result)}

    def _handle_local(self, action: str, params: Dict) -> Optional[Dict]:
        """Intents answered locally as text (no hands needed). None = not local."""
        if action == "get_time":
            # Re-review finding: answer in Tehran local time (fixed +03:30),
            # not the machine clock — consistent with today_tehran() used by
            # get_date. Machine-local time is wrong on machines in other zones.
            now = _dt.datetime.now(_TEHRAN_TZ).strftime("%H:%M")
            return {"status": "ok",
                    "response": f"ساعت {now} است."}
        if action == "get_date":
            # Finding 2 fix: answer in the Jalali calendar, Tehran local time
            # (machine-local Gregorian was wrong for a Persian father and could
            # be off-by-one across the Tehran/UTC midnight boundary).
            t = today_tehran()
            jy, jm, jd = gregorian_to_jalali(t.year, t.month, t.day)
            return {"status": "ok",
                    "response": f"امروز {format_jalali_fa(t.year, t.month, t.day)} است.",
                    "date_jalali": f"{jy:04d}-{jm:02d}-{jd:02d}",
                    "date_gregorian": t.isoformat()}
        if action == "note":
            # Finding 3 fix: strip \r and other control chars so the stored
            # line is always single-line clean.
            text = clean_note_text(params.get("text", ""))
            if not text:
                return {"status": "error", "reason": "empty_note",
                        "response": "متن یادداشت خالی بود؛ چیزی ذخیره نشد."}
            try:
                with open(self.notes_path, "a", encoding="utf-8") as f:
                    # Tehran-pinned timestamp for consistency with get_time/get_date
                    f.write(f"{_dt.datetime.now(_TEHRAN_TZ).isoformat()} | {text}\n")
            except OSError as exc:
                return {"status": "error", "reason": "note_write_failed",
                        "response": "یادداشت ذخیره نشد.", "error": str(exc)}
            return {"status": "ok", "response": "یادداشت ذخیره شد."}
        return None

    @staticmethod
    def _describe_result(action: str, params: Dict, result: Dict) -> str:
        status = result.get("status", "?") if isinstance(result, dict) else "?"
        if action == "open_app":
            return f"برنامه‌ی {params.get('app')} باز شد." if status == "ok" \
                else f"باز کردن {params.get('app')} انجام نشد ({status})."
        if action == "close_app":
            return f"برنامه‌ی {params.get('app')} بسته شد." if status == "ok" \
                else f"بستن {params.get('app')} انجام نشد ({status})."
        if action == "web_search":
            return f"جستجوی «{params.get('query')}» باز شد."
        if action == "screenshot":
            return "اسکرین‌شات گرفته شد."
        if action == "volume":
            return {"up": "صدا زیاد شد.", "down": "صدا کم شد.",
                    "mute": "بی‌صدا شد."}.get(params.get("direction"), "تنظیم صدا انجام شد.")
        if action == "lock_screen":
            return "صفحه قفل شد."
        return "انجام شد."


def np_concat(frames):
    import numpy as np
    return np.concatenate(frames)
