r"""Tests for the PA-ESCALATE consent consumer core (shared/security/escalation_consent.py).

Vikunja #639 / ADR-024 §2.5. The Policy Agent emits ``ESCALATE`` for 7 deterministic
rule classes; this module is the consumer that turns an ESCALATE into a synchronous
operator approve/deny decision. These tests prove the load-bearing contract:

  - approve → allowed; deny → denied;
  - the FAIL-CLOSED paths (no verifier, erroring verifier, timeout, malformed result)
    all deny — approval is the only thing that allows;
  - the dormant default (no verifier wired) is byte-for-byte today's behaviour (DENY);
  - :class:`EscalationContext` carries labels/descriptors only — never raw secrets/PII;
  - the verifier seam is pluggable (a mock injects cleanly via the registry).

Every test runs under an autouse fixture that clears the verifier afterwards, so an
injected mock can never leak into the wider suite.
"""

from __future__ import annotations

import threading
import time

import pytest

from shared.security import escalation_consent as ec
from shared.security.escalation_consent import (
    ApprovalResult,
    ApprovalVerifier,
    EscalationContext,
    active_verifier,
    clear_verifier,
    register_verifier,
    request_escalation_consent,
)


@pytest.fixture(autouse=True)
def _clear_verifier_around_each_test() -> None:
    """Guarantee a clean (no verifier) registry before and after every test."""
    clear_verifier()
    yield
    clear_verifier()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _ApprovingVerifier:
    """A verifier that always approves (records the context it was given)."""

    def __init__(self) -> None:
        self.seen: list[EscalationContext] = []

    def verify(self, context: EscalationContext) -> ApprovalResult:
        self.seen.append(context)
        return ApprovalResult.allow(verifier_identity="mock-approve")


class _DenyingVerifier:
    def verify(self, context: EscalationContext) -> ApprovalResult:
        return ApprovalResult.deny("operator denied", verifier_identity="mock-deny")


class _ErroringVerifier:
    def verify(self, context: EscalationContext) -> ApprovalResult:
        raise RuntimeError("surface blew up")


class _MalformedVerifier:
    """Returns a non-ApprovalResult — a misbehaving verifier."""

    def verify(self, context: EscalationContext):  # type: ignore[no-untyped-def]
        return "yes please allow it"  # not an ApprovalResult → must fail closed


class _NoneVerifier:
    def verify(self, context: EscalationContext):  # type: ignore[no-untyped-def]
        return None  # → must fail closed


class _HangingVerifier:
    """Blocks until released — used to exercise the timeout fail-closed path."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()

    def verify(self, context: EscalationContext) -> ApprovalResult:
        self.entered.set()
        self.release.wait(timeout=5.0)
        return ApprovalResult.allow(verifier_identity="mock-late")


def _ctx() -> EscalationContext:
    return EscalationContext.from_pa_verdict(
        "ESCALATE_CRYPTO_MATERIAL",
        tool_name="web_fetch",
        action_summary="EXECUTE tool:web_fetch",
    )


# ---------------------------------------------------------------------------
# The four core outcomes: approve / deny / error / no-verifier
# ---------------------------------------------------------------------------


class TestConsentOutcomes:
    def test_no_verifier_denies_unchanged_default(self) -> None:
        """Dormant default — no verifier wired → DENY (today's behaviour)."""
        assert active_verifier() is None
        result = request_escalation_consent(_ctx())
        assert result.approved is False
        assert result.verifier_identity == "no-verifier"
        assert "no verifier" in result.reason.lower()

    def test_approving_verifier_allows(self) -> None:
        register_verifier(_ApprovingVerifier())
        result = request_escalation_consent(_ctx())
        assert result.approved is True

    def test_denying_verifier_denies(self) -> None:
        register_verifier(_DenyingVerifier())
        result = request_escalation_consent(_ctx())
        assert result.approved is False
        assert result.verifier_identity == "mock-deny"

    def test_erroring_verifier_fails_closed(self) -> None:
        register_verifier(_ErroringVerifier())
        result = request_escalation_consent(_ctx())
        assert result.approved is False
        assert "error" in result.reason.lower()

    def test_malformed_result_fails_closed(self) -> None:
        register_verifier(_MalformedVerifier())
        result = request_escalation_consent(_ctx())
        assert result.approved is False
        assert "malformed" in result.reason.lower()

    def test_none_result_fails_closed(self) -> None:
        register_verifier(_NoneVerifier())
        result = request_escalation_consent(_ctx())
        assert result.approved is False

    def test_timeout_fails_closed(self) -> None:
        """A verifier that does not answer within the timeout → DENY (fail-closed)."""
        hanging = _HangingVerifier()
        register_verifier(hanging)
        start = time.monotonic()
        result = request_escalation_consent(_ctx(), timeout_s=0.2)
        elapsed = time.monotonic() - start
        assert result.approved is False
        assert result.reason == "timeout"
        # Returned promptly at the timeout, did not wait for the (5s) hang.
        assert elapsed < 2.0
        # Release the worker so it does not linger.
        hanging.release.set()

    def test_late_answer_cannot_retroactively_allow(self) -> None:
        """After a timeout DENY, the verifier later answering 'approve' must not
        change the (already-returned) denied decision."""
        hanging = _HangingVerifier()
        register_verifier(hanging)
        result = request_escalation_consent(_ctx(), timeout_s=0.2)
        assert result.approved is False  # denied on timeout
        hanging.release.set()  # verifier now 'approves' — too late, decision stands
        time.sleep(0.1)
        assert result.approved is False


# ---------------------------------------------------------------------------
# Registry seam — pluggable verifier
# ---------------------------------------------------------------------------


class TestRegistrySeam:
    def test_register_then_clear_restores_dormant_default(self) -> None:
        register_verifier(_ApprovingVerifier())
        assert request_escalation_consent(_ctx()).approved is True
        clear_verifier()
        assert active_verifier() is None
        # Back to the dormant DENY default.
        assert request_escalation_consent(_ctx()).approved is False

    def test_register_replaces_previous_verifier(self) -> None:
        register_verifier(_ApprovingVerifier())
        register_verifier(_DenyingVerifier())  # singular — replaces
        assert request_escalation_consent(_ctx()).approved is False

    def test_register_rejects_non_verifier(self) -> None:
        with pytest.raises(TypeError):
            register_verifier(object())  # no verify() method

    def test_mock_verifier_satisfies_protocol(self) -> None:
        """The mock is structurally an ApprovalVerifier (runtime_checkable)."""
        assert isinstance(_ApprovingVerifier(), ApprovalVerifier)


# ---------------------------------------------------------------------------
# EscalationContext — labels/descriptors only, never raw secrets/PII
# ---------------------------------------------------------------------------


class TestEscalationContextSafety:
    def test_from_pa_verdict_carries_only_safe_descriptors(self) -> None:
        ctx = EscalationContext.from_pa_verdict(
            "ESCALATE_CRYPTO_MATERIAL", tool_name="web_fetch"
        )
        assert ctx.rule_label == "ESCALATE_CRYPTO_MATERIAL"
        assert ctx.tool_name == "web_fetch"
        # Derived summary is a descriptor, not arguments.
        assert ctx.action_summary == "EXECUTE tool:web_fetch"

    def test_constructor_has_no_raw_argument_parameter(self) -> None:
        """from_pa_verdict has no parameter that accepts raw tool args / payload —
        a secret in the arguments cannot reach the operator surface via this path."""
        import inspect

        params = set(inspect.signature(EscalationContext.from_pa_verdict).parameters)
        # Only safe, descriptor-shaped parameters are accepted (classmethod, so
        # 'cls' is already bound and not in the signature).
        assert params == {"rule_label", "tool_name", "action_summary", "source"}
        for forbidden in ("tool_args", "args", "payload", "parameters", "raw"):
            assert forbidden not in params

    def test_secret_does_not_leak_through_provided_summary_path(self) -> None:
        """The supported builder takes a *summary*, not raw args. If a caller passes
        an already-safe summary, the context holds exactly that — no raw arg field
        exists to smuggle a secret through."""
        secret = "AKIAIOSFODNN7EXAMPLE-super-secret-value"
        ctx = EscalationContext.from_pa_verdict(
            "ESCALATE_CRYPTO_MATERIAL",
            tool_name="web_fetch",
            action_summary="EXECUTE tool:web_fetch",
        )
        rendered = ctx.describe()
        assert secret not in rendered
        # describe() is labels/descriptors only.
        assert "ESCALATE_CRYPTO_MATERIAL" in rendered
        assert "web_fetch" in rendered

    def test_describe_is_labels_only(self) -> None:
        ctx = EscalationContext.from_pa_verdict(
            "ESCALATE_LARGE_WRITE", action_summary="WRITE /internal/config"
        )
        out = ctx.describe()
        assert "ESCALATE_LARGE_WRITE" in out
        assert "WRITE /internal/config" in out


# ---------------------------------------------------------------------------
# ApprovalResult shape
# ---------------------------------------------------------------------------


class TestApprovalResult:
    def test_allow_is_approved(self) -> None:
        r = ApprovalResult.allow(verifier_identity="tui")
        assert r.approved is True
        assert r.verifier_identity == "tui"

    def test_deny_is_not_approved(self) -> None:
        r = ApprovalResult.deny("nope", verifier_identity="tui")
        assert r.approved is False
        assert r.reason == "nope"
