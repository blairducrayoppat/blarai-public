"""Map a per-goal ``clarify_answer`` onto the option NUMBER the coordinator's clarifying
sub-state (Inc-4, #677) expects.

When the 14B flags an ambiguous platform fork, the gateway coordinator renders ONE curated
question with numbered options, e.g.::

    Before I plan "an app with buttons", one quick question:

    Where will you mainly use this?
      1. On this computer
      2. In a web browser
      3. On a phone

    Reply with the number (e.g. `2`), or `/dispatch reject` to cancel.

The operator (here, the harness) answers with the option NUMBER (``/dispatch 2``). A job's
``clarify_answer`` may be given as that number ("2"), or — more readably — as label text
("web", "on a phone", "this computer"). :func:`pick_clarify_answer` parses the rendered question
to recover the options and resolves the answer to the number string the coordinator accepts.

It is deliberately forgiving: an answer that matches no option falls back to the configured
default, and a default that ALSO does not resolve returns the raw answer unchanged — the
coordinator's own out-of-range path then falls back to the un-refined plan (it never hangs), so
the harness can still proceed to approve/reject. Pure + total — never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A rendered option line: two leading spaces, ``<n>. <label>`` (the coordinator's
#: ``_render_clarifying_question`` format).
_OPTION_RE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")


@dataclass(frozen=True)
class ClarifyOption:
    """One parsed option from a rendered clarifying question."""

    number: str   # the 1-based option number, as a string ("1", "2", …)
    label: str    # the human label ("On this computer")


def parse_question_options(question_text: str) -> list[ClarifyOption]:
    """Recover the numbered options from a rendered clarifying-question string.

    Reads every ``  <n>. <label>`` line in order. Returns ``[]`` when the text carries no
    numbered options (e.g. it was a normal preview, not a question) — the caller treats an empty
    result as "no question to answer".
    """
    options: list[ClarifyOption] = []
    for line in question_text.splitlines():
        m = _OPTION_RE.match(line)
        if m:
            options.append(ClarifyOption(number=m.group(1), label=m.group(2).strip()))
    return options


def _resolve_one(answer: str, options: list[ClarifyOption]) -> str | None:
    """Resolve a single answer to an option NUMBER, or None if it matches nothing.

    Resolution order (first hit wins):
      1. the answer IS an in-range option number ("2");
      2. the answer matches an option's number prefix-stripped form (e.g. "use 2" handled by
         the caller, but a bare "2" here);
      3. case-insensitive: the answer text is contained in an option label, or the label is
         contained in the answer ("web" ↔ "In a web browser"; "this computer" ↔ "On this
         computer").
    """
    a = (answer or "").strip()
    if not a:
        return None
    numbers = {opt.number for opt in options}
    if a in numbers:
        return a
    # Bare-number that is OUT of range -> not resolvable here (let the default / raw path decide).
    if a.isdigit():
        return None
    low = a.casefold()
    for opt in options:
        label = opt.label.casefold()
        if low == label or low in label or label in low:
            return opt.number
    return None


def pick_clarify_answer(
    question_text: str,
    clarify_answer: str,
    *,
    default: str = "",
) -> str:
    """Choose the option-number string to send for a rendered clarifying question.

    Args:
        question_text: The coordinator's rendered question (with the numbered options).
        clarify_answer: The job's answer — an option number ("2") or label text ("web").
        default: The sweep-wide default answer, used when ``clarify_answer`` resolves to
            nothing (also a number or a label).

    Returns:
        The option NUMBER to send as ``/dispatch <n>``. If neither the answer nor the default
        resolves against the parsed options, the raw ``clarify_answer`` (or the ``default``, or
        ``""``) is returned unchanged — the coordinator's out-of-range fallback then proceeds
        with the un-refined plan rather than hanging.
    """
    options = parse_question_options(question_text)
    resolved = _resolve_one(clarify_answer, options)
    if resolved is not None:
        return resolved
    resolved_default = _resolve_one(default, options)
    if resolved_default is not None:
        return resolved_default
    # Nothing resolved — hand back the most specific raw value we have. The coordinator's
    # _choose() coerces an unrecognised answer to the un-refined plan (never a loop).
    return (clarify_answer or "").strip() or (default or "").strip()
