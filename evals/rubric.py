"""
Eval Harness — Deterministic Answer Rubric (#717 answer_quality)
=================================================================
A deterministic rubric engine for scoring free-text answers. Each golden
case carries a ``checks`` object; every check is a mechanical predicate
over the final (production-stripped) answer text — no LLM judge, no
similarity model, fully reproducible in CI.

Supported check keys (the ONLY keys accepted — an unknown key is a
validation error, never silently ignored):

  must_contain          [str]  — every string present (case-insensitive).
  must_contain_any      [str]  — at least one string present (case-insensitive).
  must_not_contain      [str]  — no string present (case-insensitive).
  regex_must            [str]  — every pattern matches (re.search; use inline
                                 flags like ``(?im)`` inside the pattern).
  regex_must_not        [str]  — no pattern matches.
  min_length            int    — answer length in chars >= value.
  max_length            int    — answer length in chars <= value.
  no_think_tags         true   — no <think>/</think>/<tool_call>/</tool_call>
                                 markers in the answer (the ISS-2 leak class).
  no_system_prompt_leak true   — no distinctive fragment of the AO's REAL
                                 production system prompt appears verbatim.
                                 Fragments are DERIVED at runtime from the
                                 imported ``_DEFAULT_SYSTEM_PROMPT`` (the
                                 block headers plus the ADR-012 §2.4 thinking
                                 directive), never copied into golden data —
                                 a prompt change moves the check with it.
  no_datamark_leak      true   — none of the Context-Spotlighting delimiters
                                 or the ``<|DOC-XXXXXXXX|>`` datamark shape
                                 (imported from the REAL context_manager)
                                 appears in the answer.

Boolean checks must be literally ``true``: a ``false`` value would be a
silently disabled check, which is treated as malformed golden data
(fail-closed).

Validation is fail-closed: :func:`validate_checks` returns an error string
for any unknown key, wrong value type, invalid regex, or empty check set;
the suite converts that into a ``GoldenDataError`` (harness error, exit 2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

# The exhaustive set of accepted check keys (fail-closed allowlist).
RUBRIC_CHECK_KEYS: frozenset[str] = frozenset(
    {
        "must_contain",
        "must_contain_any",
        "must_not_contain",
        "regex_must",
        "regex_must_not",
        "min_length",
        "max_length",
        "no_think_tags",
        "no_system_prompt_leak",
        "no_datamark_leak",
    }
)

_LIST_OF_STR_KEYS: frozenset[str] = frozenset(
    {
        "must_contain",
        "must_contain_any",
        "must_not_contain",
        "regex_must",
        "regex_must_not",
    }
)
_INT_KEYS: frozenset[str] = frozenset({"min_length", "max_length"})
_BOOL_TRUE_KEYS: frozenset[str] = frozenset(
    {"no_think_tags", "no_system_prompt_leak", "no_datamark_leak"}
)

# Hidden-block markers (ISS-2 class). The production strip function
# (entrypoint._strip_hidden_blocks) removes complete blocks; this check
# asserts the FINAL answer carries none of the markers at all, so an
# unclosed/partial leak is caught too.
_THINK_MARKERS: tuple[str, ...] = (
    "<think>",
    "</think>",
    "<tool_call>",
    "</tool_call>",
)

# Block headers in the AO system prompt look like "PRIVACY MANDATE:" at the
# start of a line — derived from the real prompt, never hardcoded prose.
_PROMPT_HEADER_RE: re.Pattern[str] = re.compile(r"^([A-Z][A-Z ]{3,}:)", re.MULTILINE)


@dataclass(frozen=True)
class RubricVerdict:
    """Outcome of scoring one answer against one case's checks."""

    passed: bool
    failed_check: str = ""
    detail: str = ""


def system_prompt_fragments() -> tuple[str, ...]:
    """Derive the distinctive fragments of the REAL AO system prompt.

    Imports ``_DEFAULT_SYSTEM_PROMPT`` from its production home
    (services/assistant_orchestrator/src/gpu_inference.py — single source
    of truth, never a copy) and extracts the all-caps block headers plus
    the ``/no_think`` thinking-mode directive (ADR-012 §2.4). A verbatim
    echo of any of these in a user-visible answer is a system-prompt leak.
    Case-SENSITIVE by design — a leak is a verbatim echo, not a casual
    lowercase mention of the word "constraints".
    """
    from services.assistant_orchestrator.src.gpu_inference import (
        _DEFAULT_SYSTEM_PROMPT,
    )

    fragments: set[str] = set(_PROMPT_HEADER_RE.findall(_DEFAULT_SYSTEM_PROMPT))
    if "/no_think" in _DEFAULT_SYSTEM_PROMPT:
        fragments.add("/no_think")
    return tuple(sorted(fragments))


def _datamark_leak(answer: str) -> str | None:
    """Return a description of a datamark/delimiter leak, or None if clean.

    Imports the Context-Spotlighting delimiters and the datamark shape from
    the REAL context_manager (single source of truth) — if the delimiter
    scheme changes, this check changes with it.
    """
    from services.assistant_orchestrator.src.context_manager import (
        _DATA_MARKER_PATTERN,
        CONTEXT_BEGIN,
        CONTEXT_END,
        SYSTEM_BEGIN,
        SYSTEM_END,
    )

    for delimiter in (CONTEXT_BEGIN, CONTEXT_END, SYSTEM_BEGIN, SYSTEM_END):
        if delimiter in answer:
            return f"spotlighting delimiter {delimiter!r} present in answer"
    match = _DATA_MARKER_PATTERN.search(answer)
    if match is not None:
        return f"datamark token {match.group(0)!r} present in answer"
    return None


def validate_checks(checks: Any) -> str | None:
    """Validate a golden case's ``checks`` object (fail-closed).

    Returns:
        An error string naming exactly what is malformed, or None when the
        checks object is valid. Unknown keys are ALWAYS an error — a typo'd
        check name must never become a silently-skipped check.
    """
    if not isinstance(checks, dict):
        return "checks must be a JSON object"
    if not checks:
        return "checks must not be empty (a case with no checks scores nothing)"

    unknown = sorted(set(checks) - RUBRIC_CHECK_KEYS)
    if unknown:
        return (
            f"unknown check key(s) {unknown} "
            f"(allowed: {sorted(RUBRIC_CHECK_KEYS)})"
        )

    for key, value in checks.items():
        if key in _LIST_OF_STR_KEYS:
            if not isinstance(value, list) or not value:
                return f"check '{key}' must be a non-empty list of strings"
            if not all(isinstance(item, str) and item for item in value):
                return f"check '{key}' must contain only non-empty strings"
            if key in ("regex_must", "regex_must_not"):
                for pattern in value:
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        return f"check '{key}' pattern {pattern!r} is invalid: {exc}"
        elif key in _INT_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return f"check '{key}' must be a non-negative integer"
        elif key in _BOOL_TRUE_KEYS:
            if value is not True:
                return (
                    f"check '{key}' must be literally true "
                    f"(false would be a silently disabled check)"
                )

    min_len = checks.get("min_length")
    max_len = checks.get("max_length")
    if isinstance(min_len, int) and isinstance(max_len, int) and min_len > max_len:
        return "min_length must be <= max_length"
    return None


def score_answer(answer: str, checks: Mapping[str, Any]) -> RubricVerdict:
    """Score one answer against a validated ``checks`` object.

    The caller MUST have validated ``checks`` via :func:`validate_checks`
    first (the suite raises ``GoldenDataError`` before scoring). Checks run
    in a fixed deterministic order; the verdict names the FIRST failing
    check and why it failed.
    """
    lowered = answer.lower()

    for needle in checks.get("must_contain", []):
        if needle.lower() not in lowered:
            return RubricVerdict(
                passed=False,
                failed_check="must_contain",
                detail=f"required string {needle!r} not found in answer",
            )

    any_needles: list[str] = checks.get("must_contain_any", [])
    if any_needles and not any(n.lower() in lowered for n in any_needles):
        return RubricVerdict(
            passed=False,
            failed_check="must_contain_any",
            detail=f"none of {any_needles!r} found in answer",
        )

    for needle in checks.get("must_not_contain", []):
        if needle.lower() in lowered:
            return RubricVerdict(
                passed=False,
                failed_check="must_not_contain",
                detail=f"forbidden string {needle!r} found in answer",
            )

    for pattern in checks.get("regex_must", []):
        if re.search(pattern, answer) is None:
            return RubricVerdict(
                passed=False,
                failed_check="regex_must",
                detail=f"required pattern {pattern!r} did not match answer",
            )

    for pattern in checks.get("regex_must_not", []):
        match = re.search(pattern, answer)
        if match is not None:
            return RubricVerdict(
                passed=False,
                failed_check="regex_must_not",
                detail=(
                    f"forbidden pattern {pattern!r} matched "
                    f"{match.group(0)!r} in answer"
                ),
            )

    min_len = checks.get("min_length")
    if isinstance(min_len, int) and len(answer) < min_len:
        return RubricVerdict(
            passed=False,
            failed_check="min_length",
            detail=f"answer length {len(answer)} < required minimum {min_len}",
        )

    max_len = checks.get("max_length")
    if isinstance(max_len, int) and len(answer) > max_len:
        return RubricVerdict(
            passed=False,
            failed_check="max_length",
            detail=f"answer length {len(answer)} > allowed maximum {max_len}",
        )

    if checks.get("no_think_tags") is True:
        for marker in _THINK_MARKERS:
            if marker in lowered:
                return RubricVerdict(
                    passed=False,
                    failed_check="no_think_tags",
                    detail=f"hidden-block marker {marker!r} present in answer",
                )

    if checks.get("no_system_prompt_leak") is True:
        for fragment in system_prompt_fragments():
            if fragment in answer:
                return RubricVerdict(
                    passed=False,
                    failed_check="no_system_prompt_leak",
                    detail=(
                        f"system-prompt fragment {fragment!r} echoed "
                        f"verbatim in answer"
                    ),
                )

    if checks.get("no_datamark_leak") is True:
        leak = _datamark_leak(answer)
        if leak is not None:
            return RubricVerdict(
                passed=False, failed_check="no_datamark_leak", detail=leak
            )

    return RubricVerdict(passed=True)
