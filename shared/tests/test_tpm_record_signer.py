"""Tests for TpmRecordSigner and the production _build_audit_log wiring.

Sprint 14, Tier-2 security hardening (Vikunja #605 / Domain 7).

Coverage areas:
  K. TpmRecordSigner — signer_id carries key name and algorithm label.
  L. TpmRecordSigner — fail-closed: TPM unavailable raises TpmRecordSignerError.
  M. TpmRecordSigner — fail-closed: TPM sign error raises TpmRecordSignerError.
  N. TpmRecordSigner — software-stub round-trip: sign+verify accept a known-good sig.
  O. SWAGR MINOR-3 CONTRAST TEST — recomputable stub key is forgeable (verify accepts
     a re-derived signature); TpmRecordSigner key is NOT recomputable from filesystem
     state, demonstrating the upgrade's non-forgeability value.
  P. Production-wiring regression — _build_audit_log returns an AuditLog with
     TpmRecordSigner when TPM is available (not-dev); raises AuditProvisioningError
     when key unprovisioned or TPM unavailable (ADR-025 §2.8(a) refuse-to-start);
     HmacSha256Signer in dev mode (unchanged).
  Q. Production-wiring regression — _build_adjudicator wires the signer so
     has_audit_log is True in both production and dev paths.
  R. TpmRecordSigner hardware round-trip (slow, requires real chip).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shared.security import tpm_signer
from shared.security.audit_log import (
    AUDIT_TPM_KEY_NAME,
    GENESIS_HASH,
    AuditChainError,
    AuditLog,
    AuditProvisioningError,
    HmacSha256Signer,
    RecordSigner,
    TpmRecordSigner,
    TpmRecordSignerError,
    _canonical_bytes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_TS = "2026-06-05T12:00:00+00:00"

_BASE_RECORD_KWARGS: dict[str, Any] = dict(
    adjudication_id="tpm-test-uuid-001",
    decision="ALLOW",
    car_hash="a" * 64,
    source_agent="assistant_orchestrator",
    destination_service="substrate",
    verb="READ",
    resource="substrate.vector_store",
    sensitivity="INTERNAL",
    rule_engine_passed=True,
    confidence=0.90,
    timestamp_utc=_FIXED_TS,
)


def _append_record(log: AuditLog, *, override: dict[str, Any] | None = None) -> Any:
    kwargs = {**_BASE_RECORD_KWARGS, **(override or {})}
    return log.append(**kwargs)


def _make_stub_sign(key: bytes):
    """Build a sign callable that behaves like the real TPM sign but uses HMAC."""
    import hmac as _hmac

    def _sign(key_name: str, data: bytes) -> bytes:
        return _hmac.new(key, data, hashlib.sha256).digest()

    return _sign


def _make_stub_verify(key: bytes):
    """Build a verify callable that accepts the HMAC signature for ``key``."""
    import hmac as _hmac

    def _verify(key_name: str, data: bytes, signature: bytes) -> bool:
        expected = _hmac.new(key, data, hashlib.sha256).digest()
        return _hmac.compare_digest(expected, signature)

    return _verify


# ---------------------------------------------------------------------------
# Group K: signer_id
# ---------------------------------------------------------------------------


class TestTpmRecordSignerIdentity:
    def test_signer_id_contains_algorithm_and_key_name(self) -> None:
        signer = TpmRecordSigner(key_name="test-audit-key")
        sid = signer.signer_id()
        assert "ECDSA-P256-TPM" in sid
        assert "test-audit-key" in sid

    def test_default_key_name_is_audit_constant(self) -> None:
        signer = TpmRecordSigner()
        assert AUDIT_TPM_KEY_NAME in signer.signer_id()

    def test_signer_is_record_signer_subclass(self) -> None:
        assert issubclass(TpmRecordSigner, RecordSigner)


# ---------------------------------------------------------------------------
# Group L: fail-closed — TPM unavailable
# ---------------------------------------------------------------------------


class TestTpmRecordSignerFailClosedUnavailable:
    def test_sign_raises_on_tpm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_unavailable(name: str) -> bool:
            raise tpm_signer.TpmUnavailable("no TPM in test")

        monkeypatch.setattr(tpm_signer, "ensure_key", _raise_unavailable)
        signer = TpmRecordSigner(key_name="audit-test")
        with pytest.raises(TpmRecordSignerError, match="TPM audit signing failed"):
            signer.sign(b"canonical-bytes")

    def test_sign_raises_on_tpm_signing_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _sign_fail(name: str, data: bytes) -> bytes:
            raise tpm_signer.TpmSigningError("CNG error 0x80090006")

        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: None)
        monkeypatch.setattr(tpm_signer, "sign", _sign_fail)
        signer = TpmRecordSigner(key_name="audit-test")
        with pytest.raises(TpmRecordSignerError, match="TPM audit signing failed"):
            signer.sign(b"canonical-bytes")

    def test_verify_raises_on_tpm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _verify_unavailable(name: str, data: bytes, sig: bytes) -> bool:
            raise tpm_signer.TpmUnavailable("no TPM")

        monkeypatch.setattr(tpm_signer, "verify", _verify_unavailable)
        signer = TpmRecordSigner(key_name="audit-test")
        with pytest.raises(TpmRecordSignerError, match="TPM audit verification failed"):
            signer.verify(b"canonical-bytes", b"\x00" * 64)

    def test_tpm_record_signer_constructible_without_tpm(self) -> None:
        """Construction must not call the TPM (object is safe to create everywhere)."""
        # If construction called ensure_key/sign, this would raise on a machine
        # without a TPM.  The lazy-import pattern means construction is safe.
        signer = TpmRecordSigner(key_name="hypothetical-key")
        assert signer is not None


# ---------------------------------------------------------------------------
# Group M / N: software-stub sign+verify round-trip (no real TPM needed)
# ---------------------------------------------------------------------------


class TestTpmRecordSignerStubRoundTrip:
    """Use monkeypatched tpm_signer to exercise TpmRecordSigner's sign/verify
    logic without a real chip, verifying the interface contract."""

    def _patched_signer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        key: bytes,
    ) -> TpmRecordSigner:
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: None)
        monkeypatch.setattr(tpm_signer, "sign", _make_stub_sign(key))
        monkeypatch.setattr(tpm_signer, "verify", _make_stub_verify(key))
        return TpmRecordSigner(key_name="test-audit-key")

    def test_sign_returns_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signer = self._patched_signer(monkeypatch, b"test-key-32bytes!!!!!!!!!!!!!!!!")
        sig = signer.sign(b"data")
        assert isinstance(sig, bytes)
        assert len(sig) > 0

    def test_verify_accepts_own_signature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = b"test-key-32bytes!!!!!!!!!!!!!!!!"
        signer = self._patched_signer(monkeypatch, key)
        data = b"canonical-record-bytes"
        sig = signer.sign(data)
        assert signer.verify(data, sig) is True

    def test_verify_rejects_corrupted_signature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = b"test-key-32bytes!!!!!!!!!!!!!!!!"
        signer = self._patched_signer(monkeypatch, key)
        data = b"canonical-record-bytes"
        sig = signer.sign(data)
        corrupted = bytes([sig[0] ^ 0xFF]) + sig[1:]
        assert signer.verify(data, corrupted) is False

    def test_full_chain_verify_with_tpm_signer(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A chain built and verified with TpmRecordSigner (stubbed) passes verify()."""
        key = b"test-audit-key-32bytes!!!!!!!!!!!"
        signer = self._patched_signer(monkeypatch, key)
        log = AuditLog.in_memory(signer=signer)
        _append_record(log, override={"adjudication_id": "id-0"})
        _append_record(log, override={"adjudication_id": "id-1", "decision": "DENY"})
        _append_record(log, override={"adjudication_id": "id-2"})
        log.verify()  # must not raise
        assert log.record_count == 3


# ---------------------------------------------------------------------------
# Group O: SWAGR MINOR-3 CONTRAST TEST
# Encodes the upgrade's security value as a VISIBLE test, not prose.
#
# The claim:
#   - HmacSha256Signer with a RECOMPUTABLE key (derived from public information)
#     is forgeable: an adversary can re-derive the key, recompute a valid
#     signature over tampered bytes, and verify() accepts it.
#   - TpmRecordSigner's key is NON-RECOMPUTABLE from filesystem state (it is
#     sealed inside the chip with no export path), so an adversary who tampers
#     with a record cannot produce a valid signature for the tampered bytes —
#     verify() rejects them.  We demonstrate this property by showing that a
#     "forger" armed only with the key-derivation formula (filesystem access)
#     can fool the HMAC signer but NOT the TPM signer.
# ---------------------------------------------------------------------------


class TestStubVsTpmContrastForgeability:
    """SWAGR MINOR-3 contrast test: the stub key is forgeable; the TPM key is not."""

    def test_stub_key_is_recomputable_and_forgeable(self, tmp_path: Path) -> None:
        """An adversary who knows the derivation formula can re-derive the HMAC key
        and forge a valid signature over tampered canonical bytes.

        This is the FORGEABLE scenario: the stub-signer path used in dev/CI
        is NOT a security boundary (by design — the hash chain provides tamper
        evidence; the HMAC signer provides only a weak authenticity signal
        when the key derivation is filesystem-visible).
        """
        audit_path = tmp_path / "audit.jsonl"

        # 1. Build a record with the stub signer (same derivation as _build_audit_log).
        stub_key = hashlib.sha256(
            b"BlarAI-audit-hmac-stub-v1::" + str(audit_path).encode("utf-8")
        ).digest()
        original_signer = HmacSha256Signer(key=stub_key, key_id="dev-stub")
        log = AuditLog.in_memory(signer=original_signer)
        _append_record(log)

        # 2. Tamper the record's decision field.
        rec = log.records[0]
        tampered_decision = "ALLOW_FORGED"

        # 3. An adversary re-derives the key (they have filesystem access —
        #    the derivation is deterministic from the known log path).
        adversary_key = hashlib.sha256(
            b"BlarAI-audit-hmac-stub-v1::" + str(audit_path).encode("utf-8")
        ).digest()
        assert adversary_key == stub_key, "Key derivation must be recomputable"

        # 4. The adversary recomputes the canonical bytes for the tampered record.
        tampered_canon = _canonical_bytes(
            seq=rec.seq,
            adjudication_id=rec.adjudication_id,
            decision=tampered_decision,
            car_hash=rec.car_hash,
            source_agent=rec.source_agent,
            destination_service=rec.destination_service,
            verb=rec.verb,
            resource=rec.resource,
            sensitivity=rec.sensitivity,
            rule_engine_passed=rec.rule_engine_passed,
            confidence=rec.confidence,
            timestamp_utc=rec.timestamp_utc,
            prev_hash=rec.prev_hash,
        )

        # 5. The adversary forges a valid HMAC signature with the re-derived key.
        import hmac as _hmac

        forged_sig = _hmac.new(adversary_key, tampered_canon, hashlib.sha256).digest()

        # 6. DEMONSTRATE FORGEABLE: the forged signature verifies as authentic.
        #    The stub signer ACCEPTS the forged signature — the attacker wins.
        forger_signer = HmacSha256Signer(key=adversary_key, key_id="dev-stub")
        assert forger_signer.verify(tampered_canon, forged_sig) is True, (
            "STUB FORGEABLE: a re-derived key produces a valid signature over "
            "tampered bytes — the adversary successfully forges an audit record."
        )

    def test_tpm_signer_key_is_not_recomputable_from_filesystem(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An adversary who knows the TPM key NAME cannot forge a valid signature
        because the private key never leaves the chip (no export path).

        We demonstrate this by showing that a software signer using a DIFFERENT
        key (simulating the adversary's inability to obtain the real TPM key)
        produces a signature that the TpmRecordSigner REJECTS — they cannot
        forge it even knowing the algorithm and key name.

        In the real attack: the adversary knows ``AUDIT_TPM_KEY_NAME`` (it is in
        source) but cannot call NCryptExportKey on the private half (CNG refuses;
        test_tpm_signer asserts this on hardware).  We simulate the adversary's
        position with a DIFFERENT software key and prove verify() rejects it.
        """
        # The real TPM key (chip-bound, non-exportable):
        real_tpm_key = b"real-non-exportable-chip-key-!!!!!"
        # The adversary's best guess (they cannot extract the real key):
        adversary_key = b"adversary-guessed-key-random-!!!!"
        assert real_tpm_key != adversary_key

        # Wire TpmRecordSigner to use the REAL key internally.
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: None)
        monkeypatch.setattr(tpm_signer, "sign", _make_stub_sign(real_tpm_key))
        monkeypatch.setattr(tpm_signer, "verify", _make_stub_verify(real_tpm_key))

        tpm_signer_instance = TpmRecordSigner(key_name=AUDIT_TPM_KEY_NAME)

        # Build a legitimate record.
        log = AuditLog.in_memory(signer=tpm_signer_instance)
        _append_record(log)
        rec = log.records[0]

        # Adversary tampers the decision and tries to forge a signature.
        tampered_canon = _canonical_bytes(
            seq=rec.seq,
            adjudication_id=rec.adjudication_id,
            decision="ALLOW_FORGED",
            car_hash=rec.car_hash,
            source_agent=rec.source_agent,
            destination_service=rec.destination_service,
            verb=rec.verb,
            resource=rec.resource,
            sensitivity=rec.sensitivity,
            rule_engine_passed=rec.rule_engine_passed,
            confidence=rec.confidence,
            timestamp_utc=rec.timestamp_utc,
            prev_hash=rec.prev_hash,
        )

        # Adversary cannot get the real key, so they sign with their own key.
        import hmac as _hmac

        adversary_forged_sig = _hmac.new(
            adversary_key, tampered_canon, hashlib.sha256
        ).digest()

        # DEMONSTRATE NON-FORGEABLE: the TpmRecordSigner rejects the forged sig.
        # (verify() uses the real chip key; the adversary's key is different.)
        assert tpm_signer_instance.verify(tampered_canon, adversary_forged_sig) is False, (
            "TPM NON-FORGEABLE: the adversary's signature over tampered bytes "
            "must be REJECTED — they cannot extract the chip-bound private key."
        )

    def test_audit_chain_rejects_tampered_record_with_wrong_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full chain verify detects a tampered record even when adversary provides
        a forged signature with a different key (the verify key is the real TPM key).
        """
        real_key = b"real-tpm-audit-key-32bytes!!!!!"
        adversary_key = b"wrong-key-that-cannot-forge!!!!!"

        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: None)
        monkeypatch.setattr(tpm_signer, "sign", _make_stub_sign(real_key))
        monkeypatch.setattr(tpm_signer, "verify", _make_stub_verify(real_key))

        tpm_signer_obj = TpmRecordSigner(key_name=AUDIT_TPM_KEY_NAME)
        log = AuditLog.in_memory(signer=tpm_signer_obj)
        _append_record(log)
        _append_record(log, override={"adjudication_id": "id-1"})

        # Tamper record 0: replace its signature with one forged under the wrong key.
        import hmac as _hmac

        rec = log._records[0]
        tampered_canon = _canonical_bytes(
            seq=rec.seq,
            adjudication_id=rec.adjudication_id,
            decision=rec.decision,
            car_hash=rec.car_hash,
            source_agent=rec.source_agent,
            destination_service=rec.destination_service,
            verb=rec.verb,
            resource=rec.resource,
            sensitivity=rec.sensitivity,
            rule_engine_passed=rec.rule_engine_passed,
            confidence=rec.confidence,
            timestamp_utc=rec.timestamp_utc,
            prev_hash=rec.prev_hash,
        )
        forged_sig = _hmac.new(adversary_key, tampered_canon, hashlib.sha256).digest()
        object.__setattr__(rec, "signature", forged_sig.hex())

        with pytest.raises(AuditChainError) as exc_info:
            log.verify()
        assert exc_info.value.index == 0
        assert "signature" in exc_info.value.reason


# ---------------------------------------------------------------------------
# Group P/Q: Production-wiring regression
# Guards the "built but wired into nothing" trap from Sprint 13.
# ---------------------------------------------------------------------------


class TestProductionWiringRegression:
    """Assert _build_audit_log wires TpmRecordSigner in production and
    HmacSha256Signer in dev, and that _build_adjudicator actually passes the
    audit log through to the adjudicator.
    """

    def _dev_config(self, tmp_path: Path) -> Any:
        """Return a PolicyAgentEntrypointConfig in dev mode with a temp audit path."""
        from services.policy_agent.src.entrypoint import PolicyAgentEntrypointConfig
        from shared.ipc.vsock import VsockAddress, VsockConfig
        from shared.runtime_config import DeploymentMode

        return PolicyAgentEntrypointConfig(
            config_dir=tmp_path / "config",
            model_dir=tmp_path / "models",
            manifest_path=None,
            model_bin_path=tmp_path / "models" / "openvino_model.bin",
            device="GPU",
            draft_model_dir=None,
            speculative_decoding_enabled=False,
            dev_mode=True,
            jwt_tpm_key_name=None,
            jwt_ca_cert_path=None,
            jwt_issuer="policy_agent",
            jwt_validity_seconds=5,
            vsock_config=VsockConfig(
                address=VsockAddress(cid=2, port=5000),
                mtls_cert_path="",
                mtls_key_path="",
                ca_cert_path="",
                timeout_ms=5000,
                max_message_bytes=65536,
            ),
            deployment_mode=DeploymentMode.HOST,
            require_signed_manifest=False,
            audit_log_path=tmp_path / "data" / "audit" / "adjudication_audit.jsonl",
            audit_hmac_key_id="dev-stub",
        )

    def _prod_config(self, tmp_path: Path) -> Any:
        """Return a PolicyAgentEntrypointConfig in production mode."""
        from services.policy_agent.src.entrypoint import PolicyAgentEntrypointConfig
        from shared.ipc.vsock import VsockAddress, VsockConfig
        from shared.runtime_config import DeploymentMode

        return PolicyAgentEntrypointConfig(
            config_dir=tmp_path / "config",
            model_dir=tmp_path / "models",
            manifest_path=None,
            model_bin_path=tmp_path / "models" / "openvino_model.bin",
            device="GPU",
            draft_model_dir=None,
            speculative_decoding_enabled=False,
            dev_mode=False,
            jwt_tpm_key_name="BlarAI-PA-JWT-Test",
            jwt_ca_cert_path=None,
            jwt_issuer="policy_agent",
            jwt_validity_seconds=5,
            vsock_config=VsockConfig(
                address=VsockAddress(cid=2, port=5000),
                mtls_cert_path="",
                mtls_key_path="",
                ca_cert_path="",
                timeout_ms=5000,
                max_message_bytes=65536,
            ),
            deployment_mode=DeploymentMode.HOST,
            require_signed_manifest=False,
            audit_log_path=tmp_path / "data" / "audit" / "adjudication_audit.jsonl",
            audit_hmac_key_id="dev-stub",
        )

    def test_dev_mode_uses_hmac_signer(self, tmp_path: Path) -> None:
        """In dev mode, _build_audit_log wires HmacSha256Signer."""
        from services.policy_agent.src.entrypoint import PolicyAgentService

        resolved = self._dev_config(tmp_path)
        audit_log = PolicyAgentService._build_audit_log(resolved)

        assert audit_log is not None
        assert isinstance(audit_log._signer, HmacSha256Signer), (
            "Dev mode must use HmacSha256Signer (stub) — never silently fall "
            "back in production."
        )

    def test_production_mode_uses_tpm_signer_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """In production mode with a provisioned key, _build_audit_log wires
        TpmRecordSigner — NOT HmacSha256Signer.

        This is the core wiring regression: it asserts the actual type of signer
        wired into the live factory, so a code refactor that accidentally
        downgrades to the HMAC stub in production will fail this test.
        """
        from services.policy_agent.src.entrypoint import PolicyAgentService

        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: True)

        resolved = self._prod_config(tmp_path)
        audit_log = PolicyAgentService._build_audit_log(resolved)

        assert audit_log is not None, (
            "Production _build_audit_log must return a non-None log when TPM "
            "key is provisioned."
        )
        assert isinstance(audit_log._signer, TpmRecordSigner), (
            "Production mode must wire TpmRecordSigner — not HmacSha256Signer. "
            "If this fails, the TPM upgrade has been silently reverted."
        )

    def test_production_mode_uses_dedicated_audit_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Production wiring uses AUDIT_TPM_KEY_NAME, not the JWT key (separation
        of duties: Sprint 14 constraint).
        """
        from services.policy_agent.src.entrypoint import PolicyAgentService

        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: True)

        resolved = self._prod_config(tmp_path)
        audit_log = PolicyAgentService._build_audit_log(resolved)

        assert audit_log is not None
        assert isinstance(audit_log._signer, TpmRecordSigner)
        # The signer_id encodes the key name — verify it is the DEDICATED audit
        # key and NOT the JWT signing key.
        sid = audit_log._signer.signer_id()
        assert AUDIT_TPM_KEY_NAME in sid, (
            f"Audit signer must use the dedicated audit key '{AUDIT_TPM_KEY_NAME}', "
            f"not a JWT or other key. Got signer_id: {sid!r}"
        )
        # Confirm it is NOT the JWT key (separation of duties).
        jwt_key_name = resolved.jwt_tpm_key_name or ""
        assert jwt_key_name not in sid or jwt_key_name == AUDIT_TPM_KEY_NAME, (
            "Audit signer must not reuse the JWT TPM key — separation of duties."
        )

    def test_production_mode_refuses_to_start_when_key_unprovisioned(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Production mode raises AuditProvisioningError (refuse-to-start) when
        the audit TPM key has not been provisioned (ADR-025 §2.8(a)).

        The LA ruled: a PA authorizing actions with no audit trail in production
        is a governance hole.  The audit path is intentionally STRICTER than
        _build_jwt_minter (which degrades to None) — it refuses to start instead.
        """
        from services.policy_agent.src.entrypoint import PolicyAgentService

        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: False)

        resolved = self._prod_config(tmp_path)
        with pytest.raises(AuditProvisioningError, match="not provisioned"):
            PolicyAgentService._build_audit_log(resolved)

    def test_production_mode_refuses_to_start_on_tpm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Production mode raises AuditProvisioningError when the TPM is
        unavailable (ADR-025 §2.8(a) — refuse-to-start posture).
        """
        from services.policy_agent.src.entrypoint import PolicyAgentService

        def _raise(name: str) -> bool:
            raise tpm_signer.TpmUnavailable("no platform TPM in test")

        monkeypatch.setattr(tpm_signer, "key_exists", _raise)

        resolved = self._prod_config(tmp_path)
        with pytest.raises(AuditProvisioningError, match="TPM unavailable"):
            PolicyAgentService._build_audit_log(resolved)

    # -----------------------------------------------------------------------
    # Group P (continued): EA-5c — production refuses to start when
    # audit_log_path is not configured at all (LA ruling 2026-06-05,
    # ADR-025 §2.8(a)).
    # -----------------------------------------------------------------------

    def test_production_mode_refuses_to_start_when_audit_path_not_configured(
        self, tmp_path: Path
    ) -> None:
        """Production mode raises AuditProvisioningError (refuse-to-start) when
        audit_log_path is None — i.e. the operator never set an audit-log path.

        LA ruling 2026-06-05: a PA authorizing actions in production with no
        audit trail, for ANY reason, is a governance hole.  Missing path is
        treated identically to a missing TPM key: the PA refuses to start
        rather than silently running without a forensic record (ADR-025 §2.8(a)).
        """
        from services.policy_agent.src.entrypoint import (
            PolicyAgentEntrypointConfig,
            PolicyAgentService,
        )
        from shared.ipc.vsock import VsockAddress, VsockConfig
        from shared.runtime_config import DeploymentMode

        resolved = PolicyAgentEntrypointConfig(
            config_dir=tmp_path / "config",
            model_dir=tmp_path / "models",
            manifest_path=None,
            model_bin_path=tmp_path / "models" / "openvino_model.bin",
            device="GPU",
            draft_model_dir=None,
            speculative_decoding_enabled=False,
            dev_mode=False,  # PRODUCTION
            jwt_tpm_key_name="BlarAI-PA-JWT-Test",
            jwt_ca_cert_path=None,
            jwt_issuer="policy_agent",
            jwt_validity_seconds=5,
            vsock_config=VsockConfig(
                address=VsockAddress(cid=2, port=5000),
                mtls_cert_path="",
                mtls_key_path="",
                ca_cert_path="",
                timeout_ms=5000,
                max_message_bytes=65536,
            ),
            deployment_mode=DeploymentMode.HOST,
            require_signed_manifest=False,
            audit_log_path=None,  # NOT CONFIGURED — the governance hole under test
            audit_hmac_key_id="dev-stub",
        )
        with pytest.raises(
            AuditProvisioningError,
            match="No audit-log path configured",
        ):
            PolicyAgentService._build_audit_log(resolved)

    def test_dev_mode_returns_none_when_audit_path_not_configured(
        self, tmp_path: Path
    ) -> None:
        """Dev mode returns None when audit_log_path is None — audit log is
        optional in dev/CI.

        This is the baseline: no regression from the pre-EA-5c behaviour.
        The production guard must NOT fire in dev mode when the path is absent.
        """
        from services.policy_agent.src.entrypoint import (
            PolicyAgentEntrypointConfig,
            PolicyAgentService,
        )
        from shared.ipc.vsock import VsockAddress, VsockConfig
        from shared.runtime_config import DeploymentMode

        resolved = PolicyAgentEntrypointConfig(
            config_dir=tmp_path / "config",
            model_dir=tmp_path / "models",
            manifest_path=None,
            model_bin_path=tmp_path / "models" / "openvino_model.bin",
            device="GPU",
            draft_model_dir=None,
            speculative_decoding_enabled=False,
            dev_mode=True,  # DEV — no audit required
            jwt_tpm_key_name=None,
            jwt_ca_cert_path=None,
            jwt_issuer="policy_agent",
            jwt_validity_seconds=5,
            vsock_config=VsockConfig(
                address=VsockAddress(cid=2, port=5000),
                mtls_cert_path="",
                mtls_key_path="",
                ca_cert_path="",
                timeout_ms=5000,
                max_message_bytes=65536,
            ),
            deployment_mode=DeploymentMode.HOST,
            require_signed_manifest=False,
            audit_log_path=None,  # NOT CONFIGURED — acceptable in dev
            audit_hmac_key_id="dev-stub",
        )
        result = PolicyAgentService._build_audit_log(resolved)
        assert result is None, (
            "Dev mode with no audit_log_path must return None — "
            "the production refuse-to-start guard must not fire in dev mode."
        )

    def test_build_adjudicator_has_audit_log_in_dev_mode(self, tmp_path: Path) -> None:
        """_build_adjudicator wires the audit log in dev mode — has_audit_log is True."""
        from services.policy_agent.src.config_loader import RateLimitConfig, RuleEngineConfig
        from services.policy_agent.src.entrypoint import PolicyAgentService

        resolved = self._dev_config(tmp_path)
        rule_cfg = RuleEngineConfig(
            acl_matrix={"assistant_orchestrator": ["substrate"]},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(max_requests_per_window=10, window_seconds=60.0),
            version="1.0.0",
        )
        inference = MagicMock()
        adjudicator = PolicyAgentService._build_adjudicator(inference, rule_cfg, resolved)

        assert adjudicator.has_audit_log is True, (
            "_build_adjudicator must wire the audit log — has_audit_log False "
            "means decisions are being silently discarded (the Sprint-13 anti-pattern)."
        )

    def test_build_adjudicator_has_audit_log_in_production_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """_build_adjudicator wires the audit log in production mode — has_audit_log is True."""
        from services.policy_agent.src.config_loader import RateLimitConfig, RuleEngineConfig
        from services.policy_agent.src.entrypoint import PolicyAgentService

        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: True)

        resolved = self._prod_config(tmp_path)
        rule_cfg = RuleEngineConfig(
            acl_matrix={"assistant_orchestrator": ["substrate"]},
            resource_deny_rules=[],
            rate_limit=RateLimitConfig(max_requests_per_window=10, window_seconds=60.0),
            version="1.0.0",
        )
        inference = MagicMock()
        adjudicator = PolicyAgentService._build_adjudicator(inference, rule_cfg, resolved)

        assert adjudicator.has_audit_log is True, (
            "_build_adjudicator must wire the audit log in production mode too."
        )


# ---------------------------------------------------------------------------
# Group R: Hardware round-trip (slow, requires real TPM 2.0 on-chip)
# Deselected by default — run with: pytest -m slow
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestTpmRecordSignerHardware:
    """Real-chip round-trip: sign/verify with the TPM audit key on real hardware.

    These tests are excluded from the default suite because they require the
    on-chip ceremony to have been run (``ensure_key`` provisions the key if
    absent, which the tests rely on).
    """

    @pytest.fixture(autouse=True)
    def require_tpm(self) -> None:
        """Skip the whole class if no real TPM is present."""
        if not tpm_signer.is_available():
            pytest.skip("No real TPM available on this host")

    def test_hardware_sign_and_verify_round_trip(self) -> None:
        """Sign real canonical bytes and verify with the same key (real chip)."""
        signer = TpmRecordSigner(key_name=AUDIT_TPM_KEY_NAME)
        data = b"hardware-audit-test-canonical-bytes"
        sig = signer.sign(data)
        assert isinstance(sig, bytes)
        assert len(sig) > 0
        assert signer.verify(data, sig) is True

    def test_hardware_wrong_data_rejected(self) -> None:
        """Verify with different data rejects the signature (real chip)."""
        signer = TpmRecordSigner(key_name=AUDIT_TPM_KEY_NAME)
        data = b"original-data"
        sig = signer.sign(data)
        assert signer.verify(b"tampered-data", sig) is False

    def test_hardware_dedicated_key_separate_from_jwt_key(self) -> None:
        """The audit key name differs from the default JWT key (separation of duties)."""
        jwt_default = "BlarAI-JWT-Signing-Key-v1"  # The PA JWT key from provision_signing_key.py
        assert AUDIT_TPM_KEY_NAME != jwt_default, (
            "Audit key must be a DIFFERENT key than the JWT signing key — "
            "separation of duties requires separate chip slots."
        )

    def test_hardware_full_chain_with_tpm_signer(self) -> None:
        """A chain built and verified entirely with the TPM signer passes verify()."""
        signer = TpmRecordSigner(key_name=AUDIT_TPM_KEY_NAME)
        log = AuditLog.in_memory(signer=signer)
        for i in range(3):
            _append_record(log, override={"adjudication_id": f"hw-id-{i}"})
        log.verify()
        assert log.record_count == 3
