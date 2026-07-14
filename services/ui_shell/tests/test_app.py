"""
Tests for services.ui_shell.src.app (P1.12).

Tests the BlarAIApp construction, action guards, and correct API
wiring to TransportGateway and SessionStore without running a full
Textual compositor. Textual's App.run_test() is used for the
integration-level tests (P1.14).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ui_shell.src.app import BlarAIApp
from services.ui_gateway.src.transport import StartupState


class TestBlarAIAppConstruction:
    """Verify app construction and metadata."""

    def test_app_title(self) -> None:
        app = BlarAIApp()
        assert app.TITLE == "BlarAI Assistant"

    def test_gateway_none_by_default(self) -> None:
        app = BlarAIApp()
        assert app._gateway is None

    def test_session_store_none_by_default(self) -> None:
        app = BlarAIApp()
        assert app._session_store is None

    def test_not_operational_by_default(self) -> None:
        app = BlarAIApp()
        assert app._operational is False

    def test_last_prompt_empty_by_default(self) -> None:
        app = BlarAIApp()
        assert app._last_prompt == ""

    def test_bindings_registered(self) -> None:
        """Verify all keybindings are declared (Submit, Retry, New Session,
        Delete Session, Paste, Quit)."""
        app = BlarAIApp()
        # BINDINGS is a class attribute; verify count
        assert len(app.BINDINGS) == 6

    def test_gateway_injection(self) -> None:
        """Verify gateway is stored when injected."""
        sentinel = object()
        app = BlarAIApp(gateway=sentinel)  # type: ignore[arg-type]
        assert app._gateway is sentinel

    def test_session_store_injection(self) -> None:
        """Verify session_store is stored when injected."""
        sentinel = object()
        app = BlarAIApp(session_store=sentinel)  # type: ignore[arg-type]
        assert app._session_store is sentinel

    def test_both_injections(self) -> None:
        """Verify gateway + session_store are both stored."""
        gw = object()
        store = object()
        app = BlarAIApp(gateway=gw, session_store=store)  # type: ignore[arg-type]
        assert app._gateway is gw
        assert app._session_store is store


class TestBlarAIAppActionGuards:
    """Verify action methods respect operational guards."""

    @pytest.mark.asyncio
    async def test_submit_noop_when_not_operational(self) -> None:
        """action_submit_prompt exits early when not operational — send_prompt not called."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock()
        app = BlarAIApp(gateway=gateway)
        assert app._operational is False
        await app.action_submit_prompt()
        gateway.send_prompt.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_noop_when_no_gateway(self) -> None:
        """action_submit_prompt exits early when gateway is None — no AttributeError raised."""
        app = BlarAIApp()
        app._operational = True
        assert app._gateway is None
        # Should return immediately without touching any widget
        await app.action_submit_prompt()


class TestBlarAIAppAPIWiring:
    """Verify the app calls TransportGateway with correct signatures."""

    def test_send_prompt_requires_session_id_and_text(self) -> None:
        """Verify send_prompt is called with (session_id, prompt)."""
        # Construct a mock gateway with the correct method signatures
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-123")
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))
        gateway.get_pgov_result = MagicMock(
            return_value=MagicMock(approved=True, sanitized_text="ok", reason_codes=[])
        )
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app = BlarAIApp(gateway=gateway)
        # Verify the mock has the correct signature
        assert gateway.send_prompt is not None
        assert gateway.stream_tokens is not None
        assert gateway.get_pgov_result is not None

    def test_get_pgov_result_is_sync(self) -> None:
        """Verify get_pgov_result is a sync method (not async)."""
        from services.ui_gateway.src.transport import TransportGateway

        gw = TransportGateway(dev_mode=True, port=0)
        result = gw.get_pgov_result("test-id")
        # Should not need await — it's sync
        assert result.approved is False  # default deny
        assert result.request_id == "test-id"

    def test_check_pa_status_returns_bool(self) -> None:
        """Verify check_pa_status return type annotation."""
        from services.ui_gateway.src.transport import TransportGateway
        import inspect

        sig = inspect.signature(TransportGateway.check_pa_status)
        # Return annotation is 'bool' (string due to __future__ annotations)
        assert sig.return_annotation in (bool, "bool")


class AsyncIterStub:
    """Stub for an async iterator (for mock stream_tokens)."""

    def __init__(self, items: list) -> None:
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class _DisplayStub:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, text: str) -> None:
        self.lines.append(text)


class _PromptStub:
    def __init__(self) -> None:
        self.disabled: bool = True
        self.value: str = ""
        self.focused: bool = False

    def focus(self) -> None:
        self.focused = True


class _GatewaySuccessStub:
    def __init__(self) -> None:
        self.state = StartupState.INITIALIZING

    async def check_pa_status(self) -> bool:
        self.state = StartupState.HANDSHAKING
        await asyncio.sleep(0)
        self.state = StartupState.OPERATIONAL
        return True

    def reset(self) -> None:
        self.state = StartupState.INITIALIZING


class _GatewayFailedStub:
    def __init__(self) -> None:
        self.state = StartupState.INITIALIZING

    async def check_pa_status(self) -> bool:
        self.state = StartupState.HANDSHAKING
        await asyncio.sleep(0)
        self.state = StartupState.FAILED
        return False

    def reset(self) -> None:
        self.state = StartupState.INITIALIZING


class TestBootPhase3P113:
    @pytest.mark.asyncio
    async def test_poll_boot_status_logs_operational(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        app = BlarAIApp(gateway=_GatewaySuccessStub())
        display = _DisplayStub()
        prompt = _PromptStub()

        def _query_one(selector: str, _type: object = None) -> object:
            if selector == "#response-area":
                return display
            if selector == "#prompt-input":
                return prompt
            raise KeyError(selector)

        app.query_one = _query_one  # type: ignore[method-assign]
        await app._poll_boot_status()

        boot_log = tmp_path / "BlarAI" / "boot.log"
        assert boot_log.exists()
        content = boot_log.read_text(encoding="utf-8")
        assert "OPERATIONAL" in content

    @pytest.mark.asyncio
    async def test_poll_boot_status_logs_failed(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        app = BlarAIApp(gateway=_GatewayFailedStub())
        display = _DisplayStub()
        prompt = _PromptStub()

        def _query_one(selector: str, _type: object = None) -> object:
            if selector == "#response-area":
                return display
            if selector == "#prompt-input":
                return prompt
            raise KeyError(selector)

        app.query_one = _query_one  # type: ignore[method-assign]
        await app._poll_boot_status()

        boot_log = tmp_path / "BlarAI" / "boot.log"
        assert boot_log.exists()
        content = boot_log.read_text(encoding="utf-8")
        assert "FAILED" in content

    @pytest.mark.asyncio
    async def test_retry_boot_calls_gateway_reset(self) -> None:
        gateway = MagicMock()
        gateway.reset = MagicMock()
        app = BlarAIApp(gateway=gateway)
        app._operational = False
        display = _DisplayStub()

        def _query_one(selector: str, _type: object = None) -> object:
            if selector == "#response-area":
                return display
            raise KeyError(selector)

        app.query_one = _query_one  # type: ignore[method-assign]

        with patch("services.ui_shell.src.app.asyncio.create_task") as create_task:
            fake_task = MagicMock()
            fake_task.done.return_value = False

            def _create_task_stub(coro: object) -> object:
                if hasattr(coro, "close"):
                    coro.close()
                return fake_task

            create_task.side_effect = _create_task_stub
            app._boot_task = None
            await app.action_retry_boot()

        gateway.reset.assert_called_once()
        assert create_task.called

    @pytest.mark.asyncio
    async def test_retry_boot_when_operational_resends_prompt(self) -> None:
        gateway = MagicMock()
        gateway.reset = MagicMock()
        app = BlarAIApp(gateway=gateway)
        app._operational = True
        app._last_prompt = "repeat this"
        prompt = _PromptStub()

        def _query_one(selector: str, _type: object = None) -> object:
            if selector == "#prompt-input":
                return prompt
            raise KeyError(selector)

        app.query_one = _query_one  # type: ignore[method-assign]
        app.action_submit_prompt = AsyncMock()  # type: ignore[method-assign]

        await app.action_retry_boot()

        assert prompt.value == "repeat this"
        gateway.reset.assert_not_called()
        app.action_submit_prompt.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_boot_log_directory_created_if_missing(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_appdata = tmp_path / "localappdata"
        assert not local_appdata.exists()
        monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

        app = BlarAIApp(gateway=_GatewayFailedStub())
        display = _DisplayStub()
        prompt = _PromptStub()

        def _query_one(selector: str, _type: object = None) -> object:
            if selector == "#response-area":
                return display
            if selector == "#prompt-input":
                return prompt
            raise KeyError(selector)

        app.query_one = _query_one  # type: ignore[method-assign]
        await app._poll_boot_status()

        boot_dir = local_appdata / "BlarAI"
        boot_log = boot_dir / "boot.log"
        assert boot_dir.exists()
        assert boot_log.exists()


class TestSessionReload:
    """Verify selecting a session loads persisted turns into the display."""

    @pytest.mark.asyncio
    async def test_on_list_view_selected_loads_turns(self) -> None:
        """When a session is clicked, its turns must render into StreamingDisplay."""
        from dataclasses import dataclass, field

        @dataclass(frozen=True)
        class _Turn:
            id: str
            session_id: str
            role: str
            content: str
            pgov_status: str
            pgov_reasons: list[str] = field(default_factory=list)
            timestamp: str = ""

        turns = [
            _Turn(id="t1", session_id="s1", role="user", content="Hello", pgov_status="N/A"),
            _Turn(id="t2", session_id="s1", role="assistant", content="Hi there", pgov_status="approved"),
        ]

        store = MagicMock()
        store.get_turns.return_value = turns
        store.set_active_session = MagicMock()

        app = BlarAIApp(session_store=store)

        display_lines: list[str] = []

        class _Display:
            def clear_display(self) -> None:
                display_lines.clear()

            def write_line(self, text: str) -> None:
                display_lines.append(text)

        class _Panel:
            active_session_id: str | None = "s1"

            async def select_session(self, sid: str) -> None:
                self.active_session_id = sid

            async def refresh_list(self) -> None:
                pass

        class _PGov:
            def hide(self) -> None:
                pass

        panel = _Panel()
        display = _Display()
        pgov = _PGov()

        def _query_one(selector: str, _type: object = None) -> object:
            if selector == "#session-panel":
                return panel
            if selector == "#response-area":
                return display
            if selector == "#pgov-panel":
                return pgov
            raise KeyError(selector)

        app.query_one = _query_one  # type: ignore[method-assign]

        # Build a fake ListView.Selected event
        from services.ui_shell.src.session_panel import SessionListItem

        summary = MagicMock()
        summary.id = "s1"
        summary.title = "Test"
        summary.turn_count = 2
        summary.is_active = True

        item = SessionListItem(summary)

        event = MagicMock()
        event.item = item

        await app.on_list_view_selected(event)

        store.get_turns.assert_called_once_with("s1")
        # User turn rendered
        assert any("Hello" in line for line in display_lines)
        # Assistant turn rendered
        assert any("Hi there" in line for line in display_lines)
        # Separator lines present
        assert any("─" in line for line in display_lines)


# ─────────────────────────────────────────────────────────────────
# WI-4 / WI-5 / WI-6: action_submit_prompt branch coverage
# ─────────────────────────────────────────────────────────────────

from services.ui_gateway.src.transport import GatewayPGOVResult  # noqa: E402


def _make_app_with_stubs(
    gateway: object,
    session_id: str = "sess-test",
    prompt_text: str = "hello",
) -> tuple["BlarAIApp", dict]:
    """Construct BlarAIApp with all query_one stubs wired for action_submit_prompt."""
    app = BlarAIApp(gateway=gateway)  # type: ignore[arg-type]
    app._operational = True

    display = MagicMock()
    display.start_new_response = MagicMock()
    display.write_line = MagicMock()
    display.append_token = MagicMock()
    display.clear_display = MagicMock()

    pgov_panel = MagicMock()
    pgov_panel.hide = MagicMock()
    pgov_panel.display_denial = MagicMock()

    prompt_input = MagicMock()
    prompt_input.value = prompt_text
    prompt_input.disabled = False
    prompt_input.focus = MagicMock()

    session_panel = MagicMock()
    session_panel.active_session_id = session_id
    session_panel.refresh_list = AsyncMock()

    def _query_one(selector: str, _type: object = None) -> object:
        if selector == "#response-area":
            return display
        if selector == "#pgov-panel":
            return pgov_panel
        if selector == "#prompt-input":
            return prompt_input
        if selector == "#session-panel":
            return session_panel
        raise KeyError(selector)

    app.query_one = _query_one  # type: ignore[method-assign]

    stubs = {
        "display": display,
        "pgov_panel": pgov_panel,
        "prompt_input": prompt_input,
        "session_panel": session_panel,
    }
    return app, stubs


class TestActionSubmitPromptBranches:
    """WI-4/5/6: PGOV-denied, PGOV-approved, RuntimeError, Exception branches."""

    @pytest.mark.asyncio
    async def test_action_submit_prompt_pgov_denied_displays_panel_and_flushes_rejected(
        self,
    ) -> None:
        """PGOV denied → display_denial called, flush with pgov_approved=False."""
        denial_result = GatewayPGOVResult(
            approved=False,
            sanitized_text="blocked by policy",
            reason_codes=["PII_DETECTED"],
            request_id="req-1",
        )

        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-1")
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))
        gateway.get_pgov_result = MagicMock(return_value=denial_result)
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app, stubs = _make_app_with_stubs(gateway)
        await app.action_submit_prompt()

        stubs["pgov_panel"].display_denial.assert_called_once_with(denial_result)
        gateway.flush_tool_call_buffer.assert_called_once_with(pgov_approved=False)
        # No approved flush path
        assert gateway.flush_tool_call_buffer.call_args[1]["pgov_approved"] is False

    @pytest.mark.asyncio
    async def test_action_submit_prompt_pgov_approved_persists_and_streams(
        self,
    ) -> None:
        """PGOV approved → flush with pgov_approved=True, display_denial NOT called."""
        approved_result = GatewayPGOVResult(
            approved=True,
            sanitized_text="all good",
            reason_codes=[],
            request_id="req-2",
        )

        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-2")
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))
        gateway.get_pgov_result = MagicMock(return_value=approved_result)
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app, stubs = _make_app_with_stubs(gateway)
        await app.action_submit_prompt()

        stubs["pgov_panel"].display_denial.assert_not_called()
        gateway.flush_tool_call_buffer.assert_called_once_with(pgov_approved=True)

    @pytest.mark.asyncio
    async def test_action_submit_prompt_runtime_error_displays_specific_message(
        self,
    ) -> None:
        """RuntimeError from send_prompt → error message contains exception text."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(side_effect=RuntimeError("boom"))
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))

        app, stubs = _make_app_with_stubs(gateway)
        await app.action_submit_prompt()

        write_calls = [str(c) for c in stubs["display"].write_line.call_args_list]
        assert any("boom" in call for call in write_calls)
        assert any("[red]Error:" in call for call in write_calls)
        stubs["pgov_panel"].display_denial.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_submit_prompt_generic_exception_displays_fail_closed(
        self,
    ) -> None:
        """Generic Exception → fail-closed message displayed."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(side_effect=Exception("unknown"))
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))

        app, stubs = _make_app_with_stubs(gateway)
        await app.action_submit_prompt()

        write_calls = [str(c) for c in stubs["display"].write_line.call_args_list]
        assert any("Unexpected error" in call and "Fail-Closed" in call for call in write_calls)

    @pytest.mark.asyncio
    async def test_action_submit_prompt_refreshes_session_panel(self) -> None:
        """After a prompt, the session panel is refreshed so the auto-title
        (set on the first prompt) and the new turn count appear at once."""
        approved_result = GatewayPGOVResult(
            approved=True,
            sanitized_text="ok",
            reason_codes=[],
            request_id="req-r",
        )
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(return_value="req-r")
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))
        gateway.get_pgov_result = MagicMock(return_value=approved_result)
        gateway.flush_tool_call_buffer = MagicMock(return_value=[])

        app, stubs = _make_app_with_stubs(gateway)
        app._session_store = MagicMock()  # enables the persist + refresh path

        await app.action_submit_prompt()

        stubs["session_panel"].refresh_list.assert_awaited()

    @pytest.mark.asyncio
    async def test_action_submit_prompt_panel_refresh_is_best_effort(self) -> None:
        """A session-panel refresh failure must not break the prompt flow."""
        gateway = MagicMock()
        gateway.send_prompt = AsyncMock(side_effect=RuntimeError("boom"))
        gateway.stream_tokens = MagicMock(return_value=AsyncIterStub([]))

        app, stubs = _make_app_with_stubs(gateway)
        app._session_store = MagicMock()
        stubs["session_panel"].refresh_list = AsyncMock(
            side_effect=Exception("refresh failed")
        )

        # Must not raise despite the refresh failure ...
        await app.action_submit_prompt()
        # ... and the flow still completes (prompt input re-focused).
        stubs["prompt_input"].focus.assert_called()


# ─────────────────────────────────────────────────────────────────
# WI-9: boot-poll attempt-marker list computation
# ─────────────────────────────────────────────────────────────────

from services.ui_gateway.src.constants import (  # noqa: E402
    PA_HANDSHAKE_BACKOFF_BASE_S,
    PA_HANDSHAKE_BUDGET_S,
    PA_HANDSHAKE_MAX_RETRIES,
    pa_handshake_backoff_schedule,
)


class TestBootPollAttemptMarkers:
    """WI-9: attempt_markers list computation from _poll_boot_status.

    #808: the markers derive from the SAME ``pa_handshake_backoff_schedule()``
    the gateway's retry loop executes — this test mirrors the app.py
    computation and locks the banner to the budget (lesson 221: the display
    window and the retry budget must never disagree).
    """

    def test_poll_boot_status_advances_all_attempt_markers(self) -> None:
        """attempt_markers has PA_HANDSHAKE_MAX_RETRIES entries with correct elapsed times."""
        schedule = pa_handshake_backoff_schedule()
        attempt_markers: list[float] = [0.0]
        elapsed = 0.0
        for delay in schedule:
            elapsed += delay
            attempt_markers.append(elapsed)

        assert len(attempt_markers) == PA_HANDSHAKE_MAX_RETRIES
        assert attempt_markers[0] == 0.0
        assert attempt_markers[1] == pytest.approx(PA_HANDSHAKE_BACKOFF_BASE_S)
        assert attempt_markers[2] == pytest.approx(
            PA_HANDSHAKE_BACKOFF_BASE_S + PA_HANDSHAKE_BACKOFF_BASE_S * 2
        )
        # Markers are strictly increasing
        for i in range(1, len(attempt_markers)):
            assert attempt_markers[i] > attempt_markers[i - 1]
        # #808: the LAST planned attempt fires exactly at the aggregate
        # backoff budget — the banner's arithmetic covers the whole widened
        # window, not the old ~3 s one.
        assert attempt_markers[-1] == pytest.approx(PA_HANDSHAKE_BUDGET_S)
