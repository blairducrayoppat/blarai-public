"""
Weight Integrity Verification Tests
======================================
P1.3: Validates compute_sha256, load_manifest, and verify_weight_integrity
against the Known-Good Manifest pattern.

Test groups:
  A. compute_sha256 (3 tests) — hash correctness on real temp files.
  B. load_manifest (6 tests) — JSON parsing, error handling.
  C. verify_weight_integrity (5 tests) — end-to-end verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from shared.models.weight_integrity import (
    IntegrityCheckResult,
    compute_sha256,
    load_manifest,
    verify_weight_integrity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_temp(content: bytes, suffix: str = ".bin") -> str:
    """Write bytes to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, content)
    os.close(fd)
    return path


def _write_manifest(digests: dict[str, str], suffix: str = ".json") -> str:
    """Write a manifest JSON and return the path."""
    data = {"version": "1.0.0", "digests": digests}
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, json.dumps(data).encode("utf-8"))
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# Group A: compute_sha256
# ---------------------------------------------------------------------------


class TestComputeSha256:
    """Verify SHA-256 digest computation on real files."""

    def test_known_content(self) -> None:
        """SHA-256 of known bytes matches hashlib reference."""
        content = b"BlarAI weight integrity test data"
        expected = hashlib.sha256(content).hexdigest()
        path = _write_temp(content)
        try:
            assert compute_sha256(path) == expected
        finally:
            os.unlink(path)

    def test_empty_file(self) -> None:
        """SHA-256 of an empty file is the well-known empty digest."""
        empty_digest = hashlib.sha256(b"").hexdigest()
        path = _write_temp(b"")
        try:
            assert compute_sha256(path) == empty_digest
        finally:
            os.unlink(path)

    def test_missing_file_raises(self) -> None:
        """Missing file raises OSError."""
        with pytest.raises(OSError):
            compute_sha256("/nonexistent/path/model.bin")


# ---------------------------------------------------------------------------
# Group B: load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    """Verify manifest JSON loading and validation."""

    def test_valid_manifest(self) -> None:
        """Well-formed manifest returns dict of filename → digest."""
        digests = {"model.bin": "abcdef1234567890" * 4}
        path = _write_manifest(digests)
        try:
            result = load_manifest(path)
            assert result is not None
            assert result["model.bin"] == "abcdef1234567890" * 4
        finally:
            os.unlink(path)

    def test_uppercase_digest_normalized(self) -> None:
        """Manifest digests are normalized to lowercase."""
        digests = {"model.bin": "AABBCCDD"}
        path = _write_manifest(digests)
        try:
            result = load_manifest(path)
            assert result is not None
            assert result["model.bin"] == "aabbccdd"
        finally:
            os.unlink(path)

    def test_missing_file_returns_none(self) -> None:
        """Missing manifest file returns None (Fail-Closed)."""
        assert load_manifest("/nonexistent/manifest.json") is None

    def test_malformed_json_returns_none(self) -> None:
        """Invalid JSON returns None."""
        path = _write_temp(b"not valid json{{{", suffix=".json")
        try:
            assert load_manifest(path) is None
        finally:
            os.unlink(path)

    def test_missing_digests_key_returns_none(self) -> None:
        """JSON without 'digests' key returns None."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, json.dumps({"version": "1.0"}).encode())
        os.close(fd)
        try:
            assert load_manifest(path) is None
        finally:
            os.unlink(path)

    def test_non_string_value_returns_none(self) -> None:
        """Manifest with non-string digest value returns None."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, json.dumps({"digests": {"model.bin": 12345}}).encode())
        os.close(fd)
        try:
            assert load_manifest(path) is None
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Group C: verify_weight_integrity (end-to-end)
# ---------------------------------------------------------------------------


class TestVerifyWeightIntegrity:
    """End-to-end verification with real temp files."""

    def test_matching_digest_passes(self) -> None:
        """Correct digest → verified=True, no error."""
        content = b"valid model weights for PA classifier"
        model_path = _write_temp(content, suffix=".bin")
        try:
            expected_digest = hashlib.sha256(content).hexdigest()
            manifest_path = _write_manifest(
                {Path(model_path).name: expected_digest}
            )
            try:
                result = verify_weight_integrity(model_path, manifest_path)
                assert result.verified is True
                assert result.error is None
                assert result.computed_digest == expected_digest
                assert result.expected_digest == expected_digest
                assert result.model_path == model_path
            finally:
                os.unlink(manifest_path)
        finally:
            os.unlink(model_path)

    def test_mismatching_digest_fails(self) -> None:
        """Wrong expected digest → verified=False with mismatch error."""
        content = b"actual weight data"
        model_path = _write_temp(content, suffix=".bin")
        try:
            manifest_path = _write_manifest(
                {Path(model_path).name: "0" * 64}
            )
            try:
                result = verify_weight_integrity(model_path, manifest_path)
                assert result.verified is False
                assert result.error is not None
                assert "mismatch" in result.error.lower()
                assert result.computed_digest != "0" * 64
            finally:
                os.unlink(manifest_path)
        finally:
            os.unlink(model_path)

    def test_missing_model_file(self) -> None:
        """Nonexistent model file → verified=False with IO error."""
        manifest_path = _write_manifest({"ghost.bin": "a" * 64})
        try:
            result = verify_weight_integrity(
                "/nonexistent/ghost.bin", manifest_path
            )
            assert result.verified is False
            assert result.error is not None
            assert "io error" in result.error.lower() or "not found" in result.error.lower()
        finally:
            os.unlink(manifest_path)

    def test_missing_manifest_file(self) -> None:
        """Nonexistent manifest → verified=False."""
        content = b"model data"
        model_path = _write_temp(content, suffix=".bin")
        try:
            result = verify_weight_integrity(
                model_path, "/no/such/manifest.json"
            )
            assert result.verified is False
            assert "manifest" in result.error.lower()
        finally:
            os.unlink(model_path)

    def test_model_not_in_manifest(self) -> None:
        """Manifest exists but does not contain the model filename."""
        content = b"model data"
        model_path = _write_temp(content, suffix=".bin")
        try:
            manifest_path = _write_manifest(
                {"other_model.bin": "a" * 64}
            )
            try:
                result = verify_weight_integrity(model_path, manifest_path)
                assert result.verified is False
                assert "not found in manifest" in result.error.lower()
            finally:
                os.unlink(manifest_path)
        finally:
            os.unlink(model_path)
