"""Provisioning ceremony for the Policy Agent's TPM-sealed JWT signing key (ADR-021).

Run ONCE on the deployment host, by the operator, on the real chip::

    python -m shared.security.provision_signing_key

This is the human-in-the-loop step that completes the signing-key rotation. It
creates the non-exportable ECDSA P-256 key *inside* the platform TPM 2.0
(idempotent — a no-op if the key already exists) and exports its PUBLIC half to
``certs/pa_public.pem`` so every validator (Policy Agent, Assistant
Orchestrator, Semantic Router) can verify the JWTs the Policy Agent signs. The
PRIVATE half is generated in the TPM and never leaves it.

Fail-Closed: if no usable TPM 2.0 is present (non-Windows, or no Microsoft
Platform Crypto Provider), the ceremony refuses to run rather than silently
falling back to a software key. Production JWT signing stays fail-closed until
this ceremony has been run on the host (see ``PolicyAgentService`` preflight).

Design constraints (inherited from :mod:`shared.security.tpm_signer`):
  - **No external network. No new dependencies** — stdlib plus ``cryptography``,
    already a project dependency, used only to canonicalise the public key for
    its fingerprint.
  - The emitted ``pa_public.pem`` is a **per-chip** artifact (the TPM key is
    non-exportable and machine-bound), so it is intentionally *gitignored*, not
    committed. The printed ``SHA-256 (SPKI DER)`` fingerprint is the trust
    anchor the operator records in the rotation journal / ADR-021 — committing
    the fingerprint documents the anchor in git without committing one chip's
    key into a repo framed for decades across hardware generations.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from services.policy_agent.src.constants import PA_JWT_TPM_KEY_NAME
from shared.security import tpm_signer

# This file is .../<repo>/shared/security/provision_signing_key.py — repo root is parents[2].
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_PUBLIC_KEY_PATH: Path = _REPO_ROOT / "certs" / "pa_public.pem"


def _spki_sha256(public_key_pem: bytes) -> str:
    """SHA-256 over the SubjectPublicKeyInfo DER — canonical and tool-comparable.

    Matches ``openssl pkey -pubin -in pa_public.pem -outform DER | openssl dgst
    -sha256``, so the operator can independently verify the recorded trust
    anchor against the on-disk public key.
    """
    from cryptography.hazmat.primitives import serialization

    public_key = serialization.load_pem_public_key(public_key_pem)
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def provision(key_name: str, public_key_path: Path) -> int:
    """Create the TPM key if absent and export its public half.

    Returns a process exit code: 0 on success, 1 if the host has no usable TPM
    (Fail-Closed). Idempotent — safe to re-run; an existing key is left intact
    and its public half re-exported.
    """
    if not tpm_signer.is_available():
        print(
            "FAIL-CLOSED: no usable TPM 2.0 (Microsoft Platform Crypto Provider) on "
            "this host.\nThe provisioning ceremony must run on the deployment "
            "hardware with a TPM. No key was created.",
            file=sys.stderr,
        )
        return 1

    created = tpm_signer.ensure_key(key_name)  # idempotent: True if newly created
    public_key_pem = tpm_signer.export_public_key_pem(key_name)

    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.write_bytes(public_key_pem)

    fingerprint = _spki_sha256(public_key_pem)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "created" if created else "already existed (idempotent no-op)"

    print("Policy Agent JWT signing-key provisioning ceremony (ADR-021)")
    print(f"  TPM key name       : {key_name}")
    print(f"  TPM key status     : {status}")
    print(f"  public key written : {public_key_path}")
    print(f"  SHA-256 (SPKI DER) : {fingerprint}")
    print(f"  date (UTC)         : {stamp}")
    print(
        "Done. Record the SHA-256 fingerprint above as the trust anchor "
        "(rotation journal / ADR-021)."
    )
    print(
        "NOTE: pa_public.pem is a per-chip artifact (gitignored); the private "
        "key never leaves the TPM."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. See module docstring for the ceremony contract."""
    parser = argparse.ArgumentParser(
        prog="python -m shared.security.provision_signing_key",
        description=(
            "Provision the Policy Agent's non-exportable TPM JWT signing key "
            "and export its public half (ADR-021)."
        ),
    )
    parser.add_argument(
        "--key-name",
        default=PA_JWT_TPM_KEY_NAME,
        help=f"TPM persisted key name (default: {PA_JWT_TPM_KEY_NAME}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PUBLIC_KEY_PATH,
        help=f"Public-key output path (default: {DEFAULT_PUBLIC_KEY_PATH}).",
    )
    args = parser.parse_args(argv)

    try:
        return provision(args.key_name, args.out)
    except tpm_signer.TpmUnavailable as exc:
        print(f"FAIL-CLOSED: TPM unavailable: {exc}", file=sys.stderr)
        return 1
    except tpm_signer.TpmSigningError as exc:
        print(f"FAIL-CLOSED: TPM operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
