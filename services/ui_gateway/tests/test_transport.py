"""
Tests for services.ui_gateway.src.transport (P1.11).

Covers:
  - StartupState enum values
  - StreamToken serialization round-trip
  - GatewayPGOVResult serialization round-trip
  - Reason code constants
  - TransportGateway state machine transitions
  - check_pa_status retry + fail-closed
  - send_prompt validation
  - stream_tokens operational guard
  - get_pgov_result default deny
  - Tool-call buffer + flush
  - reset()
"""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from services.ui_gateway.src.transport import (
    ALL_REASON_CODES,
    PGOV_DENIAL_FALLBACK,
    REASON_DELIMITER_ECHO,
    REASON_LEAKAGE_DETECTED,
    REASON_PII_DETECTED,
    REASON_TOKEN_BUDGET_EXCEEDED,
    REASON_TOOL_CALL_VIOLATION,
    REASON_VALIDATION_ERROR,
    GatewayPGOVResult,
    StartupState,
    StreamToken,
    TransportGateway,
)
from services.ui_gateway.src.constants import (
    TOOL_CALL_BUFFER_MAX_TOKENS,
)
from shared.ipc import MessageFramer, MessageType, VsockTransport


# ─────────────────────────────────────────────────────────────────
# Helpers — mock TCP servers that speak the MessageFramer protocol
# ─────────────────────────────────────────────────────────────────

_HEADER_FMT = "!I"
_HEADER_SZ = struct.calcsize(_HEADER_FMT)
_framer = MessageFramer()


async def _read_framed(reader: asyncio.StreamReader) -> bytes:
    """Read one length-prefixed message from an asyncio StreamReader."""
    hdr = await reader.readexactly(_HEADER_SZ)
    (length,) = struct.unpack(_HEADER_FMT, hdr)
    return await reader.readexactly(length)


async def _write_framed(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write one length-prefixed message to an asyncio StreamWriter."""
    writer.write(struct.pack(_HEADER_FMT, len(data)) + data)
    await writer.drain()


# ─────────────────────────────────────────────────────────────────
# StartupState
# ─────────────────────────────────────────────────────────────────


class TestStartupState:
    """Verify the StartupState enum members and string representation."""

    def test_enum_members(self) -> None:
        assert set(StartupState) == {
            StartupState.INITIALIZING,
            StartupState.HANDSHAKING,
            StartupState.OPERATIONAL,
            StartupState.FAILED,
        }

    def test_string_values(self) -> None:
        assert StartupState.INITIALIZING.value == "INITIALIZING"
        assert StartupState.HANDSHAKING.value == "HANDSHAKING"
        assert StartupState.OPERATIONAL.value == "OPERATIONAL"
        assert StartupState.FAILED.value == "FAILED"

    def test_str_identity(self) -> None:
        """StartupState inherits from str — string equality should hold."""
        assert StartupState.OPERATIONAL == "OPERATIONAL"


# ─────────────────────────────────────────────────────────────────
# StreamToken
# ─────────────────────────────────────────────────────────────────


class TestStreamToken:
    """StreamToken dataclass serialization and construction."""

    def _make_token(self, **overrides: object) -> StreamToken:
        defaults: dict = {
            "token": "hello",
            "token_index": 0,
            "is_final": False,
            "is_tool_call": False,
            "session_id": "sess-1",
            "is_thinking": False,
        }
        defaults.update(overrides)
        return StreamToken(**defaults)

    def test_construction(self) -> None:
        t = self._make_token()
        assert t.token == "hello"
        assert t.token_index == 0
        assert t.is_final is False
        assert t.is_tool_call is False
        assert t.session_id == "sess-1"
        assert t.is_thinking is False

    def test_frozen(self) -> None:
        t = self._make_token()
        with pytest.raises(AttributeError):
            t.token = "modified"  # type: ignore[misc]

    def test_to_dict(self) -> None:
        t = self._make_token(token_index=5, is_final=True)
        d = t.to_dict()
        assert d == {
            "token": "hello",
            "token_index": 5,
            "is_final": True,
            "is_tool_call": False,
            "session_id": "sess-1",
            "is_thinking": False,
        }

    def test_round_trip(self) -> None:
        original = self._make_token(token="world", token_index=3, is_tool_call=True)
        restored = StreamToken.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_defaults(self) -> None:
        """Missing keys should fall back to safe defaults."""
        t = StreamToken.from_dict({})
        assert t.token == ""
        assert t.token_index == 0
        assert t.is_final is False
        assert t.is_tool_call is False
        assert t.session_id == ""
        assert t.is_thinking is False

    def test_is_thinking_true_round_trip(self) -> None:
        """is_thinking=True survives to_dict / from_dict round-trip."""
        t = self._make_token(is_thinking=True)
        restored = StreamToken.from_dict(t.to_dict())
        assert restored.is_thinking is True
        assert restored == t

    def test_is_thinking_default_false(self) -> None:
        """from_dict with no is_thinking key defaults to False (backward compat)."""
        d = {"token": "hi", "token_index": 0, "is_final": False, "is_tool_call": False, "session_id": "s"}
        t = StreamToken.from_dict(d)
        assert t.is_thinking is False

    def test_json_serializable(self) -> None:
        t = self._make_token()
        raw = json.dumps(t.to_dict())
        restored = StreamToken.from_dict(json.loads(raw))
        assert restored == t


# ─────────────────────────────────────────────────────────────────
# GatewayPGOVResult
# ─────────────────────────────────────────────────────────────────


class TestGatewayPGOVResult:
    """GatewayPGOVResult serialization and construction."""

    def test_approved_result(self) -> None:
        r = GatewayPGOVResult(approved=True, sanitized_text="ok")
        assert r.approved is True
        assert r.sanitized_text == "ok"
        assert r.reason_codes == []
        assert r.request_id == ""

    def test_denied_result(self) -> None:
        r = GatewayPGOVResult(
            approved=False,
            sanitized_text=PGOV_DENIAL_FALLBACK,
            reason_codes=[REASON_PII_DETECTED, REASON_LEAKAGE_DETECTED],
            request_id="req-1",
        )
        assert r.approved is False
        assert len(r.reason_codes) == 2
        assert REASON_PII_DETECTED in r.reason_codes

    def test_round_trip(self) -> None:
        original = GatewayPGOVResult(
            approved=False,
            sanitized_text="redacted",
            reason_codes=[REASON_TOKEN_BUDGET_EXCEEDED],
            request_id="req-2",
        )
        restored = GatewayPGOVResult.from_dict(original.to_dict())
        assert restored.approved == original.approved
        assert restored.sanitized_text == original.sanitized_text
        assert restored.reason_codes == original.reason_codes
        assert restored.request_id == original.request_id

    def test_from_dict_defaults(self) -> None:
        r = GatewayPGOVResult.from_dict({})
        assert r.approved is False  # Fail-Closed
        assert r.sanitized_text == ""
        assert r.reason_codes == []


# ─────────────────────────────────────────────────────────────────
# Reason Codes
# ─────────────────────────────────────────────────────────────────


class TestReasonCodes:
    """Verify the 6 canonical reason codes (ADR-009)."""

    def test_all_reason_codes_count(self) -> None:
        assert len(ALL_REASON_CODES) == 6

    def test_all_reason_codes_members(self) -> None:
        assert ALL_REASON_CODES == frozenset({
            "TOKEN_BUDGET_EXCEEDED",
            "PII_DETECTED",
            "DELIMITER_ECHO",
            "TOOL_CALL_VIOLATION",
            "LEAKAGE_DETECTED",
            "VALIDATION_ERROR",
        })

    def test_constants_match_set(self) -> None:
        expected = {
            REASON_TOKEN_BUDGET_EXCEEDED,
            REASON_PII_DETECTED,
            REASON_DELIMITER_ECHO,
            REASON_TOOL_CALL_VIOLATION,
            REASON_LEAKAGE_DETECTED,
            REASON_VALIDATION_ERROR,
        }
        assert expected == ALL_REASON_CODES


# ─────────────────────────────────────────────────────────────────
# TransportGateway
# ─────────────────────────────────────────────────────────────────


class TestTransportGatewayInit:
    """Verify gateway initial state."""

    def test_initial_state_is_initializing(self) -> None:
        gw = TransportGateway()
        assert gw.state == StartupState.INITIALIZING

    def test_not_connected_by_default(self) -> None:
        gw = TransportGateway()
        assert gw.connected is False

    def test_dev_mode_defaults(self) -> None:
        gw = TransportGateway(dev_mode=True, host="localhost", port=9999)
        assert gw._dev_mode is True
        assert gw._host == "localhost"
        assert gw._port == 9999


class TestCheckPaStatus:
    """Boot-Phase-3 PA handshake retry logic."""

    @pytest.mark.asyncio
    async def test_check_pa_status_state_transitions(self) -> None:
        """State transitions INITIALIZING -> HANDSHAKING -> OPERATIONAL."""
        gw = TransportGateway(dev_mode=True, port=0)
        observed: list[StartupState] = [gw.state]

        async def _success() -> bool:
            observed.append(gw.state)
            return True

        gw._attempt_pa_handshake = _success  # type: ignore[method-assign]
        result = await gw.check_pa_status()
        observed.append(gw.state)

        assert result is True
        assert observed[0] == StartupState.INITIALIZING
        assert StartupState.HANDSHAKING in observed
        assert observed[-1] == StartupState.OPERATIONAL

    @pytest.mark.asyncio
    async def test_check_pa_status_state_failed(self) -> None:
        """State transitions INITIALIZING -> HANDSHAKING -> FAILED."""
        gw = TransportGateway(dev_mode=True, port=0)

        async def _fail() -> bool:
            raise ConnectionError("forced")

        async def _no_sleep(_: float) -> None:
            return None

        gw._attempt_pa_handshake = _fail  # type: ignore[method-assign]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(asyncio, "sleep", _no_sleep)
            result = await gw.check_pa_status()

        assert result is False
        assert gw.state == StartupState.FAILED

    @pytest.mark.asyncio
    async def test_handshake_fails_with_no_port(self) -> None:
        """Port=0 → configuration absence → IMMEDIATE FAILED (#808 carve-out)."""
        gw = TransportGateway(dev_mode=True, port=0)
        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED
        assert gw.connected is False

    @pytest.mark.asyncio
    async def test_handshake_fails_with_unreachable_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unreachable port → ConnectionError → FAILED after budget exhaustion.

        Drives the REAL connect path (refused instantly — the exact shape of
        a not-yet-listening PA); the 180 s backoff schedule is stubbed to a
        two-sleep schedule so the test proves exhaustion without real sleeps.
        """
        import services.ui_gateway.src.transport as transport_module

        monkeypatch.setattr(
            transport_module,
            "pa_handshake_backoff_schedule",
            lambda: (0.0, 0.0),
        )
        gw = TransportGateway(dev_mode=True, port=1)
        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED


class TestSendPrompt:
    """send_prompt validation and state guards."""

    @pytest.mark.asyncio
    async def test_rejects_when_not_operational(self) -> None:
        gw = TransportGateway()
        with pytest.raises(RuntimeError, match="not operational"):
            await gw.send_prompt("sess-1", "hello")

    @pytest.mark.asyncio
    async def test_rejects_empty_prompt(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL  # force state for test
        with pytest.raises(ValueError, match="empty"):
            await gw.send_prompt("sess-1", "   ")

    @pytest.mark.asyncio
    async def test_returns_request_id(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        request_id = await gw.send_prompt("sess-1", "Hello world")
        assert isinstance(request_id, str)
        assert len(request_id) == 36  # UUID format


class TestStreamTokens:
    """stream_tokens operational guards."""

    @pytest.mark.asyncio
    async def test_raises_when_not_operational(self) -> None:
        gw = TransportGateway()
        with pytest.raises(RuntimeError, match="not operational"):
            async for _ in gw.stream_tokens("sess-1"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_yields_nothing_when_operational_stub(self) -> None:
        """STUB: default Fail-Closed yields zero tokens."""
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        tokens = [t async for t in gw.stream_tokens("sess-1")]
        assert tokens == []


class TestGetPGOVResult:
    """get_pgov_result default Fail-Closed behavior."""

    def test_default_deny(self) -> None:
        gw = TransportGateway()
        result = gw.get_pgov_result("req-1")
        assert result.approved is False
        assert REASON_VALIDATION_ERROR in result.reason_codes
        assert result.request_id == "req-1"
        assert result.sanitized_text == PGOV_DENIAL_FALLBACK


class TestToolCallBuffer:
    """Tool-call buffering and flushing."""

    def _make_tool_token(self, text: str = "fn()", index: int = 0) -> StreamToken:
        return StreamToken(
            token=text,
            token_index=index,
            is_final=False,
            is_tool_call=True,
            session_id="sess-1",
        )

    def test_buffer_and_flush_approved(self) -> None:
        gw = TransportGateway()
        t1 = self._make_tool_token("open(", 0)
        t2 = self._make_tool_token("file)", 1)
        gw.buffer_tool_call_token(t1)
        gw.buffer_tool_call_token(t2)
        flushed = gw.flush_tool_call_buffer(pgov_approved=True)
        assert flushed == [t1, t2]

    def test_buffer_and_flush_denied(self) -> None:
        gw = TransportGateway()
        gw.buffer_tool_call_token(self._make_tool_token())
        flushed = gw.flush_tool_call_buffer(pgov_approved=False)
        assert flushed == []

    def test_flush_clears_buffer(self) -> None:
        gw = TransportGateway()
        gw.buffer_tool_call_token(self._make_tool_token())
        gw.flush_tool_call_buffer(pgov_approved=True)
        assert gw.flush_tool_call_buffer(pgov_approved=True) == []

    def test_buffer_overflow_raises(self) -> None:
        gw = TransportGateway()
        for i in range(TOOL_CALL_BUFFER_MAX_TOKENS):
            gw.buffer_tool_call_token(self._make_tool_token(index=i))
        with pytest.raises(ValueError, match="buffer exceeded"):
            gw.buffer_tool_call_token(self._make_tool_token())


class TestReset:
    """reset() returns gateway to initial state."""

    def test_reset_returns_to_initializing(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.FAILED
        gw.reset()
        assert gw.state == StartupState.INITIALIZING

    def test_reset_clears_state(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._connected = True
        gw.buffer_tool_call_token(
            StreamToken("x", 0, False, True, "s")
        )
        gw.reset()
        assert gw.state == StartupState.INITIALIZING
        assert gw.connected is False
        assert gw.flush_tool_call_buffer(pgov_approved=True) == []

    def test_reset_clears_pgov_cache(self) -> None:
        """P1.11: reset must also flush the PGOV result cache."""
        gw = TransportGateway()
        gw._pgov_cache["req-1"] = GatewayPGOVResult(
            approved=True, sanitized_text="ok", request_id="req-1"
        )
        gw.reset()
        result = gw.get_pgov_result("req-1")
        assert result.approved is False  # fallen back to Fail-Closed


# ─────────────────────────────────────────────────────────────────
# P1.11 Live IPC Tests — full mock Orchestrator flow
# ─────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────
# WI-1: STREAM_TOKEN_BUFFER_LIMIT exact-boundary overflow guard
# ─────────────────────────────────────────────────────────────────


class _MockTransport:
    """Synchronous receive-from-list transport stub (no real socket)."""

    def __init__(self, messages: list[bytes | None]) -> None:
        self._iter = iter(messages)
        self.connected = True

    def receive(self) -> bytes | None:
        return next(self._iter, None)


from services.ui_gateway.src.constants import STREAM_TOKEN_BUFFER_LIMIT  # noqa: E402


class TestStreamTokensBufferLimit:
    """WI-1: stream_tokens() circuit-breaker at exactly STREAM_TOKEN_BUFFER_LIMIT."""

    def _make_token_msg(self, index: int) -> bytes:
        return _framer.encode_stream_token(
            token=f"t{index}",
            token_index=index,
            is_final=False,
            is_tool_call=False,
            session_id="sess",
            request_id="",
        )

    @pytest.mark.asyncio
    async def test_stream_tokens_at_limit_yields_last_token(self) -> None:
        """Exactly STREAM_TOKEN_BUFFER_LIMIT tokens are all yielded; no overflow log."""
        messages: list[bytes | None] = [
            self._make_token_msg(i) for i in range(STREAM_TOKEN_BUFFER_LIMIT)
        ]
        messages.append(None)  # stream-end sentinel

        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._transport = _MockTransport(messages)  # type: ignore[assignment]

        tokens = [t async for t in gw.stream_tokens("sess")]
        assert len(tokens) == STREAM_TOKEN_BUFFER_LIMIT
        assert tokens[0].token == "t0"
        assert tokens[-1].token == f"t{STREAM_TOKEN_BUFFER_LIMIT - 1}"

    @pytest.mark.asyncio
    async def test_stream_tokens_one_over_limit_breaks(self) -> None:
        """STREAM_TOKEN_BUFFER_LIMIT+1 tokens → exactly LIMIT yielded, stream breaks."""
        messages: list[bytes | None] = [
            self._make_token_msg(i) for i in range(STREAM_TOKEN_BUFFER_LIMIT + 1)
        ]
        messages.append(None)

        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._transport = _MockTransport(messages)  # type: ignore[assignment]

        tokens = [t async for t in gw.stream_tokens("sess")]
        assert len(tokens) == STREAM_TOKEN_BUFFER_LIMIT
        assert tokens[-1].token == f"t{STREAM_TOKEN_BUFFER_LIMIT - 1}"


# ─────────────────────────────────────────────────────────────────
# WI-2: stream_tokens malformed-message / decode-error continue path
# ─────────────────────────────────────────────────────────────────


class TestStreamTokensDecodeError:
    """WI-2: Malformed frames are skipped; surrounding valid tokens are yielded."""

    @pytest.mark.asyncio
    async def test_stream_tokens_malformed_frame_skips_and_continues(self) -> None:
        """Injected ValueError frame → skipped with logger.error; stream continues."""
        valid_0 = _framer.encode_stream_token(
            "tok0", 0, False, False, "sess", ""
        )
        # Bytes that cause ValueError in MessageFramer.decode (invalid JSON body)
        malformed = b"not-valid-json"
        valid_1 = _framer.encode_stream_token(
            "tok1", 1, False, False, "sess", ""
        )
        final_tok = _framer.encode_stream_token(
            "final", 2, True, False, "sess", ""
        )
        complete_msg = _framer.encode_generation_complete(request_id="")

        messages: list[bytes | None] = [valid_0, malformed, valid_1, final_tok, complete_msg]

        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        gw._transport = _MockTransport(messages)  # type: ignore[assignment]

        tokens = [t async for t in gw.stream_tokens("sess")]
        token_texts = [t.token for t in tokens]
        assert "tok0" in token_texts
        assert "tok1" in token_texts
        assert "final" in token_texts


# ─────────────────────────────────────────────────────────────────
# WI-3: check_pa_status already-connected short-circuit
# ─────────────────────────────────────────────────────────────────


class TestCheckPaStatusShortCircuit:
    """WI-3: Already-connected gateway skips handshake entirely."""

    @pytest.mark.asyncio
    async def test_check_pa_status_returns_true_when_already_connected(self) -> None:
        gw = TransportGateway()
        gw._connected = True

        from unittest.mock import AsyncMock as _AsyncMock
        gw._attempt_pa_handshake = _AsyncMock()  # type: ignore[method-assign]

        result = await gw.check_pa_status()
        assert result is True
        gw._attempt_pa_handshake.assert_not_called()  # type: ignore[attr-defined]


# ─────────────────────────────────────────────────────────────────
# WI-10: PA handshake retry / backoff sequence assertions
# ─────────────────────────────────────────────────────────────────

from services.ui_gateway.src.constants import (  # noqa: E402
    PA_HANDSHAKE_BACKOFF_BASE_S,
    PA_HANDSHAKE_MAX_RETRIES,
)


class TestPaHandshakeRetry:
    """WI-10: Retry loop fires correct backoff sleeps; exhaustion returns False."""

    @pytest.mark.asyncio
    async def test_check_pa_status_backoff_sequence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail twice, succeed on attempt 3 → sleep [1.0, 2.0] recorded."""
        gw = TransportGateway(dev_mode=True, port=0)

        attempt_count = 0

        async def _mock_handshake() -> bool:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("forced fail")
            return True

        gw._attempt_pa_handshake = _mock_handshake  # type: ignore[method-assign]

        recorded_sleeps: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded_sleeps.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is True
        assert recorded_sleeps == [
            PA_HANDSHAKE_BACKOFF_BASE_S,
            PA_HANDSHAKE_BACKOFF_BASE_S * 2,
        ]

    @pytest.mark.asyncio
    async def test_check_pa_status_exhausts_retries_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All retries fail → returns False; sleep called exactly MAX_RETRIES-1 times."""
        gw = TransportGateway(dev_mode=True, port=0)

        async def _always_fail() -> bool:
            raise ConnectionError("forced")

        gw._attempt_pa_handshake = _always_fail  # type: ignore[method-assign]

        recorded_sleeps: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded_sleeps.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED
        assert len(recorded_sleeps) == PA_HANDSHAKE_MAX_RETRIES - 1


# ─────────────────────────────────────────────────────────────────
# #808: budgeted handshake — the widened cold-load window
# ─────────────────────────────────────────────────────────────────

from services.ui_gateway.src.constants import (  # noqa: E402
    PA_HANDSHAKE_BUDGET_S,
    PA_HANDSHAKE_TIMEOUT_S,
    pa_handshake_backoff_schedule,
)
from services.ui_gateway.src.transport import (  # noqa: E402
    HandshakeConfigurationError,
)


class TestHandshakeBudget808:
    """#808 regression locks: the aggregate handshake budget is the documented
    cold-14B-load ceiling (180 s), the healthy path is unchanged, exhaustion
    still fails closed, and configuration absence still fails FAST."""

    @pytest.mark.asyncio
    async def test_cold_pa_recovers_within_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A PA that becomes ready long AFTER the old ~15-18 s budget now connects.

        Simulates a cold 14B load: every attempt is refused until the planned
        elapsed backoff exceeds 60 s (deep past the old ceiling), then the
        handshake succeeds. Sleeps are recorded, not slept.
        """
        schedule = pa_handshake_backoff_schedule()
        # Succeed on the first attempt whose planned start offset is > 60 s.
        elapsed = 0.0
        ready_attempt = None
        for idx, delay in enumerate(schedule):
            elapsed += delay
            if elapsed > 60.0:
                ready_attempt = idx + 2  # attempt AFTER the idx-th sleep
                break
        assert ready_attempt is not None
        planned_backoff_before_success = sum(schedule[: ready_attempt - 1])
        assert planned_backoff_before_success > 18.0, (
            "the simulated readiness must land beyond the OLD worst-case "
            "budget, or this lock proves nothing"
        )

        gw = TransportGateway(dev_mode=True, port=0)
        # port=0 would config-fail; bypass by stubbing the attempt itself.
        attempt_count = 0

        async def _cold_then_ready() -> bool:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < ready_attempt:
                raise ConnectionError("refused — model still loading")
            return True

        gw._attempt_pa_handshake = _cold_then_ready  # type: ignore[method-assign]

        recorded: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is True
        assert gw.state == StartupState.OPERATIONAL
        assert gw.connected is True
        # The loop executed exactly the planned schedule prefix.
        assert recorded == list(schedule[: ready_attempt - 1])
        assert sum(recorded) == planned_backoff_before_success

    @pytest.mark.asyncio
    async def test_healthy_path_latency_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First-attempt success sleeps ZERO seconds — the widen adds no
        latency to a healthy boot."""
        gw = TransportGateway(dev_mode=True, port=0)

        async def _immediate() -> bool:
            return True

        gw._attempt_pa_handshake = _immediate  # type: ignore[method-assign]

        recorded: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is True
        assert gw.state == StartupState.OPERATIONAL
        assert recorded == []

    @pytest.mark.asyncio
    async def test_budget_exhausted_still_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exhausting the FULL 180 s schedule still lands FAILED + not
        connected (bounded retry, not abandoned fail-closed)."""
        gw = TransportGateway(dev_mode=True, port=0)

        async def _never_ready() -> bool:
            raise ConnectionError("refused forever")

        gw._attempt_pa_handshake = _never_ready  # type: ignore[method-assign]

        recorded: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED
        assert gw.connected is False
        # The whole planned schedule was consumed — and it IS the budget.
        assert recorded == list(pa_handshake_backoff_schedule())
        assert sum(recorded) == PA_HANDSHAKE_BUDGET_S

    @pytest.mark.asyncio
    async def test_config_absence_fails_immediately_no_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """port=0 (dev) is a configuration absence: FAILED with ZERO sleeps —
        the 180 s patience must never apply to a misconfiguration (#808)."""
        gw = TransportGateway(dev_mode=True, port=0)

        recorded: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED
        assert recorded == []

    @pytest.mark.asyncio
    async def test_production_missing_certs_fails_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production (dev_mode=False) without mTLS cert paths: configuration
        absence → immediate FAILED, zero sleeps, no socket ever opened."""
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path="", mtls_key_path="", ca_cert_path="",
        )

        recorded: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED
        assert recorded == []

    @pytest.mark.asyncio
    async def test_production_host_mode_port_zero_fails_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production host-mode with port=0: configuration absence → immediate
        FAILED (the helper's own port check is now defense-in-depth)."""
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=0,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )

        recorded: list[float] = []

        async def fake_sleep(duration: float) -> None:
            recorded.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        result = await gw.check_pa_status()
        assert result is False
        assert gw.state == StartupState.FAILED
        assert recorded == []

    @pytest.mark.asyncio
    async def test_production_handshake_attempt_bounded_by_handshake_timeout(
        self,
    ) -> None:
        """The host-mode handshake attempt passes PA_HANDSHAKE_TIMEOUT_S to the
        connector — NOT the 180 s PROMPT_RESPONSE_TIMEOUT_S default it rode
        before #808 (one mute server must not eat the whole budget)."""
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )
        captured: list[float] = []

        def _capture(timeout_s: float = -1.0):  # noqa: ANN202 — test double
            captured.append(timeout_s)
            return None  # → ConnectionError → retryable failure

        gw._connect_host_loopback_mtls = _capture  # type: ignore[method-assign]

        with pytest.raises(ConnectionError):
            await gw._attempt_pa_handshake()
        assert captured == [PA_HANDSHAKE_TIMEOUT_S]

    @pytest.mark.asyncio
    async def test_guest_handshake_attempt_bounded_by_handshake_timeout(
        self,
    ) -> None:
        """Same bound for the guest-mode (AF_HYPERV) handshake attempt."""
        gw = TransportGateway(
            dev_mode=False, host_mode=False, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )
        captured: list[float] = []

        def _capture(timeout_s: float = -1.0):  # noqa: ANN202 — test double
            captured.append(timeout_s)
            return None

        gw._connect_hyperv = _capture  # type: ignore[method-assign]

        with pytest.raises(ConnectionError):
            await gw._attempt_pa_handshake()
        assert captured == [PA_HANDSHAKE_TIMEOUT_S]

    def test_hyperv_raw_socket_honors_caller_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_connect_hyperv must settimeout(timeout_s) on the raw socket — it
        previously HARDCODED PROMPT_RESPONSE_TIMEOUT_S, silently ignoring its
        own parameter (#808 latent-defect fix lock)."""
        import services.ui_gateway.src.transport as transport_module

        recorded_timeouts: list[float] = []

        class _FakeRawSocket:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def settimeout(self, value: float) -> None:
                recorded_timeouts.append(value)

            def connect(self, address: object) -> None:
                raise OSError("no AF_HYPERV endpoint in tests")

            def close(self) -> None:
                pass

        monkeypatch.setattr(
            transport_module._socket_mod, "socket", _FakeRawSocket
        )
        gw = TransportGateway(
            dev_mode=False, host_mode=False, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )
        result = gw._connect_hyperv(timeout_s=3.25)
        assert result is None  # connect refused → fail-closed None
        assert recorded_timeouts == [3.25]

    def test_handshake_configuration_error_is_a_connection_error(self) -> None:
        """The carve-out subclasses ConnectionError so any existing caller
        catching ConnectionError keeps working."""
        assert issubclass(HandshakeConfigurationError, ConnectionError)


# ─────────────────────────────────────────────────────────────────
# #805: mTLS client SSLContext reuse across per-message connections
# ─────────────────────────────────────────────────────────────────


class _FakeRawSocket805:
    """Minimal raw-socket stand-in for the connect helpers."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def settimeout(self, value: float) -> None:
        pass

    def connect(self, address: object) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeSSLContext805:
    """Stand-in mTLS context; records how many sockets it wrapped."""

    def __init__(self) -> None:
        self.wrap_calls = 0

    def wrap_socket(self, sock: object, server_side: bool = False) -> object:
        self.wrap_calls += 1
        return ("wrapped", sock)


class _FakeSSLContextWrapFails805:
    """Stand-in mTLS context that BUILDS fine but whose handshake (wrap_socket)
    FAILS with SSLError — mimics the cert-signature-mismatch a mid-re-mint
    per-boot cert set produces during the battery's early boot (night-20260711)."""

    def __init__(self) -> None:
        self.wrap_calls = 0

    def wrap_socket(self, sock: object, server_side: bool = False) -> object:
        import ssl

        self.wrap_calls += 1
        raise ssl.SSLError("certificate verify failed: signature failure (test)")


class _FakeTransport805:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs


class TestClientSSLContextReuse:
    """#805: the immutable mTLS client context is built ONCE and reused across
    the connection-per-message calls — not rebuilt (disk PEM reads + context
    construction) on every send_prompt / tool round-trip / ingest / imagine."""

    def _patch_connect_env(
        self, monkeypatch: pytest.MonkeyPatch, factory_result: object
    ) -> dict[str, int]:
        """Patch the SSL factory + socket + transport; return a call counter."""
        import services.ui_gateway.src.transport as transport_module

        counter = {"factory": 0}

        def _fake_factory(cert: str, key: str, ca: str) -> object:
            counter["factory"] += 1
            return factory_result

        monkeypatch.setattr(
            "shared.ipc.vsock.create_client_ssl_context", _fake_factory
        )
        monkeypatch.setattr(
            transport_module._socket_mod, "socket", _FakeRawSocket805
        )
        monkeypatch.setattr(transport_module, "VsockTransport", _FakeTransport805)
        return counter

    def test_host_loopback_builds_context_once_across_connections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two host-mode (loopback+mTLS) connections build the SSLContext once."""
        fake_ctx = _FakeSSLContext805()
        counter = self._patch_connect_env(monkeypatch, fake_ctx)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )

        t1 = gw._connect_host_loopback_mtls()
        t2 = gw._connect_host_loopback_mtls()

        # The OLD code called the factory once PER connection (== 2 here);
        # the fix builds it once and reuses the cached context.
        assert counter["factory"] == 1
        assert isinstance(t1, _FakeTransport805)
        assert isinstance(t2, _FakeTransport805)
        assert gw._client_ssl_ctx is fake_ctx
        # Both connections actually used the SAME context object (2 wraps).
        assert fake_ctx.wrap_calls == 2

    def test_hyperv_reuses_the_same_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The AF_HYPERV (guest-mode) connect path reuses the cached context too."""
        fake_ctx = _FakeSSLContext805()
        counter = self._patch_connect_env(monkeypatch, fake_ctx)
        gw = TransportGateway(
            dev_mode=False, host_mode=False, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )

        t1 = gw._connect_hyperv()
        t2 = gw._connect_hyperv()

        assert counter["factory"] == 1
        assert isinstance(t1, _FakeTransport805)
        assert isinstance(t2, _FakeTransport805)
        assert gw._client_ssl_ctx is fake_ctx
        assert fake_ctx.wrap_calls == 2

    def test_build_failure_is_not_cached_fail_closed_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A context-build failure returns None (connection refused, fail-closed)
        and is NOT cached — the next connect retries the build rather than being
        permanently poisoned by one transient failure."""
        counter = self._patch_connect_env(monkeypatch, None)  # factory → None
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )

        assert gw._connect_host_loopback_mtls() is None  # fail-closed
        assert gw._connect_host_loopback_mtls() is None
        assert gw._client_ssl_ctx is None  # nothing cached
        assert counter["factory"] == 2  # retried, not poisoned

    def test_host_failed_handshake_drops_cache_so_retry_rebuilds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#805 regression fix (night-20260711 battery): a context that BUILDS
        successfully but whose HANDSHAKE fails (wrap_socket raises — the
        mid-re-mint cert signature mismatch) must be DROPPED from the cache, so
        the next connect rebuilds from the settled certs. WITHOUT this fix the
        poisoned context is reused and fails all 16 boot handshake retries, and
        the AO dies fail-closed (every battery job then STALLs)."""
        failing = _FakeSSLContextWrapFails805()
        counter = self._patch_connect_env(monkeypatch, failing)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path="c.pem", mtls_key_path="k.pem", ca_cert_path="ca.pem",
        )

        assert gw._connect_host_loopback_mtls() is None  # handshake fails, fail-closed
        assert gw._client_ssl_ctx is None  # cache DROPPED — restores self-healing
        assert gw._connect_host_loopback_mtls() is None
        assert counter["factory"] == 2  # rebuilt on the retry, NOT poisoned once
        assert failing.wrap_calls == 2  # both attempts actually tried the handshake


# ─────────────────────────────────────────────────────────────────
# #906: the #805 cache must FOLLOW a cert re-mint. A long-lived gateway (the
# battery runner holds ONE all night) outlives AO launcher reboots; a
# swap-restore relaunch re-mints certs/ under it, and a context cached across
# that re-mint burned the next PLAN with CERTIFICATE_VERIFY_FAILED —
# night-20260714 B2/B5/B7, one job per re-mint.
# ─────────────────────────────────────────────────────────────────


class _FakeSSLContextVerifyFails906:
    """Stand-in context whose handshake fails VERIFICATION specifically
    (``ssl.SSLCertVerificationError``) — the stale-generation shape #906's
    bounded retry exists for (distinct from the plain ``SSLError`` above)."""

    def __init__(self) -> None:
        self.wrap_calls = 0

    def wrap_socket(self, sock: object, server_side: bool = False) -> object:
        import ssl

        self.wrap_calls += 1
        raise ssl.SSLCertVerificationError(
            1, "certificate verify failed: certificate signature failure (test)"
        )


class TestClientSSLContextFollowsRemint:
    """#906: the cached client context is keyed to the ON-DISK cert generation
    ((mtime_ns,size) fingerprint) and a verify failure earns exactly one
    rebuild-and-retry — so a re-mint under a live gateway costs zero failed
    operations instead of one burned job."""

    def _patch_connect_env_seq(
        self, monkeypatch: pytest.MonkeyPatch, results: list[object]
    ) -> dict[str, int]:
        """Like TestClientSSLContextReuse._patch_connect_env, but the factory
        returns results[i] on its i-th call (last one repeats)."""
        import services.ui_gateway.src.transport as transport_module

        counter = {"factory": 0}

        def _fake_factory(cert: str, key: str, ca: str) -> object:
            idx = min(counter["factory"], len(results) - 1)
            counter["factory"] += 1
            return results[idx]

        monkeypatch.setattr(
            "shared.ipc.vsock.create_client_ssl_context", _fake_factory
        )
        monkeypatch.setattr(
            transport_module._socket_mod, "socket", _FakeRawSocket805
        )
        monkeypatch.setattr(transport_module, "VsockTransport", _FakeTransport805)
        return counter

    @staticmethod
    def _write_generation(certs_dir, tag: str, t_ns: int) -> tuple[str, str, str]:
        """Write a (cert,key,ca) file triple with a pinned mtime — one on-disk
        'generation'. Re-writing with a different t_ns is the re-mint."""
        import os

        paths = []
        for name in ("c.pem", "k.pem", "ca.pem"):
            p = certs_dir / name
            p.write_text(f"{tag}:{name}", encoding="utf-8")
            os.utime(p, ns=(t_ns, t_ns))
            paths.append(str(p))
        return tuple(paths)  # type: ignore[return-value]

    def test_same_generation_reuses_across_connections(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With REAL cert files present and unchanged, the #805 reuse survives
        the #906 fingerprint check — two connections, one context build."""
        fake_ctx = _FakeSSLContext805()
        counter = self._patch_connect_env_seq(monkeypatch, [fake_ctx])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_host_loopback_mtls() is not None
        assert gw._connect_host_loopback_mtls() is not None
        assert counter["factory"] == 1  # the #805 win is intact
        assert fake_ctx.wrap_calls == 2

    def test_cert_remint_rebuilds_the_cached_context(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rewriting the cert files (new mtime = a re-mint) makes the NEXT
        connect rebuild the context BEFORE any handshake — the stale context is
        never offered to the server (the night-20260714 defect: it was, and the
        job burned)."""
        gen_a_ctx = _FakeSSLContext805()
        gen_b_ctx = _FakeSSLContext805()
        counter = self._patch_connect_env_seq(monkeypatch, [gen_a_ctx, gen_b_ctx])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_host_loopback_mtls() is not None
        assert counter["factory"] == 1
        assert gw._client_ssl_ctx is gen_a_ctx

        # THE RE-MINT: same paths, new content + mtime (generation B).
        self._write_generation(tmp_path, "gen-b", 2_000_000_000)

        assert gw._connect_host_loopback_mtls() is not None
        assert counter["factory"] == 2               # rebuilt on the generation change
        assert gw._client_ssl_ctx is gen_b_ctx        # the NEW context is cached
        assert gen_a_ctx.wrap_calls == 1              # the stale context was NOT reused
        assert gen_b_ctx.wrap_calls == 1

    def test_unknown_generation_keeps_serving_the_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Paths that cannot be stat'd (absent / mid-mint) are an UNKNOWN
        generation, not a CHANGED one — the cached context keeps serving (the
        exact pre-#906 semantics; staleness is not provable and a rebuild could
        not read the files anyway). Pins the #805-compat behavior the other
        tests in TestClientSSLContextReuse rely on."""
        fake_ctx = _FakeSSLContext805()
        counter = self._patch_connect_env_seq(monkeypatch, [fake_ctx])
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path="absent-c.pem", mtls_key_path="absent-k.pem",
            ca_cert_path="absent-ca.pem",
        )

        assert gw._connect_host_loopback_mtls() is not None
        assert gw._connect_host_loopback_mtls() is not None
        assert counter["factory"] == 1

    def test_verify_failure_rebuilds_and_retries_once(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stat-then-mint race residue: a VERIFICATION failure drops the
        cache, rebuilds from disk, and retries ONCE — the caller's operation
        SUCCEEDS instead of burning (verification is re-run in full against the
        freshly-read CA; nothing is relaxed)."""
        stale = _FakeSSLContextVerifyFails906()
        fresh = _FakeSSLContext805()
        counter = self._patch_connect_env_seq(monkeypatch, [stale, fresh])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_host_loopback_mtls() is not None  # the SAME call succeeds
        assert counter["factory"] == 2   # stale build + the one retry rebuild
        assert stale.wrap_calls == 1
        assert fresh.wrap_calls == 1
        assert gw._client_ssl_ctx is fresh

    def test_verify_failure_retry_is_bounded(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A GENUINE trust mismatch (verification still fails after the rebuild)
        stays a loud failure — exactly one retry, never a loop."""
        counter = self._patch_connect_env_seq(
            monkeypatch,
            [_FakeSSLContextVerifyFails906(), _FakeSSLContextVerifyFails906()],
        )
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_host_loopback_mtls() is None  # fail-closed after 1 retry
        assert counter["factory"] == 2  # never a third build

    def test_timeout_does_not_retry(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A handshake TIMEOUT never earns the retry — the no-timeout-doubling
        guarantee, pinned explicitly (review nit): one attempt, fail-closed."""

        class _TimesOut:
            def __init__(self) -> None:
                self.wrap_calls = 0

            def wrap_socket(self, sock: object, server_side: bool = False) -> object:
                self.wrap_calls += 1
                raise TimeoutError("The handshake operation timed out (test)")

        hanging = _TimesOut()
        counter = self._patch_connect_env_seq(monkeypatch, [hanging])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_host_loopback_mtls() is None
        assert hanging.wrap_calls == 1  # ONE attempt — a timeout is never doubled
        assert counter["factory"] == 1

    def test_non_verify_ssl_error_does_not_retry(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only VERIFICATION failures earn the retry — a plain SSLError (protocol
        /record-layer) keeps the pre-#906 single-attempt behavior (no timeout or
        failure doubling)."""
        failing = _FakeSSLContextWrapFails805()  # plain ssl.SSLError
        counter = self._patch_connect_env_seq(monkeypatch, [failing])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_host_loopback_mtls() is None
        assert failing.wrap_calls == 1  # ONE attempt — no retry for non-verify errors
        assert counter["factory"] == 1

    # -- #907: AF_HYPERV (guest-mode) parity for the #906 verify-failure retry --
    # The guest-topology connect path (#615) got the generation-fingerprint
    # rebuild from #906 (it shares _client_ssl_context) but NOT the bounded
    # verify-failure retry, which lived only on the host-loopback path. These
    # pin the parity fix: same VERIFY-only, retry-once, never-on-timeout shape.

    def test_hyperv_verify_failure_rebuilds_and_retries_once(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A guest-mode (AF_HYPERV) verification failure drops the cache,
        rebuilds from disk, and retries ONCE — the connect SUCCEEDS instead of
        burning, exactly as the host path (verification re-run in full)."""
        stale = _FakeSSLContextVerifyFails906()
        fresh = _FakeSSLContext805()
        counter = self._patch_connect_env_seq(monkeypatch, [stale, fresh])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=False, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_hyperv() is not None  # the SAME call succeeds
        assert counter["factory"] == 2           # stale build + one retry rebuild
        assert stale.wrap_calls == 1
        assert fresh.wrap_calls == 1
        assert gw._client_ssl_ctx is fresh

    def test_hyperv_verify_failure_retry_is_bounded(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A genuine guest-mode trust mismatch stays a loud failure — exactly
        one retry, never a loop."""
        counter = self._patch_connect_env_seq(
            monkeypatch,
            [_FakeSSLContextVerifyFails906(), _FakeSSLContextVerifyFails906()],
        )
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=False, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_hyperv() is None  # fail-closed after 1 retry
        assert counter["factory"] == 2       # never a third build

    def test_hyperv_timeout_does_not_retry(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A guest-mode handshake TIMEOUT never earns the retry — no timeout
        doubling on the AF_HYPERV path either."""

        class _TimesOut:
            def __init__(self) -> None:
                self.wrap_calls = 0

            def wrap_socket(self, sock: object, server_side: bool = False) -> object:
                self.wrap_calls += 1
                raise TimeoutError("The handshake operation timed out (test)")

        hanging = _TimesOut()
        counter = self._patch_connect_env_seq(monkeypatch, [hanging])
        cert, key, ca = self._write_generation(tmp_path, "gen-a", 1_000_000_000)
        gw = TransportGateway(
            dev_mode=False, host_mode=False, port=5001,
            mtls_cert_path=cert, mtls_key_path=key, ca_cert_path=ca,
        )

        assert gw._connect_hyperv() is None
        assert hanging.wrap_calls == 1  # ONE attempt — a timeout is never doubled
        assert counter["factory"] == 1


class TestGatewayFollowsRemintLive:
    """#906 real-seam lock: a REAL TransportGateway, REAL per-boot certs
    (shared.security.cert_provisioning), a REAL loopback TLS server — the exact
    night-20260714 sequence in miniature. Pre-#906 code fails the second
    connect (the burned job); the fix makes it succeed."""

    def test_gateway_survives_a_cert_remint_between_connections(self, tmp_path) -> None:
        import socket as _socket
        import ssl as _ssl
        import threading

        from shared.security.cert_provisioning import (
            CA_CERT_NAME,
            GATEWAY_CLIENT_CERT_NAME,
            GATEWAY_CLIENT_KEY_NAME,
            PA_SERVER_CERT_NAME,
            PA_SERVER_KEY_NAME,
            provision_per_boot_certs,
        )

        certs = tmp_path / "certs"

        def _server_ctx() -> _ssl.SSLContext:
            ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(
                certfile=str(certs / PA_SERVER_CERT_NAME),
                keyfile=str(certs / PA_SERVER_KEY_NAME),
            )
            return ctx

        provision_per_boot_certs(certs_dir=certs)  # generation A
        holder = {"ctx": _server_ctx()}            # the live AO presents leaf A

        srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        srv.settimeout(0.5)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def _serve() -> None:
            while not stop.is_set():
                try:
                    raw, _ = srv.accept()
                except _socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    with holder["ctx"].wrap_socket(raw, server_side=True) as ss:
                        ss.recv(1)  # hold until the client closes post-handshake
                except (OSError, _ssl.SSLError):
                    pass

        t = threading.Thread(target=_serve, daemon=True)
        t.start()

        gw = TransportGateway(
            dev_mode=False, host_mode=True, port=port,
            mtls_cert_path=str(certs / GATEWAY_CLIENT_CERT_NAME),
            mtls_key_path=str(certs / GATEWAY_CLIENT_KEY_NAME),
            ca_cert_path=str(certs / CA_CERT_NAME),
        )
        t1 = t2 = None
        try:
            t1 = gw._connect_host_loopback_mtls(timeout_s=5.0)
            assert t1 is not None, "sanity: the generation-A connect must succeed"
            # The gateway is connection-per-message: the PLAN that burned on the
            # real night opened a FRESH connection (the prior one long closed).
            # Close t1 so the single-threaded test server is free to accept the
            # next handshake — holding it open would only test server backlog.
            t1.close()

            # THE RE-MINT: a swap-restore relaunch rewrites the SAME certs dir
            # with a fresh CA + leaves, and the relaunched AO presents the new leaf.
            provision_per_boot_certs(certs_dir=certs)  # generation B
            holder["ctx"] = _server_ctx()

            t2 = gw._connect_host_loopback_mtls(timeout_s=5.0)
            assert t2 is not None, (
                "the connect after a cert re-mint must succeed — pre-#906 the "
                "gateway offered its stale cached context, died "
                "CERTIFICATE_VERIFY_FAILED, and the battery burned one job per "
                "re-mint (night-20260714 B2/B5/B7)"
            )
        finally:
            stop.set()
            srv.close()
            t.join(timeout=2.0)
            for transport in (t1, t2):
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:  # noqa: BLE001 — teardown must never mask the assert
                        pass


# ─────────────────────────────────────────────────────────────────
# WI-14: tool_call_buffer exact-boundary overflow test
# ─────────────────────────────────────────────────────────────────

from services.ui_gateway.src.constants import TOOL_CALL_BUFFER_MAX_TOKENS as _TCBMT  # noqa: E402


class TestToolCallBufferBoundary:
    """WI-14: Buffer accepts tokens up to MAX and raises on MAX+1."""

    def _make_tc_token(self, index: int = 0) -> StreamToken:
        return StreamToken(
            token=f"tc{index}",
            token_index=index,
            is_final=False,
            is_tool_call=True,
            session_id="sess",
        )

    def test_tool_call_buffer_at_limit_minus_one_accepts_next_token(self) -> None:
        """Fill MAX-1 tokens, accept one more (→MAX), then raise on the next."""
        gw = TransportGateway()
        # Fill MAX-1
        for i in range(_TCBMT - 1):
            gw.buffer_tool_call_token(self._make_tc_token(i))
        assert len(gw._tool_call_buffer) == _TCBMT - 1
        # Accept one more → exactly MAX, no raise
        gw.buffer_tool_call_token(self._make_tc_token(_TCBMT - 1))
        assert len(gw._tool_call_buffer) == _TCBMT
        # One more → overflow
        with pytest.raises(ValueError, match=f"exceeded {_TCBMT} tokens"):
            gw.buffer_tool_call_token(self._make_tc_token(_TCBMT))


# ─────────────────────────────────────────────────────────────────
# Non-live retained tests (degenerate no-transport / cache-only paths).
# The live-TCP variants of these classes moved to
# tests/integration/test_ui_gateway_ipc.py per P5_TASK8_EA5 WI-3.
# ─────────────────────────────────────────────────────────────────


class TestTransportNoTransportGuards:
    """Degenerate paths that do not spin up real TCP servers."""


    @pytest.mark.asyncio
    async def test_send_prompt_no_transport_still_returns_id(self) -> None:
        """When no transport, send_prompt still returns request_id (stub)."""
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        request_id = await gw.send_prompt("sess-1", "Hello stub")
        assert isinstance(request_id, str)
        assert len(request_id) == 36



    @pytest.mark.asyncio
    async def test_stream_tokens_no_transport_yields_nothing(self) -> None:
        """No transport connected → Fail-Closed (zero tokens)."""
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        tokens = [t async for t in gw.stream_tokens("sess-1")]
        assert tokens == []




class TestGetPGOVResultCache:
    """Cache hit/miss paths for get_pgov_result (no live TCP)."""


    def test_cache_hit_returns_result(self) -> None:
        """Pre-populated cache should return the cached result."""
        gw = TransportGateway()
        expected = GatewayPGOVResult(
            approved=True,
            sanitized_text="All clear",
            reason_codes=[],
            request_id="req-42",
        )
        gw._pgov_cache["req-42"] = expected
        result = gw.get_pgov_result("req-42")
        assert result.approved is True
        assert result.sanitized_text == "All clear"


    def test_cache_miss_returns_deny(self) -> None:
        """Missing cache entry → Fail-Closed (denied)."""
        gw = TransportGateway()
        result = gw.get_pgov_result("nonexistent")
        assert result.approved is False
        assert REASON_VALIDATION_ERROR in result.reason_codes



# ---------------------------------------------------------------------------
# Relocated from tests/integration/test_p114_ui_end_to_end.py per P5_TASK8_EA5 WI-4.
# `slow` marker stripped (3F.3): these are unit-scope service tests.
# ---------------------------------------------------------------------------


class TestP114Relocated:
    """Relocated non-cross-service P114 tests (formerly under tests/integration/)."""

    @pytest.mark.asyncio
    async def test_send_prompt_returns_request_id_string(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.OPERATIONAL
        request_id = await gw.send_prompt("sess-a1", "hello")
        assert isinstance(request_id, str)
        assert len(request_id) == 36


    @pytest.mark.asyncio
    async def test_send_prompt_raises_when_not_operational(self) -> None:
        gw = TransportGateway()
        with pytest.raises(RuntimeError, match="not operational"):
            await gw.send_prompt("sess-a6", "blocked")



    def test_flush_tool_call_buffer_approved_releases_tokens(self) -> None:
        gw = TransportGateway()
        gw.buffer_tool_call_token(StreamToken("one", 0, False, True, "sess-c2"))
        gw.buffer_tool_call_token(StreamToken("two", 1, True, True, "sess-c2"))
        flushed = gw.flush_tool_call_buffer(pgov_approved=True)
        assert [t.token for t in flushed] == ["one", "two"]


    def test_flush_tool_call_buffer_denied_discards_tokens(self) -> None:
        gw = TransportGateway()
        gw.buffer_tool_call_token(StreamToken("one", 0, False, True, "sess-c3"))
        flushed = gw.flush_tool_call_buffer(pgov_approved=False)
        assert flushed == []


    def test_gateway_reset_returns_to_initializing(self) -> None:
        gw = TransportGateway()
        gw._state = StartupState.FAILED
        gw.reset()
        assert gw.state == StartupState.INITIALIZING


    @pytest.mark.asyncio
    async def test_gateway_state_transition_to_failed_after_retries(self) -> None:
        gw = TransportGateway(dev_mode=True, port=0)
        assert gw.state == StartupState.INITIALIZING
        assert await gw.check_pa_status() is False
        assert gw.state == StartupState.FAILED


# ─────────────────────────────────────────────────────────────────
# FUT-07: send_prompt history wiring
# ─────────────────────────────────────────────────────────────────

import json as _json  # noqa: E402 (after class definitions for readability)
from services.ui_gateway.src.session_store import SessionStore  # noqa: E402
from services.ui_gateway.src.transport import PROMPT_HISTORY_MAX_BYTES  # noqa: E402


def _decode_prompt_request(data: bytes) -> dict[str, object]:
    """Decode a bare-JSON PROMPT_REQUEST frame and return its payload.

    send_prompt passes the raw bytes from encode_prompt_request() directly
    to transport.send() — the length prefix is added inside VsockTransport,
    NOT by the MessageFramer.  Our _CapturingTransport.send() captures the
    bytes before they hit VsockTransport, so they are plain JSON.
    """
    envelope: dict[str, object] = _json.loads(data.decode("utf-8"))
    return envelope["payload"]  # type: ignore[return-value]


class _CapturingTransport:
    """Fake VsockTransport that captures the bytes passed to send()."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.connected = True

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


class TestSendPromptHistory:
    """FUT-07: send_prompt includes prior history and excludes current prompt."""

    def _make_gateway_with_store(self) -> tuple[TransportGateway, SessionStore]:
        store = SessionStore(db_path=":memory:")
        gw = TransportGateway(session_store=store, dev_mode=True, port=0)
        gw._state = StartupState.OPERATIONAL
        return gw, store

    @pytest.mark.asyncio
    async def test_no_prior_turns_sends_empty_history(self) -> None:
        """With no prior turns in the store, history is an empty list."""
        gw, store = self._make_gateway_with_store()
        session_id = store.create_session("test")

        captured: list[_CapturingTransport] = []

        async def _fake_open() -> VsockTransport | None:
            t = _CapturingTransport()
            captured.append(t)
            return t  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        await gw.send_prompt(session_id, "first prompt")

        assert len(captured) == 1
        payload = _decode_prompt_request(captured[0].sent[0])
        assert payload["history"] == []

    @pytest.mark.asyncio
    async def test_prior_turns_included_in_history(self) -> None:
        """Prior approved turns are included; current prompt is NOT in history."""
        gw, store = self._make_gateway_with_store()
        session_id = store.create_session("test")

        # Seed two prior turns
        store.add_turn(session_id, "user", "My name is Alice", "N/A", [])
        store.add_turn(session_id, "assistant", "Nice to meet you, Alice!", "approved", [])

        captured: list[_CapturingTransport] = []

        async def _fake_open() -> VsockTransport | None:
            t = _CapturingTransport()
            captured.append(t)
            return t  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        await gw.send_prompt(session_id, "What is my name?")

        payload = _decode_prompt_request(captured[0].sent[0])
        history = payload["history"]

        # Both prior turns should be present
        assert any(e["role"] == "user" and "Alice" in e["content"] for e in history)  # type: ignore[index]
        assert any(e["role"] == "assistant" for e in history)  # type: ignore[index]

        # The current prompt must NOT appear in history
        assert not any("What is my name?" in e.get("content", "") for e in history)  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_denied_assistant_turns_excluded(self) -> None:
        """Denied assistant turns are excluded from history."""
        gw, store = self._make_gateway_with_store()
        session_id = store.create_session("test")

        store.add_turn(session_id, "user", "Say something bad", "N/A", [])
        store.add_turn(session_id, "assistant", "bad output", "denied", ["PII_DETECTED"])
        store.add_turn(session_id, "user", "Try again", "N/A", [])

        captured: list[_CapturingTransport] = []

        async def _fake_open() -> VsockTransport | None:
            t = _CapturingTransport()
            captured.append(t)
            return t  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        await gw.send_prompt(session_id, "Next prompt")

        payload = _decode_prompt_request(captured[0].sent[0])
        history = payload["history"]
        # Denied assistant turn must be absent
        assert not any(e.get("content") == "bad output" for e in history)  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_history_cap_drops_oldest_turns(self) -> None:
        """When serialized history exceeds PROMPT_HISTORY_MAX_BYTES, oldest turns are dropped."""
        gw, store = self._make_gateway_with_store()
        session_id = store.create_session("test")

        # Seed many large turns to exceed the byte cap
        big_content = "x" * 5000
        for i in range(20):
            store.add_turn(session_id, "user", f"turn-{i}: {big_content}", "N/A", [])
            store.add_turn(session_id, "assistant", f"reply-{i}: {big_content}", "approved", [])

        captured: list[_CapturingTransport] = []

        async def _fake_open() -> VsockTransport | None:
            t = _CapturingTransport()
            captured.append(t)
            return t  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        await gw.send_prompt(session_id, "Summary?")

        payload = _decode_prompt_request(captured[0].sent[0])
        history = payload["history"]

        # Serialized history must be within budget
        history_bytes = sum(len(_json.dumps(e, separators=(",", ":"))) for e in history)  # type: ignore[arg-type]
        assert history_bytes <= PROMPT_HISTORY_MAX_BYTES

        # Must keep most-recent turns (turn-19) and drop oldest
        recent_contents = [e["content"] for e in history]  # type: ignore[index]
        has_recent = any("turn-19" in c or "reply-19" in c for c in recent_contents)  # type: ignore[operator]
        assert has_recent, "Most-recent turns should be preserved after cap"

    @pytest.mark.asyncio
    async def test_no_session_store_sends_empty_history(self) -> None:
        """Gateway without a session_store sends empty history (no crash)."""
        gw = TransportGateway(session_store=None, dev_mode=True, port=0)
        gw._state = StartupState.OPERATIONAL
        session_id = "bare-session"

        captured: list[_CapturingTransport] = []

        async def _fake_open() -> VsockTransport | None:
            t = _CapturingTransport()
            captured.append(t)
            return t  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]
        await gw.send_prompt(session_id, "Hello without store")

        payload = _decode_prompt_request(captured[0].sent[0])
        assert payload["history"] == []

    @pytest.mark.asyncio
    async def test_oversized_history_plus_large_prompt_falls_back_to_empty_history(
        self,
    ) -> None:
        """Large history + large prompt: must not raise; falls back to history=[]."""
        from shared.ipc.protocol import DEFAULT_MAX_MESSAGE_BYTES

        gw, store = self._make_gateway_with_store()
        session_id = store.create_session("test")

        # Seed enough prior turns to fill ~39 KB of history (just under the
        # 40 KB history cap, so they survive the history-cap stage).
        # Each assistant turn ≈ ~200 bytes serialised; 190 turns ≈ 38 KB.
        for i in range(190):
            store.add_turn(session_id, "user", f"q{i}", "N/A", [])
            store.add_turn(session_id, "assistant", f"a{i}" + ("x" * 180), "approved", [])

        # Current prompt is 26 KB on its own.
        large_prompt = "p" * (26 * 1024)

        captured: list[_CapturingTransport] = []

        async def _fake_open() -> VsockTransport | None:
            t = _CapturingTransport()
            captured.append(t)
            return t  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]

        # Must not raise even though history + prompt together exceed 64 KB.
        await gw.send_prompt(session_id, large_prompt)

        assert len(captured) == 1
        raw = captured[0].sent[0]

        # Encoded message must be within the 64 KB envelope limit.
        assert len(raw) <= DEFAULT_MAX_MESSAGE_BYTES, (
            f"Encoded message is {len(raw)} bytes — exceeds {DEFAULT_MAX_MESSAGE_BYTES}"
        )

        # History must have been degraded to empty for this message.
        payload = _decode_prompt_request(raw)
        assert payload["history"] == [], (
            "Expected history=[] after fallback, "
            f"got {len(payload['history'])} entries"  # type: ignore[arg-type]
        )



class TestSendPromptAutoTitle:
    """send_prompt gives a session an auto-title from its first user prompt."""

    def _make_gateway_with_store(self) -> tuple[TransportGateway, SessionStore]:
        store = SessionStore(db_path=":memory:")
        gw = TransportGateway(session_store=store, dev_mode=True, port=0)
        gw._state = StartupState.OPERATIONAL
        return gw, store

    def _wire_capturing_open(self, gw: TransportGateway) -> None:
        async def _fake_open() -> VsockTransport | None:
            return _CapturingTransport()  # type: ignore[return-value]

        gw._open_prompt_transport = _fake_open  # type: ignore[method-assign]

    def _title_of(self, store: SessionStore, sid: str) -> str:
        return [s for s in store.list_sessions() if s.id == sid][0].title

    @pytest.mark.asyncio
    async def test_first_prompt_sets_title(self) -> None:
        """A session created with an empty title is named after its first prompt."""
        gw, store = self._make_gateway_with_store()
        sid = store.create_session()  # empty title
        assert self._title_of(store, sid) == ""

        self._wire_capturing_open(gw)
        await gw.send_prompt(sid, "How do I bake sourdough bread")

        title = self._title_of(store, sid)
        assert title.startswith("How do I bake s…")
        assert " · " in title  # the date separator

    @pytest.mark.asyncio
    async def test_title_not_overwritten_by_second_prompt(self) -> None:
        """The auto-title is set once - a later prompt does not change it."""
        gw, store = self._make_gateway_with_store()
        sid = store.create_session()

        self._wire_capturing_open(gw)
        await gw.send_prompt(sid, "First question about cats")
        title_after_first = self._title_of(store, sid)
        await gw.send_prompt(sid, "Totally different second question")

        assert self._title_of(store, sid) == title_after_first
        assert title_after_first.startswith("First question …")

    @pytest.mark.asyncio
    async def test_rename_title_survives_first_prompt(self) -> None:
        """A title set via /rename before the first prompt is not clobbered."""
        gw, store = self._make_gateway_with_store()
        sid = store.create_session()
        store.update_session_title(sid, "My Custom Name")

        self._wire_capturing_open(gw)
        await gw.send_prompt(sid, "Some first prompt text")

        assert self._title_of(store, sid) == "My Custom Name"
