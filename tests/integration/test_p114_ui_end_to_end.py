"""
P1.14 — End-to-End UX Validation Tests
=======================================

Validation scope:
  A. Transport Gateway API
  B. Session CRUD via SessionStore
  C. StreamToken Flow
  D. Boot-Phase-3 Gating
  E. PGOV Display

All tests run in dev_mode=True over TCP loopback and mock model behavior.
"""

from __future__ import annotations

import asyncio
import struct
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Entire module uses real socket I/O; excluded from default runs.
pytestmark = pytest.mark.slow

from services.ui_gateway.src import transport as transport_module
from services.ui_gateway.src.constants import STREAM_TOKEN_BUFFER_LIMIT
from services.ui_gateway.src.session_store import SessionStore
from services.ui_gateway.src.transport import (
    GatewayPGOVResult,
    StartupState,
    StreamToken,
    TransportGateway,
)
from services.ui_shell.src.app import BlarAIApp
from services.ui_shell.src.constants import PGOV_REASON_LABELS
from services.ui_shell.src.pgov_display import PGOVPanel
from shared.ipc import MessageFramer, MessageType


_HEADER_FMT = "!I"
_HEADER_SZ = struct.calcsize(_HEADER_FMT)
_framer = MessageFramer()


async def _read_framed(reader: asyncio.StreamReader) -> bytes:
    hdr = await reader.readexactly(_HEADER_SZ)
    (length,) = struct.unpack(_HEADER_FMT, hdr)
    return await reader.readexactly(length)


async def _write_framed(writer: asyncio.StreamWriter, data: bytes) -> None:
    writer.write(struct.pack(_HEADER_FMT, len(data)) + data)
    await writer.drain()


class _AsyncIter:
    def __init__(self, items: list[StreamToken]) -> None:
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> StreamToken:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        value = self._items[self._index]
        self._index += 1
        return value


class _DisplayStub:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.tokens: list[StreamToken] = []

    def write_line(self, text: str) -> None:
        self.lines.append(text)

    def start_new_response(self) -> None:
        self.lines.append("<new>")

    def append_token(self, token: StreamToken) -> None:
        self.tokens.append(token)

    def clear_display(self) -> None:
        self.lines.clear()
        self.tokens.clear()


class _PromptStub:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.disabled: bool = False
        self.focused: bool = False

    def focus(self) -> None:
        self.focused = True


class _SessionPanelStub:
    def __init__(self, session_id: str | None = None) -> None:
        self.active_session_id = session_id


class _PGOVPanelStub:
    def __init__(self) -> None:
        self.displayed: list[GatewayPGOVResult] = []
        self.hidden_calls = 0

    def hide(self) -> None:
        self.hidden_calls += 1

    def display_denial(self, result: GatewayPGOVResult) -> None:
        self.displayed.append(result)


class _GatewayBootSuccess:
    def __init__(self) -> None:
        self.state = StartupState.INITIALIZING

    async def check_pa_status(self) -> bool:
        self.state = StartupState.HANDSHAKING
        await asyncio.sleep(0)
        self.state = StartupState.OPERATIONAL
        return True

    def reset(self) -> None:
        self.state = StartupState.INITIALIZING


# ===========================================================================
# Group A: Transport Gateway API
# ===========================================================================


class TestP114GroupATransportGatewayAPI:
    @pytest.mark.asyncio
    async def test_stream_tokens_yields_streamtoken_sequence(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            elif msg_type == MessageType.PROMPT_REQUEST:
                await _write_framed(
                    writer,
                    _framer.encode_stream_token("A", 0, False, False, "sess-a2", rid),
                )
                await _write_framed(
                    writer,
                    _framer.encode_stream_token("B", 1, True, False, "sess-a2", rid),
                )
                await _write_framed(writer, _framer.encode_generation_complete(request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            assert await gw.check_pa_status() is True
            await gw.send_prompt("sess-a2", "go")

            tokens = [tok async for tok in gw.stream_tokens("sess-a2")]
            assert len(tokens) == 2
            assert all(isinstance(tok, StreamToken) for tok in tokens)
            assert [tok.token for tok in tokens] == ["A", "B"]
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_stream_tokens_final_token_is_final_true(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            elif msg_type == MessageType.PROMPT_REQUEST:
                await _write_framed(
                    writer,
                    _framer.encode_stream_token("done", 0, True, False, "sess-a3", rid),
                )
                await _write_framed(writer, _framer.encode_generation_complete(request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            assert await gw.check_pa_status() is True
            await gw.send_prompt("sess-a3", "go")
            tokens = [tok async for tok in gw.stream_tokens("sess-a3")]
            assert len(tokens) == 1
            assert tokens[-1].is_final is True
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_check_pa_status_true_with_echo_server(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            _, rid, _ = _framer.decode(req)
            await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            assert await gw.check_pa_status() is True
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_check_pa_status_false_when_no_pa(self) -> None:
        gw = TransportGateway(dev_mode=True, port=0)
        assert await gw.check_pa_status() is False
        assert gw.state == StartupState.FAILED
# ===========================================================================
# Group B: Session CRUD via SessionStore
# ===========================================================================


class TestP114GroupCStreamTokenFlow:
    @pytest.mark.asyncio
    async def test_tool_call_tokens_buffered_until_pgov_clearance(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            elif msg_type == MessageType.PROMPT_REQUEST:
                await _write_framed(writer, _framer.encode_stream_token("visible", 0, False, False, "sess-c1", rid))
                await _write_framed(writer, _framer.encode_stream_token("tool()", 1, False, True, "sess-c1", rid))
                await _write_framed(writer, _framer.encode_stream_token("done", 2, True, False, "sess-c1", rid))
                await _write_framed(writer, _framer.encode_generation_complete(request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            await gw.send_prompt("sess-c1", "run")
            tokens = [tok async for tok in gw.stream_tokens("sess-c1")]
            assert [t.token for t in tokens] == ["visible", "done"]
            buffered = gw.flush_tool_call_buffer(pgov_approved=True)
            assert len(buffered) == 1
            assert buffered[0].token == "tool()"
        finally:
            server.close()
            await server.wait_closed()
    async def test_normal_tokens_flow_without_buffering(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            elif msg_type == MessageType.PROMPT_REQUEST:
                await _write_framed(writer, _framer.encode_stream_token("hello", 0, False, False, "sess-c4", rid))
                await _write_framed(writer, _framer.encode_stream_token(" world", 1, True, False, "sess-c4", rid))
                await _write_framed(writer, _framer.encode_generation_complete(request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            await gw.check_pa_status()
            await gw.send_prompt("sess-c4", "go")
            tokens = [tok async for tok in gw.stream_tokens("sess-c4")]
            assert [t.token for t in tokens] == ["hello", " world"]
            assert gw.flush_tool_call_buffer(True) == []
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_stream_token_buffer_limit_respected(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            msg_type, rid, _ = _framer.decode(req)
            if msg_type == MessageType.HANDSHAKE_REQUEST:
                await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            elif msg_type == MessageType.PROMPT_REQUEST:
                for idx in range(3):
                    await _write_framed(
                        writer,
                        _framer.encode_stream_token(str(idx), idx, False, False, "sess-c5", rid),
                    )
                await _write_framed(writer, _framer.encode_generation_complete(request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(transport_module, "STREAM_TOKEN_BUFFER_LIMIT", 2)
                gw = TransportGateway(dev_mode=True, port=port)
                await gw.check_pa_status()
                await gw.send_prompt("sess-c5", "go")
                tokens = [tok async for tok in gw.stream_tokens("sess-c5")]
                assert len(tokens) == 2
                assert [tok.token for tok in tokens] == ["0", "1"]
        finally:
            server.close()
            await server.wait_closed()
# ===========================================================================
# Group D: Boot-Phase-3 Gating
# ===========================================================================


class TestP114GroupDBootPhase3Gating:
    @pytest.mark.asyncio
    async def test_no_prompt_dispatched_until_operational(self) -> None:
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock()
        app = BlarAIApp(gateway=gateway)
        app._operational = False
        await app.action_submit_prompt()
        gateway.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_after_operational_prompt_dispatches_correctly(self) -> None:
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-d2")
        gateway.stream_tokens = MagicMock(return_value=_AsyncIter([]))
        gateway.get_pgov_result = MagicMock(
            return_value=GatewayPGOVResult(approved=True, sanitized_text="ok", reason_codes=[], request_id="req-d2")
        )
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app = BlarAIApp(gateway=gateway)
        app._operational = True

        prompt = _PromptStub("hello")
        display = _DisplayStub()
        panel = _PGOVPanelStub()
        sessions = _SessionPanelStub("sess-d2")

        def _query_one(selector: str, _type: object = None) -> object:
            mapping = {
                "#prompt-input": prompt,
                "#response-area": display,
                "#pgov-panel": panel,
                "#session-panel": sessions,
            }
            return mapping[selector]

        app.query_one = _query_one  # type: ignore[method-assign]
        await app.action_submit_prompt()

        gateway.send_prompt.assert_awaited_once_with("sess-d2", "hello")

    @pytest.mark.asyncio
    async def test_gateway_state_transition_to_operational(self) -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req = await _read_framed(reader)
            _, rid, _ = _framer.decode(req)
            await _write_framed(writer, _framer.encode_handshake_response("OPERATIONAL", request_id=rid))
            await asyncio.sleep(0.1)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            gw = TransportGateway(dev_mode=True, port=port)
            assert gw.state == StartupState.INITIALIZING
            assert await gw.check_pa_status() is True
            assert gw.state == StartupState.OPERATIONAL
        finally:
            server.close()
            await server.wait_closed()
    async def test_boot_log_written_on_state_transitions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        app = BlarAIApp(gateway=_GatewayBootSuccess())
        display = _DisplayStub()
        prompt = _PromptStub()

        def _query_one(selector: str, _type: object = None) -> object:
            mapping = {
                "#response-area": display,
                "#prompt-input": prompt,
            }
            return mapping[selector]

        app.query_one = _query_one  # type: ignore[method-assign]
        await app._poll_boot_status()

        boot_log = tmp_path / "BlarAI" / "boot.log"
        assert boot_log.exists()
        text = boot_log.read_text(encoding="utf-8")
        assert "INITIALIZING" in text
        assert "HANDSHAKING" in text
        assert "OPERATIONAL" in text


# ===========================================================================
# Group E: PGOV Display
# ===========================================================================


class TestP114GroupEPGOVDisplay:
    def _capture_panel_text(self, panel: PGOVPanel) -> dict[str, str]:
        captured = {"text": ""}

        def _update(text: str) -> None:
            captured["text"] = text

        panel.update = _update  # type: ignore[method-assign]
        return captured

    @pytest.mark.asyncio
    async def test_approved_result_does_not_trigger_pgov_panel_display(self) -> None:
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-e5")
        gateway.stream_tokens = MagicMock(return_value=_AsyncIter([]))
        gateway.get_pgov_result = MagicMock(
            return_value=GatewayPGOVResult(
                approved=True,
                sanitized_text="approved text",
                reason_codes=[],
                request_id="req-e5",
            )
        )
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app = BlarAIApp(gateway=gateway)
        app._operational = True

        prompt = _PromptStub("hello")
        display = _DisplayStub()
        panel = _PGOVPanelStub()
        sessions = _SessionPanelStub("sess-e5")

        def _query_one(selector: str, _type: object = None) -> object:
            mapping = {
                "#prompt-input": prompt,
                "#response-area": display,
                "#pgov-panel": panel,
                "#session-panel": sessions,
            }
            return mapping[selector]

        app.query_one = _query_one  # type: ignore[method-assign]
        await app.action_submit_prompt()
        assert panel.displayed == []
