"""
Encrypted ingest staging handoff (UC-002/UC-003, Vikunja #655)
==============================================================
Cleaned document content crosses the gateway → AO process boundary via an
ENCRYPTED staging file, never the 64 KB IPC frame:

    %LOCALAPPDATA%\\BlarAI\\ingest_staging\\<doc_uuid>.bin

Each file is a single :class:`~shared.security.field_cipher.FieldCipher`
AES-256-GCM blob under the SAME shared DEK as sessions/substrate/knowledge
(ADR-025 §2.1 one-DEK rule), AAD-bound to its doc_uuid::

    aad = make_aad_for("ingest_staging", "content", doc_uuid)

so a staged blob cannot be replayed under a different document identity.
Files are DACL-hardened at creation (#637) and deleted by the AO immediately
after the pending row persists — staging is a handoff, not a store.

Security posture (Fail-Closed):
  * ``doc_uuid`` is validated as a canonical UUID string BEFORE any path is
    built — a traversal-shaped identifier (``..\\evil``) never reaches the
    filesystem.
  * The read side derives the canonical path from the validated doc_uuid; a
    payload-supplied path is only ever CHECKED against it, never trusted.
  * Reads enforce a byte cap (``[knowledge].staging_max_bytes``) before
    touching file content.
  * Any decrypt failure raises :class:`StagingError` — tampered or wrong-key
    content is never returned.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from shared.security.field_cipher import (
    ENVELOPE_OVERHEAD_BYTES as CIPHER_ENVELOPE_OVERHEAD_BYTES,
)

logger = logging.getLogger(__name__)

#: Directory name under the BlarAI runtime data root.
STAGING_DIR_NAME: str = "ingest_staging"

#: Default read cap — mirrors the [knowledge].staging_max_bytes config default.
#: NOTE this caps the on-disk CIPHERTEXT.  ``write_staged`` produces exactly
#: ``plaintext_len + CIPHER_ENVELOPE_OVERHEAD_BYTES`` bytes (AES-256-GCM
#: version + nonce + tag envelope — derived from the field_cipher format
#: constants, re-exported above), so the largest PLAINTEXT that fits is
#: ``DEFAULT_STAGING_MAX_BYTES - CIPHER_ENVELOPE_OVERHEAD_BYTES``.  Writers
#: enforcing a plaintext pre-check MUST subtract the envelope (#655 byte-cap
#: seam: a same-number plaintext cap passes the gateway and bounces here).
DEFAULT_STAGING_MAX_BYTES: int = 262_144


class StagingError(RuntimeError):
    """Raised on any ingest-staging failure (Fail-Closed)."""


def validate_doc_uuid(doc_uuid: str) -> str:
    """Validate *doc_uuid* as a canonical UUID string and return it normalised.

    Fail-Closed: anything that does not parse as a UUID — including
    traversal-shaped strings — raises :class:`StagingError` before a path is
    ever constructed from it.
    """
    try:
        parsed = uuid.UUID(doc_uuid.strip())
    except (ValueError, AttributeError, TypeError) as exc:
        raise StagingError(
            f"Invalid doc_uuid {doc_uuid!r}: not a canonical UUID (Fail-Closed)"
        ) from exc
    return str(parsed)


def default_staging_dir() -> Path:
    """Resolve the canonical staging directory under the runtime data root.

    Mirrors the inline ``%LOCALAPPDATA%\\BlarAI`` resolution the AO and gateway
    use (no shared helper exists — see DATA_MAP §0).

    Raises:
        StagingError: When ``LOCALAPPDATA`` is unset (no on-disk staging home).
    """
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise StagingError(
            "LOCALAPPDATA is not set — no staging directory available (Fail-Closed)"
        )
    return Path(local) / "BlarAI" / STAGING_DIR_NAME


def staging_path_for(doc_uuid: str, staging_dir: Path) -> Path:
    """Return the canonical staging path for *doc_uuid* (validated)."""
    return staging_dir / f"{validate_doc_uuid(doc_uuid)}.bin"


def write_staged(
    content: str,
    doc_uuid: str,
    cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
    staging_dir: Path,
) -> Path:
    """Encrypt *content* and write it to the staging file for *doc_uuid*.

    Creates the staging directory if needed and applies the #637 owner-only
    DACL to both the directory and the file.  Hard fail-closed: any
    encryption or I/O failure raises.

    Returns:
        The path of the staged file.
    """
    from shared.security.field_cipher import make_aad_for
    from shared.security.file_dacl import ensure_owner_only_dacl

    doc_uuid = validate_doc_uuid(doc_uuid)
    staging_dir.mkdir(parents=True, exist_ok=True)
    ensure_owner_only_dacl(str(staging_dir))

    blob = cipher.encrypt(
        content.encode("utf-8"),
        aad=make_aad_for("ingest_staging", "content", doc_uuid),
    )
    path = staging_dir / f"{doc_uuid}.bin"
    path.write_bytes(blob)
    ensure_owner_only_dacl(str(path))
    logger.info("Ingest staging: wrote %s (%d encrypted bytes)", path.name, len(blob))
    return path


def read_staged(
    doc_uuid: str,
    cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
    staging_dir: Path,
    *,
    max_bytes: int = DEFAULT_STAGING_MAX_BYTES,
    claimed_path: str | None = None,
) -> str:
    """Read and decrypt the staged content for *doc_uuid*.

    The path is DERIVED from the validated doc_uuid + the canonical staging
    directory.  When the IPC payload supplied a ``staging_path`` it is passed
    as *claimed_path* and merely CHECKED against the canonical path — a
    mismatch refuses (a payload path is attacker-influenceable input and is
    never dereferenced).

    Args:
        doc_uuid: Canonical UUID of the staged document.
        cipher: FieldCipher under the shared DEK.
        staging_dir: The canonical staging directory.
        max_bytes: Refuse files larger than this BEFORE reading content
            (the ``[knowledge].staging_max_bytes`` config value).
        claimed_path: Optional payload-supplied path to cross-check.

    Raises:
        StagingError: Missing file, oversize file, path mismatch, or any
            decrypt failure (Fail-Closed).
    """
    from shared.security.field_cipher import FieldCipherError, make_aad_for

    doc_uuid = validate_doc_uuid(doc_uuid)
    path = staging_dir / f"{doc_uuid}.bin"

    if claimed_path is not None and claimed_path.strip():
        try:
            claimed_resolved = Path(claimed_path).resolve()
        except (OSError, ValueError) as exc:
            raise StagingError(
                f"Ingest staging: unresolvable claimed path {claimed_path!r}"
            ) from exc
        if claimed_resolved != path.resolve():
            raise StagingError(
                "Ingest staging: claimed staging_path does not match the "
                f"canonical path for doc {doc_uuid} (Fail-Closed refuse)"
            )

    if not path.exists():
        raise StagingError(f"Ingest staging: no staged file for doc {doc_uuid}")
    size = path.stat().st_size
    if size > max_bytes:
        raise StagingError(
            f"Ingest staging: staged file is {size} bytes, exceeding the "
            f"{max_bytes}-byte cap (Fail-Closed refuse)"
        )

    blob = path.read_bytes()
    try:
        plaintext = cipher.decrypt(
            blob,
            aad=make_aad_for("ingest_staging", "content", doc_uuid),
        )
    except FieldCipherError as exc:
        raise StagingError(
            f"Ingest staging: decrypt failed for doc {doc_uuid} — tampered, "
            "wrong key, or wrong doc identity (Fail-Closed)"
        ) from exc
    return plaintext.decode("utf-8")


def delete_staged(doc_uuid: str, staging_dir: Path) -> bool:
    """Delete the staged file for *doc_uuid*; True if a file was removed.

    Fail-safe (never raises): deletion runs AFTER the pending row persisted,
    so a failure here leaks only an encrypted blob — logged, not fatal.
    """
    try:
        path = staging_dir / f"{validate_doc_uuid(doc_uuid)}.bin"
        if path.exists():
            path.unlink()
            logger.info("Ingest staging: deleted %s", path.name)
            return True
        return False
    except Exception as exc:  # noqa: BLE001 — cleanup must never raise
        logger.warning("Ingest staging: delete failed for %s: %s", doc_uuid, exc)
        return False
