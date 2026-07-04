"""Tests for the at-rest encryption DEK keystore provisioning ceremony (ADR-025).

All tests run against SoftwareSealer + a temporary keystore path — no real TPM
required.  The on-chip path is covered by the @pytest.mark.slow class at the
bottom.

Coverage:
- Provisioning creates a loadable keystore; DEK round-trips via both paths.
- Recovery key unseals the same DEK as the TPM path (central ADR-025 §2.1 guarantee).
- --rotate allows a fresh DEK; without --rotate existing keystore is refused (clobber guard).
- --recover flow: load old keystore via recovery key → re-seal → new keystore round-trips.
- Recovery key is NOT written to disk.
- No real secret appears in stdout/stderr (recovery hex is a test key — confirmed non-empty
  but not echoed into logs in an unsafe way).
- Audit signing key is provisioned within the ceremony.
- Mutually exclusive flags (--rotate + --recover → error).
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers for monkeypatching the TPM surfaces the ceremony calls
# ---------------------------------------------------------------------------


def _patch_tpm_sealer_available(value: bool):
    """Context-manager patch: tpm_sealer.is_available()."""
    from shared.security import tpm_sealer
    return patch.object(tpm_sealer, "is_available", return_value=value)


def _patch_tpm_signer_available(value: bool):
    """Context-manager patch: tpm_signer.is_available()."""
    from shared.security import tpm_signer
    return patch.object(tpm_signer, "is_available", return_value=value)


# ---------------------------------------------------------------------------
# Fixture: monkeypatched ceremony module that routes TPM calls to SoftwareSealer
# ---------------------------------------------------------------------------


@pytest.fixture()
def software_ceremony(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Patch the ceremony so every TpmSealer() call returns a SoftwareSealer.

    This lets us exercise the full provision/recover logic on any machine without
    a TPM.  The SoftwareSealer satisfies the Sealer protocol; the DEK lifecycle
    is real.  The only thing bypassed is the CNG ncrypt.dll layer.

    Patches:
      - tpm_sealer.is_available → True
      - tpm_sealer.ensure_key → True  (idempotent "created")
      - tpm_signer.ensure_key → True
      - provision_dek_keystore.TpmSealer → SoftwareSealer()
      - provision_dek_keystore.build_envelope → dev_mode=True forced
      - provision_dek_keystore.reseal_dek → dev_mode=True forced
        (so the SoftwareSealer test stub passes the dev_mode guard in
        dek_envelope.py for BOTH the provision and recover paths)
    """
    from shared.security import tpm_sealer, tpm_signer, provision_dek_keystore as pdk
    from shared.security import dek_envelope as _dek_env
    from shared.security.tpm_sealer import SoftwareSealer

    # Route all TpmSealer(key_name=...) construction to SoftwareSealer.
    monkeypatch.setattr(pdk, "TpmSealer", lambda *args, **kwargs: SoftwareSealer())

    # Force dev_mode=True in build_envelope so SoftwareSealer is allowed.
    _original_build = _dek_env.build_envelope

    def _sw_build_envelope(*, sealer, recovery_key, keystore_path, dev_mode=False):
        return _original_build(
            sealer=sealer,
            recovery_key=recovery_key,
            keystore_path=keystore_path,
            dev_mode=True,  # always dev_mode in test context
        )

    monkeypatch.setattr(pdk, "build_envelope", _sw_build_envelope)

    # Force dev_mode=True in reseal_dek so SoftwareSealer is allowed on the
    # recover() path (mirrors the build_envelope patch above).
    _original_reseal = _dek_env.reseal_dek

    def _sw_reseal_dek(dek, *, sealer, recovery_key, dev_mode=False):
        return _original_reseal(
            dek,
            sealer=sealer,
            recovery_key=recovery_key,
            dev_mode=True,  # always dev_mode in test context
        )

    monkeypatch.setattr(pdk, "reseal_dek", _sw_reseal_dek)

    # TPM availability is True so the is_available() gate passes.
    monkeypatch.setattr(tpm_sealer, "is_available", lambda: True)

    # ensure_key() calls succeed and report "created".
    monkeypatch.setattr(tpm_sealer, "ensure_key", lambda _name: True)
    monkeypatch.setattr(tpm_signer, "ensure_key", lambda _name: True)

    keystore = tmp_path / "dek_keystore.json"
    return {"pdk": pdk, "keystore": keystore, "tmp_path": tmp_path}


# ---------------------------------------------------------------------------
# Core provisioning tests
# ---------------------------------------------------------------------------


class TestProvision:
    """Happy-path provisioning and clobber guard."""

    def test_creates_loadable_keystore(self, software_ceremony: dict) -> None:
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        rc = pdk.provision(keystore)

        assert rc == 0
        assert keystore.exists()

    def test_keystore_is_valid_json(self, software_ceremony: dict) -> None:
        import json
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        pdk.provision(keystore)

        doc = json.loads(keystore.read_text(encoding="utf-8"))
        assert "tpm_wrap_v1" in doc
        assert "recovery_wrap_v1" in doc

    def test_dek_round_trips_via_both_paths(self, software_ceremony: dict) -> None:
        """Both TPM-stub path and recovery path unseal the IDENTICAL DEK."""
        from shared.security.dek_envelope import DekEnvelope
        from shared.security.tpm_sealer import SoftwareSealer

        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        # Capture the recovery key that was generated during provisioning so we
        # can use it to verify the recovery path.  We do this by intercepting
        # generate_recovery_key() and storing the result.
        captured: dict = {}
        original_gen = pdk.generate_recovery_key

        def _capture_gen():
            key = original_gen()
            captured["key"] = key
            return key

        with patch.object(pdk, "generate_recovery_key", side_effect=_capture_gen):
            rc = pdk.provision(keystore)

        assert rc == 0
        recovery_key = captured["key"]
        assert len(recovery_key) == 32

        # Load the keystore and verify both unseal paths.
        sealer = SoftwareSealer()
        envelope = DekEnvelope.load(sealer=sealer, keystore_path=keystore)

        dek_tpm = envelope.unseal_dek()
        dek_rec = envelope.unseal_dek(recovery_key=recovery_key)

        assert dek_tpm == dek_rec, "TPM-unsealed DEK must equal recovery-unsealed DEK (ADR-025 §2.1)"
        assert len(dek_tpm) == 32

    def test_recovery_key_not_written_to_disk(
        self, software_ceremony: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The recovery key printed to stdout must NOT appear in any file under tmp_path."""
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        rc = pdk.provision(keystore)
        assert rc == 0

        captured = capsys.readouterr()

        # Extract the recovery hex from stdout (it is in the delimited block).
        recovery_line = [
            line.strip()
            for line in captured.out.splitlines()
            if "Recovery key (hex):" in line
        ]
        assert len(recovery_line) == 1, "Expected exactly one recovery key line in output"
        recovery_hex = recovery_line[0].split(":", 1)[1].strip()
        assert len(recovery_hex) == 64, "Recovery key should be 64 hex chars"

        # Now scan every file in tmp_path for the recovery hex — must not be there.
        recovery_bytes = bytes.fromhex(recovery_hex)
        for f in tmp_path.rglob("*"):
            if f.is_file():
                raw = f.read_bytes()
                # Neither the raw bytes nor the hex encoding should appear.
                assert recovery_bytes not in raw, (
                    f"Recovery key bytes found in disk file: {f}"
                )
                assert recovery_hex.encode() not in raw, (
                    f"Recovery key hex found in disk file: {f}"
                )

    def test_clobber_guard_refuses_existing_keystore(
        self, software_ceremony: dict
    ) -> None:
        """Without --rotate, provision() refuses if the keystore already exists."""
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        # First provision succeeds.
        rc1 = pdk.provision(keystore)
        assert rc1 == 0

        # Second provision without rotate must fail.
        rc2 = pdk.provision(keystore, rotate=False)
        assert rc2 == 1

    def test_rotate_replaces_existing_keystore(
        self, software_ceremony: dict
    ) -> None:
        """With rotate=True, provision() replaces the keystore with a fresh DEK."""
        import json

        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        pdk.provision(keystore)
        first_doc = json.loads(keystore.read_text(encoding="utf-8"))

        rc = pdk.provision(keystore, rotate=True)
        assert rc == 0

        second_doc = json.loads(keystore.read_text(encoding="utf-8"))
        # The TPM wrap blob should be different (new DEK = new sealed blob).
        assert first_doc["tpm_wrap_v1"] != second_doc["tpm_wrap_v1"], (
            "--rotate must produce a fresh DEK (different TPM wrap)"
        )

    def test_fail_closed_without_tpm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from shared.security import tpm_sealer, provision_dek_keystore as pdk

        monkeypatch.setattr(tpm_sealer, "is_available", lambda: False)

        keystore = tmp_path / "ks.json"
        rc = pdk.provision(keystore)

        assert rc == 1
        assert not keystore.exists()

    def test_provisions_audit_key(
        self, software_ceremony: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ceremony calls tpm_signer.ensure_key for the audit key."""
        from shared.security import tpm_signer
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        audit_calls: list[str] = []
        original = tpm_signer.ensure_key
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda name: audit_calls.append(name) or True)

        rc = pdk.provision(keystore)

        assert rc == 0
        from shared.security.audit_log import AUDIT_TPM_KEY_NAME
        assert AUDIT_TPM_KEY_NAME in audit_calls, (
            f"Audit key {AUDIT_TPM_KEY_NAME!r} not provisioned; calls: {audit_calls}"
        )

    def test_banner_and_status_in_stdout(
        self, software_ceremony: dict, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        rc = pdk.provision(keystore)
        out = capsys.readouterr().out

        assert rc == 0
        assert "ADR-025" in out
        assert "BlarAI-DEKSeal" in out
        assert "PASS" in out
        assert "RECOVERY KEY" in out
        assert "Ceremony Complete" in out


# ---------------------------------------------------------------------------
# main() / argparse tests
# ---------------------------------------------------------------------------


class TestMain:
    """CLI surface and flag validation."""

    def test_main_default_path_invokes_provision(
        self, software_ceremony: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pdk = software_ceremony["pdk"]
        keystore = tmp_path / "ks.json"
        monkeypatch.setattr(pdk, "_default_keystore_path", lambda: keystore)

        rc = pdk.main([])
        assert rc == 0
        assert keystore.exists()

    def test_main_explicit_keystore_path(
        self, software_ceremony: dict, tmp_path: Path
    ) -> None:
        pdk = software_ceremony["pdk"]
        keystore = tmp_path / "custom.json"

        rc = pdk.main(["--keystore-path", str(keystore)])
        assert rc == 0
        assert keystore.exists()

    def test_main_rotate_flag(
        self, software_ceremony: dict, tmp_path: Path
    ) -> None:
        import json

        pdk = software_ceremony["pdk"]
        keystore = tmp_path / "ks.json"

        pdk.main(["--keystore-path", str(keystore)])
        first = json.loads(keystore.read_text(encoding="utf-8"))

        rc = pdk.main(["--keystore-path", str(keystore), "--rotate"])
        assert rc == 0
        second = json.loads(keystore.read_text(encoding="utf-8"))
        assert first["tpm_wrap_v1"] != second["tpm_wrap_v1"]

    def test_main_rotate_and_recover_are_mutually_exclusive(
        self, software_ceremony: dict, tmp_path: Path
    ) -> None:
        pdk = software_ceremony["pdk"]
        keystore = tmp_path / "ks.json"

        rc = pdk.main(["--keystore-path", str(keystore), "--rotate", "--recover"])
        assert rc == 1


# ---------------------------------------------------------------------------
# --recover path tests
# ---------------------------------------------------------------------------


class TestRecover:
    """Recovery ceremony: re-seal existing DEK after chip replacement."""

    def _make_old_keystore(
        self, pdk: Any, keystore: Path
    ) -> tuple[bytes, str]:
        """Provision a fresh keystore and capture the recovery key hex.

        Returns (recovery_key_bytes, recovery_hex).
        """
        captured: dict = {}
        original_gen = pdk.generate_recovery_key

        def _capture():
            key = original_gen()
            captured["key"] = key
            return key

        with patch.object(pdk, "generate_recovery_key", side_effect=_capture):
            pdk.provision(keystore)

        rk = captured["key"]
        return rk, rk.hex()

    def test_recover_reseals_and_new_keystore_round_trips(
        self, software_ceremony: dict
    ) -> None:
        """After recover(), the new keystore unseals via the new TPM-stub path."""
        from shared.security.dek_envelope import DekEnvelope
        from shared.security.tpm_sealer import SoftwareSealer

        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        # Provision the initial keystore.
        rk, rk_hex = self._make_old_keystore(pdk, keystore)

        # Recover (simulate chip replacement — same SoftwareSealer since no
        # real TPM; the new sealer is also a SoftwareSealer via the fixture).
        # We must also capture the NEW recovery key that recover() generates.
        new_rk_captured: dict = {}
        original_gen = pdk.generate_recovery_key

        def _capture_new():
            key = original_gen()
            new_rk_captured["key"] = key
            return key

        with patch("getpass.getpass", return_value=rk_hex), \
             patch.object(pdk, "generate_recovery_key", side_effect=_capture_new):
            rc = pdk.recover(keystore)

        assert rc == 0

        # Load the new keystore and verify the TPM-stub path works.
        new_sealer = SoftwareSealer()
        env = DekEnvelope.load(sealer=new_sealer, keystore_path=keystore)
        dek_new_tpm = env.unseal_dek()
        assert len(dek_new_tpm) == 32

    def test_recover_wrong_recovery_key_fails_closed(
        self, software_ceremony: dict
    ) -> None:
        """recover() with a wrong recovery key must fail with rc=1.

        recover() now uses ``unseal_via_recovery`` which unwraps the RECOVERY
        wrap ONLY and never attempts the TPM path.  So a wrong recovery key
        fails by-design (DekEnvelopeError from the GCM auth check) regardless
        of any sealer — no DeadSealer / catch-order trickery is needed.
        """
        from shared.security import provision_dek_keystore as pdk

        keystore: Path = software_ceremony["keystore"]
        self._make_old_keystore(pdk, keystore)

        wrong_hex = "ab" * 32  # 64 hex chars but wrong key
        with patch("getpass.getpass", return_value=wrong_hex):
            rc = pdk.recover(keystore)

        assert rc == 1

    def test_recover_dead_chip_success_recovers_same_dek(
        self, software_ceremony: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REAL dead-chip recovery SUCCESS: the old TPM wrap is UNUSABLE, yet the
        correct recovery key recovers the SAME DEK, which is re-sealed under a
        NEW working sealer whose keystore round-trips via the TPM path.

        This is the load-bearing break-glass test the round-1 merge gate asked
        for.  Unlike ``test_recover_reseals_and_new_keystore_round_trips`` (which
        used a working SoftwareSealer on both ends, so the TPM path could mask
        the recovery path), here the OLD keystore's TPM wrap is sealed by a
        ``DeadSealer`` whose ``unseal`` ALWAYS raises.  recover() therefore
        cannot reach the DEK via the TPM path — only ``unseal_via_recovery``
        (recovery wrap only) can produce it.  We assert:
          1. recover() returns 0,
          2. the recovered DEK equals the original DEK we sealed in,
          3. the OLD TPM path is provably dead (DeadSealer.unseal raises),
          4. the new keystore unseals via a fresh working sealer (TPM path) AND
             yields that same DEK.
        """
        import os as _os
        from shared.security import provision_dek_keystore as pdk
        from shared.security import dek_envelope as _dek_env
        from shared.security.dek_envelope import (
            DekEnvelope,
            _wrap_dek_dual,
            _recovery_unwrap,
        )
        from shared.security.tpm_sealer import SoftwareSealer, TpmSealingError

        keystore: Path = software_ceremony["keystore"]

        # The DEK and recovery key the "original ceremony" produced (known so we
        # can assert byte-identity after recovery).
        original_dek = _os.urandom(32)
        old_recovery_key = _os.urandom(32)
        old_recovery_hex = old_recovery_key.hex()

        # A sealer whose unseal ALWAYS raises — the dead old chip.  Its seal()
        # produces a blob that can never be unsealed (the TPM private half is
        # gone), exactly like a replaced chip.
        class DeadSealer:
            def seal(self, key_material: bytes) -> bytes:
                # Produce a real-shaped blob (so save/load works) but one that
                # this sealer can never unseal again.
                return SoftwareSealer().seal(key_material)

            def unseal(self, blob: bytes) -> bytes:
                raise TpmSealingError("dead old chip — TPM private half is gone")

        # Build the OLD keystore: TPM wrap via DeadSealer, recovery wrap real.
        old_env = _wrap_dek_dual(
            dek=original_dek, sealer=DeadSealer(), recovery_key=old_recovery_key
        )
        old_env.save(keystore)

        # Sanity 1: the OLD keystore's TPM path is genuinely dead — unsealing with
        # no recovery key (TPM path only) is refused fail-closed (the dead-chip
        # TpmSealingError is wrapped into DekEnvelopeError), so the DEK is
        # unreachable via the TPM path.
        reloaded_dead = DekEnvelope.load(sealer=DeadSealer(), keystore_path=keystore)
        from shared.security.dek_envelope import DekEnvelopeError as _DEErr
        with pytest.raises(_DEErr):
            reloaded_dead.unseal_dek()  # no recovery key → only the dead TPM path
        # Sanity 2: the recovery wrap DOES hold the original DEK (the break-glass
        # authority), reachable ONLY via the recovery path.
        assert (
            _recovery_unwrap(old_env.recovery_wrap_record, old_recovery_key)
            == original_dek
        )

        # Capture the NEW recovery key recover() will generate.
        new_rk: dict = {}
        original_gen = pdk.generate_recovery_key

        def _cap():
            key = original_gen()
            new_rk["key"] = key
            return key

        # Run recover() with the CORRECT old recovery key.  The fixture's
        # TpmSealer→SoftwareSealer patch makes the NEW chip a working sealer.
        with patch("getpass.getpass", return_value=old_recovery_hex), \
             patch.object(pdk, "generate_recovery_key", side_effect=_cap):
            rc = pdk.recover(keystore)

        assert rc == 0, "dead-chip recovery with correct key must succeed"

        # The new keystore must unseal via the NEW (working) sealer's TPM path
        # AND yield the SAME DEK we started with — proving unseal_via_recovery
        # produced the real DEK (not a masked/zero value), end to end.
        new_env = DekEnvelope.load(sealer=SoftwareSealer(), keystore_path=keystore)
        recovered_dek = new_env.unseal_dek()
        assert recovered_dek == original_dek, (
            "recovered DEK must equal the original DEK (break-glass identity)"
        )

        # And the new keystore's recovery wrap is bound to the NEW recovery key,
        # and ALSO yields the same DEK (both wraps agree post-reseal).
        assert new_env.unseal_via_recovery(new_rk["key"]) == original_dek

    def test_recover_new_recovery_key_not_written_to_disk(
        self, software_ceremony: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The NEW recovery key printed during recover() must not be on disk."""
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        rk, rk_hex = self._make_old_keystore(pdk, keystore)

        new_rk_captured: dict = {}
        original_gen = pdk.generate_recovery_key

        def _cap():
            key = original_gen()
            new_rk_captured["key"] = key
            return key

        with patch("getpass.getpass", return_value=rk_hex), \
             patch.object(pdk, "generate_recovery_key", side_effect=_cap):
            pdk.recover(keystore)

        captured = capsys.readouterr()
        # Extract new recovery hex from stdout.
        recovery_lines = [
            line.strip()
            for line in captured.out.splitlines()
            if "Recovery key (hex):" in line
        ]
        assert len(recovery_lines) >= 1
        new_rk_hex = recovery_lines[-1].split(":", 1)[1].strip()
        assert len(new_rk_hex) == 64

        new_rk_bytes = bytes.fromhex(new_rk_hex)
        for f in tmp_path.rglob("*"):
            if f.is_file():
                raw = f.read_bytes()
                assert new_rk_bytes not in raw, f"New recovery key bytes found in {f}"
                assert new_rk_hex.encode() not in raw, f"New recovery key hex found in {f}"

    def test_recover_missing_keystore_fails_closed(
        self, software_ceremony: dict, tmp_path: Path
    ) -> None:
        pdk = software_ceremony["pdk"]
        missing = tmp_path / "does_not_exist.json"

        with patch("getpass.getpass", return_value="ab" * 32):
            rc = pdk.recover(missing)

        assert rc == 1

    def test_recover_short_key_input_fails_closed(
        self, software_ceremony: dict
    ) -> None:
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]
        self._make_old_keystore(pdk, keystore)

        # Only 32 hex chars — too short.
        with patch("getpass.getpass", return_value="ab" * 16):
            rc = pdk.recover(keystore)

        assert rc == 1

    def test_recover_with_spaces_in_input_accepted(
        self, software_ceremony: dict, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spaces in the pasted hex are stripped automatically."""
        pdk = software_ceremony["pdk"]
        keystore: Path = software_ceremony["keystore"]

        rk, rk_hex = self._make_old_keystore(pdk, keystore)

        # Insert some spaces into the hex string.
        spaced_hex = " ".join(rk_hex[i:i+8] for i in range(0, len(rk_hex), 8))

        new_rk_captured: dict = {}
        original_gen = pdk.generate_recovery_key

        def _cap():
            key = original_gen()
            new_rk_captured["key"] = key
            return key

        with patch("getpass.getpass", return_value=spaced_hex), \
             patch.object(pdk, "generate_recovery_key", side_effect=_cap):
            rc = pdk.recover(keystore)

        assert rc == 0


# ---------------------------------------------------------------------------
# On-chip: real platform TPM 2.0 (deselected by default; run with -m slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestProvisionOnChip:
    """Full ceremony on the real chip.

    Run with: ``pytest shared/tests/test_provision_dek_keystore.py -m slow``

    Uses throwaway key names (never the production seal key) and cleans up
    after itself.
    """

    _SEAL_KEY = "BlarAI-DEKSeal-PytestHW"
    _AUDIT_KEY = "BlarAI-Audit-Signing-Key-v1-PytestHW"

    @pytest.fixture(autouse=True)
    def _require_tpm(self):
        from shared.security import tpm_sealer
        if not tpm_sealer.is_available():
            pytest.skip("No platform TPM available")
        yield
        # Cleanup — delete the throwaway keys.
        try:
            tpm_sealer.delete_key(self._SEAL_KEY)
        except Exception:
            pass

    @pytest.fixture()
    def on_chip_ceremony(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Patch key names to use throwaway keys; leave everything else real."""
        from shared.security import provision_dek_keystore as pdk
        monkeypatch.setattr(pdk, "DEK_SEAL_KEY_NAME", self._SEAL_KEY)
        keystore = tmp_path / "dek_keystore.json"
        return {"pdk": pdk, "keystore": keystore}

    def test_ceremony_creates_real_tpm_keystore(self, on_chip_ceremony: dict) -> None:
        pdk = on_chip_ceremony["pdk"]
        keystore: Path = on_chip_ceremony["keystore"]

        rc = pdk.provision(keystore)

        assert rc == 0
        assert keystore.exists()
