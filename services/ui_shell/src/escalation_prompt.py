r"""TUI operator-approval verifier for PA ESCALATE (Vikunja #639, ADR-024 §2.5).

The Textual implementation of :class:`shared.security.escalation_consent.ApprovalVerifier`.
When the Policy Agent returns an ``ESCALATE`` verdict, the AO consumer
(:func:`services.assistant_orchestrator.src.entrypoint._escalation_approved_by_operator`)
calls :meth:`TUIApprovalVerifier.verify` synchronously; this surfaces a modal to the
operator showing the **rule label + safe action descriptor (no secrets/PII)** and
captures their approve/deny answer, then returns it.

Surface posture (ADR-014 / ADR-009): the native WinUI 3 app is the primary surface;
the Textual TUI is retained as a dormant fallback. This verifier therefore renders on
the TUI **only when the TUI is the active surface**. If no Textual app is running (the
WinUI is in front, or the process has no TUI at all), the verifier **fails closed** —
it returns a denied :class:`ApprovalResult` rather than blocking or guessing. The
Windows-Hello biometric verifier (#556) is the WinUI-side counterpart and plugs into
the SAME registry seam; see the module docstring of ``shared.security.escalation_consent``.

Fail-closed guarantees here:
  - No active Textual app → DENY (cannot prompt).
  - The modal cannot be pushed / the app is shutting down → DENY.
  - The operator does not answer before the consent timeout → the *core* helper
    (:func:`request_escalation_consent`) abandons the wait and DENIES; this verifier
    simply blocks on the operator's choice and never fabricates an approval.
  - Any exception → DENY.

Synchronisation: :meth:`verify` runs on the consent worker thread (the core hosts the
verifier off the event loop to bound the wait). It uses
``App.call_from_thread`` to push the modal onto the Textual event loop and a
``threading.Event`` to block the worker until the operator dismisses the modal.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Optional

from shared.security.escalation_consent import (
    ApprovalResult,
    EscalationContext,
)

logger = logging.getLogger(__name__)

# Identity stamped on results this verifier produces.
_TUI_VERIFIER_IDENTITY: str = "tui"

if TYPE_CHECKING:  # import only for typing — keep runtime import lazy/optional
    from textual.app import App


# ---------------------------------------------------------------------------
# The modal screen (built lazily so this module imports without a running app)
# ---------------------------------------------------------------------------


_MODAL_CLASS_CACHE: "Optional[type]" = None


def _build_modal_class() -> type:
    """Construct (once) the ``EscalationConsentModal`` class.

    Built inside a function so importing this module does not force Textual widget
    construction at import time (and so the class is only realised in a process that
    actually has Textual available + a running app). Returns a ``ModalScreen``
    subclass parameterised to return ``True`` (approve) / ``False`` (deny).

    Memoised: the SAME class object is returned on every call (so ``isinstance``
    checks against a pushed modal are stable, and the class is built only once).
    """
    global _MODAL_CLASS_CACHE
    if _MODAL_CLASS_CACHE is not None:
        return _MODAL_CLASS_CACHE

    from textual.app import ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, Static

    class EscalationConsentModal(ModalScreen):  # type: ignore[misc, type-arg]
        """A blocking approve/deny modal for an escalated action.

        Renders the SAFE descriptor only (rule label + action summary + tool name);
        it is handed an :class:`EscalationContext`, which by construction carries no
        raw secrets/PII. Dismisses with ``True`` on approve, ``False`` on deny.
        """

        BINDINGS = [
            ("y", "approve", "Approve"),
            ("a", "approve", "Approve"),
            ("n", "deny", "Deny"),
            ("escape", "deny", "Deny"),
        ]

        DEFAULT_CSS = """
        EscalationConsentModal {
            align: center middle;
        }
        EscalationConsentModal > Vertical {
            width: 70;
            height: auto;
            border: heavy $warning;
            background: $surface;
            padding: 1 2;
        }
        EscalationConsentModal .title {
            text-style: bold;
            color: $warning;
        }
        EscalationConsentModal .buttons {
            height: auto;
            align-horizontal: center;
            padding-top: 1;
        }
        EscalationConsentModal Button {
            margin: 0 1;
        }
        """

        def __init__(self, context: EscalationContext) -> None:
            super().__init__()
            # NB: NOT ``self._context`` — Textual's MessagePump reserves that name
            # for its internal active-context manager. Use a distinct attribute.
            self._escalation_context = context

        def compose(self) -> "ComposeResult":  # noqa: D401
            from rich.markup import escape

            ctx = self._escalation_context
            tool_line = f"\nTool: {escape(ctx.tool_name)}" if ctx.tool_name else ""
            yield Vertical(
                Static("Action requires your approval", classes="title"),
                Static(
                    f"\nThe Policy Agent escalated this action for human review:\n\n"
                    f"Rule: {escape(ctx.rule_label)}\n"
                    f"Action: {escape(ctx.action_summary)}"
                    f"{tool_line}\n\n"
                    f"Approve to allow it once, or deny to refuse. "
                    f"(Denial is the safe default.)"
                ),
                Horizontal(
                    Button("Approve (y)", variant="warning", id="approve"),
                    Button("Deny (n)", variant="primary", id="deny"),
                    classes="buttons",
                ),
            )

        def on_button_pressed(self, event: "Button.Pressed") -> None:  # type: ignore[name-defined]
            self.dismiss(event.button.id == "approve")

        def action_approve(self) -> None:
            self.dismiss(True)

        def action_deny(self) -> None:
            self.dismiss(False)

    _MODAL_CLASS_CACHE = EscalationConsentModal
    return EscalationConsentModal


# ---------------------------------------------------------------------------
# The verifier
# ---------------------------------------------------------------------------


class TUIApprovalVerifier:
    """Textual operator-approval verifier (implements ``ApprovalVerifier``).

    Construct it with the running :class:`textual.app.App` (or a callable returning
    it), then register it via
    :func:`shared.security.escalation_consent.register_verifier`. When the active
    surface is the TUI, :meth:`verify` renders a modal and returns the operator's
    answer; otherwise it fails closed (deny).

    The app reference may be supplied lazily (a zero-arg callable) so the verifier can
    be constructed before the app is fully running and resolve it at prompt time.
    """

    def __init__(self, app: "Optional[App] | None" = None, *, app_getter=None) -> None:
        self._app = app
        self._app_getter = app_getter

    # -- ApprovalVerifier protocol -------------------------------------------------

    def verify(self, context: EscalationContext) -> ApprovalResult:
        """Prompt the operator on the TUI and return their approve/deny answer.

        Fail-closed: no active app, a push failure, or any exception → denied.
        Blocks (synchronously) until the operator dismisses the modal. The outer
        :func:`request_escalation_consent` bounds the total wait and abandons it on
        timeout, so this method need not implement its own timeout.
        """
        app = self._resolve_app()
        if app is None or not self._app_is_active(app):
            logger.info(
                "TUI approval verifier: no active TUI surface — DENY (fail-closed) "
                "for %s",
                context.describe(),
            )
            return ApprovalResult.deny(
                "TUI not the active surface", verifier_identity=_TUI_VERIFIER_IDENTITY
            )

        answered = threading.Event()
        decision_box: dict[str, bool] = {}
        error_box: dict[str, BaseException] = {}

        def _push() -> None:
            # Runs on the Textual event loop (via call_from_thread).
            try:
                modal_cls = _build_modal_class()

                def _on_dismiss(result: object) -> None:
                    decision_box["approved"] = bool(result)
                    answered.set()

                app.push_screen(modal_cls(context), _on_dismiss)
            except BaseException as exc:  # noqa: BLE001 — fail-closed
                error_box["error"] = exc
                answered.set()

        try:
            app.call_from_thread(_push)
        except BaseException as exc:  # noqa: BLE001 — app gone / loop closed → deny
            logger.warning(
                "TUI approval verifier: could not surface prompt (%r) — DENY "
                "(fail-closed) for %s",
                exc, context.describe(),
            )
            return ApprovalResult.deny(
                "could not surface TUI prompt",
                verifier_identity=_TUI_VERIFIER_IDENTITY,
            )

        # Block the consent worker thread until the modal is dismissed. The outer
        # request_escalation_consent join() bounds the overall wait; if it times out
        # it abandons this thread and denies, so a never-dismissed modal cannot wedge
        # the AO turn.
        answered.wait()

        if "error" in error_box:
            logger.warning(
                "TUI approval verifier: prompt error (%r) — DENY (fail-closed) for %s",
                error_box["error"], context.describe(),
            )
            return ApprovalResult.deny(
                "TUI prompt error", verifier_identity=_TUI_VERIFIER_IDENTITY
            )

        approved = decision_box.get("approved", False)
        if approved:
            return ApprovalResult.allow(
                verifier_identity=_TUI_VERIFIER_IDENTITY, reason="operator approved (TUI)"
            )
        return ApprovalResult.deny(
            "operator denied (TUI)", verifier_identity=_TUI_VERIFIER_IDENTITY
        )

    # -- helpers -------------------------------------------------------------------

    def _resolve_app(self) -> "Optional[App]":
        if self._app is not None:
            return self._app
        if self._app_getter is not None:
            try:
                return self._app_getter()
            except Exception:  # noqa: BLE001 — fail-closed: no app
                return None
        return None

    @staticmethod
    def _app_is_active(app: "App") -> bool:
        """True iff ``app`` is a running Textual app that can host a modal.

        Fail-closed: any uncertainty (no ``is_running`` attribute, an exception)
        is treated as NOT active, so the verifier denies rather than guesses.
        """
        try:
            running = getattr(app, "is_running", False)
            return bool(running)
        except Exception:  # noqa: BLE001
            return False
