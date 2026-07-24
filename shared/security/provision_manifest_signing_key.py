"""Provisioning ceremony for TPM-signed weight-integrity manifests (FUT-04 / FUT-05 / ADR-018).

Run ONCE on the deployment host after every manifest update::

    python -m shared.security.provision_manifest_signing_key

This ceremony:
  1. Creates the non-exportable ECDSA P-256 TPM key (idempotent — a no-op if
     the key already exists).
  2. Signs EACH served weight-integrity manifest with that ONE key, writing per
     manifest:
       ``<manifest>.sig``  — base64url-encoded raw ECDSA signature.
       ``<manifest>.pub``  — PEM-encoded public key (for off-chip verification).
  3. Prints the SHA-256 fingerprint of the public key as the trust anchor for
     the rotation journal / ADR-018 audit trail.

Coverage (FUT-05 remainder, #107 + #917): by default this signs, with the SAME
``BlarAI-Manifest-Signing`` key —

  - the authoritative Qwen3-14B target manifest (required), AND
  - BOTH ENFORCED speculative-decoding DRAFT manifests (optional, gitignored):
      * the pruned 6-layer draft the shared pipeline uses (``DRAFT_MODEL_OV_PATH``),
        verified by the launcher's ``build_shared_pipeline`` (#107); and
      * the Qwen3-0.6B INT4 draft the Policy Agent's standalone/fallback path uses
        (``qwen3-0.6b/openvino-int4-gpu``), verified by
        ``gpu_inference._verify_draft_integrity`` (#917).

We sign ONLY what a code path enforces. Both drafts above now have a verifier, so
both are signed. (The #107 build deliberately excluded the PA int4 draft precisely
because nothing verified it then — signing a manifest no code checks is pure attack
surface; #917 added the verifier, so the manifest belongs.) Still EXCLUDED:
``qwen2.5-1.5b`` — not a served model at all (only phase2_gates/ + dev scripts).

One key is sufficient (LA decision 2026-07-16): the draft is NON-AUTHORITATIVE —
in speculative decoding it only PROPOSES tokens the signed+verified 14B target
re-verifies, so a tampered draft degrades speed, not output integrity. This is
integrity-not-authenticity closure / defense-in-depth on the non-authoritative
model, NOT a second trust root.

Fail-Closed: if no usable TPM 2.0 is present (non-Windows, or no Microsoft
Platform Crypto Provider) the ceremony refuses to run rather than silently
falling back to unsigned manifests. A REQUIRED manifest (the 14B) that is absent
is likewise fail-closed (nothing is signed). An OPTIONAL manifest (a draft) that
is absent is skipped with a note — the draft models are gitignored and may not be
present on a given box; the ceremony signs what is there and reports the rest.

The ``[security].require_signed_manifest`` flag (14B) and the new
``[security].require_signed_draft_manifest`` flag (drafts) each remain the LA's
posture decision — flipped only after this ceremony has run and the signatures
are verified on-chip.

Design constraints (inherited from :mod:`shared.security.tpm_signer` and
:mod:`shared.security.provision_signing_key`):
  - No external network.  No new dependencies (stdlib + ``cryptography``).
  - The ``.pub`` is a per-chip artifact (gitignored).  The ``.sig`` is also
    per-chip and must be kept alongside the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from shared.models.manifest_signer import (
    MANIFEST_SIGNING_KEY_NAME,
    sign_manifest,
)
from shared.security import tpm_signer

# This file is .../<repo>/shared/security/provision_manifest_signing_key.py.
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# The authoritative target — REQUIRED (its digest gates the Policy Agent + the
# Assistant Orchestrator at boot under [security].require_signed_manifest=true).
DEFAULT_MANIFEST_PATH: Path = (
    _REPO_ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu" / "manifest.json"
)

# The served, ENFORCED speculative-decoding DRAFT manifests (FUT-05, #107 + #917) —
# OPTIONAL (gitignored; may be absent on a given box). Signed with the SAME key. The
# signed set is exactly the set a code path verifies — a signature no code checks is
# pure attack surface:
#   - qwen3-0.6b-pruned-6l/openvino-int8-gpu — the shared-pipeline draft
#     (shared.constants.DRAFT_MODEL_OV_PATH); the launcher's build_shared_pipeline
#     verifies it, gated by [security].require_signed_draft_manifest (AO config). #107.
#   - qwen3-0.6b/openvino-int4-gpu — the PA standalone/fallback draft; verified by
#     gpu_inference._verify_draft_integrity, gated by
#     [security].require_signed_draft_manifest (PA config). #917 (added the verifier,
#     so the manifest that #107 deferred now belongs).
# Deliberately EXCLUDED:
#   - qwen2.5-1.5b — not a served model at all (only phase2_gates/ + dev scripts).
DRAFT_MANIFEST_PATHS: tuple[Path, ...] = (
    _REPO_ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu" / "manifest.json",
    _REPO_ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu" / "manifest.json",
)


def _default_served_manifests() -> list[tuple[Path, bool]]:
    """The enforced set signed by a no-argument ceremony run.

    Returns ``(path, required)`` pairs: the 14B target is required; the enforced
    draft(s) in ``DRAFT_MANIFEST_PATHS`` are optional (signed if present,
    skipped-with-note if absent).
    """
    manifests: list[tuple[Path, bool]] = [(DEFAULT_MANIFEST_PATH, True)]
    manifests.extend((p, False) for p in DRAFT_MANIFEST_PATHS)
    return manifests


def _spki_sha256(public_key_pem: bytes) -> str:
    """SHA-256 over the SubjectPublicKeyInfo DER — matches ``openssl pkey`` output."""
    from cryptography.hazmat.primitives import serialization

    public_key = serialization.load_pem_public_key(public_key_pem)
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def provision(
    key_name: str,
    manifests: Sequence[tuple[Path, bool]],
) -> int:
    """Provision the TPM key (idempotent) and sign each manifest in *manifests*.

    Every manifest is signed with the SAME ``key_name`` (one trust root).

    Args:
        key_name: TPM persisted key name (default: ``MANIFEST_SIGNING_KEY_NAME``).
        manifests: ordered ``(manifest_path, required)`` pairs.
            ``required=True`` → an absent manifest is FAIL-CLOSED: nothing is
            signed and the ceremony returns 1 (the 14B target).
            ``required=False`` → an absent manifest is SKIPPED with a note (a
            gitignored draft that is not on this box).

    Returns:
        0 on success (every required manifest signed; every optional
        signed-or-skipped). 1 on any fail-closed condition (no usable TPM, or a
        required manifest missing) — with nothing signed in the missing-required
        case (the required-existence check runs BEFORE any signing).
    """
    if not tpm_signer.is_available():
        print(
            "FAIL-CLOSED: no usable TPM 2.0 (Microsoft Platform Crypto Provider) on "
            "this host.\nThe provisioning ceremony must run on the deployment "
            "hardware with a TPM. No key was created and no manifest was signed.",
            file=sys.stderr,
        )
        return 1

    # Fail-closed EARLY on any missing REQUIRED manifest — before creating a key
    # or signing anything, so a required-absent run leaves no partial state.
    for manifest_path, required in manifests:
        if required and not manifest_path.exists():
            print(
                f"FAIL-CLOSED: required manifest file not found: {manifest_path}\n"
                "Generate the manifest before running the signing ceremony "
                "(python -m shared.models.stage_production_manifest).",
                file=sys.stderr,
            )
            return 1

    created = tpm_signer.ensure_key(key_name)
    key_status = "created" if created else "already existed (idempotent no-op)"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("Manifest signing-key provisioning ceremony (FUT-04 / FUT-05 / ADR-018)")
    print(f"  TPM key name       : {key_name}")
    print(f"  TPM key status     : {key_status}")
    print(f"  date (UTC)         : {stamp}")

    fingerprint: str | None = None
    signed_count = 0
    skipped: list[Path] = []

    for manifest_path, required in manifests:
        if not manifest_path.exists():
            # Only optionals can reach here (required-absent already returned 1).
            skipped.append(manifest_path)
            print(f"  [skip] absent (optional) : {manifest_path}")
            continue

        sig_path, pub_path = sign_manifest(manifest_path, key_name=key_name)
        signed_count += 1
        if fingerprint is None:
            fingerprint = _spki_sha256(pub_path.read_bytes())
        print(f"  [sign] manifest          : {manifest_path}")
        print(f"         signature written : {sig_path}")
        print(f"         public key written: {pub_path}")

    print(f"  manifests signed   : {signed_count}")
    if skipped:
        print(
            f"  manifests skipped  : {len(skipped)} absent optional draft(s) — "
            "gitignored / not on this box"
        )
    if fingerprint is not None:
        print(f"  SHA-256 (SPKI DER) : {fingerprint}")

    print(
        "Done. Record the SHA-256 fingerprint above as the trust anchor "
        "(rotation journal / ADR-018)."
    )
    print(
        "NOTE: .pub and .sig are per-chip artifacts (gitignored); the private "
        "key never leaves the TPM."
    )
    print(
        "NEXT: after verifying the signatures on-chip, flip "
        "`require_signed_manifest = true` (14B) and, once the draft signatures "
        "are present, `require_signed_draft_manifest = true` in the AO config "
        "(shared-pipeline draft) and the PA config (standalone/fallback draft) — "
        "LA posture decisions."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. See module docstring for the ceremony contract.

    With no ``--manifest``, signs the enforced set (14B target + both enforced
    spec-decode drafts: the shared-pipeline pruned-6L and the PA standalone int4)
    with one key. ``--manifest X`` signs ONLY X (treated as required) — used to
    re-sign a single manifest (e.g. the SDXL image manifest, or just the 14B).
    """
    parser = argparse.ArgumentParser(
        prog="python -m shared.security.provision_manifest_signing_key",
        description=(
            "Provision the non-exportable TPM manifest-signing key and sign the "
            "enforced weight-integrity manifests (14B target + both spec-decode "
            "drafts; FUT-04 / FUT-05 / ADR-018)."
        ),
    )
    parser.add_argument(
        "--key-name",
        default=MANIFEST_SIGNING_KEY_NAME,
        help=f"TPM persisted key name (default: {MANIFEST_SIGNING_KEY_NAME}).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Sign ONLY this single manifest.json (treated as required). "
            "Default (omitted): sign the enforced set — the 14B target plus the "
            "present enforced spec-decode draft manifests."
        ),
    )
    args = parser.parse_args(argv)

    manifests: list[tuple[Path, bool]] = (
        [(args.manifest, True)] if args.manifest is not None else _default_served_manifests()
    )

    try:
        return provision(args.key_name, manifests)
    except tpm_signer.TpmUnavailable as exc:
        print(f"FAIL-CLOSED: TPM unavailable: {exc}", file=sys.stderr)
        return 1
    except tpm_signer.TpmSigningError as exc:
        print(f"FAIL-CLOSED: TPM operation failed: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FAIL-CLOSED: file I/O error during ceremony: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
