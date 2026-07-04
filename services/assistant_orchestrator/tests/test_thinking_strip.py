"""Streaming visibility filter — thinking/tool-call suppression (ADR-012 §2.4).

Regression for ISS-2: the per-chunk tag check missed <think>/<tool_call> tags
that streamed SPLIT across tokens, leaking the model's reasoning to the live UI
(and, once voice shipped, speaking it). _visible_text runs on the accumulated
text instead, so split tags are joined before matching.
"""

from __future__ import annotations

from services.assistant_orchestrator.src.gpu_inference import _visible_text


def _stream(chunks: list[str]) -> str:
    """Emulate the streamer: accumulate, emit only the growing visible delta."""
    acc = ""
    emitted = 0
    shown = ""
    for c in chunks:
        acc += c
        visible = _visible_text(acc)
        if len(visible) > emitted:
            shown += visible[emitted:]
            emitted = len(visible)
    return shown


def test_split_think_tag_does_not_leak() -> None:
    chunks = ["Hi! ", "<", "think", ">", "secret reasoning", "</", "think", ">", "Answer."]
    shown = _stream(chunks)
    assert "secret reasoning" not in shown
    assert shown == "Hi! Answer."


def test_whole_think_tag_in_one_chunk() -> None:
    assert _stream(["A ", "<think>r</think>", "B"]) == "A B"


def test_tool_call_suppressed_from_live_stream() -> None:
    shown = _stream(["Result: ", "<tool_call>", '{"name":"x"}', "</tool_call>", " done"])
    assert "tool_call" not in shown
    assert "name" not in shown
    assert shown == "Result:  done"


def test_unclosed_think_block_is_withheld() -> None:
    assert _visible_text("Hi <think>still thinking") == "Hi "


def test_trailing_partial_tag_is_withheld() -> None:
    # A "<" that might begin a tag must not be emitted until it resolves.
    assert _visible_text("Hi <thi") == "Hi "
    assert _visible_text("Hi <") == "Hi "


def test_plain_text_passes_through() -> None:
    assert _visible_text("Just a normal answer.") == "Just a normal answer."


def test_emit_is_prefix_stable_no_duplication() -> None:
    # Streaming the delta must never re-show or drop already-shown text.
    chunks = ["The ", "cat <think>", "hmm", "</think> sat ", "down."]
    assert _stream(chunks) == "The cat  sat down."
