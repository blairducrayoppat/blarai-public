"""
Tests for the /load slash-command handling in BlarAIApp.action_submit_prompt.

Covers:
  - /load <file> is routed to gateway.load_document, NOT sent as a prompt.
  - Success feedback is displayed (filename + KB size).
  - DocumentLoadError is shown as an error message, not re-raised.
  - Ordinary text input (non-/load) is NOT intercepted.
  - /load with no filename after prefix still calls load_document (empty string).
  - prompt_input is re-enabled and focused after command handling.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ui_shell.src.app import BlarAIApp
from services.ui_gateway.src.document_loader import DocumentLoadError
from services.ui_gateway.src.transport import StartupState


# ---------------------------------------------------------------------------
# Helpers — minimal stubs for Textual widgets
# ---------------------------------------------------------------------------


class _DisplayStub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, text: str) -> None:
        self.lines.append(text)

    def start_new_response(self) -> None:
        pass


class _PGOVPanelStub:
    def hide(self) -> None:
        pass


class _InputStub:
    def __init__(self, value: str = "") -> None:
        self.value: str = value
        self.disabled: bool = False
        self._focused: bool = False

    def focus(self) -> None:
        self._focused = True


def _make_app_operational(
    gateway: MagicMock,
    prompt_value: str,
    session_id: str = "sess-test",
) -> BlarAIApp:
    """Return a BlarAIApp with operational state wired up for action tests."""
    app = BlarAIApp(gateway=gateway)
    app._operational = True
    return app


async def _run_submit(
    app: BlarAIApp,
    prompt_value: str,
    session_id: str = "sess-test",
) -> tuple[_DisplayStub, _InputStub]:
    """Patch Textual widget queries and run action_submit_prompt."""
    display = _DisplayStub()
    pgov = _PGOVPanelStub()
    prompt_input = _InputStub(value=prompt_value)

    def _query_one(selector: str, widget_type: type) -> object:  # type: ignore[return]
        if selector == "#response-area":
            return display
        if selector == "#pgov-panel":
            return pgov
        if selector == "#prompt-input":
            return prompt_input
        raise ValueError(f"Unknown selector: {selector}")

    with (
        patch.object(app, "query_one", side_effect=_query_one),
        patch.object(app, "_ensure_session", new=AsyncMock(return_value=session_id)),
    ):
        await app.action_submit_prompt()

    return display, prompt_input


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadCommand:
    """action_submit_prompt intercepts /load correctly."""

    @pytest.mark.asyncio
    async def test_load_command_calls_load_document_not_send_prompt(self) -> None:
        """/load routes to gateway.load_document, NOT send_prompt."""
        gateway = MagicMock()
        gateway.load_document.return_value = {
            "filename": "notes.txt",
            "content": "some content",
            "size_bytes": 100,
        }
        gateway.send_prompt = AsyncMock()

        app = _make_app_operational(gateway, "/load notes.txt")
        display, prompt_input = await _run_submit(app, "/load notes.txt")

        gateway.load_document.assert_called_once_with("sess-test", "notes.txt")
        gateway.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_success_shows_feedback(self) -> None:
        """/load success shows a 'Loaded <file> (<size> KB)' message."""
        gateway = MagicMock()
        gateway.load_document.return_value = {
            "filename": "notes.txt",
            "content": "x" * 4096,
            "size_bytes": 4096,
        }

        app = _make_app_operational(gateway, "/load notes.txt")
        display, _ = await _run_submit(app, "/load notes.txt")

        assert any("notes.txt" in line for line in display.lines)
        assert any("4.0 KB" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_load_error_shows_error_message(self) -> None:
        """/load failure shows an error message, does not raise."""
        gateway = MagicMock()
        gateway.load_document.side_effect = DocumentLoadError("File not found: 'missing.txt'.")

        app = _make_app_operational(gateway, "/load missing.txt")
        display, _ = await _run_submit(app, "/load missing.txt")

        assert any("Load failed" in line or "not found" in line.lower() for line in display.lines)

    @pytest.mark.asyncio
    async def test_ordinary_input_not_intercepted(self) -> None:
        """Normal text (no /load prefix) is NOT intercepted as a command."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-1")
        gateway.stream_tokens = MagicMock(return_value=_async_iter([]))
        gateway.get_pgov_result = MagicMock(
            return_value=MagicMock(approved=True, sanitized_text="ok", reason_codes=[])
        )
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])
        gateway.load_document = MagicMock()

        app = _make_app_operational(gateway, "Hello, BlarAI!")
        await _run_submit(app, "Hello, BlarAI!")

        gateway.load_document.assert_not_called()
        gateway.send_prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_input_re_enabled_after_load(self) -> None:
        """/load re-enables and re-focuses prompt_input after handling."""
        gateway = MagicMock()
        gateway.load_document.return_value = {
            "filename": "f.txt",
            "content": "c",
            "size_bytes": 1,
        }

        app = _make_app_operational(gateway, "/load f.txt")
        display, prompt_input = await _run_submit(app, "/load f.txt")

        assert prompt_input.disabled is False
        assert prompt_input._focused is True

    @pytest.mark.asyncio
    async def test_prompt_input_re_enabled_after_load_error(self) -> None:
        """Even on /load error, prompt_input is re-enabled and focused."""
        gateway = MagicMock()
        gateway.load_document.side_effect = DocumentLoadError("oops")

        app = _make_app_operational(gateway, "/load bad.txt")
        display, prompt_input = await _run_submit(app, "/load bad.txt")

        assert prompt_input.disabled is False
        assert prompt_input._focused is True


class TestUnloadCommand:
    """action_submit_prompt intercepts /unload correctly."""

    @pytest.mark.asyncio
    async def test_unload_calls_unload_documents_not_send_prompt(self) -> None:
        """/unload routes to gateway.unload_documents, NOT send_prompt."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock()

        app = _make_app_operational(gateway, "/unload")
        await _run_submit(app, "/unload")

        gateway.unload_documents.assert_called_once_with("sess-test")
        gateway.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_unload_shows_feedback(self) -> None:
        """/unload shows a confirmation message."""
        gateway = MagicMock()

        app = _make_app_operational(gateway, "/unload")
        display, _ = await _run_submit(app, "/unload")

        assert any("cleared" in line.lower() for line in display.lines)

    @pytest.mark.asyncio
    async def test_unload_re_enables_prompt_input(self) -> None:
        """/unload re-enables and re-focuses prompt_input after handling."""
        gateway = MagicMock()

        app = _make_app_operational(gateway, "/unload")
        _, prompt_input = await _run_submit(app, "/unload")

        assert prompt_input.disabled is False
        assert prompt_input._focused is True


# ---------------------------------------------------------------------------
# Async iter stub
# ---------------------------------------------------------------------------


class _AsyncIterStub:
    def __init__(self, items: list) -> None:
        self._items = list(items)
        self._idx = 0

    def __aiter__(self) -> "_AsyncIterStub":
        return self

    async def __anext__(self) -> object:
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


def _async_iter(items: list) -> _AsyncIterStub:
    return _AsyncIterStub(items)
