# enforces-rule: security_by_design.principles.single-adjudication-door -- door verdicts only
"""Gate: every consumer of the single adjudication door REFUSES a verdict it
does not recognise (#1604).

`DeterministicPolicyChecker.check` returns ``("DENY", rule)``, ``("ESCALATE",
rule)`` or ``None``, and **allow is the absence of a verdict**, not a verdict
string. That shape is what makes an unrecognised tuple safe: it is already
non-None, and every consumer's non-None path refuses unless it recognises the
word.

WHY THIS FILE EXISTS. #1548 added a fourth route outcome in the tool loop and
declined to wire it into the door, recording in its closing comment that "a
fourth verdict falls through ``if verdict == "DENY"`` into an implicit allow".
That claim was false -- measured against all four consumers -- but nobody could
tell, because **nothing asserted the behaviour either way**. The claim survived
into a follow-up ticket's description before anyone drove the code.

So the consumers are fail-closed, correctly, and **by accident**: no test pins
it, and any one of these branches could be rewritten into an allow without a
single failure. This file makes the refusal deliberate.

The catch-all arms being locked, one per consumer:

  * ``url_adjudicator``  -- the final ``return AdjudicationDecision.DENY``
  * ``GPUClassificationResult.passed`` -- ``label == "ALLOW"``, exactly
  * ``adjudicator``      -- the arm the source itself labels ``# Default: DENY``
  * AO tool dispatch     -- the ``else`` that writes a deny receipt and breaks

Each is checked twice: the behaviour is DRIVEN through the real object, and the
structure that produces it is asserted, so a refactor that keeps the behaviour
by luck is still caught. The toggle tests mutate a COPY of the source and prove
the structural assertions flip -- never the tree.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ENTRYPOINT = (
    _REPO / "services" / "assistant_orchestrator" / "src" / "entrypoint.py"
)
_URL_ADJUDICATOR = _REPO / "services" / "ui_gateway" / "src" / "url_adjudicator.py"
_PA_ADJUDICATOR = _REPO / "services" / "policy_agent" / "src" / "adjudicator.py"

#: A verdict no consumer has ever been written to handle. The string is
#: deliberately the one #1548 would have used, so this file also documents what
#: would happen if the door's contract were extended without updating consumers.
UNKNOWN_VERDICT: tuple[str, str] = ("SIMULATE_FIRST", "RULE_SIMULATE_FIRST")


# ---------------------------------------------------------------------------
# The contract that makes the rest of it work.
# ---------------------------------------------------------------------------


def test_allow_is_the_ABSENCE_of_a_verdict_not_a_verdict() -> None:
    """The load-bearing property. If ``check`` ever returned ``("ALLOW", rule)``
    instead of ``None``, every consumer below would need re-reading, because an
    unrecognised tuple could then plausibly be an allow."""
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker

    source = ast.get_source_segment(
        _PA_GPU_SRC := (
            _REPO / "services" / "policy_agent" / "src" / "gpu_inference.py"
        ).read_text(encoding="utf-8"),
        next(
            node for node in ast.walk(ast.parse(_PA_GPU_SRC))
            if isinstance(node, ast.FunctionDef) and node.name == "check"
        ),
    )
    assert source is not None
    assert 'return ("DENY"' in source or "'DENY'" in source, (
        "check no longer returns a DENY tuple; this gate's model of the door is stale"
    )
    assert '("ALLOW"' not in source, (
        "check now returns an ALLOW verdict. Allow used to be None, and every "
        "consumer lock in this file assumes an unrecognised tuple cannot be an "
        "allow. Re-read all four before deleting this assertion."
    )
    assert DeterministicPolicyChecker.check.__doc__ is not None


# ---------------------------------------------------------------------------
# Consumer 1 - the egress door.
# ---------------------------------------------------------------------------


def test_the_egress_door_denies_an_unknown_verdict() -> None:
    """Driven through the REAL adjudicator factory, not a stub."""
    from services.policy_agent.src.gpu_inference import DeterministicPolicyChecker
    from services.ui_gateway.src.url_adjudicator import (
        make_request_keyed_url_adjudicate,
        make_url_adjudicator,
    )

    with patch.object(
        DeterministicPolicyChecker,
        "check",
        classmethod(lambda cls, car, **kw: UNKNOWN_VERDICT),
    ):
        decision = make_url_adjudicator(make_request_keyed_url_adjudicate())(
            "https://kagi.com/search?q=x", "web_search"
        )

    assert decision.name == "DENY", (
        f"the egress door returned {decision.name} for a verdict it has never "
        "seen. Its catch-all arm must refuse."
    )


def test_the_egress_doors_catch_all_arm_is_a_refusal() -> None:
    """Structure, so a refactor cannot keep the behaviour by luck."""
    assert _catch_all_returns_deny(_URL_ADJUDICATOR.read_text(encoding="utf-8"))


def _catch_all_returns_deny(source: str) -> bool:
    """True iff ``_adjudicate``'s final statement is a DENY return."""
    tree = ast.parse(source)
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_adjudicate"
    )
    last = fn.body[-1]
    if not isinstance(last, ast.Return) or last.value is None:
        return False
    return "DENY" in (ast.get_source_segment(source, last.value) or "")


def test_the_egress_door_structural_check_FAILS_on_a_permissive_arm() -> None:
    """Toggle. Mutates a COPY; the tree is never touched."""
    permissive = _URL_ADJUDICATOR.read_text(encoding="utf-8").replace(
        "return AdjudicationDecision.DENY", "return AdjudicationDecision.ALLOW"
    )
    assert not _catch_all_returns_deny(permissive), (
        "the structural check passed against a source whose catch-all ALLOWS, "
        "so it is not reading the arm it claims to read"
    )


# ---------------------------------------------------------------------------
# Consumer 2 - the Policy-Agent result's own allow gate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label", ["SIMULATE_FIRST", "ALLOW_WITH_CONDITIONS", "allow", "", "DENY"]
)
def test_only_the_exact_word_ALLOW_passes(label: str) -> None:
    from services.policy_agent.src.gpu_inference import GPUClassificationResult

    result = GPUClassificationResult(
        label=label, confidence=1.0, latency_ms=0.0, error=None
    )
    assert result.passed is False, (
        f"label {label!r} at full confidence was treated as an allow. Only the "
        "exact string 'ALLOW' may pass -- a near-miss is a refusal."
    )


def test_the_exact_word_ALLOW_does_still_pass() -> None:
    """The other half: a lock that refuses everything proves nothing."""
    from services.policy_agent.src.gpu_inference import GPUClassificationResult

    assert GPUClassificationResult(
        label="ALLOW", confidence=1.0, latency_ms=0.0, error=None
    ).passed is True


# ---------------------------------------------------------------------------
# Consumer 3 - the Policy-Agent decision ladder.
# ---------------------------------------------------------------------------


def test_the_pa_ladders_final_arm_is_DENY() -> None:
    """The arm an unknown label falls to: not ``passed``, not in the escalate
    range, so the ladder's default. The source names it ``# Default: DENY``."""
    assert _ladder_default_is_deny(_PA_ADJUDICATOR.read_text(encoding="utf-8"))


def _ladder_default_is_deny(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        last = node.body[-1]
        if not isinstance(last, ast.Return) or last.value is None:
            continue
        segment = ast.get_source_segment(source, last.value) or ""
        if "DecisionArtifact" in segment and "AdjudicationDecision" in segment:
            return "DENY" in segment
    return False


def test_the_pa_ladder_structural_check_FAILS_on_a_permissive_default() -> None:
    """Toggle, on a copy."""
    source = _PA_ADJUDICATOR.read_text(encoding="utf-8")
    marker = "# Default: DENY"
    assert marker in source, "the ladder's default arm is no longer where this gate looks"
    head, _, tail = source.partition(marker)
    permissive = head + marker + tail.replace(
        "decision=AdjudicationDecision.DENY",
        "decision=AdjudicationDecision.ALLOW",
        1,
    )
    assert not _ladder_default_is_deny(permissive), (
        "the structural check passed against a ladder whose default ALLOWS"
    )


# ---------------------------------------------------------------------------
# Consumer 4 - the Assistant Orchestrator's tool-dispatch branch.
# ---------------------------------------------------------------------------


def test_the_dispatch_branch_refuses_anything_that_is_not_an_approved_ESCALATE() -> None:
    """The one consumer that cannot be driven in isolation -- it lives inside a
    700-line request handler -- so it is asserted structurally, in both halves:
    the ``else`` exists, it records the refusal, and it leaves the loop.
    """
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    node = _escalate_branch(source)
    assert node is not None, (
        "the ESCALATE dispatch branch was not found; this gate is measuring nothing"
    )
    assert node.orelse, (
        "the dispatch branch has no else. A verdict that is neither None nor an "
        "approved ESCALATE would fall through to execute the tool."
    )
    dumped = ast.dump(ast.Module(body=node.orelse, type_ignores=[]))
    assert "_audit_verdict" in dumped, "the refusal arm writes no receipt"
    assert "Break" in dumped, (
        "the refusal arm does not leave the tool loop, so the dispatch continues"
    )


def _escalate_branch(source: str) -> ast.If | None:
    """Locate the dispatch branch, quote-agnostically.

    Matched via ``ast.unparse`` rather than the raw source segment: the toggle
    below round-trips the tree, and unparse normalises string quoting, so a
    matcher keyed on `== "ESCALATE"` finds nothing in the rebuilt source and the
    toggle passes for the wrong reason. Caught by that toggle on its first run.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp):
            segment = ast.unparse(node.test)
            if "_pa_decision" in segment and "ESCALATE" in segment:
                return node
    return None


def test_the_dispatch_structural_check_FAILS_without_the_else() -> None:
    """Toggle, on a copy: strip the else and the assertions must flip."""
    source = _ENTRYPOINT.read_text(encoding="utf-8")
    node = _escalate_branch(source)
    assert node is not None
    stripped = ast.parse(source)
    for candidate in ast.walk(stripped):
        if isinstance(candidate, ast.If) and isinstance(candidate.test, ast.BoolOp):
            segment = ast.unparse(candidate.test)
            if "_pa_decision" in segment and "ESCALATE" in segment:
                candidate.orelse = []
    rebuilt = _escalate_branch(ast.unparse(stripped))
    assert rebuilt is not None and not rebuilt.orelse, (
        "the toggle did not remove the else, so it proves nothing"
    )


# ---------------------------------------------------------------------------
# The claim this file was written to retire.
# ---------------------------------------------------------------------------


def test_no_consumer_treats_an_unknown_verdict_as_an_allow() -> None:
    """#1548 comment 3544 asserted the opposite, and #1604's description repeated
    it. Both were wrong, and neither could be checked because nothing asserted
    the behaviour. This is that assertion.
    """
    from services.policy_agent.src.gpu_inference import (
        DeterministicPolicyChecker,
        GPUClassificationResult,
    )
    from services.ui_gateway.src.url_adjudicator import (
        make_request_keyed_url_adjudicate,
        make_url_adjudicator,
    )

    with patch.object(
        DeterministicPolicyChecker,
        "check",
        classmethod(lambda cls, car, **kw: UNKNOWN_VERDICT),
    ):
        egress = make_url_adjudicator(make_request_keyed_url_adjudicate())(
            "https://kagi.com/search?q=x", "web_search"
        )

    pa = GPUClassificationResult(
        label=UNKNOWN_VERDICT[0], confidence=1.0, latency_ms=0.0, error=None
    )

    assert egress.name == "DENY"
    assert pa.passed is False
    assert _ladder_default_is_deny(_PA_ADJUDICATOR.read_text(encoding="utf-8"))
    branch = _escalate_branch(_ENTRYPOINT.read_text(encoding="utf-8"))
    assert branch is not None and branch.orelse
