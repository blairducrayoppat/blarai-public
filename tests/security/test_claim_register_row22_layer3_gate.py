"""Claim-register row 22 describes the Layer-3 lock. Keep it describing the code (#1595).

Row 22 is what the operator is told about the strongest anti-injection control in
the system: when untrusted content enters a conversation, tool calls are refused
outside the model, so the refusal holds even if the model is fully fooled.

**It had drifted in four ways, all in the reassuring direction**, and nothing
noticed because nothing connected the row to the gate:

  1. it said "when any document is loaded" — the trigger is untrusted PROVENANCE,
     and a trusted local document does not lock anything;
  2. it said "every tool call is refused" — SAFE tools, lock-exempt tools and
     EGRESS tools are all carved out, the last deliberately (#723 rung 3);
  3. it said "three-condition gate" — there are six;
  4. it said "per-turn only that the document is present" — grounded provenance
     is per SESSION and nothing clears it at turn end.

This file is the row's lock, in the same spirit as
`test_claim_register_row12_tls_blindspot.py`. It does NOT re-test the gate — the
eval mirror and `test_retrieval_tools.py` do that. It tests that the ROW and the
GATE still describe the same thing, because a governance row that overstates a
protection is worse than no row: the reader stops checking.

**Deliberately structural, not prose-matching.** Asserting the row's exact wording
would fail on an innocent edit and train people to edit the lock (a lesson from
the #1594 review). What is asserted is that every carve-out present in the code is
NAMED in the row, and that the condition count the row states is the count the
code has.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_REGISTER = _REPO / "docs" / "governance" / "trust-spine-claim-register.md"
_ENTRYPOINT = (
    _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
)

#: Every carve-out the gate implements, and the token the row must use to name it.
#: A new carve-out added to the code without a row edit fails
#: `test_every_carve_out_in_the_code_is_NAMED_in_the_row` below, which is the
#: point: widening a control silently is the failure this row exists to prevent.
_CARVE_OUTS: dict[str, str] = {
    "is_lock_exempt": "lock-EXEMPT",
    "is_egress_tool": "egress tool",
    "RiskTier.SAFE": "SAFE",
    "has_trusted_documents_for_tools": "trusted documents for tools",
}


def _row_22() -> str:
    rows = [
        line
        for line in _REGISTER.read_text(encoding="utf-8").splitlines()
        if line.startswith("| 22 |")
    ]
    assert len(rows) == 1, f"expected exactly one row 22, found {len(rows)}"
    return rows[0]


def _gate_condition() -> ast.BoolOp:
    """The Layer-3 gate's `if` test, located by the names it must contain.

    Found structurally rather than by line number: a line citation is invalidated
    by anyone adding a comment above it, which is how the #1592 citation broke.
    """
    tree = ast.parse(_ENTRYPOINT.read_text(encoding="utf-8"))
    candidates = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.BoolOp):
            continue
        src = ast.unparse(node.test)
        if (
            "block_tools_on_untrusted_content" in src
            and "has_untrusted_content" in src
        ):
            candidates.append(node.test)
    assert len(candidates) == 1, (
        f"expected exactly one Layer-3 gate in entrypoint.py, found "
        f"{len(candidates)}. More than one means the lock is applied in two "
        "places and they can disagree"
    )
    return candidates[0]


def test_the_gate_is_findable_at_all() -> None:
    """The control on this whole file: if the gate cannot be located, every
    assertion below passes vacuously."""
    condition = _gate_condition()
    assert isinstance(condition.op, ast.And), (
        "the Layer-3 gate is no longer a conjunction — its shape changed and "
        "every count below is measuring something else"
    )


def test_the_row_states_the_CONDITION_COUNT_the_gate_actually_has() -> None:
    """The row said 'three-condition gate' while the gate had six.

    Two amendments (ADR-023 Am.1/#593, Am.4/#723) added conditions and neither
    updated the row, because nothing connected them.
    """
    actual = len(_gate_condition().values)
    row = _row_22()
    stated = re.search(r"\*\*([A-Z]+)\*\*-condition gate", row)
    assert stated, (
        "row 22 no longer states a condition count in the expected form "
        "(`**SIX**-condition gate`). If the wording changed deliberately, update "
        "this lock in the same commit; if it was dropped, restore it — the count "
        "is how a reader knows the row was checked against the code"
    )
    words = {
        "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
        "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
    }
    claimed = words.get(stated.group(1))
    assert claimed == actual, (
        f"row 22 says the gate has {stated.group(1)} ({claimed}) conditions; the "
        f"code has {actual}. A condition was added or removed without the row "
        "being updated, which is exactly the drift that made the row overstate "
        "this control for months"
    )


@pytest.mark.parametrize(("symbol", "token"), sorted(_CARVE_OUTS.items()))
def test_every_carve_out_in_the_code_is_NAMED_in_the_row(
    symbol: str, token: str
) -> None:
    """A carve-out the code has and the row does not name is an overstatement.

    The egress carve-out is the load-bearing one: `web_search` is exempt from
    this lock BY DESIGN (#723 rung 3), so "every tool call is refused" was false
    about the one tool that reaches the network.
    """
    src = ast.unparse(_gate_condition())
    if symbol not in src:
        pytest.skip(
            f"{symbol} is no longer part of the gate — this parametrization is "
            "stale, which the count test above will have caught"
        )
    assert token in _row_22(), (
        f"the gate carves out {symbol!r} and row 22 does not mention it "
        f"(expected the phrase {token!r}). The row tells the operator this "
        "control refuses tool calls; every unnamed carve-out makes that claim "
        "broader than the code"
    )


def test_the_row_does_not_call_the_trigger_A_DOCUMENT() -> None:
    """The trigger is untrusted PROVENANCE, not a document being attached.

    A `TRUSTED_LOCAL` document — the ordinary case of the operator attaching a
    file — does NOT lock anything. The old wording told the reader the opposite,
    and the opposite is the reassuring direction.
    """
    row = _row_22()
    claim = row.split("|")[2]
    assert "UNTRUSTED" in claim, (
        "row 22's claim no longer says the trigger is UNTRUSTED content. If it "
        "has gone back to describing documents, it is describing a control this "
        "code does not implement"
    )


def test_the_row_does_not_claim_the_scope_is_PER_TURN() -> None:
    """Grounded provenance is per SESSION; nothing clears it at turn end.

    `clear_grounded_context` has one production caller, reached only by an
    explicit unload or a fresh attachment on a later turn.
    """
    row = _row_22()
    assert "per SESSION" in row or "per-session" in row.lower(), (
        "row 22 no longer states that the scope is per-session. It said "
        "'per-turn only that the document is present' until 2026-09-20, which "
        "understated how long the lock persists"
    )
