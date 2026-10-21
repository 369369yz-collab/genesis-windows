"""ear_listener.py — GENESIS ear module (genesis-ear v1.0.0).

Live Persian speech recognition for GENESIS on Windows, powered by
faster-whisper (open-source, free, CPU-friendly).

  * Model: faster-whisper "small", int8 quantized, CPU. Fast enough for
    real-time chunked transcription on a normal PC; good Persian quality.
  * The model is downloaded ONCE from Hugging Face on first activation
    (free) into ``models/fw-small/`` under this module's directory and
    reused afterwards. Fully offline after that.
  * ``transcribe_file(path)`` — transcribe any audio file (Persian).
  * ``listen_once(seconds)`` — capture one mic chunk and transcribe it.
    Returns {"ok": False, "reason": ...} when no microphone is present —
    never raises.
  * ``start(on_utterance, chunk_seconds)`` — background thread: records
    rolling chunks, transcribes each, and calls ``on_utterance(record)``
    for every non-empty utterance. ``stop()`` ends it cleanly.
  * ``health_check()`` — {"ok", "engine", "model_ready",
    "mic_available"} for the updater's pre-swap gate and the launcher.

The module never crashes its host: every public method returns a result
dict with "ok" instead of raising on expected failures (no mic, no
model yet, silence). Truly unexpected errors are contained by the
module loader's call_guarded boundary.
"""

from __future__ import annotations

import os
import threading
import time

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_DIR = os.path.join(MODULE_DIR, "models", "fw-small")

FASTER_WHISPER_MODEL = "small"
FASTER_WHISPER_DEVICE = "cpu"
FASTER_WHISPER_COMPUTE_TYPE = "int8"
SAMPLE_RATE = 16000


class EarError(Exception):
    """Expected ear failure (no mic, model unavailable)."""


class EarListener:
    """Live Persian ear for GENESIS."""

    def __init__(self, model_dir: str | None = None,
                 device: str = FASTER_WHISPER_DEVICE,
                 compute_type: str = FASTER_WHISPER_COMPUTE_TYPE) -> None:
        # GENESIS_EAR_MODEL_DIR lets the operator point at a pre-seeded
        # model directory (e.g. a snapshot copied from another machine).
        self.model_dir = (model_dir
                          or os.environ.get("GENESIS_EAR_MODEL_DIR")
                          or DEFAULT_MODEL_DIR)
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._model_lock = threading.Lock()
        self._listen_thread: threading.Thread | None = None
        self._listen_stop = threading.Event()
        self.engine = "faster-whisper-%s" % FASTER_WHISPER_MODEL

    # -- model ----------------------------------------------------------
    def _model_path_if_local(self) -> str | None:
        """If model_dir already holds a ready model (a snapshot directory
        containing model.bin), return it for direct use."""
        if os.path.isfile(os.path.join(self.model_dir, "model.bin")):
            return self.model_dir
        return None

    def _ensure_model(self):
        """Lazily load (downloading once if needed). Raises EarError if
        the model cannot be obtained (e.g. offline on first run)."""
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise EarError("faster-whisper not installed: %s" % exc)
            local_path = self._model_path_if_local()
            try:
                if local_path is not None:
                    self._model = WhisperModel(
                        local_path,
                        device=self.device,
                        compute_type=self.compute_type,
                    )
                else:
                    os.makedirs(self.model_dir, exist_ok=True)
                    self._model = WhisperModel(
                        FASTER_WHISPER_MODEL,
                        device=self.device,
                        compute_type=self.compute_type,
                        download_root=self.model_dir,
                    )
            except Exception as exc:  # noqa: BLE001 - e.g. offline
                raise EarError("cannot load/download the ear model: %s: %s"
                               % (type(exc).__name__, exc))
            return self._model

    def model_ready(self) -> bool:
        """True if the model is already on disk (no download needed)."""
        # faster-whisper stores the model under
        # <download_root>/models--Systran--faster-whisper-small/...
        marker = os.path.join(
            self.model_dir, "models--Systran--faster-whisper-small")
        return (os.path.isfile(os.path.join(self.model_dir, "model.bin"))
                or os.path.isdir(marker)
                or self._model is not None)

    # -- transcription ----------------------------------------------------
    def transcribe_file(self, path: str, language: str = "fa") -> dict:
        """Transcribe an audio file. Returns {"ok": True, "text": ...,
        "segments": [...], "language": ..., "duration_s": ...} or
        {"ok": False, "reason": ...}."""
        if not os.path.isfile(path):
            return {"ok": False, "reason": "file not found: %s" % path}
        try:
            model = self._ensure_model()
        except EarError as exc:
            return {"ok": False, "reason": str(exc)}
        started = time.time()
        try:
            segments, info = model.transcribe(path, language=language,
                                              beam_size=5)
            seg_list = []
            texts = []
            for seg in segments:
                seg_list.append({"start": round(seg.start, 2),
                                 "end": round(seg.end, 2),
                                 "text": seg.text.strip()})
                texts.append(seg.text.strip())
        except Exception as exc:  # noqa: BLE001
            return {"ok": False,
                    "reason": "%s: %s" % (type(exc).__name__, exc)}
        text = " ".join(t for t in texts if t).strip()
        return {"ok": True, "text": text, "segments": seg_list,
                "language": getattr(info, "language", language),
                "duration_s": round(time.time() - started, 2),
                "engine": self.engine}

    # -- microphone ---------------------------------------------------------
    def _record_chunk(self, seconds: float,
                      sample_rate: int = SAMPLE_RATE):
        """Record one chunk from the default mic. Raises EarError when no
        microphone/audio backend is available."""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise EarError("microphone backend not installed: %s" % exc)
        except OSError as exc:
            raise EarError("no audio device: %s" % exc)
        try:
            frames = int(seconds * sample_rate)
            audio = sd.rec(frames, samplerate=sample_rate, channels=1,
                           dtype="float32", blocking=True)
        except Exception as exc:  # noqa: BLE001 - no mic, busy device...
            raise EarError("microphone capture failed: %s: %s"
                           % (type(exc).__name__, exc))
        return np.squeeze(audio, axis=1)

    def mic_available(self) -> bool:
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            return any(d.get("max_input_channels", 0) > 0
                       for d in devices)
        except Exception:  # noqa: BLE001
            return False

    def listen_once(self, seconds: float = 4.0,
                    language: str = "fa") -> dict:
        """Capture one utterance from the mic and transcribe it. Never
        raises on silence or missing mic — returns ok=False."""
        try:
            audio = self._record_chunk(seconds)
        except EarError as exc:
            return {"ok": False, "reason": str(exc)}
        try:
            model = self._ensure_model()
        except EarError as exc:
            return {"ok": False, "reason": str(exc)}
        try:
            segments, info = model.transcribe(audio, language=language,
                                              beam_size=5)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False,
                    "reason": "%s: %s" % (type(exc).__name__, exc)}
        if not text:
            return {"ok": False, "reason": "silence",
                    "engine": self.engine}
        return {"ok": True, "text": text,
                "language": getattr(info, "language", language),
                "engine": self.engine}

    def start(self, on_utterance, chunk_seconds: float = 4.0,
              language: str = "fa") -> dict:
        """Start background listening: every chunk is transcribed and
        non-empty utterances are delivered to ``on_utterance(record)``.
        Returns {"ok": True} or {"ok": False, "reason": ...}."""
        if self._listen_thread is not None and self._listen_thread.is_alive():
            return {"ok": False, "reason": "already listening"}
        try:
            self._ensure_model()
        except EarError as exc:
            return {"ok": False, "reason": str(exc)}
        if not self.mic_available():
            return {"ok": False, "reason": "no microphone available"}
        self._listen_stop.clear()

        def _loop():
            while not self._listen_stop.is_set():
                try:
                    audio = self._record_chunk(chunk_seconds)
                    model = self._ensure_model()
                    segments, _info = model.transcribe(
                        audio, language=language, beam_size=5)
                    text = " ".join(
                        s.text.strip() for s in segments).strip()
                    if text:
                        record = {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime()),
                            "text": text,
                            "engine": self.engine,
                        }
                        try:
                            on_utterance(record)
                        except Exception:  # noqa: BLE001 - host callback
                            pass
                except EarError:
                    time.sleep(1.0)
                except Exception:  # noqa: BLE001 - never kill the thread
                    time.sleep(1.0)

        self._listen_thread = threading.Thread(target=_loop, daemon=True,
                                               name="genesis-ear")
        self._listen_thread.start()
        return {"ok": True, "chunk_seconds": chunk_seconds}

    def stop(self) -> dict:
        self._listen_stop.set()
        thread, self._listen_thread = self._listen_thread, None
        if thread is not None:
            thread.join(timeout=10.0)
        return {"ok": True}

    @property
    def listening(self) -> bool:
        return (self._listen_thread is not None
                and self._listen_thread.is_alive())

    # -- health --------------------------------------------------------------
    def health_check(self) -> dict:
        """For the updater pre-swap gate and launcher --check."""
        try:
            from faster_whisper import WhisperModel  # noqa: F401
            engine_ok = True
        except ImportError:
            engine_ok = False
        return {"ok": engine_ok,
                "engine": self.engine,
                "model_ready": self.model_ready(),
                "mic_available": self.mic_available()}
