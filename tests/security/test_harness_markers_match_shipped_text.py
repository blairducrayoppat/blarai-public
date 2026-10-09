"""The battery harness recognises the corridor by PROSE. That coupling is checked here.

HOW THIS WAS FOUND. Fixing #1406 meant correcting six operator-facing instructions that told
the operator to type text the parser refuses. One of them was
:meth:`DispatchCoordinator._render_clarifying_question`'s *"Reply with the number (e.g. `2`)"* —
and rewording it broke four dry-run tests in a completely different subsystem, because
``tools/dispatch_harness/harness.py`` decides whether a reply is a clarifying question by
searching it for the literal string ``"Reply with the number"``.

That is a real dependency with no declaration anywhere. The gate caught it this time only
because the harness has dry-run tests that happen to exercise the path. The failure mode when
it is NOT caught is quiet and expensive: the harness stops recognising clarifying questions,
never sends an option number, and every affected battery job stalls at the platform fork — a
night's work lost to a copy-edit, with nothing in the diff to suggest a connection.

WHAT THIS ASSERTS. Every marker the harness matches on still appears in the shipped text it is
meant to recognise, driven off the REAL renderer rather than a copy of its output. So a reword
fails here, in a test whose message says exactly what it broke and why, instead of surfacing as
four confusing dry-run failures or — worse — as a silent stall at 02:00.

WHAT IT DOES NOT FIX. Prose-matching is still the wrong mechanism; a structural signal would
not need this test at all. #1408 carries that case. This makes the current coupling honest,
which is the most a test can do about a design it is not allowed to change tonight — the
harness is on the battery path and #740's one-change-per-run rule applies before a nightly.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import DispatchCoordinator
from tools.dispatch_harness import harness as _harness

#: A clarifying question as the coordinator really renders it — options and all.
_QUESTION = {
    "question": "Where will you mainly use this?",
    "options": [
        {"label": "On this computer", "surface": "desktop"},
        {"label": "In a web browser", "surface": "web"},
        {"label": "On a phone", "surface": "mobile"},
    ],
}


def _rendered_clarifying_question() -> str:
    """The real render, from the real method — never a transcribed copy.

    ``_render_clarifying_question`` touches no instance state, so an unbound call keeps this
    test free of the coordinator's construction requirements. A copy of the string here would
    make the test pass while the shipped text drifted, which is the whole defect.
    """
    return DispatchCoordinator._render_clarifying_question(
        None, "an app with buttons", _QUESTION
    )


def test_the_clarify_marker_still_matches_the_shipped_question():
    """The lock. If this fails, the harness has just gone blind to platform questions."""
    rendered = _rendered_clarifying_question()
    assert _harness._CLARIFY_MARKER in rendered, (
        f"tools/dispatch_harness/harness.py::_CLARIFY_MARKER is "
        f"{_harness._CLARIFY_MARKER!r}, and _render_clarifying_question no longer contains "
        f"it:\n\n{rendered}\n\n"
        "The harness finds clarifying questions by searching for that literal. With it gone "
        "the harness never answers one, and every battery job that hits the platform fork "
        "stalls there. Either restore the phrase in the render, or update the marker — but "
        "the marker lives on the BATTERY path, so changing it before a nightly is a #740 "
        "one-change-per-run decision, not a copy-edit."
    )


def test_the_approve_marker_still_matches_a_shipped_plan_card():
    """The same coupling, on the marker that gates the harness's approve step. This one is
    already robust — it matches a `/dispatch approve` literal rather than prose — and is
    asserted so the pair cannot drift into being the only checked one."""
    assert _harness._APPROVE_MARKER == "/dispatch approve"
    from services.ui_gateway.src.dispatch_coordinator import _playback_invitation

    assert _harness._APPROVE_MARKER in _playback_invitation(0), (
        "the plan card's own invitation no longer offers the verb the harness waits for"
    )


def test_the_requirements_marker_still_matches_the_shipped_question_set():
    """And the third. ``_render_requirements_questions`` is the #819 turn the harness
    auto-answers with 'just decide for me'."""
    rendered = DispatchCoordinator._render_requirements_questions(
        None, "a website for my pottery studio",
        [{"axis": "surface", "question": "Where will you use this?"}],
    )
    assert _harness._REQUIREMENTS_MARKER in rendered, (
        f"_REQUIREMENTS_MARKER {_harness._REQUIREMENTS_MARKER!r} is no longer in the "
        f"rendered requirements question set:\n\n{rendered}"
    )


@pytest.mark.parametrize(
    "marker",
    ["_CLARIFY_MARKER", "_REQUIREMENTS_MARKER", "_APPROVE_MARKER"],
)
def test_every_marker_is_covered_by_a_check_above(marker):
    """Guards the vacuous shape from the other direction: a marker ADDED to the harness
    without a matching assertion here would leave a new invisible coupling, and this file
    would still be green. Measured 2026-08-15: three markers, three checks.

    ``_RUN_ID_RE`` is deliberately excluded — it matches the EXECUTE reply's run id, which is
    machine-shaped output rather than an instruction to a human, and it is a compiled regex
    rather than a literal."""
    literals = {
        name for name in dir(_harness)
        if name.endswith("_MARKER") and isinstance(getattr(_harness, name), str)
    }
    assert marker in literals, f"{marker} is gone from the harness — update this file"
    assert literals == {"_CLARIFY_MARKER", "_REQUIREMENTS_MARKER", "_APPROVE_MARKER"}, (
        f"the harness's marker set changed to {sorted(literals)}; every marker that matches "
        "shipped operator-facing text needs its own check in this file, or the coupling it "
        "creates is invisible again"
    )


def test_a_reworded_render_is_REFUSED():
    """The toggle. Without it this file passes on text that already matches and nobody learns
    whether it can fail. The fixture is the #1406 reword that actually broke the harness:
    correct as an instruction, and fatal to the marker."""
    reworded = "Reply `/dispatch 2` with the number of the option you want."
    assert "/dispatch 2" in reworded, "fixture must be a VALID instruction"
    assert _harness._CLARIFY_MARKER not in reworded, (
        "the marker survived a reword that drops its literal — this control cannot fail"
    )
