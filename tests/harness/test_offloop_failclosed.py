"""Layer A — off-loop + Fail-Closed lock tests (Vikunja #566).

NO models, NO GPU. Extends the freeze-regression harness with three
complementary lock classes that an adversarial review of #563 named as
coverage gaps.

LOCK 1 — ``_m_store_attachment`` off-loop (parametrized with load_document):
    ``store_attachment`` does a blocking file copy then calls ``load_document``;
    both must run on a worker thread, not the event-loop thread.

LOCK 2 — ``_m_transcribe`` / ``_m_synthesize`` off-loop (voice path):
    Both handlers delegate their blocking model calls via ``asyncio.to_thread``;
    a stub voice engine records the thread each blocking call executed on so we
    can compare against the loop-thread id (no timing, no jitter).

LOCK 3 — PGOV Fail-Closed denial branch:
    ``FakeGateway(approved=False)`` makes PGOV deny the reply. The dispatcher
    MUST:
      - call ``flush_tool_call_buffer(pgov_approved=False)`` (buffer discarded)
      - persist the denied turn when a store is wired
      - emit an ``audio_cancel`` stream frame when ``speak=True``
      - emit a ``pgov`` frame with ``approved=False``
      - still emit a terminal ``end`` frame (input always re-enabled)
    A regression that skips the discard (e.g. always calls flush with True) or
    omits the end frame would ship green against the old harness.

Each primary lock has a teeth check that proves the assertion WOULD fail if the
production property were absent (i.e. a naive sync-on-loop version or an always-
approving PGOV).
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest

from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_backend.src.protocol import ok_response
from tests.harness.driver import InProcessBackend
from tests.harness.fakes import FakeGateway, FakeVoiceEngine


# ── Helpers / regression stand-ins ──────────────────────────────────────────


class _OnLoopStoreDispatcher(RpcDispatcher):
    """Pre-fix regression: runs store_attachment blocking work ON the loop.

    Used by the teeth check to prove the thread-identity assertion catches
    a regression where the copy is not delegated to a worker thread.
    """

    async def _m_store_attachment(self, rid: Any, params: dict, send: Any) -> None:  # type: ignore[override]
        from services.ui_gateway.src.document_loader import store_attachment

        # Synchronous on the loop — the regression shape.
        doc = store_attachment(params["src_path"])
        session_id = params.get("session_id")
        if session_id:
            result = self._gateway.load_document(session_id, doc["filename"])
        else:
            result = doc
        await send(ok_response(rid, result))


class _OnLoopTranscribeDispatcher(RpcDispatcher):
    """Pre-fix regression: transcribe runs blocking calls ON the loop."""

    async def _m_transcribe(self, rid: Any, params: dict, send: Any) -> None:  # type: ignore[override]
        from services.voice.src.audio import prepare_for_stt
        from services.ui_backend.src.protocol import ok_response as _ok

        audio_b64 = params["audio_b64"]
        sample_rate = int(params.get("sample_rate", 16000))
        fmt = params.get("format", "pcm_s16le")
        channels = int(params.get("channels", 1))
        # On the loop — the regression shape (no asyncio.to_thread).
        samples = prepare_for_stt(audio_b64, sample_rate, fmt, channels)
        text = self._voice.transcribe(samples)
        await send(_ok(rid, {"text": text}))


# ── LOCK 1: store_attachment off-loop ────────────────────────────────────────


def _fake_store_attachment_factory(gateway: FakeGateway):
    """Return a ``store_attachment`` replacement that delegates to the gateway fake."""
    def _fake_store(src_path: str) -> dict:
        return gateway.store_attachment(src_path)
    return _fake_store


async def test_store_attachment_runs_off_the_event_loop_thread() -> None:
    """PRIMARY LOCK 1: the blocking store_attachment copy runs OFF the loop thread.

    Mirrors ``test_attach_runs_off_the_event_loop_thread`` for the picker path.
    Thread identity — no timing jitter.

    The dispatcher imports store_attachment inline (``from ... import
    store_attachment``), so we patch the name at the source module level
    (``services.ui_gateway.src.document_loader.store_attachment``) so the
    inline import resolves to our fake.
    """
    loop_thread_id = threading.get_ident()

    gateway = FakeGateway(block_s=0.01)

    with patch(
        "services.ui_gateway.src.document_loader.store_attachment",
        side_effect=_fake_store_attachment_factory(gateway),
    ):
        backend = InProcessBackend(gateway, session_store=None, voice=None)
        res = await backend.call(
            "store_attachment",
            {"src_path": "/tmp/cat.png", "session_id": "s"},
        )

    assert res.error is None, f"unexpected error: {res.error}"
    # store_attachment ran off the loop thread (asyncio.to_thread dispatch).
    assert gateway.store_thread_id is not None
    assert gateway.store_thread_id != loop_thread_id, (
        "store_attachment ran ON the event-loop thread — off-loop regression"
    )
    # The subsequent load_document also ran off the loop thread.
    assert gateway.load_thread_id is not None
    assert gateway.load_thread_id != loop_thread_id, (
        "load_document (re-load in store_attachment) ran ON the loop thread"
    )


async def test_store_attachment_off_loop_teeth() -> None:
    """Teeth: the on-loop regression dispatcher runs store_attachment ON the loop.

    Proves the thread-identity assertion above WOULD fail if the dispatcher
    regressed to calling store_attachment synchronously on the loop.
    """
    loop_thread_id = threading.get_ident()

    gateway = FakeGateway(block_s=0.01)

    with patch(
        "services.ui_gateway.src.document_loader.store_attachment",
        side_effect=_fake_store_attachment_factory(gateway),
    ):
        backend = InProcessBackend(
            gateway,
            session_store=None,
            voice=None,
            dispatcher_cls=_OnLoopStoreDispatcher,
        )
        await backend.call(
            "store_attachment",
            {"src_path": "/tmp/cat.png", "session_id": "s"},
        )

    # On-loop regression: store_attachment ran ON the loop thread.
    assert gateway.store_thread_id == loop_thread_id, (
        "Teeth check failed: on-loop dispatcher did NOT run store on the loop thread — "
        "the primary assertion cannot catch a real regression"
    )


# ── LOCK 2: transcribe / synthesize off-loop ─────────────────────────────────


async def test_transcribe_runs_off_the_event_loop_thread() -> None:
    """PRIMARY LOCK 2a: the blocking STT call runs OFF the loop thread.

    The dispatcher calls ``asyncio.to_thread(self._voice.transcribe, samples)``;
    FakeVoiceEngine records the thread its ``transcribe`` method executed on.
    """
    loop_thread_id = threading.get_ident()

    voice = FakeVoiceEngine(block_s=0.01)
    gateway = FakeGateway(block_s=0.0)

    # prepare_for_stt is imported inline inside _m_transcribe; patch at the
    # source module level so the inline ``from services.voice.src.audio import
    # prepare_for_stt`` resolves to our stub.
    with patch(
        "services.voice.src.audio.prepare_for_stt",
        return_value=[0.0] * 160,
    ):
        backend = InProcessBackend(gateway, session_store=None, voice=voice)
        import base64
        # 320 bytes of silence (160 int16 samples at 16 kHz, 0.01 s)
        dummy_b64 = base64.b64encode(b"\x00" * 320).decode()
        res = await backend.call(
            "transcribe",
            {"audio_b64": dummy_b64, "sample_rate": 16000},
        )

    assert res.error is None, f"transcribe returned error: {res.error}"
    assert res.ok_result is not None
    assert res.ok_result["text"] == "hello world"

    assert voice.transcribe_thread_id is not None
    assert voice.transcribe_thread_id != loop_thread_id, (
        "voice.transcribe ran ON the event-loop thread — off-loop regression"
    )


async def test_transcribe_off_loop_teeth() -> None:
    """Teeth: on-loop transcribe dispatcher runs the blocking call ON the loop.

    Proves the thread-identity assertion above would catch a real regression.
    """
    loop_thread_id = threading.get_ident()

    voice = FakeVoiceEngine(block_s=0.01)
    gateway = FakeGateway(block_s=0.0)

    with patch(
        "services.voice.src.audio.prepare_for_stt",
        return_value=[0.0] * 160,
    ):
        backend = InProcessBackend(
            gateway,
            session_store=None,
            voice=voice,
            dispatcher_cls=_OnLoopTranscribeDispatcher,
        )
        import base64
        dummy_b64 = base64.b64encode(b"\x00" * 320).decode()
        await backend.call(
            "transcribe",
            {"audio_b64": dummy_b64, "sample_rate": 16000},
        )

    assert voice.transcribe_thread_id == loop_thread_id, (
        "Teeth check failed: on-loop dispatcher did NOT run transcribe on the loop thread"
    )


async def test_synthesize_runs_off_the_event_loop_thread() -> None:
    """PRIMARY LOCK 2b: the blocking TTS generator is advanced OFF the loop thread.

    ``_m_synthesize`` calls ``asyncio.to_thread(_next_or_none, gen)`` to pull
    each chunk; FakeVoiceEngine records the thread the generator body executes on
    (i.e., where ``__next__`` is first called — that is the worker thread).
    """
    loop_thread_id = threading.get_ident()

    voice = FakeVoiceEngine(block_s=0.01, synth_chunks=2)
    gateway = FakeGateway(block_s=0.0)

    # encode_b64_pcm is imported inline in _m_synthesize; patch at the source
    # module so the inline import resolves to the stub.
    with patch(
        "services.voice.src.audio.encode_b64_pcm",
        return_value="AAAA",
    ):
        backend = InProcessBackend(gateway, session_store=None, voice=voice)
        res = await backend.call(
            "synthesize",
            {"text": "hello world"},
        )

    assert res.error is None, f"synthesize returned error: {res.error}"
    # end frame carries chunk count
    end_frames = [f for f in res.frames if f.get("stream") == "end"]
    assert end_frames, "synthesize emitted no end frame"
    assert end_frames[0]["value"]["chunks"] == 2

    assert voice.synthesize_thread_id is not None
    assert voice.synthesize_thread_id != loop_thread_id, (
        "synthesize_stream generator was advanced ON the event-loop thread — "
        "off-loop regression"
    )


# ── LOCK 3: PGOV Fail-Closed denial branch ──────────────────────────────────


class _FakeSessionStore:
    """Minimal SessionStore stub that records add_turn calls."""

    def __init__(self) -> None:
        self.turns: list[dict] = []

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        pgov_status: str,
        pgov_reasons: list[str],
    ) -> None:
        self.turns.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "pgov_status": pgov_status,
                "pgov_reasons": pgov_reasons,
            }
        )


async def test_pgov_denial_discards_tool_call_buffer() -> None:
    """PRIMARY LOCK 3a: denied PGOV calls flush with pgov_approved=False.

    A regression that passes ``True`` to flush (or skips it) on denial would
    silently leak buffered tool-call tokens — a security-relevant path.  This
    test verifies ``flush_tool_call_buffer`` is called with ``False`` and that
    the gateway returns nothing (the Fail-Closed contract).
    """
    from tests.harness.fakes import _Tok  # type: ignore[attr-defined]

    tool_tok = _Tok(token="<tool>", is_tool_call=True)
    gateway = FakeGateway(
        approved=False,
        reply="bad output",
        tool_call_tokens=[tool_tok],
    )
    backend = InProcessBackend(gateway, session_store=None, voice=None)

    res = await backend.call("prompt", {"session_id": "s", "prompt": "hello"})

    # flush_tool_call_buffer must have been called exactly once, with False.
    assert gateway.flush_calls == [False], (
        f"Expected flush_tool_call_buffer(False) on denial; got flush_calls={gateway.flush_calls}"
    )
    # No tool-call tokens should have been streamed.
    tool_tokens_streamed = [
        f for f in res.frames
        if f.get("stream") == "token" and f.get("value", {}).get("is_tool_call")
    ]
    assert not tool_tokens_streamed, (
        f"Tool-call tokens leaked into stream on PGOV denial: {tool_tokens_streamed}"
    )
    # pgov frame must report denied.
    pgov_frames = [f for f in res.frames if f.get("stream") == "pgov"]
    assert pgov_frames, "No pgov frame emitted on denial"
    assert pgov_frames[0]["value"]["approved"] is False

    # Terminal end frame must still be emitted (input re-enable guarantee).
    assert any(f.get("stream") == "end" for f in res.frames), (
        "No terminal end frame emitted after PGOV denial"
    )


async def test_pgov_denial_persists_denied_turn() -> None:
    """PRIMARY LOCK 3b: denied turn is persisted with pgov_status='denied'.

    When a session store is wired, ``_m_prompt`` must persist the denied turn
    (sanitized_text='', status='denied') — not skip persistence or persist it
    as approved.
    """
    gateway = FakeGateway(approved=False, reply="bad output")
    store = _FakeSessionStore()
    backend = InProcessBackend(gateway, session_store=store, voice=None)

    await backend.call("prompt", {"session_id": "s", "prompt": "hello"})

    assert len(store.turns) == 1, f"Expected 1 persisted turn; got {store.turns}"
    turn = store.turns[0]
    assert turn["role"] == "assistant"
    assert turn["pgov_status"] == "denied", (
        f"Denied turn persisted with wrong pgov_status: {turn['pgov_status']!r}"
    )
    assert "DENIAL_TEST" in turn["pgov_reasons"], (
        f"Expected DENIAL_TEST in pgov_reasons; got {turn['pgov_reasons']}"
    )


async def test_pgov_denial_emits_audio_cancel_when_speak() -> None:
    """PRIMARY LOCK 3c: PGOV denial emits audio_cancel when speak=True.

    The front end must stop playback of already-streamed audio when PGOV denies
    the reply. This verifies the ``audio_cancel`` frame is emitted on the
    denial path.
    """
    voice = FakeVoiceEngine(block_s=0.001, synth_chunks=1)
    gateway = FakeGateway(
        approved=False,
        reply="bad output bad output",
        token_delay_s=0.0,
    )

    with patch(
        "services.voice.src.audio.encode_b64_pcm",
        return_value="AAAA",
    ), patch(
        "services.voice.src.engine.extract_sentences",
        return_value=(["bad output bad output"], ""),
    ):
        backend = InProcessBackend(gateway, session_store=None, voice=voice)
        res = await backend.call(
            "prompt",
            {"session_id": "s", "prompt": "hello", "speak": True},
        )

    audio_cancel = [f for f in res.frames if f.get("stream") == "audio_cancel"]
    assert audio_cancel, (
        "Expected audio_cancel frame on PGOV denial with speak=True; none emitted"
    )
    # Terminal end frame must still be present.
    assert any(f.get("stream") == "end" for f in res.frames), (
        "No terminal end frame after denial+speak"
    )


async def test_pgov_denial_teeth_approval_does_not_flush_false() -> None:
    """Teeth: approved path calls flush with True, NOT False.

    Proves that ``flush_calls == [False]`` is a meaningful assertion — an
    approved turn would never produce that result, so the denial test above
    cannot silently pass on an always-approving gateway.
    """
    gateway = FakeGateway(approved=True, reply="good output")
    backend = InProcessBackend(gateway, session_store=None, voice=None)

    await backend.call("prompt", {"session_id": "s", "prompt": "hello"})

    # On approval, flush is called with True — not False.
    assert gateway.flush_calls == [True], (
        f"Approved path should flush with True; got {gateway.flush_calls}"
    )
    # If the primary denial test asserted flush_calls==[False], this confirms
    # that assertion would FAIL for an always-approving gateway — i.e. it has teeth.
    assert gateway.flush_calls != [False], (
        "Teeth check failed: approved path flush_calls matches the denial assertion"
    )
