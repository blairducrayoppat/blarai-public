"""Tests for Policy Agent entrypoint startup/shutdown wiring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization

from services.policy_agent.src.config_loader import (
    RateLimitConfig,
    RuleEngineConfig,
)
from shared.runtime_config import ConfigResolutionError
from services.policy_agent.src.entrypoint import (
    PolicyAgentEntrypointConfig,
    PolicyAgentService,
)
from services.policy_agent.src.jwt_minter import AgenticJWTMinter
from shared.security import tpm_signer


def _raise_tpm_unavailable(_name: str) -> bool:
    raise tpm_signer.TpmUnavailable("no platform TPM in this test")


def _write_minimal_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
[runtime]
deployment_mode = "host"

[inference]
device = "GPU"
model_dir = "models/qwen3-14b/openvino-int4-gpu"
weight_manifest = "models/qwen3-14b/openvino-int4-gpu/manifest.json"
draft_model_dir = "models/qwen3-0.6b/openvino-int4-gpu"
speculative_decoding_enabled = true

[security]
dev_mode = true

[jwt]
issuer = "policy_agent"
validity_seconds = 5

[ipc]
vsock_cid = 2
vsock_port = 5000
timeout_ms = 5000
max_message_bytes = 65536
""".strip(),
        encoding="utf-8",
    )


class TestPolicyAgentEntrypoint:
    def test_measured_boot_hard_lock_after_retry_exhaustion(
        self,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        service = PolicyAgentService(config_path)
        with patch.object(
            service,
            "_load_entrypoint_config",
            side_effect=ConfigResolutionError(
                code="CFG_PATH_MISSING",
                message="Config missing.",
            ),
        ) as mock_loader:
            assert service.start() is False
            assert service.measured_boot_hard_locked is True
            assert service.measured_boot_state is not None
            assert service.measured_boot_state.hard_locked is True
            assert service.measured_boot_state.attempt_count == 3
            assert mock_loader.call_count == 3

            # Subsequent start is blocked deterministically without re-attempting.
            assert service.start() is False
            assert service.last_failure is not None
            assert service.last_failure.get("code") == "PA_BOOT_HARD_LOCKED"
            assert mock_loader.call_count == 3

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_measured_boot_orders_model_before_rules(
        self,
        mock_load_rules,
        mock_inference_cls,
        mock_listener_cls,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        call_order: list[str] = []

        mock_inference = MagicMock()

        def _load_model() -> bool:
            call_order.append("model")
            return True

        mock_inference.load_model.side_effect = _load_model
        mock_inference_cls.return_value = mock_inference

        rule_cfg = RuleEngineConfig(
            acl_matrix={"assistant_orchestrator": ["substrate"]},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(max_requests_per_window=10, window_seconds=60.0),
            version="1.0.0",
        )

        def _load_rules(_config_dir: Path) -> RuleEngineConfig:
            call_order.append("rules")
            return rule_cfg

        mock_load_rules.side_effect = _load_rules

        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener_cls.return_value = mock_listener

        service = PolicyAgentService(config_path)
        assert service.start() is True
        service.stop()

        assert "model" in call_order
        assert "rules" in call_order
        assert call_order.index("model") < call_order.index("rules")

    def test_start_fails_closed_on_runtime_mode_mismatch(
        self,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'deployment_mode = "host"',
                'deployment_mode = "guest"',
            ),
            encoding="utf-8",
        )

        service = PolicyAgentService(config_path)
        assert service.start() is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "PA_CFG_RUNTIME_MODE_MISMATCH"

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_start_calls_config_and_model_load(
        self,
        mock_load_rules,
        mock_inference_cls,
        mock_listener_cls,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        rule_cfg = RuleEngineConfig(
            acl_matrix={"assistant_orchestrator": ["substrate"]},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(max_requests_per_window=10, window_seconds=60.0),
            version="1.0.0",
        )
        mock_load_rules.return_value = rule_cfg

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener_cls.return_value = mock_listener

        service = PolicyAgentService(config_path)
        assert service.start() is True
        assert service.running is True

        mock_load_rules.assert_called_once()
        mock_inference.load_model.assert_called_once()
        mock_listener.start.assert_called_once()

        service.stop()
        mock_inference.unload.assert_called_once()

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config", return_value=None)
    def test_start_fails_closed_on_rule_config_failure(
        self,
        _mock_load_rules,
        mock_inference_cls,
        _mock_listener_cls,
        tmp_path: Path,
    ) -> None:
        """Rule-config load failure surfaces PA_RULE_CONFIG_LOAD_FAILED as the
        fingerprint code. PolicyGPUInference is mocked to load successfully so
        the measured-boot sequence reaches the rule-load phase (otherwise the
        failure is masked by an earlier PA_MODEL_LOAD_FAILED on a missing model
        dir).
        """
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        service = PolicyAgentService(config_path)
        assert service.start() is False
        assert service.running is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "PA_RULE_CONFIG_LOAD_FAILED"

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_start_fails_closed_on_model_load_failure(
        self,
        mock_load_rules,
        mock_inference_cls,
        _mock_listener_cls,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        mock_load_rules.return_value = RuleEngineConfig(
            acl_matrix={},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(),
            version="1.0.0",
        )

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = False
        mock_inference_cls.return_value = mock_inference

        service = PolicyAgentService(config_path)
        assert service.start() is False
        assert service.running is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "PA_MODEL_LOAD_FAILED"

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_start_non_dev_succeeds_with_real_key_and_kgm(
        self,
        mock_load_rules,
        mock_inference_cls,
        mock_listener_cls,
        tmp_path: Path,
        monkeypatch,
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

        # Production signs via the non-exportable TPM key (stubbed present here);
        # the validator still loads a real public key from ca_cert_path.
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        _private_key, public_key = AgenticJWTMinter.generate_key_pair()
        public_key_path = cert_dir / "pa_public.pem"
        public_key_path.write_bytes(
            public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: True)

        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            f"""
[runtime]
deployment_mode = "host"

[inference]
device = "GPU"
model_dir = "{model_dir.as_posix()}"
weight_manifest = "{manifest_path.as_posix()}"

[security]
dev_mode = false

[jwt]
issuer = "policy_agent"
validity_seconds = 30
tpm_key_name = "BlarAI-PA-JWT-Test"
ca_cert_path = "{public_key_path.as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = 5000
timeout_ms = 5000
max_message_bytes = 65536
""".strip(),
            encoding="utf-8",
        )

        mock_load_rules.return_value = RuleEngineConfig(
            acl_matrix={},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(),
            version="1.0.0",
        )
        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference
        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener_cls.return_value = mock_listener

        service = PolicyAgentService(config_path)
        assert service.start() is True
        assert service.running is True
        service.stop()

    @pytest.mark.parametrize(
        "key_exists_impl, expected_code",
        [
            (lambda name: False, "PA_CFG_JWT_TPM_KEY_NOT_PROVISIONED"),
            (_raise_tpm_unavailable, "PA_CFG_JWT_TPM_UNAVAILABLE"),
        ],
    )
    def test_start_non_dev_fails_closed_when_tpm_key_unusable(
        self,
        tmp_path: Path,
        monkeypatch,
        key_exists_impl,
        expected_code,
    ) -> None:
        """Production preflight is fail-closed until the provisioning ceremony.

        With dev_mode=false and the TPM signing key either unprovisioned
        (key_exists -> False) or the TPM itself unavailable, startup MUST refuse
        rather than fall back to a software key. This is the security posture of
        the whole rotation increment (ADR-021).
        """
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
        _private_key, public_key = AgenticJWTMinter.generate_key_pair()
        public_key_path = cert_dir / "pa_public.pem"
        public_key_path.write_bytes(
            public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "key_exists", key_exists_impl)

        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            f"""
[runtime]
deployment_mode = "host"

[inference]
device = "GPU"
model_dir = "{model_dir.as_posix()}"
weight_manifest = "{manifest_path.as_posix()}"

[security]
dev_mode = false

[jwt]
issuer = "policy_agent"
validity_seconds = 30
tpm_key_name = "BlarAI-PA-JWT-Test"
ca_cert_path = "{public_key_path.as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = 5000
timeout_ms = 5000
max_message_bytes = 65536
""".strip(),
            encoding="utf-8",
        )

        service = PolicyAgentService(config_path)
        assert service.start() is False
        assert service.last_failure is not None
        assert service.last_failure.get("code") == expected_code

    def test_stop_when_not_running_does_not_raise(self, tmp_path: Path) -> None:
        """stop() on a never-started service must be a safe no-op.

        Documents the shutdown contract: stop() handles the
        not-yet-started case without raising. A regression that required
        start() before stop() would fail this test.
        """
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        service = PolicyAgentService(config_path)
        # Never call start(); go straight to stop().
        service.stop()
        assert service.running is False


class TestAuditLogWiredIntoProductionAdjudicator:
    """Lock the audit sink into the production factory (Sprint 13 / Domain 7).

    These tests are teeth against the "built but wired into nothing" anti-pattern:
    the sink exists and is unit-tested, but if _build_adjudicator forgets to pass
    audit_log=, the LIVE PA persists zero decisions.  They assert the production
    factory returns an adjudicator with a non-None sink, and that a decision
    driven through that adjudicator actually lands a verifiable record.
    """

    def _resolved_config(self, service: PolicyAgentService) -> PolicyAgentEntrypointConfig:
        """Resolve the real entrypoint config (exercises default audit-path logic)."""
        return service._load_entrypoint_config()

    def _rule_cfg(self) -> RuleEngineConfig:
        return RuleEngineConfig(
            acl_matrix={"assistant_orchestrator": ["substrate"]},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(max_requests_per_window=10, window_seconds=60.0),
            version="1.0.0",
        )

    def test_production_factory_has_audit_log_true(self, tmp_path: Path) -> None:
        """_build_adjudicator returns an adjudicator with a live (non-None) sink."""
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        service = PolicyAgentService(config_path)
        resolved = self._resolved_config(service)

        # Default audit path must resolve under the (temp) service data dir,
        # NOT a real shared location.
        assert resolved.audit_log_path is not None
        assert "audit" in str(resolved.audit_log_path)
        assert str(tmp_path) in str(resolved.audit_log_path)

        inference = MagicMock()
        adjudicator = PolicyAgentService._build_adjudicator(
            inference, self._rule_cfg(), resolved
        )

        # THE LOCK: the live adjudicator has a sink wired in.
        assert adjudicator.has_audit_log is True

    def test_production_adjudication_round_trip_lands_record(
        self, tmp_path: Path
    ) -> None:
        """Drive a real adjudication through the production-built adjudicator and
        confirm a record landed on disk + the chain verifies."""
        from services.policy_agent.src.car import build_car
        from services.policy_agent.src.gpu_inference import (
            GPUClassificationResult,
            PolicyGPUInference,
        )
        from shared.schemas.car import ActionVerb, Sensitivity
        from shared.security.audit_log import AuditLog, HmacSha256Signer

        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        service = PolicyAgentService(config_path)
        resolved = self._resolved_config(service)

        # Real GPU stub forced to ALLOW so we exercise the full-GPU return path
        # (the most complex of the three persisted return points).
        npu = PolicyGPUInference("dummy_dir")
        npu.classify_car = MagicMock(  # type: ignore[assignment]
            return_value=GPUClassificationResult(
                label="ALLOW", confidence=0.92, latency_ms=1.0,
            )
        )
        npu._loaded = True  # type: ignore[attr-defined]

        adjudicator = PolicyAgentService._build_adjudicator(
            npu, self._rule_cfg(), resolved
        )
        assert adjudicator.has_audit_log is True

        car = build_car(
            source_agent="assistant_orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.INTERNAL,
            session_id="sess-prod-roundtrip",
        )
        ctx = adjudicator.adjudicate_car(car)

        # A record must exist on disk at the resolved path.
        assert resolved.audit_log_path is not None
        assert resolved.audit_log_path.exists()
        lines = resolved.audit_log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["adjudication_id"] == ctx.adjudication_id
        assert rec["decision"] == ctx.decision.value

        # Re-open the on-disk log with the SAME stub-key derivation and verify
        # the chain end-to-end (the entrypoint derives the key from the path).
        key_material = hashlib.sha256(
            b"BlarAI-audit-hmac-stub-v1::"
            + str(resolved.audit_log_path).encode("utf-8")
        ).digest()
        reopened = AuditLog.from_path(
            resolved.audit_log_path,
            HmacSha256Signer(key=key_material, key_id=resolved.audit_hmac_key_id),
        )
        assert reopened.record_count == 1
        reopened.verify()  # must not raise — chain + signature intact

    def test_deny_also_persists_via_production_factory(self, tmp_path: Path) -> None:
        """A rule-engine DENY (short-circuit path) also lands a record through the
        production-built adjudicator."""
        from services.policy_agent.src.car import build_car
        from services.policy_agent.src.gpu_inference import PolicyGPUInference
        from shared.schemas.car import ActionVerb, Sensitivity

        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        service = PolicyAgentService(config_path)
        resolved = self._resolved_config(service)

        npu = PolicyGPUInference("dummy_dir")  # unloaded is fine; rule DENY short-circuits
        adjudicator = PolicyAgentService._build_adjudicator(
            npu, self._rule_cfg(), resolved
        )

        # UNCLASSIFIED sensitivity → rule-engine DENY short-circuit.
        car = build_car(
            source_agent="assistant_orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.UNCLASSIFIED,
            session_id="sess-prod-deny",
        )
        ctx = adjudicator.adjudicate_car(car)
        assert ctx.decision.value == "DENY"

        assert resolved.audit_log_path is not None
        assert resolved.audit_log_path.exists()
        lines = resolved.audit_log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["decision"] == "DENY"


class TestValidateRuntimeConfig:
    """Direct isolation tests for PolicyAgentService.validate_runtime_config()."""

    def test_validate_runtime_config_returns_true_for_valid_dev_config(
        self, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        _write_minimal_config(config_path)

        ok, fingerprint = PolicyAgentService.validate_runtime_config(
            deployment_mode="host",
            dev_mode_override=True,
            config_path=str(config_path),
        )

        assert ok is True
        assert fingerprint is None

    def test_validate_runtime_config_returns_false_for_missing_config(
        self, tmp_path: Path
    ) -> None:
        missing_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
        # Parent exists so resolve_service_config_path reaches its existence check
        # rather than failing earlier for an unreachable directory.
        missing_path.parent.mkdir(parents=True, exist_ok=True)

        ok, fingerprint = PolicyAgentService.validate_runtime_config(
            deployment_mode="host",
            dev_mode_override=True,
            config_path=str(missing_path),
        )

        assert ok is False
        assert fingerprint is not None
        code = fingerprint.get("code")
        assert isinstance(code, str)
        assert code.startswith("PA_")


class TestShippedConfigTokenLifetime:
    """#638 — the SHIPPED PA configs set the 5 s capability-token TTL.

    This is the regression lock for the one containment gap that failed OPEN:
    both PA service configs previously set ``validity_seconds = 30`` while the
    spec (Use Cases_FINAL.md §3) is 5 s. Asserting the real on-disk config —
    not a fixture — means any future drift back to 30 s breaks the gate.
    """

    _CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

    @pytest.mark.parametrize("config_name", ["default.toml", "guest_runtime.toml"])
    def test_shipped_config_validity_is_5s(self, config_name: str) -> None:
        import tomllib

        config_path = self._CONFIG_DIR / config_name
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        assert data["jwt"]["validity_seconds"] == 5, (
            f"{config_name} jwt.validity_seconds must be 5 (Use Cases_FINAL.md "
            f"§3); a 30 s value is the #638 fail-open."
        )
