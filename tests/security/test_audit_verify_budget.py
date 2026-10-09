"""#1543: the verify-on-load budget is a contract between three constants, not three knobs.

``AuditLog.verify()`` runs at both production construction sites so a tampered chain is
refused rather than extended.  Its cost is dominated by per-record signature verification,
which is a TPM operation in production.  The active-segment ceiling therefore cannot be
raised independently of the measured per-record cost without lengthening every boot.

These locks make that coupling fail the standing gate instead of failing silently.

Measurement behind ``AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD``:
``docs/performance/audit_chain_verify_cost_2026-09-17_22-50-00.json`` (100 isolated
``tpm_signer.verify()`` calls, Arc 140V host, 2026-09-17).
"""

from __future__ import annotations

import pytest

from shared.security.audit_log import (
    AUDIT_BOOT_VERIFY_BUDGET_SECONDS,
    AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD,
    DEFAULT_MAX_ACTIVE_RECORDS,
    PRODUCTION_MAX_ACTIVE_RECORDS,
)


class TestVerifyOnLoadBudgetContract:
    """The three constants must satisfy the inequality the boot path depends on."""

    def test_worst_case_active_segment_verification_fits_the_boot_budget(self) -> None:
        """ceiling x per-record cost <= budget.  The whole point of the ceiling."""
        worst_case = PRODUCTION_MAX_ACTIVE_RECORDS * AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD
        assert worst_case <= AUDIT_BOOT_VERIFY_BUDGET_SECONDS, (
            f"A full active-segment verification would cost {worst_case:.1f} s at the "
            f"{PRODUCTION_MAX_ACTIVE_RECORDS:,}-record ceiling and "
            f"{AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD * 1000:.1f} ms/record, which "
            f"exceeds the {AUDIT_BOOT_VERIFY_BUDGET_SECONDS} s boot budget registered in "
            "shared/timeout_registry.py.  Either lower PRODUCTION_MAX_ACTIVE_RECORDS or "
            "RE-MEASURE the per-record cost and raise the budget deliberately — do not "
            "widen one constant to silence this."
        )

    def test_production_ceiling_is_far_below_the_adr_029_default(self) -> None:
        """The production ceiling is a deliberate reduction, not a copy of the default.

        ADR-029's 100,000 default bounds RAM and file size.  It does not bound boot-time
        signature verification, which is what #1543 added.  If these two ever become equal
        again, the reduction has been reverted and the boot path has quietly regained an
        11-21 minute worst case.
        """
        assert PRODUCTION_MAX_ACTIVE_RECORDS < DEFAULT_MAX_ACTIVE_RECORDS, (
            "PRODUCTION_MAX_ACTIVE_RECORDS must stay below ADR-029's "
            f"DEFAULT_MAX_ACTIVE_RECORDS ({DEFAULT_MAX_ACTIVE_RECORDS:,}); the reduction "
            "is what keeps a complete verify-on-load affordable at boot."
        )

    def test_the_adr_029_default_would_NOT_fit_the_budget(self) -> None:
        """The toggle-test for this lock: prove the constraint can fail.

        A lock that only ever passes cannot be distinguished from a lock that cannot
        reach its subject (security_by_design principle 12).  This asserts that the
        UNREDUCED ADR-029 ceiling genuinely breaches the budget — so the inequality in
        the first test is load-bearing rather than vacuously true.
        """
        unreduced = DEFAULT_MAX_ACTIVE_RECORDS * AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD
        assert unreduced > AUDIT_BOOT_VERIFY_BUDGET_SECONDS, (
            "The ADR-029 default ceiling now fits the boot budget, which makes the "
            "production reduction pointless.  That can only happen if the per-record "
            "cost or the budget changed by orders of magnitude — re-read "
            "docs/performance/audit_chain_verify_cost_2026-09-17_22-50-00.json before "
            "touching this."
        )

    @pytest.mark.parametrize(
        "name, value",
        [
            ("AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD", AUDIT_VERIFY_WORST_CASE_SECONDS_PER_RECORD),
            ("AUDIT_BOOT_VERIFY_BUDGET_SECONDS", AUDIT_BOOT_VERIFY_BUDGET_SECONDS),
        ],
    )
    def test_budget_constants_are_positive(self, name: str, value: float) -> None:
        """A zero or negative budget would make the contract vacuous."""
        assert value > 0, f"{name} must be positive; got {value!r}"
