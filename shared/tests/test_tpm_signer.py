"""Tests for the TPM 2.0 signing primitive (shared/security/tpm_signer.py, ADR-018).

Two tiers:
  - Fast unit tests (default suite): off-Windows Fail-Closed behaviour, verified by
    monkeypatching the platform — run anywhere.
  - Hardware round-trip (``@pytest.mark.slow``, deselected by default like the GPU
    tests): exercises the real platform TPM 2.0 on this host. Run with
    ``pytest shared/tests/test_tpm_signer.py -m slow``. Skipped if no TPM is present.

The hardware test asserts the security-critical property directly: the key is
**non-exportable** (a private-key export attempt is refused by the provider),
greedily proving rather than assuming the trust-root guarantee.
"""

from __future__ import annotations

import pytest

from shared.security import tpm_signer


# --------------------------------------------------------------------------
# Fast unit tests — Fail-Closed off-Windows (run on every platform).
# --------------------------------------------------------------------------
class TestFailClosedOffWindows:
    def test_is_available_false_off_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "_API", None)
        monkeypatch.setattr(tpm_signer.sys, "platform", "linux")
        assert tpm_signer.is_available() is False

    def test_operations_raise_off_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "_API", None)
        monkeypatch.setattr(tpm_signer.sys, "platform", "linux")
        with pytest.raises(tpm_signer.TpmUnavailable):
            tpm_signer.ensure_key("whatever")
        with pytest.raises(tpm_signer.TpmUnavailable):
            tpm_signer.sign("whatever", b"data")
        with pytest.raises(tpm_signer.TpmUnavailable):
            tpm_signer.verify("whatever", b"data", b"sig")

    def test_exceptions_are_runtimeerror(self) -> None:
        assert issubclass(tpm_signer.TpmUnavailable, RuntimeError)
        assert issubclass(tpm_signer.TpmSigningError, RuntimeError)


# --------------------------------------------------------------------------
# Hardware round-trip — real platform TPM 2.0 (deselected by default).
# --------------------------------------------------------------------------
_HW_KEY = "BlarAI-TPMSigner-PytestHW"


@pytest.mark.slow
class TestTpmHardwareRoundTrip:
    @pytest.fixture(autouse=True)
    def _require_tpm(self):
        if not tpm_signer.is_available():
            pytest.skip("no TPM 2.0 / CNG Platform Crypto Provider on this host")
        # clean any leftover from a previous interrupted run
        if tpm_signer.key_exists(_HW_KEY):
            tpm_signer.delete_key(_HW_KEY)
        yield
        if tpm_signer.key_exists(_HW_KEY):
            tpm_signer.delete_key(_HW_KEY)

    def test_provision_sign_verify_tamper_export_delete(self) -> None:
        # provision (idempotent)
        assert tpm_signer.ensure_key(_HW_KEY) is True
        assert tpm_signer.ensure_key(_HW_KEY) is False  # second call: already exists
        assert tpm_signer.key_exists(_HW_KEY) is True

        data = b"BlarAI weight-integrity manifest bytes v1.0.0"
        sig = tpm_signer.sign(_HW_KEY, data)
        assert isinstance(sig, bytes) and len(sig) == 64  # ECDSA P-256 raw r||s

        assert tpm_signer.verify(_HW_KEY, data, sig) is True
        assert tpm_signer.verify(_HW_KEY, data + b"!", sig) is False  # tamper rejected
        assert tpm_signer.verify(_HW_KEY, data, bytes(len(sig))) is False  # zeroed sig

        pub = tpm_signer.export_public_key(_HW_KEY)
        assert isinstance(pub, bytes) and len(pub) > 0  # public export allowed

        tpm_signer.delete_key(_HW_KEY)
        assert tpm_signer.key_exists(_HW_KEY) is False

    def test_private_key_is_non_exportable(self) -> None:
        """The security-critical guarantee: the private key cannot be exported."""
        import ctypes

        tpm_signer.ensure_key(_HW_KEY)
        ctypes_mod, d = tpm_signer._api()
        h = tpm_signer._open_provider(ctypes_mod, d)
        try:
            hk = tpm_signer._open_key(ctypes_mod, d, h, _HW_KEY)
            try:
                cb = ctypes.c_ulong(0)
                # Attempt a PRIVATE key export (ECCPRIVATEBLOB) — must be refused.
                status = tpm_signer._u32(
                    d.NCryptExportKey(hk, None, "ECCPRIVATEBLOB", None, None, 0, ctypes.byref(cb), 0)
                )
                assert status != tpm_signer._ERROR_SUCCESS, (
                    "private key export unexpectedly SUCCEEDED — key is exportable!"
                )
            finally:
                d.NCryptFreeObject(hk)
        finally:
            d.NCryptFreeObject(h)
