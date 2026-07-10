"""
Tests for the Launcher Entry Point
====================================
Validates the startup sequence with mocked dependencies.
Does NOT actually start VMs or Textual apps — all components are mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We test the main() function by mocking all its dependencies.
# The imports inside main() are at module level, so we patch them there.


class TestLauncherMain:
    """Tests for launcher.__main__.main()."""

    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.BlarAIApp")
    @patch("launcher.__main__.TransportGateway")
    @patch("launcher.__main__.build_session_store")
    @patch("launcher.__main__.build_shared_pipeline")
    @patch("launcher.__main__._run_uat2_prompt_flow_preflight", return_value=True)
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_production_happy_path(
        self,
        _mock_admin,
        mock_vm_state,
        _mock_ensure_vm,
        _mock_prompt_flow,
        mock_build_pipeline,
        mock_build_store,
        mock_gateway_cls,
        mock_app_cls,
        mock_policy_service_cls,
        mock_orchestrator_service_cls,
    ) -> None:
        """Full happy path: admin, VM, PA, AO, session store, gateway, handshake, TUI.

        build_shared_pipeline (Step 4) is mocked to a successful build so the
        test does not require the Qwen3-14B model files on disk (absent in
        model-less checkouts/worktrees); previously this test silently depended
        on those files being present.
        """
        from launcher.__main__ import VMState, main

        mock_vm_state.return_value = VMState.RUNNING

        mock_build_result = MagicMock()
        mock_build_result.ok = True
        mock_build_result.pipeline = MagicMock()
        mock_build_result.error = None
        mock_build_pipeline.return_value = mock_build_result

        mock_build_store.return_value = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.check_pa_status = AsyncMock(return_value=True)
        mock_gateway_cls.return_value = mock_gateway
        mock_app_cls.return_value = MagicMock()

        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = True
        mock_policy_service.running = True
        mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service

        mock_orchestrator_service = MagicMock()
        mock_orchestrator_service.start.return_value = True
        mock_orchestrator_service.running = True
        mock_orchestrator_service_cls.from_runtime_mode.return_value = (
            mock_orchestrator_service
        )

        result = main()

        assert result == 0
        mock_policy_service_cls.from_runtime_mode.assert_called_once()
        mock_orchestrator_service_cls.from_runtime_mode.assert_called_once()
        mock_gateway_cls.assert_called_once()
        mock_app_cls.return_value.run.assert_called_once()
        # #670: the launcher provides the AO its swap context — the REAL relaunch invocation
        # (python -m launcher [...]) + the daemon→main step-aside callable — so EXECUTE can
        # fire on go-live (a future edit that stops threading it fails loud here).
        mock_orchestrator_service.set_swap_context.assert_called_once()
        _ctx = mock_orchestrator_service.set_swap_context.call_args.kwargs
        assert _ctx["relaunch_argv"][1:3] == ["-m", "launcher"]
        assert _ctx["relaunch_cwd"] and callable(_ctx["step_aside"])

    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.BlarAIApp")
    @patch("launcher.__main__.TransportGateway")
    @patch("launcher.__main__.build_session_store")
    @patch("launcher.__main__.build_shared_pipeline")
    @patch("launcher.__main__._run_uat2_prompt_flow_preflight", return_value=True)
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_gateway_wires_images_enabled_from_orchestrator(
        self,
        _mock_admin,
        mock_vm_state,
        _mock_ensure_vm,
        _mock_prompt_flow,
        mock_build_pipeline,
        mock_build_store,
        mock_gateway_cls,
        mock_app_cls,
        mock_policy_service_cls,
        mock_orchestrator_service_cls,
    ) -> None:
        """TD-2 (#663): the launcher threads the AO-resolved
        [knowledge].images_enabled weld-lock into the TransportGateway as
        ``images_enabled=`` — read off the already-started orchestrator service,
        never a second TOML parse — so the gateway-side image FETCH gate honors
        the same flag the AO storage gate reads (single source of truth)."""
        from launcher.__main__ import VMState, main

        mock_vm_state.return_value = VMState.RUNNING

        mock_build_result = MagicMock()
        mock_build_result.ok = True
        mock_build_result.pipeline = MagicMock()
        mock_build_result.error = None
        mock_build_pipeline.return_value = mock_build_result

        mock_build_store.return_value = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.check_pa_status = AsyncMock(return_value=True)
        mock_gateway_cls.return_value = mock_gateway
        mock_app_cls.return_value = MagicMock()

        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = True
        mock_policy_service.running = True
        mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service

        # A SENTINEL value distinct from any constant: the assertion proves the
        # gateway received THIS object (the AO-resolved flag), not a hard-coded
        # default — so a future edit that stops threading it would fail loud.
        sentinel_flag = object()
        mock_orchestrator_service = MagicMock()
        mock_orchestrator_service.start.return_value = True
        mock_orchestrator_service.running = True
        mock_orchestrator_service.knowledge_images_enabled = sentinel_flag
        mock_orchestrator_service_cls.from_runtime_mode.return_value = (
            mock_orchestrator_service
        )

        result = main()

        assert result == 0
        mock_gateway_cls.assert_called_once()
        assert (
            mock_gateway_cls.call_args.kwargs["images_enabled"] is sentinel_flag
        )

    @patch("launcher.__main__.request_elevation", return_value=True)
    @patch("launcher.__main__.is_admin", return_value=False)
    def test_requests_elevation_when_not_admin(
        self, mock_admin, mock_elevation
    ) -> None:
        """Should request elevation and return 0 when UAC is accepted."""
        from launcher.__main__ import main

        result = main()
        assert result == 0
        mock_elevation.assert_called_once()

    @patch("launcher.__main__.input", return_value="")  # Mock input() for the Enter prompt
    @patch("launcher.__main__.request_elevation", return_value=False)
    @patch("launcher.__main__.is_admin", return_value=False)
    def test_elevation_denied_returns_1(
        self, mock_admin, mock_elevation, mock_input
    ) -> None:
        """Should return 1 when UAC elevation is denied."""
        from launcher.__main__ import main

        result = main()
        assert result == 1

    @patch("launcher.__main__.input", return_value="")
    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_policy_entrypoint_failure_returns_1(
        self,
        mock_admin,
        mock_vm_state,
        mock_ensure_vm,
        mock_policy_service_cls,
        mock_orchestrator_service_cls,
        mock_input,
    ) -> None:
        """Fail-Closed: Policy Agent startup failure must abort launcher."""
        from launcher.__main__ import main, VMState

        mock_vm_state.return_value = VMState.RUNNING

        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = False
        mock_policy_service.measured_boot_state = None
        mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service

        result = main()
        assert result == 1
        mock_orchestrator_service_cls.from_runtime_mode.assert_not_called()

    @patch("launcher.__main__.input", return_value="")
    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_orchestrator_entrypoint_failure_returns_1(
        self,
        mock_admin,
        mock_vm_state,
        mock_ensure_vm,
        mock_policy_service_cls,
        mock_orchestrator_service_cls,
        mock_input,
    ) -> None:
        """Fail-Closed: Orchestrator startup failure must abort launcher."""
        from launcher.__main__ import main, VMState

        mock_vm_state.return_value = VMState.RUNNING

        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = True
        mock_policy_service.running = True
        mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service

        mock_orchestrator_service = MagicMock()
        mock_orchestrator_service.start.return_value = False
        mock_orchestrator_service_cls.from_runtime_mode.return_value = mock_orchestrator_service

        result = main()
        assert result == 1

    @patch("launcher.__main__.input", return_value="")
    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.ensure_vm_running", return_value=False)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_vm_failure_is_fatal(
        self,
        _mock_admin,
        mock_vm_state,
        _mock_ensure_vm,
        _mock_policy_service_cls,
        _mock_orchestrator_service_cls,
        _mock_input,
    ) -> None:
        """VM start failure must abort launcher (Fail-Closed)."""
        from launcher.__main__ import VMState, main

        mock_vm_state.return_value = VMState.OFF

        result = main()
        assert result == 1

    @patch("launcher.__main__.input", return_value="")
    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.BlarAIApp")
    @patch("launcher.__main__.TransportGateway")
    @patch("launcher.__main__.build_session_store")
    @patch("launcher.__main__.build_shared_pipeline")
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_handshake_failure_is_fatal(
        self,
        _mock_admin,
        mock_vm_state,
        _mock_ensure_vm,
        mock_build_pipeline,
        mock_build_store,
        mock_gateway_cls,
        _mock_app_cls,
        mock_policy_service_cls,
        mock_orchestrator_service_cls,
        _mock_input,
    ) -> None:
        """Handshake preflight failure must abort launcher (Fail-Closed).

        Mocks build_shared_pipeline (Step 4) so the launcher reaches the
        handshake step regardless of model-file presence -- otherwise this test
        could pass for the wrong reason (a Step-4 build failure also returns 1).
        """
        from launcher.__main__ import VMState, main

        mock_vm_state.return_value = VMState.RUNNING

        mock_build_result = MagicMock()
        mock_build_result.ok = True
        mock_build_result.pipeline = MagicMock()
        mock_build_result.error = None
        mock_build_pipeline.return_value = mock_build_result

        mock_build_store.return_value = MagicMock()

        mock_gateway = MagicMock()
        mock_gateway.check_pa_status = AsyncMock(return_value=False)
        mock_gateway_cls.return_value = mock_gateway

        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = True
        mock_policy_service.running = True
        mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service

        mock_orchestrator_service = MagicMock()
        mock_orchestrator_service.start.return_value = True
        mock_orchestrator_service.running = True
        mock_orchestrator_service_cls.from_runtime_mode.return_value = (
            mock_orchestrator_service
        )

        result = main()
        assert result == 1


# ---------------------------------------------------------------------------
# Sprint 14 EA-4: production session-store encryption-wiring regression lock
# ---------------------------------------------------------------------------


class TestSessionStoreEncryptionWiringLock:
    """Regression lock WITH TEETH for the launcher's session-store wiring.

    Unlike the happy-path tests above (which MOCK build_session_store and so
    would still pass if the call site were swapped back to a plaintext
    SessionStore), these tests exercise the launcher's REAL Step-5 construction
    and assert the resulting store is the encrypted variant.  They catch a
    future refactor that silently re-wires the production call site to the
    plaintext SessionStore (the Sprint-13 "built but wired into nothing" trap,
    lesson 46).
    """

    @patch("launcher.__main__.input", return_value="")
    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.BlarAIApp")
    @patch("launcher.__main__.TransportGateway")
    @patch("launcher.__main__.build_shared_pipeline")
    @patch("launcher.__main__._run_uat2_prompt_flow_preflight", return_value=True)
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_launcher_builds_encrypted_session_store(
        self,
        _mock_admin,
        mock_vm_state,
        _mock_ensure_vm,
        _mock_prompt_flow,
        mock_build_pipeline,
        _mock_gateway_cls,
        _mock_app_cls,
        _mock_policy_service_cls,
        _mock_orchestrator_service_cls,
        _mock_input,
        monkeypatch,
    ) -> None:
        """Run the launcher's real Step-5 (build_session_store NOT mocked) and
        assert the module-global _session_store is an EncryptedSessionStore.

        Forces the in-memory dev DEK path by clearing LOCALAPPDATA +
        BLARAI_DEK_KEYSTORE and pointing SESSION_DB_PATH at ':memory:' so no
        TPM / keystore file is required and the test is hardware-independent.

        build_shared_pipeline (Step 4) is mocked to a successful build -- it
        requires the Qwen3-14B model files on disk, which are not present in
        every checkout/worktree; mocking it lets main() reach Step 5 regardless.
        Everything EXCEPT build_session_store is mocked, so this exercises the
        real session-store wiring.
        """
        import launcher.__main__ as main_mod
        from services.ui_gateway.src.session_store import EncryptedSessionStore

        # Dev DEK path: no keystore, no LOCALAPPDATA -> SoftwareSealer + in-memory.
        monkeypatch.setenv("LOCALAPPDATA", "")
        monkeypatch.setenv("BLARAI_DEK_KEYSTORE", "")
        # Force the launcher's db_path resolution to ':memory:'.
        monkeypatch.setattr(main_mod, "SESSION_DB_PATH", "", raising=False)

        mock_vm_state.return_value = main_mod.VMState.RUNNING

        # Step 4: shared pipeline build succeeds (no real model files needed).
        mock_build_result = MagicMock()
        mock_build_result.ok = True
        mock_build_result.pipeline = MagicMock()
        mock_build_result.error = None
        mock_build_pipeline.return_value = mock_build_result

        mock_gateway = MagicMock()
        mock_gateway.check_pa_status = AsyncMock(return_value=True)
        _mock_gateway_cls.return_value = mock_gateway
        _mock_app_cls.return_value = MagicMock()

        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = True
        mock_policy_service.running = True
        _mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service

        mock_orchestrator_service = MagicMock()
        mock_orchestrator_service.start.return_value = True
        mock_orchestrator_service.running = True
        _mock_orchestrator_service_cls.from_runtime_mode.return_value = (
            mock_orchestrator_service
        )

        # build_session_store is deliberately NOT mocked -- the real factory runs.
        result = main_mod.main()
        assert result == 0, "launcher did not reach a clean exit"

        store = main_mod._session_store
        assert store is not None, (
            "launcher did not build a session store (Step 5 wiring missing)"
        )
        assert isinstance(store, EncryptedSessionStore), (
            f"launcher built {type(store).__name__!r}, expected "
            "'EncryptedSessionStore' -- production session DB would be PLAINTEXT. "
            "The Step-5 call site was likely re-wired to the unencrypted "
            "SessionStore (Sprint-13 'built but wired into nothing' trap)."
        )
        assert store.has_encryption is True, (
            "launcher's session store has has_encryption != True -- "
            "encryption silently disabled"
        )

    def test_launcher_imports_build_session_store_not_plaintext_ctor(self) -> None:
        """The launcher module must expose build_session_store and must NOT have
        re-imported the plaintext SessionStore as a construction symbol.

        A cheap, fast guard complementing the run-through test above: if a
        refactor re-adds ``from ... import SessionStore`` and uses it at the call
        site, this catches the symbol's reappearance at module scope.
        """
        import launcher.__main__ as main_mod

        assert hasattr(main_mod, "build_session_store"), (
            "launcher.__main__ no longer imports build_session_store -- "
            "the encrypted construction path is gone"
        )
        # SessionStore (plaintext) must not be a module-level name in the
        # launcher; only the encrypted factory + class should be wired.
        assert not hasattr(main_mod, "SessionStore"), (
            "launcher.__main__ re-imported the plaintext SessionStore -- "
            "this is the symbol a refactor would use to re-wire the call site "
            "back to an unencrypted store"
        )


# ---------------------------------------------------------------------------
# EA-4 WI-7: TestRunUat2PromptFlowPreflight
# ---------------------------------------------------------------------------


class TestRunUat2PromptFlowPreflight:
    """Sprint 8 EA-4 WI-7: _run_uat2_prompt_flow_preflight success + exception branches."""

    @patch("launcher.__main__._record_prompt_flow_evidence")
    def test_success_writes_pass_evidence(self, mock_record) -> None:
        from launcher.__main__ import _run_uat2_prompt_flow_preflight
        from shared.runtime_config import DeploymentMode

        mock_session_store = MagicMock()
        mock_session_store.create_session.return_value = "sess-1"

        class _StreamToken:
            def __init__(self, token: str) -> None:
                self.token = token

        class _PgovResult:
            approved = True
            sanitized_text = ""
            reason_codes: list = []

        mock_gateway = MagicMock()
        mock_gateway.send_prompt = AsyncMock(return_value="req-1")

        async def _stream(_sid):
            yield _StreamToken("hello")

        mock_gateway.stream_tokens = _stream
        mock_gateway.get_pgov_result.return_value = _PgovResult()

        ok = _run_uat2_prompt_flow_preflight(
            gateway=mock_gateway,
            session_store=mock_session_store,
            runtime_mode=DeploymentMode.HOST,
        )
        assert ok is True
        mock_session_store.delete_session.assert_called_once_with("sess-1")
        assert mock_record.called
        payload = mock_record.call_args.args[0]
        assert payload["disposition"] == "PASS"

    @patch("launcher.__main__._record_prompt_flow_evidence")
    def test_exception_writes_fail_evidence(self, mock_record) -> None:
        from launcher.__main__ import _run_uat2_prompt_flow_preflight
        from shared.runtime_config import DeploymentMode

        mock_session_store = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.send_prompt = AsyncMock(side_effect=RuntimeError("boom"))

        async def _stream(_sid):
            if False:
                yield

        mock_gateway.stream_tokens = _stream

        ok = _run_uat2_prompt_flow_preflight(
            gateway=mock_gateway,
            session_store=mock_session_store,
            runtime_mode=DeploymentMode.GUEST,
        )
        assert ok is False
        payload = mock_record.call_args.args[0]
        assert payload["disposition"] == "FAIL"
        assert payload["failure"]["code"] == "UAT2_PROMPT_FLOW_FAILED"


# ---------------------------------------------------------------------------
# EA-4 WI-8: TestCleanupAtExit
# ---------------------------------------------------------------------------


class TestCleanupAtExit:
    """Sprint 8 EA-4 WI-8 + 2026-06-10 vm-stop-ratchet fix: _cleanup guards.

    All cases mock Hyper-V fully — ``stop_vm`` and ``get_vm_state`` are patched
    on ``launcher.__main__`` so no real VM is ever touched.  The 2026-06-10 fix
    introduced the ``vm_stop_on_exit`` policy (``always`` (default) /
    ``if_started`` / ``never``); these cases pin each policy via the
    ``BLARAI_VM_STOP_ON_EXIT`` env var (or its absence for the default) so the
    ambient environment cannot perturb them.
    """

    def test_services_running_vm_was_started(self, monkeypatch) -> None:
        """Default policy (always) + VM Running → services stop AND VM stops."""
        import launcher.__main__ as main_mod

        monkeypatch.delenv("BLARAI_VM_STOP_ON_EXIT", raising=False)

        pa = MagicMock()
        pa.running = True
        ao = MagicMock()
        ao.running = True
        store = MagicMock()
        stop_vm_mock = MagicMock(return_value=True)

        monkeypatch.setattr(main_mod, "_policy_agent_service", pa)
        monkeypatch.setattr(main_mod, "_orchestrator_service", ao)
        monkeypatch.setattr(main_mod, "_session_store", store)
        monkeypatch.setattr(main_mod, "_vm_was_started", True)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(
            main_mod, "get_vm_state", MagicMock(return_value=main_mod.VMState.RUNNING)
        )

        main_mod._cleanup()

        pa.stop.assert_called_once()
        ao.stop.assert_called_once()
        store.close.assert_called_once()
        stop_vm_mock.assert_called_once()

    def test_services_not_running_skip_stop_but_stop_vm(self, monkeypatch) -> None:
        """Stopped services are not re-stopped; default policy still stops a Running VM."""
        import launcher.__main__ as main_mod

        monkeypatch.delenv("BLARAI_VM_STOP_ON_EXIT", raising=False)

        pa = MagicMock()
        pa.running = False
        ao = MagicMock()
        ao.running = False
        stop_vm_mock = MagicMock(return_value=True)

        monkeypatch.setattr(main_mod, "_policy_agent_service", pa)
        monkeypatch.setattr(main_mod, "_orchestrator_service", ao)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", True)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(
            main_mod, "get_vm_state", MagicMock(return_value=main_mod.VMState.RUNNING)
        )

        main_mod._cleanup()

        pa.stop.assert_not_called()
        ao.stop.assert_not_called()
        stop_vm_mock.assert_called_once()

    # ── always-policy (NEW DEFAULT) — the ratchet fix ────────────────────────

    def test_always_policy_stops_when_not_started_but_running(self, monkeypatch) -> None:
        """THE RATCHET FIX: always-policy stops a Running VM even though THIS
        launcher did not start it (``_vm_was_started=False``).  Under the legacy
        if_started behaviour this VM leaked forever."""
        import launcher.__main__ as main_mod

        monkeypatch.setenv("BLARAI_VM_STOP_ON_EXIT", "always")

        stop_vm_mock = MagicMock(return_value=True)
        get_state_mock = MagicMock(return_value=main_mod.VMState.RUNNING)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", False)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        main_mod._cleanup()

        get_state_mock.assert_called_once()
        stop_vm_mock.assert_called_once()

    def test_always_policy_skips_when_vm_off(self, monkeypatch) -> None:
        """always-policy + VM already Off → NO spurious Stop-VM."""
        import launcher.__main__ as main_mod

        monkeypatch.setenv("BLARAI_VM_STOP_ON_EXIT", "always")

        stop_vm_mock = MagicMock(return_value=True)
        get_state_mock = MagicMock(return_value=main_mod.VMState.OFF)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", True)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        main_mod._cleanup()

        get_state_mock.assert_called_once()
        stop_vm_mock.assert_not_called()

    # ── if_started-policy (legacy behaviour, now opt-in) ─────────────────────

    def test_if_started_policy_skips_stop_when_not_started(self, monkeypatch) -> None:
        """if_started + ``_vm_was_started=False`` → VM left running (legacy case).

        This is the former ``test_vm_was_not_started_skips_stop_vm`` re-cast as
        the explicit if_started policy.  Under if_started, ``get_vm_state`` is
        NOT consulted — the decision rests solely on ``_vm_was_started``."""
        import launcher.__main__ as main_mod

        monkeypatch.setenv("BLARAI_VM_STOP_ON_EXIT", "if_started")

        pa = MagicMock()
        pa.running = True
        stop_vm_mock = MagicMock(return_value=True)
        get_state_mock = MagicMock(return_value=main_mod.VMState.RUNNING)

        monkeypatch.setattr(main_mod, "_policy_agent_service", pa)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", False)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        main_mod._cleanup()

        pa.stop.assert_called_once()
        stop_vm_mock.assert_not_called()
        get_state_mock.assert_not_called()

    def test_if_started_policy_stops_when_started(self, monkeypatch) -> None:
        """if_started + ``_vm_was_started=True`` → VM stops (this launcher owns it)."""
        import launcher.__main__ as main_mod

        monkeypatch.setenv("BLARAI_VM_STOP_ON_EXIT", "if_started")

        stop_vm_mock = MagicMock(return_value=True)
        get_state_mock = MagicMock(return_value=main_mod.VMState.RUNNING)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", True)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        main_mod._cleanup()

        stop_vm_mock.assert_called_once()
        # if_started never consults live state — it trusts _vm_was_started.
        get_state_mock.assert_not_called()

    # ── never-policy ─────────────────────────────────────────────────────────

    def test_never_policy_never_stops(self, monkeypatch) -> None:
        """never-policy → VM is left Running regardless of state or _vm_was_started."""
        import launcher.__main__ as main_mod

        monkeypatch.setenv("BLARAI_VM_STOP_ON_EXIT", "never")

        stop_vm_mock = MagicMock(return_value=True)
        get_state_mock = MagicMock(return_value=main_mod.VMState.RUNNING)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", True)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        main_mod._cleanup()

        stop_vm_mock.assert_not_called()
        # never short-circuits before any live-state query.
        get_state_mock.assert_not_called()

    # ── best-effort robustness on the slow path ──────────────────────────────

    def test_stop_vm_returns_false_logs_warning_and_completes(
        self, monkeypatch, caplog
    ) -> None:
        """stop_vm() returning False (timeout / Stop-VM failure) → WARNING logged,
        cleanup STILL completes (never raises on the atexit path)."""
        import logging

        import launcher.__main__ as main_mod

        monkeypatch.delenv("BLARAI_VM_STOP_ON_EXIT", raising=False)  # default: always

        stop_vm_mock = MagicMock(return_value=False)
        get_state_mock = MagicMock(return_value=main_mod.VMState.RUNNING)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", True)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        # Capture at INFO so both the WARNING and the final INFO "complete"
        # line are recorded (the 'complete' line proves cleanup ran to the end).
        with caplog.at_level(logging.INFO, logger="blarai.launcher"):
            main_mod._cleanup()  # must not raise

        stop_vm_mock.assert_called_once()
        assert any(
            record.levelno == logging.WARNING
            and "did not confirm" in record.getMessage()
            for record in caplog.records
        ), "expected a WARNING when stop_vm() returns False"
        # cleanup ran to the end — the 'complete' line is always logged last.
        assert any(
            "Cleanup: complete" in record.getMessage() for record in caplog.records
        )

    def test_unrecognised_policy_falls_back_to_always(self, monkeypatch) -> None:
        """A typo'd policy value resolves to the safe default (always), never to
        a leak — so a misconfiguration cannot silently re-arm the ratchet."""
        import launcher.__main__ as main_mod

        monkeypatch.setenv("BLARAI_VM_STOP_ON_EXIT", "sometimes-maybe")

        assert main_mod._resolve_vm_stop_policy() == main_mod.VM_STOP_POLICY_ALWAYS

        stop_vm_mock = MagicMock(return_value=True)
        get_state_mock = MagicMock(return_value=main_mod.VMState.RUNNING)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", False)
        monkeypatch.setattr(main_mod, "stop_vm", stop_vm_mock)
        monkeypatch.setattr(main_mod, "get_vm_state", get_state_mock)

        main_mod._cleanup()

        stop_vm_mock.assert_called_once()

    def test_session_store_close_called(self, monkeypatch) -> None:
        import launcher.__main__ as main_mod

        monkeypatch.delenv("BLARAI_VM_STOP_ON_EXIT", raising=False)

        store = MagicMock()
        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", store)
        monkeypatch.setattr(main_mod, "_vm_was_started", False)
        monkeypatch.setattr(main_mod, "stop_vm", MagicMock(return_value=True))
        # default policy (always) queries live state — VM Off means no stop,
        # and this case only asserts the session store is closed.
        monkeypatch.setattr(
            main_mod, "get_vm_state", MagicMock(return_value=main_mod.VMState.OFF)
        )

        main_mod._cleanup()

        store.close.assert_called_once()

    def test_all_none_guards_no_attribute_error(self, monkeypatch) -> None:
        import launcher.__main__ as main_mod

        monkeypatch.delenv("BLARAI_VM_STOP_ON_EXIT", raising=False)

        monkeypatch.setattr(main_mod, "_policy_agent_service", None)
        monkeypatch.setattr(main_mod, "_orchestrator_service", None)
        monkeypatch.setattr(main_mod, "_session_store", None)
        monkeypatch.setattr(main_mod, "_vm_was_started", False)
        monkeypatch.setattr(main_mod, "stop_vm", MagicMock(return_value=True))
        monkeypatch.setattr(
            main_mod, "get_vm_state", MagicMock(return_value=main_mod.VMState.OFF)
        )

        main_mod._cleanup()


class TestPromptFlowPreflightGate:
    """_prompt_flow_preflight_enabled(dev_mode=...) gates the real model-loaded boot check.

    Contract (S15 host-mode-routing fix):
      * Production (dev_mode=False): ON by default — the real prompt-path gate
        that catches a PROMPT_REQUEST misroute at boot. Reversible via an
        explicit OFF env value.
      * Dev (dev_mode=True): OFF by default (fast iterative launches); opt in
        via an explicit truthy env value.
      * The env var is an explicit override in BOTH directions and always wins.
    """

    def test_production_enabled_by_default(self, monkeypatch) -> None:
        """REGRESSION: production must run the real prompt-flow gate by default."""
        from launcher.__main__ import _prompt_flow_preflight_enabled

        monkeypatch.delenv("BLARAI_PROMPTFLOW_PREFLIGHT", raising=False)
        assert _prompt_flow_preflight_enabled(dev_mode=False) is True

    def test_dev_disabled_by_default(self, monkeypatch) -> None:
        from launcher.__main__ import _prompt_flow_preflight_enabled

        monkeypatch.delenv("BLARAI_PROMPTFLOW_PREFLIGHT", raising=False)
        assert _prompt_flow_preflight_enabled(dev_mode=True) is False

    def test_explicit_off_override_skips_in_production(self, monkeypatch) -> None:
        """The production default-ON is reversible via an explicit OFF value."""
        from launcher.__main__ import _prompt_flow_preflight_enabled

        for value in ("0", "false", "FALSE", "no", "off"):
            monkeypatch.setenv("BLARAI_PROMPTFLOW_PREFLIGHT", value)
            assert _prompt_flow_preflight_enabled(dev_mode=False) is False, value

    def test_explicit_on_override_runs_in_dev(self, monkeypatch) -> None:
        """Dev can opt in to the gate via an explicit truthy value."""
        from launcher.__main__ import _prompt_flow_preflight_enabled

        for value in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("BLARAI_PROMPTFLOW_PREFLIGHT", value)
            assert _prompt_flow_preflight_enabled(dev_mode=True) is True, value

    def test_blank_or_unknown_env_falls_back_to_mode_default(self, monkeypatch) -> None:
        """Blank/whitespace/unrecognised env → mode default (prod ON, dev OFF)."""
        from launcher.__main__ import _prompt_flow_preflight_enabled

        for value in ("", "  ", "maybe"):
            monkeypatch.setenv("BLARAI_PROMPTFLOW_PREFLIGHT", value)
            assert _prompt_flow_preflight_enabled(dev_mode=False) is True, repr(value)
            assert _prompt_flow_preflight_enabled(dev_mode=True) is False, repr(value)


class TestVoicePreload:
    """VOICE_ENABLED gates whether the launcher preloads the voice models (#561).

    Always-off-at-boot (#660 decision #3): even with VOICE_ENABLED False the
    engine is built path-aware (``with_paths``) so the WinUI toggles can load each
    half on demand in-session — no model occupies RAM at launch.
    """

    def test_voice_disabled_skips_model_load(self) -> None:
        from pathlib import Path

        from launcher.__main__ import _build_voice_engine

        with patch("launcher.__main__.VOICE_ENABLED", False), \
                patch("launcher.__main__.VoiceEngine.load") as mock_load:
            engine = _build_voice_engine(Path("."))

        mock_load.assert_not_called()  # no Whisper/Kokoro preloaded — RAM saved
        assert engine.stt_available is False
        assert engine.tts_available is False  # speak gate -> no auto recital

    def test_voice_disabled_builds_path_aware_engine_for_on_demand_load(self) -> None:
        # #660: boot-off must still remember the model paths so the toggles can
        # load on demand. Use a repo_root whose model paths exist so the engine
        # records them (existence-gated in _build_voice_engine).
        from pathlib import Path

        from launcher.__main__ import _build_voice_engine

        with patch("launcher.__main__.VOICE_ENABLED", False), \
                patch("launcher.__main__.VoiceEngine.load") as mock_load, \
                patch("pathlib.Path.is_dir", return_value=True), \
                patch("pathlib.Path.is_file", return_value=True):
            engine = _build_voice_engine(Path("/repo"))

        mock_load.assert_not_called()
        # Path-aware: the engine knows where to load each half from on demand.
        assert engine._whisper_dir is not None
        assert engine._kokoro_model is not None
        assert engine._kokoro_voices is not None
        # But nothing is loaded yet (RAM-safe at boot).
        assert engine.stt_available is False
        assert engine.tts_available is False

    def test_voice_enabled_loads_models(self) -> None:
        from pathlib import Path

        from launcher.__main__ import _build_voice_engine

        loaded = MagicMock()
        loaded.stt_available = True
        loaded.tts_available = True
        loaded.available_voices.return_value = ["af_heart"]
        with patch("launcher.__main__.VOICE_ENABLED", True), \
                patch("launcher.__main__.VoiceEngine.load", return_value=loaded) as mock_load:
            engine = _build_voice_engine(Path("."))

        mock_load.assert_called_once()
        assert engine is loaded


class TestGoLiveFlag:
    """The --go-live CLI flag — the elevation-surviving operator door-opener (#655)."""

    def test_flag_present_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from launcher.__main__ import _go_live_requested

        monkeypatch.setattr("sys.argv", ["launcher", "--winui", "--go-live"])
        assert _go_live_requested() is True

    def test_flag_absent_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from launcher.__main__ import _go_live_requested

        monkeypatch.setattr("sys.argv", ["launcher", "--winui"])
        assert _go_live_requested() is False

    def test_flag_translates_to_guest_parser_enable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--go-live -> BLARAI_GUEST_PARSER_ENABLED -> load_guest_parser_config enables.

        Proves the flag actually opens the door: the env var the flag sets in-process
        is the same one load_guest_parser_config reads, so a committed enabled=false
        section comes back enabled=True under the flag (and stays welded without it)."""
        import tomllib

        from launcher.guest_parser import load_guest_parser_config

        # A minimal valid [guest_parser] section with enabled=false (welded at rest).
        # Use the shipped default config path so the section is real + valid.
        from launcher.guest_parser import default_config_path

        with open(default_config_path(), "rb") as fh:
            assert tomllib.load(fh)["guest_parser"]["enabled"] is False, (
                "committed default must stay welded (enabled=false)"
            )

        # Without the flag/env -> disabled (welded).
        monkeypatch.delenv("BLARAI_GUEST_PARSER_ENABLED", raising=False)
        assert load_guest_parser_config().enabled is False

        # The flag sets this env var in-process (see main()); the config then enables.
        monkeypatch.setenv("BLARAI_GUEST_PARSER_ENABLED", "true")
        assert load_guest_parser_config().enabled is True


class _HardExitCalled(BaseException):
    """Sentinel raised by the mocked ``os._exit`` so the test can observe it.

    BaseException (not Exception) so no fail-soft handler in ``main()`` can
    swallow it — exactly like the real ``os._exit``, nothing downstream runs.
    """


class TestInstanceLockRefusal:
    """The #670 single-instance refusal path: hard exit, nothing touched.

    Gate-integrity regression lock for 2026-07-04: a pytest run from a
    checkout whose ``certs/launcher.lock`` a LIVE BlarAI held reached the
    REAL refusal path and its ``os._exit(1)`` killed the whole pytest
    process — the standing gate truncated silently at 76% with no summary.
    The autouse conftest guard now isolates the lock for every launcher
    test; THIS test re-patches the lock to a refusal and pins the
    production semantics the guard must not erase: refuse -> flush logs ->
    hard exit 1, WITHOUT starting the VM and WITHOUT releasing (someone
    else's) lock.
    """

    @patch("launcher.__main__.os._exit", side_effect=_HardExitCalled)
    @patch("launcher.__main__.ensure_vm_running")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_refused_lock_hard_exits_before_any_service_work(
        self,
        _mock_admin,
        mock_ensure_vm,
        mock_os_exit,
    ) -> None:
        import launcher.__main__ as main_mod
        from launcher.instance_lock import InstanceLockResult

        refused = InstanceLockResult(acquired=False, holder_pid=4048)
        with (
            patch.object(
                main_mod, "acquire_instance_lock", return_value=refused
            ),
            patch.object(main_mod, "release_instance_lock") as mock_release,
        ):
            with pytest.raises(_HardExitCalled):
                main_mod.main()

        mock_os_exit.assert_called_once_with(1)
        # A refused instance acquired nothing and must start nothing:
        mock_ensure_vm.assert_not_called()
        # ...and must NEVER release the LIVE holder's lock:
        mock_release.assert_not_called()


def _snapshot_certs_dir(path: Path) -> "dict[str, tuple[int, int]] | None":
    """Snapshot ``{filename: (size, mtime_ns)}`` for every file in ``path``.

    Returns ``None`` when ``path`` is absent, so "absent before AND after"
    compares equal while "absent before, present after" (a fresh mint) does not.
    Used by the #751 isolation locks to prove the REAL ``<repo_root>/certs/`` is
    neither created nor modified by a launcher test.
    """
    if not path.exists():
        return None
    return {
        p.name: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(path.iterdir())
        if p.is_file()
    }


class TestPerBootCertIsolation:
    """#751: the standing gate must never mint into the REAL ``<repo_root>/certs/``.

    Root cause (lesson 55 recurrence, observed 2026-07-06): ``main()`` in
    production posture (the HOST default) calls
    ``provision_per_boot_certs(repo_root=<repo_root>)`` at Step 1.5, minting nine
    per-boot PEMs into ``<repo_root>/certs/`` — the SAME dir the shipped PA config
    reads (``certs/pa_server.pem`` / ``certs/ca.pem``). Running the standing gate
    from the operator's LIVE checkout therefore rotated the CA out from under a
    running AO whose in-memory CA no longer matched disk →
    ``CERTIFICATE_VERIFY_FAILED``. The ``LOCALAPPDATA`` redirect the test-isolation
    discipline relies on does NOT cover ``certs/`` (it lives in the repo, not under
    ``LOCALAPPDATA``). The autouse ``conftest.py`` fixture now redirects the mint to
    a tmp dir; these locks pin that isolation so it cannot silently regress.
    """

    def test_fixture_redirects_cert_mint_away_from_repo_certs(self) -> None:
        """The autouse fixture patches the mint binding to write tmp, not the repo.

        Safe by construction — no ``main()`` drive: the binding is already
        redirected, so a mint call carrying a production ``repo_root`` still lands
        in tmp. Proves (a) the ``launcher.__main__`` binding is NOT the real
        function and (b) a mint targeting ``<repo_root>/certs/`` writes a tmp dir,
        leaving the real certs dir byte-for-byte unchanged — while the REAL cert
        minting still runs (coverage preserved).
        """
        import launcher.__main__ as main_mod
        from shared.security.cert_provisioning import (
            provision_per_boot_certs as real_fn,
        )

        # (a) the binding main() uses is the redirect wrapper, not the real fn.
        assert main_mod.provision_per_boot_certs is not real_fn, (
            "the autouse cert-isolation fixture must redirect "
            "launcher.__main__.provision_per_boot_certs (#751)"
        )

        repo_root = Path(main_mod.__file__).resolve().parent.parent
        repo_certs = repo_root / "certs"
        before = _snapshot_certs_dir(repo_certs)

        # Call exactly as main() does at Step 1.5: repo_root=<repo_root>.
        certs = main_mod.provision_per_boot_certs(repo_root=repo_root)

        # The REAL mint ran (coverage) but landed in tmp, NOT <repo_root>/certs/.
        assert certs.ca_cert_path.exists(), "the real per-boot mint must have run"
        assert repo_certs not in certs.ca_cert_path.parents, (
            f"per-boot certs must NOT be minted into {repo_certs}; "
            f"got {certs.ca_cert_path}"
        )
        # And the real certs dir is unchanged by the call (created-or-modified → fail).
        assert _snapshot_certs_dir(repo_certs) == before, (
            f"the redirected mint must not create or modify {repo_certs}"
        )

    @patch("launcher.__main__.AssistantOrchestratorService")
    @patch("launcher.__main__.PolicyAgentService")
    @patch("launcher.__main__.BlarAIApp")
    @patch("launcher.__main__.TransportGateway")
    @patch("launcher.__main__.build_session_store")
    @patch("launcher.__main__.build_shared_pipeline")
    @patch("launcher.__main__._run_uat2_prompt_flow_preflight", return_value=True)
    @patch("launcher.__main__.ensure_vm_running", return_value=True)
    @patch("launcher.__main__.get_vm_state")
    @patch("launcher.__main__.is_admin", return_value=True)
    def test_production_boot_does_not_touch_repo_certs(
        self,
        _mock_admin,
        mock_vm_state,
        _mock_ensure_vm,
        _mock_prompt_flow,
        mock_build_pipeline,
        mock_build_store,
        mock_gateway_cls,
        mock_app_cls,
        mock_policy_service_cls,
        mock_orchestrator_service_cls,
    ) -> None:
        """End-to-end: a full production ``main()`` leaves ``<repo_root>/certs/`` untouched.

        Same mock stack as ``test_production_happy_path`` — the CONFIRMED culprit:
        without the fixture, one run of it mints nine PEMs into the real certs dir.
        A fail-fast pre-assert refuses to drive ``main()`` if the redirect
        regressed, so this lock can never itself pollute the live certs.
        """
        import launcher.__main__ as main_mod
        from launcher.__main__ import VMState, main
        from shared.security.cert_provisioning import (
            provision_per_boot_certs as real_fn,
        )

        # FAIL FAST: never drive a real production mint if the redirect regressed.
        assert main_mod.provision_per_boot_certs is not real_fn, (
            "cert-mint redirect missing — refusing to drive main() into a real "
            "<repo_root>/certs/ mint (#751)"
        )

        repo_certs = Path(main_mod.__file__).resolve().parent.parent / "certs"
        before = _snapshot_certs_dir(repo_certs)

        mock_vm_state.return_value = VMState.RUNNING
        mock_build_result = MagicMock()
        mock_build_result.ok = True
        mock_build_result.pipeline = MagicMock()
        mock_build_result.error = None
        mock_build_pipeline.return_value = mock_build_result
        mock_build_store.return_value = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.check_pa_status = AsyncMock(return_value=True)
        mock_gateway_cls.return_value = mock_gateway
        mock_app_cls.return_value = MagicMock()
        mock_policy_service = MagicMock()
        mock_policy_service.start.return_value = True
        mock_policy_service.running = True
        mock_policy_service_cls.from_runtime_mode.return_value = mock_policy_service
        mock_orchestrator_service = MagicMock()
        mock_orchestrator_service.start.return_value = True
        mock_orchestrator_service.running = True
        mock_orchestrator_service_cls.from_runtime_mode.return_value = (
            mock_orchestrator_service
        )

        assert main() == 0

        # The production boot reached Step 1.5 (the cert mint) but the fixture
        # redirected it to tmp: the REAL certs dir is unchanged — absent stays
        # absent, or present-with-identical (size, mtime) for every file.
        assert _snapshot_certs_dir(repo_certs) == before, (
            f"production main() must not create or modify {repo_certs} — the "
            f"per-boot mint must be redirected to tmp (#751)"
        )
