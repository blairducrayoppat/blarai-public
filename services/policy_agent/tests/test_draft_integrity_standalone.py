"""Regression locks: the PA STANDALONE path verifies its draft weight (#917).

The Policy Agent's standalone/fallback GPU pipeline (``PolicyGPUInference.load_model``
``else`` branch) builds its OWN speculative-decoding draft — the path the guest
startup-smoke ceremony and the test suite exercise (host-mode production injects the
launcher's already-verified shared pipeline instead). Before #917 that draft loaded
with NO integrity check at all. These locks drive the REAL ``load_model`` entry point
(only ``ov_genai`` is mocked — the integrity check runs for real against on-disk draft
files) and prove, for BOTH postures of ``require_signed_draft_manifest``:

  * dormant (False, shipped default) = DIGEST-ONLY:
      - unsigned draft, good digest      → loads (boot-safe; the no-brick guarantee)
      - draft weight digest MISMATCH     → FAILS CLOSED (digest still enforced dormant)
      - draft manifest ABSENT            → loads WITH a WARNING (pre-#917 behaviour,
                                           but loud — never silent)
  * enforced (True, LA-flipped only post-ceremony) = SIGNATURE REQUIRED:
      - valid ``.sig``                    → loads (the lock passes when engaged)
      - MISSING ``.sig``                  → FAILS CLOSED (toggle: enforcement blocks)
      - draft manifest ABSENT            → FAILS CLOSED

Fail-closed means ``load_model`` returns False AND ``ov_genai.draft_model`` is never
called. Mirrors the shared-pipeline draft locks in
``shared/tests/test_draft_manifest_signing.py`` (principle 12: prove BLOCK-when-engaged
and the toggle proving the probe fails when the lock is off).

conftest.py supplies the LOCALAPPDATA redirect so no test writes to real user data.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.policy_agent.src.gpu_inference import PolicyGPUInference
from shared.models import manifest_signer
from shared.models.manifest_signer import MANIFEST_SIGNING_KEY_NAME
from shared.security import tpm_signer


# ---------------------------------------------------------------------------
# Deterministic stub signer (no real TPM) — same idiom as the mechanism test.
# ---------------------------------------------------------------------------

def _stub_sign(key_name: str, data: bytes) -> bytes:
    return hashlib.sha256(b"stub-manifest-key:" + data).digest()


def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
    return signature == _stub_sign(key_name, data)


def _make_model_dir(model_dir: Path, *, bin_content: bytes) -> Path:
    """Write a minimal OV model dir (xml + bin + digest manifest); return the dir.

    The manifest lists ONLY ``openvino_model.bin`` — for the TARGET this keeps the
    load-time ``verify_all_manifest_entries`` sweep (which rejects extra/missing .bin)
    green; for a DRAFT only that one file is re-hashed anyway.
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "openvino_model.xml").write_text("<xml/>", encoding="utf-8")
    (model_dir / "openvino_model.bin").write_bytes(bin_content)
    manifest = model_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "digests": {"openvino_model.bin": hashlib.sha256(bin_content).hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    return model_dir


def _sign_draft_manifest(draft_dir: Path) -> Path:
    """Write a valid stub ``.sig`` next to the draft manifest; return the .sig path."""
    manifest = draft_dir / "manifest.json"
    sig_bytes = _stub_sign(MANIFEST_SIGNING_KEY_NAME, manifest.read_bytes())
    sig_path = draft_dir / "manifest.json.sig"
    sig_path.write_bytes(base64.urlsafe_b64encode(sig_bytes))
    return sig_path


def _build_pa(
    tmp_path: Path, *, require_signed_draft_manifest: bool
) -> tuple[PolicyGPUInference, Path]:
    """A PA wired to a valid target dir + a separate draft dir. Returns (pa, draft_dir).

    The caller shapes the draft dir (good/bad digest, signed/unsigned, present/absent)
    BEFORE calling load_model to exercise a specific posture.
    """
    model_dir = _make_model_dir(tmp_path / "target", bin_content=b"pa target 14b weights")
    draft_dir = tmp_path / "draft"
    pa = PolicyGPUInference(
        str(model_dir),
        device="CPU",
        priority=0,
        manifest_path=str(model_dir / "manifest.json"),
        draft_model_dir=str(draft_dir),
        speculative_decoding_enabled=True,
        require_signed_draft_manifest=require_signed_draft_manifest,
    )
    return pa, draft_dir


def _run_load_model(pa: PolicyGPUInference) -> tuple[bool, MagicMock]:
    """Drive the REAL load_model with ov_genai mocked; return (result, mock_ov_genai)."""
    with patch(
        "services.policy_agent.src.gpu_inference._OV_GENAI_AVAILABLE", True
    ), patch(
        "services.policy_agent.src.gpu_inference.ov_genai"
    ) as mock_ov_genai:
        mock_ov_genai.LLMPipeline.return_value = MagicMock()
        mock_ov_genai.draft_model.return_value = MagicMock()
        mock_ov_genai.SchedulerConfig.return_value = MagicMock()
        result = pa.load_model()
    return result, mock_ov_genai


# ===========================================================================
# Dormant (require_signed_draft_manifest = False) — the shipped default
# ===========================================================================

class TestDraftIntegrityDormant:
    """Digest-only: the digest is enforced; the .sig is not consulted."""

    def test_unsigned_good_digest_loads(self, tmp_path: Path) -> None:
        """Boot-safe: an unsigned draft with a matching digest loads (no-brick)."""
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=False)
        _make_model_dir(draft_dir, bin_content=b"pa draft int4 weights")
        assert not (draft_dir / "manifest.json.sig").exists()

        result, mock_ov_genai = _run_load_model(pa)

        assert result is True
        assert pa.loaded is True
        mock_ov_genai.draft_model.assert_called_once()

    def test_digest_mismatch_fails_closed(self, tmp_path: Path) -> None:
        """Even dormant, a tampered draft weight (digest mismatch) FAILS CLOSED."""
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=False)
        _make_model_dir(draft_dir, bin_content=b"original draft weights")
        # Corrupt the draft weight AFTER staging — its digest no longer matches.
        (draft_dir / "openvino_model.bin").write_bytes(b"tampered draft weights")

        result, mock_ov_genai = _run_load_model(pa)

        assert result is False
        assert pa.loaded is False
        mock_ov_genai.draft_model.assert_not_called()

    def test_absent_manifest_loads_with_warning(self, tmp_path: Path) -> None:
        """Dormant + no draft manifest → loads (pre-#917 behaviour), never silent.

        Only the xml + bin exist; no manifest.json. The draft still loads (boot-safe),
        proving the dormant default does not brick a box whose draft is unstaged.
        """
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=False)
        draft_dir.mkdir(parents=True, exist_ok=True)
        (draft_dir / "openvino_model.xml").write_text("<xml/>", encoding="utf-8")
        (draft_dir / "openvino_model.bin").write_bytes(b"unstaged draft weights")
        assert not (draft_dir / "manifest.json").exists()

        result, mock_ov_genai = _run_load_model(pa)

        assert result is True
        assert pa.loaded is True
        mock_ov_genai.draft_model.assert_called_once()


# ===========================================================================
# Enforced (require_signed_draft_manifest = True) — LA-flipped post-ceremony
# ===========================================================================

class TestDraftIntegrityEnforced:
    """Signature required: a missing/invalid .sig or absent manifest FAILS CLOSED."""

    def test_valid_sig_loads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Enforced + a valid draft .sig → the draft loads (lock passes when engaged)."""
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=True)
        _make_model_dir(draft_dir, bin_content=b"pa draft int4 weights")
        _sign_draft_manifest(draft_dir)
        monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
        monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

        result, mock_ov_genai = _run_load_model(pa)

        assert result is True
        assert pa.loaded is True
        mock_ov_genai.draft_model.assert_called_once()

    def test_missing_sig_fails_closed(self, tmp_path: Path) -> None:
        """Enforced + NO draft .sig → FAILS CLOSED (the toggle: enforcement blocks).

        This is the state that would exist if the LA flipped the flag BEFORE the
        on-chip signing ceremony — the draft (and the whole standalone build) is
        refused rather than loaded unverified.
        """
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=True)
        _make_model_dir(draft_dir, bin_content=b"pa draft int4 weights")
        assert not (draft_dir / "manifest.json.sig").exists()

        result, mock_ov_genai = _run_load_model(pa)

        assert result is False
        assert pa.loaded is False
        mock_ov_genai.draft_model.assert_not_called()

    def test_invalid_sig_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Enforced + a .sig that no longer matches the manifest → FAILS CLOSED."""
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=True)
        _make_model_dir(draft_dir, bin_content=b"pa draft int4 weights")
        _sign_draft_manifest(draft_dir)
        # Tamper the manifest AFTER signing — the detached .sig is now stale.
        (draft_dir / "manifest.json").write_text(
            json.dumps({"version": "1.0.0", "digests": {"openvino_model.bin": "c" * 64}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
        monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

        result, mock_ov_genai = _run_load_model(pa)

        assert result is False
        assert pa.loaded is False
        mock_ov_genai.draft_model.assert_not_called()

    def test_absent_manifest_fails_closed(self, tmp_path: Path) -> None:
        """Enforced + no draft manifest at all → FAILS CLOSED (nothing to verify)."""
        pa, draft_dir = _build_pa(tmp_path, require_signed_draft_manifest=True)
        draft_dir.mkdir(parents=True, exist_ok=True)
        (draft_dir / "openvino_model.xml").write_text("<xml/>", encoding="utf-8")
        (draft_dir / "openvino_model.bin").write_bytes(b"unstaged draft weights")
        assert not (draft_dir / "manifest.json").exists()

        result, mock_ov_genai = _run_load_model(pa)

        assert result is False
        assert pa.loaded is False
        mock_ov_genai.draft_model.assert_not_called()
