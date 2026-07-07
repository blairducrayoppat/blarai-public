"""Deterministic test doubles for the harness Layer A (no models, no GPU).

These stand in for the :class:`~services.ui_gateway.src.transport.TransportGateway`
and the dispatcher's async ``send`` sink, so the real
:class:`~services.ui_backend.src.dispatcher.RpcDispatcher` can be exercised
against predictable, fast fakes — including a deliberately SLOW
``load_document`` that models the pre-fix freeze hazard.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Generator


class CollectingSend:
    """An async ``send`` sink matching the dispatcher's ``SendFn`` contract.

    Records every frame together with the ``perf_counter`` time it arrived, so a
    caller can reason about *when* each frame was emitted. That timing is what
    proves off-loop concurrency: a starved event loop emits a canary request's
    frame late.
    """

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.times: list[float] = []

    async def __call__(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)
        self.times.append(time.perf_counter())

    @property
    def ok_result(self) -> Any:
        for f in self.frames:
            if f.get("ok") is True:
                return f.get("result")
        return None

    @property
    def error(self) -> dict[str, Any] | None:
        for f in self.frames:
            if f.get("ok") is False:
                return f.get("error")
        return None

    def stream_values(self, kind: str) -> list[Any]:
        return [f["value"] for f in self.frames if f.get("stream") == kind]


@dataclass
class _Tok:
    """Minimal StreamToken stand-in — the subset ``_m_prompt`` reads."""

    token: str
    is_tool_call: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"token": self.token, "is_tool_call": self.is_tool_call}


@dataclass
class _PGOV:
    """Minimal GatewayPGOVResult stand-in."""

    approved: bool = True
    sanitized_text: str = ""
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "sanitized_text": self.sanitized_text,
            "reason_codes": list(self.reason_codes),
        }


class FakeGateway:
    """A TransportGateway stand-in implementing the subset the dispatcher uses.

    ``load_document`` BLOCKS for ``block_s`` seconds (a synchronous, blocking
    call — exactly the pre-fix grounding hazard). The dispatcher is supposed to
    run it OFF the event loop (``asyncio.to_thread``); if a regression puts it
    back on the loop, that block starves every concurrent request, which the
    freeze-regression test detects.

    The chat surface (``send_prompt`` / ``stream_tokens`` / ``get_pgov_result``)
    streams a fixed approved reply token-by-token with an optional per-token
    delay, so a concurrent attach can be shown NOT to stall it.

    Pass ``approved=False`` to force the PGOV result to deny the reply. This
    exercises the Fail-Closed denial branch in ``_m_prompt``: ``audio_cancel``
    on speak, tool-call buffer discarded with ``pgov_approved=False``, denied
    turn persisted.  The ``flush_calls`` list records every
    ``flush_tool_call_buffer`` call so tests can verify the approved/denied
    argument.
    """

    def __init__(
        self,
        block_s: float = 0.5,
        reply: str = "Hello there friend.",
        token_delay_s: float = 0.0,
        hang: bool = False,
        approved: bool = True,
        tool_call_tokens: list[_Tok] | None = None,
    ) -> None:
        self.block_s = block_s
        self.reply = reply
        self.token_delay_s = token_delay_s
        # hang=True reproduces the live bug: stream a token or two, then never
        # signal completion (the AO dropped GENERATION_COMPLETE under memory
        # pressure), so _m_prompt waits forever and no terminal frame reaches
        # the UI — the dead-input freeze. The fail-safe must defeat this.
        self.hang = hang
        self.approved = approved
        # tool_call_tokens: buffered tool-call tokens returned by
        # flush_tool_call_buffer on approval. Lets tests verify that the denied
        # path discards them (flush is called with pgov_approved=False).
        self._tool_call_tokens: list[_Tok] = tool_call_tokens or []
        self.load_calls: list[tuple[str, str]] = []
        # The thread load_document actually ran on — the harness asserts this is
        # NOT the event-loop thread, the direct (jitter-free) proof of the
        # off-loop fix.
        self.load_thread_id: int | None = None
        # Thread store_attachment's blocking copy ran on — same off-loop
        # property as load_document.
        self.store_thread_id: int | None = None
        # Records (pgov_approved,) for each flush_tool_call_buffer call.
        self.flush_calls: list[bool] = []
        # Every prompt the dispatcher forwarded to send_prompt, in order. Lets a
        # Layer-C test assert what the WinUI actually SENT to the backend — e.g.
        # that "/external …" reached it as a prompt (the EA-6a fall-through fix)
        # rather than being swallowed host-side as an unknown command.
        self.prompts: list[str] = []
        self._req = 0

    # ── document / attachment ─────────────────────────────────────────
    def load_document(self, session_id: str, filename: str) -> dict[str, Any]:
        self.load_calls.append((session_id, filename))
        self.load_thread_id = threading.get_ident()
        time.sleep(self.block_s)  # blocking — MUST be dispatched off the loop
        return {
            "filename": filename,
            "content": "",
            "media_type": "image",
            "pending_vision": True,
            "image_path": f"/userdata/{filename}",
            "message": f"Photo '{filename}' attached — I'll look at it when you ask about it.",
        }

    def store_attachment(self, src_path: str) -> dict[str, Any]:
        """Fake store_attachment: record thread identity and sleep to model blocking copy."""
        self.store_thread_id = threading.get_ident()
        time.sleep(self.block_s)  # blocking file copy — MUST run off the loop
        filename = src_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "attachment.bin"
        return {
            "filename": filename,
            "content": "",
            "media_type": "image",
            "pending_vision": True,
            "image_path": f"/userdata/{filename}",
            "message": f"Photo '{filename}' attached — I'll look at it when you ask about it.",
        }

    def unload_documents(self, session_id: str) -> None:  # pragma: no cover - convenience
        pass

    def list_userdata_files(self) -> list[dict[str, Any]]:  # pragma: no cover - convenience
        return []

    def trust_documents_for_tools(self, session_id: str) -> None:  # pragma: no cover
        pass

    # ── chat (streaming) ──────────────────────────────────────────────
    async def send_prompt(self, session_id: str, prompt: str) -> str:
        self._req += 1
        self.prompts.append(prompt)
        return f"req-{self._req}"

    async def stream_tokens(self, session_id: str) -> AsyncIterator[_Tok]:
        for word in self.reply.split():
            if self.token_delay_s:
                await asyncio.sleep(self.token_delay_s)
            yield _Tok(word + " ")
        if self.hang:
            # Never complete — simulate a dropped GENERATION_COMPLETE so the
            # caller (dispatcher _m_prompt) waits forever. A correct fail-safe
            # still emits a terminal frame; without one, the UI input stays dead.
            await asyncio.Event().wait()

    def get_pgov_result(self, request_id: str) -> _PGOV:
        sanitized = self.reply if self.approved else ""
        reason = () if self.approved else ("DENIAL_TEST",)
        return _PGOV(approved=self.approved, sanitized_text=sanitized, reason_codes=reason)

    def flush_tool_call_buffer(self, pgov_approved: bool) -> list[_Tok]:
        self.flush_calls.append(pgov_approved)
        if pgov_approved:
            return list(self._tool_call_tokens)
        # Fail-Closed: discard buffered tokens on denial — return nothing.
        return []


class FakeVoiceEngine:
    """Minimal VoiceEngine stand-in for off-loop transcribe/synthesize tests.

    Records the thread each blocking call ran on so tests can assert they
    ran OFF the event-loop thread (``asyncio.to_thread`` dispatch).

    ``transcribe`` and ``synthesize_stream`` are the two blocking paths the
    dispatcher hands to ``asyncio.to_thread``. Both record ``threading.get_ident()``
    at call time; tests compare against the loop-thread id (captured in the
    async test body via ``threading.get_ident()``).
    """

    def __init__(
        self,
        transcription: str = "hello world",
        block_s: float = 0.01,
        synth_chunks: int = 1,
    ) -> None:
        self.transcription = transcription
        self.block_s = block_s
        self.synth_chunks = synth_chunks
        # Thread IDs recorded when the blocking calls actually execute.
        self.transcribe_thread_id: int | None = None
        self.synthesize_thread_id: int | None = None

        # Properties the dispatcher checks before calling voice methods.
        self.stt_available: bool = True
        self.tts_available: bool = True

    def status(self) -> dict[str, Any]:
        return {"stt": self.stt_available, "tts": self.tts_available, "voices": ["default"]}

    def transcribe(self, samples: Any) -> str:
        """Blocking STT stub — records thread identity."""
        self.transcribe_thread_id = threading.get_ident()
        time.sleep(self.block_s)
        return self.transcription

    def synthesize_stream(
        self,
        text: str,
        voice: Any = None,
        speed: Any = None,
    ) -> Generator[tuple[Any, int], None, None]:
        """Blocking TTS stub — records thread identity and yields fake chunks.

        The dispatcher's ``_m_synthesize`` loop calls
        ``asyncio.to_thread(_next_or_none, gen)`` to pull each chunk off the loop.
        We record the thread on the FIRST chunk pull (that is the call the
        dispatcher dispatches via to_thread — the generator is advanced there,
        not here). The dummy numpy-array-like object is a list; sample_rate is
        fixed at 16000.
        """
        self.synthesize_thread_id = threading.get_ident()
        time.sleep(self.block_s)
        for _ in range(self.synth_chunks):
            yield ([0] * 160, 16000)
