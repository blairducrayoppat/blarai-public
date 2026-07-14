"""#834: the AO brain's hidden-block strip is now resolved from the model-profiles
manifest (``shared.fleet.model_profiles``) instead of a hard-coded regex — in BOTH
``entrypoint._strip_hidden_blocks`` and its twin ``gpu_inference._visible_text``.

These lock the DORMANT contract: with the shipped manifest (or none at all), the
resolved binding is BYTE-IDENTICAL to the historical
``<think>.*?</think>|<tool_call>.*?</tool_call>`` DOTALL regex, and the two
consumers share ONE binding so the twin can never drift.
"""

from __future__ import annotations

import re

from services.assistant_orchestrator.src import entrypoint as ep
from services.assistant_orchestrator.src import gpu_inference as gi

# The exact pattern both consumers hard-coded before #834.
_HISTORICAL = re.compile(r"<think>.*?</think>|<tool_call>.*?</tool_call>", re.DOTALL)


def _is_historical(pattern: "re.Pattern[str]") -> bool:
    return pattern.pattern == _HISTORICAL.pattern and pattern.flags == _HISTORICAL.flags


def test_entrypoint_regex_byte_identical() -> None:
    assert _is_historical(ep._HIDDEN_BLOCK_RE)


def test_gpu_inference_regex_byte_identical() -> None:
    assert _is_historical(gi._HIDDEN_BLOCK_RE)
    assert gi._HIDDEN_BLOCK_OPEN_TAGS == ("<think>", "<tool_call>")


def test_twin_shares_one_binding() -> None:
    # Both resolve the SAME model (the AO brain); the patterns must match so the
    # fork closed here cannot silently drift (dossier sec 6.2).
    assert ep._HIDDEN_BLOCK_RE.pattern == gi._HIDDEN_BLOCK_RE.pattern
    assert ep._HIDDEN_BLOCK_RE.flags == gi._HIDDEN_BLOCK_RE.flags


def test_strip_hidden_blocks_behavior_unchanged() -> None:
    cases = [
        ("a<think>x</think>b<tool_call>{}</tool_call>c", "abc"),
        ("no blocks here", "no blocks here"),
        ("<think>only</think>", ""),
        ("multi\nline<think>a\nb</think>tail", "multi\nlinetail"),
        ("<tool_call>call</tool_call>keep", "keep"),
    ]
    for raw, _expected in cases:
        # Compare against the historical regex directly (behaviour equivalence).
        historical = _HISTORICAL.sub("", raw).strip()
        assert ep._strip_hidden_blocks(raw) == historical


def test_visible_text_behavior_unchanged() -> None:
    cases = [
        "keep<think>hidden",
        "shown<think>a</think>more<tool_call>{}</tool_call>end",
        "prefix<",
        "prefix<thi",
        "clean text no tags",
    ]
    for raw in cases:
        # Reference implementation with the historical constants.
        s = _HISTORICAL.sub("", raw)
        for tag in ("<think>", "<tool_call>"):
            idx = s.find(tag)
            if idx != -1:
                s = s[:idx]
        lt = s.rfind("<")
        if lt != -1 and ">" not in s[lt:]:
            s = s[:lt]
        assert gi._visible_text(raw) == s
