"""Off-chip stub-signer cascade harness — Sprint 15 EA-3.

Proves the full dev_mode=false PA boot cascade is structurally green WITHOUT
a physical TPM, by combining:
  - A stub-digest manifest (dummy file + computed digest, keyed by filename)
  - Stub signers (HmacSha256Signer for audit, ephemeral ECDSA for JWT)
  - A temp BLARAI_DEK_KEYSTORE so substrate never touches the real keystore
  - tpm_signer.key_exists patched to True (key assumed present; no chip call)
  - PolicyGPUInference / PolicyAgentListener / load_rule_engine_config patched
    (real models and vsock not available off-chip)

ISOLATION CONTRACT (Sprint 14 lesson / reject-the-merge condition):
  This harness MUST NOT touch the real sessions.db / substrate.db / real
  keystore.  The root conftest.py (repo-root, executed at process startup)
  redirects LOCALAPPDATA, HOME, and XDG_DATA_HOME to a throwaway tempdir and
  pops BLARAI_DEK_KEYSTORE.  This file must never re-point BLARAI_DEK_KEYSTORE
  at a real path "to exercise the cascade."  Keep it on stub signers + temp
  keystore paths derived from tmp_path only.

SCOPE BOUNDARY:
  - This harness de-risks cascade STRUCTURE (manifest format, digest-keyed-by-
    filename, config-validation + _validate_security_material + adjudicator
    build), NOT the real Qwen3-14B digest match.
  - require_signed_manifest stays False (not FUT-04, not full Vikunja #106).
  - The real Qwen3-14B digest manifest is EA-4 ceremony-prep.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization

from services.policy_agent.src.config_loader import (
    RateLimitConfig,
    RuleEngineConfig,
)
from services.policy_agent.src.entrypoint import PolicyAgentService
from services.policy_agent.src.jwt_minter import AgenticJWTMinter
from shared.security import tpm_signer
from shared.security.audit_log import HmacSha256Signer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_manifest(
    model_dir: Path,
    model_bin: Path,
) -> Path:
    """Write a stub-digest manifest keyed by the dummy binary's filename.

    The digest is the real SHA-256 of the dummy binary so the validation-
    flow test (fixture that checks digest format) works correctly.  The
    binary itself is a dummy (not real Qwen3-14B weights) — this de-risks
    the cascade STRUCTURE only, per EA-3 scope.
    """
    digest = hashlib.sha256(model_bin.read_bytes()).hexdigest()
    manifest = {
        "version": "1.0.0",
        "_stub_notice": (
            "STUB-DIGEST PLACEHOLDER (Sprint 15 EA-3). "
            "This digest is for the dummy model binary only — NOT real Qwen3-14B weights. "
            "Real digest manifest is EA-4 ceremony-prep."
        ),
        "digests": {
            model_bin.name: digest,
        },
    }
    manifest_path = model_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _make_production_config(
    config_path: Path,
    *,
    model_dir: Path,
    manifest_path: Path,
    ca_cert_path: Path,
    audit_log_dir: Path,
) -> None:
    """Write a production-posture (dev_mode=false) config to config_path."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    audit_log_path = audit_log_dir / "adjudication_audit.jsonl"
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
require_signed_manifest = false
audit_log_path = "{audit_log_path.as_posix()}"

[jwt]
issuer = "policy_agent"
validity_seconds = 30
tpm_key_name = "BlarAI-PA-JWT-EA3-Stub"
ca_cert_path = "{ca_cert_path.as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = 5000
timeout_ms = 5000
max_message_bytes = 65536
""".strip(),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Shared fixture: full stub environment
# ---------------------------------------------------------------------------


@pytest.fixture()
def stub_env(tmp_path: Path) -> Generator[dict[str, object], None, None]:
    """Set up the complete off-chip stub environment for dev_mode=false.

    Provides:
      - model_dir: temp dir containing openvino_model.bin (dummy binary)
      - manifest_path: stub-digest manifest (keyed by 'openvino_model.bin')
      - ca_cert_path: ephemeral ECDSA P-256 public key PEM (for JWT validation)
      - config_path: production-posture config pointing at the above
      - audit_log_dir: temp dir for the audit log output
      - stub_keystore_path: path inside tmp_path (never a real keystore)

    ISOLATION NOTE: tmp_path is pytest's per-test tmpdir, completely inside
    the throwaway LOCALAPPDATA set by the root conftest.  BLARAI_DEK_KEYSTORE
    is NOT set to a real path here — the substrate engine will see the missing
    env var and raise StoreProvisioningError (expected: substrate non-load-
    bearing, AO still starts).  The PA harness does not exercise substrate at
    all; this note is for reference.
    """
    # ── Dummy model binary ──────────────────────────────────────────────────
    model_dir = tmp_path / "models" / "qwen3-14b-stub"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_bin = model_dir / "openvino_model.bin"
    # Dummy content — NOT real Qwen3-14B weights (cascade structure test only)
    model_bin.write_bytes(b"EA3-STUB-DIGEST-PLACEHOLDER-NOT-REAL-QWEN3-14B-WEIGHTS")

    # ── Stub-digest manifest (keyed by filename, valid 64-hex digest) ────────
    manifest_path = _make_stub_manifest(model_dir, model_bin)

    # ── Ephemeral ECDSA P-256 key pair (stub JWT cert/key) ──────────────────
    # Generates a real ephemeral key so AgenticJWTValidator.from_public_key_file
    # loads successfully — the private key is ephemeral, never stored on disk
    # in a durable location, never the TPM.
    _priv_key, pub_key = AgenticJWTMinter.generate_key_pair()
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_cert_path = cert_dir / "pa_public.pem"
    ca_cert_path.write_bytes(
        pub_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    # ── Audit log dir (inside tmp_path — root conftest ensures this is safe) ─
    audit_log_dir = tmp_path / "audit"
    audit_log_dir.mkdir(parents=True, exist_ok=True)

    # ── Production config ────────────────────────────────────────────────────
    config_path = tmp_path / "services" / "policy_agent" / "config" / "default.toml"
    _make_production_config(
        config_path,
        model_dir=model_dir,
        manifest_path=manifest_path,
        ca_cert_path=ca_cert_path,
        audit_log_dir=audit_log_dir,
    )

    # ── Stub keystore path (safe: inside tmp_path only) ──────────────────────
    stub_keystore_path = tmp_path / "stub_keystore.json"

    yield {
        "tmp_path": tmp_path,
        "model_dir": model_dir,
        "model_bin": model_bin,
        "manifest_path": manifest_path,
        "ca_cert_path": ca_cert_path,
        "config_path": config_path,
        "audit_log_dir": audit_log_dir,
        "stub_keystore_path": stub_keystore_path,
    }


# ---------------------------------------------------------------------------
# Cascade harness tests
# ---------------------------------------------------------------------------


class TestCascadeStubHarness:
    """Off-chip stub harness: proves the dev_mode=false cascade is structurally
    green before the LA's on-chip ceremony session (EA-4).

    What is tested (cascade STRUCTURE):
      - config-validation passes at dev_mode=false (weight_manifest, tpm_key_name,
        ca_cert_path all present)
      - _validate_security_material passes (manifest exists, digest is valid 64-hex
        keyed by model filename, tpm_key_name present, ca_cert_path exists + loads
        as EC public key)
      - adjudicator builds (HybridAdjudicator.from_config succeeds with stub audit
        log and stub inference)
      - boot returns True (full measured-boot cascade green)

    What is NOT tested (out of scope):
      - Real Qwen3-14B weight digest match (EA-4 ceremony)
      - Real TPM key operations (patched to key_present=True)
      - Real vsock / GPU inference (patched)
      - Full FUT-04 (require_signed_manifest=false)
    """

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_config_validation_passes_at_dev_mode_false(
        self,
        mock_load_rules: MagicMock,
        mock_inference_cls: MagicMock,
        mock_listener_cls: MagicMock,
        stub_env: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """config-validation: weight_manifest + tpm_key_name + ca_cert_path all
        present; no ConfigResolutionError is raised."""
        config_path = stub_env["config_path"]
        assert isinstance(config_path, Path)

        monkeypatch.setattr(tpm_signer, "key_exists", lambda _name: True)

        service = PolicyAgentService(config_path)
        # validate_runtime_config exercises _validate_config_data + _validate_security_material
        ok, fingerprint = PolicyAgentService.validate_runtime_config(
            deployment_mode=None,
            config_path=config_path,
        )
        assert ok is True, (
            f"config-validation failed at dev_mode=false: {fingerprint}"
        )
        assert fingerprint is None

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_validate_security_material_passes_at_dev_mode_false(
        self,
        mock_load_rules: MagicMock,
        mock_inference_cls: MagicMock,
        mock_listener_cls: MagicMock,
        stub_env: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_validate_security_material: manifest exists, digest is 64-hex keyed
        by model filename, tpm_key_name present, ca_cert_path loads as EC PK."""
        config_path = stub_env["config_path"]
        assert isinstance(config_path, Path)

        monkeypatch.setattr(tpm_signer, "key_exists", lambda _name: True)

        service = PolicyAgentService(config_path)
        resolved = service._load_entrypoint_config()

        assert resolved.dev_mode is False
        assert resolved.manifest_path is not None
        assert resolved.manifest_path.exists()
        assert resolved.jwt_tpm_key_name is not None
        assert resolved.jwt_ca_cert_path is not None
        assert resolved.jwt_ca_cert_path.exists()

        # _validate_security_material must not raise
        service._validate_security_material(
            model_bin_path=resolved.model_bin_path,
            manifest_path=resolved.manifest_path,
            jwt_tpm_key_name=resolved.jwt_tpm_key_name,
            jwt_ca_cert_path=resolved.jwt_ca_cert_path,
            dev_mode=resolved.dev_mode,
            require_signed_manifest=resolved.require_signed_manifest,
        )

    @patch("services.policy_agent.src.entrypoint.PolicyAgentListener")
    @patch("services.policy_agent.src.entrypoint.PolicyGPUInference")
    @patch("services.policy_agent.src.entrypoint.load_rule_engine_config")
    def test_full_boot_cascade_green_at_dev_mode_false(
        self,
        mock_load_rules: MagicMock,
        mock_inference_cls: MagicMock,
        mock_listener_cls: MagicMock,
        stub_env: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full dev_mode=false boot cascade: config-validation + security-material
        + adjudicator build all pass; service.start() returns True.

        This is the primary cascade harness result the merge gate checks.
        """
        config_path = stub_env["config_path"]
        assert isinstance(config_path, Path)

        # Stub TPM key-presence checks (key assumed present; no chip call).
        monkeypatch.setattr(tpm_signer, "key_exists", lambda _name: True)

        # Stub inference (no real GPU/model required off-chip).
        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference

        # Stub rule config.
        mock_load_rules.return_value = RuleEngineConfig(
            acl_matrix={"assistant_orchestrator": ["substrate"]},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(max_requests_per_window=10, window_seconds=60.0),
            version="1.0.0",
        )

        # Stub listener (no real vsock off-chip).
        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener_cls.return_value = mock_listener

        service = PolicyAgentService(config_path)
        result = service.start()
        assert result is True, (
            f"Full dev_mode=false cascade FAILED. last_failure={service.last_failure}"
        )
        assert service.running is True
        assert service.last_failure is None

        service.stop()

    def test_missing_manifest_fails_closed(
        self,
        stub_env: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: if the manifest file is missing, boot must fail-closed
        with PA_CFG_KGM_PATH_NOT_FOUND — never silently boot at dev_mode=false."""
        config_path = stub_env["config_path"]
        manifest_path = stub_env["manifest_path"]
        assert isinstance(config_path, Path)
        assert isinstance(manifest_path, Path)

        monkeypatch.setattr(tpm_signer, "key_exists", lambda _name: True)

        # Remove the manifest to simulate a missing KGM.
        manifest_path.unlink()
        assert not manifest_path.exists()

        service = PolicyAgentService(config_path)
        ok, fingerprint = PolicyAgentService.validate_runtime_config(
            deployment_mode=None,
            config_path=config_path,
        )
        assert ok is False
        assert fingerprint is not None
        assert "PA_CFG_KGM_PATH_NOT_FOUND" in fingerprint.get("code", ""), (
            f"Expected PA_CFG_KGM_PATH_NOT_FOUND, got: {fingerprint}"
        )

    def test_missing_tpm_key_fails_closed(
        self,
        stub_env: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: if the TPM JWT key is not provisioned, boot must fail-closed
        with PA_CFG_JWT_TPM_KEY_NOT_PROVISIONED — never silently boot at dev_mode=false."""
        config_path = stub_env["config_path"]
        assert isinstance(config_path, Path)

        # Stub key_exists to return False (key not provisioned).
        monkeypatch.setattr(tpm_signer, "key_exists", lambda _name: False)

        ok, fingerprint = PolicyAgentService.validate_runtime_config(
            deployment_mode=None,
            config_path=config_path,
        )
        assert ok is False
        assert fingerprint is not None
        assert "PA_CFG_JWT_TPM_KEY_NOT_PROVISIONED" in fingerprint.get("code", ""), (
            f"Expected PA_CFG_JWT_TPM_KEY_NOT_PROVISIONED, got: {fingerprint}"
        )

    def test_stub_manifest_is_not_full_fut04(
        self,
        stub_env: dict[str, object],
    ) -> None:
        """Confirm the staged stub manifest is NOT full FUT-04: require_signed_manifest
        is False and no .sig file exists alongside the manifest."""
        manifest_path = stub_env["manifest_path"]
        assert isinstance(manifest_path, Path)
        sig_path = Path(str(manifest_path) + ".sig")

        # The stub manifest must not have a .sig (no TPM signing ceremony run yet).
        assert not sig_path.exists(), (
            f"Unexpected .sig file found at {sig_path}. "
            "EA-3 stages a stub-digest manifest only; full FUT-04 signing is EA-4."
        )

        # The manifest must contain a valid 64-hex digest keyed by openvino_model.bin.
        import re
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        digests = data.get("digests", {})
        assert "openvino_model.bin" in digests
        digest = digests["openvino_model.bin"]
        assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None, (
            f"Stub manifest digest is not valid 64-hex: {digest!r}"
        )

    def test_isolation_guard_no_real_keystore_touched(
        self,
        stub_env: dict[str, object],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Isolation guard: BLARAI_DEK_KEYSTORE must NOT point at the real production
        keystore during this test.  The root conftest.py pops it; verify it remains
        absent or points only inside tmp_path."""
        tmp_path = stub_env["tmp_path"]
        assert isinstance(tmp_path, Path)

        keystore_val = os.environ.get("BLARAI_DEK_KEYSTORE", "")

        if keystore_val:
            # If set, it must be inside the test's throwaway tmp area.
            keystore_path = Path(keystore_val)
            # Resolve both to compare; if keystore is outside tmp_path, fail.
            try:
                keystore_path.relative_to(tmp_path)
            except ValueError:
                # Not a subpath of tmp_path — check if it's inside the process-
                # wide blarai-pytest-userdata- tempdir (set by root conftest).
                userdata_dir = os.environ.get("LOCALAPPDATA", "")
                assert userdata_dir and "blarai-pytest-userdata-" in userdata_dir, (
                    f"ISOLATION BREACH: BLARAI_DEK_KEYSTORE={keystore_val!r} points "
                    f"outside the test isolation boundary. "
                    f"LOCALAPPDATA={userdata_dir!r}. "
                    "The root conftest.py must pop BLARAI_DEK_KEYSTORE before this "
                    "test runs. Sprint 14 lesson: un-isolated boot harness damaged "
                    "the real sessions.db."
                )
        # Preferred state: not set at all (root conftest pops it).
        # Either state (absent or pointing inside throwaway dir) is acceptable.
