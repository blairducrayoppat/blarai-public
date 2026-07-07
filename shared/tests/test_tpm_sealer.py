"""Tests for the TPM 2.0 key-sealing primitive (shared/security/tpm_sealer.py).

Two tiers:
  - Default-suite tests (software stub, no chip): round-trip, tamper detection,
    oversized input, Protocol conformance.  Run anywhere; deselected-marker-free.
  - Real-TPM tests (``@pytest.mark.slow``): exercises the actual platform TPM 2.0.
    Run with ``pytest shared/tests/test_tpm_sealer.py -m slow``.  Skipped on
    machines without a CNG Platform Crypto Provider.

The hardware tests assert the security-critical property directly: the key is
**non-exportable** (a private-key export attempt is refused by the provider),
proving the trust-root guarantee rather than assuming it.

Marker note: the sealing tests use ``@pytest.mark.slow`` for consistency with
``test_tpm_signer.py`` — both are deselected by the default ``addopts``
``-m 'not slow'``.
"""

from __future__ import annotations

import pytest

from shared.security import tpm_sealer
from shared.security.tpm_sealer import (
    SoftwareSealer,
    Sealer,
    TpmSealingError,
    TpmUnavailable,
    _RSA2048_OAEP_SHA256_MAX_PLAINTEXT,
)


# ---------------------------------------------------------------------------
# Default-suite tests — SoftwareSealer (no chip required)
# ---------------------------------------------------------------------------


class TestSoftwareSealerRoundTrip:
    """Seal / unseal cycle against the software stub."""

    def test_dek_round_trip_32_bytes(self) -> None:
        """A 32-byte AES-256 DEK survives a seal → unseal round-trip."""
        sealer = SoftwareSealer()
        dek = b"\xab" * 32
        blob = sealer.seal(dek)
        assert sealer.unseal(blob) == dek

    def test_round_trip_arbitrary_payload(self) -> None:
        """Any payload up to the OAEP limit round-trips correctly."""
        sealer = SoftwareSealer()
        payload = bytes(range(64))
        assert sealer.unseal(sealer.seal(payload)) == payload

    def test_fresh_nonce_two_seals_differ(self) -> None:
        """Sealing the same plaintext twice yields DIFFERENT blobs (fresh nonce)."""
        sealer = SoftwareSealer()
        dek = b"\x00" * 32
        blob1 = sealer.seal(dek)
        blob2 = sealer.seal(dek)
        assert blob1 != blob2, (
            "seal() produced identical blobs for the same input — nonce is not fresh"
        )

    def test_protocol_conformance(self) -> None:
        """SoftwareSealer satisfies the Sealer Protocol at runtime."""
        assert isinstance(SoftwareSealer(), Sealer)


class TestSoftwareSealerTamperDetection:
    """Tampered blobs must fail closed — never return corrupted key material."""

    def test_bit_flip_in_ciphertext_raises(self) -> None:
        """A single-byte mutation in the ciphertext body triggers authentication failure."""
        sealer = SoftwareSealer()
        blob = bytearray(sealer.seal(b"\x42" * 32))
        # Flip a byte in the ciphertext region (after the 12-byte nonce).
        blob[13] ^= 0xFF
        with pytest.raises(TpmSealingError):
            sealer.unseal(bytes(blob))

    def test_nonce_mutation_raises(self) -> None:
        """Mutating the nonce makes the tag invalid."""
        sealer = SoftwareSealer()
        blob = bytearray(sealer.seal(b"\x99" * 16))
        blob[5] ^= 0x01
        with pytest.raises(TpmSealingError):
            sealer.unseal(bytes(blob))

    def test_truncated_blob_raises(self) -> None:
        """A blob shorter than nonce+tag (28 bytes) is rejected immediately."""
        sealer = SoftwareSealer()
        blob = sealer.seal(b"\x55" * 8)
        with pytest.raises(TpmSealingError):
            sealer.unseal(blob[:10])

    def test_empty_blob_raises(self) -> None:
        sealer = SoftwareSealer()
        with pytest.raises(TpmSealingError):
            sealer.unseal(b"")


class TestOversizedInput:
    """Inputs exceeding the RSA-OAEP limit must be rejected, not silently truncated."""

    def test_oversized_seal_raises(self) -> None:
        """seal() with payload > 190 bytes raises TpmSealingError."""
        sealer = SoftwareSealer()
        oversized = b"\x00" * (_RSA2048_OAEP_SHA256_MAX_PLAINTEXT + 1)
        with pytest.raises(TpmSealingError, match="too large"):
            sealer.seal(oversized)

    def test_exactly_at_limit_accepted(self) -> None:
        """A payload of exactly 190 bytes is accepted (at the boundary, not over it)."""
        sealer = SoftwareSealer()
        at_limit = b"\x00" * _RSA2048_OAEP_SHA256_MAX_PLAINTEXT
        blob = sealer.seal(at_limit)
        assert sealer.unseal(blob) == at_limit

    def test_limit_constant_value(self) -> None:
        """The OAEP limit constant has the expected value for RSA-2048 / SHA-256."""
        assert _RSA2048_OAEP_SHA256_MAX_PLAINTEXT == 190


class TestExceptionHierarchy:
    """Error classes must be RuntimeError subclasses (mirrors tpm_signer)."""

    def test_tpm_unavailable_is_runtime_error(self) -> None:
        assert issubclass(TpmUnavailable, RuntimeError)

    def test_tpm_sealing_error_is_runtime_error(self) -> None:
        assert issubclass(TpmSealingError, RuntimeError)


class TestOffWindowsFailClosed:
    """Off-Windows: every TPM operation raises TpmUnavailable (Fail-Closed)."""

    def test_is_available_false_off_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "_API", None)
        monkeypatch.setattr(tpm_sealer.sys, "platform", "linux")
        assert tpm_sealer.is_available() is False

    def test_ensure_key_raises_off_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "_API", None)
        monkeypatch.setattr(tpm_sealer.sys, "platform", "linux")
        with pytest.raises(TpmUnavailable):
            tpm_sealer.ensure_key("any-key")

    def test_tpm_sealer_constructor_raises_off_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "_API", None)
        monkeypatch.setattr(tpm_sealer.sys, "platform", "linux")
        with pytest.raises(TpmUnavailable):
            tpm_sealer.TpmSealer("any-key")


# ---------------------------------------------------------------------------
# Real-TPM hardware tests (deselected by default; requires platform TPM 2.0)
# ---------------------------------------------------------------------------

_HW_KEY = "BlarAI-TPMSealer-PytestHW"


@pytest.mark.slow
class TestTpmSealerHardwareRoundTrip:
    """Real-chip: provision, seal, unseal, verify non-exportability, delete."""

    @pytest.fixture(autouse=True)
    def _require_tpm(self) -> None:
        if not tpm_sealer.is_available():
            pytest.skip("no TPM 2.0 / CNG Platform Crypto Provider on this host")
        # Clean any leftover from a previous interrupted run.
        if tpm_sealer.key_exists(_HW_KEY):
            tpm_sealer.delete_key(_HW_KEY)
        yield
        if tpm_sealer.key_exists(_HW_KEY):
            tpm_sealer.delete_key(_HW_KEY)

    def test_ensure_key_idempotent(self) -> None:
        """ensure_key() returns True the first call, False on subsequent calls."""
        assert tpm_sealer.ensure_key(_HW_KEY) is True
        assert tpm_sealer.ensure_key(_HW_KEY) is False  # already exists
        assert tpm_sealer.key_exists(_HW_KEY) is True

    def test_real_chip_seal_unseal_round_trip(self) -> None:
        """A 32-byte DEK sealed on the real TPM unseals to the original value."""
        tpm_sealer.ensure_key(_HW_KEY)
        sealer = tpm_sealer.TpmSealer(_HW_KEY, auto_provision=False)
        dek = bytes(range(32))
        blob = sealer.seal(dek)
        assert isinstance(blob, bytes)
        assert len(blob) == 256, f"RSA-2048 ciphertext should be 256 bytes, got {len(blob)}"
        assert sealer.unseal(blob) == dek

    def test_private_key_is_non_exportable(self) -> None:
        """The security-critical guarantee: the private key cannot be exported from the TPM."""
        import ctypes

        tpm_sealer.ensure_key(_HW_KEY)
        ctypes_mod, d = tpm_sealer._api()
        h = tpm_sealer._open_provider(ctypes_mod, d)
        try:
            hk = tpm_sealer._open_key(ctypes_mod, d, h, _HW_KEY)
            try:
                cb = ctypes.c_ulong(0)
                # Attempt a PRIVATE key export (RSAFULLPRIVATEBLOB) — must be refused.
                status = tpm_sealer._u32(
                    d.NCryptExportKey(hk, None, "RSAFULLPRIVATEBLOB", None, None, 0, ctypes.byref(cb), 0)
                )
                assert status != tpm_sealer._ERROR_SUCCESS, (
                    "private key export unexpectedly SUCCEEDED — RSA seal key is exportable!"
                )
            finally:
                d.NCryptFreeObject(hk)
        finally:
            d.NCryptFreeObject(h)

    def test_tpm_sealer_satisfies_sealer_protocol(self) -> None:
        """TpmSealer satisfies the Sealer Protocol at runtime."""
        tpm_sealer.ensure_key(_HW_KEY)
        sealer = tpm_sealer.TpmSealer(_HW_KEY, auto_provision=False)
        assert isinstance(sealer, Sealer)

    def test_off_windows_raises_tpm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On any non-win32 platform, TpmSealer construction raises TpmUnavailable."""
        monkeypatch.setattr(tpm_sealer, "_API", None)
        monkeypatch.setattr(tpm_sealer.sys, "platform", "linux")
        with pytest.raises(TpmUnavailable):
            tpm_sealer.TpmSealer("some-key")
