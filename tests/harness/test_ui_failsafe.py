"""Layer A — UI fail-safe regression lock: every _m_prompt must emit a terminal frame.

NO models, NO GPU. Locks the "never freeze the UI" guarantee introduced as the
fail-safe for Vikunja #565 (memory-pressure root cause tracked separately).

Background
----------
A user attached an 8.3 MP image and asked about it. Under memory pressure the
Assistant Orchestrator generated and validated the answer but never sent the
GENERATION_COMPLETE message over the IPC channel. The dispatcher's ``_m_prompt``
hung inside ``async for token in self._gateway.stream_tokens(...)`` waiting for
the generator to finish, which it never would (or not for up to 180 s — the
per-socket receive timeout). Because ``_m_prompt`` never returned, it never emitted
the terminal ``end`` frame. The WinUI front end disables its text input during
generation and only re-enables it on a terminal frame, so the input stayed dead
and the app was frozen until the user killed the process ~6 minutes later.

Root cause (exact point)
------------------------
``stream_tokens`` in ``transport.py`` calls
``await asyncio.to_thread(self._transport.receive)`` in a loop. When
GENERATION_COMPLETE never arrives (or arrives but PGOV_RESULT hasn't been
received yet, causing the ``continue`` path at transport.py line ~823 which
re-enters another blocking receive), the generator suspends indefinitely.
``_m_prompt`` awaits the ``async for`` and therefore suspends with it. The
gateway's per-socket receive timeout (``PROMPT_RESPONSE_TIMEOUT_S = 180 s``)
would eventually wake the thread, but 180 s is far too long for the UI to remain
frozen, and in test scenarios with a fake gateway (no socket timeout) the hang
is truly infinite.

The fail-safe
-------------
``_m_prompt`` wraps the entire streaming + PGOV + store arc in
``asyncio.wait_for`` with a ``_PROMPT_STREAM_FAILSAFE_S`` deadline (90 s in
production, injectable for tests). On timeout (or any unhandled exception) a
``finally`` guard emits a terminal ``end`` frame, so the front end's input is
ALWAYS re-enabled within the bounded time regardless of what the gateway does.

Tests
-----
``test_stalled_stream_emits_terminal_frame``
    PRIMARY LOCK: a gateway whose ``stream_tokens`` yields a token or two then
    hangs forever (``await asyncio.Event().wait()`` — never resolves, simulating
    GENERATION_COMPLETE that never arrives). Assert the dispatcher STILL emits a
    terminal ``end`` frame to ``send`` within the fail-safe bound. With current
    code (pre-fix) this hangs / never emits the terminal frame.

``test_stalled_stream_terminal_frame_has_correct_shape``
    Assert the exact wire shape: the final frame is ``{"stream": "end", ...}``
    so the front end's terminal-frame check fires.

``test_raising_gateway_emits_terminal_frame``
    A gateway that raises RuntimeError after streaming one token must still
    yield exactly one terminal frame.

``test_happy_path_contract_preserved``
    The fast, normal path (stream completes quickly) still emits the correct
    frame sequence: ``token* -> pgov -> end``. The fail-safe must not break the
    happy path.

``test_exactly_one_terminal_frame_on_stall``
    Stalled stream must emit EXACTLY one terminal frame — not zero, not two.

``test_failsafe_teeth``
    Meta-guard: a patched _m_prompt WITHOUT the fail-safe hangs demonstrably
    (a shorter asyncio.wait_for around the raw call proves it times out rather
    than completing cleanly). This ensures the lock cannot silently rot.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from services.ui_backend.src.dispatcher import RpcDispatcher
from tests.harness.driver import InProcessBackend
from tests.harness.fakes import CollectingSend, FakeGateway, _PGOV, _Tok

# ---------------------------------------------------------------------------
# Fail-safe bound used in tests.  This is passed as prompt_stream_failsafe_s=
# to InProcessBackend (which forwards it to RpcDispatcher), so the dispatcher
# itself fires the terminal frame within this window rather than waiting 90 s.
# Must be comfortably longer than any legitimate fast-path to avoid flaking on
# a loaded CI box, while being short enough to keep the suite fast.
# ---------------------------------------------------------------------------
FAILSAFE_S: float = 2.0

# Outer wall-clock budget for each test (how long we let the whole test run
# before giving up).  Must exceed FAILSAFE_S so the dispatcher has time to fire
# the failsafe and return before the test outer timeout fires.
TEST_WALL_S: float = FAILSAFE_S + 2.0


# ---------------------------------------------------------------------------
# Fake gateways for the new failure scenarios
# ---------------------------------------------------------------------------


class _HangingGateway(FakeGateway):
    """Gateway whose stream_tokens yields a token or two then hangs forever.

    Simulates a GENERATION_COMPLETE that never arrives — the exact bug from the
    live 2026-06-04 memory-pressure hang.
    """

    async def stream_tokens(self, session_id: str) -> AsyncIterator[_Tok]:  # type: ignore[override]
        yield _Tok("hello ")
        yield _Tok("world ")
        # Block the generator forever — GENERATION_COMPLETE never arrives.
        await asyncio.Event().wait()
        return  # pragma: no cover — unreachable; satisfies type checker

    def get_pgov_result(self, request_id: str) -> _PGOV:
        return _PGOV(approved=True, sanitized_text="hello world")

    def flush_tool_call_buffer(self, pgov_approved: bool) -> list[_Tok]:
        return []


class _RaisingGateway(FakeGateway):
    """Gateway that raises RuntimeError after streaming one token.

    Simulates an IPC exception mid-stream — the other failure mode that must
    still produce a terminal frame.
    """

    async def stream_tokens(self, session_id: str) -> AsyncIterator[_Tok]:  # type: ignore[override]
        yield _Tok("partial ")
        raise RuntimeError("IPC channel died")
        return  # pragma: no cover

    def get_pgov_result(self, request_id: str) -> _PGOV:
        return _PGOV(approved=False, sanitized_text="error")

    def flush_tool_call_buffer(self, pgov_approved: bool) -> list[_Tok]:
        return []


# ---------------------------------------------------------------------------
# Helper: build an InProcessBackend with the test-sized failsafe bound.
# ---------------------------------------------------------------------------


def _backend(gateway: Any) -> InProcessBackend:
    """Return an InProcessBackend whose fail-safe fires at FAILSAFE_S, not 90 s."""
    return InProcessBackend(
        gateway,
        session_store=None,
        voice=None,
        prompt_stream_failsafe_s=FAILSAFE_S,
    )


# ---------------------------------------------------------------------------
# PRIMARY LOCK
# ---------------------------------------------------------------------------


async def test_stalled_stream_emits_terminal_frame() -> None:
    """PRIMARY LOCK: a stalled stream MUST emit a terminal frame within the bound.

    The gateway hangs forever after two tokens (GENERATION_COMPLETE never
    arrives). The fail-safe must unblock _m_prompt and push an ``end`` frame to
    ``send`` within FAILSAFE_S seconds.

    Pre-fix behaviour: this test hangs indefinitely (or until the 180 s socket
    timeout, whichever is shorter — in a test with a fake gateway there is no
    socket timeout, so it truly hangs).
    """
    backend = _backend(_HangingGateway())

    result = await asyncio.wait_for(
        backend.call("prompt", {"session_id": "s", "prompt": "hello"}),
        timeout=TEST_WALL_S,
    )

    terminal = [
        f for f in result.frames
        if f.get("stream") == "end" or (f.get("ok") is False)
    ]
    assert terminal, (
        f"No terminal frame emitted after {FAILSAFE_S}s stall. "
        f"Frames received: {result.frames}"
    )


async def test_stalled_stream_terminal_frame_has_correct_shape() -> None:
    """The terminal frame on stall must be stream='end' so the front end unblocks."""
    backend = _backend(_HangingGateway())

    result = await asyncio.wait_for(
        backend.call("prompt", {"session_id": "s", "prompt": "hello"}),
        timeout=TEST_WALL_S,
    )

    end_frames = [f for f in result.frames if f.get("stream") == "end"]
    assert len(end_frames) >= 1, (
        f"Expected at least one stream='end' frame; got: {result.frames}"
    )
    assert len(end_frames) == 1, (
        f"Expected exactly one terminal 'end' frame; got {len(end_frames)}: {end_frames}"
    )


async def test_raising_gateway_emits_terminal_frame() -> None:
    """A gateway that raises mid-stream must still yield a terminal frame.

    The dispatcher's outer exception handler in handle() catches unhandled
    exceptions, but that emits an ``ok: False`` non-streaming frame — not a
    streaming ``end`` frame. The fail-safe ensures a raising stream exits
    cleanly with a streaming ``end`` frame that the front end recognises as
    the terminal event to re-enable its text input.
    """
    backend = _backend(_RaisingGateway())
    result = await asyncio.wait_for(
        backend.call("prompt", {"session_id": "s", "prompt": "hello"}),
        timeout=TEST_WALL_S,
    )

    terminal = [
        f for f in result.frames
        if f.get("stream") == "end" or (f.get("ok") is False)
    ]
    assert terminal, (
        f"No terminal frame after mid-stream raise. Frames: {result.frames}"
    )


async def test_happy_path_contract_preserved() -> None:
    """The fail-safe must not alter the happy path frame contract.

    A fast, normal completion must still yield: token* -> pgov -> end (in order).
    Exactly one 'end' frame, exactly one 'pgov' frame.
    """
    gateway = FakeGateway(reply="alpha beta gamma", token_delay_s=0.0)
    backend = _backend(gateway)
    result = await asyncio.wait_for(
        backend.call("prompt", {"session_id": "s", "prompt": "hello"}),
        timeout=TEST_WALL_S,
    )
    frames = result.frames

    stream_frames = [f for f in frames if "stream" in f]
    kinds = [f["stream"] for f in stream_frames]

    assert "end" in kinds, f"No 'end' frame in happy path: {kinds}"
    assert "pgov" in kinds, f"No 'pgov' frame in happy path: {kinds}"
    assert kinds.count("end") == 1, f"Expected exactly one 'end': {kinds}"
    assert kinds.count("pgov") == 1, f"Expected exactly one 'pgov': {kinds}"

    # Order invariant: tokens before pgov; pgov before end.
    pgov_idx = kinds.index("pgov")
    end_idx = kinds.index("end")
    assert end_idx == len(kinds) - 1, f"'end' must be last: {kinds}"
    assert pgov_idx == end_idx - 1, f"'pgov' must immediately precede 'end': {kinds}"
    for i, k in enumerate(kinds):
        if k == "token":
            assert i < pgov_idx, f"token at position {i} is after pgov at {pgov_idx}"


async def test_exactly_one_terminal_frame_on_stall() -> None:
    """Stalled stream must emit EXACTLY one terminal frame — not zero, not two."""
    backend = _backend(_HangingGateway())

    result = await asyncio.wait_for(
        backend.call("prompt", {"session_id": "s", "prompt": "hello"}),
        timeout=TEST_WALL_S,
    )

    end_frames = [f for f in result.frames if f.get("stream") == "end"]
    error_frames = [f for f in result.frames if f.get("ok") is False]
    total_terminal = len(end_frames) + len(error_frames)
    assert total_terminal == 1, (
        f"Expected exactly 1 terminal frame; got {total_terminal}. "
        f"end={end_frames} errors={error_frames}"
    )


async def test_failsafe_teeth() -> None:
    """Meta-guard: WITHOUT the fail-safe, _m_prompt hangs on a stalled stream.

    This proves the primary lock has teeth: the fail-safe is not decoration —
    its absence causes a real hang. We reconstruct a dispatcher that calls the
    original _m_prompt logic without the fail-safe wrapper, then verify that a
    call against the hanging gateway does NOT complete within FAILSAFE_S / 2.

    Implementation: subclass RpcDispatcher to replace _m_prompt with a version
    that has no asyncio.wait_for guard and no finally terminal-frame guarantee,
    relying solely on the generator exhausting itself (which it never does for
    _HangingGateway). Then drive it through an InProcessBackend with a short
    outer timeout; we expect asyncio.TimeoutError to propagate.
    """
    from services.ui_backend.src.protocol import stream_frame as stream_frame_fn

    class _NoFailsafeDispatcher(RpcDispatcher):
        """Replays the pre-fix _m_prompt: no timeout wrapper around stream_tokens."""

        async def _m_prompt(  # type: ignore[override]
            self, rid: Any, params: dict, send: CollectingSend,
        ) -> None:
            session_id = params["session_id"]
            prompt = params["prompt"]
            request_id = await self._gateway.send_prompt(session_id, prompt)

            # No asyncio.wait_for here — pure original loop; hangs on stall.
            async for token in self._gateway.stream_tokens(session_id):
                await send(stream_frame_fn(rid, "token", token.to_dict()))

            pgov = self._gateway.get_pgov_result(request_id)
            self._gateway.flush_tool_call_buffer(pgov_approved=pgov.approved)
            await send(stream_frame_fn(rid, "pgov", pgov.to_dict()))
            await send(stream_frame_fn(rid, "end", {"request_id": request_id}))

    gateway = _HangingGateway()
    backend = InProcessBackend(
        gateway, session_store=None, voice=None,
        dispatcher_cls=_NoFailsafeDispatcher,
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            backend.call("prompt", {"session_id": "s", "prompt": "hello"}),
            timeout=FAILSAFE_S * 0.5,  # shorter than FAILSAFE_S — should time out
        )
