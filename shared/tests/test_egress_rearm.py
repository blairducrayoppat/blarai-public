r"""Tests for the egress kill-switch fingerprint re-arm core (shared/security/egress_rearm.py).

Vikunja #653 / ADR-027 §3. The egress kill-switch is a latched control; clearing
it is a deliberate operator act, authorised by the #649 Windows-Hello verifier.
:func:`shared.security.egress_rearm.request_egress_rearm` is that authorise-then-
clear seam. These tests prove the load-bearing contract:

  - not tripped → no prompt, no-op allow (the verifier is never consulted);
  - tripped + no verifier configured → DENY, stays LOCKED (fail-closed dormant default);
  - tripped + verifier approves → :func:`egress_guard.rearm` effected, ``is_tripped()`` False;
  - tripped + verifier denies/cancels → stays LOCKED;
  - verifier raises → stays LOCKED; verifier times out → stays LOCKED;
  - a late answer cannot retroactively clear an already-denied latch.

The verifier is MOCKED (a fake ``ApprovalVerifier`` injected via the
``escalation_consent`` registry); ``egress_guard`` is driven with its REAL global
state via ``trip()`` / ``disarm()``. The autouse fixture resets BOTH globals
(``egress_guard.disarm()`` releases the latch; ``clear_verifier()`` drops the mock)
before and after every test, so neither leaks into the wider suite.
"""

from __future__ import annotations

import threading
import time

import pytest

from shared.security import egress_guard
from shared.security.escalation_consent import (
    ApprovalResult,
    ApprovalVerifier,
    EscalationContext,
    clear_verifier,
    register_verifier,
)
from shared.security.egress_rearm import request_egress_rearm


@pytest.fixture(autouse=True)
def _reset_global_state() -> None:
    """Reset BOTH the egress latch and the verifier registry around every test.

    ``disarm()`` releases any trip latch (its docstring: "Clears the trip latch")
    AND restores the real socket surface if a test ever armed; ``clear_verifier()``
    drops any injected mock. Run before AND after so an aborted test cannot leave
    the module-global kill-switch tripped or a mock verifier wired.
    """
    egress_guard.disarm()
    clear_verifier()
    yield
    egress_guard.disarm()
    clear_verifier()


# ---------------------------------------------------------------------------
# Test doubles (fake ApprovalVerifier implementations)
# ---------------------------------------------------------------------------


class _ApprovingVerifier:
    """Always approves; records the contexts it was given (to assert no-prompt)."""

    def __init__(self) -> None:
        self.seen: list[EscalationContext] = []

    def verify(self, context: EscalationContext) -> ApprovalResult:
        self.seen.append(context)
        return ApprovalResult.allow(verifier_identity="mock-approve")


class _DenyingVerifier:
    """Simulates an operator cancelling the Hello prompt."""

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, context: EscalationContext) -> ApprovalResult:
        self.calls += 1
        return ApprovalResult.deny("operator cancelled", verifier_identity="mock-deny")


class _ErroringVerifier:
    def verify(self, context: EscalationContext) -> ApprovalResult:
        raise RuntimeError("hello helper blew up")


class _MalformedVerifier:
    """Returns a non-ApprovalResult — a misbehaving verifier (must fail closed)."""

    def verify(self, context: EscalationContext):  # type: ignore[no-untyped-def]
        return "unlocked!"


class _NoneVerifier:
    def verify(self, context: EscalationContext):  # type: ignore[no-untyped-def]
        return None


class _HangingVerifier:
    """Blocks until released — exercises the timeout fail-closed path."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()

    def verify(self, context: EscalationContext) -> ApprovalResult:
        self.entered.set()
        self.release.wait(timeout=5.0)
        return ApprovalResult.allow(verifier_identity="mock-late")


# ---------------------------------------------------------------------------
# Not tripped → no prompt, no-op
# ---------------------------------------------------------------------------


class TestNotTripped:
    def test_not_tripped_is_noop_allow_without_prompting(self) -> None:
        """When the latch is not set, the verifier is NEVER consulted and the call
        is a no-op allow (nothing to re-arm)."""
        approving = _ApprovingVerifier()
        register_verifier(approving)
        assert egress_guard.is_tripped() is False

        result = request_egress_rearm()

        assert result.approved is True
        assert "nothing to re-arm" in result.reason.lower()
        # The verifier must NOT have been called — no Hello dialog for a no-op.
        assert approving.seen == []
        assert egress_guard.is_tripped() is False


# ---------------------------------------------------------------------------
# Tripped + no verifier → fail-closed, stays LOCKED
# ---------------------------------------------------------------------------


class TestTrippedNoVerifier:
    def test_tripped_no_verifier_stays_locked(self) -> None:
        """The #649 dormant default: no operator surface wired → cannot self-clear."""
        egress_guard.trip("test: simulated anomaly")
        assert egress_guard.is_tripped() is True

        result = request_egress_rearm()

        assert result.approved is False
        assert result.verifier_identity == "no-verifier"
        assert "no verifier" in result.reason.lower()
        # Latch UNCHANGED — still locked, original reason preserved.
        assert egress_guard.is_tripped() is True
        assert egress_guard.trip_reason() == "test: simulated anomaly"


# ---------------------------------------------------------------------------
# Tripped + verifier approves → rearm effected
# ---------------------------------------------------------------------------


class TestTrippedApproved:
    def test_approval_clears_the_latch(self) -> None:
        register_verifier(_ApprovingVerifier())
        egress_guard.trip("test: simulated exfiltration anomaly")
        assert egress_guard.is_tripped() is True

        result = request_egress_rearm()

        assert result.approved is True
        # rearm() effected — latch cleared, reason gone.
        assert egress_guard.is_tripped() is False
        assert egress_guard.trip_reason() is None

    def test_approval_context_carries_the_trip_reason(self) -> None:
        """The operator must see WHY egress locked before approving the clear — the
        re-arm context's descriptor includes the (log-safe) trip reason."""
        approving = _ApprovingVerifier()
        register_verifier(approving)
        egress_guard.trip("connect to off-allowlist address '203.0.113.5'")

        request_egress_rearm()

        assert len(approving.seen) == 1
        described = approving.seen[0].describe()
        assert "EGRESS_REARM" in described
        assert "203.0.113.5" in described  # the trip reason is surfaced
        assert "re-arm" in described.lower()


# ---------------------------------------------------------------------------
# Tripped + every fail-closed path → stays LOCKED
# ---------------------------------------------------------------------------


class TestTrippedFailsClosed:
    def test_denial_stays_locked(self) -> None:
        denying = _DenyingVerifier()
        register_verifier(denying)
        egress_guard.trip("test: anomaly")

        result = request_egress_rearm()

        assert result.approved is False
        assert result.verifier_identity == "mock-deny"
        assert denying.calls == 1
        # Latch UNCHANGED.
        assert egress_guard.is_tripped() is True

    def test_erroring_verifier_stays_locked(self) -> None:
        register_verifier(_ErroringVerifier())
        egress_guard.trip("test: anomaly")

        result = request_egress_rearm()

        assert result.approved is False
        assert "error" in result.reason.lower()
        assert egress_guard.is_tripped() is True

    def test_malformed_result_stays_locked(self) -> None:
        register_verifier(_MalformedVerifier())
        egress_guard.trip("test: anomaly")

        result = request_egress_rearm()

        assert result.approved is False
        assert "malformed" in result.reason.lower()
        assert egress_guard.is_tripped() is True

    def test_none_result_stays_locked(self) -> None:
        register_verifier(_NoneVerifier())
        egress_guard.trip("test: anomaly")

        result = request_egress_rearm()

        assert result.approved is False
        assert egress_guard.is_tripped() is True

    def test_timeout_stays_locked(self) -> None:
        """A verifier that does not answer within the timeout → DENY, stays LOCKED."""
        hanging = _HangingVerifier()
        register_verifier(hanging)
        egress_guard.trip("test: anomaly")

        start = time.monotonic()
        result = request_egress_rearm(timeout_s=0.2)
        elapsed = time.monotonic() - start

        assert result.approved is False
        assert result.reason == "timeout"
        assert elapsed < 2.0  # returned at the timeout, did not wait the 5s hang
        assert egress_guard.is_tripped() is True
        hanging.release.set()  # release the worker so it does not linger

    def test_late_answer_cannot_retroactively_clear(self) -> None:
        """After a timeout DENY, the verifier later 'approving' must NOT clear the
        already-locked latch."""
        hanging = _HangingVerifier()
        register_verifier(hanging)
        egress_guard.trip("test: anomaly")

        result = request_egress_rearm(timeout_s=0.2)
        assert result.approved is False  # denied on timeout
        assert egress_guard.is_tripped() is True

        hanging.release.set()  # verifier now 'approves' — too late
        time.sleep(0.1)
        # The latch must remain locked: a late answer cannot re-arm.
        assert egress_guard.is_tripped() is True


# ---------------------------------------------------------------------------
# The mock satisfies the real ApprovalVerifier protocol (reuse, not a new path)
# ---------------------------------------------------------------------------


class TestVerifierReuse:
    def test_mock_is_an_approval_verifier(self) -> None:
        """The re-arm path consumes the SAME ApprovalVerifier protocol as #639/#649
        (runtime_checkable) — proving it reuses the #649 mechanism, not a new one."""
        assert isinstance(_ApprovingVerifier(), ApprovalVerifier)
        assert isinstance(_DenyingVerifier(), ApprovalVerifier)
