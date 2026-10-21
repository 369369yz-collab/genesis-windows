"""genesis-wakeword — CPU-friendly on-device wake-word detector.

Approach (honest, no trained model shipped):
  1. Voice Activity Detection on 20ms frames — webrtcvad when installed,
     otherwise a pure-Python energy VAD fallback (documented in README).
  2. When a speech segment ends, an energy/ZCR contour of the segment is
     compared (cosine similarity, length-normalized) against a template
     recorded during ENROLLMENT. Detection is "this sounds like the enrolled
     utterance of the keyword", not true phonetic recognition.

This requires enrollment: the user speaks the keyword 3+ times and
`enroll()` builds the template. Without a trained neural model this is
moderately accurate — see README "Accuracy limits" and the documented
upgrade path to an openWakeWord-style ONNX model (no fake model files).

Everything runs on-device. No GPU. No network calls anywhere in this module.
"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

import numpy as np

try:  # optional: webrtcvad is the documented primary VAD
    import webrtcvad

    _VAD_IMPL = "webrtcvad"
except Exception:  # pragma: no cover - fallback path
    webrtcvad = None
    _VAD_IMPL = "energy_fallback"

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320 int16 samples
CONTOUR_LENGTH = 40  # frames -> 0.8s keyword window


def _frame_features(frame: np.ndarray) -> tuple:
    """(log_energy, zero_crossing_rate) for one int16 frame."""
    x = frame.astype(np.float64)
    energy = float(np.mean(x * x))
    log_energy = math.log10(energy + 1e-12)
    signs = np.sign(x)
    zcr = float(np.sum(signs[1:] * signs[:-1] < 0)) / max(len(x) - 1, 1)
    return log_energy, zcr


def _contour(pcm: np.ndarray) -> np.ndarray:
    """Nx2 (log_energy, zcr) contour, one row per 20ms frame."""
    pcm = np.asarray(pcm, dtype=np.int16).ravel()
    n = len(pcm) // FRAME_SAMPLES
    feats = np.zeros((max(n, 1), 2), dtype=np.float64)
    for i in range(n):
        feats[i, 0], feats[i, 1] = _frame_features(pcm[i * FRAME_SAMPLES:(i + 1) * FRAME_SAMPLES])
    return feats


def _normalize(feats: np.ndarray) -> np.ndarray:
    """Zero-mean/unit-variance per feature column (energy contours vary by mic gain)."""
    mu = feats.mean(axis=0)
    sigma = feats.std(axis=0) + 1e-9
    return (feats - mu) / sigma


def _resample(feats: np.ndarray, length: int = CONTOUR_LENGTH) -> np.ndarray:
    """Linear-resample a contour to fixed frame count so utterances align."""
    if len(feats) == length:
        return feats
    idx = np.linspace(0, len(feats) - 1, length)
    out = np.empty((length, feats.shape[1]))
    for c in range(feats.shape[1]):
        out[:, c] = np.interp(idx, np.arange(len(feats)), feats[:, c])
    return out


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of flattened contours, always a finite float in [-1, 1].

    Overflow-safe by construction: each vector is scaled by its own max
    absolute value (a finite scale-invariant rescale) BEFORE the dot product,
    so dot/norm can never overflow float64 — even for corrupt templates with
    extreme-but-finite values that passed load validation. Vectors of
    different lengths are not comparable and yield 0.0; empty, zero, or
    non-finite vectors yield 0.0; the final clamp+finite guard guarantees the
    public result dict can never carry NaN/Inf downstream.

    Hard contract (closed for every input): for ANY ndarray inputs this
    function returns a finite float in [-1, 1] and never raises — only
    MemoryError/KeyboardInterrupt/SystemExit propagate. Non-numeric or
    otherwise unconvertible input degrades to 0.0 instead of raising.
    """
    try:
        fa = np.asarray(a, dtype=np.float64).ravel()
        fb = np.asarray(b, dtype=np.float64).ravel()
    except MemoryError:
        raise  # out of memory must surface, never be masked
    except Exception:
        # Unconvertible input (ragged/object arrays, non-numeric data):
        # degrade to 0.0 rather than raising.
        return 0.0
    if fa.shape != fb.shape or fa.size == 0:
        return 0.0

    def _safe_unit(v: np.ndarray) -> np.ndarray:
        m = np.max(np.abs(v)) if v.size else 0.0
        if not np.isfinite(m) or m == 0.0:
            return np.zeros_like(v)
        s = v / m  # |s| <= 1 elementwise: dot and norm below can never overflow
        n = float(np.linalg.norm(s))
        if not np.isfinite(n) or n == 0.0:
            return np.zeros_like(v)
        return s / n

    ua, ub = _safe_unit(fa), _safe_unit(fb)
    sim = float(np.dot(ua, ub))
    if not math.isfinite(sim):
        return 0.0
    return max(-1.0, min(1.0, sim))


class _Vad:
    """webrtcvad wrapper with an honest pure-Python energy fallback."""

    def __init__(self, aggressiveness: int = 2, energy_threshold_db: float = -45.0):
        self.energy_threshold_db = energy_threshold_db
        self._vad = webrtcvad.Vad(aggressiveness) if webrtcvad else None

    @property
    def implementation(self) -> str:
        return "webrtcvad" if self._vad is not None else "energy_fallback"

    def is_speech(self, frame_bytes: bytes) -> bool:
        if self._vad is not None:
            return bool(self._vad.is_speech(frame_bytes, SAMPLE_RATE))
        x = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float64)
        if x.size == 0:
            return False
        rms = math.sqrt(float(np.mean(x * x)))
        db = 20.0 * math.log10(rms + 1e-9)
        return db > self.energy_threshold_db


@dataclass
class _Enrollment:
    keyword: str
    template: np.ndarray  # (CONTOUR_LENGTH, 2), normalized

    def to_dict(self) -> Dict:
        return {"keyword": self.keyword, "template": self.template.tolist()}

    @staticmethod
    def from_dict(d: Dict) -> "_Enrollment":
        # Strict validation: a corrupt template must be rejected at load time
        # with a clean error dict, never explode later inside score().
        if not isinstance(d, dict):
            raise ValueError("template file must contain a JSON object")
        keyword = d.get("keyword")
        if not isinstance(keyword, str) or not keyword:
            raise ValueError("template 'keyword' must be a non-empty string")
        raw = d.get("template")
        try:
            template = np.array(raw, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("template matrix is not numeric: %s" % exc) from exc
        if template.ndim != 2 or template.shape != (CONTOUR_LENGTH, 2):
            raise ValueError(
                "template must have shape (%d, 2), got %s"
                % (CONTOUR_LENGTH, template.shape))
        if not np.all(np.isfinite(template)):
            raise ValueError("template contains NaN or infinite values")
        # Magnitude bound: templates produced by enroll() are z-normalized,
        # so any real value stays far below this. Extreme magnitudes (e.g.
        # +-1e308) pass the finiteness check above but would overflow float64
        # inside score(); reject such corrupt/hand-crafted files at load.
        if np.any(np.abs(template) > 1e6):
            raise ValueError("template contains out-of-range values "
                             "(|x| > 1e6); corrupt or hand-crafted template")
        return _Enrollment(keyword=keyword, template=template)


class WakeWordDetector:
    """On-device wake-word detector for one keyword (default "genesis").

    Usage:
        det = WakeWordDetector(keyword="genesis", on_wake=lambda: print("WAKE"))
        det.enroll([samples...])          # list of int16 np arrays, user speaking keyword
        det.listen()                      # blocks until stop() is called
        det.stop()
    """

    def __init__(
        self,
        keyword: str = "genesis",
        on_wake: Optional[Callable[[], None]] = None,
        threshold: float = 0.72,
        vad_aggressiveness: int = 2,
    ):
        self.keyword = keyword
        self.on_wake = on_wake or (lambda: None)
        self.threshold = float(threshold)
        self._vad = _Vad(aggressiveness=vad_aggressiveness)
        self._enrollment: Optional[_Enrollment] = None
        self._stop_event = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None
        # Avatar-first UI surface: this module owns only the mic indicator
        # state. Rendering belongs to the avatar host's summoned-layer
        # renderer; this module never builds panels (see ui_surface()).
        self._mic_state: str = "idle"

    # ------------------------------------------------------------------ state
    @property
    def enrolled(self) -> bool:
        return self._enrollment is not None

    @property
    def vad_implementation(self) -> str:
        return self._vad.implementation

    # --------------------------------------------------------------- enroll
    def enroll(self, utterances: List[np.ndarray]) -> Dict:
        """Build the keyword template from 1+ recordings of the user saying the keyword.

        Each utterance: int16 mono numpy array at 16000 Hz (any length ~0.3-1.5s).
        Returns {"status": ...} dict per contract.
        """
        if not utterances:
            return {"status": "error", "reason": "no_utterances",
                    "message": "enroll() needs at least one utterance (int16 array @16kHz)."}
        contours = []
        for u in utterances:
            pcm = np.asarray(u, dtype=np.int16).ravel()
            if pcm.size < FRAME_SAMPLES * 4:
                return {"status": "error", "reason": "utterance_too_short",
                        "message": f"utterance has {pcm.size} samples; need >= {FRAME_SAMPLES * 4}."}
            contours.append(_normalize(_resample(_contour(pcm))))
        template = np.median(np.stack(contours), axis=0)
        self._enrollment = _Enrollment(keyword=self.keyword, template=_normalize(template))
        return {"status": "ok", "keyword": self.keyword,
                "utterances_used": len(utterances),
                "vad": self._vad.implementation}

    def score(self, pcm: np.ndarray) -> Dict:
        """Score one audio chunk against the enrolled template.

        Returns similarity in [-1, 1] (cosine of flattened normalized contours).
        """
        if not self.enrolled:
            return {"status": "not_enrolled",
                    "message": "Call enroll() with keyword utterances before scoring."}
        feats = _normalize(_resample(_contour(np.asarray(pcm, dtype=np.int16))))
        sim = _similarity(feats, self._enrollment.template)
        detected = sim >= self.threshold
        return {"status": "ok", "similarity": sim,
                "detected": detected, "threshold": self.threshold}

    # --------------------------------------------------------------- persistence
    def save_template(self, path: str) -> Dict:
        if not self.enrolled:
            return {"status": "not_enrolled"}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._enrollment.to_dict(), f)
            return {"status": "ok", "path": os.path.abspath(path)}
        except OSError as exc:
            return {"status": "error", "reason": "io_error", "message": str(exc)}

    def load_template(self, path: str) -> Dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._enrollment = _Enrollment.from_dict(json.load(f))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"status": "error", "reason": "bad_template", "message": str(exc)}
        return {"status": "ok", "keyword": self._enrollment.keyword,
                "path": os.path.abspath(path)}

    # -------------------------------------------------------- UI surface
    def ui_surface(self) -> Dict:
        """UI-surface contract (avatar-first law).

        This module's only UI surface is the whisper-thin mic indicator:
        idle / listening / heard / thinking. "thinking" is host-owned (the
        avatar host flashes it once the mind takes over after a wake); this
        module reports idle/listening/heard only. No panels are ever built
        here — floating-layer rendering belongs to the avatar host's
        summoned-layer renderer (v1.1 spec).
        """
        return {
            "module": "genesis-wakeword",
            "surface": "mic_indicator",
            "allowed_states": ["idle", "listening", "heard", "thinking"],
            "current_state": self._mic_state,
            "state_meaning": {
                "idle": "not listening (no active listen() loop)",
                "listening": "actively monitoring the audio stream for the keyword",
                "heard": "keyword just detected; on_wake fired (host should flash)",
                "thinking": "host-owned: mind takes over after wake; module reports heard->idle",
            },
            "rendering": "avatar host summoned-layer renderer; module builds no panels",
        }

    # ----------------------------------------------------------------- listen
    def listen(self, source: Optional[Iterable[np.ndarray]] = None) -> Dict:
        """Block and listen for the keyword; call on_wake() on each detection.

        source=None  -> live microphone (requires sounddevice; see README).
        source=iterable of int16 chunks -> simulated stream (tests / dev).
        Returns a {"status": ...} dict when the loop ends (stop() called,
        source exhausted, or a configuration problem).
        """
        if not self.enrolled:
            return {"status": "not_enrolled",
                    "message": "Detector has no enrolled template. Call enroll() first."}
        self._stop_event.clear()
        self._mic_state = "listening"
        try:
            if source is None:
                return self._listen_mic()
            return self._listen_stream(iter(source))
        finally:
            self._mic_state = "idle"

    def stop(self) -> Dict:
        """Signal a running listen() loop to exit."""
        self._stop_event.set()
        thread = self._listen_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        return {"status": "stopped"}

    # ---------------------------------------------------------------- internals
    def _listen_mic(self) -> Dict:
        try:
            import sounddevice as sd  # local import: optional dependency
        except Exception:
            return {"status": "mic_unavailable",
                    "message": "sounddevice (and its PortAudio library) is not available. "
                               "Install it, or pass an audio iterable to listen(source=...).",
                    "requirements": "sounddevice (pip) + PortAudio native library"}
        frames = _MicStreamer(sd, self._stop_event)
        frames.start()
        try:
            self._listen_stream(frames.chunks())
        finally:
            frames.stop()
        return {"status": "stopped"}

    def _listen_stream(self, chunks: Iterable[np.ndarray]) -> Dict:
        segment: List[np.ndarray] = []
        silence_frames = 0
        detections = 0
        try:
            for chunk in chunks:
                if self._stop_event.is_set():
                    return {"status": "stopped", "detections": detections}
                frame = np.asarray(chunk, dtype=np.int16).ravel()
                # feed the VAD whole 20ms frames even if chunks are smaller
                for i in range(0, len(frame), FRAME_SAMPLES):
                    f = frame[i:i + FRAME_SAMPLES]
                    if len(f) < FRAME_SAMPLES:
                        continue
                    speech = self._vad.is_speech(f.tobytes())
                    if speech:
                        segment.append(f)
                        silence_frames = 0
                    else:
                        if segment:
                            silence_frames += 1
                            # end of speech segment after ~300ms of silence
                            if silence_frames >= 15:
                                self._handle_segment(np.concatenate(self._trim(segment)))
                                detections += 1 if getattr(self, "_last_detected", False) else 0
                                segment = []
                                silence_frames = 0
            # trailing segment
            if segment and not self._stop_event.is_set():
                self._handle_segment(np.concatenate(self._trim(segment)))
                detections += 1 if getattr(self, "_last_detected", False) else 0
        except Exception as exc:
            return {"status": "error", "reason": "stream_error", "message": str(exc)}
        return {"status": "stream_ended", "detections": detections}

    @staticmethod
    def _trim(frames: List[np.ndarray]) -> List[np.ndarray]:
        """Drop trailing low-energy frames (VAD hangover) so scoring sees the utterance.

        Energy-based, not VAD-flag-based: webrtcvad keeps internal memory and may
        flag a few silence frames as speech after a burst. Any trailing frame with
        RMS below 15% of the segment peak is cut.
        """
        if not frames:
            return frames
        rms = np.array([float(np.sqrt(np.mean(f.astype(np.float64) ** 2))) for f in frames])
        peak = rms.max()
        # Gentle floor: only true digital-silence / room-hiss frames are cut.
        # (A keyword's natural envelope decay is much louder than this.)
        floor = max(peak * 0.02, 300.0)  # 300 int16 units ~= -40 dBFS
        end = len(frames)
        while end > 1 and rms[end - 1] < floor:
            end -= 1
        return frames[:end]

    def _handle_segment(self, pcm: np.ndarray) -> None:
        res = self.score(pcm)
        self._last_detected = bool(res.get("detected"))
        self._mic_state = "heard" if self._last_detected else "listening"
        if self._last_detected:
            try:
                self.on_wake()
            except Exception:
                pass  # on_wake must never kill the listen loop


class _MicStreamer:
    """sounddevice callback -> queue of 20ms int16 frames. Windows/Linux/macOS."""

    def __init__(self, sd_module, stop_event: threading.Event):
        self._sd = sd_module
        self._stop_event = stop_event
        import queue
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=256)
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            pass
        try:
            self._queue.put_nowait(np.asarray(indata[:, 0] * 32767, dtype=np.int16))
        except Exception:
            pass

    def start(self):
        self._stream = self._sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=FRAME_SAMPLES, callback=self._callback)
        self._stream.start()

    def chunks(self):
        while not self._stop_event.is_set():
            try:
                yield self._queue.get(timeout=0.2)
            except Exception:
                continue

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
