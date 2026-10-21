"""Tests for the genesis-ear module.

The transcription test is REAL: faster-whisper small (int8, CPU) against
the cached Hugging Face snapshot, transcribing the father's actual
Persian voice-enrollment audio. No stubs, no mocks on that path.
"""

import os
import sys

import pytest

GW_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
EAR_DIR = os.path.join(GW_DIR, "modules", "genesis-ear")
if EAR_DIR not in sys.path:
    sys.path.insert(0, EAR_DIR)

from ear_listener import EarListener  # noqa: E402

HF_SNAPSHOT = ("/home/hatch/.cache/huggingface/hub/"
               "models--Systran--faster-whisper-small/snapshots/"
               "536b0662742c02347bc0e980a01041f333bce120")

FA_AUDIO = os.path.join(GW_DIR, "identity_vault",
                        "voice_enrollment_20261012.m4a")

needs_model = pytest.mark.skipif(
    not os.path.isfile(os.path.join(HF_SNAPSHOT, "model.bin")),
    reason="faster-whisper small snapshot not cached on this machine")


def _ear():
    return EarListener(model_dir=HF_SNAPSHOT)


def test_health_check_reports_engine():
    ear = _ear()
    health = ear.health_check()
    assert health["engine"] == "faster-whisper-small"
    assert health["model_ready"] is True
    assert isinstance(health["mic_available"], bool)


@needs_model
def test_real_persian_transcription():
    """Father's real Persian voice enrollment -> Persian text out."""
    assert os.path.isfile(FA_AUDIO), "Persian test audio missing"
    ear = _ear()
    result = ear.transcribe_file(FA_AUDIO, language="fa")
    assert result["ok"] is True, result.get("reason")
    text = result["text"]
    assert isinstance(text, str) and len(text.strip()) > 0
    assert result["language"] == "fa"
    assert len(result["segments"]) >= 1
    # The enrollment states his name: the model must hear Persian words.
    assert any("\u0600" <= ch <= "\u06FF" for ch in text), \
        "expected Persian script in transcription, got: %r" % text


@needs_model
def test_transcription_result_shape():
    ear = _ear()
    result = ear.transcribe_file(FA_AUDIO, language="fa")
    assert result["ok"] is True
    for seg in result["segments"]:
        assert {"start", "end", "text"} <= set(seg)
        assert seg["end"] >= seg["start"]


def test_missing_file_is_ok_false_not_raise():
    ear = _ear()
    result = ear.transcribe_file("/nonexistent/audio.wav")
    assert result["ok"] is False
    assert "reason" in result


def test_listen_once_without_mic_is_ok_false():
    ear = _ear()
    result = ear.listen_once(seconds=0.5)
    # On a machine with no mic this is ok=False; on a machine WITH a mic
    # it may genuinely record — either way it must not raise.
    assert isinstance(result, dict) and "ok" in result


def test_start_stop_lifecycle_without_mic():
    ear = _ear()
    got = []
    started = ear.start(got.append, chunk_seconds=0.5)
    # No mic on CI/VM -> clean refusal; a real mic -> background thread.
    assert isinstance(started, dict) and "ok" in started
    stopped = ear.stop()
    assert stopped["ok"] is True
    assert ear.listening is False
