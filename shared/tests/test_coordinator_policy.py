"""Adversarial regression locks for signed policy verification (ADR-039 #848, control 7).

Control 7 extends the existing signed-manifest machinery (ADR-018) beyond model weights
to the coordinator policy file. Proven here (all OFFLINE — no TPM required):

  * a TAMPERED / missing-when-required / corrupt-signature policy file → refuse (verified=False);
  * the DORMANT path (require_signed=false, no file) is permitted with compiled-in defaults;
  * a present-but-invalid signature is fail-closed even when require_signed=false (no silent
    downgrade), delegating the crypto to the separately-tested manifest_signer;
  * a verified policy may only ADD governed-core roots, never subtract the compiled-in core;
  * any exception in the integrity check fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import shared.models.manifest_signer as manifest_signer
from shared.coordinator.config import PROTECTED_CONFIG_SECTIONS
from shared.coordinator.policy import (
    load_policy_verified,
    resolve_governed_core_roots_from_policy,
    resolve_protected_config_sections_from_policy,
    verify_policy_integrity,
)


def _write_policy(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Dormant path — unsigned permitted, compiled-in defaults authoritative
# ---------------------------------------------------------------------------


class TestDormantPath:
    def test_no_policy_file_not_required_passes(self) -> None:
        result = verify_policy_integrity(None, require_signed=False)
        assert result.verified is True
        assert result.policy is None and result.signed is False

    def test_empty_policy_path_not_required_passes(self) -> None:
        result = verify_policy_integrity("   ", require_signed=False)
        assert result.verified is True

    def test_unsigned_policy_file_not_required_loads(self, tmp_path: Path) -> None:
        """require_signed=false + a present unsigned policy file (no .sig) → loads with a
        warning (the manifest machinery's unsigned-permitted path)."""
        policy = _write_policy(tmp_path / "coordinator_policy.json", {"version": "1.0.0"})
        result = verify_policy_integrity(policy, require_signed=False)
        assert result.verified is True and result.policy == {"version": "1.0.0"}
        assert result.signed is False


# ---------------------------------------------------------------------------
# Tampered / missing / corrupt → refuse-to-start
# ---------------------------------------------------------------------------


class TestRefuseToStart:
    def test_required_but_no_policy_configured_refuses(self) -> None:
        result = verify_policy_integrity(None, require_signed=True)
        assert result.verified is False and result.error

    def test_required_but_no_signature_refuses(self, tmp_path: Path) -> None:
        """require_signed=true + a policy file with NO .sig → refuse (real machinery path)."""
        policy = _write_policy(tmp_path / "coordinator_policy.json", {"version": "1.0.0"})
        result = verify_policy_integrity(policy, require_signed=True)
        assert result.verified is False

    def test_corrupt_signature_refuses(self, tmp_path: Path) -> None:
        """A present-but-corrupt .sig (not valid base64) → refuse — fails at signature
        decode, before any TPM call, so this is deterministic offline."""
        policy = _write_policy(tmp_path / "coordinator_policy.json", {"version": "1.0.0"})
        (tmp_path / "coordinator_policy.json.sig").write_bytes(b"!!! not base64 !!!")
        # Fail-closed even when require_signed=False: a present-but-invalid signature is
        # never silently downgraded.
        result = verify_policy_integrity(policy, require_signed=False)
        assert result.verified is False

    def test_invalid_signature_refuses_via_wiring(self, tmp_path: Path, monkeypatch) -> None:
        """Delegating the crypto: when the (separately-tested) signature verifier reports
        INVALID, control 7 refuses. Simulates a tampered policy whose bytes no longer
        match the signature."""
        monkeypatch.setattr(
            manifest_signer, "verify_manifest_signature", lambda *a, **k: False
        )
        policy = _write_policy(tmp_path / "coordinator_policy.json", {"version": "1.0.0"})
        result = verify_policy_integrity(policy, require_signed=True)
        assert result.verified is False

    def test_valid_signature_but_malformed_json_refuses(self, tmp_path: Path, monkeypatch) -> None:
        """Even with a valid signature, malformed policy content is refused (fail-closed)."""
        monkeypatch.setattr(
            manifest_signer, "verify_manifest_signature", lambda *a, **k: True
        )
        bad = tmp_path / "coordinator_policy.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        assert load_policy_verified(bad, require_signed=True) is None

    def test_valid_signature_but_wrong_shape_refuses(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            manifest_signer, "verify_manifest_signature", lambda *a, **k: True
        )
        bad = _write_policy(
            tmp_path / "coordinator_policy.json",
            {"governed_core_extra_roots": "should-be-a-list"},
        )
        assert load_policy_verified(bad, require_signed=True) is None

    def test_integrity_check_exception_fails_closed(self, tmp_path: Path, monkeypatch) -> None:
        """Any unexpected exception in the integrity check → verified=False."""
        import shared.coordinator.policy as policy_mod

        def boom(*a, **k):
            raise RuntimeError("simulated")

        monkeypatch.setattr(policy_mod, "load_policy_verified", boom)
        result = verify_policy_integrity(tmp_path / "p.json", require_signed=False)
        assert result.verified is False and "raised" in (result.error or "")


# ---------------------------------------------------------------------------
# Verified policy — additive only (never subtracts the compiled-in core)
# ---------------------------------------------------------------------------


class TestPolicyRoots:
    def test_signed_policy_adds_roots(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            manifest_signer, "verify_manifest_signature", lambda *a, **k: True
        )
        extra = str(tmp_path / "extra-governed")
        policy = _write_policy(
            tmp_path / "coordinator_policy.json",
            {"version": "1.0.0", "governed_core_extra_roots": [extra]},
        )
        # A signed policy has a .sig alongside it (its crypto is monkeypatched-valid here;
        # the real TPM signature is the operator provisioning ceremony).
        (tmp_path / "coordinator_policy.json.sig").write_bytes(b"dummy-sig")
        result = verify_policy_integrity(policy, require_signed=True)
        assert result.verified and result.signed
        roots = resolve_governed_core_roots_from_policy(result.policy, repo_root=tmp_path / "repo")
        assert Path(extra) in roots.extra_roots
        # The compiled-in repo_root is always present — a policy can only ADD.
        assert roots.repo_root == tmp_path / "repo"

    def test_none_policy_yields_compiled_defaults(self, tmp_path: Path) -> None:
        roots = resolve_governed_core_roots_from_policy(None, repo_root=tmp_path / "repo")
        assert roots.repo_root == tmp_path / "repo"
        assert roots.extra_roots == ()


# ---------------------------------------------------------------------------
# SG-review F5 — single-read (no verify/parse TOCTOU) + protected_config_sections consumed
# ---------------------------------------------------------------------------


class TestSingleReadNoToctou:
    def test_policy_bytes_read_once_and_verified_bytes_are_parsed_bytes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The policy file is read from disk EXACTLY ONCE — the bytes handed to the
        signature check are byte-identical to the bytes parsed, so a file swapped between
        a verify-read and a parse-read cannot load malicious content under a signature
        that was valid over benign content (the double-read the reviewer flagged)."""
        payload = {"version": "1.0.0", "protected_config_sections": ["coordinator"]}
        policy_file = _write_policy(tmp_path / "coordinator_policy.json", payload)

        seen: dict = {}

        def capturing_verify(path, *, require_signed, key_name=None, manifest_bytes=None):
            seen["bytes"] = manifest_bytes
            return True

        monkeypatch.setattr(manifest_signer, "verify_manifest_signature", capturing_verify)

        # Count content reads of THIS policy file.
        real_read_bytes = Path.read_bytes
        reads = {"n": 0}

        def counting_read_bytes(self):
            if str(self) == str(policy_file):
                reads["n"] += 1
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

        result = load_policy_verified(policy_file, require_signed=True)
        assert result == payload
        # The signature check was handed the ACTUAL bytes (single-read wiring), not None
        # (which would mean it re-read the file itself — the second read the swap needs).
        assert seen["bytes"] is not None
        assert json.loads(seen["bytes"].decode("utf-8")) == result
        # Exactly ONE content read of the policy file — structurally forecloses the swap.
        assert reads["n"] == 1

    def test_unreadable_policy_fails_closed_before_verify(self, tmp_path: Path, monkeypatch) -> None:
        """If the single read itself fails, the loader fails closed (None) without ever
        calling the signature verifier over stale/absent bytes."""
        called = {"verify": False}

        def tripwire_verify(*a, **k):
            called["verify"] = True
            return True

        monkeypatch.setattr(manifest_signer, "verify_manifest_signature", tripwire_verify)
        missing = tmp_path / "coordinator_policy.json"  # never created
        assert load_policy_verified(missing, require_signed=False) is None
        assert called["verify"] is False


class TestProtectedSectionsConsumed:
    def test_signed_policy_adds_protected_sections(self, tmp_path: Path, monkeypatch) -> None:
        """A verified policy's ``protected_config_sections`` is CONSUMED (previously
        validated but ignored) — additive over the compiled-in set, never subtractive,
        case-normalised."""
        monkeypatch.setattr(manifest_signer, "verify_manifest_signature", lambda *a, **k: True)
        policy = _write_policy(
            tmp_path / "coordinator_policy.json",
            {"version": "1.0.0", "protected_config_sections": ["my_new_section", "COORDINATOR"]},
        )
        (tmp_path / "coordinator_policy.json.sig").write_bytes(b"dummy-sig")
        result = verify_policy_integrity(policy, require_signed=True)
        assert result.verified and result.signed
        sections = resolve_protected_config_sections_from_policy(result.policy)
        # Compiled-in defaults are always present (additive, never subtractive).
        assert PROTECTED_CONFIG_SECTIONS <= sections
        # The policy-added section is now protected (consumed, not ignored)...
        assert "my_new_section" in sections
        # ...case-normalised.
        assert "coordinator" in sections

    def test_none_policy_yields_compiled_sections(self) -> None:
        assert resolve_protected_config_sections_from_policy(None) == PROTECTED_CONFIG_SECTIONS

    def test_policy_cannot_subtract_compiled_sections(self, tmp_path: Path, monkeypatch) -> None:
        """Even if a policy lists an EMPTY set, the compiled-in core sections remain
        protected — the set is widenable, never subtractable from inside."""
        monkeypatch.setattr(manifest_signer, "verify_manifest_signature", lambda *a, **k: True)
        policy = _write_policy(
            tmp_path / "coordinator_policy.json",
            {"version": "1.0.0", "protected_config_sections": []},
        )
        (tmp_path / "coordinator_policy.json.sig").write_bytes(b"dummy-sig")
        result = verify_policy_integrity(policy, require_signed=True)
        sections = resolve_protected_config_sections_from_policy(result.policy)
        assert PROTECTED_CONFIG_SECTIONS <= sections
        assert "coordinator" in sections and "egress" in sections
