"""Tests for the dispatcher voice methods (ADR-017) — transcribe/synthesize/status."""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from services.ui_backend.src._stub import StubGateway, StubVoiceEngine
from services.ui_backend.src.dispatcher import RpcDispatcher
from services.voice.src.audio import encode_b64_pcm


def _run(dispatcher: RpcDispatcher, request: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(request, send))
    return frames


def _voice_dispatcher() -> RpcDispatcher:
    return RpcDispatcher(StubGateway(), None, voice=StubVoiceEngine())


# ── voice_status ───────────────────────────────────────────────────────


def test_voice_status_reports_available() -> None:
    frames = _run(_voice_dispatcher(), {"id": 1, "method": "voice_status", "params": {}})
    assert frames[0]["ok"] is True
    assert frames[0]["result"]["stt"] is True
    assert frames[0]["result"]["tts"] is True
    assert "af_heart" in frames[0]["result"]["voices"]


def test_voice_status_without_engine_reports_unavailable() -> None:
    d = RpcDispatcher(StubGateway(), None, voice=None)
    frames = _run(d, {"id": 1, "method": "voice_status", "params": {}})
    assert frames[0]["result"] == {"stt": False, "tts": False, "voices": []}


# ── transcribe ─────────────────────────────────────────────────────────


def test_transcribe_returns_text() -> None:
    audio_b64 = encode_b64_pcm(np.zeros(1600, dtype=np.float32))
    frames = _run(
        _voice_dispatcher(),
        {"id": 7, "method": "transcribe", "params": {"audio_b64": audio_b64, "sample_rate": 16000}},
    )
    assert frames[0]["ok"] is True
    assert "stub transcript" in frames[0]["result"]["text"]


def test_transcribe_unavailable_without_engine() -> None:
    d = RpcDispatcher(StubGateway(), None, voice=None)
    audio_b64 = encode_b64_pcm(np.zeros(16, dtype=np.float32))
    frames = _run(d, {"id": 1, "method": "transcribe", "params": {"audio_b64": audio_b64}})
    assert frames[0]["ok"] is False
    assert frames[0]["error"]["code"] == "voice_unavailable"


# ── synthesize (streaming) ─────────────────────────────────────────────


def test_synthesize_streams_audio_then_end() -> None:
    frames = _run(
        _voice_dispatcher(),
        {"id": 5, "method": "synthesize", "params": {"text": "one two three", "voice": "af_heart"}},
    )
    kinds = [f.get("stream") for f in frames]
    assert kinds[-1] == "end"
    audio_frames = [f for f in frames if f.get("stream") == "audio"]
    assert len(audio_frames) == 3  # one chunk per word (stub)
    # frames carry monotonically increasing index + a base64 payload
    assert [f["value"]["index"] for f in audio_frames] == [0, 1, 2]
    assert all(f["value"]["audio_b64"] for f in audio_frames)
    assert frames[-1]["value"]["chunks"] == 3
    assert all(f["id"] == 5 for f in frames)


def test_synthesize_unavailable_without_engine() -> None:
    d = RpcDispatcher(StubGateway(), None, voice=None)
    frames = _run(d, {"id": 1, "method": "synthesize", "params": {"text": "hi"}})
    assert frames[0]["ok"] is False
    assert frames[0]["error"]["code"] == "voice_unavailable"


# ── prompt with streaming speech (ADR-017) ─────────────────────────────


def test_prompt_speak_interleaves_audio_then_pgov_end() -> None:
    from services.ui_gateway.src.session_store import SessionStore

    store = SessionStore(db_path=":memory:")
    sid = store.create_session()
    d = RpcDispatcher(StubGateway(), store, voice=StubVoiceEngine())
    frames = _run(d, {"id": 3, "method": "prompt",
                      "params": {"session_id": sid, "prompt": "hello there", "speak": True}})
    kinds = [f.get("stream") for f in frames]
    assert "token" in kinds
    assert "audio" in kinds  # reply was synthesized as it streamed
    assert kinds[-2:] == ["pgov", "end"]  # audio all precedes the verdict + end
    assert all(f["id"] == 3 for f in frames)


def test_prompt_without_speak_emits_no_audio() -> None:
    from services.ui_gateway.src.session_store import SessionStore

    store = SessionStore(db_path=":memory:")
    sid = store.create_session()
    d = RpcDispatcher(StubGateway(), store, voice=StubVoiceEngine())
    frames = _run(d, {"id": 4, "method": "prompt",
                      "params": {"session_id": sid, "prompt": "hello there"}})  # no speak
    assert "audio" not in [f.get("stream") for f in frames]


# ── voice_set_stt / voice_set_tts (on-demand load/unload, #660) ─────────


def test_voice_set_tts_disable_then_enable_round_trips_status() -> None:
    voice = StubVoiceEngine()
    d = RpcDispatcher(StubGateway(), None, voice=voice)

    # Disable: unloads TTS; status reports tts off + empty voices.
    frames = _run(d, {"id": 1, "method": "voice_set_tts", "params": {"enabled": False}})
    assert frames[0]["ok"] is True
    assert frames[0]["result"]["tts"] is False
    assert frames[0]["result"]["voices"] == []
    assert voice.tts_available is False

    # Enable: loads TTS; status reports tts on + voices back.
    frames = _run(d, {"id": 2, "method": "voice_set_tts", "params": {"enabled": True}})
    assert frames[0]["result"]["tts"] is True
    assert "af_heart" in frames[0]["result"]["voices"]
    assert voice.tts_available is True


def test_voice_set_stt_disable_then_enable_round_trips_status() -> None:
    voice = StubVoiceEngine()
    d = RpcDispatcher(StubGateway(), None, voice=voice)

    frames = _run(d, {"id": 1, "method": "voice_set_stt", "params": {"enabled": False}})
    assert frames[0]["result"]["stt"] is False
    assert voice.stt_available is False

    frames = _run(d, {"id": 2, "method": "voice_set_stt", "params": {"enabled": True}})
    assert frames[0]["result"]["stt"] is True
    assert voice.stt_available is True


def test_voice_set_stt_only_touches_stt_not_tts() -> None:
    voice = StubVoiceEngine()
    d = RpcDispatcher(StubGateway(), None, voice=voice)
    _run(d, {"id": 1, "method": "voice_set_stt", "params": {"enabled": False}})
    # TTS must be untouched by an STT toggle.
    assert voice.tts_available is True


def test_voice_set_without_engine_reports_unavailable() -> None:
    d = RpcDispatcher(StubGateway(), None, voice=None)
    frames = _run(d, {"id": 1, "method": "voice_set_tts", "params": {"enabled": True}})
    assert frames[0]["ok"] is True
    assert frames[0]["result"] == {"stt": False, "tts": False, "voices": []}


def test_voice_set_tts_defaults_enabled_false_when_param_missing() -> None:
    # A missing "enabled" param is treated as disable (fail-safe: never auto-load).
    voice = StubVoiceEngine()
    d = RpcDispatcher(StubGateway(), None, voice=voice)
    frames = _run(d, {"id": 1, "method": "voice_set_tts", "params": {}})
    assert frames[0]["result"]["tts"] is False
    assert voice.tts_available is False
