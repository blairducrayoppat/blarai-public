"""Tests for the TPM signing-key provisioning ceremony (ADR-021).

  - TestProvisionCeremony — headless, with the TPM stubbed via monkeypatch.
    Proves the command's logic (write public PEM, canonical fingerprint,
    idempotence, fail-closed-without-TPM) on any machine.
  - TestProvisionCeremonyOnChip — real platform TPM 2.0 (@slow, on-chip).
    Proves the ceremony writes a public key the production validator can load
    and that the written public half corresponds to the TPM private key.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils as asym_utils
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from services.policy_agent.src.constants import PA_JWT_TPM_KEY_NAME
from shared.crypto.jwt_validator import AgenticJWTValidator
from shared.security import provision_signing_key as psk
from shared.security import tpm_signer


def _gen_public_key_pem() -> bytes:
    """A real P-256 SubjectPublicKeyInfo PEM, standing in for a TPM export."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _spki_der_sha256(public_key_pem: bytes) -> str:
    public_key = load_pem_public_key(public_key_pem)
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


class TestProvisionCeremony:
    """Ceremony logic with a software stand-in for the TPM."""

    def test_writes_public_key_and_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pem = _gen_public_key_pem()
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: True)
        monkeypatch.setattr(tpm_signer, "export_public_key_pem", lambda name: pem)

        out = tmp_path / "certs" / "pa_public.pem"
        rc = psk.provision("BlarAI-PA-JWT-Signing", out)

        assert rc == 0
        assert out.exists()
        assert out.read_bytes() == pem

    def test_prints_canonical_fingerprint_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pem = _gen_public_key_pem()
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: True)
        monkeypatch.setattr(tpm_signer, "export_public_key_pem", lambda name: pem)

        rc = psk.provision("BlarAI-PA-JWT-Signing", tmp_path / "pa_public.pem")
        out = capsys.readouterr().out

        assert rc == 0
        # The printed trust anchor is the canonical SHA-256(SPKI DER).
        assert _spki_der_sha256(pem) in out
        assert "BlarAI-PA-JWT-Signing" in out
        assert "SHA-256 (SPKI DER)" in out
        assert "Done." in out

    def test_idempotent_when_key_already_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pem = _gen_public_key_pem()
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: False)  # already existed
        monkeypatch.setattr(tpm_signer, "export_public_key_pem", lambda name: pem)

        rc = psk.provision("BlarAI-PA-JWT-Signing", tmp_path / "pa_public.pem")

        assert rc == 0
        assert "already existed" in capsys.readouterr().out

    def test_fail_closed_without_tpm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _must_not_run(*_a: object, **_k: object) -> object:
            raise AssertionError("ceremony must not touch the TPM when unavailable")

        monkeypatch.setattr(tpm_signer, "is_available", lambda: False)
        monkeypatch.setattr(tpm_signer, "ensure_key", _must_not_run)
        monkeypatch.setattr(tpm_signer, "export_public_key_pem", _must_not_run)

        out = tmp_path / "certs" / "pa_public.pem"
        rc = psk.provision("BlarAI-PA-JWT-Signing", out)

        assert rc == 1
        assert not out.exists()  # nothing written on the fail-closed path

    def test_main_default_key_name_is_the_constant(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        seen: dict[str, str] = {}
        pem = _gen_public_key_pem()
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(
            tpm_signer, "ensure_key", lambda name: seen.setdefault("key", name) and False
        )
        monkeypatch.setattr(tpm_signer, "export_public_key_pem", lambda name: pem)

        rc = psk.main(["--out", str(tmp_path / "pa_public.pem")])

        assert rc == 0
        assert seen["key"] == PA_JWT_TPM_KEY_NAME

    def test_main_maps_tpm_unavailable_to_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _raise(name: str) -> bool:
            raise tpm_signer.TpmUnavailable("no provider")

        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "ensure_key", _raise)

        rc = psk.main(["--out", str(tmp_path / "pa_public.pem")])

        assert rc == 1


# ═══════════════════════════════════════════════════════════════════════════
# On-chip: real platform TPM 2.0 (deselected by default; run with -m slow)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.slow
class TestProvisionCeremonyOnChip:
    """The ceremony on the real chip: writes a usable, correct trust anchor.

    Run with: ``pytest shared/tests/test_provision_signing_key.py -m slow``.
    Skipped if no TPM is present. Uses a throwaway key (never the production
    signing key), provisioned and deleted within the test.
    """

    _KEY = "BlarAI-PA-JWT-Ceremony-PytestHW"

    @pytest.fixture(autouse=True)
    def _require_tpm(self):
        if not tpm_signer.is_available():
            pytest.skip("No platform TPM available")
        yield
        try:
            tpm_signer.delete_key(self._KEY)
        except Exception:
            pass

    def test_ceremony_writes_usable_trust_anchor(self, tmp_path: Path) -> None:
        out = tmp_path / "certs" / "pa_public.pem"

        rc = psk.provision(self._KEY, out)
        assert rc == 0
        assert out.exists()

        # The written file is a real P-256 public key the production validator loads.
        pem = out.read_bytes()
        public_key = load_pem_public_key(pem)
        assert isinstance(public_key, ec.EllipticCurvePublicKey)
        assert AgenticJWTValidator.from_public_key_file(out) is not None

        # The exported public half corresponds to the non-exportable TPM private
        # half: a TPM signature verifies under the PEM the ceremony wrote.
        message = b"blarai-ceremony-key-correspondence"
        raw = tpm_signer.sign(self._KEY, message)  # raw r||s over SHA-256(message)
        assert len(raw) == 64
        der_sig = asym_utils.encode_dss_signature(
            int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
        )
        public_key.verify(der_sig, message, ec.ECDSA(hashes.SHA256()))  # raises if wrong key
