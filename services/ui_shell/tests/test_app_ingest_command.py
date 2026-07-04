"""
Tests for the /ingest interception in BlarAIApp.action_submit_prompt (#655).

The TUI mirrors the backend dispatcher's prompt-arc integration
(``dispatcher._m_prompt``): the gateway's ``handle_ingest_command`` is called
BEFORE the ``send_prompt`` arc; a non-None reply is rendered as ONE
informational message (no token streaming, no PGOV panel) and the model is
never invoked.  Covers:

  - /ingest is intercepted: handler called, send_prompt NOT called, the
    informational reply is displayed, input re-enabled.
  - Informational turns never trigger the PGOV denial panel.
  - Normal prompts are unaffected: handler returns None and the unchanged
    send_prompt arc runs.
  - A stub gateway WITHOUT the method keeps the old arc (getattr guard).
  - A handler exception surfaces as a Fail-Closed message, never a crash.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ui_shell.src.app import BlarAIApp


INFO_TEXT = (
    "**Ingest preview — pending your approval**\n\n"
    "- Title: A Real Headline\n\nBody text here.\n\n"
    "Reply **/approve** or **/reject**."
)


# ---------------------------------------------------------------------------
# Helpers — minimal stubs for Textual widgets (test_app_load_command pattern)
# ---------------------------------------------------------------------------


class _DisplayStub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, text: str) -> None:
        self.lines.append(text)

    def start_new_response(self) -> None:
        pass

    def append_token(self, token: object) -> None:
        pass


class _PGOVPanelStub:
    def __init__(self) -> None:
        self.denials: list[object] = []

    def hide(self) -> None:
        pass

    def display_denial(self, result: object) -> None:
        self.denials.append(result)


class _InputStub:
    def __init__(self, value: str = "") -> None:
        self.value: str = value
        self.disabled: bool = False
        self._focused: bool = False

    def focus(self) -> None:
        self._focused = True


class _LegacyGateway:
    """A gateway WITHOUT handle_ingest_command — the pre-#655 surface.

    A real class (not MagicMock) so the getattr guard genuinely sees the
    attribute as absent.
    """

    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    async def send_prompt(self, session_id: str, text: str) -> str:
        self.prompts.append((session_id, text))
        return "req-legacy"

    def stream_tokens(self, session_id: str) -> "_AsyncIterStub":
        return _async_iter([])

    def get_pgov_result(self, request_id: str) -> MagicMock:
        return MagicMock(approved=True, sanitized_text="ok", reason_codes=[])

    def flush_tool_call_buffer(self, pgov_approved: bool) -> list:
        return []


async def _run_submit(
    app: BlarAIApp,
    prompt_value: str,
    session_id: str = "sess-test",
) -> tuple[_DisplayStub, _PGOVPanelStub, _InputStub]:
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

    return display, pgov, prompt_input


def _make_app(gateway: object) -> BlarAIApp:
    app = BlarAIApp(gateway=gateway)
    app._operational = True
    return app


def _ingest_aware_gateway(info_text: str | None) -> MagicMock:
    """MagicMock gateway + an awaitable ingest surface (AsyncMock)."""
    gateway = MagicMock()
    gateway.handle_ingest_command = AsyncMock(return_value=info_text)
    return gateway


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestInterception:
    """action_submit_prompt intercepts ingest commands before send_prompt."""

    @pytest.mark.asyncio
    async def test_ingest_intercepted_send_prompt_not_called(self) -> None:
        gateway = _ingest_aware_gateway(INFO_TEXT)
        gateway.send_prompt = AsyncMock()

        app = _make_app(gateway)
        display, _, _ = await _run_submit(app, "/ingest pasted article text")

        gateway.handle_ingest_command.assert_awaited_once_with(
            "sess-test", "/ingest pasted article text"
        )
        gateway.send_prompt.assert_not_called()
        # The informational reply is rendered (Rich-escaped, single message).
        assert any("Ingest preview" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_user_command_echoed_with_reply(self) -> None:
        gateway = _ingest_aware_gateway(INFO_TEXT)
        app = _make_app(gateway)
        display, _, _ = await _run_submit(app, "/approve")

        assert any("You:" in line and "/approve" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_informational_turn_does_not_trigger_pgov_panel(self) -> None:
        gateway = _ingest_aware_gateway(INFO_TEXT)
        app = _make_app(gateway)
        _, pgov, _ = await _run_submit(app, "/ingest pasted text")

        assert pgov.denials == []  # never PGOV-validated, never a panel

    @pytest.mark.asyncio
    async def test_input_re_enabled_after_interception(self) -> None:
        gateway = _ingest_aware_gateway(INFO_TEXT)
        app = _make_app(gateway)
        _, _, prompt_input = await _run_submit(app, "/ingest pasted text")

        assert prompt_input.disabled is False
        assert prompt_input._focused is True

    @pytest.mark.asyncio
    async def test_handler_exception_is_fail_closed_message(self) -> None:
        gateway = _ingest_aware_gateway(None)
        gateway.handle_ingest_command = AsyncMock(side_effect=RuntimeError("boom"))
        gateway.send_prompt = AsyncMock()

        app = _make_app(gateway)
        display, _, prompt_input = await _run_submit(app, "/ingest pasted text")

        assert any("Fail-Closed" in line for line in display.lines)
        gateway.send_prompt.assert_not_called()
        assert prompt_input.disabled is False
        assert prompt_input._focused is True


class TestNormalPromptPassthrough:
    """Non-ingest prompts run the unchanged send_prompt arc."""

    @pytest.mark.asyncio
    async def test_none_reply_runs_the_unchanged_prompt_arc(self) -> None:
        gateway = _ingest_aware_gateway(None)  # handler present, declines
        gateway.send_prompt = AsyncMock(return_value="req-1")
        gateway.stream_tokens = MagicMock(return_value=_async_iter([]))
        gateway.get_pgov_result = MagicMock(
            return_value=MagicMock(approved=True, sanitized_text="ok", reason_codes=[])
        )
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app = _make_app(gateway)
        await _run_submit(app, "Hello, BlarAI!")

        gateway.handle_ingest_command.assert_awaited_once_with(
            "sess-test", "Hello, BlarAI!"
        )
        gateway.send_prompt.assert_called_once_with("sess-test", "Hello, BlarAI!")

    @pytest.mark.asyncio
    async def test_gateway_without_ingest_surface_keeps_old_arc(self) -> None:
        """No handle_ingest_command — /ingest flows to the model untouched
        (the getattr guard holds; pre-#655 behavior preserved)."""
        gateway = _LegacyGateway()
        app = _make_app(gateway)
        _, _, prompt_input = await _run_submit(app, "/ingest pasted text")

        assert gateway.prompts == [("sess-test", "/ingest pasted text")]
        assert prompt_input.disabled is False


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
