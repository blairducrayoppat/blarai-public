"""
Multi-entry Weight Integrity Sweep Tests
=========================================
Sprint 16, SDV criterion #2 / #106 (partial).

Verifies ``verify_all_manifest_entries`` and the updated ``load_model()`` paths
in both PolicyGPUInference (PA) and OrchestratorGPUInference (AO).

Test groups:
  A. ``verify_all_manifest_entries`` — core sweep function (4 scenarios).
  B. PA ``load_model()`` — integrity gate integration (2 scenarios).
  C. AO ``load_model()`` — integrity gate integration (2 scenarios).

All tests use temp directories only.  Never touches real user data
(the root conftest.py redirects LOCALAPPDATA before collection).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from shared.models.weight_integrity import (
    ManifestSweepResult,
    verify_all_manifest_entries,
    verify_all_manifest_entries_nested,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bin(model_dir: Path, filename: str, content: bytes) -> Path:
    """Write a .bin file into model_dir and return its path."""
    p = model_dir / filename
    p.write_bytes(content)
    return p


def _write_manifest(manifest_dir: Path, digests: dict[str, str]) -> Path:
    """Write a manifest.json into manifest_dir and return its path."""
    p = manifest_dir / "manifest.json"
    p.write_text(json.dumps({"version": "1.0.0", "digests": digests}), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Group A: verify_all_manifest_entries
# ---------------------------------------------------------------------------


class TestVerifyAllManifestEntries:
    """Core sweep function — four fail-closed scenarios."""

    def test_all_entries_pass(self, tmp_path: Path) -> None:
        """All manifest entries correct AND no extra .bin → all_verified=True."""
        content_a = b"primary model weights"
        content_b = b"speculative draft weights"
        content_c = b"tokenizer embedding weights"
        _write_bin(tmp_path, "openvino_model.bin", content_a)
        _write_bin(tmp_path, "openvino_draft.bin", content_b)
        _write_bin(tmp_path, "tokenizer.bin", content_c)
        digests = {
            "openvino_model.bin": _sha256(content_a),
            "openvino_draft.bin": _sha256(content_b),
            "tokenizer.bin": _sha256(content_c),
        }
        manifest_path = _write_manifest(tmp_path, digests)

        result: ManifestSweepResult = verify_all_manifest_entries(tmp_path, manifest_path)

        assert result.all_verified is True
        assert result.error is None
        assert len(result.per_file) == 3
        assert all(r.verified for r in result.per_file)

    def test_swapped_entry_fails_closed(self, tmp_path: Path) -> None:
        """A .bin whose content differs from the manifest digest → all_verified=False."""
        good_content = b"real weights"
        tampered_content = b"SWAPPED WEIGHTS - ATTACKER CONTENT"
        _write_bin(tmp_path, "openvino_model.bin", tampered_content)  # content differs
        digests = {
            "openvino_model.bin": _sha256(good_content),  # original digest
        }
        manifest_path = _write_manifest(tmp_path, digests)

        result = verify_all_manifest_entries(tmp_path, manifest_path)

        assert result.all_verified is False
        assert result.error is not None
        assert "mismatch" in result.error.lower()
        assert len(result.per_file) == 1
        assert result.per_file[0].verified is False

    def test_extra_bin_not_in_manifest_fails_closed(self, tmp_path: Path) -> None:
        """A .bin present on disk but absent from the manifest → all_verified=False."""
        content = b"legitimate weight data"
        extra_content = b"unknown extra binary"
        _write_bin(tmp_path, "openvino_model.bin", content)
        _write_bin(tmp_path, "suspicious_extra.bin", extra_content)  # NOT in manifest
        digests = {
            "openvino_model.bin": _sha256(content),
        }
        manifest_path = _write_manifest(tmp_path, digests)

        result = verify_all_manifest_entries(tmp_path, manifest_path)

        assert result.all_verified is False
        assert result.error is not None
        assert "extra" in result.error.lower() or "not listed" in result.error.lower()
        # The extra file should appear in per_file with verified=False
        extra_results = [r for r in result.per_file if Path(r.model_path).name == "suspicious_extra.bin"]
        assert len(extra_results) == 1
        assert extra_results[0].verified is False

    def test_missing_manifest_entry_fails_closed(self, tmp_path: Path) -> None:
        """A .bin listed in the manifest but not found on disk → all_verified=False."""
        content = b"one real weight file"
        _write_bin(tmp_path, "openvino_model.bin", content)
        # Manifest references a second file that does NOT exist on disk
        digests = {
            "openvino_model.bin": _sha256(content),
            "openvino_draft.bin": "a" * 64,  # listed but absent from disk
        }
        manifest_path = _write_manifest(tmp_path, digests)

        result = verify_all_manifest_entries(tmp_path, manifest_path)

        assert result.all_verified is False
        assert result.error is not None
        # Error text should identify the missing file
        assert "openvino_draft.bin" in result.error or "not found" in result.error.lower()
        missing_results = [
            r for r in result.per_file
            if Path(r.model_path).name == "openvino_draft.bin"
        ]
        assert len(missing_results) == 1
        assert missing_results[0].verified is False


# ---------------------------------------------------------------------------
# Group B: PA load_model() integrity gate
# ---------------------------------------------------------------------------


class TestPALoadModelIntegritySweep:
    """Policy Agent load_model() refuses to load when sweep fails."""

    def _make_pa(self, model_dir: Path, manifest_path: Path | None) -> "PolicyGPUInference":
        from services.policy_agent.src.gpu_inference import PolicyGPUInference
        return PolicyGPUInference(
            model_dir=str(model_dir),
            manifest_path=str(manifest_path) if manifest_path else None,
        )

    def _patch_ov_available(self) -> "contextlib._GeneratorContextManager[None]":
        """Patch OV availability so load_model() reaches the integrity check."""
        import contextlib

        @contextlib.contextmanager
        def _ctx() -> Generator[None, None, None]:
            with patch(
                "services.policy_agent.src.gpu_inference._OV_GENAI_AVAILABLE", True
            ), patch(
                "services.policy_agent.src.gpu_inference.ov_genai"
            ) as mock_ov:
                # Make LLMPipeline init succeed so load_model() returns True on clean pass.
                mock_ov.LLMPipeline.return_value = object()
                mock_ov.draft_model.return_value = None
                mock_ov.SchedulerConfig.return_value = type(
                    "_SC", (), {"cache_size": 0, "enable_prefix_caching": False}
                )()
                yield

        return _ctx()

    def test_pa_clean_manifest_loads(self, tmp_path: Path) -> None:
        """PA load_model() succeeds when all manifest entries pass."""
        content = b"pa model weights"
        # Create minimum required files
        (tmp_path / "openvino_model.xml").write_bytes(b"<xml/>")
        _write_bin(tmp_path, "openvino_model.bin", content)
        manifest_path = _write_manifest(tmp_path, {"openvino_model.bin": _sha256(content)})

        with self._patch_ov_available():
            pa = self._make_pa(tmp_path, manifest_path)
            result = pa.load_model()

        assert result is True
        assert pa.loaded is True
        assert pa.integrity_result is not None
        assert pa.integrity_result.verified is True

    def test_pa_tampered_manifest_fails_closed(self, tmp_path: Path) -> None:
        """PA load_model() refuses to load when a manifest entry is tampered."""
        (tmp_path / "openvino_model.xml").write_bytes(b"<xml/>")
        _write_bin(tmp_path, "openvino_model.bin", b"real weights")
        # Manifest has the WRONG digest for the file on disk
        manifest_path = _write_manifest(
            tmp_path, {"openvino_model.bin": "0" * 64}
        )

        with self._patch_ov_available():
            pa = self._make_pa(tmp_path, manifest_path)
            result = pa.load_model()

        assert result is False
        assert pa.loaded is False


# ---------------------------------------------------------------------------
# Group C: AO load_model() integrity gate
# ---------------------------------------------------------------------------


class TestAOLoadModelIntegritySweep:
    """Orchestrator load_model() refuses to load when sweep fails."""

    def _make_ao(self, model_dir: Path, manifest_path: Path | None) -> "OrchestratorGPUInference":
        from services.assistant_orchestrator.src.gpu_inference import OrchestratorGPUInference
        return OrchestratorGPUInference(
            model_dir=str(model_dir),
            manifest_path=str(manifest_path) if manifest_path else None,
            speculative_decoding_enabled=False,
        )

    def _patch_ov_available(self) -> "contextlib._GeneratorContextManager[None]":
        import contextlib

        @contextlib.contextmanager
        def _ctx() -> Generator[None, None, None]:
            with patch(
                "services.assistant_orchestrator.src.gpu_inference._OV_GENAI_AVAILABLE", True
            ), patch(
                "services.assistant_orchestrator.src.gpu_inference.ov_genai"
            ) as mock_ov:
                mock_ov.LLMPipeline.return_value = object()
                mock_ov.draft_model.return_value = None
                mock_ov.SchedulerConfig.return_value = type(
                    "_SC", (), {"cache_size": 0, "enable_prefix_caching": False}
                )()
                yield

        return _ctx()

    def test_ao_clean_manifest_loads(self, tmp_path: Path) -> None:
        """AO load_model() succeeds when all manifest entries pass."""
        content = b"ao model weights"
        (tmp_path / "openvino_model.xml").write_bytes(b"<xml/>")
        _write_bin(tmp_path, "openvino_model.bin", content)
        manifest_path = _write_manifest(tmp_path, {"openvino_model.bin": _sha256(content)})

        with self._patch_ov_available():
            ao = self._make_ao(tmp_path, manifest_path)
            result = ao.load_model()

        assert result is True
        assert ao.loaded is True
        assert ao.integrity_result is not None
        assert ao.integrity_result.verified is True

    def test_ao_extra_bin_fails_closed(self, tmp_path: Path) -> None:
        """AO load_model() refuses to load when an extra .bin is present in the model dir."""
        content = b"ao model weights"
        (tmp_path / "openvino_model.xml").write_bytes(b"<xml/>")
        _write_bin(tmp_path, "openvino_model.bin", content)
        _write_bin(tmp_path, "injected_extra.bin", b"attacker content")  # extra
        manifest_path = _write_manifest(
            tmp_path, {"openvino_model.bin": _sha256(content)}
        )

        with self._patch_ov_available():
            ao = self._make_ao(tmp_path, manifest_path)
            result = ao.load_model()

        assert result is False
        assert ao.loaded is False


# ---------------------------------------------------------------------------
# Group D: verify_all_manifest_entries_nested
# (UC-010 WS1 — nested diffusers-OV layout: subdirs like unet/openvino_model.bin
#  + unet/openvino_model.xml + model_index.json at the root; manifest keys are
#  relative POSIX paths. Covers .xml + model_index.json + TPM-signature gate.)
# ---------------------------------------------------------------------------


# Synthetic TPM-signing stub (no real TPM in CI) — mirrors the pattern in
# test_manifest_signer.py / test_manifest_signing_mechanism.py verbatim.
def _stub_sign(key_name: str, data: bytes) -> bytes:
    """Deterministic HMAC-SHA256 substitute for tpm_signer.sign."""
    return hashlib.sha256(b"stub-nested-key:" + data).digest()


def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
    """Verify against _stub_sign output."""
    return signature == _stub_sign(key_name, data)


def _sign_manifest_stub(manifest: Path) -> None:
    """Write a valid base64url .sig alongside *manifest* using the stub signer."""
    import base64

    from shared.models.manifest_signer import MANIFEST_SIGNING_KEY_NAME

    raw = manifest.read_bytes()
    sig = _stub_sign(MANIFEST_SIGNING_KEY_NAME, raw)
    sig_path = manifest.parent / (manifest.name + ".sig")
    sig_path.write_bytes(base64.urlsafe_b64encode(sig))


def _patch_tpm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route tpm_signer.verify -> the software stub for manifest_signer."""
    from shared.models import manifest_signer
    from shared.security import tpm_signer

    monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
    monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)


def _write_nested_bin(model_dir: Path, rel: str, content: bytes) -> bytes:
    """Write *content* to model_dir/rel (creating parent subdirs); return content."""
    p = model_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return content


def _write_nested_manifest(model_dir: Path, digests: dict[str, str]) -> Path:
    """Write a manifest.json into model_dir (keys = relative POSIX paths)."""
    p = model_dir / "manifest.json"
    p.write_text(
        json.dumps({"version": "1.0.0", "digests": digests}), encoding="utf-8"
    )
    return p


class TestVerifyAllManifestEntriesNested:
    """Nested-layout sweep — .xml / model_index.json coverage + signature gate."""

    def _full_nested_model(self, model_dir: Path) -> dict[str, str]:
        """Stage a minimal nested SDXL-shaped model + return matching digests.

        Layout: unet/openvino_model.bin, unet/openvino_model.xml,
        model_index.json — the three file kinds the widened Step-2 sweeps.
        """
        bin_c = _write_nested_bin(
            model_dir, "unet/openvino_model.bin", b"unet weights"
        )
        xml_c = _write_nested_bin(
            model_dir, "unet/openvino_model.xml", b"<net>unet topology</net>"
        )
        idx_c = _write_nested_bin(
            model_dir, "model_index.json", b'{"_class_name": "StableDiffusionXLPipeline"}'
        )
        return {
            "unet/openvino_model.bin": _sha256(bin_c),
            "unet/openvino_model.xml": _sha256(xml_c),
            "model_index.json": _sha256(idx_c),
        }

    # -- tampered topology / index -----------------------------------------

    def test_nested_tampered_xml_refuses(self, tmp_path: Path) -> None:
        """A nested .xml whose on-disk bytes differ from the manifest digest
        ⇒ all_verified False, error mentions the mismatch."""
        digests = self._full_nested_model(tmp_path)
        # Tamper the .xml on disk AFTER computing its digest into the manifest.
        (tmp_path / "unet" / "openvino_model.xml").write_bytes(
            b"<net>SWAPPED COMPUTE GRAPH</net>"
        )
        manifest = _write_nested_manifest(tmp_path, digests)

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert "mismatch" in result.error.lower()

    def test_nested_tampered_model_index_json_refuses(self, tmp_path: Path) -> None:
        """A tampered model_index.json ⇒ all_verified False (the index is swept)."""
        digests = self._full_nested_model(tmp_path)
        (tmp_path / "model_index.json").write_bytes(
            b'{"_class_name": "AttackerPipeline"}'
        )
        manifest = _write_nested_manifest(tmp_path, digests)

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert "mismatch" in result.error.lower()

    # -- missing listed entry ----------------------------------------------

    def test_nested_missing_xml_entry_refuses(self, tmp_path: Path) -> None:
        """A manifest lists an .xml that is absent on disk ⇒ all_verified False."""
        digests = self._full_nested_model(tmp_path)
        # Add a manifest entry for a topology file that does NOT exist.
        digests["text_encoder/openvino_model.xml"] = "a" * 64
        manifest = _write_nested_manifest(tmp_path, digests)

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert (
            "text_encoder/openvino_model.xml" in result.error
            or "not found" in result.error.lower()
        )

    # -- extra unlisted .xml / model_index.json ----------------------------

    def test_nested_extra_unlisted_xml_refuses(self, tmp_path: Path) -> None:
        """An on-disk .xml NOT in a (.bin-only) manifest ⇒ refused by the widened
        Step-2 recursive sweep (the swap-and-drop defense extended to topology)."""
        bin_c = _write_nested_bin(
            tmp_path, "unet/openvino_model.bin", b"unet weights"
        )
        # An unlisted .xml the attacker drops in to swap the compute graph.
        _write_nested_bin(
            tmp_path, "unet/openvino_model.xml", b"<net>unlisted graph</net>"
        )
        manifest = _write_nested_manifest(
            tmp_path, {"unet/openvino_model.bin": _sha256(bin_c)}
        )

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert "extra" in result.error.lower() or "not listed" in result.error.lower()

    def test_nested_extra_unlisted_model_index_refuses(self, tmp_path: Path) -> None:
        """An on-disk model_index.json NOT in a (.bin-only) manifest ⇒ refused
        by the widened recursive sweep."""
        bin_c = _write_nested_bin(
            tmp_path, "unet/openvino_model.bin", b"unet weights"
        )
        _write_nested_bin(
            tmp_path, "model_index.json", b'{"_class_name": "Sneaky"}'
        )
        manifest = _write_nested_manifest(
            tmp_path, {"unet/openvino_model.bin": _sha256(bin_c)}
        )

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert "extra" in result.error.lower() or "not listed" in result.error.lower()

    # -- full clean pass ----------------------------------------------------

    def test_nested_full_bin_xml_index_manifest_passes(self, tmp_path: Path) -> None:
        """All three kinds (.bin + .xml + model_index.json) listed and matching
        ⇒ all_verified True."""
        digests = self._full_nested_model(tmp_path)
        manifest = _write_nested_manifest(tmp_path, digests)

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is True
        assert result.error is None
        assert len(result.per_file) == 3
        assert all(r.verified for r in result.per_file)

    # -- signature gate (require_signed) -----------------------------------

    def test_nested_require_signed_missing_sig_refuses(self, tmp_path: Path) -> None:
        """A correct manifest with NO .sig + require_signed=True ⇒ all_verified
        False. No monkeypatch needed — load_manifest_verified short-circuits on
        the absent .sig (FAIL-CLOSED)."""
        digests = self._full_nested_model(tmp_path)
        manifest = _write_nested_manifest(tmp_path, digests)
        sig_path = manifest.parent / (manifest.name + ".sig")
        assert not sig_path.exists(), "precondition: no .sig present"

        result = verify_all_manifest_entries_nested(
            tmp_path, manifest, require_signed=True
        )

        assert result.all_verified is False
        assert result.error is not None

    def test_nested_require_signed_valid_sig_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A correct manifest + a valid STUB .sig + monkeypatched TPM verify +
        require_signed=True ⇒ all_verified True (the on-chip ceremony analogue)."""
        digests = self._full_nested_model(tmp_path)
        manifest = _write_nested_manifest(tmp_path, digests)
        _sign_manifest_stub(manifest)
        sig_path = manifest.parent / (manifest.name + ".sig")
        assert sig_path.exists(), "precondition: stub .sig written"
        _patch_tpm(monkeypatch)

        result = verify_all_manifest_entries_nested(
            tmp_path, manifest, require_signed=True
        )

        assert result.all_verified is True
        assert result.error is None
        assert len(result.per_file) == 3

    # -- traversal / absolute-path escape guard (_safe_join) ---------------

    def test_nested_manifest_key_traversal_refuses(self, tmp_path: Path) -> None:
        """A manifest key that traverses OUT of the model dir (``../escape.bin``)
        ⇒ all_verified False, error names the escape (the _safe_join guard).

        Fail-closed: a tampered manifest must not be able to point the verifier at
        an arbitrary file outside ``model_dir``."""
        digests = self._full_nested_model(tmp_path)
        # A relative key that escapes the model root via a parent-dir traversal.
        digests["../escape.bin"] = "a" * 64
        manifest = _write_nested_manifest(tmp_path, digests)

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert "escapes the model directory" in result.error

    def test_nested_manifest_key_absolute_path_refuses(self, tmp_path: Path) -> None:
        """A manifest key that is an ABSOLUTE path ⇒ all_verified False with the
        same escape error (_safe_join rejects absolute keys, fail-closed)."""
        digests = self._full_nested_model(tmp_path)
        # An absolute key (resolves outside model_dir) — a Windows-shaped abs path
        # so the test is meaningful on the dev box; _safe_join's relative_to check
        # rejects any key that does not resolve under the model root.
        abs_key = "C:/Windows/System32/escape.bin"
        digests[abs_key] = "a" * 64
        manifest = _write_nested_manifest(tmp_path, digests)

        result = verify_all_manifest_entries_nested(tmp_path, manifest)

        assert result.all_verified is False
        assert result.error is not None
        assert "escapes the model directory" in result.error

    # -- regression lock: flat .bin-only verifier unchanged ----------------

    def test_flat_bin_only_14b_shape_still_verifies_unchanged(
        self, tmp_path: Path
    ) -> None:
        """REGRESSION LOCK: the FLAT verifier stays .bin-only — a flat dir with
        openvino_model.bin AND an openvino_model.xml on disk + a .bin-only
        manifest ⇒ verify_all_manifest_entries all_verified True (the .xml is
        ignored). Proves the signed 14B/PA boot is unaffected by the WS1 widening."""
        content = b"the 14B primary weights"
        _write_bin(tmp_path, "openvino_model.bin", content)
        # The 14B layout ships an .xml topology alongside the .bin — the FLAT
        # verifier must NOT sweep it (a .bin-only signed manifest would otherwise
        # refuse the real boot).
        (tmp_path / "openvino_model.xml").write_bytes(b"<net>14B topology</net>")
        manifest_path = _write_manifest(tmp_path, {"openvino_model.bin": _sha256(content)})

        result = verify_all_manifest_entries(tmp_path, manifest_path)

        assert result.all_verified is True
        assert result.error is None
        assert len(result.per_file) == 1
        assert result.per_file[0].verified is True
