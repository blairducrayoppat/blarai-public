r"""Escalation human-review consent — the ESCALATE consumer (Vikunja #639, ADR-024 §2.5).

The Policy Agent's deterministic checker
(:meth:`services.policy_agent.src.gpu_inference.DeterministicPolicyChecker.check`)
emits ``("ESCALATE", rule_name)`` for seven deterministic rule classes
(ESCALATE_CERT_RENEWAL, ESCALATE_CROSS_AGENT_OWNERSHIP, ESCALATE_INFRA_CONFIG_WRITE,
ESCALATE_LARGE_WRITE, ESCALATE_UNVERIFIED_CODE, ESCALATE_CRYPTO_MATERIAL,
ESCALATE_CROSS_AGENT_PATH), and the adjudicator surfaces
:attr:`AdjudicationDecision.ESCALATE`. ADR-024 §2.5 specifies the intended
behaviour: *"a PA ESCALATE result pauses the loop and surfaces a user prompt."*
Until this module, no production code consumed ESCALATE — at the AO tool-dispatch
enforcement point it silently collapsed to DENY.

This module is the **consumer**: the seam through which an ESCALATE verdict is
turned into a *human approve/deny decision* before the escalated action is allowed.
It does NOT change the ESCALATE *emission* (the 7 rules stay); it adds the missing
consumer. BlarAI is a single-user local system, so the operator is at the console —
this is a **synchronous-inline** confirmation (the action blocks pending the answer),
NOT an async queue.

What it provides (the autonomous core — #639):
  - :class:`EscalationContext` — the SAFE descriptor of the escalated action: the
    rule label that fired + the action verb + a resource *summary* + the tool name.
    It carries **labels/descriptors only, never raw secrets/PII** (the same
    discipline :mod:`shared.security.exfil_screen` applies to its detection report —
    an approval prompt/audit record must not itself leak the thing it is gating).
  - :class:`ApprovalResult` — ``approved`` + the verifier identity + an optional
    reason. The load-bearing field is ``approved``: **only an explicit True allows**.
  - :class:`ApprovalVerifier` — the Protocol an operator-surface implements:
    ``verify(context) -> ApprovalResult``. A Textual TUI implementation lives in
    ``services.ui_shell.src.escalation_prompt``; a future Windows-Hello biometric
    verifier (Vikunja #556) implements the SAME interface (see :class:`ApprovalVerifier`
    docstring — the documented extension point).
  - :func:`register_verifier` / :func:`clear_verifier` / :func:`active_verifier` —
    a single-verifier registry (an operator surface wires its verifier at startup;
    tests inject a mock). The registry is the integration seam between the in-AO
    consumer and whatever operator surface is live.
  - :func:`request_escalation_consent` — the one call the enforcement point makes.
    **Fail-closed**: no verifier configured → DENIED (today's behaviour, preserved);
    any exception/timeout/None-result → DENIED. Approval is the ONLY thing that allows.

Design constraints (match the rest of ``shared/security/``):
  - **No external network. No new dependencies** (stdlib only).
  - **Importing this module has no side effects** — no verifier is registered and
    nothing is armed at import. A process wires a verifier explicitly at its entry
    point; tests register a mock directly. With no verifier wired, the consumer's
    behaviour is byte-for-byte identical to today (ESCALATE → DENY) — dormant-safe.
  - **Fail-Closed everywhere:** the safe state is DENY. A timeout → DENY. An absent
    verifier → DENY. An erroring verifier → DENY. A verifier that returns ``None``
    or a malformed result → DENY. "I can't get an answer" is never "approved."
  - **Synchronous-inline:** :func:`request_escalation_consent` blocks the caller
    until the verifier answers (or the bounded timeout fires, → DENY).
  - The context carries **labels/descriptors only** (see :class:`EscalationContext`).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# Bounded wait for an operator answer. Fail-closed: the synchronous consent call
# will not block the AO turn forever — if no answer arrives within this window the
# action is DENIED. A console operator answers in seconds; this is the backstop for
# a wedged/absent surface, not the expected path. Kept conservative (a person needs
# time to read the prompt) but finite (a hung surface must never wedge the loop).
DEFAULT_CONSENT_TIMEOUT_S: float = 120.0

# Identity used when no verifier is configured (the dormant default deny path).
_NO_VERIFIER_IDENTITY: str = "no-verifier"


# ---------------------------------------------------------------------------
# Safe descriptor + result shapes (labels/descriptors only — never raw payload)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationContext:
    """The SAFE descriptor of an escalated action, surfaced to the operator.

    Carries **labels and descriptors only — never raw secrets/PII or payload
    values** (the same discipline :class:`shared.security.exfil_screen.Detection`
    applies: an alert/approval record must not itself leak the thing it gates).
    Every field here is action *metadata* — the rule that fired, the verb, a short
    resource *summary*, and the tool name — sufficient for the operator to make an
    approve/deny call without seeing payload content. This mirrors the CAR contract
    (``shared.schemas.car`` — *"CARs never contain raw user data"*).

    The :meth:`from_pa_verdict` constructor is the supported way to build one from a
    Policy-Agent ESCALATE verdict; it takes only already-safe fields (the rule label,
    the tool name, an optional pre-summarised resource/verb string) — it never
    receives raw tool arguments, so a secret in the arguments cannot reach the
    operator surface or an audit record through this path.
    """

    rule_label: str
    """The ESCALATE rule that fired, e.g. ``"ESCALATE_CRYPTO_MATERIAL"``. A label,
    not a value."""

    action_summary: str
    """A short, human-readable summary of the action verb + resource — e.g.
    ``"EXECUTE tool:web_fetch"`` or ``"WRITE /internal/config"``. A descriptor of
    *what kind of action*, NOT the payload. Callers MUST pass an already-safe
    summary; never raw arguments."""

    tool_name: str = ""
    """The tool/skill whose dispatch is being escalated (e.g. ``"web_fetch"``), when
    the escalation originates from an AO tool dispatch. Empty for non-tool
    escalations. A name, not arguments."""

    source: str = "policy_agent"
    """Where the escalation came from — defaults to the Policy Agent. A provenance
    label for the operator/audit record."""

    @classmethod
    def from_pa_verdict(
        cls,
        rule_label: str,
        *,
        tool_name: str = "",
        action_summary: str = "",
        source: str = "policy_agent",
    ) -> "EscalationContext":
        """Build a context from a PA ESCALATE verdict using SAFE fields only.

        Args:
            rule_label: The ESCALATE rule name (a label).
            tool_name: The tool being dispatched (a name), if tool-originated.
            action_summary: A pre-summarised, already-safe ``verb + resource``
                descriptor. If omitted, a minimal summary is derived from the tool
                name (``"EXECUTE tool:<name>"``) or the rule label — never from raw
                arguments.
            source: Provenance label (defaults to ``"policy_agent"``).

        This constructor deliberately accepts only safe descriptors. There is no
        parameter that takes raw tool arguments / payload, so this path cannot carry
        a secret to the operator surface.
        """
        safe_label = str(rule_label or "ESCALATE").strip()
        safe_tool = str(tool_name or "").strip()
        if action_summary:
            safe_summary = str(action_summary).strip()
        elif safe_tool:
            safe_summary = f"EXECUTE tool:{safe_tool}"
        else:
            safe_summary = safe_label
        return cls(
            rule_label=safe_label,
            action_summary=safe_summary,
            tool_name=safe_tool,
            source=str(source or "policy_agent").strip(),
        )

    def describe(self) -> str:
        """A one-line operator-facing description (labels/descriptors only).

        Suitable for a TUI prompt line or an audit record. Contains no raw payload.
        """
        tool_suffix = f" [{self.tool_name}]" if self.tool_name else ""
        return f"{self.rule_label}: {self.action_summary}{tool_suffix}"


@dataclass(frozen=True)
class ApprovalResult:
    """The outcome of an approval request.

    ``approved`` is the load-bearing field: **True means the escalated action is
    permitted; anything else means DENY.** A denied/fail-closed result still carries
    the verifier identity + a reason so the decision is auditable.
    """

    approved: bool
    """True iff the operator explicitly approved. The ONLY value that allows the
    escalated action; every other path (deny, error, timeout, absent verifier)
    yields False."""

    verifier_identity: str = _NO_VERIFIER_IDENTITY
    """Which verifier produced this result (e.g. ``"tui"``, ``"biometric-hello"``,
    or ``"no-verifier"`` for the dormant deny). A label for the audit record."""

    reason: str = ""
    """Optional human-readable reason (e.g. ``"operator approved"``,
    ``"operator denied"``, ``"timeout"``, ``"no verifier configured"``). Labels/
    descriptors only — never raw payload."""

    @classmethod
    def deny(cls, reason: str, *, verifier_identity: str = _NO_VERIFIER_IDENTITY) -> "ApprovalResult":
        """Construct a fail-closed DENY result with a reason."""
        return cls(approved=False, verifier_identity=verifier_identity, reason=reason)

    @classmethod
    def allow(cls, *, verifier_identity: str, reason: str = "operator approved") -> "ApprovalResult":
        """Construct an APPROVED result. Only an operator surface should call this."""
        return cls(approved=True, verifier_identity=verifier_identity, reason=reason)


# ---------------------------------------------------------------------------
# Verifier interface (the operator-surface contract)
# ---------------------------------------------------------------------------


@runtime_checkable
class ApprovalVerifier(Protocol):
    """The contract an operator-approval surface implements (ADR-024 §2.5).

    A verifier is given the SAFE :class:`EscalationContext` and returns an
    :class:`ApprovalResult` — synchronously. It is the human-in-the-loop: it pauses
    the action, surfaces the rule + safe descriptor to the operator, and returns
    their approve/deny answer. It MUST NOT itself perform the escalated action; it
    only decides whether the action is permitted.

    Fail-closed contract: a verifier that cannot obtain an answer (its surface is
    not active, the operator does not respond, an error occurs) SHOULD return a
    denied :class:`ApprovalResult` rather than raise. :func:`request_escalation_consent`
    additionally treats any raised exception, a ``None`` return, a timeout, or a
    non-:class:`ApprovalResult` return as DENY — so a misbehaving verifier still
    fails closed even if it does not honour the contract.

    Implementations:
      - **TUI** (live, this build): ``services.ui_shell.src.escalation_prompt`` —
        a Textual modal that renders the rule label + safe descriptor and captures
        the operator's approve/deny synchronously; if the TUI is not the active
        surface it fails closed (deny).
      - **Windows Hello biometric** (SEAM — Vikunja #556, NOT implemented here): a
        future ``BiometricApprovalVerifier`` implementing this same interface would
        prompt for a fingerprint via the WinUI (ADR-014) and map a successful
        biometric match to :meth:`ApprovalResult.allow`, a failure/cancel to
        :meth:`ApprovalResult.deny`. This is a C#/WinUI + biometric-hardware step
        done on-box later; the seam is the registry below — wiring the biometric
        verifier via :func:`register_verifier` is the ONLY change needed to make
        Windows Hello the approval mechanism. The autonomous core (this module +
        the AO consumer + the TUI verifier) does not change when that lands.
    """

    def verify(self, context: EscalationContext) -> ApprovalResult:
        """Surface ``context`` to the operator and return their approve/deny answer.

        MUST be synchronous (the caller blocks on it). SHOULD fail closed (return a
        denied result) if it cannot obtain an answer.
        """
        ...


# ---------------------------------------------------------------------------
# Single-verifier registry (the integration seam) — dormant by default
# ---------------------------------------------------------------------------
#
# Mirrors shared.security.egress_guard's register/clear screener registry: an
# operator surface registers its verifier at startup so the in-AO consumer can
# reach it WITHOUT this module importing the surface (no circular import). The
# default is NO verifier, which means the consumer denies every ESCALATE — exactly
# today's behaviour. The registry is what makes the consumer dormant-safe: it only
# changes behaviour once a verifier is explicitly wired.

_verifier: Optional[ApprovalVerifier] = None
_verifier_lock = threading.Lock()


def register_verifier(verifier: ApprovalVerifier) -> None:
    """Register the operator-approval verifier (the integration seam).

    INTERFACE ANCHOR. An operator surface (the TUI today; a Windows-Hello biometric
    verifier under #556 later) calls this once at startup. With a verifier
    registered, :func:`request_escalation_consent` consults it on every ESCALATE;
    with none registered (the default), every ESCALATE is DENIED — today's posture.

    Single-verifier: registering replaces any previously-registered verifier (the
    operator surface is singular on a single-user console). Registering does not by
    itself allow anything — it only makes an approve/deny *answerable*; the answer is
    still the operator's, and absent/failed answers fail closed.

    :param verifier: an object implementing the :class:`ApprovalVerifier` protocol
        (a ``verify(context) -> ApprovalResult`` callable surface).
    """
    if not hasattr(verifier, "verify") or not callable(getattr(verifier, "verify")):
        raise TypeError("register_verifier requires an ApprovalVerifier (a verify(context) method)")
    global _verifier
    with _verifier_lock:
        _verifier = verifier
    logger.info(
        "Escalation consent: approval verifier registered (%s) — ESCALATE verdicts "
        "now route to operator review.",
        type(verifier).__name__,
    )


def clear_verifier() -> None:
    """Unregister the verifier — return to the dormant deny-every-ESCALATE default.

    Used at shutdown and by tests (so an injected mock does not leak across tests).
    After this, :func:`request_escalation_consent` denies every ESCALATE again.
    """
    global _verifier
    with _verifier_lock:
        _verifier = None


def active_verifier() -> Optional[ApprovalVerifier]:
    """Return the currently-registered verifier, or ``None`` if none is wired."""
    with _verifier_lock:
        return _verifier


# ---------------------------------------------------------------------------
# The consumer entry point — the one call the ESCALATE enforcement point makes
# ---------------------------------------------------------------------------


def request_escalation_consent(
    context: EscalationContext,
    *,
    timeout_s: float = DEFAULT_CONSENT_TIMEOUT_S,
) -> ApprovalResult:
    """Pause for operator approval of an escalated action (ADR-024 §2.5). Fail-closed.

    This is the single call the ESCALATE enforcement point makes (the AO
    tool-dispatch consumer; any future ESCALATE enforcement site). It is
    **synchronous-inline**: it blocks until the registered verifier answers (or the
    bounded ``timeout_s`` fires). The result's ``approved`` field is the ONLY thing
    that permits the action.

    Fail-closed guarantees — every one of these yields a denied :class:`ApprovalResult`:
      * **No verifier configured** (the dormant default) → DENIED. This preserves
        today's behaviour exactly: with no operator surface wired, an ESCALATE is a
        DENY. The consumer only changes behaviour once a verifier is registered.
      * The verifier **raises** an exception → DENIED.
      * The verifier **does not answer within ``timeout_s``** → DENIED (a wedged or
        absent surface must never wedge the AO turn).
      * The verifier returns **``None``** or a **non-:class:`ApprovalResult`** value
        → DENIED (a malformed verifier fails closed).

    Approval is the only allow path: the action is permitted **iff** the verifier
    returns an :class:`ApprovalResult` with ``approved is True`` within the timeout.

    Args:
        context: the SAFE :class:`EscalationContext` (labels/descriptors only).
        timeout_s: bounded wait for the operator answer; on expiry → DENIED.

    Returns:
        An :class:`ApprovalResult`. ``approved=True`` only on an explicit operator
        approval delivered in time; every other path is a fail-closed deny.
    """
    verifier = active_verifier()
    if verifier is None:
        # Dormant default: behaviour identical to pre-#639 (ESCALATE → DENY).
        logger.info(
            "Escalation consent: no verifier configured — DENY (fail-closed default) "
            "for %s",
            context.describe(),
        )
        return ApprovalResult.deny(
            "no verifier configured", verifier_identity=_NO_VERIFIER_IDENTITY
        )

    return run_verifier_bounded(
        verifier, context, timeout_s=timeout_s, label="Escalation consent"
    )


def run_verifier_bounded(
    verifier: ApprovalVerifier,
    context: EscalationContext,
    *,
    timeout_s: float = DEFAULT_CONSENT_TIMEOUT_S,
    label: str = "Consent",
) -> ApprovalResult:
    """Run one synchronous ``verifier.verify(context)`` under a bounded, fail-closed
    wait — the SINGLE shared harness behind every operator-consent surface.

    Extracted from :func:`request_escalation_consent` so every consent registry (the
    ESCALATE path here; the ADR-023 Amendment 4 rung-3 egress and rung-2
    generation-approval paths) shares ONE fail-closed implementation rather than
    drifting copies. The caller resolves *which* verifier (from its own registry) and
    handles the no-verifier case; this function only bounds + hardens the call.

    Fail-closed — EVERY one of these yields a denied :class:`ApprovalResult`:
      * the verifier **raises** → DENIED;
      * the verifier **does not answer within ``timeout_s``** → DENIED (a wedged or
        absent surface must never wedge the caller — the worker thread is a daemon
        and a late answer can never retroactively allow a denied action);
      * the verifier returns **``None``**/a **non-``ApprovalResult``** → DENIED.

    Approval is the ONLY allow path: permitted iff the verifier returns an
    ``ApprovalResult`` with ``approved is True`` within the timeout.

    :param verifier: an already-resolved :class:`ApprovalVerifier` (never ``None``).
    :param context: the SAFE :class:`EscalationContext` (labels/descriptors only).
    :param timeout_s: bounded wait; on expiry → DENIED.
    :param label: a short log prefix identifying the consent surface (e.g.
        ``"Escalation consent"``, ``"Generation consent"``).
    """
    verifier_name = type(verifier).__name__
    result_box: dict[str, ApprovalResult] = {}
    error_box: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            result_box["result"] = verifier.verify(context)
        except BaseException as exc:  # noqa: BLE001 — fail-closed: any failure → DENY
            error_box["error"] = exc

    worker = threading.Thread(target=_run, name="operator-consent", daemon=True)
    worker.start()
    worker.join(timeout=timeout_s if timeout_s and timeout_s > 0 else None)

    if worker.is_alive():
        logger.warning(
            "%s: verifier %s did not answer within %.1fs — DENY (fail-closed "
            "timeout) for %s",
            label, verifier_name, timeout_s, context.describe(),
        )
        return ApprovalResult.deny("timeout", verifier_identity=verifier_name)

    if "error" in error_box:
        logger.error(
            "%s: verifier %s raised %r — DENY (fail-closed) for %s",
            label, verifier_name, error_box["error"], context.describe(),
        )
        return ApprovalResult.deny(
            f"verifier error: {type(error_box['error']).__name__}",
            verifier_identity=verifier_name,
        )

    result = result_box.get("result")
    if not isinstance(result, ApprovalResult):
        logger.error(
            "%s: verifier %s returned a non-ApprovalResult (%r) — DENY "
            "(fail-closed) for %s",
            label, verifier_name, type(result).__name__, context.describe(),
        )
        return ApprovalResult.deny(
            "verifier returned malformed result", verifier_identity=verifier_name
        )

    if result.approved:
        logger.warning(
            "%s: operator APPROVED %s via %s (%s).",
            label, context.describe(), result.verifier_identity or verifier_name,
            result.reason,
        )
        return result

    logger.info(
        "%s: operator DENIED %s via %s (%s).",
        label, context.describe(), result.verifier_identity or verifier_name,
        result.reason,
    )
    return result
