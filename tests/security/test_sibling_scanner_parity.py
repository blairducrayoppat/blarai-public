"""The two bounded scanners must disclose the same KINDS of shortfall, or say why not.

THIS IS THE STRUCTURAL CONTROL FOR LESSON 342'S THIRD INSTANCE, and it is here because a
lesson did not stop the fourth.

``green_quality/security.py`` and ``green_quality/placeholder_prose.py`` are siblings: both
walk a delivered tree under bounds, both publish a ``coverage_partial`` flag that tells a
reader whether the looking FINISHED, and both feed the same scorecard. In one review pass on
2026-08-14/15, three separate fixes landed on ``security.py`` and were not carried to
``placeholder_prose.py`` — the byte-cap disclosure (#1395), the rule-list clip and the
exact-boundary cap inference (#1400) — each ticket having said "in the same change" in its
own DONE list. Writing this control then surfaced a fourth: prose could abandon its walk at
the high-severity ceiling and still publish complete coverage, because it had no
``walk_abandoned`` at all.

Four instances is not a memory problem, so this is not a reminder. The rule enforced here is:
**every disclosure concept one scanner publishes must be published by the other, or be listed
in** :data:`DECLARED_ASYMMETRIES` **with a reason.** A divergence must be argued, not merely
possible — which is the same standard the deferral gate applies to a `blocked-by:` predicate.

Deliberately compares CONCEPTS rather than variable names: the two modules legitimately name
the same fact differently (``unparsed_python`` vs ``unparsed``), and a test that demanded
identical identifiers would be brittle enough that someone would eventually delete it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[2] / "tools" / "dispatch_harness" / "green_quality"

#: Local variable name -> the shortfall it discloses. Adding a NEW disclosure variable to
#: either scanner without an entry here fails :func:`test_every_disclosure_name_is_classified`,
#: which is the point: an unclassified name is a fact nobody decided about.
_CONCEPT_OF: dict[str, str] = {
    "file_cap_hit": "the file-count bound was reached",
    "truncated_reads": "a file was read only up to its byte bound",
    "unreadable": "a file could not be read at all",
    "unparsed_python": "content was found but did not parse",
    "unparsed": "content was found but did not parse",
    "silenced": "a page went silent mid-document on an unclosed tag",
    "walk_abandoned": "the walk stopped early and files went unread",
}

#: Concepts one scanner publishes and the other deliberately does not, each with the reason.
#: An entry here is a decision on the record; an omission is a defect.
DECLARED_ASYMMETRIES: dict[str, str] = {
    "a page went silent mid-document on an unclosed tag": (
        "PROSE ONLY. It describes an HTML/template parser losing the rest of a document to an "
        "unclosed <pre>/<code>/<template>. The security scanner greps source text and has no "
        "parse that can go silent, so there is no equivalent fact for it to report."
    ),
}

#: Names that appear in a coverage expression but are NOT disclosures — assertions about the
#: population rather than about the scan's completeness.
_NOT_A_DISCLOSURE = {"scanned", "pages_scanned", "files_scanned"}


def _coverage_expr(module: str) -> ast.expr:
    """The ``coverage_partial=`` expression from *module*'s result construction."""
    return _select_coverage_expr((_PKG / module).read_text(encoding="utf-8"), module)


def _select_coverage_expr(source: str, module: str) -> ast.expr:
    """The one OR-shaped ``coverage_partial=`` construction in *source*.

    Takes SOURCE rather than a path so the selection rules can be tested against synthetic
    modules — see :func:`test_a_second_or_shaped_construction_is_REFUSED`. Fails loudly
    rather than returning None: a parity check that silently passes on a module it could not
    read is the exact defect this file exists to catch."""
    tree = ast.parse(source)
    found = [
        kw.value
        for node in ast.walk(tree)
        for kw in (node.keywords if isinstance(node, ast.Call) else [])
        if kw.arg == "coverage_partial"
        # SELECTED BY SHAPE, not by position. The summary is the one construction whose
        # argument ORs the signals together — `bool(a or b or c)` — and nothing else in these
        # modules has that shape: the single-cause early returns are `coverage_partial=True`
        # (an ast.Constant, not a Call at all).
        #
        # An earlier version of this filter took `found[-1]`, i.e. whichever matching node
        # ast.walk happened to visit last. An independent reviewer demonstrated the hole by
        # appending a synthetic `coverage_partial=bool(some_var)` branch to an in-memory copy
        # of a scanner: selection silently moved to the decoy and BOTH parity tests then
        # validated the wrong expression while the real one went unchecked — green, with no
        # warning. That is a fail-loud control failing silently, which is worse than no
        # control, and it would have armed itself the next time either scanner grew a second
        # branch. This pass added several, so that was not a hypothetical.
        and isinstance(kw.value, ast.Call)
        and len(kw.value.args) == 1
        and isinstance(kw.value.args[0], ast.BoolOp)
    ]
    assert found, (
        f"no `coverage_partial=bool(<a or b or ...>)` construction found in {module}. Either "
        f"the scanner stopped publishing the flag, or it now builds it in a shape this "
        f"control cannot read — both are failures, and neither may pass silently."
    )
    assert len(found) == 1, (
        f"{module} has {len(found)} OR-shaped `coverage_partial` constructions at lines "
        f"{[n.lineno for n in found]}. This control cannot tell which one is the summary, so "
        f"it refuses to guess: guessing is how it would validate a decoy while the real "
        f"expression drifts unchecked. Give the module one summary construction, or teach "
        f"this function how to pick — deliberately, and in writing."
    )
    return found[0]


def _disclosure_names(module: str) -> set[str]:
    # Walk the ARGUMENTS of `bool(...)`, never the call node itself: `bool` is an ast.Name
    # like any other and would otherwise be reported as an unclassified disclosure.
    expr = _coverage_expr(module)
    return {
        node.id
        for arg in expr.args
        for node in ast.walk(arg)
        if isinstance(node, ast.Name) and node.id not in _NOT_A_DISCLOSURE
    }


def _concepts(module: str) -> set[str]:
    return {_CONCEPT_OF[name] for name in _disclosure_names(module) if name in _CONCEPT_OF}


@pytest.mark.parametrize("module", ["security.py", "placeholder_prose.py"])
def test_every_disclosure_name_is_classified(module: str) -> None:
    """A name nobody classified is a fact nobody decided about."""
    unknown = _disclosure_names(module) - set(_CONCEPT_OF)
    assert not unknown, (
        f"{module}'s coverage_partial references {sorted(unknown)}, which _CONCEPT_OF does "
        f"not classify. Add it there naming the shortfall it discloses, then either give the "
        f"sibling scanner the same signal or declare the asymmetry with a reason."
    )


def test_the_two_scanners_disclose_the_same_shortfalls() -> None:
    """The control. Every concept must be on both sides or declared, with a reason."""
    security = _concepts("security.py")
    prose = _concepts("placeholder_prose.py")

    for missing_from, present_in, gap in (
        ("placeholder_prose.py", "security.py", security - prose),
        ("security.py", "placeholder_prose.py", prose - security),
    ):
        undeclared = gap - set(DECLARED_ASYMMETRIES)
        assert not undeclared, (
            f"{present_in} discloses {sorted(undeclared)} and {missing_from} does not.\n"
            f"This is lesson 342's shape: a fix carried to one sibling and not the other. "
            f"Either add the same signal to {missing_from}, or add an entry to "
            f"DECLARED_ASYMMETRIES explaining why the fact cannot exist there."
        )


def test_the_asymmetry_declarations_are_not_stale() -> None:
    """A declared exception that no longer describes anything is a licence sitting open.

    Without this, DECLARED_ASYMMETRIES would only ever grow, and a future divergence could be
    waved through by an entry written for a fact that has since been fixed."""
    live = _concepts("security.py") ^ _concepts("placeholder_prose.py")
    stale = set(DECLARED_ASYMMETRIES) - live
    assert not stale, (
        f"DECLARED_ASYMMETRIES still excuses {sorted(stale)}, but the two scanners no longer "
        f"differ on it. Delete the entry — an exception nobody needs is one that can be "
        f"borrowed by the next divergence."
    )


def test_the_finding_list_cap_is_NOT_treated_as_a_coverage_shortfall() -> None:
    """The precision half, and the reason this control compares concepts and not variables.

    Both scanners cap how many findings they keep. That abbreviates the LIST while every file
    is still read, so it is not a coverage shortfall and must not set `coverage_partial` —
    otherwise the flag fires on complete scans of noisy deliveries and readers learn to skip
    it. Prose's `truncated` is the flag in question; asserting its ABSENCE here is what stops
    a future reader "fixing" the parity gap by adding the wrong variable."""
    assert "truncated" not in _disclosure_names("placeholder_prose.py"), (
        "`truncated` means the finding list was abbreviated, not that coverage was short. "
        "The signal for walking out early is `walk_abandoned`, which is a different fact."
    )
    assert "walk_abandoned" in _disclosure_names("placeholder_prose.py"), (
        "the early-exit path must still be disclosed — that one DOES leave files unread"
    )


# ---------------------------------------------------------------------------
# The control's own controls. A gate that cannot be shown to fail is not a gate.
# ---------------------------------------------------------------------------

_ONE = "r = R(coverage_partial=bool(a or b))\n"
_DECOY = "def later(x):\n    return R(coverage_partial=bool(x or x))\n"
_SINGLE_CAUSE = "def early():\n    return R(coverage_partial=True)\n"


def test_the_one_or_shaped_construction_is_found() -> None:
    expr = _select_coverage_expr(_ONE, "synthetic.py")
    assert {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)} >= {"a", "b"}


def test_a_second_or_shaped_construction_is_REFUSED() -> None:
    """The hole an independent reviewer demonstrated, now closed and locked.

    Selection used to be `found[-1]` — whichever matching node ast.walk visited last. Adding
    a second OR-shaped construction silently moved selection to it, and both parity tests
    then validated the decoy while the real summary drifted unchecked. Green, no warning:
    a fail-loud control failing silently, which is worse than no control.

    Refusing is the only safe answer. Picking one and being right by luck is what it did
    before."""
    with pytest.raises(AssertionError) as exc:
        _select_coverage_expr(_ONE + _DECOY, "synthetic.py")
    assert "cannot tell which one is the summary" in str(exc.value)


def test_a_single_cause_TRUE_branch_is_not_mistaken_for_the_summary() -> None:
    """Precision. `coverage_partial=True` early returns are legitimate and numerous; if they
    counted, the refusal above would fire on every honest module and the control would be
    deleted within a week for crying wolf."""
    expr = _select_coverage_expr(_SINGLE_CAUSE + _ONE, "synthetic.py")
    assert {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)} >= {"a", "b"}


def test_a_scanner_that_stops_publishing_the_flag_is_REFUSED() -> None:
    """Zero matches must fail, not pass. A module this control cannot read is a module it is
    not checking, and that must never look like agreement."""
    with pytest.raises(AssertionError) as exc:
        _select_coverage_expr("x = 1\n", "synthetic.py")
    assert "no `coverage_partial=" in str(exc.value)
