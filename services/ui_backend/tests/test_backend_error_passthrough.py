"""Backend (AO/PA) error-frame passthrough guard (Vikunja #560 sub-item 4).

Companion to ``test_error_sanitize.py``.  That suite locks the ui_backend
dispatcher's OWN exception path (an exception raised *inside* a dispatch handler
is turned into a generic ``internal error [<cid>]`` with the full detail logged
server-side).  THIS suite locks the adjacent, distinct question raised by #560
sub-item 4: when the *backend* (the Assistant Orchestrator / Policy Agent, over
the vsock leg) returns an error frame whose text may carry raw exception detail,
does any of that text reach the untrusted WinUI client on the chat/prompt path?

DISPOSITION (investigation, 2026-07-16 — evidence in the assertions below):
  NO client-reachable leak exists on the chat/prompt path, and it is closed by
  STRUCTURAL ABSENCE, not by a wrapper.  The Orchestrator emits a chat-turn
  failure as a ``MessageType.ERROR`` frame (entrypoint.py ``encode_error(
  generation.error, ...)``).  ``TransportGateway.stream_tokens`` *drops* that
  frame — it logs the payload SERVER-SIDE (``logger.error``) and breaks the
  receive loop; the payload is never turned into a ``StreamToken`` (transport.py
  ``elif msg_type == MessageType.ERROR``).  With no PGOV_RESULT cached,
  ``get_pgov_result`` then returns the generic Fail-Closed ``PGOV_DENIAL_FALLBACK``
  (no backend text).  The dispatcher's ``_m_prompt`` builds the client frames
  purely from the yielded tokens + that PGOV result — it never reads a backend
  error ``message`` field — so the AO/PA ``message=str(exc)`` frames (PLAN /
  EXECUTE / INGEST / PREFERENCE) and the PA ``error="MALFORMED_CAR: ..."`` never
  cross to the client on this path.

These tests drive the REAL ``TransportGateway`` seam and the REAL
``RpcDispatcher`` — not a re-implementation — with a genuine framed ERROR frame,
so a future refactor that started surfacing the backend error text (as a token,
or by having ``get_pgov_result`` echo it) fails loudly here.

RESIDUALS (out of THIS path — reported to the fleet lead, ticketed separately,
NOT fixed here to keep this a focused chat-path lock):
  * The slash-command *informational* legs (``/ingest`` live; ``/imagine`` /
    ``/dispatch`` / ``/coord`` dormant) render an AO-composed ``message`` verbatim
    as a transcript token.  Most are coded, intentional operator diagnostics; the
    one unbounded branch is the ingest generic-``Exception`` fallback
    (assistant_orchestrator entrypoint ``_send_ingest_result(..., error_code=
    "INGEST_SUBMIT_FAILED", message=str(exc))``), whose ``str(exc)`` reaches the
    client through ``IngestCoordinator._format_ao_error``.  Its full detail is
    already logged server-side; the fix (a generic message, mirroring the
    preference generic-Exception sibling) is a one-line AO change in a distinct
    subsystem and belongs on its own ticket + independent review.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shared.ipc import MessageFramer
from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_gateway.src.transport import (
    PGOV_DENIAL_FALLBACK,
    REASON_VALIDATION_ERROR,
    StartupState,
    TransportGateway,
)

# A canonical leaky backend-error payload: everything sub-item 4 must keep out of
# the client — a filesystem path, a DB filename, an OS error detail, and an
# exception class name.  Mirrors the leak shape asserted in test_error_sanitize.py.
_LEAKY_ERROR: str = (
    r"RuntimeError: sqlite3 error: unable to open database file "
    r"C:\Users\mrbla\BlarAI\userdata\sessions.db: permission denied"
)

_LEAK_MARKERS: tuple[str, ...] = (
    r"C:\Users",
    "sessions.db",
    "sqlite3 error",
    "permission denied",
    "RuntimeError",
)


class _MockTransport:
    """Receive-from-list transport stub (no real socket).

    Mirrors the ``_MockTransport`` idiom in ``ui_gateway/tests/test_transport.py``
    but also answers ``send``/``close`` so it can back a full ``send_prompt`` →
    ``stream_tokens`` round trip driven through the real gateway.
    """

    def __init__(self, messages: list[bytes | None]) -> None:
        self._iter = iter(messages)
        self.connected = True

    def send(self, _msg: bytes) -> bool:
        return True

    def receive(self) -> bytes | None:
        return next(self._iter, None)

    def close(self) -> None:
        return None


def _leaky_error_frame(request_id: str = "req-1") -> bytes:
    """A real, framed ``MessageType.ERROR`` carrying the leaky payload — exactly
    the shape the Orchestrator emits for a failed chat turn."""
    return MessageFramer().encode_error(_LEAKY_ERROR, request_id)


def _assert_no_leak(text: str, where: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, (
            f"Backend error detail {marker!r} leaked to the client via {where}: "
            f"{text!r}"
        )


# ---------------------------------------------------------------------------
# 1. Gateway seam: a backend ERROR frame is dropped, never surfaced
# ---------------------------------------------------------------------------

class TestGatewayDropsBackendErrorFrame:
    """The TransportGateway is the sanitizing seam for backend chat errors."""

    def _operational_gateway(self, frames: list[bytes | None]) -> TransportGateway:
        gw = TransportGateway()  # dev_mode, no session store
        gw._state = StartupState.OPERATIONAL
        gw._active_request_id = "req-1"
        gw._transport = _MockTransport(frames)  # type: ignore[assignment]
        return gw

    def test_error_frame_yields_no_token(self) -> None:
        """TEETH: a regression that surfaced the ERROR payload as a StreamToken
        (instead of dropping it) would yield a token here and fail."""
        gw = self._operational_gateway([_leaky_error_frame(), None])

        async def _collect() -> list[Any]:
            return [t async for t in gw.stream_tokens("sess")]

        tokens = asyncio.run(_collect())
        assert tokens == [], (
            "Backend ERROR frame was surfaced as a token stream — it must be "
            "dropped (logged server-side) and never reach the client"
        )

    def test_pgov_result_is_generic_after_error_frame(self) -> None:
        """With the ERROR frame dropped, no PGOV was cached → get_pgov_result
        returns the generic Fail-Closed denial, carrying no backend text."""
        gw = self._operational_gateway([_leaky_error_frame(), None])

        async def _drain() -> None:
            async for _ in gw.stream_tokens("sess"):
                pass

        asyncio.run(_drain())
        result = gw.get_pgov_result("req-1")

        assert result.approved is False
        assert result.sanitized_text == PGOV_DENIAL_FALLBACK
        assert result.reason_codes == [REASON_VALIDATION_ERROR]
        _assert_no_leak(result.sanitized_text, "get_pgov_result.sanitized_text")

    def test_leaky_payload_really_was_in_the_frame(self) -> None:
        """Sanity anchor for the teeth above: the frame genuinely carried the
        leaky strings, so the 'clean client output' assertions are meaningful
        (they are stripping real detail, not asserting against an empty payload).

        Checked against the DECODED payload — the on-the-wire JSON escapes the
        backslashes in the path, so the raw bytes are not the right surface."""
        _msg_type, _req_id, payload = MessageFramer().decode(_leaky_error_frame())
        error_text = payload["error"]
        for marker in _LEAK_MARKERS:
            assert marker in error_text, (
                f"test setup error: {marker!r} not present in the decoded ERROR "
                f"payload"
            )


# ---------------------------------------------------------------------------
# 2. Full boundary: the real dispatcher emits clean client frames on a backend
#    error, driven through the real gateway (AO ERROR frame → gateway → client)
# ---------------------------------------------------------------------------

class TestDispatcherPromptCleanOnBackendError:
    """Drive RpcDispatcher._m_prompt end to end against a real gateway whose
    next backend reply is a leaky ERROR frame; assert every client-visible frame
    is clean AND the failure signal is still delivered."""

    def _frames_for_prompt(self, prompt: str) -> list[dict[str, Any]]:
        gw = TransportGateway()  # dev_mode, no session store
        gw._state = StartupState.OPERATIONAL

        transport = _MockTransport([_leaky_error_frame("req-1"), None])

        async def _fake_open(timeout_s: float | None = None) -> _MockTransport:
            return transport

        # send_prompt opens this transport, sends the PROMPT_REQUEST, and stores
        # it; stream_tokens then reads the leaky ERROR frame from it.
        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]

        dispatcher = RpcDispatcher(gw, session_store=None)
        frames: list[dict[str, Any]] = []

        async def _send(frame: dict[str, Any]) -> None:
            frames.append(frame)

        asyncio.run(
            dispatcher.handle(
                {"id": 7, "method": "prompt",
                 "params": {"session_id": "sess-e2e", "prompt": prompt}},
                _send,
            )
        )
        return frames

    def test_no_client_frame_carries_backend_error_text(self) -> None:
        frames = self._frames_for_prompt("Tell me about this week's schedule")

        # Nothing the client receives — token text, pgov text, or any value —
        # may carry backend error detail.
        for frame in frames:
            value = frame.get("value", {})
            if frame.get("stream") == "token":
                _assert_no_leak(str(value.get("token", "")), "prompt token frame")
            if frame.get("stream") == "pgov":
                _assert_no_leak(
                    str(value.get("sanitized_text", "")), "prompt pgov frame"
                )
            # Catch-all: no leaky marker anywhere in any emitted frame.
            _assert_no_leak(str(frame), "emitted client frame")

    def test_failure_signal_still_delivered(self) -> None:
        """A dropped backend error must not become a silent hang: the client
        still gets a terminal frame (input re-enabled) and a Fail-Closed PGOV
        denial (the turn is not falsely shown as approved)."""
        frames = self._frames_for_prompt("Tell me about this week's schedule")

        streams = [f.get("stream") for f in frames]
        assert "end" in streams, (
            "No terminal 'end' frame — the WinUI input would never re-enable"
        )

        pgov_frames = [f for f in frames if f.get("stream") == "pgov"]
        if pgov_frames:
            # When a pgov frame is emitted it must be the Fail-Closed denial,
            # never an 'approved' verdict fabricated from a broken stream.
            pgov = pgov_frames[-1]["value"]
            assert pgov["approved"] is False
            assert pgov["sanitized_text"] == PGOV_DENIAL_FALLBACK
