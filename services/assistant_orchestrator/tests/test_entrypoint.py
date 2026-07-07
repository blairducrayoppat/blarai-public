"""Tests for Assistant Orchestrator entrypoint startup/shutdown wiring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.vsock import VsockAddress, VsockConfig
from services.assistant_orchestrator.src.context_manager import ContextManager
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorEntrypointConfig,
)
from shared.tests._keygen import AgenticJWTMinter


def _write_minimal_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "models/qwen3-14b/openvino-int4-gpu"
weight_manifest = "models/qwen3-14b/openvino-int4-gpu/manifest.json"
draft_model_dir = "models/qwen3-0.6b/openvino-int4-gpu"
speculative_decoding_enabled = true

[generation]
max_new_tokens = 512
temperature = 0.0
top_k = 50
top_p = 0.9
repetition_penalty = 1.1
do_sample = false
response_depth_mode = "standard"

[security]
dev_mode = true

[ipc]
vsock_cid = 2
vsock_port = 5001
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
""".strip(),
        encoding="utf-8",
    )


class _FakeTransport:
    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


class TestAssistantOrchestratorEntrypoint:
    def test_start_fails_closed_on_runtime_mode_mismatch(
        self,
        tmp_path: Path,
    ) -> None:
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'deployment_mode = "host"',
                'deployment_mode = "guest"',
            ),
            encoding="utf-8",
        )

        service = AssistantOrchestratorService(config_path)
        assert service.start() is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "AO_CFG_RUNTIME_MODE_MISMATCH"

    def test_start_fails_closed_on_invalid_response_depth_mode(
        self,
        tmp_path: Path,
    ) -> None:
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'response_depth_mode = "standard"',
                'response_depth_mode = "ultra"',
            ),
            encoding="utf-8",
        )

        service = AssistantOrchestratorService(config_path)
        assert service.start() is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "AO_CFG_RESPONSE_DEPTH_MODE_INVALID"

    @patch("services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference")
    @patch("services.assistant_orchestrator.src.entrypoint.VsockListener")
    def test_start_calls_model_load(
        self,
        mock_listener_cls,
        mock_inference_cls,
        tmp_path: Path,
    ) -> None:
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener.running = False
        mock_listener_cls.return_value = mock_listener

        service = AssistantOrchestratorService(config_path)
        assert service.start() is True
        assert service.running is True
        mock_inference.load_model.assert_called_once()
        mock_listener.start.assert_called_once()

        service.stop()
        mock_listener.stop.assert_called_once()
        mock_inference.unload.assert_called_once()

    @patch("services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference")
    @patch("services.assistant_orchestrator.src.entrypoint.VsockListener")
    def test_start_fails_closed_on_model_load_failure(
        self,
        _mock_listener_cls,
        mock_inference_cls,
        tmp_path: Path,
    ) -> None:
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = False
        mock_inference_cls.return_value = mock_inference

        service = AssistantOrchestratorService(config_path)
        assert service.start() is False
        assert service.running is False

    def test_handle_connection_handshake_response(self) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()

        request = framer.encode_handshake_request(request_id="hs-1")
        transport = _FakeTransport(request)

        assert service._handle_connection(transport) is True
        assert len(transport.sent) == 1

        msg_type, request_id, payload = framer.decode(transport.sent[0])
        assert msg_type == MessageType.HANDSHAKE_RESPONSE
        assert request_id == "hs-1"
        assert payload.get("status") == "OPERATIONAL"

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_handle_connection_prompt_streams_and_completes(
        self,
        mock_validate_output,
    ) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()

        service._resolved_config = AssistantOrchestratorEntrypointConfig(
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
            deployment_mode="host",
        )
        service._inference = MagicMock()
        service._inference.generate_text.return_value = SimpleNamespace(
            text="safe output",
            token_count=2,
            error=None,
        )
        service._context_manager = ContextManager()
        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="safe output",
        )

        request = framer.encode_prompt_request(
            session_id="s-1",
            prompt="hello",
            request_id="req-1",
        )
        transport = _FakeTransport(request)

        assert service._handle_connection(transport) is True
        assert len(transport.sent) == 3

        msg0, rid0, payload0 = framer.decode(transport.sent[0])
        assert msg0 == MessageType.STREAM_TOKEN
        assert rid0 == "req-1"
        assert payload0["token"] == "safe output"

        msg1, rid1, payload1 = framer.decode(transport.sent[1])
        assert msg1 == MessageType.PGOV_RESULT
        assert rid1 == "req-1"
        assert payload1["approved"] is True

        msg2, rid2, _payload2 = framer.decode(transport.sent[2])
        assert msg2 == MessageType.GENERATION_COMPLETE
        assert rid2 == "req-1"

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_handle_connection_model_time_streaming_callback(
        self,
        mock_validate_output,
    ) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()

        service._resolved_config = AssistantOrchestratorEntrypointConfig(
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
            deployment_mode="host",
        )

        service._inference = MagicMock()
        service._context_manager = ContextManager()

        def _fake_generate_text(*_args, **kwargs):
            cb = kwargs.get("stream_callback")
            assert cb is not None
            assert cb("Hello ") is True
            assert cb("world") is True
            return SimpleNamespace(text="Hello world", token_count=2, error=None)

        service._inference.generate_text.side_effect = _fake_generate_text
        mock_validate_output.return_value = SimpleNamespace(
            approved=True,
            sanitized_text="Hello world",
        )

        request = framer.encode_prompt_request(
            session_id="s-1",
            prompt="hello",
            request_id="req-stream",
        )
        transport = _FakeTransport(request)

        assert service._handle_connection(transport) is True
        assert len(transport.sent) == 5

        msg0, rid0, payload0 = framer.decode(transport.sent[0])
        assert msg0 == MessageType.STREAM_TOKEN
        assert rid0 == "req-stream"
        assert payload0["token"] == "Hello "
        assert payload0["is_final"] is False

        msg1, rid1, payload1 = framer.decode(transport.sent[1])
        assert msg1 == MessageType.STREAM_TOKEN
        assert rid1 == "req-stream"
        assert payload1["token"] == "world"
        assert payload1["is_final"] is False

        msg2, rid2, payload2 = framer.decode(transport.sent[2])
        assert msg2 == MessageType.STREAM_TOKEN
        assert rid2 == "req-stream"
        assert payload2["token"] == ""
        assert payload2["is_final"] is True

        msg3, rid3, payload3 = framer.decode(transport.sent[3])
        assert msg3 == MessageType.PGOV_RESULT
        assert rid3 == "req-stream"
        assert payload3["approved"] is True

        msg4, rid4, _payload4 = framer.decode(transport.sent[4])
        assert msg4 == MessageType.GENERATION_COMPLETE
        assert rid4 == "req-stream"

    def test_handle_connection_malformed_message_fails_closed(self) -> None:
        """Malformed-frame errors reach the client as a sanitized message (no raw
        exception text).  The client still learns the request failed (ERROR frame
        present), but the internal decode detail stays server-side (Tier-1
        error-sanitize hardening, Vikunja #560)."""
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()
        transport = _FakeTransport(b"not-json")

        assert service._handle_connection(transport) is True
        assert len(transport.sent) == 1

        msg_type, _rid, payload = framer.decode(transport.sent[0])
        assert msg_type == MessageType.ERROR
        error_text = str(payload.get("error", ""))
        # Sanitized: generic text + correlation id (no raw exception detail).
        assert "malformed message" in error_text.lower()
        # The raw exception text ("Malformed JSON", "Expecting value", Python
        # traceback details) must NOT appear in the client-facing message.
        assert "Malformed JSON" not in error_text
        assert "Expecting value" not in error_text
        assert "JSONDecodeError" not in error_text

    @patch("services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference")
    @patch("services.assistant_orchestrator.src.entrypoint.VsockListener")
    def test_start_non_dev_succeeds_with_jwt_ca_and_kgm(
        self,
        mock_listener_cls,
        mock_inference_cls,
        tmp_path: Path,
    ) -> None:
        model_dir = tmp_path / "models" / "qwen"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_bin = model_dir / "openvino_model.bin"
        model_bin.write_bytes(b"priority7-model-bin")

        manifest_path = model_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "digests": {
                        "openvino_model.bin": hashlib.sha256(
                            model_bin.read_bytes()
                        ).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )

        cert_dir = tmp_path / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        private_key, public_key = AgenticJWTMinter.generate_key_pair()
        signing_key_path = cert_dir / "ao_test_signing.pem"
        public_key_path = cert_dir / "ca.pem"
        AgenticJWTMinter.save_key_pair(private_key, signing_key_path, public_key_path)

        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "{model_dir.as_posix()}"
weight_manifest = "{manifest_path.as_posix()}"

[generation]
max_new_tokens = 512
temperature = 0.0
top_k = 50
top_p = 0.9
repetition_penalty = 1.1
do_sample = false
response_depth_mode = "standard"

[security]
dev_mode = false
jwt_ca_cert_path = "{public_key_path.as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = 5001
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
""".strip(),
            encoding="utf-8",
        )

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener.running = False
        mock_listener_cls.return_value = mock_listener

        service = AssistantOrchestratorService(config_path)
        assert service.start() is True
        assert service.running is True
        service.stop()

    def test_start_non_dev_fails_closed_when_jwt_ca_missing(
        self,
        tmp_path: Path,
    ) -> None:
        model_dir = tmp_path / "models" / "qwen"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_bin = model_dir / "openvino_model.bin"
        model_bin.write_bytes(b"priority7-model-bin")

        manifest_path = model_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "digests": {
                        "openvino_model.bin": hashlib.sha256(
                            model_bin.read_bytes()
                        ).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )

        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "{model_dir.as_posix()}"
weight_manifest = "{manifest_path.as_posix()}"

[generation]
max_new_tokens = 512
temperature = 0.0
top_k = 50
top_p = 0.9
repetition_penalty = 1.1
do_sample = false
response_depth_mode = "standard"

[security]
dev_mode = false
jwt_ca_cert_path = "{(tmp_path / 'certs' / 'missing_ca.pem').as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = 5001
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
""".strip(),
            encoding="utf-8",
        )

        service = AssistantOrchestratorService(config_path)
        assert service.start() is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "AO_CFG_JWT_CA_PATH_NOT_FOUND"


class TestAssistantOrchestratorHeartbeat:
    """Heartbeat responses keep the vsock liveness channel alive."""

    def test_heartbeat_request_produces_heartbeat_response(self) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()

        request = framer.encode_heartbeat(request_id="hb-1")
        transport = _FakeTransport(request)

        assert service._handle_connection(transport) is True
        assert len(transport.sent) == 1

        msg_type, request_id, payload = framer.decode(transport.sent[0])
        assert msg_type == MessageType.HEARTBEAT
        assert request_id == "hb-1"
        assert payload.get("status") == "alive"

    def test_heartbeat_preserves_request_id(self) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        framer = MessageFramer()

        request = framer.encode_heartbeat(request_id="unique-hb-42")
        transport = _FakeTransport(request)

        assert service._handle_connection(transport) is True
        _msg_type, request_id, _payload = framer.decode(transport.sent[0])
        assert request_id == "unique-hb-42"

    def test_heartbeat_does_not_invoke_inference(self) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        service._inference = MagicMock()
        framer = MessageFramer()

        request = framer.encode_heartbeat(request_id="hb-2")
        transport = _FakeTransport(request)

        assert service._handle_connection(transport) is True
        service._inference.generate_text.assert_not_called()


class TestAssistantOrchestratorStopIsolation:
    """stop() must be idempotent and leave the service in a clean state."""

    def test_stop_before_start_is_safe(self) -> None:
        """Calling stop() on an un-started service must not raise."""
        service = AssistantOrchestratorService("dummy.toml")
        # Should not raise — no listener, no inference, no thread.
        service.stop()
        assert service.running is False

    @patch("services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference")
    @patch("services.assistant_orchestrator.src.entrypoint.VsockListener")
    def test_stop_is_idempotent(
        self,
        mock_listener_cls,
        mock_inference_cls,
        tmp_path: Path,
    ) -> None:
        """Two stop() calls must not error; unload()/listener.stop() are
        safely gated so the second invocation is a no-op."""
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener.running = False
        mock_listener_cls.return_value = mock_listener

        service = AssistantOrchestratorService(config_path)
        assert service.start() is True
        assert service.running is True

        service.stop()
        assert service.running is False
        assert mock_listener.stop.call_count == 1
        assert mock_inference.unload.call_count == 1

        # Second stop — must not raise; subsystems already released.
        service.stop()
        assert service.running is False
        # After first stop, references are cleared, so stop() cannot call them again.
        assert mock_listener.stop.call_count == 1
        assert mock_inference.unload.call_count == 1

    @patch("services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference")
    @patch("services.assistant_orchestrator.src.entrypoint.VsockListener")
    def test_stop_clears_resolved_state(
        self,
        mock_listener_cls,
        mock_inference_cls,
        tmp_path: Path,
    ) -> None:
        """After stop(), the service must release its resolved config and
        subsystem references so a fresh start() starts clean."""
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener.running = False
        mock_listener_cls.return_value = mock_listener

        service = AssistantOrchestratorService(config_path)
        assert service.start() is True
        assert service._resolved_config is not None
        assert service._inference is not None

        service.stop()
        assert service._resolved_config is None
        assert service._inference is None
        assert service._listener is None
        assert service._loop_thread is None
        assert service._jwt_validator is None

    def test_stop_sets_stop_event(self) -> None:
        """stop() must set _stop_event so any live loop exits."""
        service = AssistantOrchestratorService("dummy.toml")
        assert not service._stop_event.is_set()
        service.stop()
        assert service._stop_event.is_set()


class TestAssistantOrchestratorConfigValidation:
    """Fail-Closed rejection of out-of-range config values.

    Covers the numeric-range / enum constraints enforced by
    ``_validate_config_data``. Each test mutates a single value in the
    minimal valid config and asserts the correct ``AO_CFG_*_INVALID``
    failure fingerprint. These are tighter than the happy-path start
    tests and close coverage on the validation routine.
    """

    def _write_and_tweak(
        self,
        tmp_path: Path,
        old: str,
        new: str,
    ) -> Path:
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_minimal_config(config_path)
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(old, new),
            encoding="utf-8",
        )
        return config_path

    def _assert_start_fails_with_code(
        self, config_path: Path, expected_code: str
    ) -> None:
        service = AssistantOrchestratorService(config_path)
        assert service.start() is False
        assert service.running is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == expected_code

    # ── GPU section ────────────────────────────────────────────────────
    def test_device_not_gpu_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, 'device = "GPU"', 'device = "CPU"')
        self._assert_start_fails_with_code(path, "AO_CFG_DEVICE_INVALID")

    def test_priority_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, "priority = 1", "priority = 42")
        self._assert_start_fails_with_code(path, "AO_CFG_PRIORITY_INVALID")

    # ── Generation section ─────────────────────────────────────────────
    def test_max_new_tokens_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path, "max_new_tokens = 512", "max_new_tokens = 100000"
        )
        self._assert_start_fails_with_code(path, "AO_CFG_MAX_NEW_TOKENS_INVALID")

    def test_temperature_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, "temperature = 0.0", "temperature = 5.0")
        self._assert_start_fails_with_code(path, "AO_CFG_TEMPERATURE_INVALID")

    def test_top_k_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, "top_k = 50", "top_k = -1")
        self._assert_start_fails_with_code(path, "AO_CFG_TOP_K_INVALID")

    def test_top_p_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, "top_p = 0.9", "top_p = 1.5")
        self._assert_start_fails_with_code(path, "AO_CFG_TOP_P_INVALID")

    def test_repetition_penalty_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path, "repetition_penalty = 1.1", "repetition_penalty = 0.1"
        )
        self._assert_start_fails_with_code(path, "AO_CFG_REPETITION_PENALTY_INVALID")

    # ── IPC section ────────────────────────────────────────────────────
    def test_vsock_cid_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, "vsock_cid = 2", "vsock_cid = -1")
        self._assert_start_fails_with_code(path, "AO_CFG_VSOCK_CID_INVALID")

    def test_vsock_port_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(tmp_path, "vsock_port = 5001", "vsock_port = 0")
        self._assert_start_fails_with_code(path, "AO_CFG_VSOCK_PORT_INVALID")

    def test_timeout_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path, "timeout_ms = 250", "timeout_ms = 999999"
        )
        self._assert_start_fails_with_code(path, "AO_CFG_TIMEOUT_INVALID")

    def test_max_message_bytes_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path, "max_message_bytes = 65536", "max_message_bytes = 16"
        )
        self._assert_start_fails_with_code(path, "AO_CFG_MAX_MESSAGE_BYTES_INVALID")

    # ── PGOV section ───────────────────────────────────────────────────
    def test_pgov_threshold_out_of_range_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path,
            "cosine_similarity_threshold = 0.85",
            "cosine_similarity_threshold = 1.5",
        )
        self._assert_start_fails_with_code(path, "AO_CFG_PGOV_THRESHOLD_INVALID")

    def test_pgov_pii_mode_invalid_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path,
            "cosine_similarity_threshold = 0.85",
            'cosine_similarity_threshold = 0.85\npii_mode = "garbage"',
        )
        self._assert_start_fails_with_code(path, "AO_CFG_PGOV_PII_MODE_INVALID")

    # ── Response-depth enum ────────────────────────────────────────────
    def test_response_depth_mode_invalid_rejected(self, tmp_path: Path) -> None:
        path = self._write_and_tweak(
            tmp_path,
            'response_depth_mode = "standard"',
            'response_depth_mode = "nonsense"',
        )
        self._assert_start_fails_with_code(
            path, "AO_CFG_RESPONSE_DEPTH_MODE_INVALID"
        )


class TestJwtValidatorNonceAlignment:
    """#638 — the AO builds its JWT validator with a nonce window that OUTLASTS
    the token.

    The AO is the live destination validator in the system (the PA mints; it
    does not validate at runtime). Before #638 it constructed the validator via
    ``from_public_key_file`` with no validity, taking the bare 5 s ``NonceStore``
    default while tokens were valid for 30 s — a 5–30 s replay window. This locks
    the wiring so the validator's nonce TTL is sized to the shared
    ``JWT_VALIDITY_SECONDS`` and can never be shorter than the token life.
    """

    def _resolved_with_ca(
        self, tmp_path: Path
    ) -> "AssistantOrchestratorEntrypointConfig":
        from shared.ipc.vsock import VsockAddress, VsockConfig

        cert_dir = tmp_path / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        private_key, _public_key = AgenticJWTMinter.generate_key_pair()
        signing_key_path = cert_dir / "ao_test_signing.pem"
        public_key_path = cert_dir / "ca.pem"
        AgenticJWTMinter.save_key_pair(private_key, signing_key_path, public_key_path)

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
            dev_mode=False,
            jwt_ca_cert_path=public_key_path,
            vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
            pgov_cosine_threshold=0.85,
            deployment_mode="host",
        )

    def test_built_validator_nonce_ttl_outlasts_token(self, tmp_path: Path) -> None:
        from shared.constants import JWT_VALIDITY_SECONDS
        from shared.crypto.jwt_validator import aligned_nonce_ttl

        resolved = self._resolved_with_ca(tmp_path)
        validator = AssistantOrchestratorService._build_jwt_validator(resolved)

        assert validator is not None
        # nonce window >= token validity — the #638 invariant.
        assert validator.nonce_store.ttl >= float(JWT_VALIDITY_SECONDS)
        # and specifically the aligned value (validity + skew margin).
        assert validator.nonce_store.ttl == aligned_nonce_ttl(
            float(JWT_VALIDITY_SECONDS)
        )
