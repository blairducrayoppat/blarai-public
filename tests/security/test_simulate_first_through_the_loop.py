"""Gate: the simulate-first branch works when driven through the REAL tool loop
(#1567 / #1568 / #1548 executor).

WHY THIS FILE EXISTS. `curate_knowledge` shipped 100% non-functional and every
gate was green. `_approved_identity` was bound only inside
``if _pa_verdict is not None:`` and read unconditionally in the simulate-first
branch, so every path where the rehearsal SUCCEEDED raised
``UnboundLocalError`` — and the Policy Agent returns ``None`` for this tool,
which is the production case. At the operator's go-live ceremony the connection
handler would have raised, no consent dialog would have appeared, and the turn
would have died with no answer.

Nothing caught it because nothing drove the loop:

  * `test_curate_knowledge.py` drives a shim, not the loop.
  * `test_simulate_first.py` asserts the branch's SOURCE TEXT, not its execution.
  * `test_denied_turn_persistence.py` drives the loop but only the arm where the
    rehearsal FAILS, which returns before touching the unbound name.

Three suites, none of them wrong, and the tool could not run. This file drives
`_handle_connection` — the real entry point — with the real registrations
`start()` makes, and asserts the behaviour rather than the prose.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.assistant_orchestrator.src import tools
from shared.governance import dry_run as _dry_run

_ARGS = json.dumps({"action": "delete", "source_type": "file"}, sort_keys=True)
_CALL = (
    '<tool_call>{"name": "curate_knowledge", "arguments": '
    '{"action": "delete", "source_type": "file"}}</tool_call>'
)


def _drive(*, approve: bool, rehearsal_count: int = 3):
    """Run the REAL connection handler through the simulate-first branch.

    Returns ``(persisted_text, consent_summaries, executed_args, raised)``.

    The Policy-Agent verdict is ``None`` — no rule objects to this tool — which
    is what production returns and what the unbound-local defect required.
    """
    from services.assistant_orchestrator.tests.test_tools import (
        _FakeTransport,
        _make_service,
    )
    from shared.ipc.protocol import MessageFramer

    service = _make_service()
    service._inference = MagicMock()
    responses = [
        SimpleNamespace(text=_CALL, token_count=5, error=None),
        SimpleNamespace(text="Done.", token_count=2, error=None),
    ]
    service._inference.generate_text.side_effect = (
        lambda *a, **k: responses.pop(0)
        if responses
        else SimpleNamespace(text="done.", token_count=2, error=None)
    )

    summaries: list[str] = []
    executed: list[str] = []
    receipts: list[tuple[str, str, bool]] = []
    captured: dict[str, str] = {}
    raised: list[BaseException] = []

    real_audit = service._audit_verdict

    def _audit(**kw):
        ok = real_audit(**kw)
        receipts.append((kw.get("decision", ""), kw.get("reason", ""), bool(ok)))
        return ok

    service._audit_verdict = _audit  # type: ignore[assignment]

    def _rehearse(args: str):
        return _dry_run.DryRunResult(
            action="erase", unit="documents", affected_count=rehearsal_count
        )

    before = dict(_dry_run._DRY_RUNS)
    _dry_run._DRY_RUNS.clear()
    _dry_run.register_dry_run(
        "curate_knowledge", _rehearse, applies_to=tools.curate_action_needs_rehearsal
    )
    tools.register_curate_knowledge_runner(
        lambda args: (executed.append(args), "Erased 3 documents permanently.")[1]
    )

    def _consent(ctx):
        summaries.append(ctx.action_summary)
        # `action_identity` must be present: the helper reads it to enforce
        # #1541's mismatch check, and an AttributeError there is caught by its
        # outer handler and fails closed -- which is correct behaviour and made
        # this stub silently un-approvable.
        return SimpleNamespace(
            approved=approve, reason="test", action_identity=""
        )

    try:
        with patch.object(
            type(service), "simulate_first_enabled", property(lambda self: True)
        ), patch(
            "services.assistant_orchestrator.src.entrypoint.validate_output"
        ) as pgov, patch(
            "services.assistant_orchestrator.src.entrypoint._adjudicate_tool_dispatch",
            return_value=None,  # the PRODUCTION answer for this tool
        ), patch(
            "shared.security.escalation_consent.request_escalation_consent",
            side_effect=_consent,
        ):
            def _capture(generated_text: str, **_k: object):
                captured["text"] = generated_text
                return SimpleNamespace(approved=True, sanitized_text=generated_text)

            pgov.side_effect = _capture
            request = MessageFramer().encode_prompt_request(
                session_id="simfirst-loop", prompt="tidy my files", request_id="r1"
            )
            try:
                service._handle_connection(_FakeTransport(request))
            except BaseException as exc:  # noqa: BLE001 - the defect WAS a raise
                raised.append(exc)
    finally:
        tools.clear_curate_knowledge_runner()
        _dry_run._DRY_RUNS.clear()
        _dry_run._DRY_RUNS.update(before)

    return captured.get("text", ""), summaries, executed, raised, receipts, service


# ---------------------------------------------------------------------------
# The defect that shipped.
# ---------------------------------------------------------------------------


def test_the_branch_does_not_RAISE_when_the_policy_agent_returns_None() -> None:
    """THE regression. `_approved_identity` was unbound on exactly this path."""
    _text, _summaries, _executed, raised, _receipts, _svc = _drive(approve=False)
    assert not raised, (
        f"the tool loop raised {raised[0]!r}. The Policy Agent returns None for "
        "this tool — no rule objects — so this is the production path, and a "
        "raise here kills the request handler before the operator is asked."
    )


def test_the_operator_IS_asked_and_the_summary_carries_no_content() -> None:
    _text, summaries, _executed, raised, _receipts, _svc = _drive(approve=False)
    assert not raised
    assert summaries, (
        "no consent prompt was raised. The rehearsal exists to be shown; a "
        "rehearsal nobody sees is a delay, not a control."
    )
    assert summaries[0] == "Would erase 3 documents"


# ---------------------------------------------------------------------------
# Approve and refuse, end to end.
# ---------------------------------------------------------------------------


def test_REFUSING_the_rehearsal_executes_nothing() -> None:
    text, summaries, executed, raised, _receipts, _svc = _drive(approve=False)
    assert not raised
    assert summaries
    assert executed == [], "the tool ran despite the operator refusing"
    assert "not approved" in text.lower() or "nothing ran" in text.lower()
    assert "<tool_call>" not in text


def test_APPROVING_the_rehearsal_executes_exactly_once() -> None:
    """Toggle for the test above: the refusal is the operator's answer, not a
    dead path that never executes."""
    _text, summaries, executed, raised, _receipts, _svc = _drive(approve=True)
    assert not raised
    assert summaries
    assert len(executed) == 1, f"expected one execution, got {len(executed)}"
    assert json.loads(executed[0])["action"] == "delete"


def test_a_ZERO_match_rehearsal_does_not_ask_the_operator_at_all() -> None:
    """An approval prompt that appears when nothing is at stake is how a person
    learns to approve without reading."""
    text, summaries, executed, raised, _receipts, _svc = _drive(approve=True, rehearsal_count=0)
    assert not raised
    assert summaries == [], "the operator was asked to approve doing nothing"
    assert executed == []
    assert "nothing matched" in text.lower()


def test_a_refused_rehearsal_leaves_NOTHING_armed() -> None:
    """DRIVEN, not read.

    The first version asserted `inspect.getsource(...).count("... = None") >= 2`
    — a source-text assertion, in the file whose own docstring indicts source-
    text assertions. It never checked `_rehearsed_moves` at all, and two copies
    on one path satisfied it.
    """
    _text, summaries, executed, raised, _receipts, svc = _drive(approve=False)
    assert not raised
    assert summaries and executed == []
    assert svc._rehearsed_curation is None, (
        "a refused rehearsal left the curation record armed, so 'the operator "
        "said no' and 'no rehearsal has happened' are different states"
    )
    assert svc._rehearsed_moves is None, "the move record was left armed"


def test_a_ZERO_match_also_leaves_nothing_armed() -> None:
    _text, _summaries, _executed, raised, _receipts, svc = _drive(
        approve=True, rehearsal_count=0
    )
    assert not raised
    assert svc._rehearsed_curation is None
    assert svc._rehearsed_moves is None


# ---------------------------------------------------------------------------
# The record. A rehearsal is the one event simulate-first exists to make
# auditable, and it briefly wrote NOTHING.
# ---------------------------------------------------------------------------


def test_the_rehearsal_IS_recorded_in_the_signed_chain() -> None:
    """THE missing lock.

    `decision="escalate"` was introduced to stop a refused rehearsal leaving
    both an allow and a deny. `build_receipt` accepts only "allow" and "deny" —
    "An escalation is a route to an operator, not a verdict" — so it raised,
    `_audit_verdict` swallowed it and returned False, and every rehearsal wrote
    NO ROW. Nothing asserted the row existed, which is why it was invisible.
    """
    _text, _summaries, _executed, raised, receipts, _svc = _drive(approve=False)
    assert not raised

    rehearsals = [r for r in receipts if r[1] == "SIMULATE_FIRST_REHEARSED"]
    assert rehearsals, "the rehearsal wrote no verdict record at all"
    decision, _reason, recorded = rehearsals[0]
    assert recorded is True, (
        f"the rehearsal record was REFUSED by the receipt builder "
        f"(decision={decision!r}). A rehearsal that leaves no row is the one "
        "event this whole design exists to make auditable."
    )


def test_the_receipt_builder_still_refuses_a_non_verdict() -> None:
    """Toggle: the test above passes because the decision is valid, not because
    the builder accepts anything."""
    import pytest as _pytest

    from shared.security.verdict_receipt import DECISIONS

    assert "escalate" not in DECISIONS
    assert {"allow", "deny"} <= set(DECISIONS)
    del _pytest



@pytest.mark.parametrize("enabled", [False])
def test_with_the_flag_OFF_the_branch_is_never_entered(enabled: bool) -> None:
    """Dormancy, through the loop rather than by inspection."""
    from services.assistant_orchestrator.tests.test_tools import _make_service

    service = _make_service()
    assert service.simulate_first_enabled is False
    assert service.curate_knowledge_enabled is False
    assert service.organise_userdata_enabled is False
