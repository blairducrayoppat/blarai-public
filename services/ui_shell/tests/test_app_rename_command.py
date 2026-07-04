"""
Tests for the /rename slash-command handling in BlarAIApp.action_submit_prompt.

Covers:
  - /rename <title> routes to session_store.update_session_title, NOT send_prompt.
  - Success shows a confirmation and refreshes the session panel.
  - /rename with no title shows a usage message and does not rename.
  - /rename with no active session shows a 'no session' message.
  - '/renamer ...' (not the command) is NOT intercepted as a rename.
  - prompt_input is re-enabled and focused after command handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ui_shell.src.app import BlarAIApp


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


class _PanelStub:
    """Stand-in for SessionPanel — exposes active_session_id and refresh_list."""

    def __init__(self, active_session_id: str | None) -> None:
        self.active_session_id = active_session_id
        self.refresh_count = 0

    async def refresh_list(self) -> None:
        self.refresh_count += 1


def _make_app(gateway: MagicMock, store: object) -> BlarAIApp:
    app = BlarAIApp(gateway=gateway, session_store=store)  # type: ignore[arg-type]
    app._operational = True
    return app


async def _run_submit(
    app: BlarAIApp,
    prompt_value: str,
    panel: _PanelStub,
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
        if selector == "#session-panel":
            return panel
        raise ValueError(f"Unknown selector: {selector}")

    with patch.object(app, "query_one", side_effect=_query_one):
        await app.action_submit_prompt()

    return display, prompt_input


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenameCommand:
    """action_submit_prompt intercepts /rename correctly."""

    @pytest.mark.asyncio
    async def test_rename_calls_update_session_title_not_send_prompt(self) -> None:
        """/rename routes to store.update_session_title, NOT send_prompt."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id="sess-1")
        await _run_submit(app, "/rename My Project", panel)

        store.update_session_title.assert_called_once_with("sess-1", "My Project")
        gateway.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_rename_success_refreshes_panel_and_confirms(self) -> None:
        """A successful /rename refreshes the panel and shows a confirmation."""
        gateway = MagicMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id="sess-1")
        display, _ = await _run_submit(app, "/rename Budget Notes", panel)

        assert panel.refresh_count == 1
        assert any("Budget Notes" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_rename_with_no_title_shows_usage(self) -> None:
        """'/rename' alone shows a usage hint and does not rename."""
        gateway = MagicMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id="sess-1")
        display, _ = await _run_submit(app, "/rename", panel)

        store.update_session_title.assert_not_called()
        assert any("Usage" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_rename_with_only_whitespace_title_shows_usage(self) -> None:
        """'/rename    ' (trailing whitespace only) is treated as no title."""
        gateway = MagicMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id="sess-1")
        display, _ = await _run_submit(app, "/rename    ", panel)

        store.update_session_title.assert_not_called()
        assert any("Usage" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_rename_with_no_active_session(self) -> None:
        """/rename with no active session shows a 'no session' message."""
        gateway = MagicMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id=None)
        display, _ = await _run_submit(app, "/rename Whatever", panel)

        store.update_session_title.assert_not_called()
        assert any("No active session" in line for line in display.lines)

    @pytest.mark.asyncio
    async def test_renamer_prefix_not_intercepted(self) -> None:
        """'/renamer ...' is NOT the /rename command — it must not rename."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id="sess-1")
        # _ensure_session -> None makes the ordinary prompt path bail early,
        # so we do not need full gateway stream stubs.
        with patch.object(app, "_ensure_session", new=AsyncMock(return_value=None)):
            await _run_submit(app, "/renamer is not a command", panel)

        store.update_session_title.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_input_re_enabled_after_rename(self) -> None:
        """/rename re-enables and re-focuses prompt_input after handling."""
        gateway = MagicMock()
        store = MagicMock()

        app = _make_app(gateway, store)
        panel = _PanelStub(active_session_id="sess-1")
        _, prompt_input = await _run_submit(app, "/rename Done", panel)

        assert prompt_input.disabled is False
        assert prompt_input._focused is True
