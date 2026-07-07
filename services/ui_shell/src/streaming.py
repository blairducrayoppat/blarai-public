"""
Streaming Display Widget (P1.12, ADR-009)
=========================================
Renders streaming tokens from the Transport Gateway into the
response area. Supports:
  - Incremental token append (no full re-render)
  - Tool-call block rendering (buffered, displayed atomically)
  - Cursor blink indicator while streaming
  - Scroll-back history up to RESPONSE_SCROLL_BACK_LINES
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.widgets import RichLog

from .constants import RESPONSE_SCROLL_BACK_LINES

if TYPE_CHECKING:
    from services.ui_gateway.src.transport import StreamToken


class StreamingDisplay(RichLog):
    """Real-time streaming token display.

    Inherits from Textual's RichLog which already handles efficient
    append-only rendering and configurable scroll-back.
    """

    DEFAULT_CSS = """
    StreamingDisplay {
        height: 1fr;
        border: solid $primary;
        padding: 1;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            max_lines=RESPONSE_SCROLL_BACK_LINES,
            wrap=True,
            highlight=False,
            markup=True,
            **kwargs,  # type: ignore[arg-type]
        )
        self._buffer: str = ""
        self._streaming: bool = False

    # ── Public API ────────────────────────────────────────────────

    def append_token(self, token: StreamToken) -> None:
        """Append a single streaming token to the display.

        Parameters
        ----------
        token : StreamToken
            Token from the Transport Gateway's stream_tokens() generator.
        """
        if token.is_tool_call:
            # Tool-call tokens are buffered at the gateway level and
            # delivered atomically — render as a distinct block. The [dim]
            # framing is the widget's own intentional markup; the tool name
            # is model-derived data, so it is escaped — it must not inject
            # markup of its own.
            self._append_text(
                f"\n[dim]⚙ tool-call:[/dim] {escape(token.token)}\n"
            )
            return

        self._streaming = True
        # Model output is DATA, not markup. Escape it before buffering so
        # square brackets render literally — otherwise RichLog (markup=True)
        # consumes "[...]" as a Rich markup tag. That is what made the
        # redaction marker "[phone number withheld ...]" vanish on screen.
        self._append_text(escape(token.token))

        if token.is_final:
            self._streaming = False

    def _append_text(self, text: str) -> None:
        """Append text to the mutable response buffer and re-render."""
        if not text:
            return
        self._buffer += text
        self._render_buffer()

    def _render_buffer(self) -> None:
        """Render the full mutable buffer to the response pane."""
        self.clear()
        for line in self._buffer.split("\n"):
            self.write(line)

    def write_line(self, text: str) -> None:
        """Write a complete line (for boot status, errors, etc.)."""
        self._append_text(f"{text}\n")

    def start_new_response(self) -> None:
        """Prepare for a new assistant response."""
        self._streaming = False
        self._append_text("─" * 40 + "\n")

    def clear_display(self) -> None:
        """Clear all content."""
        self._buffer = ""
        self.clear()
        self._streaming = False

    @property
    def is_streaming(self) -> bool:
        """Whether tokens are currently being appended."""
        return self._streaming
