"""Tests for shared.security.ceremony_preflight (EA-4a, Sprint 15).

All tests use monkeypatch to stub TPM calls and tmp_path for file paths.
No real TPM, no real keystore, no real model files touched.

Test groups:
  A. TPM availability checks (signer + sealer)
  B. TPM key-existence checks
  C. File presence checks (keystore, pa_public.pem)
  D. Manifest checks (missing, stub, model-not-found advisory, digest match/mismatch)
  E. Integration — run_preflight() return codes (all-pass, one-fail, all-fail)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from shared.security import ceremony_preflight as cp
from shared.security import tpm_sealer, tpm_signer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(
    path: Path,
    digests: dict[str, str],
    *,
    stub: bool = False,
) -> None:
    data: dict = {"version": "1.0.0", "digests": digests}
    if stub:
        data["_stub_notice"] = "placeholder"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_model(path: Path, content: bytes = b"fake model binary data") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Group A: TPM availability checks
# ---------------------------------------------------------------------------


class TestTpmAvailability:
    """_check_tpm_sealer and _check_tpm_signer return correct pass/fail."""

    def test_sealer_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "is_available", lambda: True)
        ok, line = cp._check_tpm_sealer()
        assert ok is True
        assert "OK" in line

    def test_sealer_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "is_available", lambda: False)
        ok, line = cp._check_tpm_sealer()
        assert ok is False
        assert "FAIL" in line
        assert "NOT available" in line

    def test_signer_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        ok, line = cp._check_tpm_signer()
        assert ok is True
        assert "OK" in line

    def test_signer_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "is_available", lambda: False)
        ok, line = cp._check_tpm_signer()
        assert ok is False
        assert "FAIL" in line
        assert "NOT available" in line


# ---------------------------------------------------------------------------
# Group B: TPM key-existence checks
# ---------------------------------------------------------------------------


class TestKeyExistence:
    """_check_key returns correct pass/fail for present/absent keys."""

    def test_signer_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: True)
        ok, line = cp._check_key("BlarAI-Audit-Signing-Key-v1", "Audit key", is_signer=True)
        assert ok is True
        assert "OK" in line

    def test_signer_key_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: False)
        ok, line = cp._check_key("BlarAI-Audit-Signing-Key-v1", "Audit key", is_signer=True)
        assert ok is False
        assert "FAIL" in line
        assert "NOT FOUND" in line

    def test_sealer_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_sealer, "key_exists", lambda name: True)
        ok, line = cp._check_key("BlarAI-DEKSeal", "DEK seal key", is_signer=False)
        assert ok is True
        assert "OK" in line

    def test_sealer_key_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_sealer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_sealer, "key_exists", lambda name: False)
        ok, line = cp._check_key("BlarAI-DEKSeal", "DEK seal key", is_signer=False)
        assert ok is False
        assert "FAIL" in line

    def test_tpm_unavailable_returns_warn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tpm_signer, "is_available", lambda: False)
        ok, line = cp._check_key("BlarAI-JWT", "JWT key", is_signer=True)
        assert ok is False
        assert "WARN" in line
        assert "TPM unavailable" in line


# ---------------------------------------------------------------------------
# Group C: File presence checks
# ---------------------------------------------------------------------------


class TestFileChecks:
    """Keystore and pa_public.pem checks."""

    def test_keystore_present(self, tmp_path: Path) -> None:
        ks = tmp_path / "dek_keystore.json"
        ks.write_text("{}", encoding="utf-8")
        ok, line = cp._check_keystore(ks)
        assert ok is True
        assert "OK" in line

    def test_keystore_absent(self, tmp_path: Path) -> None:
        ks = tmp_path / "dek_keystore.json"
        ok, line = cp._check_keystore(ks)
        assert ok is False
        assert "FAIL" in line
        assert "NOT FOUND" in line

    def test_pa_public_pem_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pem = tmp_path / "pa_public.pem"
        pem.write_text("-----BEGIN PUBLIC KEY-----\n", encoding="utf-8")
        monkeypatch.setattr(cp, "_PA_PUBLIC_PEM", pem)
        ok, line = cp._check_pa_public_pem()
        assert ok is True
        assert "OK" in line

    def test_pa_public_pem_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pem = tmp_path / "pa_public.pem"
        monkeypatch.setattr(cp, "_PA_PUBLIC_PEM", pem)
        ok, line = cp._check_pa_public_pem()
        assert ok is False
        assert "FAIL" in line
        assert "NOT FOUND" in line


# ---------------------------------------------------------------------------
# Group D: Manifest checks
# ---------------------------------------------------------------------------


class TestManifestCheck:
    """_check_manifest covers absent / stub / no-model-advisory / match / mismatch."""

    def test_manifest_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        manifest = tmp_path / "manifest.json"
        model_bin = tmp_path / "openvino_model.bin"
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)
        ok, line = cp._check_manifest()
        assert ok is False
        assert "FAIL" in line
        assert "NOT FOUND" in line

    def test_manifest_stub_placeholder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        manifest = tmp_path / "manifest.json"
        model_bin = tmp_path / "openvino_model.bin"
        _write_manifest(manifest, {"openvino_model.bin": "a" * 64}, stub=True)
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)
        ok, line = cp._check_manifest()
        assert ok is False
        assert "FAIL" in line
        assert "stub" in line.lower()

    def test_manifest_present_model_absent_advisory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        manifest = tmp_path / "manifest.json"
        model_bin = tmp_path / "openvino_model.bin"
        _write_manifest(manifest, {"openvino_model.bin": "a" * 64})
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)
        # model_bin does NOT exist
        ok, line = cp._check_manifest()
        # INFO advisory — reported as ok=True (not a hard failure)
        assert ok is True
        assert "INFO" in line
        assert "not verified" in line.lower() or "digest not verified" in line.lower()

    def test_manifest_digest_match(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        model_bin = tmp_path / "openvino_model.bin"
        content = b"real qwen3 model data"
        correct_digest = _write_model(model_bin, content)

        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"openvino_model.bin": correct_digest})
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)

        ok, line = cp._check_manifest()
        assert ok is True
        assert "OK" in line
        assert "digest verified" in line.lower()

    def test_manifest_digest_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        model_bin = tmp_path / "openvino_model.bin"
        _write_model(model_bin, b"real model data")

        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"openvino_model.bin": "0" * 64})
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)

        ok, line = cp._check_manifest()
        assert ok is False
        assert "FAIL" in line
        assert "MISMATCH" in line.upper()

    def test_manifest_missing_entry_for_model(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        model_bin = tmp_path / "openvino_model.bin"
        _write_model(model_bin, b"model data")

        manifest = tmp_path / "manifest.json"
        # Manifest exists but has NO entry for openvino_model.bin
        _write_manifest(manifest, {"other_file.bin": "a" * 64})
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)

        ok, line = cp._check_manifest()
        assert ok is False
        assert "FAIL" in line


# ---------------------------------------------------------------------------
# Group E: Integration — run_preflight() return codes
# ---------------------------------------------------------------------------


class TestRunPreflightIntegration:
    """run_preflight() integrates all checks and returns correct exit codes."""

    def _all_pass_monkeypatches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Patch every external dependency to report success."""
        # TPM availability
        monkeypatch.setattr(tpm_sealer, "is_available", lambda: True)
        monkeypatch.setattr(tpm_signer, "is_available", lambda: True)
        # TPM key existence
        monkeypatch.setattr(tpm_sealer, "key_exists", lambda name: True)
        monkeypatch.setattr(tpm_signer, "key_exists", lambda name: True)

        # DEK keystore
        ks = tmp_path / "dek_keystore.json"
        ks.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(cp, "_default_keystore_path", lambda: ks)

        # pa_public.pem
        pem = tmp_path / "pa_public.pem"
        pem.write_text("-----BEGIN PUBLIC KEY-----\n", encoding="utf-8")
        monkeypatch.setattr(cp, "_PA_PUBLIC_PEM", pem)

        # Manifest with a matching digest (model binary present)
        model_bin = tmp_path / "openvino_model.bin"
        content = b"mock model weights"
        digest = _write_model(model_bin, content)
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"openvino_model.bin": digest})
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)

    def test_all_pass_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._all_pass_monkeypatches(monkeypatch, tmp_path)
        rc = cp.run_preflight()
        captured = capsys.readouterr()
        assert rc == 0
        assert "READY for production boot" in captured.out

    def test_tpm_unavailable_returns_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._all_pass_monkeypatches(monkeypatch, tmp_path)
        # Override TPM sealer to be unavailable
        monkeypatch.setattr(tpm_sealer, "is_available", lambda: False)
        rc = cp.run_preflight()
        captured = capsys.readouterr()
        assert rc == 1
        assert "NOT READY" in captured.out

    def test_keystore_missing_returns_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._all_pass_monkeypatches(monkeypatch, tmp_path)
        # Override keystore to point at a nonexistent file
        monkeypatch.setattr(cp, "_default_keystore_path", lambda: tmp_path / "no_ks.json")
        rc = cp.run_preflight()
        captured = capsys.readouterr()
        assert rc == 1
        assert "NOT READY" in captured.out

    def test_manifest_digest_mismatch_returns_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._all_pass_monkeypatches(monkeypatch, tmp_path)
        # Override manifest to have wrong digest
        model_bin = tmp_path / "openvino_model.bin"
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"openvino_model.bin": "0" * 64})
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)
        rc = cp.run_preflight()
        captured = capsys.readouterr()
        assert rc == 1
        assert "NOT READY" in captured.out

    def test_manifest_advisory_not_a_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Model absent + valid manifest → INFO advisory, not a hard failure (still READY)."""
        self._all_pass_monkeypatches(monkeypatch, tmp_path)
        # Override manifest to have a valid (non-stub) manifest, but model binary absent
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, {"openvino_model.bin": "a" * 64})
        model_bin = tmp_path / "openvino_model_absent.bin"  # does not exist
        monkeypatch.setattr(cp, "_MANIFEST_RELATIVE", manifest)
        monkeypatch.setattr(cp, "_PRIMARY_MODEL_BIN", model_bin)
        rc = cp.run_preflight()
        captured = capsys.readouterr()
        assert rc == 0
        assert "READY for production boot" in captured.out
