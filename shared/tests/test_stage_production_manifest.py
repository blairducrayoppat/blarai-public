"""Tests for shared.models.stage_production_manifest (EA-4a, Sprint 15).

All tests use tmp_path — no real model files, no real keystore touched.

Test groups:
  A. stage_manifest() success path — hashes files, writes manifest correctly
  B. stage_manifest() fail-closed paths — missing dir, no .bin files, write error
  C. Idempotence — re-running overwrites manifest with same result
  D. Atomic write — .tmp file is cleaned up on error; no partial manifest
  E. Integration — main() reads env overrides and calls stage_manifest
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.models import stage_production_manifest as spm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bin_files(model_dir: Path, *names_and_contents: tuple[str, bytes]) -> dict[str, str]:
    """Write .bin files and return {filename: expected_sha256}."""
    model_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name, content in names_and_contents:
        p = model_dir / name
        p.write_bytes(content)
        digests[name] = hashlib.sha256(content).hexdigest()
    return digests


# ---------------------------------------------------------------------------
# Group A: Success path
# ---------------------------------------------------------------------------


class TestStagingSuccess:
    """stage_manifest() writes correct manifest when model files are present."""

    def test_writes_manifest_with_correct_digests(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        expected = _make_bin_files(
            model_dir,
            ("openvino_model.bin", b"model bytes here"),
            ("openvino_tokenizer.bin", b"tokenizer bytes here"),
        )
        manifest_path = tmp_path / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 0
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["version"] == "1.0.0"
        assert data["digests"] == expected

    def test_single_bin_file(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        expected = _make_bin_files(
            model_dir,
            ("openvino_model.bin", b"only one file"),
        )
        manifest_path = tmp_path / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 0
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["digests"]["openvino_model.bin"] == expected["openvino_model.bin"]

    def test_manifest_has_no_stub_notice(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        _make_bin_files(model_dir, ("openvino_model.bin", b"model"))
        manifest_path = tmp_path / "manifest.json"

        spm.stage_manifest(model_dir, manifest_path)

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "_stub_notice" not in data

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        _make_bin_files(model_dir, ("openvino_model.bin", b"data"))
        manifest_path = tmp_path / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 0

    def test_creates_parent_dirs_if_absent(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "nested" / "model"
        _make_bin_files(model_dir, ("openvino_model.bin", b"data"))
        manifest_path = tmp_path / "nested" / "model" / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 0
        assert manifest_path.exists()


# ---------------------------------------------------------------------------
# Group B: Fail-closed paths
# ---------------------------------------------------------------------------


class TestStagingFailClosed:
    """stage_manifest() returns 1 and writes nothing when preconditions fail."""

    def test_model_dir_absent_returns_one(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "does_not_exist"
        manifest_path = tmp_path / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 1
        assert not manifest_path.exists()

    def test_no_bin_files_returns_one(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        # Write only a non-.bin file
        (model_dir / "config.json").write_text("{}", encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 1
        assert not manifest_path.exists()

    def test_unreadable_bin_returns_one_no_partial_write(
        self, tmp_path: Path
    ) -> None:
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        good = model_dir / "openvino_model.bin"
        good.write_bytes(b"good file")
        bad = model_dir / "openvino_tokenizer.bin"
        bad.write_bytes(b"bad file")

        manifest_path = tmp_path / "manifest.json"

        # Simulate a read error on the second file by patching compute_sha256
        original_compute = spm.compute_sha256

        def _failing_compute(path: Path, chunk_size: int = 65_536) -> str:
            if "tokenizer" in str(path):
                raise OSError("simulated read error")
            return original_compute(path)

        with patch.object(spm, "compute_sha256", side_effect=_failing_compute):
            rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 1
        # No partial manifest written
        assert not manifest_path.exists()
        # No .tmp file left over
        assert not manifest_path.with_suffix(".json.tmp").exists()


# ---------------------------------------------------------------------------
# Group C: Idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    """Running stage_manifest() twice produces the same manifest."""

    def test_second_run_overwrites_first(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        expected = _make_bin_files(model_dir, ("openvino_model.bin", b"stable content"))
        manifest_path = tmp_path / "manifest.json"

        rc1 = spm.stage_manifest(model_dir, manifest_path)
        rc2 = spm.stage_manifest(model_dir, manifest_path)

        assert rc1 == 0
        assert rc2 == 0
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["digests"] == expected


# ---------------------------------------------------------------------------
# Group D: Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """No partial manifest is left behind on a write failure."""

    def test_tmp_file_cleaned_up_on_write_error(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "model"
        _make_bin_files(model_dir, ("openvino_model.bin", b"data"))
        manifest_path = tmp_path / "manifest.json"

        # Simulate an error during the atomic replace step.
        # The stager uses Path.replace() (not rename) for idempotent overwrites.
        def _failing_replace(self: Path, target: object) -> None:
            raise OSError("simulated replace failure")

        with patch.object(Path, "replace", _failing_replace):
            rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 1
        # Neither the final manifest nor a leftover .tmp should survive
        assert not manifest_path.exists()
        assert not manifest_path.with_suffix(".json.tmp").exists()


# ---------------------------------------------------------------------------
# Group E: Integration — main() env override
# ---------------------------------------------------------------------------


class TestMainEnvOverride:
    """main() reads BLARAI_MODEL_DIR + BLARAI_MANIFEST_PATH from env."""

    def test_main_with_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model_dir = tmp_path / "env_model"
        _make_bin_files(model_dir, ("openvino_model.bin", b"env-override model"))
        manifest_path = tmp_path / "env_manifest.json"

        monkeypatch.setenv("BLARAI_MODEL_DIR", str(model_dir))
        monkeypatch.setenv("BLARAI_MANIFEST_PATH", str(manifest_path))

        rc = spm.main()

        assert rc == 0
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "openvino_model.bin" in data["digests"]

    def test_main_missing_model_dir_returns_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLARAI_MODEL_DIR", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("BLARAI_MANIFEST_PATH", str(tmp_path / "manifest.json"))

        rc = spm.main()

        assert rc == 1


# ---------------------------------------------------------------------------
# Group F: Nested stager (UC-010 WS1 — diffusers-OV / SDXL layout)
# stage_manifest_nested walks subdirs and hashes .bin + .xml + model_index.json
# keyed by relative POSIX path; main() dispatches to it on --nested /
# BLARAI_MANIFEST_NESTED. The flat 14B stager stays .bin-only and unchanged.
# ---------------------------------------------------------------------------


def _make_nested_model(model_dir: Path) -> dict[str, str]:
    """Stage a minimal nested SDXL-shaped model + return the expected
    {relative-posix-path: sha256} digest map for the three swept kinds."""
    (model_dir / "unet").mkdir(parents=True, exist_ok=True)
    bin_payload = b"unet weights"
    xml_payload = b"<net>unet topology</net>"
    idx_payload = b'{"_class_name": "StableDiffusionXLPipeline"}'
    (model_dir / "unet" / "openvino_model.bin").write_bytes(bin_payload)
    (model_dir / "unet" / "openvino_model.xml").write_bytes(xml_payload)
    (model_dir / "model_index.json").write_bytes(idx_payload)
    return {
        "unet/openvino_model.bin": hashlib.sha256(bin_payload).hexdigest(),
        "unet/openvino_model.xml": hashlib.sha256(xml_payload).hexdigest(),
        "model_index.json": hashlib.sha256(idx_payload).hexdigest(),
    }


class TestNestedStager:
    """stage_manifest_nested() — relative-path digests covering .bin/.xml/index."""

    def test_stage_manifest_nested_hashes_bin_xml_and_index(
        self, tmp_path: Path
    ) -> None:
        """Nested dir ⇒ rc==0; manifest digest KEYS == the 3 relative POSIX paths
        with correct SHA-256; AND the produced manifest round-trips through
        verify_all_manifest_entries_nested ⇒ all_verified True."""
        from shared.models.weight_integrity import verify_all_manifest_entries_nested

        model_dir = tmp_path / "model"
        expected = _make_nested_model(model_dir)
        manifest_path = model_dir / "manifest.json"

        rc = spm.stage_manifest_nested(model_dir, manifest_path)

        assert rc == 0
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["digests"] == expected
        assert set(data["digests"]) == {
            "unet/openvino_model.bin",
            "unet/openvino_model.xml",
            "model_index.json",
        }
        # Round-trip: the staged manifest must satisfy the nested verifier (the
        # manifest.json sitting in model_dir is NOT swept, so it is not an extra).
        result = verify_all_manifest_entries_nested(model_dir, manifest_path)
        assert result.all_verified is True
        assert result.error is None

    def test_flat_stage_manifest_unchanged_bin_only(self, tmp_path: Path) -> None:
        """The FLAT stage_manifest still hashes ONLY top-dir *.bin — an .xml in
        the dir is NOT added (regression lock: the 14B stager is unaffected)."""
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        (model_dir / "openvino_model.bin").write_bytes(b"flat weights")
        # An .xml (and a model_index.json) in the SAME dir must be ignored.
        (model_dir / "openvino_model.xml").write_bytes(b"<net/>")
        (model_dir / "model_index.json").write_bytes(b"{}")
        manifest_path = tmp_path / "manifest.json"

        rc = spm.stage_manifest(model_dir, manifest_path)

        assert rc == 0
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert set(data["digests"]) == {"openvino_model.bin"}
        assert "openvino_model.xml" not in data["digests"]
        assert "model_index.json" not in data["digests"]

    def test_main_nested_flag_dispatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main(['--nested']) routes to the nested stager — asserted via
        BLARAI_MODEL_DIR/BLARAI_MANIFEST_PATH env overrides on a tmp nested dir
        (the flat stager would refuse: a nested dir has no TOP-LEVEL *.bin)."""
        model_dir = tmp_path / "nested_model"
        expected = _make_nested_model(model_dir)
        manifest_path = tmp_path / "nested_manifest.json"
        monkeypatch.setenv("BLARAI_MODEL_DIR", str(model_dir))
        monkeypatch.setenv("BLARAI_MANIFEST_PATH", str(manifest_path))

        rc = spm.main(["--nested"])

        assert rc == 0
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Relative-path keys prove the NESTED stager ran (the flat stager keys by
        # bare name and would have found NO top-level *.bin here → rc 1).
        assert data["digests"] == expected
        assert "unet/openvino_model.bin" in data["digests"]

    def test_main_nested_env_flag_dispatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BLARAI_MANIFEST_NESTED=1 (no argv flag) also routes to the nested
        stager — the env-driven dispatch branch."""
        model_dir = tmp_path / "nested_env_model"
        expected = _make_nested_model(model_dir)
        manifest_path = tmp_path / "nested_env_manifest.json"
        monkeypatch.setenv("BLARAI_MODEL_DIR", str(model_dir))
        monkeypatch.setenv("BLARAI_MANIFEST_PATH", str(manifest_path))
        monkeypatch.setenv("BLARAI_MANIFEST_NESTED", "1")

        rc = spm.main([])

        assert rc == 0
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["digests"] == expected
