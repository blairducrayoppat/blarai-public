"""Lesson 33's owed structural control — an instrument that PUBLISHES a count must say
which of its checks actually ran.

**Why this gate exists.** Lesson 33 ("capturing data and publishing data are two separate
disciplines — a record that implies more coverage than it has is worse than none at all")
reached its THIRD instance on 2026-08-08, which under the LESSONS Rule-3 curation SOP obliges
a structural control rather than a fourth per-instrument fix. The performance-record half of
that lesson already HAS one: ``tools/perf_contrib/schema.py`` rejects any record whose
``not_measured`` is missing or empty. The GRADER half had none, and that is the half that bit:

* ``oracle-qa.json``  — ``findings_total: 0`` beside ``f2p_baseline: "not-run"`` (#1342). The
  count was a floor, not a count, and ``already_satisfied`` deleted two tasks on the strength
  of it, one of them a page the operator had explicitly asked for.
* ``link_lint``       — its FIRST sweep reported ``checked: true, hard: false`` for four empty
  scaffolds, i.e. a clean bill of health from a scan that examined nothing (#1345). Caught by
  running it, not by reviewing it.
* ``_rule_harness_budget`` — every HARNESS fault filed as budget exhaustion on the attribution
  alone (#1324).

The shape is always the same and is never disguised: the honest field is present, adjacent,
and ignored, because a reader takes the headline. So the control cannot be "add a disclosure";
it has to be "you may not ship a NEW instrument that publishes a total without one".

**What this gate does.** Deny-by-default over the grader surface. Any module that emits a
findings/counts total must also carry a not-measured vocabulary — a way for a reader to tell
*ran and found nothing* from *did not run*. A module that genuinely does not need one goes on
the allowlist WITH A WRITTEN REASON, which is the point: the exemption becomes a sentence
somebody has to defend, not a silence.

**Honest limit, stated because an unnamed limit is this lesson wearing a different hat.** This
is a SOURCE-level check. It proves a disclosure vocabulary is present in the module that
publishes the total; it cannot prove the disclosure is correct, complete, or reachable on
every path. It is a ratchet against the next instrument shipping without one — not a proof
that the existing ones are honest. Those are proved individually, by their own toggle-proofs
(``test_oracle_qa_measurement_honesty.py``, ``test_link_lint.py``).
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

#: The grader surface: modules whose job is to examine something and publish a verdict.
_SURFACE_DIRS = (
    _REPO / "shared" / "fleet",
    _REPO / "tools" / "dispatch_harness",
)

#: Dict keys that constitute PUBLISHING A COUNT — a reader will take any of these as
#: "this is how many problems there are".
_TOTAL_KEYS = frozenset({
    "findings_total", "findings", "counts", "violations", "defects", "errors_total",
})

#: Any one of these means the module gives a reader some way to tell *did not run* from
#: *ran and found nothing*. Deliberately broad, and broadened further after its first run:
#: the requirement is that the DISTINCTION EXISTS, not that it wears a particular name.
#:
#: `green_audit.py` was flagged on the first run and is NOT an offender — it carries
#: `audited: bool` and an `error` string, and its own docstring records that "not gamed"
#: stopped being rendered as "clean". `layout_lint.py` was flagged for the same reason:
#: `files_scanned: 0` is exactly the distinction, and its PowerShell caller derives
#: `not-applicable` from it. Both were false positives of a too-narrow vocabulary, and a
#: gate that cries wolf stops being read — so the vocabulary was corrected rather than the
#: modules being allowlisted, which would have recorded a fault that was not there.
_DISCLOSURE_TOKENS = (
    "not_measured", "not-measured", "not_run", "not-run", "findings_conclusive",
    "measurement", "unmeasured", "checked", "measured", "unavailable", "not-applicable",
    "not_applicable", "conclusive", "audited", "files_scanned",
)

#: Modules that publish a count-shaped key but need no disclosure, each with the REASON.
#: An entry here is a claim somebody made in writing and can be argued with — which is the
#: whole mechanism. Deny-by-default: anything not listed must carry a disclosure.
#: EMPTY, and that is the honest outcome rather than a weak one. Every module on the grader
#: surface today carries the distinction under one name or another. Three entries were
#: written here on first authoring, from reasoning about which modules "probably" needed an
#: exemption — and `test_the_allowlist_does_not_go_stale` immediately convicted all three as
#: unnecessary. Guessing at an allowlist is the same defect this gate exists to catch, one
#: level up: an exemption asserted rather than measured.
_ALLOWLIST: dict[str, str] = {}


def _module_publishes_a_total(tree: ast.AST) -> bool:
    """True when the module builds a dict carrying a count-shaped key.

    Matches dict literals (``{"findings_total": ...}``) and keyword construction
    (``dict(counts=...)``), which is how every producer on this surface writes one.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in _TOTAL_KEYS:
                    return True
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in _TOTAL_KEYS:
                    return True
    return False


def _scan() -> tuple[list[str], list[str]]:
    """Returns (modules publishing a total without a disclosure, parse errors)."""
    offenders: list[str] = []
    parse_errors: list[str] = []
    for base in _SURFACE_DIRS:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or path.name.startswith("test_"):
                continue
            rel = path.relative_to(_REPO).as_posix()
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text)
            except (OSError, SyntaxError) as exc:
                parse_errors.append(f"{rel}: {exc}")
                continue
            if not _module_publishes_a_total(tree):
                continue
            if any(token in text for token in _DISCLOSURE_TOKENS):
                continue
            offenders.append(rel)
    return offenders, parse_errors


def test_no_grader_publishes_a_total_without_saying_what_it_did_not_measure() -> None:
    """A NEW instrument may not ship a count with no way to say the check did not run.

    If this fails on a module you just wrote: the fix is not to add the word to a comment.
    It is to make the record distinguish *ran and found nothing* from *did not look*, and to
    prove it with a test that fails when the distinction is removed. ``link_lint.lint_site``
    and ``OracleQAResult.to_evidence`` are the two worked examples.
    """
    offenders, parse_errors = _scan()
    assert not parse_errors, f"grader surface failed to parse: {parse_errors}"

    unexplained = [m for m in offenders if m not in _ALLOWLIST]
    assert unexplained == [], (
        "these modules publish a findings/counts total but carry no way to say a check did "
        "not run — a zero from them is unreadable (lesson 33, #1342, #1345):\n  "
        + "\n  ".join(unexplained)
        + "\n\nAdd the disclosure, or add an entry to _ALLOWLIST with a written reason."
    )


def test_the_allowlist_does_not_go_stale() -> None:
    """FAIL if an allowlisted module no longer needs its exemption — the ratchet only shrinks.

    Without this, an exemption granted once outlives its reason and quietly protects a module
    that has since grown a real verdict. Same coupling the raw-spawn gate enforces.
    """
    offenders, _ = _scan()
    stale = [m for m in _ALLOWLIST if m not in offenders]
    assert stale == [], (
        "these modules are allowlisted but no longer publish an undisclosed total — remove "
        "their entries in the same change that made them unnecessary:\n  " + "\n  ".join(stale)
    )


def test_every_allowlist_entry_gives_a_reason() -> None:
    """An exemption with no argument is a silence with extra steps."""
    empty = [m for m, reason in _ALLOWLIST.items() if len(reason.strip()) < 20]
    assert empty == [], f"allowlist entries with no real reason: {empty}"


def test_the_gate_actually_catches_the_shape_it_names() -> None:
    """Toggle proof: the escaped record's shape must be detected by this gate's own rule.

    A green result above is worthless unless the detector fires on the artifact that caused
    the lesson. This reconstructs it — a module publishing a total with no disclosure — and
    requires the check to convict.
    """
    guilty = ast.parse('def to_evidence(self):\n    return {"findings_total": 0}\n')
    innocent = ast.parse('def go(self):\n    return {"ok": True}\n')

    assert _module_publishes_a_total(guilty) is True
    assert _module_publishes_a_total(innocent) is False

    # ...and the disclosure vocabulary must be what rescues it, not the shape.
    rescued = 'def to_evidence(self):\n    return {"findings_total": 0, "not_measured": []}\n'
    assert any(token in rescued for token in _DISCLOSURE_TOKENS)


def test_the_two_worked_examples_are_on_the_right_side_of_the_gate() -> None:
    """`link_lint` and `oracle_qa` publish totals AND disclose — they must not be exempt."""
    offenders, _ = _scan()
    for module in ("shared/fleet/link_lint.py", "shared/fleet/oracle_qa.py"):
        assert (_REPO / module).is_file(), f"{module} is missing"
        assert module not in offenders, f"{module} lost its not-measured disclosure"
        assert module not in _ALLOWLIST, f"{module} must pass on merit, not by exemption"
