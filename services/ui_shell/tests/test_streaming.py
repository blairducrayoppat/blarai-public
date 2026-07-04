"""
Tests for services.ui_shell.src.streaming (P1.12).

Tests the StreamingDisplay widget's non-Textual logic — specifically
the token-append state machine and the is_streaming property.

NOTE: Full Textual compositor tests (actual rendering) would require
App.run_test() and are deferred to integration tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.ui_gateway.src.transport import StreamToken
from services.ui_shell.src.streaming import StreamingDisplay
from services.ui_shell.src.constants import RESPONSE_SCROLL_BACK_LINES


def _make_token(
    text: str = "hello",
    index: int = 0,
    is_final: bool = False,
    is_tool_call: bool = False,
) -> StreamToken:
    return StreamToken(
        token=text,
        token_index=index,
        is_final=is_final,
        is_tool_call=is_tool_call,
        session_id="test-session",
    )


class TestStreamingDisplayConstants:
    """Verify constant defaults."""

    def test_scroll_back_limit(self) -> None:
        assert RESPONSE_SCROLL_BACK_LINES == 10_000


class TestStreamingDisplayLogic:
    """Test append_token state tracking.

    The RichLog base class is mocked to avoid Textual runtime deps.
    """

    @pytest.fixture()
    def display(self) -> StreamingDisplay:
        """Create a StreamingDisplay with mocked parent init."""
        with patch.object(StreamingDisplay, "__init__", lambda self, **kw: None):
            d = StreamingDisplay.__new__(StreamingDisplay)
            d._buffer = ""
            d._streaming = False
            # Mock RichLog methods used by mutable buffer rendering
            d.clear = MagicMock()  # type: ignore[assignment]
            d.write = MagicMock()  # type: ignore[assignment]
            return d

    def test_not_streaming_initially(self, display: StreamingDisplay) -> None:
        assert display.is_streaming is False

    def test_append_token_sets_streaming(self, display: StreamingDisplay) -> None:
        display.append_token(_make_token("hi"))
        assert display.is_streaming is True
        assert display._buffer == "hi"

    def test_final_token_clears_streaming(self, display: StreamingDisplay) -> None:
        display.append_token(_make_token("hi", is_final=False))
        display.append_token(_make_token(".", is_final=True))
        assert display.is_streaming is False
        assert display._buffer == "hi."
        display.write.assert_called()

    def test_tool_call_token_written_directly(self, display: StreamingDisplay) -> None:
        display.append_token(_make_token("fn()", is_tool_call=True))
        assert "fn()" in display._buffer
        display.write.assert_called()

    def test_newline_flushes_lines(self, display: StreamingDisplay) -> None:
        display.append_token(_make_token("line1\nline2"))
        display.write.assert_called()
        assert display._buffer == "line1\nline2"

    def test_start_new_response_resets(self, display: StreamingDisplay) -> None:
        display._buffer = "partial"
        display._streaming = True
        display.start_new_response()
        assert display._buffer.endswith("─" * 40 + "\n")
        assert display.is_streaming is False

    def test_clear_display(self, display: StreamingDisplay) -> None:
        display._buffer = "partial"
        display._streaming = True
        display.clear_display()
        display.clear.assert_called_once()
        assert display._buffer == ""
        assert display.is_streaming is False

    def test_model_token_markup_is_escaped(self, display: StreamingDisplay) -> None:
        """Model output is data, not markup. Square brackets must be escaped
        so a redaction marker like '[phone number withheld]' renders
        literally instead of being consumed as a Rich markup tag."""
        display.append_token(_make_token("see [phone number withheld] now"))
        # The bracket is escaped (backslash-prefixed) → RichLog renders it
        # literally; the human-readable words survive intact.
        assert "\\[phone number withheld]" in display._buffer
        assert "phone number withheld" in display._buffer

    def test_tool_call_token_name_is_escaped(self, display: StreamingDisplay) -> None:
        """A tool name is model-derived data — escape it — but keep the
        widget's own [dim] framing markup."""
        display.append_token(_make_token("weird[name]", is_tool_call=True))
        assert "\\[name]" in display._buffer
        assert "[dim]" in display._buffer  # widget's own markup is preserved

    def test_plain_token_unchanged_by_escape(self, display: StreamingDisplay) -> None:
        """Escaping is a no-op for ordinary text with no markup characters."""
        display.append_token(_make_token("just normal words 123"))
        assert display._buffer == "just normal words 123"


# ─────────────────────────────────────────────────────────────────
# WI-11: _streaming flag state-transition tests
# ─────────────────────────────────────────────────────────────────


class TestStreamingFlagTransitions:
    """WI-11: _streaming flag is set/cleared at the correct lifecycle moments."""

    @pytest.fixture()
    def display(self) -> StreamingDisplay:
        with patch.object(StreamingDisplay, "__init__", lambda self, **kw: None):
            d = StreamingDisplay.__new__(StreamingDisplay)
            d._buffer = ""
            d._streaming = False
            d.clear = MagicMock()
            d.write = MagicMock()
            return d

    def test_streaming_flag_true_during_non_final_tokens(
        self, display: StreamingDisplay
    ) -> None:
        """_streaming stays True after five non-final token appends."""
        for i in range(5):
            display.append_token(_make_token(f"t{i}", index=i, is_final=False))
        assert display.is_streaming is True

    def test_streaming_flag_false_after_final_token(
        self, display: StreamingDisplay
    ) -> None:
        """_streaming flips to False upon receiving is_final=True."""
        for i in range(3):
            display.append_token(_make_token(f"t{i}", index=i, is_final=False))
        assert display.is_streaming is True
        display.append_token(_make_token("end", index=3, is_final=True))
        assert display.is_streaming is False

    def test_streaming_flag_false_after_clear_display(
        self, display: StreamingDisplay
    ) -> None:
        """clear_display() resets _streaming to False and clears buffer."""
        display.append_token(_make_token("x", is_final=False))
        assert display.is_streaming is True
        display.clear_display()
        assert display.is_streaming is False
        assert display._buffer == ""

    def test_streaming_flag_false_after_start_new_response(
        self, display: StreamingDisplay
    ) -> None:
        """start_new_response() resets _streaming to False."""
        display.append_token(_make_token("partial", is_final=False))
        assert display.is_streaming is True
        display.start_new_response()
        assert display.is_streaming is False
