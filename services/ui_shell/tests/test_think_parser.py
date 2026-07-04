"""
Unit tests for ``services.ui_shell.src.think_parser.parse_think_segments``.

Coverage categories per EDD §8.2 G2:
  (a) Complete <think>X</think>
  (b) Multiple think blocks in one buffer
  (c) <think> at buffer start
  (d) <think> at buffer end (no closing tag yet)
  (e) Partial-tag-across-boundary simulation — sequential calls with growing buffer
  (f) Empty <think></think>
  (g) Unclosed <think>X (truncated)
  (h) Non-think text only
  (i) Nested <think><think>X</think></think> rejection
"""

from __future__ import annotations

import pytest

from services.ui_shell.src.think_parser import parse_think_segments


# ── (a) Complete <think>X</think> ────────────────────────────────────────────


def test_complete_think_block_only() -> None:
    """Single complete think block with no surrounding text."""
    result = parse_think_segments("<think>reasoning</think>")
    assert result == [("", False), ("reasoning", True)]


def test_complete_think_block_with_surrounding_text() -> None:
    """Complete think block embedded between plain text."""
    result = parse_think_segments("before <think>thought</think> after")
    assert result == [("before ", False), ("thought", True), (" after", False)]


# ── (b) Multiple think blocks ─────────────────────────────────────────────────


def test_multiple_think_blocks() -> None:
    """Two think blocks separated by plain text."""
    result = parse_think_segments("A<think>one</think>B<think>two</think>C")
    assert result == [
        ("A", False),
        ("one", True),
        ("B", False),
        ("two", True),
        ("C", False),
    ]


def test_multiple_adjacent_think_blocks() -> None:
    """Two think blocks with no text between them."""
    result = parse_think_segments("<think>alpha</think><think>beta</think>")
    assert result == [
        ("", False),
        ("alpha", True),
        ("", False),
        ("beta", True),
    ]


# ── (c) <think> at buffer start ──────────────────────────────────────────────


def test_think_at_start_with_trailing_text() -> None:
    """Open tag at position 0; trailing text after close."""
    result = parse_think_segments("<think>inner</think>tail")
    # Leading empty OUTSIDE segment then the think segment then the tail.
    assert result == [("", False), ("inner", True), ("tail", False)]


def test_think_at_start_no_trailing_text() -> None:
    """Open tag at position 0; nothing after close."""
    result = parse_think_segments("<think>inner</think>")
    assert result == [("", False), ("inner", True)]


# ── (d) <think> at buffer end ────────────────────────────────────────────────


def test_think_open_at_buffer_end_no_close() -> None:
    """Buffer ends right after the open tag — no close tag present."""
    result = parse_think_segments("prelude<think>")
    # "prelude" → OUTSIDE segment; empty string after open tag → think segment
    assert result == [("prelude", False), ("", True)]


def test_think_open_mid_buffer_no_close() -> None:
    """Open tag in the middle; close tag never arrives."""
    result = parse_think_segments("text<think>reasoning so far")
    assert result == [("text", False), ("reasoning so far", True)]


# ── (e) Partial-tag-across-boundary simulation ───────────────────────────────


def test_partial_open_tag_then_complete_buffer() -> None:
    """
    Simulates streaming: first call has incomplete open tag; second call has
    the full accumulated buffer including the complete tag.

    Because parse_think_segments is stateless and takes the full buffer, the
    caller passes growing accumulated text on each call.
    """
    # Call 1: buffer so far — incomplete tag prefix, emitted as plain text.
    result1 = parse_think_segments("<thi")
    assert result1 == [("<thi", False)]

    # Call 2: accumulated buffer now contains the complete open tag + content.
    result2 = parse_think_segments("<think>hello world</think>")
    assert result2 == [("", False), ("hello world", True)]


def test_partial_close_tag_then_complete_buffer() -> None:
    """
    Simulates streaming where close tag arrives across two token deliveries.

    Call 1: open tag + content + partial close tag (incomplete).
    Call 2: full accumulated buffer with complete close tag.
    """
    # Call 1: partial close tag at end — "</thi" is not a complete </think>.
    result1 = parse_think_segments("<think>content</thi")
    # The partial "</thi" is not recognized as a close tag; entire remainder
    # (including the partial suffix) is emitted as a think segment.
    assert result1 == [("", False), ("content</thi", True)]

    # Call 2: full buffer with complete close.
    result2 = parse_think_segments("<think>content</think>")
    assert result2 == [("", False), ("content", True)]


# ── (f) Empty <think></think> ────────────────────────────────────────────────


def test_empty_think_block() -> None:
    """Empty think block emits an empty-string think segment."""
    result = parse_think_segments("<think></think>")
    assert result == [("", False), ("", True)]


def test_empty_think_block_with_text_on_both_sides() -> None:
    """Empty think block surrounded by text."""
    result = parse_think_segments("left<think></think>right")
    assert result == [("left", False), ("", True), ("right", False)]


# ── (g) Unclosed <think>X ────────────────────────────────────────────────────


def test_unclosed_think_block_trailing_content() -> None:
    """Think block opened but model output truncated before close tag."""
    result = parse_think_segments("<think>truncated reasoning")
    assert result == [("", False), ("truncated reasoning", True)]


def test_unclosed_think_no_content() -> None:
    """Think block opened at very end of buffer with nothing inside."""
    result = parse_think_segments("<think>")
    assert result == [("", False), ("", True)]


# ── (h) Non-think text only ──────────────────────────────────────────────────


def test_plain_text_no_tags() -> None:
    """Buffer contains no think tags — returns a single OUTSIDE segment."""
    result = parse_think_segments("Hello, world!")
    assert result == [("Hello, world!", False)]


def test_empty_buffer() -> None:
    """Empty string input returns a single empty OUTSIDE segment."""
    result = parse_think_segments("")
    assert result == [("", False)]


# ── (i) Nested <think> rejection ─────────────────────────────────────────────


def test_nested_think_tag_treated_as_text(caplog: pytest.LogCaptureFixture) -> None:
    """
    Inner <think> while already in IN_THINK state is treated as literal text,
    and a warning is logged.  The outer close tag closes the think segment.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="services.ui_shell.src.think_parser"):
        result = parse_think_segments("<think>outer<think>inner</think></think>")

    # The nested <think> is treated as literal text; the first </think> closes
    # the think block; the trailing </think> is then outside text.
    assert result == [
        ("", False),
        ("outer<think>inner", True),
        ("</think>", False),
    ]
    # Warning was emitted.
    assert any("nested" in r.message.lower() for r in caplog.records)


def test_nested_think_double_open_then_two_closes() -> None:
    """
    Variant: EDD example <think><think>X</think></think>.
    Second <think> is literal text within the outer think segment.
    First </think> closes the outer block.  Second </think> is plain text.
    """
    result = parse_think_segments("<think><think>X</think></think>")
    assert result == [
        ("", False),
        ("<think>X", True),
        ("</think>", False),
    ]
