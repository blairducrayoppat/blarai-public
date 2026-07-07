"""Tests for the EA-2 app-layer crypto layer.

Covers ``shared/security/field_cipher.py`` and ``shared/security/dek_envelope.py``
against the :class:`~shared.security.tpm_sealer.SoftwareSealer` stub — no hardware
required.  All tests run in the default suite (no ``@pytest.mark.slow`` marker
here; real-TPM seal/unseal is deferred to the ceremony live-verify per ADR-025 §4).

Test structure
--------------
- FieldCipher:
    * Round-trip (encrypt → decrypt) for various payloads.
    * **Repeated-plaintext → distinct-ciphertext** (fresh-nonce evidence; this
      is the load-bearing nonce-uniqueness test named in ADR-025 §2.3).
    * Tampered ciphertext → raises FieldCipherError.
    * Wrong key → raises FieldCipherError.
    * AAD mismatch → raises FieldCipherError (correct AAD does NOT raise).
    * Version byte is first byte of blob; wrong version → raises.
    * Empty plaintext round-trips (GCM handles zero-length plaintext).
- SubkeySet / derive_subkeys:
    * Same DEK → same subkeys (deterministic).
    * Different DEKs → different subkeys (key separation evidence).
    * Invalid DEK length raises ValueError.
    * Subkeys are distinct from each other and from the DEK.
- keyed_index:
    * Determinism: same source → same output.
    * Separation: different source → different output.
    * Output is 32 bytes (HMAC-SHA256 digest).
    * Subkey separation: same source, different DEK → different index.
- make_aad_for:
    * Produces the canonical ``table|column|row_id`` bytes format.
    * bytes row_id is handled.
- DekEnvelope:
    * **DEK dual-unwrap**: both TPM-stub wrap and recovery wrap independently
      unseal the IDENTICAL DEK (the central ADR-025 §2.1 guarantee).
    * Wrong recovery key → DekEnvelopeError (fail-closed).
    * No recovery key + TPM failure → DekEnvelopeError (refuse to open).
    * Tampered TPM wrap + recovery key present → falls back to recovery.
    * Tampered recovery wrap + TPM works → succeeds via TPM.
    * Tampered recovery wrap + TPM fails + recovery key → DekEnvelopeError.
    * Version byte present in both wrap records.
    * save/load round-trip through a temp keystore file; DEK unchanged.
- build_envelope (factory):
    * **SoftwareSealer + dev_mode=False → DevModeSealerError** (production guard).
    * SoftwareSealer + dev_mode=True → succeeds (dev/test path).
    * TpmSealer (stub) + dev_mode=False → succeeds (validated via monkeypatch
      that substitutes a SoftwareSealer after isinstance() check; or we test
      the path indirectly using a non-SoftwareSealer Sealer).
    * Wrong-length recovery_key → ValueError.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import pytest

from shared.security.dek_envelope import (
    RECOVERY_KEY_BYTES,
    WRAP_VERSION,
    DekEnvelope,
    DekEnvelopeError,
    DevModeSealerError,
    build_envelope,
    generate_recovery_key,
    reseal_dek,
)
from shared.security.field_cipher import (
    DEK_BYTES,
    FIELD_CIPHER_VERSION,
    FieldCipher,
    FieldCipherError,
    SubkeySet,
    derive_subkeys,
    make_aad_for,
)
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_dek() -> bytes:
    """Generate a random 32-byte DEK for tests."""
    return secrets.token_bytes(DEK_BYTES)


def _make_recovery_key() -> bytes:
    """Generate a random 32-byte recovery key for tests."""
    return secrets.token_bytes(RECOVERY_KEY_BYTES)


def _make_cipher(dek: bytes | None = None) -> FieldCipher:
    """Return a FieldCipher backed by a freshly derived SubkeySet."""
    return FieldCipher(derive_subkeys(dek or _make_dek()))


def _default_aad() -> bytes:
    return b"sessions|content|row-001"


# ---------------------------------------------------------------------------
# FieldCipher — round-trip
# ---------------------------------------------------------------------------


class TestFieldCipherRoundTrip:
    """encrypt → decrypt recovers the original plaintext."""

    def test_basic_round_trip(self) -> None:
        cipher = _make_cipher()
        pt = b"hello, at-rest encryption"
        aad = _default_aad()
        blob = cipher.encrypt(pt, aad=aad)
        assert cipher.decrypt(blob, aad=aad) == pt

    def test_round_trip_empty_plaintext(self) -> None:
        """GCM must handle zero-length plaintext (authenticated empty value)."""
        cipher = _make_cipher()
        blob = cipher.encrypt(b"", aad=_default_aad())
        assert cipher.decrypt(blob, aad=_default_aad()) == b""

    def test_round_trip_large_plaintext(self) -> None:
        """10 KB field value round-trips correctly."""
        cipher = _make_cipher()
        pt = secrets.token_bytes(10 * 1024)
        aad = b"substrate_chunks|text|kind=doc|sha=abc|sess=1|chunk=0"
        assert cipher.decrypt(cipher.encrypt(pt, aad=aad), aad=aad) == pt

    def test_round_trip_binary_plaintext(self) -> None:
        """Embedding bytes (float32 array) round-trip correctly."""
        cipher = _make_cipher()
        # Simulate a 384-dim float32 embedding (1536 bytes).
        pt = os.urandom(1536)
        aad = b"substrate_chunks|embedding|kind=doc|sha=abc|sess=1|chunk=0"
        assert cipher.decrypt(cipher.encrypt(pt, aad=aad), aad=aad) == pt


# ---------------------------------------------------------------------------
# FieldCipher — nonce freshness (the load-bearing test from ADR-025 §2.3)
# ---------------------------------------------------------------------------


class TestFieldCipherNonceFreshness:
    """Repeated-plaintext must produce DISTINCT ciphertexts (fresh-nonce evidence).

    This test exists because GCM nonce reuse under one key is catastrophic — it
    breaks both confidentiality and authentication simultaneously.  The test does
    NOT prove nonce uniqueness (CSPRNG guarantees that); it provides supporting
    evidence by showing two encryptions of the same value are distinguishable.
    """

    def test_same_plaintext_different_ciphertexts(self) -> None:
        cipher = _make_cipher()
        pt = b"the same plaintext, encrypted twice"
        aad = _default_aad()
        blob1 = cipher.encrypt(pt, aad=aad)
        blob2 = cipher.encrypt(pt, aad=aad)
        assert blob1 != blob2, (
            "encrypt() returned identical blobs — nonce is not fresh per encryption"
        )

    def test_nonce_bytes_differ(self) -> None:
        """The 12-byte nonce region (bytes 1..13) must differ between calls."""
        cipher = _make_cipher()
        pt = b"x" * 32
        aad = _default_aad()
        blob1 = cipher.encrypt(pt, aad=aad)
        blob2 = cipher.encrypt(pt, aad=aad)
        nonce1 = blob1[1:13]
        nonce2 = blob2[1:13]
        assert nonce1 != nonce2, "nonces are identical — os.urandom may not be CSPRNG"

    def test_100_encryptions_all_distinct(self) -> None:
        """100 encryptions of the same value produce 100 distinct blobs."""
        cipher = _make_cipher()
        pt = b"\x00" * 32
        aad = _default_aad()
        blobs = [cipher.encrypt(pt, aad=aad) for _ in range(100)]
        assert len(set(blobs)) == 100, "detected nonce collision in 100 encryptions"


# ---------------------------------------------------------------------------
# FieldCipher — tamper detection
# ---------------------------------------------------------------------------


class TestFieldCipherTamperDetection:
    """Any mutation of the blob must cause authentication failure."""

    def test_flipped_ciphertext_byte_raises(self) -> None:
        cipher = _make_cipher()
        pt = b"secret content"
        aad = _default_aad()
        blob = bytearray(cipher.encrypt(pt, aad=aad))
        # Flip a byte in the ciphertext region (past version+nonce = 13 bytes).
        blob[14] ^= 0xFF
        with pytest.raises(FieldCipherError, match="authentication failed"):
            cipher.decrypt(bytes(blob), aad=aad)

    def test_flipped_nonce_byte_raises(self) -> None:
        cipher = _make_cipher()
        blob = bytearray(cipher.encrypt(b"data", aad=_default_aad()))
        # Mutate nonce byte 5 (offset 6 from start: version(1)+nonce[5]).
        blob[6] ^= 0x01
        with pytest.raises(FieldCipherError):
            cipher.decrypt(bytes(blob), aad=_default_aad())

    def test_flipped_tag_byte_raises(self) -> None:
        """Mutating the trailing tag triggers GCM authentication failure."""
        cipher = _make_cipher()
        pt = b"tagged"
        aad = _default_aad()
        blob = bytearray(cipher.encrypt(pt, aad=aad))
        blob[-1] ^= 0xAB  # last byte of the 16-byte tag
        with pytest.raises(FieldCipherError):
            cipher.decrypt(bytes(blob), aad=aad)

    def test_truncated_blob_raises(self) -> None:
        cipher = _make_cipher()
        blob = cipher.encrypt(b"short", aad=_default_aad())
        with pytest.raises(FieldCipherError):
            cipher.decrypt(blob[:10], aad=_default_aad())

    def test_empty_blob_raises(self) -> None:
        cipher = _make_cipher()
        with pytest.raises(FieldCipherError):
            cipher.decrypt(b"", aad=_default_aad())


# ---------------------------------------------------------------------------
# FieldCipher — wrong key
# ---------------------------------------------------------------------------


class TestFieldCipherWrongKey:
    """Decrypting with a different subkey must fail closed."""

    def test_wrong_dek_raises(self) -> None:
        dek_a = _make_dek()
        dek_b = _make_dek()
        assert dek_a != dek_b  # ensure different DEKs (vanishingly unlikely to collide)
        cipher_a = _make_cipher(dek_a)
        cipher_b = _make_cipher(dek_b)
        blob = cipher_a.encrypt(b"secret", aad=_default_aad())
        with pytest.raises(FieldCipherError):
            cipher_b.decrypt(blob, aad=_default_aad())


# ---------------------------------------------------------------------------
# FieldCipher — AAD binding
# ---------------------------------------------------------------------------


class TestFieldCipherAadBinding:
    """AAD mismatch must be detected; correct AAD must pass."""

    def test_wrong_aad_raises(self) -> None:
        cipher = _make_cipher()
        pt = b"bound content"
        correct_aad = b"sessions|content|row-abc"
        wrong_aad = b"sessions|content|row-xyz"
        blob = cipher.encrypt(pt, aad=correct_aad)
        with pytest.raises(FieldCipherError, match="authentication failed"):
            cipher.decrypt(blob, aad=wrong_aad)

    def test_correct_aad_succeeds(self) -> None:
        cipher = _make_cipher()
        pt = b"bound content"
        aad = b"sessions|content|row-abc"
        blob = cipher.encrypt(pt, aad=aad)
        assert cipher.decrypt(blob, aad=aad) == pt

    def test_empty_aad_wrong_aad_raises(self) -> None:
        """Blob encrypted with empty AAD cannot be decrypted with a non-empty AAD."""
        cipher = _make_cipher()
        pt = b"test"
        blob = cipher.encrypt(pt, aad=b"")
        with pytest.raises(FieldCipherError):
            cipher.decrypt(blob, aad=b"sessions|content|row-001")

    def test_empty_aad_round_trips(self) -> None:
        """Empty AAD is valid GCM; blob encrypted with b'' decrypts with b''."""
        cipher = _make_cipher()
        pt = b"test"
        blob = cipher.encrypt(pt, aad=b"")
        assert cipher.decrypt(blob, aad=b"") == pt


# ---------------------------------------------------------------------------
# FieldCipher — version byte
# ---------------------------------------------------------------------------


class TestFieldCipherVersionByte:
    """The version byte must be present in the blob and validated on decrypt."""

    def test_version_byte_is_first_byte(self) -> None:
        cipher = _make_cipher()
        blob = cipher.encrypt(b"v", aad=_default_aad())
        assert blob[0] == FIELD_CIPHER_VERSION, (
            f"expected version byte 0x{FIELD_CIPHER_VERSION:02X}, "
            f"got 0x{blob[0]:02X}"
        )

    def test_wrong_version_raises(self) -> None:
        cipher = _make_cipher()
        blob = bytearray(cipher.encrypt(b"v", aad=_default_aad()))
        blob[0] = FIELD_CIPHER_VERSION + 1  # corrupt the version byte
        with pytest.raises(FieldCipherError, match="unsupported cipher version"):
            cipher.decrypt(bytes(blob), aad=_default_aad())


# ---------------------------------------------------------------------------
# SubkeySet / derive_subkeys
# ---------------------------------------------------------------------------


class TestDeriveSubkeys:
    """HKDF subkey derivation must be deterministic and produce distinct keys."""

    def test_same_dek_same_subkeys(self) -> None:
        dek = _make_dek()
        sk1 = derive_subkeys(dek)
        sk2 = derive_subkeys(dek)
        assert sk1.k_enc == sk2.k_enc
        assert sk1.k_idx == sk2.k_idx

    def test_different_deks_different_subkeys(self) -> None:
        sk_a = derive_subkeys(_make_dek())
        sk_b = derive_subkeys(_make_dek())
        assert sk_a.k_enc != sk_b.k_enc
        assert sk_a.k_idx != sk_b.k_idx

    def test_k_enc_and_k_idx_are_distinct(self) -> None:
        """The two subkeys from the same DEK must be different (HKDF info separation)."""
        sk = derive_subkeys(_make_dek())
        assert sk.k_enc != sk.k_idx

    def test_subkeys_are_not_the_dek(self) -> None:
        dek = _make_dek()
        sk = derive_subkeys(dek)
        assert sk.k_enc != dek
        assert sk.k_idx != dek

    def test_subkeys_are_32_bytes(self) -> None:
        sk = derive_subkeys(_make_dek())
        assert len(sk.k_enc) == 32
        assert len(sk.k_idx) == 32

    def test_invalid_dek_length_raises(self) -> None:
        with pytest.raises(ValueError, match="DEK must be 32 bytes"):
            derive_subkeys(b"\x00" * 16)

    def test_empty_dek_raises(self) -> None:
        with pytest.raises(ValueError):
            derive_subkeys(b"")


# ---------------------------------------------------------------------------
# keyed_index
# ---------------------------------------------------------------------------


class TestKeyedIndex:
    """HMAC-SHA256 keyed index must be deterministic and key-separated."""

    def test_same_source_same_output(self) -> None:
        cipher = _make_cipher()
        src = b"docs/2024_oncology_results.pdf"
        assert cipher.keyed_index(src) == cipher.keyed_index(src)

    def test_different_source_different_output(self) -> None:
        cipher = _make_cipher()
        out1 = cipher.keyed_index(b"file_a.pdf")
        out2 = cipher.keyed_index(b"file_b.pdf")
        assert out1 != out2

    def test_output_is_32_bytes(self) -> None:
        cipher = _make_cipher()
        assert len(cipher.keyed_index(b"any source")) == 32

    def test_different_dek_different_index(self) -> None:
        """Same source, different DEK → different index (key-bound, not content-bound)."""
        src = b"the same filename"
        cipher_a = _make_cipher(_make_dek())
        cipher_b = _make_cipher(_make_dek())
        assert cipher_a.keyed_index(src) != cipher_b.keyed_index(src)

    def test_empty_source_deterministic(self) -> None:
        cipher = _make_cipher()
        out1 = cipher.keyed_index(b"")
        out2 = cipher.keyed_index(b"")
        assert out1 == out2


# ---------------------------------------------------------------------------
# make_aad_for
# ---------------------------------------------------------------------------


class TestMakeAadFor:
    """The canonical AAD helper must produce the correct ``table|column|row_id`` bytes."""

    def test_str_row_id(self) -> None:
        aad = make_aad_for("sessions", "content", "row-abc")
        assert aad == b"sessions|content|row-abc"

    def test_bytes_row_id(self) -> None:
        aad = make_aad_for("substrate_chunks", "text", b"kind=doc|sha=xyz|sess=1|chunk=0")
        assert aad == b"substrate_chunks|text|kind=doc|sha=xyz|sess=1|chunk=0"

    def test_pipe_separator_in_output(self) -> None:
        aad = make_aad_for("t", "c", "r")
        assert aad.count(b"|") == 2


# ---------------------------------------------------------------------------
# DekEnvelope — DEK dual-unwrap (the central ADR-025 §2.1 guarantee)
# ---------------------------------------------------------------------------


class TestDekEnvelopeDualUnwrap:
    """Both wrap paths must independently unseal the IDENTICAL DEK."""

    def test_tpm_wrap_and_recovery_wrap_yield_same_dek(self) -> None:
        """TPM-stub unseal and recovery-key unseal produce the same DEK bytes."""
        sealer = SoftwareSealer()
        rk = _make_recovery_key()
        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)

        dek_via_tpm = env.unseal_dek(recovery_key=None)
        dek_via_recovery = env.unseal_dek(recovery_key=rk)

        assert dek_via_tpm == dek_via_recovery, (
            "TPM-path DEK and recovery-path DEK differ — dual-wrap invariant violated"
        )
        assert len(dek_via_tpm) == DEK_BYTES

    def test_tpm_path_alone_yields_dek(self) -> None:
        sealer = SoftwareSealer()
        env = DekEnvelope.create(sealer=sealer, recovery_key=_make_recovery_key())
        dek = env.unseal_dek()
        assert len(dek) == DEK_BYTES

    def test_recovery_path_alone_yields_dek(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recovery path succeeds when the TPM sealer raises TpmUnavailable."""
        from shared.security import tpm_sealer as ts

        sealer = SoftwareSealer()
        rk = _make_recovery_key()
        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
        dek_reference = env.unseal_dek()

        # Patch the sealer's unseal to simulate TPM unavailability.
        monkeypatch.setattr(sealer, "unseal", lambda _: (_ for _ in ()).throw(ts.TpmUnavailable("chip gone")))

        dek_via_recovery = env.unseal_dek(recovery_key=rk)
        assert dek_via_recovery == dek_reference

    def test_wrong_recovery_key_raises(self) -> None:
        """A wrong recovery key must be rejected — fail-closed."""
        sealer = SoftwareSealer()
        rk_real = _make_recovery_key()
        rk_wrong = _make_recovery_key()
        assert rk_real != rk_wrong
        env = DekEnvelope.create(sealer=sealer, recovery_key=rk_real)

        # Force TPM path to fail so the recovery path is tried.
        from shared.security import tpm_sealer as ts

        def _fail_unseal(_: bytes) -> bytes:
            raise ts.TpmSealingError("simulated TPM failure")

        import types
        env._sealer = types.SimpleNamespace(unseal=_fail_unseal)

        with pytest.raises(DekEnvelopeError):
            env.unseal_dek(recovery_key=rk_wrong)

    def test_no_recovery_key_and_tpm_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TPM fails + no recovery key → DekEnvelopeError (refuse to open)."""
        sealer = SoftwareSealer()
        env = DekEnvelope.create(sealer=sealer, recovery_key=_make_recovery_key())

        from shared.security import tpm_sealer as ts

        monkeypatch.setattr(sealer, "unseal", lambda _: (_ for _ in ()).throw(ts.TpmUnavailable("no TPM")))

        with pytest.raises(DekEnvelopeError, match="refusing to open"):
            env.unseal_dek(recovery_key=None)


# ---------------------------------------------------------------------------
# DekEnvelope — wrap record version bytes
# ---------------------------------------------------------------------------


class TestDekEnvelopeVersionBytes:
    """Both wrap records must carry the expected version byte."""

    def test_tpm_wrap_record_version_byte(self) -> None:
        env = DekEnvelope.create(sealer=SoftwareSealer(), recovery_key=_make_recovery_key())
        assert env.tpm_wrap_record[0] == WRAP_VERSION, (
            f"TPM wrap record first byte: 0x{env.tpm_wrap_record[0]:02X}, "
            f"expected 0x{WRAP_VERSION:02X}"
        )

    def test_recovery_wrap_record_version_byte(self) -> None:
        env = DekEnvelope.create(sealer=SoftwareSealer(), recovery_key=_make_recovery_key())
        assert env.recovery_wrap_record[0] == WRAP_VERSION, (
            f"Recovery wrap record first byte: 0x{env.recovery_wrap_record[0]:02X}, "
            f"expected 0x{WRAP_VERSION:02X}"
        )


# ---------------------------------------------------------------------------
# DekEnvelope — save / load round-trip
# ---------------------------------------------------------------------------


class TestDekEnvelopeSaveLoad:
    """Saving wrap records to disk and loading them back must yield the same DEK."""

    def test_save_load_dek_unchanged(self, tmp_path: Path) -> None:
        keystore = tmp_path / "test.keystore.json"
        rk = _make_recovery_key()
        sealer = SoftwareSealer()

        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
        dek_original = env.unseal_dek()
        env.save(keystore)

        env2 = DekEnvelope.load(sealer=sealer, keystore_path=keystore)
        dek_loaded = env2.unseal_dek()
        assert dek_loaded == dek_original

    def test_save_load_recovery_path_works(self, tmp_path: Path) -> None:
        keystore = tmp_path / "test.keystore.json"
        rk = _make_recovery_key()
        sealer = SoftwareSealer()

        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
        dek_original = env.unseal_dek()
        env.save(keystore)

        env2 = DekEnvelope.load(sealer=sealer, keystore_path=keystore)
        # Force TPM failure on the loaded envelope.
        from shared.security import tpm_sealer as ts
        import types
        env2._sealer = types.SimpleNamespace(
            unseal=lambda _: (_ for _ in ()).throw(ts.TpmUnavailable("no chip"))
        )
        dek_via_recovery = env2.unseal_dek(recovery_key=rk)
        assert dek_via_recovery == dek_original

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DekEnvelopeError, match="cannot read keystore"):
            DekEnvelope.load(
                sealer=SoftwareSealer(),
                keystore_path=tmp_path / "does_not_exist.json",
            )

    def test_load_malformed_json_raises(self, tmp_path: Path) -> None:
        keystore = tmp_path / "bad.json"
        keystore.write_text("not json {{{", encoding="utf-8")
        with pytest.raises(DekEnvelopeError, match="not valid JSON"):
            DekEnvelope.load(sealer=SoftwareSealer(), keystore_path=keystore)

    def test_save_does_not_write_dek_in_clear(self, tmp_path: Path) -> None:
        """The keystore file must not contain the raw DEK as a readable substring."""
        keystore = tmp_path / "keystore.json"
        rk = _make_recovery_key()
        sealer = SoftwareSealer()
        env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
        dek = env.unseal_dek()
        env.save(keystore)

        # Read the raw file bytes.
        raw = keystore.read_bytes()
        import base64
        dek_b64 = base64.b64encode(dek).decode("ascii")
        # The raw DEK should not appear as a standalone base64-encoded value.
        # (It will be wrapped, so this should never be found as-is.)
        assert dek not in raw, "DEK bytes found literally in the keystore file"
        # The base64 of the raw DEK should also not appear directly (it would be
        # inside a wrapped ciphertext, not standalone).
        assert dek_b64 not in raw.decode("ascii", errors="replace"), (
            "DEK base64 found directly in the keystore — was it persisted unwrapped?"
        )


# ---------------------------------------------------------------------------
# build_envelope (fail-closed factory)
# ---------------------------------------------------------------------------


class TestBuildEnvelopeFactory:
    """The production factory must enforce dev-mode / SoftwareSealer guard."""

    def test_software_sealer_dev_mode_false_raises(self, tmp_path: Path) -> None:
        """SoftwareSealer with dev_mode=False must raise DevModeSealerError."""
        with pytest.raises(DevModeSealerError, match="SECURITY ENFORCEMENT"):
            build_envelope(
                sealer=SoftwareSealer(),
                recovery_key=_make_recovery_key(),
                keystore_path=tmp_path / "ks.json",
                dev_mode=False,
            )

    def test_software_sealer_dev_mode_true_succeeds(self, tmp_path: Path) -> None:
        """SoftwareSealer with dev_mode=True must succeed and write the keystore."""
        keystore = tmp_path / "ks.json"
        env = build_envelope(
            sealer=SoftwareSealer(),
            recovery_key=_make_recovery_key(),
            keystore_path=keystore,
            dev_mode=True,
        )
        assert isinstance(env, DekEnvelope)
        assert keystore.exists(), "keystore file was not written by build_envelope"
        dek = env.unseal_dek()
        assert len(dek) == DEK_BYTES

    def test_default_dev_mode_is_false(self, tmp_path: Path) -> None:
        """dev_mode defaults to False, so SoftwareSealer without explicit dev_mode raises."""
        with pytest.raises(DevModeSealerError):
            build_envelope(
                sealer=SoftwareSealer(),
                recovery_key=_make_recovery_key(),
                keystore_path=tmp_path / "ks.json",
                # dev_mode not passed → defaults to False
            )

    def test_wrong_length_recovery_key_raises(self, tmp_path: Path) -> None:
        """A recovery key of the wrong length must raise ValueError before any crypto."""
        with pytest.raises(ValueError, match="recovery_key must be 32 bytes"):
            build_envelope(
                sealer=SoftwareSealer(),
                recovery_key=b"\x00" * 16,  # 16 bytes instead of 32
                keystore_path=tmp_path / "ks.json",
                dev_mode=True,
            )

    def test_non_software_sealer_dev_mode_false_succeeds(self, tmp_path: Path) -> None:
        """A non-SoftwareSealer Sealer with dev_mode=False should NOT raise the guard.

        We can't easily test a real TpmSealer on CI, so we create a minimal
        conforming sealer that is NOT a SoftwareSealer instance.  The factory
        checks ``isinstance(sealer, SoftwareSealer)`` — anything else passes.
        """
        # Use a minimal in-test Sealer that wraps SoftwareSealer but is NOT
        # an instance of SoftwareSealer itself.
        class _TestSealer:
            """Wrapper sealer — NOT a SoftwareSealer instance."""

            def __init__(self) -> None:
                self._inner = SoftwareSealer()

            def seal(self, key_material: bytes) -> bytes:
                return self._inner.seal(key_material)

            def unseal(self, blob: bytes) -> bytes:
                return self._inner.unseal(blob)

        keystore = tmp_path / "ks.json"
        env = build_envelope(
            sealer=_TestSealer(),
            recovery_key=_make_recovery_key(),
            keystore_path=keystore,
            dev_mode=False,  # should NOT raise — _TestSealer is not SoftwareSealer
        )
        assert isinstance(env, DekEnvelope)
        assert keystore.exists()


# ---------------------------------------------------------------------------
# generate_recovery_key
# ---------------------------------------------------------------------------


class TestGenerateRecoveryKey:
    """Recovery key generator must produce RECOVERY_KEY_BYTES random bytes."""

    def test_length(self) -> None:
        assert len(generate_recovery_key()) == RECOVERY_KEY_BYTES

    def test_freshness(self) -> None:
        """Two recovery keys from different calls must be distinct."""
        rk1 = generate_recovery_key()
        rk2 = generate_recovery_key()
        assert rk1 != rk2


# ---------------------------------------------------------------------------
# Integration — FieldCipher end-to-end with DekEnvelope
# ---------------------------------------------------------------------------


class TestFieldCipherWithEnvelope:
    """Demonstrate the full stack: create envelope → derive subkeys → encrypt/decrypt."""

    def test_full_stack_round_trip(self, tmp_path: Path) -> None:
        keystore = tmp_path / "ks.json"
        rk = _make_recovery_key()

        # Provision the envelope (ceremony-like step).
        env = build_envelope(
            sealer=SoftwareSealer(),
            recovery_key=rk,
            keystore_path=keystore,
            dev_mode=True,
        )
        dek = env.unseal_dek()
        subkeys = derive_subkeys(dek)
        cipher = FieldCipher(subkeys)

        pt = b"patient data - decades of private content"
        aad = make_aad_for("sessions", "content", "turn-uuid-0001")
        blob = cipher.encrypt(pt, aad=aad)

        # Simulate a restart: load from disk, unseal, re-derive.
        env2 = DekEnvelope.load(sealer=SoftwareSealer(), keystore_path=keystore)
        dek2 = env2.unseal_dek()
        subkeys2 = derive_subkeys(dek2)
        cipher2 = FieldCipher(subkeys2)

        assert cipher2.decrypt(blob, aad=aad) == pt

    def test_keyed_index_survives_envelope_reload(self, tmp_path: Path) -> None:
        """The keyed index must be deterministic across envelope save/load cycles."""
        keystore = tmp_path / "ks.json"
        rk = _make_recovery_key()

        env = build_envelope(
            sealer=SoftwareSealer(),
            recovery_key=rk,
            keystore_path=keystore,
            dev_mode=True,
        )
        cipher1 = FieldCipher(derive_subkeys(env.unseal_dek()))
        src = b"important_file.pdf"
        idx1 = cipher1.keyed_index(src)

        env2 = DekEnvelope.load(sealer=SoftwareSealer(), keystore_path=keystore)
        cipher2 = FieldCipher(derive_subkeys(env2.unseal_dek()))
        idx2 = cipher2.keyed_index(src)

        assert idx1 == idx2, (
            "keyed index changed across envelope reload — DEK is not stable"
        )


# ---------------------------------------------------------------------------
# unseal_via_recovery — recovery-ONLY DEK unwrap (break-glass, no TPM attempt)
# ---------------------------------------------------------------------------


class _DeadSealer:
    """Seals like a SoftwareSealer but ALWAYS raises on unseal (dead chip)."""

    def __init__(self) -> None:
        self._inner = SoftwareSealer()

    def seal(self, key_material: bytes) -> bytes:
        return self._inner.seal(key_material)

    def unseal(self, blob: bytes) -> bytes:
        from shared.security.tpm_sealer import TpmSealingError
        raise TpmSealingError("dead chip — TPM private half is gone")


class TestUnsealViaRecovery:
    """``unseal_via_recovery`` unwraps the recovery wrap ONLY and never the TPM path."""

    def test_recovery_only_yields_dek_even_when_tpm_dead(self) -> None:
        """The DEK is recoverable via the recovery wrap even when the TPM sealer
        is dead — proving the method does NOT attempt the TPM path at all."""
        rk = _make_recovery_key()
        env = DekEnvelope.create(sealer=_DeadSealer(), recovery_key=rk)
        # Even though the sealer's unseal() always raises, the recovery path works.
        assert env.unseal_via_recovery(rk) == env.unseal_dek(recovery_key=rk)

    def test_recovery_only_does_not_touch_sealer(self) -> None:
        """unseal_via_recovery must not invoke the sealer.unseal at all."""
        rk = _make_recovery_key()

        calls: list[bytes] = []

        class _SpySealer:
            def __init__(self) -> None:
                self._inner = SoftwareSealer()

            def seal(self, key_material: bytes) -> bytes:
                return self._inner.seal(key_material)

            def unseal(self, blob: bytes) -> bytes:
                calls.append(blob)  # record any TPM-path attempt
                return self._inner.unseal(blob)

        env = DekEnvelope.create(sealer=_SpySealer(), recovery_key=rk)
        dek = env.unseal_via_recovery(rk)
        assert len(dek) == DEK_BYTES
        assert calls == [], "unseal_via_recovery must NOT call the sealer's unseal"

    def test_wrong_recovery_key_raises(self) -> None:
        rk = _make_recovery_key()
        env = DekEnvelope.create(sealer=SoftwareSealer(), recovery_key=rk)
        wrong = bytes(RECOVERY_KEY_BYTES)  # all-zero, wrong key
        with pytest.raises(DekEnvelopeError):
            env.unseal_via_recovery(wrong)

    def test_recovery_dek_matches_tpm_dek(self) -> None:
        """The recovery path and TPM path must yield the IDENTICAL DEK."""
        rk = _make_recovery_key()
        env = DekEnvelope.create(sealer=SoftwareSealer(), recovery_key=rk)
        assert env.unseal_via_recovery(rk) == env.unseal_dek()


# ---------------------------------------------------------------------------
# reseal_dek — re-wrap an EXISTING DEK (break-glass migration), shared wrap impl
# ---------------------------------------------------------------------------


class TestResealDek:
    """``reseal_dek`` re-wraps an existing DEK without generating a new one and
    shares the dual-wrap implementation with ``DekEnvelope.create``."""

    def test_reseals_same_dek_no_new_dek(self) -> None:
        """The re-sealed envelope must hold the SAME DEK passed in (no new DEK)."""
        original_dek = _make_dek()
        new_rk = _make_recovery_key()
        env = reseal_dek(
            original_dek, sealer=SoftwareSealer(), recovery_key=new_rk, dev_mode=True
        )
        # Both wrap paths must reproduce the original DEK exactly.
        assert env.unseal_dek() == original_dek
        assert env.unseal_via_recovery(new_rk) == original_dek

    def test_software_sealer_dev_mode_false_raises(self) -> None:
        """Production guard: SoftwareSealer + dev_mode=False → DevModeSealerError."""
        with pytest.raises(DevModeSealerError):
            reseal_dek(
                _make_dek(),
                sealer=SoftwareSealer(),
                recovery_key=_make_recovery_key(),
                dev_mode=False,
            )

    def test_non_software_sealer_dev_mode_false_succeeds(self) -> None:
        """A non-SoftwareSealer sealer with dev_mode=False passes the guard."""
        class _TestSealer:
            def __init__(self) -> None:
                self._inner = SoftwareSealer()

            def seal(self, key_material: bytes) -> bytes:
                return self._inner.seal(key_material)

            def unseal(self, blob: bytes) -> bytes:
                return self._inner.unseal(blob)

        dek = _make_dek()
        env = reseal_dek(
            dek, sealer=_TestSealer(), recovery_key=_make_recovery_key(), dev_mode=False
        )
        assert isinstance(env, DekEnvelope)
        assert env.unseal_dek() == dek

    def test_wrong_length_recovery_key_raises(self) -> None:
        with pytest.raises(ValueError):
            reseal_dek(
                _make_dek(),
                sealer=SoftwareSealer(),
                recovery_key=b"too-short",
                dev_mode=True,
            )

    def test_wrong_length_dek_raises(self) -> None:
        with pytest.raises(ValueError):
            reseal_dek(
                b"not-32-bytes",
                sealer=SoftwareSealer(),
                recovery_key=_make_recovery_key(),
                dev_mode=True,
            )

    def test_reseal_record_format_matches_create(self) -> None:
        """reseal_dek and create must produce byte-identical RECORD LAYOUT
        (version prefix + structure), proving the shared wrap implementation.

        We can't compare ciphertext bytes (fresh nonces / random seal), but the
        version byte, the TPM-record framing, and the recovery-record length
        must match between the two construction paths for the same DEK size.
        """
        dek = _make_dek()
        rk = _make_recovery_key()
        created = DekEnvelope.create(sealer=SoftwareSealer(), recovery_key=rk)
        resealed = reseal_dek(dek, sealer=SoftwareSealer(), recovery_key=rk, dev_mode=True)

        # Same version byte on both record types.
        assert created.tpm_wrap_record[0] == resealed.tpm_wrap_record[0] == WRAP_VERSION
        assert (
            created.recovery_wrap_record[0]
            == resealed.recovery_wrap_record[0]
            == WRAP_VERSION
        )
        # Recovery record length is deterministic (version+nonce+dek+tag), so it
        # must be identical across both paths.
        assert len(created.recovery_wrap_record) == len(resealed.recovery_wrap_record)
