"""
Typed-guard locks for the gateway-side IPC dataclass decoders (#803).

``StreamToken.from_dict`` (the anchored transport.py site) and its twin
``GatewayPGOVResult.from_dict`` historically bare-coerced untrusted payload
fields: a container ``token_index`` raised ``TypeError`` (no documented
contract), and — the worst swallow on this boundary — a truthy container in
``approved`` bool-coerced to ``True``, a governance verdict flowing APPROVED
off malformed input.  These locks pin the #803 contract:

  - MALFORMED: a present-but-mistyped field raises ``ValueError`` with the
    deterministic content-free fingerprint (never the value).
  - WELL-FORMED: round-trips are byte-identical to the pre-guard behavior;
    absent fields keep their safe (Fail-Closed) defaults.
  - WIRING: ``stream_tokens`` fails CLOSED on a malformed frame — the stream
    dies with ``ValueError`` and no PGOV verdict is cached (get_pgov_result
    falls back to default-deny), instead of yielding coerced tokens or
    caching a coerced approval.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.transport import (
    GatewayPGOVResult,
    StartupState,
    StreamToken,
    TransportGateway,
)
from shared.ipc import MessageFramer, MessageType

_framer = MessageFramer()


class _MockTransport:
    """Synchronous receive-from-list transport stub (no real socket)."""

    def __init__(self, messages: list[bytes | None]) -> None:
        self._iter = iter(messages)
        self.connected = True

    def receive(self) -> bytes | None:
        return next(self._iter, None)


def _gateway(messages: list[bytes | None]) -> TransportGateway:
    gw = TransportGateway()
    gw._state = StartupState.OPERATIONAL
    gw._transport = _MockTransport(messages)  # type: ignore[assignment]
    return gw


# ─────────────────────────────────────────────────────────────────
# StreamToken.from_dict (the anchored transport.py:153 site)
# ─────────────────────────────────────────────────────────────────


class TestStreamTokenGuards:
    def test_container_token_index_raises_valueerror(self) -> None:
        """The anchored defect: bare ``int()`` raised TypeError on a container."""
        with pytest.raises(ValueError, match="'token_index' must be int"):
            StreamToken.from_dict({"token": "x", "token_index": ["evil"]})

    def test_numeric_string_token_index_raises(self) -> None:
        with pytest.raises(ValueError, match="'token_index' must be int"):
            StreamToken.from_dict({"token_index": "5"})

    def test_bool_token_index_raises(self) -> None:
        with pytest.raises(ValueError, match="'token_index' must be int"):
            StreamToken.from_dict({"token_index": True})

    def test_container_token_raises_not_swallowed(self) -> None:
        """``str({"t": 1})`` used to flow on as the literal dict repr."""
        with pytest.raises(ValueError, match="'token' must be str"):
            StreamToken.from_dict({"token": {"t": 1}})

    def test_container_is_tool_call_raises_not_truthy(self) -> None:
        with pytest.raises(ValueError, match="'is_tool_call' must be bool"):
            StreamToken.from_dict({"is_tool_call": [1]})

    def test_int_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="'session_id' must be str"):
            StreamToken.from_dict({"session_id": 7})

    def test_well_formed_round_trip_unchanged(self) -> None:
        original = StreamToken(
            token="hello", token_index=3, is_final=True, is_tool_call=False,
            session_id="sess-1", is_thinking=True,
        )
        assert StreamToken.from_dict(original.to_dict()) == original

    def test_missing_fields_keep_safe_defaults(self) -> None:
        t = StreamToken.from_dict({})
        assert t.token == ""
        assert t.token_index == 0
        assert t.is_final is False
        assert t.is_tool_call is False
        assert t.session_id == ""
        assert t.is_thinking is False


# ─────────────────────────────────────────────────────────────────
# GatewayPGOVResult.from_dict (the same-file twin)
# ─────────────────────────────────────────────────────────────────


class TestGatewayPGOVResultGuards:
    def test_container_approved_raises_not_approved(self) -> None:
        """The fail-open swallow: ``bool(["x"])`` used to read as APPROVED.
        A malformed governance verdict must FAIL the decode."""
        with pytest.raises(ValueError, match="'approved' must be bool"):
            GatewayPGOVResult.from_dict({"approved": ["x"]})

    def test_str_approved_raises(self) -> None:
        with pytest.raises(ValueError, match="'approved' must be bool"):
            GatewayPGOVResult.from_dict({"approved": "true"})

    def test_container_sanitized_text_raises(self) -> None:
        with pytest.raises(ValueError, match="'sanitized_text' must be str"):
            GatewayPGOVResult.from_dict({"sanitized_text": ["redacted"]})

    def test_str_reason_codes_raises_not_char_exploded(self) -> None:
        """``list("ABC")`` used to silently become ``['A', 'B', 'C']``."""
        with pytest.raises(ValueError, match="'reason_codes' must be list"):
            GatewayPGOVResult.from_dict({"reason_codes": "ABC"})

    def test_mistyped_reason_code_element_raises_with_index(self) -> None:
        with pytest.raises(ValueError, match=r"'reason_codes\[1\]' must be str"):
            GatewayPGOVResult.from_dict({"reason_codes": ["PII_DETECTED", 5]})

    def test_well_formed_round_trip_unchanged(self) -> None:
        original = GatewayPGOVResult(
            approved=False, sanitized_text="redacted",
            reason_codes=["PII_DETECTED"], request_id="req-1",
        )
        restored = GatewayPGOVResult.from_dict(original.to_dict())
        assert restored.approved == original.approved
        assert restored.sanitized_text == original.sanitized_text
        assert restored.reason_codes == original.reason_codes
        assert restored.request_id == original.request_id

    def test_missing_fields_keep_fail_closed_defaults(self) -> None:
        r = GatewayPGOVResult.from_dict({})
        assert r.approved is False  # Fail-Closed
        assert r.sanitized_text == ""
        assert r.reason_codes == []
        assert r.request_id == ""


# ─────────────────────────────────────────────────────────────────
# stream_tokens wiring — Fail-Closed on a malformed frame
# ─────────────────────────────────────────────────────────────────


class TestStreamTokensFailClosed:
    """The loop-level posture: a mistyped payload FAILS the stream (the peer
    is broken or hostile — no partial/coerced response), it never yields a
    coerced token or caches a coerced verdict."""

    @pytest.mark.asyncio
    async def test_malformed_stream_token_fails_the_stream(self) -> None:
        valid = _framer.encode_stream_token(
            token="ok", token_index=0, is_final=False, is_tool_call=False,
            session_id="sess", request_id="",
        )
        malformed = _framer.encode(
            MessageType.STREAM_TOKEN,
            {"token": "x", "token_index": ["evil"], "session_id": "sess"},
            "",
        )
        gw = _gateway([valid, malformed, None])
        received: list[StreamToken] = []
        with pytest.raises(ValueError, match="'token_index' must be int"):
            async for token in gw.stream_tokens("sess"):
                received.append(token)
        # The well-formed token before the malformed frame was delivered.
        assert [t.token for t in received] == ["ok"]

    @pytest.mark.asyncio
    async def test_malformed_pgov_fails_stream_and_caches_nothing(self) -> None:
        """A container ``approved`` used to cache an APPROVED verdict; it now
        kills the stream and leaves get_pgov_result at default-deny."""
        malformed_pgov = _framer.encode(
            MessageType.PGOV_RESULT,
            {"approved": ["x"], "sanitized_text": "t", "reason_codes": []},
            "req-1",
        )
        gw = _gateway([malformed_pgov, None])
        with pytest.raises(ValueError, match="'approved' must be bool"):
            async for _ in gw.stream_tokens("sess"):
                pass  # pragma: no cover — no token precedes the bad frame
        result = gw.get_pgov_result("req-1")
        assert result.approved is False  # Fail-Closed fallback, nothing cached

    @pytest.mark.asyncio
    async def test_well_formed_pgov_still_cached_via_strict_path(self) -> None:
        """The inline construction now routes through from_dict — the happy
        path must be behavior-identical (approved cached, envelope-resolved
        request_id kept)."""
        pgov = _framer.encode_pgov_result(
            approved=True, sanitized_text="fine", reason_codes=[],
            request_id="req-9",
        )
        complete = _framer.encode_generation_complete(request_id="req-9")
        gw = _gateway([pgov, complete, None])
        tokens = [t async for t in gw.stream_tokens("sess")]
        assert tokens == []
        cached = gw.get_pgov_result("req-9")
        assert cached.approved is True
        assert cached.request_id == "req-9"
        assert cached.sanitized_text == "fine"
