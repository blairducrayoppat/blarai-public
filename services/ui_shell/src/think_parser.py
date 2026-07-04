"""
Think-tag parser for streaming model output (ISS-2, EDD §8.1).

Public API: ``parse_think_segments(text: str) -> list[tuple[str, bool]]``

Partial-tag semantic: the parser treats the full ``text`` argument as the
complete buffer received so far.  An incomplete open- or close-tag at the
*very end* of the buffer (e.g. ``"<thi"`` or ``"</thi"``) is returned as
plain text so the caller gets deterministic output on every call.  The
caller (WI-3 ``_render_buffer``) simply passes the full accumulated buffer
on each invocation; no internal state is kept between calls.

See EDD §8.1 for the state-machine design.
"""

from __future__ import annotations

import logging
from enum import Enum, auto

_LOG = logging.getLogger(__name__)

_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"


class _State(Enum):
    OUTSIDE = auto()
    IN_THINK = auto()


def parse_think_segments(text: str) -> list[tuple[str, bool]]:
    """Parse ``text`` into a list of ``(segment, is_think)`` tuples.

    Parameters
    ----------
    text:
        The full accumulated output buffer.  May contain zero, one, or many
        ``<think>...</think>`` blocks, with or without surrounding plain text.

    Returns
    -------
    list[tuple[str, bool]]
        Each tuple is ``(segment_text, is_think)``.  Segments are emitted in
        order.  Empty-string segments are possible (e.g. ``<think></think>``)
        and are included so callers can decide whether to skip them.

    Notes
    -----
    * Nested ``<think>`` inside an already-open think block is treated as
      literal text within the current think segment; a warning is logged.
    * An unclosed ``<think>`` at the end of ``text`` causes the trailing
      content to be emitted as a think segment.
    * Partial open/close tags at the end of ``text`` are emitted as plain
      text (deterministic per-call semantic; no cross-call state).
    """
    segments: list[tuple[str, bool]] = []
    state: _State = _State.OUTSIDE

    # Working cursors into ``text``.
    pos: int = 0
    # Accumulator for the segment currently being built.
    current: list[str] = []

    length = len(text)

    def _flush(is_think: bool) -> None:
        """Emit whatever is in ``current`` as a finished segment."""
        segments.append(("".join(current), is_think))
        current.clear()

    while pos < length:
        # ── Look for the next relevant tag depending on current state ──
        if state is _State.OUTSIDE:
            idx = text.find(_OPEN_TAG, pos)
            if idx == -1:
                # No more open tags — rest of buffer is plain text.
                current.append(text[pos:])
                break
            # Plain text before the tag.
            if idx > pos:
                current.append(text[pos:idx])
            _flush(is_think=False)
            state = _State.IN_THINK
            pos = idx + len(_OPEN_TAG)

        else:  # state is _State.IN_THINK
            # Scan for either another open tag (nested) or the close tag.
            close_idx = text.find(_CLOSE_TAG, pos)
            open_idx = text.find(_OPEN_TAG, pos)

            # Determine which comes first.
            has_close = close_idx != -1
            has_open = open_idx != -1

            if has_close and (not has_open or close_idx <= open_idx):
                # Close tag arrives before any nested open tag.
                current.append(text[pos:close_idx])
                _flush(is_think=True)
                state = _State.OUTSIDE
                pos = close_idx + len(_CLOSE_TAG)

            elif has_open and (not has_close or open_idx < close_idx):
                # Nested open tag — reject; treat as literal text, log warning.
                _LOG.warning(
                    "parse_think_segments: nested <think> at offset %d — "
                    "treating as literal text within current think segment.",
                    open_idx,
                )
                # Include text up to and including the inner tag as think text.
                current.append(text[pos : open_idx + len(_OPEN_TAG)])
                pos = open_idx + len(_OPEN_TAG)

            else:
                # Neither close nor nested open found — unclosed think block.
                # Emit remaining buffer as a think segment.
                current.append(text[pos:])
                break

    # Flush remaining accumulator.  We flush unconditionally when in IN_THINK
    # state (handles unclosed <think> and open-tag-at-end cases, including
    # when current is empty).  In OUTSIDE state we only flush if current is
    # non-empty (avoids spurious trailing empty segments after a clean close).
    if state is _State.IN_THINK or current:
        _flush(is_think=(state is _State.IN_THINK))

    # Edge case: empty buffer with no tags produces no segments above; emit a
    # single empty OUTSIDE segment so callers always get at least one tuple.
    if not segments:
        segments.append(("", False))

    return segments
