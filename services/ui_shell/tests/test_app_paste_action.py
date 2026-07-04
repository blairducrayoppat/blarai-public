"""
Tests for BlarAIApp.action_paste_clipboard (Ctrl+V).

The action reads the system clipboard via pyperclip and inserts at the
prompt-input's cursor position. Failure paths surface to the response
area rather than crashing the TUI.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.ui_shell.src.app import BlarAIApp
from services.ui_shell.src.constants import PROMPT_MAX_CHARS


class _DisplayStub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, text: str) -> None:
        self.lines.append(text)


class _InputStub:
    def __init__(self) -> None:
        self.inserted: list[str] = []
        self._focused: bool = False

    def insert_text_at_cursor(self, text: str) -> None:
        self.inserted.append(text)

    def focus(self) -> None:
        self._focused = True


def _make_app() -> BlarAIApp:
    gateway = MagicMock()
    app = BlarAIApp(gateway=gateway)
    app._operational = True
    return app


def _patch_widgets(app: BlarAIApp) -> tuple[_DisplayStub, _InputStub]:
    display = _DisplayStub()
    prompt = _InputStub()

    def _query_one(selector: str, widget_type: type) -> object:  # type: ignore[return]
        if selector == "#response-area":
            return display
        if selector == "#prompt-input":
            return prompt
        raise ValueError(f"Unknown selector: {selector}")

    app.query_one = _query_one  # type: ignore[assignment]
    return display, prompt


class TestPasteAction:
    @pytest.mark.asyncio
    async def test_clipboard_text_inserted_at_cursor(self) -> None:
        app = _make_app()
        display, prompt = _patch_widgets(app)
        with patch("pyperclip.paste", return_value="hello clipboard"):
            await app.action_paste_clipboard()
        assert prompt.inserted == ["hello clipboard"]
        assert prompt._focused is True
        assert display.lines == []

    @pytest.mark.asyncio
    async def test_empty_clipboard_is_silent_noop(self) -> None:
        app = _make_app()
        display, prompt = _patch_widgets(app)
        with patch("pyperclip.paste", return_value=""):
            await app.action_paste_clipboard()
        assert prompt.inserted == []
        assert display.lines == []  # no error noise on empty clipboard

    @pytest.mark.asyncio
    async def test_oversize_clipboard_truncated_to_prompt_max(self) -> None:
        app = _make_app()
        display, prompt = _patch_widgets(app)
        oversize = "x" * (PROMPT_MAX_CHARS + 500)
        with patch("pyperclip.paste", return_value=oversize):
            await app.action_paste_clipboard()
        assert len(prompt.inserted[0]) == PROMPT_MAX_CHARS

    @pytest.mark.asyncio
    async def test_clipboard_read_error_surfaces_to_display(self) -> None:
        app = _make_app()
        display, prompt = _patch_widgets(app)
        with patch("pyperclip.paste", side_effect=RuntimeError("no clipboard")):
            await app.action_paste_clipboard()
        assert prompt.inserted == []
        assert len(display.lines) == 1
        assert "Paste failed" in display.lines[0]
        assert "no clipboard" in display.lines[0]

    @pytest.mark.asyncio
    async def test_pyperclip_missing_surfaces_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _make_app()
        display, prompt = _patch_widgets(app)

        # Simulate pyperclip being uninstalled by removing it from sys.modules
        # and making `import pyperclip` raise ImportError.
        import builtins
        real_import = builtins.__import__

        def _no_pyperclip(name: str, *args: object, **kwargs: object) -> object:
            if name == "pyperclip":
                raise ImportError("No module named 'pyperclip'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_pyperclip)
        await app.action_paste_clipboard()
        assert prompt.inserted == []
        assert len(display.lines) == 1
        assert "pyperclip" in display.lines[0].lower()
