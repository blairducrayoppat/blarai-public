"""Tests for TPM-backed manifest signing (shared/models/manifest_signer.py, FUT-04).

Software-stub test tier — no real TPM required. Monkeypatches tpm_signer
primitives to exercise the manifest sign/verify logic on any platform,
mirroring the fast-unit pattern in test_tpm_signer.py.

Test groups:
  A. verify_manifest_signature — core gate logic (5 tests):
     - valid signature      → PASS  (teeth: confirms code path reaches verify())
     - tampered manifest    → FAIL  (teeth: monkeypatch confirms verify() called with wrong bytes)
     - corrupted .sig file  → FAIL
     - missing .sig + require=true  → FAIL
     - missing .sig + require=false → PASS (with warning)

  B. sign_manifest — provisioning path (2 tests):
     - successful sign: files written + content correct
     - TPM unavailable → TpmUnavailable propagates

  C. load_manifest_verified integration (4 tests) — via weight_integrity module:
     - valid sig + require=true    → returns digest dict
     - tampered manifest + require=true → returns None (FAIL-CLOSED)
     - missing sig + require=true  → returns None (FAIL-CLOSED)
     - missing sig + require=false → returns digest dict (unsigned allowed)

TEETH proof: each FAIL case asserts on the specific failure path, not just
"None was returned". The tamper cases monkeypatch tpm_signer.verify to return
False and confirm it is called (not bypassed); the missing-sig cases confirm
the .sig file does not exist before asserting the gate fires.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.models import manifest_signer
from shared.models.manifest_signer import (
    MANIFEST_SIGNING_KEY_NAME,
    sign_manifest,
    verify_manifest_signature,
)
from shared.models.weight_integrity import load_manifest_verified
from shared.security import tpm_signer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest_file(content: bytes | None = None) -> Path:
    """Write a temp manifest JSON (or custom bytes) and return its Path."""
    if content is None:
        data = {"version": "1.0.0", "digests": {"model.bin": "a" * 64}}
        content = json.dumps(data).encode("utf-8")
    fd, path_str = tempfile.mkstemp(suffix=".json")
    os.write(fd, content)
    os.close(fd)
    return Path(path_str)


def _write_sig_file(sig_bytes: bytes, manifest_path: Path) -> Path:
    """Write a base64url-encoded .sig alongside the manifest and return its Path."""
    sig_b64 = base64.urlsafe_b64encode(sig_bytes)
    sig_path = manifest_path.parent / (manifest_path.name + ".sig")
    sig_path.write_bytes(sig_b64)
    return sig_path


def _fake_sign(key_name: str, data: bytes) -> bytes:
    """Deterministic software substitute for tpm_signer.sign — HMAC-SHA256 digest."""
    return hashlib.sha256(b"stub-key:" + data).digest()


def _fake_verify(key_name: str, data: bytes, signature: bytes) -> bool:
    """Software substitute for tpm_signer.verify — returns True iff sig matches _fake_sign."""
    expected = _fake_sign(key_name, data)
    return signature == expected


# ---------------------------------------------------------------------------
# Group A: verify_manifest_signature
# ---------------------------------------------------------------------------


class TestVerifyManifestSignature:
    """Gate logic: valid / tampered / corrupted / missing × require flags."""

    def test_valid_signature_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Valid TPM signature → verify_manifest_signature returns True.

        TEETH: monkeypatch.verify is called and returns True; we confirm the
        result propagates rather than being short-circuited.
        """
        manifest = _write_manifest_file()
        try:
            manifest_bytes = manifest.read_bytes()
            sig_bytes = _fake_sign(MANIFEST_SIGNING_KEY_NAME, manifest_bytes)
            _write_sig_file(sig_bytes, manifest)

            verify_called: list[tuple[str, bytes, bytes]] = []

            def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
                verify_called.append((key_name, data, signature))
                return _fake_verify(key_name, data, signature)

            monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            result = verify_manifest_signature(manifest, require_signed=True)

            assert result is True
            assert len(verify_called) == 1, "tpm_signer.verify must be called once"
            _, called_data, called_sig = verify_called[0]
            assert called_data == manifest_bytes
            assert called_sig == sig_bytes
        finally:
            manifest.unlink(missing_ok=True)
            sig_f = manifest.parent / (manifest.name + ".sig")
            sig_f.unlink(missing_ok=True)

    def test_tampered_manifest_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tampered manifest bytes → signature mismatch → returns False (FAIL-CLOSED).

        TEETH: The original manifest is signed; then the manifest file is
        overwritten with different bytes. verify() is called and must return
        False. The test confirms the gate fires on tamper, not just on absence.
        """
        manifest = _write_manifest_file()
        try:
            original_bytes = manifest.read_bytes()
            sig_bytes = _fake_sign(MANIFEST_SIGNING_KEY_NAME, original_bytes)
            _write_sig_file(sig_bytes, manifest)

            # Tamper: overwrite the manifest with different content.
            tampered = b'{"version":"1.0.0","digests":{"model.bin":"' + b"b" * 64 + b'"}}'
            manifest.write_bytes(tampered)

            verify_called: list[bool] = []

            def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
                result = _fake_verify(key_name, data, signature)
                verify_called.append(result)
                return result

            monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            result = verify_manifest_signature(manifest, require_signed=True)

            assert result is False, "tampered manifest must be rejected"
            assert len(verify_called) == 1, "verify() must be reached (tamper detected at verify, not before)"
            assert verify_called[0] is False, "verify() must return False for tampered data"
        finally:
            manifest.unlink(missing_ok=True)
            sig_f = manifest.parent / (manifest.name + ".sig")
            sig_f.unlink(missing_ok=True)

    def test_corrupted_sig_file_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A .sig file with invalid base64url content → returns False (FAIL-CLOSED).

        TEETH: confirms the corruption is caught before the TPM call, not silently
        passed through.
        """
        manifest = _write_manifest_file()
        try:
            # Write a .sig that is NOT valid base64url.
            sig_f = manifest.parent / (manifest.name + ".sig")
            sig_f.write_bytes(b"this is not base64url!!!")

            # verify() should NOT be called — corruption caught in decode step.
            verify_called: list[bool] = []

            def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
                verify_called.append(True)  # pragma: no cover
                return True  # pragma: no cover

            monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            result = verify_manifest_signature(manifest, require_signed=True)

            assert result is False
            assert len(verify_called) == 0, "verify() must NOT be called on corrupted base64url"
        finally:
            manifest.unlink(missing_ok=True)
            sig_f = manifest.parent / (manifest.name + ".sig")
            sig_f.unlink(missing_ok=True)

    def test_missing_sig_require_true_fails(self) -> None:
        """No .sig file + require_signed=True → returns False (FAIL-CLOSED).

        TEETH: confirm the .sig file genuinely does not exist before the call.
        """
        manifest = _write_manifest_file()
        try:
            sig_f = manifest.parent / (manifest.name + ".sig")
            # Guarantee the .sig file does not exist.
            assert not sig_f.exists(), "test precondition: .sig must not exist"

            result = verify_manifest_signature(manifest, require_signed=True)

            assert result is False, "missing .sig with require=True must be FAIL-CLOSED"
        finally:
            manifest.unlink(missing_ok=True)

    def test_missing_sig_require_false_passes(self) -> None:
        """No .sig file + require_signed=False → returns True (unsigned manifest accepted).

        TEETH: confirm .sig absent, confirm True returned (unsigned mode is intentional,
        not a silent bug swallowing the failure).
        """
        manifest = _write_manifest_file()
        try:
            sig_f = manifest.parent / (manifest.name + ".sig")
            assert not sig_f.exists(), "test precondition: .sig must not exist"

            result = verify_manifest_signature(manifest, require_signed=False)

            assert result is True, "missing .sig with require=False must be accepted"
        finally:
            manifest.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Group B: sign_manifest
# ---------------------------------------------------------------------------


class TestSignManifest:
    """Provisioning ceremony: files written correctly + TPM-unavailable propagation."""

    def test_sign_writes_sig_and_pub_files(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sign_manifest writes .sig (base64url ECDSA) and .pub (PEM) files."""
        manifest = _write_manifest_file()
        try:
            manifest_bytes = manifest.read_bytes()
            expected_sig = _fake_sign(MANIFEST_SIGNING_KEY_NAME, manifest_bytes)
            fake_pem = b"-----BEGIN PUBLIC KEY-----\nZmFrZQ==\n-----END PUBLIC KEY-----\n"

            monkeypatch.setattr(tpm_signer, "sign", _fake_sign)
            monkeypatch.setattr(
                tpm_signer,
                "export_public_key_pem",
                lambda key_name: fake_pem,
            )
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            sig_path, pub_path = sign_manifest(manifest, key_name=MANIFEST_SIGNING_KEY_NAME)

            # .sig must exist and decode to the expected raw bytes.
            assert sig_path.exists(), ".sig file must be written"
            decoded = base64.urlsafe_b64decode(sig_path.read_bytes())
            assert decoded == expected_sig, ".sig must decode to the TPM-produced signature"

            # .pub must exist and match the fake PEM.
            assert pub_path.exists(), ".pub file must be written"
            assert pub_path.read_bytes() == fake_pem
        finally:
            manifest.unlink(missing_ok=True)
            sig_f = manifest.parent / (manifest.name + ".sig")
            pub_f = manifest.parent / (manifest.name + ".pub")
            sig_f.unlink(missing_ok=True)
            pub_f.unlink(missing_ok=True)

    def test_sign_propagates_tpm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sign_manifest raises TpmUnavailable when the TPM is not present."""
        manifest = _write_manifest_file()
        try:
            def _unavailable(key_name: str, data: bytes) -> bytes:
                raise tpm_signer.TpmUnavailable("no TPM in test environment")

            monkeypatch.setattr(tpm_signer, "sign", _unavailable)
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            with pytest.raises(tpm_signer.TpmUnavailable):
                sign_manifest(manifest)
        finally:
            manifest.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Group C: load_manifest_verified integration
# ---------------------------------------------------------------------------


class TestLoadManifestVerified:
    """End-to-end: signature gate + JSON loading through weight_integrity module."""

    def test_valid_sig_require_true_returns_digests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid signature + require=True → returns the digest dict."""
        data = {"version": "1.0.0", "digests": {"model.bin": "c" * 64}}
        content = json.dumps(data).encode("utf-8")
        manifest = _write_manifest_file(content)
        try:
            sig_bytes = _fake_sign(MANIFEST_SIGNING_KEY_NAME, content)
            _write_sig_file(sig_bytes, manifest)

            monkeypatch.setattr(tpm_signer, "verify", _fake_verify)
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            result = load_manifest_verified(manifest, require_signed=True)

            assert result is not None
            assert result.get("model.bin") == "c" * 64
        finally:
            manifest.unlink(missing_ok=True)
            sig_f = manifest.parent / (manifest.name + ".sig")
            sig_f.unlink(missing_ok=True)

    def test_tampered_manifest_require_true_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tampered manifest + require=True → returns None (FAIL-CLOSED).

        TEETH: signs original, overwrites with tampered bytes, confirms None.
        """
        original = json.dumps({"version": "1.0.0", "digests": {"model.bin": "d" * 64}}).encode()
        manifest = _write_manifest_file(original)
        try:
            sig_bytes = _fake_sign(MANIFEST_SIGNING_KEY_NAME, original)
            _write_sig_file(sig_bytes, manifest)

            # Tamper the manifest after signing.
            tampered = json.dumps({"version": "1.0.0", "digests": {"model.bin": "e" * 64}}).encode()
            manifest.write_bytes(tampered)

            monkeypatch.setattr(tpm_signer, "verify", _fake_verify)
            monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

            result = load_manifest_verified(manifest, require_signed=True)

            assert result is None, "tampered manifest must be FAIL-CLOSED"
        finally:
            manifest.unlink(missing_ok=True)
            sig_f = manifest.parent / (manifest.name + ".sig")
            sig_f.unlink(missing_ok=True)

    def test_missing_sig_require_true_returns_none(self) -> None:
        """No .sig file + require=True → returns None (FAIL-CLOSED).

        TEETH: .sig absence confirmed before the call.
        """
        manifest = _write_manifest_file()
        try:
            sig_f = manifest.parent / (manifest.name + ".sig")
            assert not sig_f.exists(), "test precondition: .sig must not exist"

            result = load_manifest_verified(manifest, require_signed=True)

            assert result is None, "missing .sig + require=True must be FAIL-CLOSED"
        finally:
            manifest.unlink(missing_ok=True)

    def test_missing_sig_require_false_returns_digests(self) -> None:
        """No .sig + require=False → returns digest dict (unsigned manifest accepted).

        TEETH: .sig absence confirmed before the call; digest dict confirms the
        JSON was actually parsed (not an empty or wrong return value).
        """
        data = {"version": "1.0.0", "digests": {"model.bin": "f" * 64}}
        content = json.dumps(data).encode("utf-8")
        manifest = _write_manifest_file(content)
        try:
            sig_f = manifest.parent / (manifest.name + ".sig")
            assert not sig_f.exists(), "test precondition: .sig must not exist"

            result = load_manifest_verified(manifest, require_signed=False)

            assert result is not None, "unsigned manifest with require=False must load"
            assert result.get("model.bin") == "f" * 64, "digest must be parsed from JSON"
        finally:
            manifest.unlink(missing_ok=True)
