"""
ISS-8 — Context wiring integration tests.

Covers:
  - Multi-turn wiring: prompt passed to generate_text on turns 2+ contains
    prior user messages and assistant responses.
  - Guard: PGOV-rejected turn does not add an assistant entry; user turn
    is still retained.
  - Guard: generation-error turn does not add an assistant entry; user turn
    is still retained.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.vsock import VsockAddress, VsockConfig
from services.assistant_orchestrator.src.context_manager import ContextManager
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorEntrypointConfig,
    AssistantOrchestratorService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_resolved_config() -> AssistantOrchestratorEntrypointConfig:
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
    )


def _make_service() -> AssistantOrchestratorService:
    """Return a service with all runtime attributes pre-wired for unit tests."""
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = _make_resolved_config()
    service._context_manager = ContextManager()
    return service


def _drive_turn(
    service: AssistantOrchestratorService,
    session_id: str,
    prompt: str,
    request_id: str,
    mock_generate: Any,
    response_text: str,
    pgov_approved: bool = True,
    pgov_sanitized: str | None = None,
    generation_error: str | None = None,
) -> list[bytes]:
    """
    Wire one prompt request through _handle_connection and return the
    raw frames sent by the service.

    Configures mock_generate for this turn before sending.
    """
    framer = MessageFramer()

    mock_generate.return_value = SimpleNamespace(
        text=response_text,
        token_count=max(1, len(response_text) // 4),
        error=generation_error,
    )

    request = framer.encode_prompt_request(
        session_id=session_id,
        prompt=prompt,
        request_id=request_id,
    )
    transport = _FakeTransport(request)
    service._handle_connection(transport)
    return transport.sent


# ---------------------------------------------------------------------------
# Test: multi-turn context wiring
# ---------------------------------------------------------------------------

class TestMultiTurnContextWiring:
    """
    Three-turn sequence with the same session_id.  On turns 2 and 3, the
    prompt string forwarded to generate_text MUST contain:
      - the user message from the previous turn, AND
      - the assistant response from the previous turn.

    This is the automated stand-in for "tell it your name, then ask later."
    """

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_turn_2_prompt_contains_turn_1_exchange(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        service = _make_service()
        service._inference = MagicMock()
        framer = MessageFramer()

        # PGOV always approves throughout this test.
        def _pgov_approved(generated_text: str, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                approved=True,
                sanitized_text=generated_text,
            )

        mock_validate_output.side_effect = _pgov_approved

        # Record every prompt string passed to generate_text.
        captured_prompts: list[str] = []

        def _fake_generate(**kwargs: Any) -> SimpleNamespace:  # type: ignore[misc]
            # generate_text is called positionally (first arg = prompt).
            raise AssertionError("Should not be reached — use side_effect on mock")

        def _capturing_generate(prompt_arg: str, **kwargs: Any) -> SimpleNamespace:
            captured_prompts.append(prompt_arg)
            text = f"response-to-{prompt_arg.split()[-1]}"  # stable canned reply
            return SimpleNamespace(
                text=text,
                token_count=max(1, len(text) // 4),
                error=None,
            )

        service._inference.generate_text.side_effect = _capturing_generate

        session_id = "ctx-test-session"

        # --- Turn 1 ---
        t1_prompt = "My name is Alice"
        t1_req = framer.encode_prompt_request(
            session_id=session_id, prompt=t1_prompt, request_id="r1"
        )
        t1_transport = _FakeTransport(t1_req)
        service._handle_connection(t1_transport)

        # --- Turn 2 ---
        t2_prompt = "What is my name?"
        t2_req = framer.encode_prompt_request(
            session_id=session_id, prompt=t2_prompt, request_id="r2"
        )
        t2_transport = _FakeTransport(t2_req)
        service._handle_connection(t2_transport)

        # --- Turn 3 ---
        t3_prompt = "Repeat what you said."
        t3_req = framer.encode_prompt_request(
            session_id=session_id, prompt=t3_prompt, request_id="r3"
        )
        t3_transport = _FakeTransport(t3_req)
        service._handle_connection(t3_transport)

        assert len(captured_prompts) == 3, (
            f"Expected 3 generate_text calls, got {len(captured_prompts)}"
        )

        # Turn 1 prompt: only the user message (no prior history).
        assert t1_prompt in captured_prompts[0]

        # Turn 2 prompt: must contain turn-1 user message AND turn-1 assistant reply.
        t2_ctx = captured_prompts[1]
        assert t1_prompt in t2_ctx, (
            f"Turn-2 prompt missing turn-1 user message.\nGot:\n{t2_ctx}"
        )
        # The assistant turn is stored as generation.text from turn 1.
        t1_assistant_text = captured_prompts[0].split()[-1]  # last word of turn-1 prompt
        t1_response = f"response-to-{t1_assistant_text}"
        assert t1_response in t2_ctx, (
            f"Turn-2 prompt missing turn-1 assistant response '{t1_response}'.\n"
            f"Got:\n{t2_ctx}"
        )

        # Turn 3 prompt: must additionally contain turn-2 exchange.
        t3_ctx = captured_prompts[2]
        assert t2_prompt in t3_ctx, (
            f"Turn-3 prompt missing turn-2 user message.\nGot:\n{t3_ctx}"
        )


# ---------------------------------------------------------------------------
# Test: guard — PGOV-rejected turn does not add assistant entry
# ---------------------------------------------------------------------------

class TestPGOVRejectGuard:
    """
    When PGOV rejects a generation, the user turn is retained but NO
    assistant turn is added to the session history.
    """

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_pgov_reject_retains_user_turn_no_assistant_turn(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        service = _make_service()
        service._inference = MagicMock()
        session_id = "reject-session"

        # First generate_text: succeeds but PGOV rejects.
        service._inference.generate_text.return_value = SimpleNamespace(
            text="bad output",
            token_count=2,
            error=None,
        )
        mock_validate_output.return_value = SimpleNamespace(
            approved=False,
            sanitized_text="[BLOCKED]",
            token_count_valid=True,
            pii_detected=False,
            delimiter_echo=False,
            tool_call_violation=False,
            leakage_score=0.0,
        )

        framer = MessageFramer()
        request = framer.encode_prompt_request(
            session_id=session_id,
            prompt="say something bad",
            request_id="r-reject",
        )
        transport = _FakeTransport(request)
        service._handle_connection(transport)

        assert service._context_manager is not None
        assert session_id in service._context_manager.active_sessions

        ctx = service._context_manager.build_context(session_id)
        assert ctx is not None
        # User turn must be present.
        assert "user: say something bad" in ctx, (
            f"User turn missing from context after PGOV reject.\nContext:\n{ctx}"
        )
        # No assistant turn must appear.
        assert "assistant:" not in ctx, (
            f"Assistant turn unexpectedly present after PGOV reject.\nContext:\n{ctx}"
        )


# ---------------------------------------------------------------------------
# Test: guard — generation error does not add assistant entry
# ---------------------------------------------------------------------------

class TestGenerationErrorGuard:
    """
    When generate_text returns an error, the user turn is retained but NO
    assistant turn is added to the session history.
    """

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_generation_error_retains_user_turn_no_assistant_turn(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        service = _make_service()
        service._inference = MagicMock()
        session_id = "error-session"

        # generate_text signals an error via the error field.
        service._inference.generate_text.return_value = SimpleNamespace(
            text="",
            token_count=0,
            error="GPU_OOM",
        )
        # validate_output should not be reached; but if it is, approve so it
        # does not confuse the assertion.
        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="",
        )

        framer = MessageFramer()
        request = framer.encode_prompt_request(
            session_id=session_id,
            prompt="trigger an error",
            request_id="r-error",
        )
        transport = _FakeTransport(request)
        service._handle_connection(transport)

        assert service._context_manager is not None
        assert session_id in service._context_manager.active_sessions

        ctx = service._context_manager.build_context(session_id)
        assert ctx is not None
        # User turn must be present.
        assert "user: trigger an error" in ctx, (
            f"User turn missing from context after generation error.\nContext:\n{ctx}"
        )
        # No assistant turn must appear.
        assert "assistant:" not in ctx, (
            f"Assistant turn unexpectedly present after generation error.\nContext:\n{ctx}"
        )


# ---------------------------------------------------------------------------
# FUT-07: Cold-session history seeding + warm-session ignore
# ---------------------------------------------------------------------------


class TestColdSessionHistorySeeding:
    """
    FUT-07 — on a cold session (not yet in active_sessions) the AO seeds
    context from the history payload before adding the current user turn.
    """

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_cold_session_history_appears_in_generate_text_prompt(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        """History turns are prepended; generate_text sees them."""
        service = _make_service()
        service._inference = MagicMock()

        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="ok",
        )
        service._inference.generate_text.return_value = SimpleNamespace(
            text="ok",
            token_count=2,
            error=None,
        )

        framer = MessageFramer()
        history = [
            {"role": "user", "content": "My name is Bob"},
            {"role": "assistant", "content": "Hello Bob!"},
        ]
        request = framer.encode_prompt_request(
            session_id="cold-hist-sess",
            prompt="What is my name?",
            request_id="r-cold",
            history=history,
        )
        transport = _FakeTransport(request)
        service._handle_connection(transport)  # type: ignore[arg-type]

        # The context passed to generate_text must contain the history turns.
        assert service._inference.generate_text.called
        call_args = service._inference.generate_text.call_args
        prompt_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("prompt_arg", "")
        assert "My name is Bob" in prompt_arg, (
            f"History user turn missing from generate_text input.\nGot:\n{prompt_arg}"
        )
        assert "Hello Bob!" in prompt_arg, (
            f"History assistant turn missing from generate_text input.\nGot:\n{prompt_arg}"
        )
        assert "What is my name?" in prompt_arg, (
            f"Current user prompt missing from generate_text input.\nGot:\n{prompt_arg}"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_cold_session_history_stored_in_context_manager(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        """After seeding, context_manager holds history + current user turn."""
        service = _make_service()
        service._inference = MagicMock()

        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="response",
        )
        service._inference.generate_text.return_value = SimpleNamespace(
            text="response",
            token_count=2,
            error=None,
        )

        framer = MessageFramer()
        history = [
            {"role": "user", "content": "Prior user turn"},
            {"role": "assistant", "content": "Prior assistant reply"},
        ]
        request = framer.encode_prompt_request(
            session_id="cold-ctx-sess",
            prompt="Current prompt",
            request_id="r-ctx",
            history=history,
        )
        transport = _FakeTransport(request)
        service._handle_connection(transport)  # type: ignore[arg-type]

        assert service._context_manager is not None
        ctx = service._context_manager.build_context("cold-ctx-sess")
        assert ctx is not None
        assert "Prior user turn" in ctx
        assert "Prior assistant reply" in ctx
        assert "Current prompt" in ctx

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_malformed_history_entries_skipped(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        """Malformed history entries (wrong type, bad role) are skipped; prompt still works."""
        service = _make_service()
        service._inference = MagicMock()

        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="ok",
        )
        service._inference.generate_text.return_value = SimpleNamespace(
            text="ok",
            token_count=2,
            error=None,
        )

        framer = MessageFramer()
        # Inject mix of valid and malformed entries
        history = [
            {"role": "user", "content": "Valid prior turn"},
            "not a dict at all",                       # malformed — wrong type
            {"role": "system", "content": "injected"}, # malformed — invalid role
            {"role": "assistant", "content": 12345},   # malformed — non-str content
            {"role": "assistant", "content": "Valid assistant"},
        ]
        request = framer.encode_prompt_request(
            session_id="malformed-sess",
            prompt="Works anyway",
            request_id="r-mal",
            history=history,  # type: ignore[arg-type]
        )
        transport = _FakeTransport(request)
        # Must not raise
        service._handle_connection(transport)  # type: ignore[arg-type]

        ctx = service._context_manager.build_context("malformed-sess")
        assert ctx is not None
        assert "Valid prior turn" in ctx
        assert "Valid assistant" in ctx
        # Malformed items must not appear
        assert "injected" not in ctx
        assert "Works anyway" in ctx


class TestWarmSessionHistoryIgnore:
    """
    FUT-07 — on a warm session (already in active_sessions) the AO ignores
    the history payload entirely; in-memory context is authoritative.
    """

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_warm_session_history_not_re_added(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        """A second PROMPT_REQUEST to an already-known session must not replay history."""
        service = _make_service()
        service._inference = MagicMock()

        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="response",
        )
        service._inference.generate_text.return_value = SimpleNamespace(
            text="response",
            token_count=2,
            error=None,
        )

        framer = MessageFramer()
        session_id = "warm-sess"

        # Turn 1 — no history (cold session is created normally)
        t1 = framer.encode_prompt_request(
            session_id=session_id,
            prompt="Hello",
            request_id="r-w1",
        )
        service._handle_connection(_FakeTransport(t1))  # type: ignore[arg-type]

        # Turn 2 — attach a history that contains the SAME content as turn 1
        # to verify it is NOT duplicated.
        stale_history = [{"role": "user", "content": "Hello"}]
        t2 = framer.encode_prompt_request(
            session_id=session_id,
            prompt="Second turn",
            request_id="r-w2",
            history=stale_history,
        )
        service._handle_connection(_FakeTransport(t2))  # type: ignore[arg-type]

        ctx = service._context_manager.build_context(session_id)
        assert ctx is not None
        # "Hello" appears exactly once as a user turn (not duplicated)
        user_hello_count = ctx.count("user: Hello")
        assert user_hello_count == 1, (
            f"Expected 'user: Hello' exactly once, found {user_hello_count}.\nContext:\n{ctx}"
        )


# ---------------------------------------------------------------------------
# FUT-07: Restart-survival integration test
# ---------------------------------------------------------------------------


class TestRestartSurvivalIntegration:
    """
    FUT-07 — simulate the full Gateway→AO path across a restart.

    Scenario:
      1. Prior turns are persisted via a real SessionStore.
      2. The Gateway builds the history list the same way send_prompt does.
      3. A PROMPT_REQUEST carrying that history is fed to a FRESH ContextManager
         (simulating an AO restart — all in-memory state gone).
      4. Assert that generate_text sees the prior turns in the prompt.
    """

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_prior_turns_survive_simulated_restart(
        self,
        mock_validate_output: MagicMock,
    ) -> None:
        from services.ui_gateway.src.session_store import SessionStore

        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="I remember Alice",
        )

        # Step 1: Persist prior turns in a real (in-memory) SessionStore.
        store = SessionStore(db_path=":memory:")
        session_id = store.create_session("restart-test")
        store.add_turn(session_id, "user", "My name is Alice", "N/A", [])
        store.add_turn(session_id, "assistant", "Hello Alice!", "approved", [])
        store.add_turn(session_id, "user", "What is the capital of France?", "N/A", [])
        store.add_turn(session_id, "assistant", "Paris.", "approved", [])

        # Step 2: Build the history the same way send_prompt does (BEFORE adding
        # the new user turn, approved assistant + all user turns included).
        prior_turns = store.get_session_turns(session_id)
        history: list[dict[str, str]] = [
            {"role": t.role, "content": t.content}
            for t in prior_turns
            if t.role == "user" or (t.role == "assistant" and t.pgov_status == "approved")
        ]

        # Step 3: Fresh AO service — simulates a restart (no prior in-memory context).
        service = _make_service()
        service._inference = MagicMock()

        captured_prompts: list[str] = []

        def _capturing_generate(prompt_arg: str, **_kw: Any) -> SimpleNamespace:
            captured_prompts.append(prompt_arg)
            return SimpleNamespace(text="I remember Alice", token_count=4, error=None)

        service._inference.generate_text.side_effect = _capturing_generate

        framer = MessageFramer()
        request = framer.encode_prompt_request(
            session_id=session_id,
            prompt="Who am I?",
            request_id="r-restart",
            history=history,
        )
        service._handle_connection(_FakeTransport(request))  # type: ignore[arg-type]

        assert len(captured_prompts) == 1
        ctx_str = captured_prompts[0]

        # The prior turns must be in the reconstructed context.
        assert "My name is Alice" in ctx_str, (
            f"Prior user turn missing after simulated restart.\nContext:\n{ctx_str}"
        )
        assert "Hello Alice!" in ctx_str, (
            f"Prior assistant turn missing after simulated restart.\nContext:\n{ctx_str}"
        )
        assert "Paris." in ctx_str, (
            f"Second prior assistant turn missing.\nContext:\n{ctx_str}"
        )
        # Current prompt present.
        assert "Who am I?" in ctx_str
