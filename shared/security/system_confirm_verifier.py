r"""One-click system confirm approval verifier (ADR-023 Amendment 4, #723 rung 2).

A non-biometric, surface-independent operator-approval verifier — the LA's chosen
surface for the per-generation-batch approval (a **one-click approve/deny**, NOT a
Windows-Hello fingerprint: a local, deletable, no-egress generation is
intent-confirmation, not identity-assertion). It implements the same
``verify(context) -> ApprovalResult`` Protocol
(:class:`shared.security.escalation_consent.ApprovalVerifier`) the ESCALATE/egress
surfaces do, so wiring it is a single ``register_generation_verifier`` call.

Why a SYSTEM dialog rather than an in-app WinUI/TUI modal: the approval must reach
the operator from the AO tool-loop's process regardless of whether the live surface
is the TUI or the WinUI desktop app, without an AO<->WinUI mid-loop IPC round-trip
(which the streaming path does not currently support). A system dialog raised from
the AO/launcher process is surface-independent — the same reason the #649 Hello
verifier uses a system prompt. An in-app WinUI approval card is a tracked polish
follow-up.

The actual dialog call is an INJECTABLE ``confirm_fn`` so this is unit-testable
without a desktop; the default shows a native Windows Yes/No message box via
``ctypes`` (no new dependency). **Fail-closed everywhere:** anything other than an
explicit "Yes" — a "No", a dialog error, a missing GUI, any exception — is a DENY
(the outer :func:`shared.security.escalation_consent.run_verifier_bounded` also
bounds the wait and fail-closes a wedged dialog). Importing this module has no side
effects.
"""

from __future__ import annotations

import logging
from typing import Callable

from shared.security.escalation_consent import ApprovalResult, EscalationContext

logger = logging.getLogger(__name__)

_IDENTITY: str = "system-confirm"

# The injectable dialog contract: given a title + message, return True iff the
# operator explicitly approved ("Yes"). MUST fail closed (return False) on any
# inability to obtain an explicit yes.
ConfirmFn = Callable[[str, str], bool]


def _windows_message_box_confirm(title: str, message: str) -> bool:
    """Default confirm dialog: a native Windows Yes/No message box (ctypes).

    Returns True iff the operator clicked **Yes**. Fail-closed: any error (not on
    Windows, no desktop/session, ctypes failure) → False. The message carries only
    the SAFE descriptor (labels + the prompt the operator must see); it is passed as
    a single argument, never a shell line.
    """
    try:
        import ctypes  # local import — no module-load dependency / side effect

        # MB_YESNO=0x4, MB_ICONWARNING=0x30, MB_TOPMOST=0x40000,
        # MB_SETFOREGROUND=0x10000. IDYES == 6.
        flags = 0x4 | 0x30 | 0x40000 | 0x10000
        rc = ctypes.windll.user32.MessageBoxW(None, message, title, flags)  # type: ignore[attr-defined]
        return rc == 6  # IDYES
    except Exception as exc:  # noqa: BLE001 — fail-closed: any failure → DENY
        logger.error(
            "System confirm: dialog could not be shown (%r) — DENY (fail-closed).",
            exc,
        )
        return False


class SystemConfirmApprovalVerifier:
    """One-click system Yes/No approval verifier (implements ``ApprovalVerifier``).

    Construct it (optionally with a custom ``confirm_fn`` — tests inject a stub) and
    register it via
    :func:`shared.security.generation_consent.register_generation_verifier`. On each
    request, :meth:`verify` shows the SAFE descriptor as a one-click Yes/No and maps
    **Yes -> allow**, everything else -> deny. Fail-closed on every non-approval path.
    """

    def __init__(self, confirm_fn: "ConfirmFn | None" = None) -> None:
        self._confirm_fn: ConfirmFn = confirm_fn or _windows_message_box_confirm

    def verify(self, context: EscalationContext) -> ApprovalResult:
        """Show the one-click approval for ``context`` and return the decision.

        The dialog title/message are built from ``context.describe()`` —
        labels/descriptors + the prompt the operator must see, never hidden payload
        (``EscalationContext`` carries no raw secret by construction). Synchronous
        and fail-closed: only an explicit Yes allows.
        """
        title = "BlarAI — approve this image generation?"
        message = (
            f"BlarAI wants to generate an image you did not request by typing a "
            f"command:\n\n{context.describe()}\n\nAllow this generation?"
        )
        try:
            approved = bool(self._confirm_fn(title, message))
        except Exception as exc:  # noqa: BLE001 — fail-closed: any failure → DENY
            logger.error(
                "System confirm: confirm_fn raised %r — DENY (fail-closed) for %s",
                exc, context.describe(),
            )
            return ApprovalResult.deny(
                f"confirm error: {type(exc).__name__}", verifier_identity=_IDENTITY
            )

        if approved:
            logger.warning(
                "System confirm: operator APPROVED %s via one-click confirm.",
                context.describe(),
            )
            return ApprovalResult.allow(
                verifier_identity=_IDENTITY, reason="operator approved (one-click)"
            )
        logger.info(
            "System confirm: operator DENIED %s (one-click).", context.describe()
        )
        return ApprovalResult.deny("operator denied", verifier_identity=_IDENTITY)
