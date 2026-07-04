"""
Host-side blarai-img:// resolver for generated + display images (ADR-033 §D)
=============================================================================
The host-internal counterpart to the WinUI ``ImageResolver.cs`` decrypt seam:
given a ``blarai-img://<id>`` reference, decrypt the locally-stored bytes to a
``(mime, bytes)`` pair for display (WinUI inline render) or a TUI ``/save``.

Resolves ``generated_images`` by ``image_id`` (UC-010 is the new producer):
  1. ``generated_images`` (UC-010, ADR-033) — locally-generated images, born
     on-box from an operator prompt, keyed by ``image_id`` alone.  This is the
     ONLY by-id resolve wired today.

The ``knowledge_images`` (UC-003 Workstream B) display-only article images are
keyed PER-DOCUMENT (``bank.get_knowledge_image(doc_uuid, image_id)``); the bank
exposes NO by-id finder.  A by-id fallback over that store is a RESERVED, inert
seam here (see the ``get_display_image_by_id`` getattr below) — it stays inert
until such a by-id finder is deliberately added, which is a membership-GRAIN
decision (per-doc vs. global) intentionally deferred, NOT wired in this pass.

Security posture (Fail-Closed, ADR-033 §D):
  * The id is matched against the AUTHORITATIVE shape — a ``uuid4().hex``,
    exactly 32 lowercase hex, anchored full-string ``\\A[0-9a-f]{32}\\z`` (NOT a
    prefix / ``^…$`` match — the ADR-032 Am.1 lesson: ``$`` would accept a
    trailing newline forgery).  A malformed / forged ref returns None and the
    caller renders the inert alt placeholder.
  * The bytes are ALWAYS locally-decrypted (the bank's FieldCipher under the
    shared DEK) — never a URL, never a network source.  A decrypt failure
    (tampered / wrong-identity row) is quarantined to None, never partial.
  * Display-only: these bytes are NEVER chunked, embedded, indexed, or fed to a
    model (the no-VLM lock holds at the store).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: The single host-internal image scheme (mirrors cleaner.image_refs +
#: ImageResolver.cs — duplicated as a literal to keep this leaf dependency-free).
BLARAI_IMG_SCHEME: str = "blarai-img://"

#: Authoritative id shape: uuid4().hex, anchored full-string (no trailing
#: newline — ``\Z`` end-of-string, the Python equivalent of .NET's ``\z``).
_IMAGE_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def extract_image_id(ref: str | None) -> str | None:
    """Return the 32-hex image id from a well-formed ``blarai-img://<id>`` ref.

    Returns None for any non-image scheme, an empty id, or an id that is not
    exactly the ``uuid4().hex`` shape (forgery surface a resolver must deny).
    """
    if not ref or not ref.lower().startswith(BLARAI_IMG_SCHEME):
        return None
    candidate = ref[len(BLARAI_IMG_SCHEME):].strip()
    return candidate if _IMAGE_ID_RE.match(candidate) else None


def resolve_generated_or_display_image(
    bank: Any, ref_or_id: str
) -> tuple[str, bytes] | None:
    """Resolve a ``blarai-img://<id>`` ref (or a bare 32-hex id) to ``(mime, bytes)``.

    *bank* is an ``EncryptedKnowledgeBank``.  Resolves ``generated_images`` by id
    (UC-010 — the only wired by-id store).  Returns None when the id is malformed,
    unknown, or the row fails to decrypt (Fail-Closed — never partial plaintext,
    never a network source).

    The ``knowledge_images`` (UC-003 Workstream B) by-id fallback below is a
    RESERVED, INERT seam: the bank exposes ``get_generated_image(image_id)`` and
    the per-document ``get_knowledge_image(doc_uuid, image_id)`` — there is NO
    ``get_display_image_by_id`` (by-id) method, so the ``getattr`` resolves to
    None and the fallback branch never runs.  Adding a by-id knowledge finder is
    a membership-GRAIN decision (per-doc vs. global) intentionally deferred, NOT
    to be added in this pass.
    """
    # Accept either a full ref or a bare id (the /save command passes either).
    image_id = extract_image_id(ref_or_id)
    if image_id is None and _IMAGE_ID_RE.match((ref_or_id or "").strip()):
        image_id = ref_or_id.strip()
    if image_id is None:
        return None

    # 1. generated_images (UC-010) — the new producer; keyed by image_id alone.
    try:
        gen = bank.get_generated_image(image_id)
    except Exception as exc:  # noqa: BLE001 — Fail-Closed
        logger.error("resolve image %s: generated lookup raised: %s", image_id, exc)
        gen = None
    if gen is not None:
        return gen.mime, gen.data

    # 2. knowledge_images (UC-003 Workstream B) — display-only article images.
    #    RESERVED/INERT seam: no `get_display_image_by_id` (by-id) method exists
    #    on the bank today (it exposes only the per-doc `get_knowledge_image`), so
    #    this getattr yields None and the branch never runs (graceful None today).
    #    A by-id knowledge finder is a deferred membership-GRAIN decision.
    finder = getattr(bank, "get_display_image_by_id", None)
    if finder is not None:
        try:
            disp = finder(image_id)
        except Exception as exc:  # noqa: BLE001 — Fail-Closed
            logger.error(
                "resolve image %s: display lookup raised: %s", image_id, exc
            )
            disp = None
        if disp is not None:
            return disp.mime, disp.data
    return None
