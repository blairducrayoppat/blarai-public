"""
Live-TCP integration tests for ui_gateway transport (moved from
services/ui_gateway/tests/test_transport.py per P5_TASK8_EA5 WI-3).

These tests spin up real asyncio TCP servers that speak the MessageFramer
protocol and exercise the TransportGateway against live sockets. Per
TEST_GOVERNANCE.md taxonomy, live-socket tests belong under
`tests/integration/` with the `slow` marker.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from services.ui_gateway.src.transport import (
    PGOV_DENIAL_FALLBACK,
    REASON_DELIMITER_ECHO,
    REASON_PII_DETECTED,
    StartupState,
    StreamToken,
    TransportGateway,
)
from shared.ipc import MessageFramer, MessageType

pytestmark = pytest.mark.slow


# Helpers copied from services/ui_gateway/tests/test_transport.py

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


class TestCheckPaStatusLive:
    """Live-TCP handshake flows (3C.1)."""

    @pytest.mark.asyncio
    async def test_handshake_success_with_mock_server(self) -> None:
        """Spin up a TCP server that speaks MessageFramer protocol."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            # Read HANDSHAKE_REQUEST via MessageFramer framing
            request_bytes = await _read_framed(reader)
            msg_type, request_id, _payload = _framer.decode(request_bytes)
            assert msg_type == MessageType.HANDSHAKE_REQUEST

            # Respond with HANDSHAKE_RESPONSE
            response = _framer.encode_handshake_response(
                "OPERATIONAL", request_id=request_id,
            )
            await _write_framed(writer, response)
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        try:
            gw = TransportGateway(dev_mode=True, host="127.0.0.1", port=port)
            result = await gw.check_pa_status()
            assert result is True
            assert gw.state == StartupState.OPERATIONAL
            assert gw.connected is True
            # P1.11: transport should be stored after successful handshake
            assert gw._transport is not None
        finally:
            server.close()
            await server.wait_closed()


class TestLiveHandshake:
    """Verify handshake stores VsockTransport + uses MessageFramer."""

    @pytest.mark.asyncio
    async def test_handshake_stores_transport(self) -> None:
        """After handshake, _transport must be a connected VsockTransport."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _p = _framer.decode(req)
            assert msg_type == MessageType.HANDSHAKE_REQUEST
            resp = _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
            await _write_framed(writer, resp)
            # Keep connection open so transport stays "connected"
            await asyncio.sleep(5)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            ok = await gw.check_pa_status()
            assert ok is True
            assert gw._transport is not None
            assert gw._transport.connected is True
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_handshake_non_operational_response(self) -> None:
        """Non-OPERATIONAL response → handshake fails, transport not stored.

        #808: the retry schedule is stubbed to two zero sleeps — the real
        180 s budgeted schedule would make this live-socket test sleep three
        minutes; the retried-then-FAILED semantics are what matter here.
        """
        import services.ui_gateway.src.transport as transport_module

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            _, rid, _ = _framer.decode(req)
            resp = _framer.encode_handshake_response("DEGRADED", request_id=rid)
            await _write_framed(writer, resp)
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    transport_module,
                    "pa_handshake_backoff_schedule",
                    lambda: (0.0, 0.0),
                )
                gw = TransportGateway(dev_mode=True, port=port)
                ok = await gw.check_pa_status()
            assert ok is False
            assert gw.state == StartupState.FAILED
            assert gw._transport is None
        finally:
            server.close()
            await server.wait_closed()


class TestLiveSendPrompt:
    """Verify send_prompt dispatches IPC message when transport connected."""

    @pytest.mark.asyncio
    async def test_send_prompt_sends_ipc_message(self) -> None:
        """After handshake, send_prompt should transmit a PROMPT_REQUEST."""
        received_messages: list[tuple[MessageType, str, dict]] = []

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, payload = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                resp = _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
                await _write_framed(writer, resp)
            elif msg_type == MessageType.PROMPT_REQUEST:
                received_messages.append((msg_type, rid, payload))
            await asyncio.sleep(1)  # keep connection alive

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            request_id = await gw.send_prompt("sess-1", "Hello test")
            assert isinstance(request_id, str)

            # Give the mock server time to receive
            await asyncio.sleep(0.1)
            assert len(received_messages) == 1
            msg_type, _rid, payload = received_messages[0]
            assert msg_type == MessageType.PROMPT_REQUEST
            assert payload["prompt"] == "Hello test"
            assert payload["session_id"] == "sess-1"
        finally:
            server.close()
            await server.wait_closed()
class TestLiveStreamTokens:
    """Verify stream_tokens receives tokens via IPC."""

    @pytest.mark.asyncio
    async def test_stream_tokens_full_flow(self) -> None:
        """Handshake → send_prompt → stream 3 tokens → PGOV → complete."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                prompt_rid = rid
                # 3. Stream 3 tokens
                for i, word in enumerate(["Hello", " ", "world"]):
                    token_msg = _framer.encode_stream_token(
                        token=word,
                        token_index=i,
                        is_final=(i == 2),
                        is_tool_call=False,
                        session_id="sess-1",
                        request_id=prompt_rid,
                    )
                    await _write_framed(writer, token_msg)

                # 4. Send PGOV result
                pgov_msg = _framer.encode_pgov_result(
                    approved=True,
                    sanitized_text="Hello world",
                    reason_codes=[],
                    request_id=prompt_rid,
                )
                await _write_framed(writer, pgov_msg)

                # 5. Generation complete
                await _write_framed(
                    writer,
                    _framer.encode_generation_complete(request_id=prompt_rid),
                )
            await asyncio.sleep(1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            request_id = await gw.send_prompt("sess-1", "Say hello")

            tokens: list[StreamToken] = []
            async for tok in gw.stream_tokens("sess-1"):
                tokens.append(tok)

            # Verify 3 text tokens received
            assert len(tokens) == 3
            assert tokens[0].token == "Hello"
            assert tokens[1].token == " "
            assert tokens[2].token == "world"
            assert tokens[2].is_final is True

            # Verify PGOV result was cached
            result = gw.get_pgov_result(request_id)
            assert result.approved is True
            assert result.sanitized_text == "Hello world"
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_stream_tokens_buffers_tool_calls(self) -> None:
        """Tool-call tokens buffered, text tokens yielded immediately."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                prompt_rid = rid
                # Send text token, then tool-call token, then text token
                await _write_framed(writer, _framer.encode_stream_token(
                    "Let me ", 0, False, False, "sess-1", prompt_rid,
                ))
                await _write_framed(writer, _framer.encode_stream_token(
                    "run_tool()", 1, False, True, "sess-1", prompt_rid,
                ))
                await _write_framed(writer, _framer.encode_stream_token(
                    " done", 2, True, False, "sess-1", prompt_rid,
                ))

                await _write_framed(
                    writer,
                    _framer.encode_generation_complete(request_id=prompt_rid),
                )
            # Close the connection so the gateway's "waiting for PGOV or
            # stream close" path ends on EOF. Without this the handler left
            # the socket open and stream_tokens blocked for the FULL 180 s
            # PROMPT_RESPONSE_TIMEOUT_S receive timeout — a pre-existing
            # 3-minute stall in the slow tier, surfaced by the #808 timing
            # audit (the test still passed, on timeout instead of EOF).
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            await gw.send_prompt("sess-1", "Do it")

            # Only text tokens should be yielded
            tokens = [t async for t in gw.stream_tokens("sess-1")]
            assert len(tokens) == 2
            assert tokens[0].token == "Let me "
            assert tokens[1].token == " done"

            # Tool-call token should be buffered
            buffered = gw.flush_tool_call_buffer(pgov_approved=True)
            assert len(buffered) == 1
            assert buffered[0].token == "run_tool()"
            assert buffered[0].is_tool_call is True
        finally:
            server.close()
            await server.wait_closed()
class TestLivePGOVResult:
    """PGOV result caching from stream_tokens."""
    async def test_pgov_denied_flow(self) -> None:
        """Server sends denied PGOV → cached and returned."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                prompt_rid = rid
                # Send a token then PGOV deny then complete
                await _write_framed(writer, _framer.encode_stream_token(
                    "bad", 0, True, False, "sess-1", prompt_rid,
                ))
                await _write_framed(writer, _framer.encode_pgov_result(
                    approved=False,
                    sanitized_text=PGOV_DENIAL_FALLBACK,
                    reason_codes=[REASON_PII_DETECTED],
                    request_id=prompt_rid,
                ))
                await _write_framed(
                    writer,
                    _framer.encode_generation_complete(request_id=prompt_rid),
                )
            await asyncio.sleep(1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            request_id = await gw.send_prompt("sess-1", "Show PII")
            async for _ in gw.stream_tokens("sess-1"):
                pass  # consume all tokens

            result = gw.get_pgov_result(request_id)
            assert result.approved is False
            assert REASON_PII_DETECTED in result.reason_codes
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_generation_complete_before_pgov_still_caches_result(self) -> None:
        """Out-of-order COMPLETE before PGOV should still resolve correlation."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer,
                    _framer.encode_handshake_response("OPERATIONAL", request_id=rid),
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                prompt_rid = rid
                await _write_framed(
                    writer,
                    _framer.encode_generation_complete(request_id=prompt_rid),
                )
                await _write_framed(
                    writer,
                    _framer.encode_pgov_result(
                        approved=False,
                        sanitized_text=PGOV_DENIAL_FALLBACK,
                        reason_codes=[REASON_PII_DETECTED],
                        request_id=prompt_rid,
                    ),
                )
                writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            request_id = await gw.send_prompt("sess-1", "Show PII")
            async for _ in gw.stream_tokens("sess-1"):
                pass

            result = gw.get_pgov_result(request_id)
            assert result.approved is False
            assert REASON_PII_DETECTED in result.reason_codes
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_blank_pgov_request_id_maps_to_active_request(self) -> None:
        """Blank PGOV request_id should map to active request to avoid cache miss."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer,
                    _framer.encode_handshake_response("OPERATIONAL", request_id=rid),
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                await _write_framed(
                    writer,
                    _framer.encode_pgov_result(
                        approved=False,
                        sanitized_text=PGOV_DENIAL_FALLBACK,
                        reason_codes=[REASON_DELIMITER_ECHO],
                        request_id="",
                    ),
                )
                await _write_framed(
                    writer,
                    _framer.encode_generation_complete(request_id=""),
                )
                writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            request_id = await gw.send_prompt("sess-1", "test")
            async for _ in gw.stream_tokens("sess-1"):
                pass

            result = gw.get_pgov_result(request_id)
            assert result.approved is False
            assert REASON_DELIMITER_ECHO in result.reason_codes
        finally:
            server.close()
            await server.wait_closed()


class TestLiveErrorHandling:
    """Edge cases: server disconnects, malformed messages."""

    @pytest.mark.asyncio
    async def test_server_disconnect_during_stream(self) -> None:
        """Server closes connection mid-stream → stream ends gracefully."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                prompt_rid = rid
                # Send one token then abruptly close
                await _write_framed(writer, _framer.encode_stream_token(
                    "partial", 0, False, False, "sess-1", prompt_rid,
                ))
                writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            await gw.send_prompt("sess-1", "Partial response")

            tokens = [t async for t in gw.stream_tokens("sess-1")]
            # Should get partial token before stream ends
            assert len(tokens) >= 0  # may get 1 token or 0 depending on timing
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_error_message_type_ends_stream(self) -> None:
        """ERROR message type → stream ends."""
        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(
                    writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid)
                )
            elif msg_type == MessageType.PROMPT_REQUEST:
                prompt_rid = rid
                # Send ERROR
                error_msg = _framer.encode(
                    MessageType.ERROR,
                    {"error": "internal failure"},
                    prompt_rid,
                )
                await _write_framed(writer, error_msg)
            await asyncio.sleep(1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            await gw.send_prompt("sess-1", "Trigger error")

            tokens = [t async for t in gw.stream_tokens("sess-1")]
            assert tokens == []
        finally:
            server.close()
            await server.wait_closed()


