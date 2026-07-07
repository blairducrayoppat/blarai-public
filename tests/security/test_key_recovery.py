"""Tested-recovery lock — offline DEK recovery after TPM/chip loss (C6, §5.5).

Sprint 17 Stream K — the load-bearing DoD for the #598 air-gap gate's
at-rest-encryption criterion (``SECURITY_ROADMAP_air_gap_removal.md`` §5.5):

    "Recover the at-rest DEK from the offline recovery key after TPM/chip loss
     or hardware migration + a tested-recovery lock (a fresh environment
     decrypts via the recovery key)."

WHY THIS FILE EXISTS — the seam it closes
=========================================
The dual-wrap *mechanism* (TPM-sealed primary + offline-recovery-key
secondary) has shipped since Sprint 14 in ``shared/security/dek_envelope.py``,
and ``shared/tests/test_field_cipher_and_dek_envelope.py`` already covers it at
the unit level.  But every existing test simulates "the TPM is gone" by
``monkeypatch``-ing a live sealer's ``unseal`` to raise.  None of them models
the actual disaster the recovery key exists for: a **fresh environment on new
hardware** where the *only* artifacts carried across are (a) the keystore file
and (b) the offline recovery key — and there is *no TPM that can unwrap the
primary wrap at all*.

This file is that lock.  It proves, end-to-end and against the real crypto
stack (``FieldCipher`` over the recovered DEK), that:

  1. a fresh environment with no usable TPM recovers the DEK via the recovery
     key alone (Sprint-14 Decision-2: "a dead chip or hardware migration must
     not lose decades of data");
  2. real at-rest ciphertext written on the original machine decrypts cleanly
     after the migration; and
  3. ``reseal_dek`` then re-binds the SAME DEK to the new machine's TPM so the
     fast daily path is restored — without ever generating a new DEK or
     touching the encrypted data.

It also locks the fail-closed posture: a wrong/absent recovery key in the fresh
environment must REFUSE, never return plaintext or a best-effort key.

TIER & ISOLATION
================
Gate tier — the ``SoftwareSealer`` stands in for the TPM (the C6 tier in the
SDV: "green in the gate (stand-in sealer)").  A real-TPM round-trip is a
separate ``@hardware`` concern noted in the Stream-K report for an on-chip
home; this lock is the gate-tier proof.

All tests use ``tmp_path`` only.  The root ``conftest.py`` redirects
LOCALAPPDATA/HOME/XDG_DATA_HOME to a throwaway temp dir at process startup and
unsets ``BLARAI_DEK_KEYSTORE``, so the real user-data directory and the real
production keystore are never touched.

This file deliberately does NOT collide with ``test_egress_core.py`` (Stream
H-a), ``test_egress_screen.py`` (H-b), or ``test_production_posture.py`` (J).
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from shared.security import recovery_key_store
from shared.security.dek_envelope import (
    DEK_BYTES,
    RECOVERY_KEY_BYTES,
    DekEnvelope,
    DekEnvelopeError,
    generate_recovery_key,
    reseal_dek,
)
from shared.security.field_cipher import FieldCipher, derive_subkeys, make_aad_for
from shared.security.tpm_sealer import (
    SoftwareSealer,
    TpmSealingError,
    TpmUnavailable,
)


# ===========================================================================
# Fresh-environment sealers — the faithful "chip is gone" simulation
# ===========================================================================


class _NoTpmSealer:
    """A sealer for a FRESH machine whose TPM cannot unwrap the old primary wrap.

    This is the honest model of hardware migration / chip loss: the new
    environment has *no* access to the private half that sealed the DEK on the
    original machine.  ``seal`` is never legitimately called on this sealer in
    the recovery flow (recovery uses the recovery wrap only), but if anything
    tried the TPM path it would fail closed.

    ``unseal`` raises :class:`TpmUnavailable` — exactly what a real
    ``TpmSealer`` raises off-chip / with no provider — so a test that reaches
    the TPM branch fails the same way production would on the dead chip.
    """

    def seal(self, key_material: bytes) -> bytes:  # pragma: no cover - not used in recovery
        raise TpmUnavailable("fresh environment: no TPM to seal with")

    def unseal(self, blob: bytes) -> bytes:
        raise TpmUnavailable("fresh environment: TPM/chip is gone — cannot unseal")


class _DeadChipSealer:
    """Like :class:`_NoTpmSealer` but raises :class:`TpmSealingError` on unseal.

    Models the variant where a provider *is* present on the new box but the
    persisted seal key is absent / wrong (NTE_BAD_KEYSET-class failure) — a
    different exception path that the recovery flow must survive identically.
    """

    def seal(self, key_material: bytes) -> bytes:  # pragma: no cover - not used in recovery
        raise TpmSealingError("dead chip: seal key not present on this hardware")

    def unseal(self, blob: bytes) -> bytes:
        raise TpmSealingError("dead chip: seal key not present — cannot unseal")


def _make_dek() -> bytes:
    return secrets.token_bytes(DEK_BYTES)


def _provision_on_original_machine(
    keystore: Path,
) -> tuple[bytes, bytes]:
    """Simulate the original-machine ceremony: create + persist the keystore.

    Uses ``SoftwareSealer`` as the gate-tier stand-in for the original
    machine's TPM.  Returns ``(recovery_key, dek)`` — the recovery key the
    operator stores off-box, and the DEK (only so the test can prove the
    recovered DEK matches; production never returns the DEK from the ceremony).
    """
    original_tpm = SoftwareSealer()  # stands in for machine-A TPM (gate tier)
    recovery_key = recovery_key_store.generate()
    env = DekEnvelope.create(sealer=original_tpm, recovery_key=recovery_key)
    env.save(keystore)
    dek = env.unseal_dek()  # via the (stand-in) original TPM, like a normal boot
    return recovery_key, dek


# ===========================================================================
# THE core lock — a fresh environment decrypts via the offline recovery key
# ===========================================================================


class TestFreshEnvironmentRecovery:
    """C6 DoD: a fresh environment (no TPM access) recovers the DEK + data.

    Each test does the full arc: provision on machine A → carry ONLY the
    keystore file + recovery key to a fresh machine B with no usable TPM →
    recover.
    """

    def test_fresh_env_recovers_dek_via_recovery_key(self, tmp_path: Path) -> None:
        """The headline lock: keystore + recovery key alone reconstruct the DEK
        on a machine whose TPM cannot unwrap the primary wrap."""
        keystore = tmp_path / "machineA" / "dek_keystore.json"
        keystore.parent.mkdir(parents=True)
        recovery_key, dek_on_A = _provision_on_original_machine(keystore)

        # --- Fresh machine B: only the keystore file survived the migration. ---
        # Construct the envelope with a sealer that has NO TPM (chip is gone).
        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)

        # Break-glass: recover via the recovery key only (never the TPM path).
        dek_on_B = env_on_B.unseal_via_recovery(recovery_key)

        assert dek_on_B == dek_on_A, (
            "recovered DEK differs from the original — the offline recovery "
            "path did not reconstruct the same key"
        )
        assert len(dek_on_B) == DEK_BYTES

    def test_fresh_env_decrypts_real_at_rest_ciphertext(self, tmp_path: Path) -> None:
        """Decades-of-data guarantee: ciphertext written on machine A decrypts
        on the fresh machine B using only the recovery key."""
        keystore = tmp_path / "dek_keystore.json"
        recovery_key, dek_on_A = _provision_on_original_machine(keystore)

        # Machine A encrypts a real, private field value at rest.
        cipher_A = FieldCipher(derive_subkeys(dek_on_A))
        secret = b"a decade of private session content that must survive a dead chip"
        aad = make_aad_for("sessions", "content", "turn-uuid-recovery-0001")
        ciphertext = cipher_A.encrypt(secret, aad=aad)

        # --- Machine A's chip dies.  Machine B has the keystore + recovery key. ---
        env_on_B = DekEnvelope.load(sealer=_DeadChipSealer(), keystore_path=keystore)
        dek_on_B = env_on_B.unseal_via_recovery(recovery_key)

        # The recovered DEK decrypts the original at-rest ciphertext byte-for-byte.
        cipher_B = FieldCipher(derive_subkeys(dek_on_B))
        recovered_plaintext = cipher_B.decrypt(ciphertext, aad=aad)
        assert recovered_plaintext == secret, (
            "the recovered DEK could not decrypt data written before the chip "
            "loss — the recovery path does not actually preserve the data"
        )

    def test_fresh_env_recovers_via_unseal_dek_fallback(self, tmp_path: Path) -> None:
        """The TPM-first ``unseal_dek`` API also reaches recovery in a fresh env.

        ``unseal_dek(recovery_key=...)`` tries the TPM first; on a fresh machine
        the TPM raises, so it must fall through to the recovery wrap and return
        the correct DEK.  (``unseal_via_recovery`` is the by-design break-glass
        path; this proves the convenience API does not strand a recoverable
        operator who calls the general method.)
        """
        keystore = tmp_path / "dek_keystore.json"
        recovery_key, dek_on_A = _provision_on_original_machine(keystore)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        dek_on_B = env_on_B.unseal_dek(recovery_key=recovery_key)
        assert dek_on_B == dek_on_A

    def test_fresh_env_recovers_from_operator_string(self, tmp_path: Path) -> None:
        """End-to-end through the operator-transcription surface.

        The real UX hands the operator a *string*.  This drives recovery via
        the printed checksummed-grouped display form parsed back by
        ``DekEnvelope.unseal_via_recovery_hex`` → ``recovery_key_store``."""
        keystore = tmp_path / "dek_keystore.json"
        recovery_key, dek_on_A = _provision_on_original_machine(keystore)

        # What the operator would have copied off the machine at ceremony time.
        printed = recovery_key_store.to_display_groups(recovery_key, checksum=True)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        dek_on_B = env_on_B.unseal_via_recovery_hex(printed)
        assert dek_on_B == dek_on_A


# ===========================================================================
# Full hardware-migration arc — recover THEN re-bind to the new chip
# ===========================================================================


class TestHardwareMigrationReseal:
    """After recovering on new hardware, ``reseal_dek`` restores the fast path.

    This is the complete migration story (provisioning ceremony ``--recover``
    mode in code form): recover the SAME DEK via the recovery key, re-wrap it
    under the NEW machine's TPM + a FRESH recovery key, and confirm the data is
    readable via the new TPM path while still recoverable via the new recovery
    key.
    """

    def test_resealed_dek_is_same_dek(self, tmp_path: Path) -> None:
        keystore = tmp_path / "dek_keystore.json"
        recovery_key, dek_on_A = _provision_on_original_machine(keystore)

        # Recover on fresh machine B.
        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        recovered_dek = env_on_B.unseal_via_recovery(recovery_key)

        # Re-bind to machine B's NEW TPM (gate-tier stand-in) + a fresh key.
        new_tpm = SoftwareSealer()
        new_recovery_key = generate_recovery_key()
        new_env = reseal_dek(
            recovered_dek,
            sealer=new_tpm,
            recovery_key=new_recovery_key,
            dev_mode=True,  # SoftwareSealer stand-in — gate tier
        )

        # The re-sealed envelope holds the SAME DEK via BOTH new paths.
        assert new_env.unseal_dek() == dek_on_A, "re-seal changed the DEK"
        assert new_env.unseal_via_recovery(new_recovery_key) == dek_on_A

    def test_data_survives_full_migration_and_reseal(self, tmp_path: Path) -> None:
        """Data written on A is readable via B's new TPM path after re-seal."""
        keystore_A = tmp_path / "machineA" / "dek_keystore.json"
        keystore_A.parent.mkdir(parents=True)
        recovery_key, dek_on_A = _provision_on_original_machine(keystore_A)

        # Machine A at-rest ciphertext.
        cipher_A = FieldCipher(derive_subkeys(dek_on_A))
        aad = make_aad_for("substrate_chunks", "text", "kind=doc|sha=abc|chunk=0")
        secret = b"orchestrator long-term memory: must outlive the original hardware"
        ciphertext = cipher_A.encrypt(secret, aad=aad)

        # Migrate: B recovers, then re-seals onto its own chip + new keystore.
        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore_A)
        recovered_dek = env_on_B.unseal_via_recovery(recovery_key)

        keystore_B = tmp_path / "machineB" / "dek_keystore.json"
        keystore_B.parent.mkdir(parents=True)
        new_recovery_key = generate_recovery_key()
        new_env = reseal_dek(
            recovered_dek,
            sealer=SoftwareSealer(),
            recovery_key=new_recovery_key,
            dev_mode=True,
        )
        new_env.save(keystore_B)

        # Reboot on B via the NEW keystore + the NEW (stand-in) TPM — the
        # restored fast daily path, no recovery key needed.
        rebooted = DekEnvelope.load(sealer=SoftwareSealer(), keystore_path=keystore_B)
        dek_after_reboot = rebooted.unseal_dek()
        cipher_B = FieldCipher(derive_subkeys(dek_after_reboot))
        assert cipher_B.decrypt(ciphertext, aad=aad) == secret, (
            "data written on machine A is unreadable after migration + re-seal"
        )

    def test_old_recovery_key_retired_after_reseal(self, tmp_path: Path) -> None:
        """After re-seal with a fresh recovery key, the OLD recovery key must NOT
        unwrap the NEW keystore (the old artifact is retired, fail-closed)."""
        keystore_A = tmp_path / "dek_keystore.json"
        old_recovery_key, _dek = _provision_on_original_machine(keystore_A)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore_A)
        recovered_dek = env_on_B.unseal_via_recovery(old_recovery_key)

        new_recovery_key = generate_recovery_key()
        assert old_recovery_key != new_recovery_key
        new_env = reseal_dek(
            recovered_dek,
            sealer=SoftwareSealer(),
            recovery_key=new_recovery_key,
            dev_mode=True,
        )

        # The OLD recovery key must be rejected by the NEW envelope.
        with pytest.raises(DekEnvelopeError):
            new_env.unseal_via_recovery(old_recovery_key)
        # The NEW recovery key works.
        assert new_env.unseal_via_recovery(new_recovery_key) == recovered_dek


# ===========================================================================
# Fail-closed posture in the fresh environment
# ===========================================================================


class TestFreshEnvironmentFailClosed:
    """The recovery path must REFUSE on bad inputs — never return plaintext."""

    def test_wrong_recovery_key_refuses(self, tmp_path: Path) -> None:
        keystore = tmp_path / "dek_keystore.json"
        _real_key, _dek = _provision_on_original_machine(keystore)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        wrong_key = generate_recovery_key()
        with pytest.raises(DekEnvelopeError):
            env_on_B.unseal_via_recovery(wrong_key)

    def test_all_zero_recovery_key_refuses(self, tmp_path: Path) -> None:
        keystore = tmp_path / "dek_keystore.json"
        _real_key, _dek = _provision_on_original_machine(keystore)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        with pytest.raises(DekEnvelopeError):
            env_on_B.unseal_via_recovery(bytes(RECOVERY_KEY_BYTES))

    def test_no_recovery_key_and_no_tpm_refuses(self, tmp_path: Path) -> None:
        """No recovery key supplied + dead TPM → refuse to open (no fallback)."""
        keystore = tmp_path / "dek_keystore.json"
        _real_key, _dek = _provision_on_original_machine(keystore)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        with pytest.raises(DekEnvelopeError, match="refusing to open"):
            env_on_B.unseal_dek(recovery_key=None)

    def test_recovered_dek_does_not_decrypt_foreign_ciphertext(
        self, tmp_path: Path
    ) -> None:
        """A recovered DEK must not decrypt data encrypted under a DIFFERENT DEK
        (confidentiality across the migration boundary holds)."""
        keystore = tmp_path / "dek_keystore.json"
        recovery_key, _dek = _provision_on_original_machine(keystore)

        # Ciphertext from an unrelated DEK (a different machine's data).
        foreign_cipher = FieldCipher(derive_subkeys(_make_dek()))
        aad = make_aad_for("sessions", "content", "foreign-row")
        foreign_blob = foreign_cipher.encrypt(b"someone else's secret", aad=aad)

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        recovered_dek = env_on_B.unseal_via_recovery(recovery_key)
        cipher_B = FieldCipher(derive_subkeys(recovered_dek))
        from shared.security.field_cipher import FieldCipherError

        with pytest.raises(FieldCipherError):
            cipher_B.decrypt(foreign_blob, aad=aad)

    def test_tampered_keystore_recovery_wrap_refuses(self, tmp_path: Path) -> None:
        """A flipped byte in the persisted recovery wrap must fail authentication
        in the fresh environment (tamper-evidence survives migration)."""
        import base64
        import json

        keystore = tmp_path / "dek_keystore.json"
        recovery_key, _dek = _provision_on_original_machine(keystore)

        # Tamper with the recovery wrap record on disk.
        doc = json.loads(keystore.read_text(encoding="utf-8"))
        rec_field = next(k for k in doc if k.startswith("recovery_wrap_v"))
        raw = bytearray(base64.b64decode(doc[rec_field]))
        raw[-1] ^= 0xFF  # flip a tag byte
        doc[rec_field] = base64.b64encode(bytes(raw)).decode("ascii")
        keystore.write_text(json.dumps(doc), encoding="utf-8")

        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        with pytest.raises(DekEnvelopeError):
            env_on_B.unseal_via_recovery(recovery_key)


# ===========================================================================
# recovery_key_store — the offline recovery-key material module
# ===========================================================================


class TestRecoveryKeyStoreGeneration:
    """``generate`` produces fresh, correctly-sized key material."""

    def test_length(self) -> None:
        assert len(recovery_key_store.generate()) == RECOVERY_KEY_BYTES

    def test_freshness(self) -> None:
        assert recovery_key_store.generate() != recovery_key_store.generate()

    def test_matches_envelope_key_size(self) -> None:
        """The store and the envelope must agree on the recovery key size."""
        assert recovery_key_store.RECOVERY_KEY_BYTES == RECOVERY_KEY_BYTES
        assert recovery_key_store.RECOVERY_KEY_HEX_CHARS == RECOVERY_KEY_BYTES * 2


class TestRecoveryKeyStoreEncoding:
    """Encoding/decoding round-trips through every emitted form."""

    def test_bare_hex_round_trip(self) -> None:
        key = recovery_key_store.generate()
        assert recovery_key_store.parse_hex(recovery_key_store.to_hex(key)) == key

    def test_bare_hex_is_correct_length(self) -> None:
        key = recovery_key_store.generate()
        assert len(recovery_key_store.to_hex(key)) == recovery_key_store.RECOVERY_KEY_HEX_CHARS

    def test_grouped_no_checksum_round_trip(self) -> None:
        key = recovery_key_store.generate()
        disp = recovery_key_store.to_display_groups(key, checksum=False)
        assert "-" in disp  # grouped
        assert recovery_key_store.parse_hex(disp) == key

    def test_grouped_with_checksum_round_trip(self) -> None:
        key = recovery_key_store.generate()
        disp = recovery_key_store.to_display_groups(key, checksum=True)
        assert recovery_key_store.parse_hex(disp) == key

    def test_parse_tolerates_whitespace_and_case(self) -> None:
        key = recovery_key_store.generate()
        messy = "  " + recovery_key_store.to_hex(key).upper() + "\n"
        assert recovery_key_store.parse_hex(messy) == key

    def test_parse_tolerates_legacy_dashed_hex(self) -> None:
        """A user splicing dashes into bare hex (no checksum) still parses."""
        key = recovery_key_store.generate()
        hexed = recovery_key_store.to_hex(key)
        spliced = "-".join(hexed[i : i + 4] for i in range(0, len(hexed), 4))
        assert recovery_key_store.parse_hex(spliced) == key


class TestRecoveryKeyStoreFailClosed:
    """Parsing/encoding must Fail-Closed on malformed material."""

    def test_parse_wrong_length_raises(self) -> None:
        with pytest.raises(recovery_key_store.RecoveryKeyError, match="wrong length"):
            recovery_key_store.parse_hex("abcd")

    def test_parse_non_hex_raises(self) -> None:
        bad = "z" * recovery_key_store.RECOVERY_KEY_HEX_CHARS
        with pytest.raises(recovery_key_store.RecoveryKeyError, match="non-hex"):
            recovery_key_store.parse_hex(bad)

    def test_parse_empty_raises(self) -> None:
        with pytest.raises(recovery_key_store.RecoveryKeyError, match="empty"):
            recovery_key_store.parse_hex("   ")

    def test_parse_bytes_input_raises(self) -> None:
        with pytest.raises(recovery_key_store.RecoveryKeyError, match="must be a string"):
            recovery_key_store.parse_hex(b"deadbeef")  # type: ignore[arg-type]

    def test_checksum_mismatch_raises(self) -> None:
        """A single mis-transcribed nibble in a checksummed key is caught."""
        key = recovery_key_store.generate()
        disp = recovery_key_store.to_display_groups(key, checksum=True)
        # Flip the first hex nibble of the body (guaranteed to change the key,
        # hence the checksum will no longer match).
        first = disp[0]
        replacement = "0" if first != "0" else "1"
        mutated = replacement + disp[1:]
        with pytest.raises(recovery_key_store.RecoveryKeyError, match="checksum mismatch"):
            recovery_key_store.parse_hex(mutated)

    def test_to_hex_wrong_length_raises(self) -> None:
        with pytest.raises(recovery_key_store.RecoveryKeyError, match="must be 32 bytes"):
            recovery_key_store.to_hex(b"\x00" * 16)

    def test_to_display_groups_wrong_length_raises(self) -> None:
        with pytest.raises(recovery_key_store.RecoveryKeyError):
            recovery_key_store.to_display_groups(b"\x00" * 31)


class TestRecoveryKeyStoreRedaction:
    """``redact`` must never reveal the key material."""

    def test_redact_excludes_key_bytes(self) -> None:
        key = recovery_key_store.generate()
        red = recovery_key_store.redact(key)
        assert key.hex() not in red, "redact() leaked the full key hex"
        # No 8+ contiguous hex chars of the key should appear in the descriptor.
        hexed = key.hex()
        for i in range(0, len(hexed) - 8):
            assert hexed[i : i + 8] not in red, "redact() leaked a key fragment"

    def test_redact_reports_length(self) -> None:
        key = recovery_key_store.generate()
        assert f"len={RECOVERY_KEY_BYTES}" in recovery_key_store.redact(key)

    def test_redact_is_deterministic_for_same_key(self) -> None:
        key = recovery_key_store.generate()
        assert recovery_key_store.redact(key) == recovery_key_store.redact(key)

    def test_redact_differs_for_different_keys(self) -> None:
        assert recovery_key_store.redact(recovery_key_store.generate()) != (
            recovery_key_store.redact(recovery_key_store.generate())
        )


class TestUnsealViaRecoveryHexFailClosed:
    """``DekEnvelope.unseal_via_recovery_hex`` Fail-Closed on bad strings."""

    def test_malformed_string_raises_dek_envelope_error(self, tmp_path: Path) -> None:
        keystore = tmp_path / "dek_keystore.json"
        _real_key, _dek = _provision_on_original_machine(keystore)
        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        # A wrong-length string must surface as DekEnvelopeError, not a raw
        # RecoveryKeyError leaking out of the envelope API.
        with pytest.raises(DekEnvelopeError, match="invalid recovery key string"):
            env_on_B.unseal_via_recovery_hex("not-a-real-key")

    def test_wrong_but_wellformed_key_string_raises(self, tmp_path: Path) -> None:
        keystore = tmp_path / "dek_keystore.json"
        _real_key, _dek = _provision_on_original_machine(keystore)
        env_on_B = DekEnvelope.load(sealer=_NoTpmSealer(), keystore_path=keystore)
        # Well-formed hex, correct length, but the WRONG key → auth failure.
        wrong = recovery_key_store.to_hex(generate_recovery_key())
        with pytest.raises(DekEnvelopeError):
            env_on_B.unseal_via_recovery_hex(wrong)
