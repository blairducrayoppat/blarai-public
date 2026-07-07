"""
Stub gateway for headless smoke-testing the named-pipe bridge (ADR-014).
========================================================================
A no-GPU stand-in for :class:`TransportGateway` that echoes prompts and serves
canned document/session replies. It exists so the pipe transport and RPC
dispatch can be exercised on real Windows named pipes WITHOUT the heavy runtime
(admin / Hyper-V / model compile). The production backend wiring (real gateway
behind the same pipe) lands in Phase 2 alongside the WinUI app.

NOT imported by production code paths — only the ``--stub`` entrypoint mode,
the smoke script, and the dispatcher unit tests use it.
"""

from __future__ import annotations

import math
from typing import AsyncIterator, Iterator

import numpy as np

from services.ui_gateway.src.transport import GatewayPGOVResult, StreamToken


class StubGateway:
    """Echo gateway: deterministic, no GPU, mirrors the methods the dispatcher calls."""

    def __init__(self) -> None:
        self._last_prompt: dict[str, str] = {}
        self._last_request: dict[str, str] = {}

    # ── Documents / attachments ───────────────────────────────────────

    def load_document(self, session_id: str, filename: str) -> dict[str, object]:
        return {
            "filename": filename,
            "content": f"[stub] contents of {filename}",
            "size_bytes": len(filename),
            "injection_warnings": [],
            "media_type": "text",
            "message": "",
        }

    def unload_documents(self, session_id: str) -> None:
        return None

    def list_userdata_files(self) -> list[dict[str, object]]:
        return []

    def trust_documents_for_tools(self, session_id: str) -> None:
        return None

    # ── Chat ──────────────────────────────────────────────────────────

    async def send_prompt(self, session_id: str, prompt: str) -> str:
        request_id = f"stub-{len(prompt)}-{session_id[:8]}"
        self._last_prompt[session_id] = prompt
        self._last_request[session_id] = request_id
        return request_id

    async def stream_tokens(self, session_id: str) -> AsyncIterator[StreamToken]:
        reply = f"You said: {self._last_prompt.get(session_id, '')}"
        words = reply.split(" ")
        for i, word in enumerate(words):
            token_text = word if i == len(words) - 1 else word + " "
            yield StreamToken(
                token=token_text,
                token_index=i,
                is_final=(i == len(words) - 1),
                is_tool_call=False,
                session_id=session_id,
            )

    def get_pgov_result(self, request_id: str) -> GatewayPGOVResult:
        return GatewayPGOVResult(
            approved=True,
            sanitized_text="(stub reply)",
            reason_codes=[],
            request_id=request_id,
        )

    def flush_tool_call_buffer(self, pgov_approved: bool) -> list[StreamToken]:
        return []


class StubVoiceEngine:
    """No-model voice engine: deterministic transcription + a sine-tone synth.

    Lets the mic/play affordances and the ``transcribe``/``synthesize`` frames be
    exercised over a real pipe without Whisper or Kokoro loaded. Mirrors the
    :class:`~services.voice.src.engine.VoiceEngine` surface the dispatcher calls.
    """

    _VOICES = ["af_heart", "am_adam"]

    def __init__(self) -> None:
        # Mutable so the runtime load/unload toggles (#660) can be exercised over
        # a real pipe / in dispatcher tests without Whisper or Kokoro present.
        self._stt = True
        self._tts = True

    @property
    def stt_available(self) -> bool:
        return self._stt

    @property
    def tts_available(self) -> bool:
        return self._tts

    def available_voices(self) -> list[str]:
        return list(self._VOICES) if self._tts else []

    def status(self) -> dict[str, object]:
        return {
            "stt": self._stt,
            "tts": self._tts,
            "voices": list(self._VOICES) if self._tts else [],
            "default_voice": self._VOICES[0],
        }

    # ── Runtime load / unload (#660) ──────────────────────────────────
    def load_stt(self) -> bool:
        self._stt = True
        return True

    def unload_stt(self) -> bool:
        was = self._stt
        self._stt = False
        return was

    def load_tts(self) -> bool:
        self._tts = True
        return True

    def unload_tts(self) -> bool:
        was = self._tts
        self._tts = False
        return was

    def transcribe(self, samples_16k: np.ndarray) -> str:
        # Deterministic, references the input length so tests can assert it ran.
        return f"[stub transcript of {len(samples_16k)} samples]"

    def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float | None = None
    ) -> Iterator[tuple[np.ndarray, int]]:
        # One short 440 Hz tone chunk per whitespace-delimited word.
        sample_rate = 24000
        for i, _word in enumerate(text.split() or ["."]):
            n = sample_rate // 10  # 100 ms
            t = np.arange(n, dtype=np.float32) / sample_rate
            yield 0.2 * np.sin(2 * math.pi * 440 * t).astype(np.float32), sample_rate


def build_stub_backend(db_path: str = ":memory:"):
    """Return ``(StubGateway, SessionStore)`` for stub serving / smoke tests.

    Deliberately uses the PLAINTEXT :class:`SessionStore`, not the encrypted
    variant (Sprint 14 EA-4 / ADR-025 decision).  Rationale: this is the pure
    in-memory transport-smoke path — synthetic echo data that never touches
    disk, exercised by transport tests that assert on pipe behaviour.  There is
    no confidentiality surface to protect, and threading DEK-envelope
    construction through every transport smoke test would add crypto setup cost
    for zero security benefit.  The REAL session-DB paths (the launcher and
    ``--no-model``) MUST use :func:`~services.ui_gateway.src.session_store.build_session_store`
    and are encrypted at rest; this stub path is the documented exception.
    """
    from services.ui_gateway.src.session_store import SessionStore

    return StubGateway(), SessionStore(db_path=db_path)
