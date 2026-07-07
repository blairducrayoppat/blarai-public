"""
Baseline snapshot test — StreamingDisplay pre-think-tag-rendering state (ISS-2 WI-1).

Captures the CURRENT (pre-WI-3) rendering of a token stream that contains raw
``<think>...</think>`` markup characters.  This golden SVG locks the
"before" state so that WI-4's post-rendering snapshot can be diffed against it
and regressions in WI-3 can be caught automatically.

Usage:
    # First run — capture golden SVG:
    pytest services/ui_shell/tests/test_baseline_streaming_snapshot.py --snapshot-update

    # Subsequent runs — verify no drift:
    pytest services/ui_shell/tests/test_baseline_streaming_snapshot.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from textual.app import App, ComposeResult
from textual.containers import Vertical

from services.ui_shell.src.streaming import StreamingDisplay

if TYPE_CHECKING:
    from textual.pilot import Pilot

# Token sequence that represents the PRE-rendering state:
# raw <think>...</think> markup passes through to the widget unchanged.
# WI-3 will later intercept this in _render_buffer; WI-1 baseline captures
# what the user sees BEFORE that integration.
_TOKEN_SEQUENCE = [
    "<think>",
    "This is internal reasoning content.",
    " It should eventually be dim-italic.",
    "</think>",
    "This is the visible response text.",
]


class _BaselineApp(App[None]):
    """Minimal standalone Textual app for WI-1 snapshot baseline.

    Does NOT import from services.ui_gateway — gateway deps are absent
    in the test environment.  Only the StreamingDisplay widget is mounted.
    """

    DEFAULT_CSS = """
    _BaselineApp {
        background: $surface;
    }
    StreamingDisplay {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield StreamingDisplay(id="streaming-display")


async def _populate_display(pilot: "Pilot") -> None:
    """Inject the known token sequence into the StreamingDisplay widget.

    Called by snap_compare's run_before hook after the Textual compositor
    has mounted the app but before the screenshot is taken.
    """
    display = pilot.app.query_one("#streaming-display", StreamingDisplay)
    # Simulate the token stream arriving character-by-character.
    # _append_text accumulates into _buffer and calls _render_buffer() each time,
    # matching the real streaming path used by append_token().
    for token in _TOKEN_SEQUENCE:
        display._append_text(token)
    # Give the compositor one tick to process the writes.
    await pilot.pause()


def test_baseline_streaming_snapshot(snap_compare: Callable) -> None:
    """Baseline: raw <think>...</think> characters render verbatim (pre-WI-3).

    This snapshot is the golden "before" state.  After WI-3 integrates
    think-tag rendering, WI-4 will add a SEPARATE snapshot that captures
    the dim-italic rendering — this test continues to verify the pre-state
    is not accidentally re-introduced.

    First run (--snapshot-update): captures the SVG golden file.
    Subsequent runs: asserts zero diff against the golden.
    """
    assert snap_compare(
        _BaselineApp(),
        run_before=_populate_display,
        terminal_size=(100, 30),
    )
