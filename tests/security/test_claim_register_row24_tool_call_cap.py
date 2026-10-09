"""Claim-register row 24 states the turn's caps. Keep it stating the real ones (#1596).

Row 24 tells the operator that a conversational turn is hard-capped at 4096
generated tokens and N chained tool calls, and that nothing in the request can
relax either cap. It was marked LIVE and it was wrong twice over:

  1. the NUMBER was 5; the loop has always enforced 3;
  2. the MECHANISM it cited — `CircuitBreaker` — was imported by nothing but its
     own test. `record_tool_call` was called by nothing. The row's *effect* was
     nevertheless true, because an unregistered function-local literal enforced
     it. **The row would have read identically if nothing bounded the loop.**

That second point is why this file exists and why it does not simply assert `== 3`.
A row can be accidentally right. What it must not be is *unconnected to the code*,
because then nobody finds out when the code moves.

**What is asserted, and what deliberately is not.** This does not re-test the cap —
`test_tool_loop_exhaustion` and the eighth-exit locks do that. It asserts that the
NUMBER IN THE ROW is the number the loop actually uses, that the constant is
REACHED by the loop rather than merely existing near it, and that the dead breaker
has not come back.

Structural, not prose-matching: matching the row's wording would fail on an
innocent edit and train people to edit the lock (the #1594 review's lesson).
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_REGISTER = _REPO / "docs" / "governance" / "trust-spine-claim-register.md"
_ENTRYPOINT = _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
_RUNTIME_ROOTS = ("services", "shared", "launcher")


def _row_24() -> str:
    rows = [
        line
        for line in _REGISTER.read_text(encoding="utf-8").splitlines()
        if line.startswith("| 24 |")
    ]
    assert len(rows) == 1, f"expected exactly one row 24, found {len(rows)}"
    return rows[0]


def _loop_bound_name() -> str:
    """The NAME the tool loop's `range()` is given, found by AST.

    Located structurally: a line citation is invalidated the moment somebody adds
    a comment above it, which is exactly how the #1592 citation broke.
    """
    tree = ast.parse(_ENTRYPOINT.read_text(encoding="utf-8"))
    bounds = [
        node.args[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and "TOOL_LOOP" in node.args[0].id
    ]
    assert len(bounds) == 1, (
        f"expected exactly one tool-loop `range(...)` in entrypoint.py, found "
        f"{len(bounds)}. Two loops means two bounds and they can disagree"
    )
    return bounds[0].id


def _loop_bound_value() -> int:
    """What that name is assigned, resolved to an int."""
    from shared.constants import MAX_TOOL_CALL_DEPTH

    name = _loop_bound_name()
    tree = ast.parse(_ENTRYPOINT.read_text(encoding="utf-8"))
    assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
        and node.value is not None
    ]
    assert len(assigns) == 1, (
        f"expected exactly one assignment to {name}, found {len(assigns)}"
    )
    value = assigns[0].value
    if isinstance(value, ast.Constant):
        pytest.fail(
            f"{name} is assigned the LITERAL {value.value!r} rather than reading "
            "shared.constants.MAX_TOOL_CALL_DEPTH. That is the #1596 defect "
            "exactly: the real bound invisible to anything auditing limits while "
            "the registered constant says something else"
        )
    assert isinstance(value, ast.Name) and value.id == "MAX_TOOL_CALL_DEPTH", (
        f"{name} is assigned `{ast.unparse(value)}`; it must read "
        "MAX_TOOL_CALL_DEPTH so there is exactly one name for this bound"
    )
    return MAX_TOOL_CALL_DEPTH


def test_the_loop_bound_is_findable_at_all() -> None:
    """The control on this file: if the loop cannot be located, everything
    below passes vacuously."""
    assert _loop_bound_name(), "no tool-loop range() found in entrypoint.py"


def test_the_loop_READS_the_registered_constant() -> None:
    """Not a literal that happens to agree — the constant itself.

    A literal equal to 3 would satisfy any value assertion while re-creating the
    defect: two places holding the same number until one of them moves.
    """
    assert _loop_bound_value() == 3


def test_row_24_STATES_the_number_the_loop_enforces() -> None:
    """The row said 5 while the loop enforced 3, and nothing noticed for months
    because nothing connected them."""
    row = _row_24()
    match = re.search(r"\*\*(\d+)\*\* chained tool calls", row)
    assert match, (
        "row 24 no longer states the chained-tool-call cap in the expected form "
        "(`**N** chained tool calls`). If the wording changed deliberately, update "
        "this lock in the same commit — the number is how a reader knows the row "
        "was checked against the code"
    )
    stated = int(match.group(1))
    actual = _loop_bound_value()
    assert stated == actual, (
        f"row 24 tells the operator the turn is capped at {stated} chained tool "
        f"calls; the loop enforces {actual}. One of them moved without the other"
    )


def test_row_24_does_not_cite_the_DELETED_breaker_as_the_mechanism() -> None:
    """The row cited `CircuitBreaker`, which ran never.

    The effect it claimed was true anyway — by accident, via a different literal
    — which is precisely why citing a dead mechanism is dangerous: the row reads
    as confirmed.
    """
    row = _row_24()
    evidence = row.split("|")[4]
    assert "Breaker-evaluation errors themselves trip the breaker" not in evidence, (
        "row 24's evidence again claims breaker-evaluation errors trip the "
        "breaker — a fail-closed path that does not execute, because the class "
        "is gone"
    )


def test_the_dead_breaker_has_not_come_BACK() -> None:
    """Structural absence, held.

    Re-adding the class would re-create a second mechanism for a limit already
    enforced — which is the drift #1596 removed, not a strengthening.
    """
    # AST, not a substring: this file's own history is written in comments that
    # NAME the deleted class, and a text match flags those. Matching prose when
    # the claim is about code is the defect this session has now found three
    # times in its own work.
    offenders = []
    for root in _RUNTIME_ROOTS:
        base = _REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a file that does not parse
                continue
            for node in ast.walk(tree):
                defines = (
                    isinstance(node, ast.ClassDef) and node.name == "CircuitBreaker"
                )
                references = (
                    isinstance(node, ast.Name) and node.id == "CircuitBreaker"
                ) or (
                    isinstance(node, ast.Attribute) and node.attr == "CircuitBreaker"
                )
                imports = isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                    a.name == "CircuitBreaker" or a.name.endswith("circuit_breaker")
                    for a in node.names
                )
                if defines or references or imports:
                    offenders.append(str(path.relative_to(_REPO)))
                    break
    assert not offenders, (
        "CircuitBreaker is back in the runtime: "
        + ", ".join(offenders)
        + ". If it was re-added deliberately it must have a production caller and "
        "row 24 must cite it; if it has no caller it is the built-but-wired-into-"
        "nothing shape again"
    )
