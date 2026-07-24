"""
Encrypted image staging handoff (UC-003 Workstream B, display-only images)
==========================================================================
Display-only article images cross the gateway -> AO process boundary the
SAME way cleaned text does (``shared/security/ingest_staging.py``): via a
per-image ENCRYPTED staging blob, never the 64 KB IPC frame.  The frame
carries image METADATA only (``image_id`` / ``staging_path`` / ``alt`` /
``source_url`` / ``mime``); the bytes ride the staging file.

    %LOCALAPPDATA%\\BlarAI\\ingest_staging\\<doc_uuid>__<image_id>.bin

This is the BINARY sibling of the proven text contract.  It deliberately
REUSES that module's primitives — ``STAGING_DIR_NAME`` /
``default_staging_dir`` / ``validate_doc_uuid`` (the canonical-UUID path
guard) — and shares the SAME directory, distinguishing image blobs only by
the ``<doc_uuid>__<image_id>.bin`` filename pattern.  ``ingest_staging.py``
itself is NEVER modified (its text contract is locked).

Each file is a single :class:`~shared.security.field_cipher.FieldCipher`
AES-256-GCM blob under the SAME shared DEK as sessions/substrate/knowledge
(ADR-025 §2.1 one-DEK rule), AAD-bound to BOTH the document AND the image
identity::

    aad = make_aad_for("image_staging", "content", f"{doc_uuid}:{image_id}")

so a staged image blob cannot be replayed under a different document OR a
different image identity — re-pointing it to another ``(doc_uuid, image_id)``
pair causes authentication failure.  Files are DACL-hardened at creation
(#637) and deleted by the AO immediately after the image row persists —
staging is a handoff, not a store.

SCOPE (UC-003 Workstream B): no module here performs a live fetch.  This is the
host-internal transport that MOVES already-fetched bytes; the fetch itself is
welded INDEPENDENTLY of the text door — the BED-1 ``uc003-image-ingest``
purpose-deny, the separate ``[knowledge].images_enabled`` gate, and the
MIME/magic-byte gate — and opens only by a separate LA-reviewed go-live
ceremony, never as a side effect of another scope going live.  Image bytes are
display-only — NEVER chunked, embedded, indexed, or sent to any VLM/inference.

Security posture (Fail-Closed):
  * ``doc_uuid`` is validated as a canonical UUID (reused from
    ``ingest_staging``) AND ``image_id`` is validated as a uuid4 hex string
    BEFORE any path is built — a traversal-shaped identifier never reaches
    the filesystem.
  * The read side derives the canonical path from the validated ids; a
    payload-supplied path is only ever CHECKED against it, never trusted.
  * Reads enforce a byte cap (``MAX_IMAGE_BYTES`` + cipher envelope) BEFORE
    touching file content.
  * Any decrypt failure raises :class:`ImageStagingError` — tampered,
    wrong-key, or wrong-identity content is never returned.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from shared.security.field_cipher import (
    ENVELOPE_OVERHEAD_BYTES as CIPHER_ENVELOPE_OVERHEAD_BYTES,
)

# Reused canonical primitives from the proven TEXT contract — same directory,
# same UUID path-guard, same data-root resolution.  NOT re-implemented here so
# the two siblings can never drift on where staging lives or how a doc_uuid is
# validated.  ``ingest_staging`` is imported, NEVER modified.
from shared.security.ingest_staging import (  # noqa: F401  (re-exported below)
    STAGING_DIR_NAME,
    default_staging_dir,
    validate_doc_uuid,
)

logger = logging.getLogger(__name__)

#: Per-image PLAINTEXT byte cap (2 MiB).  Defined LOCALLY (not imported from
#: ``shared.security.guarded_fetch``) to avoid a cross-module import race during
#: the parallel UC-003 Workstream B build — ``guarded_fetch`` is the egress door
#: and importing it here would pull the whole fetch stack into the transport
#: leaf.  **This value MUST EQUAL ``guarded_fetch.MAX_IMAGE_BYTES`` (2 * 1024 *
#: 1024 = 2 MiB).**  The door enforces it at the fetch seam; staging enforces it
#: again at the read seam (defence in depth — a blob never reaches the AO larger
#: than the door should ever have produced).
MAX_IMAGE_BYTES: int = 2 * 1024 * 1024

#: Largest PLAINTEXT image staged as an /edit SEED.  A seed is a LOCAL image or a
#: stored GENERATED image — NOT a door-fetched blob — so it is deliberately NOT
#: bound by the egress ``MAX_IMAGE_BYTES`` (2 MiB).  A 1536² hires generation is
#: ~3-4 MB, so the seed cap is sized for generated images (matches
#: ``resolve_channel.RESOLVE_BODY_MAX_BYTES``), decoupled from the egress cap
#: (#666: a 3.1 MB hires image hit the old 2 MiB seed cap and /edit refused
#: fail-closed).
SEED_IMAGE_MAX_BYTES: int = 16 * 1024 * 1024
#: Default READ cap on the on-disk CIPHERTEXT.  ``write_staged_image`` produces
#: exactly ``plaintext_len + CIPHER_ENVELOPE_OVERHEAD_BYTES`` bytes (AES-256-GCM
#: version + nonce + tag envelope), so the largest plaintext SEED that fits is
#: ``SEED_IMAGE_MAX_BYTES``.  Adding the envelope keeps a legitimate max-size
#: seed readable while still bouncing an over-cap blob before its content is
#: touched (mirrors the ``ingest_staging`` byte-cap seam) — still memory-DoS
#: bounded, just sized for a generated seed rather than the egress door.
DEFAULT_IMAGE_STAGING_MAX_BYTES: int = SEED_IMAGE_MAX_BYTES + CIPHER_ENVELOPE_OVERHEAD_BYTES


class ImageStagingError(RuntimeError):
    """Raised on any image-staging failure (Fail-Closed)."""


def validate_image_id(image_id: str) -> str:
    """Validate *image_id* as a ``uuid4().hex`` string; return it normalised.

    The image id is a 32-char lowercase hex ``uuid4().hex`` (NOT a content
    hash and NOT a canonical dashed UUID) — that is the shared-constant
    format pinned by the contract spec for the ``blarai-img://<image_id>``
    ref scheme.  Fail-Closed: anything that does not parse as a UUID whose
    ``.hex`` round-trips to the input — including traversal-shaped strings,
    dashed UUIDs, or wrong-length hex — raises :class:`ImageStagingError`
    before a path is ever constructed from it.
    """
    try:
        candidate = image_id.strip().lower()
    except (AttributeError, TypeError) as exc:
        raise ImageStagingError(
            f"Invalid image_id {image_id!r}: not a string (Fail-Closed)"
        ) from exc
    try:
        parsed = uuid.UUID(hex=candidate)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ImageStagingError(
            f"Invalid image_id {image_id!r}: not a uuid hex string (Fail-Closed)"
        ) from exc
    # Reject the dashed canonical form (and any other non-bare-hex input):
    # the ref scheme stores ``uuid4().hex`` exactly, so the only accepted
    # spelling is the 32-char bare hex.  ``uuid.UUID(hex=...)`` is lenient
    # (accepts dashes/braces), so we pin the canonical hex explicitly.
    if candidate != parsed.hex:
        raise ImageStagingError(
            f"Invalid image_id {image_id!r}: not the bare uuid4 hex form "
            f"(expected {parsed.hex!r}) (Fail-Closed)"
        )
    return parsed.hex


def image_staging_path_for(image_id: str, doc_uuid: str, staging_dir: Path) -> Path:
    """Return the canonical staging path for *(doc_uuid, image_id)* (validated).

    Both ids are validated BEFORE the path is built — a traversal-shaped id
    never reaches the filesystem (Fail-Closed).
    """
    doc_uuid = validate_doc_uuid(doc_uuid)
    image_id = validate_image_id(image_id)
    return staging_dir / f"{doc_uuid}__{image_id}.bin"


def write_staged_image(
    image_bytes: bytes,
    image_id: str,
    doc_uuid: str,
    cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
    staging_dir: Path,
) -> Path:
    """Encrypt *image_bytes* and write the staging blob for *(doc_uuid, image_id)*.

    Creates the staging directory if needed and applies the #637 owner-only
    DACL to both the directory and the file.  Hard fail-closed: any
    encryption or I/O failure raises.

    The AAD binds the ciphertext to BOTH the document and the image identity
    (``f"{doc_uuid}:{image_id}"``) so a blob cannot be replayed under any
    other ``(doc_uuid, image_id)`` pair.

    Args:
        image_bytes: The raw (already-fetched, MIME-validated) image bytes.
        image_id: ``uuid4().hex`` image identity (validated).
        doc_uuid: Canonical UUID of the owning document (validated).
        cipher: FieldCipher under the shared DEK.
        staging_dir: The canonical staging directory.

    Returns:
        The path of the staged image file.
    """
    from shared.security.field_cipher import make_aad_for
    from shared.security.file_dacl import ensure_owner_only_dacl

    doc_uuid = validate_doc_uuid(doc_uuid)
    image_id = validate_image_id(image_id)
    staging_dir.mkdir(parents=True, exist_ok=True)
    ensure_owner_only_dacl(str(staging_dir))

    blob = cipher.encrypt(
        image_bytes,
        aad=make_aad_for("image_staging", "content", f"{doc_uuid}:{image_id}"),
    )
    path = staging_dir / f"{doc_uuid}__{image_id}.bin"
    path.write_bytes(blob)
    ensure_owner_only_dacl(str(path))
    logger.info(
        "Image staging: wrote %s (%d encrypted bytes)", path.name, len(blob)
    )
    return path


def read_staged_image(
    image_id: str,
    doc_uuid: str,
    cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
    staging_dir: Path,
    *,
    max_bytes: int = DEFAULT_IMAGE_STAGING_MAX_BYTES,
    claimed_path: str | None = None,
) -> bytes:
    """Read and decrypt the staged image bytes for *(doc_uuid, image_id)*.

    The path is DERIVED from the validated ids + the canonical staging
    directory.  When the IPC payload supplied a ``staging_path`` it is passed
    as *claimed_path* and merely CHECKED against the canonical path — a
    mismatch refuses (a payload path is attacker-influenceable input and is
    never dereferenced).

    Args:
        image_id: ``uuid4().hex`` image identity (validated).
        doc_uuid: Canonical UUID of the owning document (validated).
        cipher: FieldCipher under the shared DEK.
        staging_dir: The canonical staging directory.
        max_bytes: Refuse files larger than this BEFORE reading content
            (defaults to the 2 MiB image cap + the cipher envelope).
        claimed_path: Optional payload-supplied path to cross-check.

    Returns:
        The decrypted image bytes.

    Raises:
        ImageStagingError: Missing file, oversize file, path mismatch, or any
            decrypt failure (Fail-Closed).
    """
    from shared.security.field_cipher import FieldCipherError, make_aad_for

    doc_uuid = validate_doc_uuid(doc_uuid)
    image_id = validate_image_id(image_id)
    path = staging_dir / f"{doc_uuid}__{image_id}.bin"

    if claimed_path is not None and claimed_path.strip():
        try:
            claimed_resolved = Path(claimed_path).resolve()
        except (OSError, ValueError) as exc:
            raise ImageStagingError(
                f"Image staging: unresolvable claimed path {claimed_path!r}"
            ) from exc
        if claimed_resolved != path.resolve():
            raise ImageStagingError(
                "Image staging: claimed staging_path does not match the "
                f"canonical path for image {image_id} of doc {doc_uuid} "
                "(Fail-Closed refuse)"
            )

    if not path.exists():
        raise ImageStagingError(
            f"Image staging: no staged file for image {image_id} of doc {doc_uuid}"
        )
    size = path.stat().st_size
    if size > max_bytes:
        raise ImageStagingError(
            f"Image staging: staged file is {size} bytes, exceeding the "
            f"{max_bytes}-byte cap (Fail-Closed refuse)"
        )

    blob = path.read_bytes()
    try:
        plaintext = cipher.decrypt(
            blob,
            aad=make_aad_for("image_staging", "content", f"{doc_uuid}:{image_id}"),
        )
    except FieldCipherError as exc:
        raise ImageStagingError(
            f"Image staging: decrypt failed for image {image_id} of doc "
            f"{doc_uuid} — tampered, wrong key, or wrong identity (Fail-Closed)"
        ) from exc
    return plaintext


def delete_staged_image(image_id: str, doc_uuid: str, staging_dir: Path) -> bool:
    """Delete the staged image for *(doc_uuid, image_id)*; True if one was removed.

    Fail-safe (never raises): deletion runs AFTER the image row persisted, so
    a failure here leaks only an encrypted blob — logged, not fatal.
    """
    try:
        doc_uuid = validate_doc_uuid(doc_uuid)
        image_id = validate_image_id(image_id)
        path = staging_dir / f"{doc_uuid}__{image_id}.bin"
        if path.exists():
            path.unlink()
            logger.info("Image staging: deleted %s", path.name)
            return True
        return False
    except Exception as exc:  # noqa: BLE001 — cleanup must never raise
        logger.warning(
            "Image staging: delete failed for %s/%s: %s", doc_uuid, image_id, exc
        )
        return False
