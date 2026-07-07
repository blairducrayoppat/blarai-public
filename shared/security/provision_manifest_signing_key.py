"""Provisioning ceremony for TPM-signed weight-integrity manifest (FUT-04 / ADR-018).

Run ONCE on the deployment host after every manifest update::

    python -m shared.security.provision_manifest_signing_key

This ceremony:
  1. Creates the non-exportable ECDSA P-256 TPM key (idempotent — a no-op if
     the key already exists).
  2. Signs the manifest file with that key, writing:
       ``<manifest>.sig``  — base64url-encoded raw ECDSA signature.
       ``<manifest>.pub``  — PEM-encoded public key (for off-chip verification).
  3. Prints the SHA-256 fingerprint of the public key as the trust anchor for
     the rotation journal / ADR-018 audit trail.

Fail-Closed: if no usable TPM 2.0 is present (non-Windows, or no Microsoft
Platform Crypto Provider) the ceremony refuses to run rather than silently
falling back to an unsigned manifest.  The ``require_signed_manifest`` config
flag remains ``false`` (the LA posture decision) until the ceremony has been
run and verified.

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
from datetime import datetime, timezone
from pathlib import Path

from shared.models.manifest_signer import (
    MANIFEST_SIGNING_KEY_NAME,
    sign_manifest,
)
from shared.security import tpm_signer

# This file is .../<repo>/shared/security/provision_manifest_signing_key.py.
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH: Path = (
    _REPO_ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu" / "manifest.json"
)


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
    manifest_path: Path,
) -> int:
    """Provision the TPM key (idempotent) and sign ``manifest_path``.

    Returns 0 on success, 1 if no usable TPM (Fail-Closed).
    """
    if not tpm_signer.is_available():
        print(
            "FAIL-CLOSED: no usable TPM 2.0 (Microsoft Platform Crypto Provider) on "
            "this host.\nThe provisioning ceremony must run on the deployment "
            "hardware with a TPM. No key was created and no manifest was signed.",
            file=sys.stderr,
        )
        return 1

    if not manifest_path.exists():
        print(
            f"FAIL-CLOSED: manifest file not found: {manifest_path}\n"
            "Generate the manifest before running the signing ceremony.",
            file=sys.stderr,
        )
        return 1

    created = tpm_signer.ensure_key(key_name)
    sig_path, pub_path = sign_manifest(manifest_path, key_name=key_name)

    pub_pem = pub_path.read_bytes()
    fingerprint = _spki_sha256(pub_pem)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    key_status = "created" if created else "already existed (idempotent no-op)"

    print("Manifest signing-key provisioning ceremony (FUT-04 / ADR-018)")
    print(f"  TPM key name       : {key_name}")
    print(f"  TPM key status     : {key_status}")
    print(f"  manifest signed    : {manifest_path}")
    print(f"  signature written  : {sig_path}")
    print(f"  public key written : {pub_path}")
    print(f"  SHA-256 (SPKI DER) : {fingerprint}")
    print(f"  date (UTC)         : {stamp}")
    print(
        "Done. Record the SHA-256 fingerprint above as the trust anchor "
        "(rotation journal / ADR-018)."
    )
    print(
        "NOTE: .pub and .sig are per-chip artifacts (gitignored); the private "
        "key never leaves the TPM."
    )
    print(
        "NEXT: after verifying the signature on-chip, flip "
        "`require_signed_manifest = true` in the service config (LA posture decision)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. See module docstring for the ceremony contract."""
    parser = argparse.ArgumentParser(
        prog="python -m shared.security.provision_manifest_signing_key",
        description=(
            "Provision the non-exportable TPM manifest-signing key and "
            "sign the weight-integrity manifest (FUT-04 / ADR-018)."
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
        default=DEFAULT_MANIFEST_PATH,
        help=f"Path to manifest.json to sign (default: {DEFAULT_MANIFEST_PATH}).",
    )
    args = parser.parse_args(argv)

    try:
        return provision(args.key_name, args.manifest)
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
