r"""Egress kill-switch fingerprint re-arm — the operator clears the latch (Vikunja #653).

The egress kill-switch (:mod:`shared.security.egress_guard`) is a **latched**
control: on an egress anomaly (an off-allowlist connect, a positive exfil-screen
detection, a failed arm-hook) it trips and cuts ALL network egress — loopback and
AF_HYPERV included — and stays cut until something calls
:func:`shared.security.egress_guard.rearm`. ADR-027 §3 makes that re-arm a
**deliberate Lead-Architect-only act**, never an automatic runtime path: on a
detected anomaly the safe state is "nothing leaves," and clearing it must be a
human decision.

This module is the **operator surface** for that decision. It does NOT change the
trip machinery (egress_guard owns the latch); it adds the one thing the latch was
missing — a fail-closed way for the operator to *authorise* the clear. Re-using
the #649 Windows-Hello path, the operator re-arms by approving with their
fingerprint (or PIN/face): "Egress LOCKED — reason: X" → tap Re-arm → the system
Hello prompt appears → a successful biometric match clears the latch; a
cancel/failure leaves it locked.

Why reuse the #649 verifier instead of a new auth path
------------------------------------------------------
The ESCALATE consumer (#639) already defines the operator-approval contract
(:class:`shared.security.escalation_consent.ApprovalVerifier` →
:class:`~shared.security.escalation_consent.ApprovalResult`), the fail-closed
bounded-wait machinery (:func:`~shared.security.escalation_consent.request_escalation_consent`),
and the registry (:func:`~shared.security.escalation_consent.active_verifier`) that
a surface wires its verifier into at startup. The Windows-Hello verifier (#649,
:class:`shared.security.hello_verifier.BiometricApprovalVerifier`) is already the
registered verifier on the live (WinUI) surface. Re-arming the egress latch is the
SAME shape of decision as approving an ESCALATE — a single-user-local, human-in-
the-loop approve/deny — so it reuses the SAME verifier, the SAME result type, and
the SAME fail-closed bounded-wait pattern. Inventing a second auth path would
duplicate the trust surface and risk it drifting out of step with the audited one.

Fail-Closed is the whole point (matches the rest of ``shared/security/``)
-------------------------------------------------------------------------
Only an explicit fingerprint approval clears the latch. Every other path leaves
egress LOCKED:

  * **No verifier configured** (the #649 dormant default) → DENY, stays LOCKED. A
    box with no registered verifier cannot self-clear its own kill-switch — there
    is no operator surface to authorise it.
  * The verifier **raises** / **times out** / returns **``None``** / returns a
    **non-:class:`~shared.security.escalation_consent.ApprovalResult`** / returns a
    result whose ``approved`` is not ``True`` → DENY, stays LOCKED.

The ONLY effect of an approval is :func:`egress_guard.rearm` — releasing the latch
so the normal (allowlist-governed) egress checks apply again. Re-arming does NOT
widen the allowlist or clear registered screeners (``rearm()`` already only
releases the latch); this module never touches those.

Design constraints (match ``escalation_consent.py`` / ``egress_guard.py``):
  - **No external network. No new dependencies** (stdlib only; the Hello prompt is
    reached through the #649 verifier's local helper subprocess, not from here).
  - **Importing this module has no side effects** — nothing is armed, no verifier
    is registered, the latch is untouched at import. A surface wires a verifier
    (the launcher, via #649) and the operator drives the re-arm explicitly.
  - **Synchronous-inline:** :func:`request_egress_rearm` blocks on the verifier
    (or the bounded ``timeout_s``) exactly like ``request_escalation_consent``.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from shared.security import egress_guard
from shared.security.escalation_consent import (
    ApprovalResult,
    EscalationContext,
    active_verifier,
)

logger = logging.getLogger(__name__)

# Bounded wait for the operator's Hello answer (seconds). Fail-closed backstop —
# the re-arm call never blocks forever; if no answer arrives within this window the
# latch stays LOCKED. Mirrors escalation_consent.DEFAULT_CONSENT_TIMEOUT_S: a
# console operator answers Hello in seconds, but a wedged/absent surface must never
# hang the caller. (The #649 verifier additionally caps its own subprocess.)
DEFAULT_REARM_TIMEOUT_S: float = 120.0

# The ESCALATE rule label this re-arm context carries — a descriptor, not a value.
# Re-using EscalationContext (the #649 SAFE descriptor) keeps the verifier code path
# identical to the ESCALATE one; this label tags the action as an egress re-arm in
# the audit record and the Hello dialog text.
_REARM_RULE_LABEL: str = "EGRESS_REARM"

# verifier_identity stamped on the no-verifier deny (mirrors escalation_consent's
# dormant default identity — the box has no surface to authorise a self-clear).
_NO_VERIFIER_IDENTITY: str = "no-verifier"


def _rearm_context() -> EscalationContext:
    """Build the SAFE descriptor surfaced to the operator for an egress re-arm.

    Reuses :class:`~shared.security.escalation_consent.EscalationContext` (the #649
    labels/descriptors-only shape) so the verifier sees exactly the kind of context
    it sees for an ESCALATE. The ``action_summary`` INCLUDES the trip reason so the
    operator knows *why* egress locked before they approve clearing it. The trip
    reason is log-safe by contract (:func:`egress_guard.trip` requires "a short,
    log-safe description … MUST NOT contain any matched secret/PII") — so embedding
    it here cannot leak a secret into the Hello dialog or an audit record.
    """
    reason = egress_guard.trip_reason()
    summary = (
        f"Re-arm egress kill-switch — clear the lock (trip reason: {reason})"
        if reason is not None
        else "Re-arm egress kill-switch — clear the lock"
    )
    return EscalationContext.from_pa_verdict(
        _REARM_RULE_LABEL,
        action_summary=summary,
        source="egress_guard",
    )


def request_egress_rearm(
    *,
    timeout_s: float = DEFAULT_REARM_TIMEOUT_S,
) -> ApprovalResult:
    """Ask the operator to clear a tripped egress kill-switch via Windows Hello. Fail-closed.

    The single call an operator surface (the WinUI "Re-arm" button; the demo) makes
    to clear the latch. It is **synchronous-inline**: it blocks until the registered
    verifier answers (or the bounded ``timeout_s`` fires). The ONLY thing that clears
    the latch is an explicit operator approval (``approved is True``); every other
    path leaves egress LOCKED.

    Behaviour:
      * **Not tripped** → returns an allow/no-op result (``"nothing to re-arm"``)
        WITHOUT prompting. Re-arming an un-tripped guard is a no-op, so there is no
        reason to raise a Hello dialog the operator would have to dismiss.
      * **Tripped, no verifier configured** (the #649 dormant default) → DENY, the
        latch stays LOCKED. A box with no registered operator surface cannot
        authorise self-clearing its own kill-switch.
      * **Tripped, verifier present** → run ``verifier.verify(context)`` under the
        SAME fail-closed bounded-wait pattern as
        :func:`~shared.security.escalation_consent.request_escalation_consent`
        (daemon worker thread + ``timeout_s``). Any exception / timeout / ``None`` /
        non-:class:`ApprovalResult` / ``approved is not True`` → DENY, stays LOCKED.
        ONLY on ``approved is True`` → call :func:`egress_guard.rearm` (the sole
        effect) and return the allow result.

    Args:
        timeout_s: bounded wait for the operator's Hello answer; on expiry → DENY
            (latch stays LOCKED). Defaults to :data:`DEFAULT_REARM_TIMEOUT_S`.

    Returns:
        An :class:`~shared.security.escalation_consent.ApprovalResult`. ``approved``
        is True iff the latch was cleared (either it was not tripped — a no-op
        allow — or the operator approved in time). Every fail-closed path returns
        ``approved=False`` and the latch is left LOCKED.
    """
    # Nothing to clear: do NOT prompt. rearm() is a no-op when not tripped, so an
    # allow/no-op result is the honest answer and saves the operator a needless
    # Hello dialog.
    if not egress_guard.is_tripped():
        logger.debug(
            "Egress re-arm requested but kill-switch is not tripped — no-op allow "
            "(nothing to re-arm)."
        )
        return ApprovalResult.allow(
            verifier_identity="egress-rearm",
            reason="nothing to re-arm (kill-switch not tripped)",
        )

    context = _rearm_context()

    verifier = active_verifier()
    if verifier is None:
        # Fail-closed dormant default (mirrors #649): no operator surface is wired,
        # so the box cannot authorise clearing its own latch. Stays LOCKED.
        logger.warning(
            "Egress re-arm DENIED — no verifier configured (fail-closed); "
            "kill-switch stays LOCKED for %s",
            context.describe(),
        )
        return ApprovalResult.deny(
            "no verifier configured", verifier_identity=_NO_VERIFIER_IDENTITY
        )

    verifier_name = type(verifier).__name__

    # Host the (synchronous) verifier on a daemon worker thread purely to enforce
    # the timeout — the SAME pattern as request_escalation_consent. On timeout the
    # thread is abandoned (daemon) and we DENY: we never wait unbounded, and a late
    # answer cannot retroactively clear a latch we already left locked.
    result_box: dict[str, ApprovalResult] = {}
    error_box: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            result_box["result"] = verifier.verify(context)
        except BaseException as exc:  # noqa: BLE001 — fail-closed: any failure → DENY
            error_box["error"] = exc

    worker = threading.Thread(target=_run, name="egress-rearm-consent", daemon=True)
    worker.start()
    worker.join(timeout=timeout_s if timeout_s and timeout_s > 0 else None)

    if worker.is_alive():
        logger.warning(
            "Egress re-arm: verifier %s did not answer within %.1fs — DENY "
            "(fail-closed timeout); kill-switch stays LOCKED for %s",
            verifier_name, timeout_s, context.describe(),
        )
        return ApprovalResult.deny("timeout", verifier_identity=verifier_name)

    if "error" in error_box:
        logger.error(
            "Egress re-arm: verifier %s raised %r — DENY (fail-closed); kill-switch "
            "stays LOCKED for %s",
            verifier_name, error_box["error"], context.describe(),
        )
        return ApprovalResult.deny(
            f"verifier error: {type(error_box['error']).__name__}",
            verifier_identity=verifier_name,
        )

    result: Optional[ApprovalResult] = result_box.get("result")
    if not isinstance(result, ApprovalResult):
        logger.error(
            "Egress re-arm: verifier %s returned a non-ApprovalResult (%r) — DENY "
            "(fail-closed); kill-switch stays LOCKED for %s",
            verifier_name, type(result).__name__, context.describe(),
        )
        return ApprovalResult.deny(
            "verifier returned malformed result", verifier_identity=verifier_name
        )

    if result.approved is not True:
        # An explicit operator deny/cancel. The latch stays LOCKED — the safe state.
        logger.info(
            "Egress re-arm: operator DENIED clearing the latch via %s (%s); "
            "kill-switch stays LOCKED for %s",
            result.verifier_identity or verifier_name, result.reason, context.describe(),
        )
        return result

    # APPROVED — and only now — release the latch. rearm() is the SOLE effect:
    # it does not widen the allowlist or clear screeners (it only releases the
    # latch), so a re-arm restores exactly the normal allowlist-governed posture.
    egress_guard.rearm()
    logger.warning(
        "Egress re-arm: operator APPROVED via %s (%s) — kill-switch CLEARED; normal "
        "allowlist enforcement resumed.",
        result.verifier_identity or verifier_name, result.reason,
    )
    return result
