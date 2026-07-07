"""TPM-backed signing and verification for the weight-integrity manifest.

Implements FUT-04 (ADR-018): sign the Known-Good Manifest (``manifest.json``)
with the non-exportable TPM ECDSA P-256 key so that an attacker who can write
the manifest file cannot forge a plausible SHA-256 digest list — defeating the
attack path "swap model weights past the unsigned manifest" (audit Domain 1 +
Domain 7, 2026-06-03).

Design:
  - Signing writes ``<manifest>.sig`` alongside the manifest (raw ECDSA
    signature bytes, base64url-encoded) and ``<manifest>.pub`` (PEM public key,
    one-time export for off-chip / cross-check verification).
  - Verification reads ``<manifest>.sig``, decodes it, and calls
    ``tpm_signer.verify`` against the manifest bytes.  The TPM provider holds
    the private key — verification uses the persisted key directly so the same
    machine boot path needs no separate public-key file.
  - **Default-off gate**: callers pass ``require_signed`` (sourced from config
    flag ``require_signed_manifest``).  When ``False`` the function logs a
    warning and returns the manifest digest dict as-is (today's air-gapped boot
    has no signature yet).  When ``True`` a missing or invalid signature is a
    hard FAIL-CLOSED — returns ``None``, blocking all inference.
  - The canonical TPM key name is ``MANIFEST_SIGNING_KEY_NAME``; callers MAY
    override it.  The provisioning ceremony
    (``python -m shared.security.provision_manifest_signing_key``) creates the
    key and writes the ``.sig`` + ``.pub`` files.

No external network. No new runtime dependencies (``cryptography`` is already a
project dependency and is only imported lazily in ``export_public_key_pem``).
Fail-Closed on every unexpected path.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Final

from shared.security import tpm_signer

logger = logging.getLogger(__name__)

# Canonical TPM key name for manifest signing (matches ADR-018 FUT-04 intent).
MANIFEST_SIGNING_KEY_NAME: Final[str] = "BlarAI-Manifest-Signing"

# Suffix for the detached signature file written by sign_manifest().
_SIG_SUFFIX: Final[str] = ".sig"
# Suffix for the public-key file written by sign_manifest().
_PUB_SUFFIX: Final[str] = ".pub"


def _sig_path(manifest_path: Path) -> Path:
    """Return the canonical ``.sig`` path adjacent to ``manifest_path``."""
    return manifest_path.parent / (manifest_path.name + _SIG_SUFFIX)


def _pub_path(manifest_path: Path) -> Path:
    """Return the canonical ``.pub`` path adjacent to ``manifest_path``."""
    return manifest_path.parent / (manifest_path.name + _PUB_SUFFIX)


# ---------------------------------------------------------------------------
# Signing (provisioning-ceremony side)
# ---------------------------------------------------------------------------


def sign_manifest(
    manifest_path: str | Path,
    key_name: str = MANIFEST_SIGNING_KEY_NAME,
) -> tuple[Path, Path]:
    """Sign ``manifest_path`` with the TPM key and write the ``.sig`` + ``.pub`` files.

    Model-agnostic: signs ANY manifest path — the flat 14B/PA manifest OR the
    UC-010 NESTED SDXL manifest (ADR-033 WS1). The image go-live runbook stages
    the SDXL manifest with ``stage_production_manifest --nested`` and THEN calls
    this on ``models/sdxl-uncensored/openvino-int8-gpu/manifest.json`` so the
    nested verifier's ``require_signed=True`` path (driven by
    ``[image_generation].require_signed_manifest``) passes. The go-live order is
    strict: stage (nested) -> sign -> flip ``enabled`` (FUT-04 / ADR-018).

    This is a **provisioning-ceremony** function — the operator runs it once
    (or after every manifest update) on the deployment hardware, mirroring the
    ``provision_signing_key`` ceremony for the JWT key.

    Returns:
        ``(sig_path, pub_path)`` — paths to the written files.

    Raises:
        ``tpm_signer.TpmUnavailable`` if no TPM 2.0 / CNG provider is present.
        ``tpm_signer.TpmSigningError`` on unexpected CNG failure.
        ``OSError`` if the manifest file cannot be read or the output files
        cannot be written.
    """
    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()

    sig_bytes = tpm_signer.sign(key_name, manifest_bytes)

    sig_b64 = base64.urlsafe_b64encode(sig_bytes)
    pub_pem = tpm_signer.export_public_key_pem(key_name)

    sig_out = _sig_path(manifest_path)
    pub_out = _pub_path(manifest_path)
    sig_out.write_bytes(sig_b64)
    pub_out.write_bytes(pub_pem)

    logger.info(
        "Manifest signed: manifest=%s sig=%s pub=%s key=%s",
        manifest_path,
        sig_out,
        pub_out,
        key_name,
    )
    return sig_out, pub_out


# ---------------------------------------------------------------------------
# Verification (boot path + per-request re-hash path)
# ---------------------------------------------------------------------------


def verify_manifest_signature(
    manifest_path: str | Path,
    *,
    require_signed: bool,
    key_name: str = MANIFEST_SIGNING_KEY_NAME,
) -> bool:
    """Verify the TPM signature over ``manifest_path``.

    Args:
        manifest_path: Path to the ``manifest.json`` file.
        require_signed: When ``True``, a missing or invalid signature is
            FAIL-CLOSED (returns ``False``).  When ``False``, the absence of a
            ``.sig`` file is permitted (returns ``True``) — the manifest loads
            but a WARNING is emitted so the unsigned state is never silent.
        key_name: Persisted TPM key name (default: ``MANIFEST_SIGNING_KEY_NAME``).

    Returns:
        ``True`` if the signature is valid, or if ``require_signed=False`` and
        no signature file is present.  ``False`` on any failure (signature
        present but invalid; TPM unavailable when ``require_signed=True``; any
        unexpected error).

    Security contract:
        Every code path that returns ``False`` is FAIL-CLOSED — the caller MUST
        NOT proceed to use the manifest digests.  Every code path that returns
        ``True`` has either positively verified the cryptographic signature or
        explicitly accepted unsigned operation via ``require_signed=False``.
    """
    manifest_path = Path(manifest_path)
    sig_file = _sig_path(manifest_path)

    if not sig_file.exists():
        if not require_signed:
            logger.warning(
                "Manifest signature file not found and require_signed_manifest=false; "
                "proceeding without signature verification (unsigned manifest accepted). "
                "sig_expected=%s",
                sig_file,
            )
            return True
        logger.error(
            "FAIL-CLOSED: manifest signature file missing and require_signed_manifest=true. "
            "Run the provisioning ceremony to sign the manifest. sig_expected=%s",
            sig_file,
        )
        return False

    # Signature file exists — always attempt verification regardless of require_signed.
    try:
        sig_b64 = sig_file.read_bytes()
    except OSError as exc:
        logger.error(
            "FAIL-CLOSED: cannot read manifest signature file %s: %s", sig_file, exc
        )
        return False

    try:
        sig_bytes = base64.urlsafe_b64decode(sig_b64)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "FAIL-CLOSED: manifest signature file is not valid base64url %s: %s",
            sig_file,
            exc,
        )
        return False

    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        logger.error(
            "FAIL-CLOSED: cannot read manifest file for signature verification %s: %s",
            manifest_path,
            exc,
        )
        return False

    try:
        valid = tpm_signer.verify(key_name, manifest_bytes, sig_bytes)
    except tpm_signer.TpmUnavailable as exc:
        logger.error(
            "FAIL-CLOSED: TPM unavailable during manifest signature verification: %s",
            exc,
        )
        return False
    except tpm_signer.TpmSigningError as exc:
        logger.error(
            "FAIL-CLOSED: TPM error during manifest signature verification: %s", exc
        )
        return False

    if not valid:
        logger.error(
            "FAIL-CLOSED: manifest signature INVALID — manifest may have been tampered. "
            "manifest=%s sig=%s key=%s",
            manifest_path,
            sig_file,
            key_name,
        )
        return False

    logger.info(
        "Manifest signature verified: manifest=%s key=%s",
        manifest_path,
        key_name,
    )
    return True
