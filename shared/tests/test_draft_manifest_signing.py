"""Regression locks for signing the speculative-decoding DRAFT manifests (FUT-05 / #107 + #917).

Extends ADR-018 manifest signing to the ENFORCED, previously-unsigned draft
manifests — the shared-pipeline draft ``qwen3-0.6b-pruned-6l/openvino-int8-gpu``
(#107) AND the PA standalone/fallback draft ``qwen3-0.6b/openvino-int4-gpu`` (#917,
which added the verifier ``gpu_inference._verify_draft_integrity``) — reusing the ONE
``BlarAI-Manifest-Signing`` key (the drafts are NON-AUTHORITATIVE — proposals the
signed 14B target re-verifies). The generic ``verify_weight_integrity`` posture below
is the exact check BOTH the shared pipeline and the PA standalone path make; the
PA-standalone LOAD path is driven end-to-end in
``services/policy_agent/tests/test_draft_integrity_standalone.py``.

Three lock groups, all in software (no real TPM, no model files, no hardware),
using the same deterministic stub-signer idiom as ``test_manifest_signing_mechanism``:

  A. Draft VERIFY posture — the exact call ``build_shared_pipeline`` makes for the
     draft (``verify_weight_integrity`` with ``require_signed=require_signed_draft``):
       - enforced (True) + valid ``.sig``      → verifies (lock passes when engaged)
       - enforced (True) + MISSING ``.sig``     → fails closed (toggle: lock blocks)
       - enforced (True) + INVALID ``.sig``     → fails closed
       - dormant  (False) + unsigned, good digest → passes (shipping dormant is boot-safe)
       - dormant  (False) + digest MISMATCH      → fails (digest still enforced dormant)
  B. Ceremony SIGNS the enforced set — ``provision()`` over a required 14B +
     optional manifests writes a ``.sig``/``.pub`` per present manifest with ONE
     key; a required absent manifest is fail-closed (nothing signed); an optional
     absent one is skipped; no TPM is fail-closed. Plus a scope lock: the default
     served set is the 14B + BOTH enforced drafts (pruned-6L #107 + int4 #917); the
     non-served 1.5b stays excluded.
  C. ``ceremony_preflight`` reports each draft manifest (present-signed / absent /
     digest-mismatch → FAIL).

conftest.py supplies the LOCALAPPDATA redirect so no test writes to real user data.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from shared.models import manifest_signer
from shared.models.manifest_signer import MANIFEST_SIGNING_KEY_NAME
from shared.models.weight_integrity import verify_weight_integrity
from shared.security import tpm_signer


# ---------------------------------------------------------------------------
# Stub signer — deterministic software substitute (no real TPM)
# ---------------------------------------------------------------------------

def _stub_sign(key_name: str, data: bytes) -> bytes:
    """Deterministic substitute for tpm_signer.sign (matches the mechanism test)."""
    return hashlib.sha256(b"stub-manifest-key:" + data).digest()


def _stub_verify(key_name: str, data: bytes, signature: bytes) -> bool:
    return signature == _stub_sign(key_name, data)


def _real_ec_public_pem() -> bytes:
    """A genuine, parseable EC P-256 public-key PEM.

    ``provision()`` feeds the ceremony's ``.pub`` through ``_spki_sha256`` (which
    calls ``serialization.load_pem_public_key``), so the stubbed
    ``export_public_key_pem`` MUST return a real PEM, not arbitrary bytes.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


# ---------------------------------------------------------------------------
# Helpers — a draft-shaped model dir (openvino_model.bin + manifest.json)
# ---------------------------------------------------------------------------

def _make_draft_model(model_dir: Path, *, bin_content: bytes = b"draft weights v1") -> Path:
    """Write a draft-shaped model dir and return the manifest path.

    The manifest carries the (correct) SHA-256 of ``openvino_model.bin`` — the file
    ``verify_weight_integrity`` re-hashes.  (Tokenizer/detokenizer entries are
    included for realism; only the one passed to verify_weight_integrity is checked.)
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "openvino_model.bin").write_bytes(bin_content)
    digests = {
        "openvino_model.bin": hashlib.sha256(bin_content).hexdigest(),
        "openvino_tokenizer.bin": "a" * 64,
        "openvino_detokenizer.bin": "b" * 64,
    }
    manifest = model_dir / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.0.0", "digests": digests}), encoding="utf-8")
    return manifest


def _stub_sign_manifest(manifest: Path) -> Path:
    """Write a valid stub ``.sig`` for manifest; return the .sig path."""
    sig_bytes = _stub_sign(MANIFEST_SIGNING_KEY_NAME, manifest.read_bytes())
    sig_path = manifest.parent / (manifest.name + ".sig")
    sig_path.write_bytes(base64.urlsafe_b64encode(sig_bytes))
    return sig_path


# ===========================================================================
# Group A — draft VERIFY posture (verify_weight_integrity require_signed path)
# ===========================================================================

class TestDraftVerifyPosture:
    """The exact draft check build_shared_pipeline makes, across both flag states."""

    def test_enforced_valid_sig_verifies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """require_signed_draft=True + a valid draft .sig → integrity verifies.

        Lock: the signature gate PASSES when engaged against a correctly-signed draft.
        """
        manifest = _make_draft_model(tmp_path / "draft")
        _stub_sign_manifest(manifest)
        monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
        monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

        result = verify_weight_integrity(
            model_path=str(tmp_path / "draft" / "openvino_model.bin"),
            manifest_path=str(manifest),
            require_signed=True,
        )

        assert result.verified is True, "valid draft .sig must verify under require_signed=True"

    def test_enforced_missing_sig_fails_closed(self, tmp_path: Path) -> None:
        """require_signed_draft=True + NO .sig → integrity FAILS closed.

        Toggle lock: with enforcement engaged and no signature, the draft (and thus
        the whole shared-pipeline build) is refused — the state that would exist if
        the LA flipped the flag BEFORE the signing ceremony.
        """
        manifest = _make_draft_model(tmp_path / "draft")
        assert not (manifest.parent / (manifest.name + ".sig")).exists()

        result = verify_weight_integrity(
            model_path=str(tmp_path / "draft" / "openvino_model.bin"),
            manifest_path=str(manifest),
            require_signed=True,
        )

        assert result.verified is False, "missing draft .sig under require_signed=True must fail closed"

    def test_enforced_invalid_sig_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """require_signed_draft=True + a .sig that no longer matches → FAILS closed.

        Sign, then tamper the manifest: the detached .sig is now cryptographically
        stale, so the gate must refuse (a .sig file alone is never sufficient).
        """
        manifest = _make_draft_model(tmp_path / "draft")
        _stub_sign_manifest(manifest)
        # Tamper AFTER signing — the .sig no longer matches the manifest bytes.
        tampered = {"version": "1.0.0", "digests": {"openvino_model.bin": "c" * 64}}
        manifest.write_text(json.dumps(tampered), encoding="utf-8")
        monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
        monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

        result = verify_weight_integrity(
            model_path=str(tmp_path / "draft" / "openvino_model.bin"),
            manifest_path=str(manifest),
            require_signed=True,
        )

        assert result.verified is False, "an invalid/stale draft .sig under require_signed=True must fail closed"

    def test_dormant_unsigned_passes_digest_only(self, tmp_path: Path) -> None:
        """require_signed_draft=False (shipped default) + unsigned draft, good digest
        → verifies (digest-only). Proves shipping DORMANT does not break the draft
        load on the currently-unsigned drafts — the no-brick guarantee."""
        manifest = _make_draft_model(tmp_path / "draft")
        assert not (manifest.parent / (manifest.name + ".sig")).exists()

        result = verify_weight_integrity(
            model_path=str(tmp_path / "draft" / "openvino_model.bin"),
            manifest_path=str(manifest),
            require_signed=False,
        )

        assert result.verified is True, "dormant default must still load the unsigned draft (digest-only)"

    def test_dormant_digest_mismatch_still_fails(self, tmp_path: Path) -> None:
        """Even DORMANT, the digest is enforced: a draft weight that does not match
        its manifest digest fails closed (signing adds authenticity, not the only
        integrity check)."""
        manifest = _make_draft_model(tmp_path / "draft")
        # Corrupt the weight AFTER staging so its digest no longer matches.
        (tmp_path / "draft" / "openvino_model.bin").write_bytes(b"tampered draft weight")

        result = verify_weight_integrity(
            model_path=str(tmp_path / "draft" / "openvino_model.bin"),
            manifest_path=str(manifest),
            require_signed=False,
        )

        assert result.verified is False, "a digest mismatch must fail even while dormant"


# ===========================================================================
# Group B — the ceremony signs the enforced set (provision multi-manifest)
# ===========================================================================

class TestCeremonySignsServedSet:
    """provision() signs every present manifest with ONE key; fail-closed paths hold."""

    def _patch_tpm(self, monkeypatch: pytest.MonkeyPatch, *, available: bool = True) -> None:
        pub_pem = _real_ec_public_pem()
        monkeypatch.setattr(tpm_signer, "is_available", lambda: available)
        monkeypatch.setattr(tpm_signer, "ensure_key", lambda key_name: True)
        monkeypatch.setattr(tpm_signer, "sign", _stub_sign)
        monkeypatch.setattr(tpm_signer, "export_public_key_pem", lambda key_name: pub_pem)
        monkeypatch.setattr(tpm_signer, "verify", _stub_verify)
        monkeypatch.setattr(manifest_signer, "tpm_signer", tpm_signer)

    def test_signs_multiple_manifests_with_one_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One ceremony run signs a required target + optional manifests with the
        SAME key: each gets a .sig + .pub, and each .sig verifies under
        require_signed=True. (Exercises the multi-manifest mechanism generically —
        the shipped default set is scoped to the 14B + the one enforced draft.)"""
        from shared.models.weight_integrity import load_manifest_verified
        from shared.security import provision_manifest_signing_key as prov

        m14b = _make_draft_model(tmp_path / "qwen3-14b", bin_content=b"target 14b")
        d1 = _make_draft_model(tmp_path / "draft-pruned", bin_content=b"draft pruned")
        d2 = _make_draft_model(tmp_path / "draft-06b", bin_content=b"draft 0.6b")
        self._patch_tpm(monkeypatch)

        rc = prov.provision(
            MANIFEST_SIGNING_KEY_NAME,
            [(m14b, True), (d1, False), (d2, False)],
        )

        assert rc == 0
        for m in (m14b, d1, d2):
            sig = m.parent / (m.name + ".sig")
            pub = m.parent / (m.name + ".pub")
            assert sig.exists(), f"{m} must get a .sig"
            assert pub.exists(), f"{m} must get a .pub"
            # Each manifest now loads under enforcement (its signature verifies).
            assert load_manifest_verified(m, require_signed=True) is not None, (
                f"{m} signature must verify under require_signed=True"
            )

    def test_absent_optional_draft_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing OPTIONAL draft is skipped (rc 0); the present ones are signed."""
        from shared.security import provision_manifest_signing_key as prov

        m14b = _make_draft_model(tmp_path / "qwen3-14b")
        absent = tmp_path / "draft-absent" / "manifest.json"  # never created
        self._patch_tpm(monkeypatch)

        rc = prov.provision(MANIFEST_SIGNING_KEY_NAME, [(m14b, True), (absent, False)])

        assert rc == 0
        assert (m14b.parent / (m14b.name + ".sig")).exists()
        assert not absent.exists()
        assert not (absent.parent / (absent.name + ".sig")).exists()

    def test_missing_required_fails_closed_nothing_signed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing REQUIRED manifest is fail-closed: rc 1 and NOTHING is signed
        (the required-existence check runs before any signing)."""
        from shared.security import provision_manifest_signing_key as prov

        missing_required = tmp_path / "qwen3-14b" / "manifest.json"  # never created
        present_optional = _make_draft_model(tmp_path / "draft")
        self._patch_tpm(monkeypatch)

        rc = prov.provision(
            MANIFEST_SIGNING_KEY_NAME,
            [(missing_required, True), (present_optional, False)],
        )

        assert rc == 1
        # Fail-closed EARLY: the present optional must NOT have been signed.
        assert not (present_optional.parent / (present_optional.name + ".sig")).exists()

    def test_no_tpm_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No usable TPM → rc 1, nothing signed (the ceremony refuses to run)."""
        from shared.security import provision_manifest_signing_key as prov

        m14b = _make_draft_model(tmp_path / "qwen3-14b")
        self._patch_tpm(monkeypatch, available=False)

        rc = prov.provision(MANIFEST_SIGNING_KEY_NAME, [(m14b, True)])

        assert rc == 1
        assert not (m14b.parent / (m14b.name + ".sig")).exists()

    def test_default_served_set_is_14b_plus_both_enforced_drafts(self) -> None:
        """The no-argument ceremony's served set = the 14B (required) + BOTH ENFORCED
        drafts (optional): the shared-pipeline pruned-6l draft (#107) AND the PA
        standalone int4 draft (#917, which added the verifier). Locks the scope — the
        signed set is exactly the set a code path verifies. The non-served
        qwen2.5-1.5b must NOT be signed (nothing loads it)."""
        from shared.security import provision_manifest_signing_key as prov

        served = prov._default_served_manifests()
        required = [p for p, req in served if req]
        optional = [p for p, req in served if not req]

        assert required == [prov.DEFAULT_MANIFEST_PATH]
        assert set(optional) == set(prov.DRAFT_MANIFEST_PATHS)
        # BOTH enforced drafts are covered — the shared-pipeline pruned-6l AND the
        # PA standalone int4. Keyed by model family (dir grandparent).
        names = {p.parent.parent.name for p in prov.DRAFT_MANIFEST_PATHS}
        assert names == {"qwen3-0.6b-pruned-6l", "qwen3-0.6b"}
        # The PA-standalone int4 draft is now present (its verifier landed in #917).
        assert any(
            p.parent.parent.name == "qwen3-0.6b" and p.parent.name == "openvino-int4-gpu"
            for p in prov.DRAFT_MANIFEST_PATHS
        )
        # The non-served qwen2.5-1.5b stays excluded (no code loads it).
        assert not any("qwen2.5" in str(p) for p in prov.DRAFT_MANIFEST_PATHS)


# ===========================================================================
# Group C — ceremony_preflight reports the enforced draft manifest
# ===========================================================================

class TestPreflightCoversDrafts:
    """_check_draft_manifests surfaces each served draft (absent / signed / mismatch)."""

    def test_reports_signed_absent_and_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shared.security.ceremony_preflight as preflight

        # Draft 1: present + signed + matching weight → INFO (ok), digest verified.
        d1 = tmp_path / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu"
        m1 = _make_draft_model(d1, bin_content=b"good draft")
        _stub_sign_manifest(m1)
        # Draft 2: absent entirely → INFO (ok).
        d2 = tmp_path / "qwen3-0.6b" / "openvino-int4-gpu"
        # Draft 3: present but weight tampered → FAIL.
        d3 = tmp_path / "qwen2p5-mismatch" / "ov"
        m3 = _make_draft_model(d3, bin_content=b"orig")
        (d3 / "openvino_model.bin").write_bytes(b"tampered")

        monkeypatch.setattr(preflight, "_DRAFT_MODEL_DIRS", (d1, d2, d3))

        results = preflight._check_draft_manifests()

        assert len(results) == 3
        oks = [ok for ok, _ in results]
        lines = "\n".join(line for _, line in results)
        # Present+signed and absent are non-fatal; the mismatch is a hard FAIL.
        assert oks[0] is True and "digest verified" in lines
        assert oks[1] is True and "absent" in lines
        assert oks[2] is False and "DIGEST MISMATCH" in lines
        # Each line names its model family so the LA can tell them apart.
        assert d1.parent.name in lines  # qwen3-0.6b-pruned-6l
        assert d2.parent.name in lines  # qwen3-0.6b
        assert d3.parent.name in lines  # qwen2p5-mismatch
