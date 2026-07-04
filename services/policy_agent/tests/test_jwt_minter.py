"""
P1.5 Tests — Agentic JWT Minter
=================================
Groups:
  A. TestMintedJWT          — frozen dataclass properties (3 tests)
  B. TestEpochManager       — monotonic epoch counter (5 tests)
  C. TestAgenticJWTMinter   — construction, properties, key I/O (7 tests)
  D. TestMinting            — claims structure, nonce, epoch, fail-closed (9 tests)
  E. TestLegacyMintFunction — backward compat pure function (3 tests)
  F. TestTpmMintingPath     — TPM signing path via software stand-in (ADR-020)
  G. TestTpmMintingHardware — real platform TPM 2.0 round-trip (@slow, on-chip)
  H. TestTokenLifetime5s    — #638: minted token carries a 5 s hard TTL
  I. TestRevoke             — #638: revoke() bumps the epoch (revoke-all caller)
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from services.policy_agent.src.jwt_minter import (
    AgenticJWTMinter,
    EpochManager,
    MintedJWT,
    mint_agentic_jwt,
)
from shared.crypto.jwt_validator import AgenticJWTValidator
from shared.schemas.car import (
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
    Sensitivity,
)
from shared.security import tpm_signer


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_decision(
    *,
    decision: AdjudicationDecision = AdjudicationDecision.ALLOW,
    confidence: float = 0.90,
) -> DecisionArtifact:
    """Build a minimal DecisionArtifact for testing."""
    car = CanonicalActionRepresentation(
        source_agent="assistant_orchestrator",
        destination_service="substrate",
        verb="READ",
        resource="substrate.vector_store",
        sensitivity=Sensitivity.INTERNAL,
        request_id="req-test-001",
    )
    return DecisionArtifact(
        car_hash=car.canonical_hash(),
        decision=decision,
        request_id=car.request_id,
        deterministic_pass=True,
        probabilistic_pass=True,
        confidence=confidence,
    )


def _gen_key_pair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    return AgenticJWTMinter.generate_key_pair()


def _make_minter(
    *,
    validity_seconds: int = 5,
    epoch_manager: EpochManager | None = None,
) -> AgenticJWTMinter:
    priv, _ = _gen_key_pair()
    return AgenticJWTMinter(
        priv,
        validity_seconds=validity_seconds,
        epoch_manager=epoch_manager,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Group A: TestMintedJWT
# ═══════════════════════════════════════════════════════════════════════════


class TestMintedJWT:
    """Frozen dataclass properties."""

    def test_default_fields(self) -> None:
        r = MintedJWT(token="", success=False)
        assert r.nonce == ""
        assert r.epoch == 0
        assert r.error is None

    def test_success_fields(self) -> None:
        r = MintedJWT(token="abc", success=True, nonce="ff" * 16, epoch=3)
        assert r.success is True
        assert len(r.nonce) == 32
        assert r.epoch == 3

    def test_frozen_immutable(self) -> None:
        r = MintedJWT(token="", success=False)
        with pytest.raises(FrozenInstanceError):
            r.token = "hack"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# Group B: TestEpochManager
# ═══════════════════════════════════════════════════════════════════════════


class TestEpochManager:
    """Monotonic epoch counter."""

    def test_initial_value_default(self) -> None:
        em = EpochManager()
        assert em.current == 1

    def test_initial_value_custom(self) -> None:
        em = EpochManager(initial_epoch=42)
        assert em.current == 42

    def test_minimum_clamp(self) -> None:
        em = EpochManager(initial_epoch=0)
        assert em.current == 1  # min 1

    def test_increment(self) -> None:
        em = EpochManager()
        new = em.increment()
        assert new == 2
        assert em.current == 2

    def test_monotonic(self) -> None:
        em = EpochManager()
        vals = [em.increment() for _ in range(5)]
        assert vals == [2, 3, 4, 5, 6]


# ═══════════════════════════════════════════════════════════════════════════
# Group C: TestAgenticJWTMinter — construction, properties, key I/O
# ═══════════════════════════════════════════════════════════════════════════


class TestAgenticJWTMinterProperties:
    """Construction and properties."""

    def test_initial_mint_count_zero(self) -> None:
        m = _make_minter()
        assert m.mint_count == 0

    def test_epoch_default(self) -> None:
        m = _make_minter()
        assert m.epoch == 1

    def test_epoch_custom(self) -> None:
        em = EpochManager(initial_epoch=10)
        m = _make_minter(epoch_manager=em)
        assert m.epoch == 10

    def test_issuer_default(self) -> None:
        m = _make_minter()
        assert m.issuer == "policy_agent"

    def test_validity_seconds(self) -> None:
        m = _make_minter(validity_seconds=30)
        assert m.validity_seconds == 30

    def test_generate_key_pair_types(self) -> None:
        priv, pub = AgenticJWTMinter.generate_key_pair()
        assert isinstance(priv, ec.EllipticCurvePrivateKey)
        assert isinstance(pub, ec.EllipticCurvePublicKey)

    def test_save_and_load_key_pair(self) -> None:
        priv, _ = _gen_key_pair()
        tmp = tempfile.mkdtemp()
        priv_path = os.path.join(tmp, "priv.pem")
        pub_path = os.path.join(tmp, "pub.pem")
        try:
            AgenticJWTMinter.save_key_pair(priv, priv_path, pub_path)
            assert os.path.exists(priv_path)
            assert os.path.exists(pub_path)
            minter = AgenticJWTMinter.from_key_file(priv_path)
            assert minter is not None
            assert minter.epoch == 1
        finally:
            for p in (priv_path, pub_path):
                if os.path.exists(p):
                    os.remove(p)
            os.rmdir(tmp)


# ═══════════════════════════════════════════════════════════════════════════
# Group D: TestMinting — claims structure, nonce, epoch, fail-closed
# ═══════════════════════════════════════════════════════════════════════════


class TestMinting:
    """Full minting pipeline."""

    def test_successful_mint(self) -> None:
        m = _make_minter()
        decision = _make_decision()
        result = m.mint(decision)
        assert result.success is True
        assert result.token != ""
        assert result.error is None

    def test_nonce_128_bit_hex(self) -> None:
        m = _make_minter()
        result = m.mint(_make_decision())
        assert len(result.nonce) == 32  # 128 bits = 16 bytes = 32 hex chars
        int(result.nonce, 16)  # must be valid hex

    def test_epoch_in_result(self) -> None:
        em = EpochManager(initial_epoch=7)
        m = _make_minter(epoch_manager=em)
        result = m.mint(_make_decision())
        assert result.epoch == 7

    def test_claims_structure(self) -> None:
        priv, pub = _gen_key_pair()
        m = AgenticJWTMinter(priv, validity_seconds=60)
        decision = _make_decision()
        result = m.mint(decision)

        claims = pyjwt.decode(result.token, pub, algorithms=["ES256"])
        assert claims["iss"] == "policy_agent"
        assert claims["car_hash"] == decision.car_hash
        assert claims["decision"] == "ALLOW"
        assert claims["request_id"] == "req-test-001"
        assert claims["deterministic_pass"] is True
        assert claims["probabilistic_pass"] is True
        assert abs(claims["confidence"] - 0.90) < 0.001
        assert claims["epoch"] == 1
        assert len(claims["nonce"]) == 32
        assert "jti" in claims
        assert "iat" in claims
        assert "exp" in claims

    def test_nonce_unique_per_mint(self) -> None:
        m = _make_minter()
        nonces = {m.mint(_make_decision()).nonce for _ in range(20)}
        assert len(nonces) == 20  # all unique

    def test_mint_count_increments(self) -> None:
        m = _make_minter()
        for i in range(3):
            m.mint(_make_decision())
        assert m.mint_count == 3

    def test_deny_decision_minted(self) -> None:
        priv, pub = _gen_key_pair()
        m = AgenticJWTMinter(priv, validity_seconds=60)
        decision = _make_decision(decision=AdjudicationDecision.DENY)
        result = m.mint(decision)
        claims = pyjwt.decode(result.token, pub, algorithms=["ES256"])
        assert claims["decision"] == "DENY"

    def test_escalate_decision_minted(self) -> None:
        priv, pub = _gen_key_pair()
        m = AgenticJWTMinter(priv, validity_seconds=60)
        decision = _make_decision(decision=AdjudicationDecision.ESCALATE)
        result = m.mint(decision)
        claims = pyjwt.decode(result.token, pub, algorithms=["ES256"])
        assert claims["decision"] == "ESCALATE"

    def test_from_key_file_bad_path_returns_none(self) -> None:
        result = AgenticJWTMinter.from_key_file("/nonexistent/key.pem")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Group E: TestLegacyMintFunction
# ═══════════════════════════════════════════════════════════════════════════


class TestLegacyMintFunction:
    """Backward-compat ``mint_agentic_jwt()`` pure function."""

    def test_with_valid_key_file(self) -> None:
        priv, _ = _gen_key_pair()
        tmp = tempfile.mkdtemp()
        key_path = os.path.join(tmp, "priv.pem")
        try:
            Path(key_path).write_bytes(
                priv.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            result = mint_agentic_jwt(_make_decision(), key_path)
            assert result.success is True
            assert result.token != ""
        finally:
            if os.path.exists(key_path):
                os.remove(key_path)
            os.rmdir(tmp)

    def test_with_bad_path_fail_closed(self) -> None:
        result = mint_agentic_jwt(_make_decision(), "/nonexistent.pem")
        assert result.success is False
        assert result.error is not None

    def test_with_bad_key_content_fail_closed(self) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        try:
            tmp.write(b"not a valid PEM key")
            tmp.close()
            result = mint_agentic_jwt(_make_decision(), tmp.name)
            assert result.success is False
        finally:
            os.unlink(tmp.name)


# ═══════════════════════════════════════════════════════════════════════════
# Group F: TestTpmMintingPath — TPM-backed signing path (ADR-020)
# ═══════════════════════════════════════════════════════════════════════════


def _software_tpm_sign(private_key: ec.EllipticCurvePrivateKey):
    """Stand-in for ``tpm_signer.sign`` that signs with a software key.

    Returns the raw r‖s (64-byte) signature CNG/TPM produces, so it exercises the
    minter's real signing path and JOSE normalisation without needing hardware.
    """

    def _sign(key_name: str, data: bytes) -> bytes:
        der = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    return _sign


class TestTpmMintingPath:
    """TPM signing path, exercised with a software stand-in for the TPM."""

    def test_requires_exactly_one_backend(self) -> None:
        with pytest.raises(ValueError):
            AgenticJWTMinter()  # neither private_key nor tpm_key_name
        priv, _ = _gen_key_pair()
        with pytest.raises(ValueError):
            AgenticJWTMinter(priv, tpm_key_name="k")  # both

    def test_from_tpm_sets_key_name(self) -> None:
        m = AgenticJWTMinter.from_tpm("BlarAI-PA-JWT-Signing")
        assert m._tpm_key_name == "BlarAI-PA-JWT-Signing"
        assert m._private_key is None

    def test_tpm_minted_jwt_validates_with_real_validator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        priv, pub = _gen_key_pair()
        monkeypatch.setattr(tpm_signer, "sign", _software_tpm_sign(priv))

        minter = AgenticJWTMinter.from_tpm("test-key", validity_seconds=60)
        decision = _make_decision()
        result = minter.mint(decision)
        assert result.success is True, result.error

        # PyJWT accepts it directly...
        claims = pyjwt.decode(result.token, pub, algorithms=["ES256"])
        assert claims["car_hash"] == decision.car_hash
        assert claims["decision"] == "ALLOW"
        assert len(claims["nonce"]) == 32

        # ...and so does the production validator, all 5 stages.
        validator = AgenticJWTValidator(pub, expected_issuer="policy_agent")
        vr = validator.validate(result.token)
        assert vr.valid is True, vr.error
        assert vr.car_hash == decision.car_hash

    def test_tpm_signature_is_jose_raw_64_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        priv, _ = _gen_key_pair()
        monkeypatch.setattr(tpm_signer, "sign", _software_tpm_sign(priv))
        minter = AgenticJWTMinter.from_tpm("test-key")
        token = minter.mint(_make_decision()).token
        sig_b64 = token.split(".")[2]
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        assert len(sig) == 64  # raw r‖s, the ES256/JOSE form

    def test_tpm_sign_failure_is_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(key_name: str, data: bytes) -> bytes:
            raise tpm_signer.TpmUnavailable("no TPM")

        monkeypatch.setattr(tpm_signer, "sign", _boom)
        result = AgenticJWTMinter.from_tpm("test-key").mint(_make_decision())
        assert result.success is False
        assert result.token == ""
        assert result.error is not None


# ═══════════════════════════════════════════════════════════════════════════
# Group G: TestTpmMintingHardware — real platform TPM 2.0 (deselected by default)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.slow
class TestTpmMintingHardware:
    """Full provision → TPM-sign → export-public → validate, on the real chip.

    Run with: ``pytest services/policy_agent/tests/test_jwt_minter.py -m slow``.
    Skipped if no TPM is present. Uses a throwaway test key (provisioned then
    deleted) — never the production signing key.
    """

    _KEY = "BlarAI-PA-JWT-PytestHW"

    @pytest.fixture(autouse=True)
    def _require_tpm(self):
        if not tpm_signer.is_available():
            pytest.skip("No platform TPM available")
        tpm_signer.ensure_key(self._KEY)
        yield
        try:
            tpm_signer.delete_key(self._KEY)
        except Exception:
            pass

    def test_tpm_minted_jwt_validates_on_chip(self) -> None:
        minter = AgenticJWTMinter.from_tpm(self._KEY, validity_seconds=60)
        decision = _make_decision()
        result = minter.mint(decision)
        assert result.success is True, result.error

        pub = load_pem_public_key(tpm_signer.export_public_key_pem(self._KEY))
        validator = AgenticJWTValidator(pub, expected_issuer="policy_agent")
        vr = validator.validate(result.token)
        assert vr.valid is True, vr.error
        assert vr.car_hash == decision.car_hash
        assert vr.decision == "ALLOW"


# ═══════════════════════════════════════════════════════════════════════════
# Group H: TestTokenLifetime5s — #638: minted token carries a 5 s hard TTL
# ═══════════════════════════════════════════════════════════════════════════


class TestTokenLifetime5s:
    """#638 — the capability-token lifetime is the 5 s hard TTL (was 30 s).

    The 5 s value is the only containment that previously failed OPEN: both PA
    service configs set ``validity_seconds = 30`` while the spec (Use
    Cases_FINAL.md §3) and the module constant are 5 s. These tests lock the
    minted-token lifetime so a future config drift back to 30 s fails the gate.
    """

    def test_minted_exp_minus_iat_is_5s(self) -> None:
        priv, pub = _gen_key_pair()
        m = AgenticJWTMinter(priv, validity_seconds=5)
        token = m.mint(_make_decision()).token
        # Decode WITHOUT verifying exp so the assertion is on the claim values,
        # not on wall-clock timing (the token would still be live anyway).
        claims = pyjwt.decode(
            token, pub, algorithms=["ES256"], options={"verify_exp": False}
        )
        assert claims["exp"] - claims["iat"] == 5

    def test_module_constant_is_5s(self) -> None:
        # The minter's default validity tracks the spec constant (5 s). This is
        # the safe default that the (now-corrected) config no longer overrides
        # to 30 s.
        from services.policy_agent.src.constants import JWT_VALIDITY_SECONDS

        assert JWT_VALIDITY_SECONDS == 5
        priv, _ = _gen_key_pair()
        # Construct with no explicit validity → falls back to the constant.
        m = AgenticJWTMinter(priv)
        assert m.validity_seconds == 5


# ═══════════════════════════════════════════════════════════════════════════
# Group I: TestRevoke — #638: revoke() bumps the epoch (revoke-all caller)
# ═══════════════════════════════════════════════════════════════════════════


class TestRevoke:
    """#638 — ``revoke()`` is the runtime revoke-all entry point.

    Before #638, ``EpochManager.increment`` had no runtime caller (the
    capability was built but wired into nothing). ``revoke()`` is that wiring:
    one call advances the epoch so every prior-epoch token is rejected at
    destination validators (epoch Stage 3).
    """

    def test_revoke_bumps_epoch_by_one(self) -> None:
        m = _make_minter()
        assert m.epoch == 1
        new_epoch = m.revoke()
        assert new_epoch == 2
        assert m.epoch == 2

    def test_revoke_is_monotonic(self) -> None:
        m = _make_minter()
        epochs = [m.revoke() for _ in range(3)]
        assert epochs == [2, 3, 4]

    def test_tokens_minted_after_revoke_carry_new_epoch(self) -> None:
        priv, pub = _gen_key_pair()
        m = AgenticJWTMinter(priv, validity_seconds=60)
        before = pyjwt.decode(
            m.mint(_make_decision()).token, pub, algorithms=["ES256"],
            options={"verify_exp": False},
        )
        assert before["epoch"] == 1
        m.revoke()
        after = pyjwt.decode(
            m.mint(_make_decision()).token, pub, algorithms=["ES256"],
            options={"verify_exp": False},
        )
        assert after["epoch"] == 2
