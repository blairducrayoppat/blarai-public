"""#1541 / Gap A: an approval binds to the ARGUMENTS, not to the tool's name.

Claim-register row 27: when an escalated action was approved, the approval bound to a
tool name and a rule label — `EscalationContext.from_pa_verdict` produced a summary
literally reading `EXECUTE tool:<name>`. `canonical_hash()` existed and was never called
on the live path. So an approval obtained for one argument set could carry a different
set into execution, and nothing downstream compared them.

These locks drive the REAL helpers rather than mocks. The lesson from #1543 in this same
sprint is the reason: there, every lock passed against a control that production never
reached, because the tests drove a configuration production never used.
"""

from __future__ import annotations

import pytest

from services.assistant_orchestrator.src.entrypoint import (
    _action_identity,
    _build_dispatch_car,
    _escalation_approved_by_operator,
)
from shared.schemas.car import ActionCategory, Reversibility
from shared.security.escalation_consent import ApprovalResult, EscalationContext

_SID = "session-1541"


class TestActionIdentityIsArgumentSensitive:
    """The identity must move with the arguments, or binding to it means nothing."""

    def test_different_arguments_give_different_identities(self) -> None:
        a = _action_identity("search_knowledge", '{"query": "pension"}', _SID)
        b = _action_identity("search_knowledge", '{"query": "passwords"}', _SID)

        assert a and b
        assert a != b, (
            "the action identity ignores the arguments, so an approval for one query "
            "would cover any other — the exact defect Gap A names"
        )

    def test_same_arguments_give_the_same_identity(self) -> None:
        """The toggle: an identity that changed every call would pass the test above
        while refusing every legitimate turn."""
        args = '{"query": "pension"}'
        assert _action_identity("search_knowledge", args, _SID) == _action_identity(
            "search_knowledge", args, _SID
        )

    def test_identity_is_a_sha256_descriptor_carrying_no_payload(self) -> None:
        """No-payload rule: the identity is a descriptor, not a value."""
        secret = "my-passphrase-hunter2"
        identity = _action_identity("search_knowledge", f'{{"query": "{secret}"}}', _SID)

        assert identity.startswith("sha256:")
        assert len(identity) == len("sha256:") + 64
        assert secret not in identity

    def test_identity_survives_session_change(self) -> None:
        """session_id is excluded from the hash, so the same action in two sessions
        binds identically — otherwise the Hello envelope's N=3 lease breaks."""
        args = '{"query": "pension"}'
        assert _action_identity("search_knowledge", args, "s1") == _action_identity(
            "search_knowledge", args, "s2"
        )


class TestDispatchCarCarriesRealExternality:
    """#1545's fields are populated here, so the hash says what the action does."""

    def test_egress_tool_is_classified_as_egress_and_irreversible(self) -> None:
        car = _build_dispatch_car("web_search", '{"query": "x"}', _SID)

        assert car.category is ActionCategory.EGRESS
        assert car.systems_touched == ("network",)
        assert car.reversible is Reversibility.IRREVERSIBLE

    def test_unknown_tool_defaults_to_the_worst_case(self) -> None:
        """Deny-by-default: a tool nobody has classified is not assumed harmless."""
        car = _build_dispatch_car("some_tool_added_next_year", "", _SID)

        assert car.category is ActionCategory.UNKNOWN
        assert car.reversible is Reversibility.IRREVERSIBLE

    def test_local_compute_is_not_marked_egress(self) -> None:
        """The toggle against classifying everything as dangerous: if every tool were
        EGRESS/IRREVERSIBLE the test above would pass while the field said nothing."""
        car = _build_dispatch_car("calculate", '{"expression": "2+2"}', _SID)

        assert car.category is ActionCategory.COMPUTE
        assert car.reversible is Reversibility.REVERSIBLE
        assert car.systems_touched == ()


class TestEscalationApprovalIsRefusedWhenTheIdentityDoesNotMatch:
    """The consent helper refuses an approval that echoes a different identity."""

    @staticmethod
    def _verifier(result: ApprovalResult):
        def _v(_ctx: EscalationContext) -> ApprovalResult:
            return result

        return _v

    def _run(self, monkeypatch: pytest.MonkeyPatch, result: ApprovalResult, identity: str) -> bool:
        import shared.security.escalation_consent as ec

        monkeypatch.setattr(ec, "request_escalation_consent", self._verifier(result))
        return _escalation_approved_by_operator(
            "ESCALATE_TEST", "search_knowledge", action_identity=identity
        )

    def test_matching_identity_is_approved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BASELINE. Without this, a helper that refused everything would pass the
        refusal cases below and the suite would certify a permanently shut door."""
        ident = _action_identity("search_knowledge", '{"query": "pension"}', _SID)
        approved = ApprovalResult.allow(verifier_identity="test", action_identity=ident)

        assert self._run(monkeypatch, approved, ident) is True

    def test_mismatched_echo_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE LOCK. A verifier that approves a DIFFERENT action is refused."""
        presented = _action_identity("search_knowledge", '{"query": "pension"}', _SID)
        other = _action_identity("search_knowledge", '{"query": "passwords"}', _SID)
        approved = ApprovalResult.allow(verifier_identity="test", action_identity=other)

        assert self._run(monkeypatch, approved, presented) is False

    def test_absent_echo_is_NOT_refused_here(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SCOPE, and the reason this is not a hole.

        Requiring every verifier to echo would break the verifier contract, and it is
        not what closes Gap A. The binding is closed by the DISPATCHER re-deriving the
        identity from the arguments about to execute: approve set A, dispatch B, and
        re-derived(B) never equals presented(A), echo or no echo. The echo check is
        defence-in-depth against a verifier that actively approves a DIFFERENT action
        (the ACS §9 rule, AH-CTK-072), not the load-bearing control.
        """
        presented = _action_identity("search_knowledge", '{"query": "pension"}', _SID)
        approved = ApprovalResult.allow(verifier_identity="test", action_identity="")

        assert self._run(monkeypatch, approved, presented) is True

    def test_non_tool_escalation_without_an_identity_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SCOPE. The helper checks a MISMATCH, not presence.

        `EscalationContext` documents tool_name as "empty for non-tool escalations",
        and those have no CAR to hash. Refusing them here would break a documented
        contract to close a hole that is not theirs. The requirement that a TOOL
        dispatch must carry an identity is enforced in the tool loop, which is the
        caller that always has one.
        """
        approved = ApprovalResult.allow(verifier_identity="test")

        assert self._run(monkeypatch, approved, "") is True

    def test_denial_is_still_a_denial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ident = _action_identity("search_knowledge", '{"query": "pension"}', _SID)
        denied = ApprovalResult.deny("operator denied", verifier_identity="test")

        assert self._run(monkeypatch, denied, ident) is False


class TestApprovalResultCarriesWhatItApproved:
    """The dataclasses must actually hold the field, or everything above is theatre."""

    def test_context_carries_the_identity(self) -> None:
        ctx = EscalationContext.from_pa_verdict(
            "ESCALATE_TEST", tool_name="web_search", action_identity="sha256:" + "a" * 64
        )
        assert ctx.action_identity == "sha256:" + "a" * 64

    def test_context_default_is_empty_not_absent(self) -> None:
        ctx = EscalationContext.from_pa_verdict("ESCALATE_TEST", tool_name="web_search")
        assert ctx.action_identity == ""

    def test_approval_result_echoes_the_identity(self) -> None:
        r = ApprovalResult.allow(verifier_identity="tui", action_identity="sha256:" + "b" * 64)
        assert r.approved is True
        assert r.action_identity == "sha256:" + "b" * 64

    def test_deny_carries_no_approved_identity(self) -> None:
        r = ApprovalResult.deny("timeout")
        assert r.approved is False
        assert r.action_identity == ""
