"""
#801 — AO idle-session reaper wiring tests.

The serve loop's ``_maybe_reap_idle_sessions`` is destroy_session's production
caller: throttled, thread-confined (serve-loop only), fail-soft, and paired
with the egress-envelope retain_only sweep. These tests drive the service
object directly (the established entrypoint-test pattern) with injected
monotonic timestamps — no sleeps, deterministic.

The lock that matters most is the correctness-safety claim: a REAPED session
is lazily re-created + history-reseeded on its next PROMPT_REQUEST (FUT-07),
so reaping can never lose a conversation.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from shared.ipc.protocol import MessageFramer
from shared.ipc.vsock import VsockAddress, VsockConfig
from services.assistant_orchestrator.src.context_manager import ContextManager
from services.assistant_orchestrator.src.entrypoint import (
    _SESSION_REAP_INTERVAL_S,
    AssistantOrchestratorEntrypointConfig,
    AssistantOrchestratorService,
)


class _FakeTransport:
    """Minimal vsock transport stand-in that records outbound frames."""

    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def _make_resolved_config(
    session_idle_ttl_s: float = 1800.0,
) -> AssistantOrchestratorEntrypointConfig:
    return AssistantOrchestratorEntrypointConfig(
        model_dir=Path("models"),
        manifest_path=None,
        device="GPU",
        priority=1,
        draft_model_dir=None,
        speculative_decoding_enabled=False,
        max_new_tokens=64,
        generation_temperature=0.0,
        generation_top_k=50,
        generation_top_p=0.9,
        generation_repetition_penalty=1.1,
        generation_do_sample=False,
        response_depth_mode="standard",
        dev_mode=True,
        jwt_ca_cert_path=None,
        vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
        pgov_cosine_threshold=0.85,
        deployment_mode="host",  # type: ignore[arg-type]
        session_idle_ttl_s=session_idle_ttl_s,
    )


def _make_service(
    session_idle_ttl_s: float = 1800.0,
) -> AssistantOrchestratorService:
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = _make_resolved_config(session_idle_ttl_s)
    service._context_manager = ContextManager()
    return service


class TestMaybeReapIdleSessions:
    def test_idle_session_is_reaped_and_logged(self) -> None:
        service = _make_service(session_idle_ttl_s=60.0)
        cm = service._context_manager
        assert cm is not None
        cm.create_session("idle-s")
        cm.touch("idle-s", now=1_000.0)
        reaped = service._maybe_reap_idle_sessions(now=1_061.0)
        assert reaped == ["idle-s"]
        assert cm.active_sessions == []

    def test_active_session_survives(self) -> None:
        service = _make_service(session_idle_ttl_s=60.0)
        cm = service._context_manager
        assert cm is not None
        cm.create_session("busy-s")
        cm.touch("busy-s", now=1_050.0)
        assert service._maybe_reap_idle_sessions(now=1_061.0) == []
        assert cm.active_sessions == ["busy-s"]

    def test_throttle_skips_within_interval(self) -> None:
        # The serve loop calls this every iteration; between interval marks it
        # must cost one compare and reap NOTHING.
        service = _make_service(session_idle_ttl_s=60.0)
        cm = service._context_manager
        assert cm is not None
        cm.create_session("s-a")
        cm.touch("s-a", now=0.0)
        assert service._maybe_reap_idle_sessions(now=1_000.0) == ["s-a"]
        # A NEW idle session inside the throttle window is untouched...
        cm.create_session("s-b")
        cm.touch("s-b", now=0.0)
        within = 1_000.0 + _SESSION_REAP_INTERVAL_S - 1.0
        assert service._maybe_reap_idle_sessions(now=within) == []
        assert cm.active_sessions == ["s-b"]
        # ...and reaped once the next interval mark passes.
        after = 1_000.0 + _SESSION_REAP_INTERVAL_S + 1.0
        assert service._maybe_reap_idle_sessions(now=after) == ["s-b"]

    def test_envelope_dropped_with_reaped_session(self) -> None:
        service = _make_service(session_idle_ttl_s=60.0)
        cm = service._context_manager
        assert cm is not None
        cm.create_session("s-env")
        cm.touch("s-env", now=1_000.0)
        service._egress_envelope.begin_turn("s-env", 3)
        service._maybe_reap_idle_sessions(now=1_061.0)
        # The dropped envelope leaves the dead session fail-closed: an egress
        # gate on it DENIES (no envelope armed).
        decision = service._egress_envelope.gate(
            "s-env", "q", consent_fn=lambda _q, _n: True
        )
        assert decision.allowed is False

    def test_non_positive_ttl_disables_reaping(self) -> None:
        service = _make_service(session_idle_ttl_s=0.0)
        cm = service._context_manager
        assert cm is not None
        cm.create_session("s-keep")
        cm.touch("s-keep", now=0.0)
        assert service._maybe_reap_idle_sessions(now=10_000_000.0) == []
        assert cm.active_sessions == ["s-keep"]

    def test_no_context_manager_is_noop(self) -> None:
        # Pre-start() posture: nothing to reap, nothing raises.
        service = AssistantOrchestratorService("dummy.toml")
        service._resolved_config = _make_resolved_config()
        assert service._maybe_reap_idle_sessions(now=1_000_000.0) == []

    def test_reaper_failure_is_fail_soft(self) -> None:
        # A hygiene failure must never take the serve loop down.
        service = _make_service(session_idle_ttl_s=60.0)
        broken = MagicMock()
        broken.reap_idle_sessions.side_effect = RuntimeError("boom")
        service._context_manager = broken  # type: ignore[assignment]
        assert service._maybe_reap_idle_sessions(now=1_000_000.0) == []

    def test_serve_loop_invokes_the_reaper(self) -> None:
        # The lesson-46 lock for THIS feature: the reaper is only real if the
        # LIVE serve loop calls it. This drives the real _serve_forever with a
        # fake listener and asserts the loop reaches the reap hook — the test
        # that fails the day the wiring line is removed.
        service = _make_service(session_idle_ttl_s=60.0)
        calls: list[float | None] = []

        def _recording_reap(now: float | None = None) -> list[str]:
            calls.append(now)
            service._stop_event.set()  # first reap ends the loop
            return []

        service._maybe_reap_idle_sessions = _recording_reap  # type: ignore[method-assign]
        listener = MagicMock()
        listener.running = True
        listener.accept.return_value = None
        service._listener = listener

        service._serve_forever()

        assert calls, "_serve_forever never reached the idle-session reap hook"

    def test_property_defaults_to_la_decided_value_before_start(self) -> None:
        # 1800 s (30 min) is the LA-DECIDED idle TTL (2026-07-11, #801
        # c.1713) — the registry drift lock pins the config field; this pins
        # the pre-start property fallback to the same decision.
        service = AssistantOrchestratorService("dummy.toml")
        assert service.session_idle_ttl_s == 1800.0

    def test_property_reads_resolved_config(self) -> None:
        service = _make_service(session_idle_ttl_s=123.0)
        assert service.session_idle_ttl_s == 123.0
        service._resolved_config = replace(
            service._resolved_config, session_idle_ttl_s=-1.0  # type: ignore[arg-type]
        )
        assert service.session_idle_ttl_s == -1.0  # <= 0 = disabled, honored

    def test_stop_releases_sessions_and_envelopes_immediately(self) -> None:
        # LA decision (#801 c.1713): app close → in-RAM sessions release
        # immediately. stop() must drop the context manager AND the egress
        # envelopes (which live outside it and previously survived a
        # stop()/start() cycle in the same process).
        service = _make_service(session_idle_ttl_s=1800.0)
        cm = service._context_manager
        assert cm is not None
        cm.create_session("s-open")
        service._egress_envelope.begin_turn("s-open", 3)

        service.stop()

        assert service._context_manager is None
        # The envelope went with the session: a post-stop egress gate on the
        # old session fails closed (no envelope armed).
        decision = service._egress_envelope.gate(
            "s-open", "q", consent_fn=lambda _q, _n: True
        )
        assert decision.allowed is False


class TestReapedSessionRecovers:
    """The FUT-07 correctness-safety lock: a reap never loses a conversation."""

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_prompt_after_reap_recreates_session_with_history(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        service = _make_service(session_idle_ttl_s=60.0)
        cm = service._context_manager
        assert cm is not None
        service._inference = MagicMock()

        def _pgov_approved(generated_text: str, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(approved=True, sanitized_text=generated_text)

        mock_validate_output.side_effect = _pgov_approved
        captured_prompts: list[str] = []

        def _capturing_generate(prompt_arg: str, **_kw: Any) -> SimpleNamespace:
            captured_prompts.append(prompt_arg)
            return SimpleNamespace(text="the answer", token_count=3, error=None)

        service._inference.generate_text.side_effect = _capturing_generate

        # A prior conversation existed, went idle, and was reaped.
        cm.create_session("s-recover")
        cm.add_turn("s-recover", "user", "My name is Alice", token_count=4)
        cm.touch("s-recover", now=1_000.0)
        assert service._maybe_reap_idle_sessions(now=1_061.0) == ["s-recover"]
        assert cm.active_sessions == []

        # The next PROMPT_REQUEST carries gateway history (as production does)
        # and must transparently re-create + reseed the session.
        framer = MessageFramer()
        request = framer.encode_prompt_request(
            session_id="s-recover",
            prompt="What is my name?",
            request_id="r-after-reap",
            history=[{"role": "user", "content": "My name is Alice"}],
        )
        transport = _FakeTransport(request)
        assert service._handle_connection(transport) is True
        assert cm.active_sessions == ["s-recover"]
        # The reseeded history reached the model — the conversation survived.
        assert any("My name is Alice" in p for p in captured_prompts)
