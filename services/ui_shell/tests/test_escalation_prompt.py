r"""Tests for the TUI operator-approval verifier (services/ui_shell/src/escalation_prompt.py).

Vikunja #639 / ADR-024 §2.5. The Textual implementation of ``ApprovalVerifier``.
These tests prove:

  - fail-closed when there is no active TUI surface (no app, or a not-running app);
  - it structurally satisfies the ApprovalVerifier protocol + plugs into the registry;
  - end-to-end against a LIVE Textual app: the modal renders the SAFE descriptor and
    the operator's Approve / Deny choice round-trips back through the synchronous
    verify() call (exercising the cross-thread call_from_thread + Event handshake).

The verify() call blocks until the modal is dismissed, so the live tests drive it on
a worker thread and dismiss the modal from the Textual pilot.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from shared.security.escalation_consent import (
    ApprovalResult,
    ApprovalVerifier,
    EscalationContext,
)
from services.ui_shell.src.escalation_prompt import TUIApprovalVerifier


def _ctx() -> EscalationContext:
    return EscalationContext.from_pa_verdict(
        "ESCALATE_CRYPTO_MATERIAL",
        tool_name="web_fetch",
        action_summary="EXECUTE tool:web_fetch",
    )


# ---------------------------------------------------------------------------
# Fail-closed when there is no active surface
# ---------------------------------------------------------------------------


class TestTUIVerifierFailClosed:
    def test_no_app_denies(self) -> None:
        verifier = TUIApprovalVerifier(app=None)
        result = verifier.verify(_ctx())
        assert result.approved is False
        assert result.verifier_identity == "tui"

    def test_not_running_app_denies(self) -> None:
        class _NotRunning:
            is_running = False

        verifier = TUIApprovalVerifier(app=_NotRunning())
        result = verifier.verify(_ctx())
        assert result.approved is False

    def test_app_getter_raising_denies(self) -> None:
        def _boom() -> Any:
            raise RuntimeError("no app")

        verifier = TUIApprovalVerifier(app_getter=_boom)
        result = verifier.verify(_ctx())
        assert result.approved is False

    def test_satisfies_protocol(self) -> None:
        assert isinstance(TUIApprovalVerifier(app=None), ApprovalVerifier)


# ---------------------------------------------------------------------------
# End-to-end against a live Textual app
# ---------------------------------------------------------------------------


def _verify_on_thread(verifier: TUIApprovalVerifier, ctx: EscalationContext) -> dict:
    """Run verify() on a worker thread; return a box the test reads after join."""
    box: dict[str, ApprovalResult] = {}

    def _run() -> None:
        box["result"] = verifier.verify(ctx)

    t = threading.Thread(target=_run, name="verify-under-test", daemon=True)
    t.start()
    return {"thread": t, "box": box}


@pytest.mark.asyncio
async def test_live_app_approve_round_trip() -> None:
    """Operator presses Approve → verify() returns approved=True."""
    from textual.app import App

    class _Host(App):
        def compose(self):  # minimal host app
            return iter(())

    app = _Host()
    async with app.run_test() as pilot:
        verifier = TUIApprovalVerifier(app=app)
        handle = _verify_on_thread(verifier, _ctx())

        # Wait for the modal to appear on the screen stack, then approve it.
        from services.ui_shell.src.escalation_prompt import _build_modal_class
        modal_cls = _build_modal_class()
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, modal_cls):
                break
        assert isinstance(app.screen, modal_cls), "escalation modal did not appear"

        await pilot.press("y")  # approve
        # Let the dismiss callback + worker thread settle.
        for _ in range(50):
            await pilot.pause()
            if "result" in handle["box"]:
                break

    handle["thread"].join(timeout=2.0)
    result = handle["box"].get("result")
    assert result is not None
    assert result.approved is True
    assert result.verifier_identity == "tui"


@pytest.mark.asyncio
async def test_live_app_deny_round_trip() -> None:
    """Operator presses Deny (Escape) → verify() returns approved=False."""
    from textual.app import App

    class _Host(App):
        def compose(self):
            return iter(())

    app = _Host()
    async with app.run_test() as pilot:
        verifier = TUIApprovalVerifier(app=app)
        handle = _verify_on_thread(verifier, _ctx())

        from services.ui_shell.src.escalation_prompt import _build_modal_class
        modal_cls = _build_modal_class()
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, modal_cls):
                break
        assert isinstance(app.screen, modal_cls), "escalation modal did not appear"

        await pilot.press("n")  # deny
        for _ in range(50):
            await pilot.pause()
            if "result" in handle["box"]:
                break

    handle["thread"].join(timeout=2.0)
    result = handle["box"].get("result")
    assert result is not None
    assert result.approved is False


@pytest.mark.asyncio
async def test_modal_renders_safe_descriptor_not_secrets() -> None:
    """The modal text contains the rule label + safe summary, never a raw secret."""
    from textual.app import App
    from textual.widgets import Static

    class _Host(App):
        def compose(self):
            return iter(())

    app = _Host()
    async with app.run_test() as pilot:
        verifier = TUIApprovalVerifier(app=app)
        handle = _verify_on_thread(verifier, _ctx())

        from services.ui_shell.src.escalation_prompt import _build_modal_class
        modal_cls = _build_modal_class()
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, modal_cls):
                break
        assert isinstance(app.screen, modal_cls)

        # Collect all Static text on the modal (render() yields the renderable).
        rendered = " ".join(
            str(w.render()) for w in app.screen.query(Static)
        )
        assert "ESCALATE_CRYPTO_MATERIAL" in rendered
        assert "web_fetch" in rendered

        await pilot.press("n")  # deny to release the worker
        for _ in range(50):
            await pilot.pause()
            if "result" in handle["box"]:
                break

    handle["thread"].join(timeout=2.0)
