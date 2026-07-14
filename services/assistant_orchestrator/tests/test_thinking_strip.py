"""Streaming visibility filter — thinking/tool-call suppression (ADR-012 §2.4).

Regression for ISS-2: the per-chunk tag check missed <think>/<tool_call> tags
that streamed SPLIT across tokens, leaking the model's reasoning to the live UI
(and, once voice shipped, speaking it). _visible_text runs on the accumulated
text instead, so split tags are joined before matching.
"""

from __future__ import annotations

import random

from services.assistant_orchestrator.src import gpu_inference
from services.assistant_orchestrator.src.gpu_inference import (
    _IncrementalVisibleText,
    _visible_text,
)


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


# ─────────────────────────────────────────────────────────────────
# #806: incremental visibility filter — O(n) with byte-identical output
# ─────────────────────────────────────────────────────────────────


def _ref_deltas(chunks: list[str]) -> list[str]:
    """Reference per-chunk delta sequence: the OLD streamer's exact behavior —
    accumulate, run _visible_text on the whole thing, emit only the growth."""
    acc = ""
    emitted = 0
    deltas: list[str] = []
    for c in chunks:
        acc += c
        vis = _visible_text(acc)
        if len(vis) > emitted:
            deltas.append(vis[emitted:])
            emitted = len(vis)
        else:
            deltas.append("")
    return deltas


def _incr_deltas(chunks: list[str]) -> list[str]:
    """Per-chunk delta sequence from the incremental filter under test."""
    vis = _IncrementalVisibleText()
    return [vis.feed(c) for c in chunks]


# Adversarial full outputs that exercise every branch of _visible_text:
# split tags, non-hidden angle brackets, the last-"<" rule, "<" immediately
# before a hidden open, ">" inside a think block, back-to-back blocks, nesting.
_ADVERSARIAL_OUTPUTS = [
    "Just a normal answer.",
    "Hi! <think>secret reasoning</think>Answer.",
    "A <think>r</think> B <tool_call>{}</tool_call> C",
    "before<think>unclosed reasoning that runs to the very end",
    "a<b>c",                     # non-hidden tag stays visible
    "a<b<c",                     # last-"<" rule: only the final "<" is withheld
    "a<<think>x</think>y",       # "<" immediately before a hidden open
    "x <think> a > b </think> y",  # ">" INSIDE a think block
    '<tool_call>{"name":"x"}</tool_call>done',
    "p <thi",                    # trailing partial that never resolves
    "text with <angle> and <that> close>",
    "nested <think>outer <tool_call>inner</tool_call> more</think>tail",
    "<think>a</think><think>b</think>visible",
    "trailing lone <",
    "greater > than only",
    "mix < and > and <think>hide</think> show",
]


def _char_chunks(s: str) -> list[str]:
    return list(s)


def _random_chunks(s: str, rng: random.Random) -> list[str]:
    chunks: list[str] = []
    i = 0
    while i < len(s):
        step = rng.randint(1, 4)
        chunks.append(s[i : i + step])
        i += step
    return chunks


def test_incremental_matches_reference_char_by_char() -> None:
    """Streaming one char per chunk — the worst case for split tags — the
    incremental filter reproduces the reference delta sequence exactly."""
    for out in _ADVERSARIAL_OUTPUTS:
        chunks = _char_chunks(out)
        assert _incr_deltas(chunks) == _ref_deltas(chunks), out
        # Cumulative emitted text equals the OLD streamer's output exactly
        # (which, for a "<" that only later becomes a tag, can differ from
        # _visible_text(out) — both reproduce that shown-then-hidden quirk).
        assert "".join(_incr_deltas(chunks)) == _stream(chunks), out


def test_incremental_matches_reference_random_chunkings() -> None:
    """Many random chunkings (seeded, deterministic) all match the reference."""
    rng = random.Random(20260711)
    for out in _ADVERSARIAL_OUTPUTS:
        for _ in range(40):
            chunks = _random_chunks(out, rng)
            assert _incr_deltas(chunks) == _ref_deltas(chunks), (out, chunks)


def test_incremental_matches_reference_on_existing_leak_fixtures() -> None:
    """The ISS-2 split-tag fixtures still produce identical, leak-free output."""
    cases = [
        ["Hi! ", "<", "think", ">", "secret reasoning", "</", "think", ">", "Answer."],
        ["A ", "<think>r</think>", "B"],
        ["Result: ", "<tool_call>", '{"name":"x"}', "</tool_call>", " done"],
        ["The ", "cat <think>", "hmm", "</think> sat ", "down."],
    ]
    for chunks in cases:
        incr = "".join(_incr_deltas(chunks))
        assert incr == _stream(chunks)
        # And the reasoning never leaks.
        assert "secret" not in incr
        assert "tool_call" not in incr


def test_plain_text_stream_never_rescans(monkeypatch) -> None:
    """The O(n^2) defect: a long plain-text answer must NOT call _visible_text
    per chunk. The clean fast path emits the chunk verbatim with zero rescans."""
    calls = {"n": 0}
    real = gpu_inference._visible_text

    def _counting(raw: str) -> str:
        calls["n"] += 1
        return real(raw)

    monkeypatch.setattr(gpu_inference, "_visible_text", _counting)

    vis = _IncrementalVisibleText()
    chunks = [f"word{i} " for i in range(500)]
    out = "".join(vis.feed(c) for c in chunks)

    assert out == "".join(chunks)           # every chunk streamed, in order
    assert calls["n"] == 0                    # zero full rescans (was O(n) before)


def test_open_block_drain_never_rescans(monkeypatch) -> None:
    """Draining a long <think> block (chunks without '>') must not rescan the
    growing accumulation each chunk — the block fast path holds visible frozen."""
    calls = {"n": 0}
    real = gpu_inference._visible_text

    def _counting(raw: str) -> str:
        calls["n"] += 1
        return real(raw)

    monkeypatch.setattr(gpu_inference, "_visible_text", _counting)

    vis = _IncrementalVisibleText()
    # Open the block (one rescan to detect it), then stream 500 no-'>' chunks.
    vis.feed("visible <think>")
    calls["n"] = 0  # ignore the open-detection rescan; count only the drain
    for i in range(500):
        assert vis.feed(f"reasoning token {i} ") == ""
    assert calls["n"] == 0  # no per-chunk rescan while the block is open

    # Closing the block reveals the trailing text exactly as the reference does.
    tail = vis.feed("</think>DONE")
    assert tail == "DONE"
