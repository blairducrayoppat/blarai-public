"""
Encrypted Knowledge Bank (USE-CASE-002 Substrate v2 — UC-003 ingest target)
===========================================================================
A sibling encrypted store to ``substrate.db`` holding *operator-curated*
knowledge documents (news articles and, later, files and pastes) with an
explicit human-approval lifecycle:

  submit (pending) -> operator reviews preview in chat -> approve | reject

Only APPROVED documents are chunked, embedded, and retrievable.  Pending rows
hold the cleaned content only (no chunks, no embeddings).  Rejected rows are
tombstones — the decision is flipped, the content is RETAINED (retention is a
later lifecycle decision, deliberately not taken here).

Display-only images (UC-003 Workstream B — DORMANT)
---------------------------------------------------
Content images of an ingested article are stored encrypted in
``knowledge_images``, keyed by ``doc_uuid``, **purely for inline display** in
the WinUI preview/render surface.  They are emphatically NOT part of the
retrieval substrate:

  * Image bytes are NEVER chunked, NEVER embedded, NEVER indexed, and NEVER
    sent to any model — there is no VLM (vision-language model) in BlarAI's
    runtime and this store must not become the seam that introduces one.
  * :meth:`retrieve` queries text chunks ONLY; it NEVER reads
    ``knowledge_images``.  The two ``self._embed(...)`` call sites
    (:meth:`approve`, :meth:`retrieve`) carry a fail-closed structural guard
    that refuses any non-``str`` argument — so image bytes cannot reach the
    embedder even by a future wiring mistake (``TypeError`` raised loudly).
  * The whole image limb is DORMANT in this build: the table exists and the
    storage methods are proven by test, but nothing populates it live until the
    LA go-live ceremony flips ``[knowledge].images_enabled`` (the 4th egress
    weld lock) AND the egress door opens.  This module merely makes the at-rest
    home correct, encrypted, and structurally inert.

Design decisions (Vikunja #655, Stage A):
  * **Sibling DB, not a new ``kind`` in substrate.db** — ``substrate_chunks``
    carries ``CHECK(kind IN ('doc','turn'))`` which SQLite cannot ALTER, and the
    knowledge bank has its own lifecycle (approval states, provenance record,
    dedup-by-source) that would distort the substrate schema.  Same DEK
    envelope (ADR-025 §2.1 one-DEK rule), own file, own DACL, own DATA_MAP row.
  * **Encryption** — AES-256-GCM via :class:`~shared.security.field_cipher.FieldCipher`
    on every content-bearing column (``source_ref``, ``title``, ``byline``,
    ``content``, chunk ``text`` + ``embedding``).  AAD binds each field to its
    natural identity: ``knowledge_docs|<column>|<doc_uuid>`` and
    ``knowledge_chunks|<column>|<doc_uuid>|<chunk_index>``.  ``source_hash`` is
    the deterministic HMAC keyed index (dedup-over-ciphertext; the ADR-025 §3
    equality-leak residual is accepted, same as the substrate).
  * **Lexical + hybrid retrieval with NO plaintext index on disk** — at
    DEK-unlock (store construction) an IN-MEMORY SQLite FTS5 index
    (``:memory:`` connection) is built over the decrypted chunk text of
    approved docs, and incrementally extended on each approve.  Hybrid
    retrieval = brute-force cosine over the in-RAM decrypted embedding cache
    (the existing substrate pattern) + FTS5 BM25, merged by reciprocal-rank
    fusion (k=60).  The rejected alternatives: a plaintext FTS5 table on disk
    (recoverable plaintext beside AES-GCM ciphertext — contradicts the
    Sprint-14 strict-residuals posture) and an encrypted-at-rest index file
    (rebuild-on-every-write complexity with no retrieval win at personal
    scale).
  * **WAL mode ON** — deliberate, unlike the substrate (which uses the default
    journal).  The knowledge bank takes interactive writes (submit/approve)
    while retrieval reads run in the same process; WAL removes writer-blocks-
    reader stalls.  App-layer encryption is proven WAL-safe (the session-store
    WAL-sidecar-never-leaks-plaintext regression test).
  * **Bulk reads decrypt-quarantine, writes hard fail-closed** (ADR-025 §2.7
    pattern): an undecryptable row during cache build / list_pending is
    skipped + logged with stable event code ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``
    and never returned as plaintext; a single-record write that cannot encrypt
    raises.
  * **Retrieved knowledge is ALWAYS untrusted** (ADR-023 / lesson 13): the
    ``provenance`` column is for the record, not for trust.  The AO grounds
    retrieval hits as ``UNTRUSTED_EXTERNAL`` with datamarking regardless of
    what this column says.
  * **Transaction discipline** (#655 adversarial-review fix): every mutating
    method runs its deterministic checks (validation, dedup verdict, doc_uuid
    collision) and ALL encryption BEFORE any DML, then executes the DML inside
    an explicit transaction (``with self._conn:``) that commits on success and
    rolls back on ANY exception.  The reproduced defect: the dedup-replace
    DELETE could be left in an open implicit transaction when a later check
    raised, and the next healthy operation's commit silently flushed it —
    destroying an unrelated pending row.
  * **Embed-window meta** (#655 adversarial-review fix): ``knowledge_meta``
    records the embedding token window the store's ``embed_fn`` was actually
    CONFIGURED with at first creation; reopening under a different configured
    window logs ``KNOWLEDGE_EMBED_WINDOW_MISMATCH`` and REFUSES retrieval and
    approve (the embedding-producing operations) so a mixed-depth store
    (ADR-031 §3) cannot be created or queried silently.  Review/reject reads
    stay available.
  * **Content fingerprint is KEYED at rest AND in the audit chain** (#655
    LA verdict 2026-06-10 — membership-oracle close).  The earlier shape
    stored the plaintext SHA-256 of the cleaned content as a plaintext
    column beside the AES-GCM ciphertext.  Under the stolen-DB threat model
    that is a membership oracle: hash any public article through the
    deterministic in-repo cleaner and test membership — exactly the attack
    the keyed ``source_hash`` was designed to deny.  ``content_sha256_keyed``
    therefore stores ``cipher.keyed_index`` over the UTF-8 bytes of the
    lowercase plaintext digest hex (BLOB, same ADR-025 §3 equality-leak
    residual as ``source_hash``).  The AO's staged-content integrity
    cross-check (recompute SHA-256 over the decrypted staging plaintext,
    compare against the INGEST_SUBMIT frame's plaintext sha) runs BEFORE the
    insert exactly as before — verification capability unchanged; only the
    at-rest form is keyed.  The same keyed hex is what the ingest audit
    chain carries as ``car_hash`` (LA-delegated sub-choice, orchestrator
    decision: KEYED) — a plaintext content digest in the signed-PLAINTEXT
    audit JSONL would recreate the oracle there; ADR-029's ratified
    plaintext exception covers action/identity labels, never
    content-derived hashes.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, NamedTuple

from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EMBED_MODEL_NAME,
    EMBED_MODEL_REVISION,
    EmbedFn,
    EmbedModelMismatch,
    _harden_db_file_dacl,
    chunk_text,
    detect_embed_model_mismatch,
)

logger = logging.getLogger(__name__)

# Knowledge-embedding token window (bge-small-en-v1.5 native max).  The
# substrate's leakage-detector default is 128 tokens; knowledge chunks are
# embedded at 512 so the whole 2048-char chunk informs its vector.
KNOWLEDGE_EMBED_MAX_TOKENS: int = 512

# Reciprocal-rank-fusion constant (the canonical value from the RRF paper;
# fixed, not config — changing it re-ranks every stored corpus silently).
RRF_K: int = 60

# Default hybrid-retrieval budget (overridden by [knowledge].retrieve_k).
DEFAULT_RETRIEVE_K: int = 4

_SOURCE_TYPES: frozenset[str] = frozenset({"url", "file", "paste"})
_DECISION_STATES: frozenset[str] = frozenset({"pending", "approved", "rejected"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_uuid        TEXT NOT NULL UNIQUE,
    source_type     TEXT NOT NULL CHECK(source_type IN ('url', 'file', 'paste')),
    source_ref      BLOB NOT NULL,
    source_hash     BLOB NOT NULL,
    provenance      TEXT NOT NULL DEFAULT 'untrusted_external',
    approval_state  TEXT NOT NULL DEFAULT 'pending'
                    CHECK(approval_state IN ('pending', 'approved', 'rejected')),
    title           BLOB,
    byline          BLOB,
    published_date  TEXT NOT NULL DEFAULT '',
    content         BLOB NOT NULL,
    content_sha256_keyed BLOB NOT NULL,
    cleaner_version TEXT NOT NULL DEFAULT '',
    word_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    decided_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_knowledge_state ON knowledge_docs(approval_state);
CREATE INDEX IF NOT EXISTS idx_knowledge_source_hash ON knowledge_docs(source_hash);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_uuid    TEXT NOT NULL REFERENCES knowledge_docs(doc_uuid) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        BLOB NOT NULL,
    embedding   BLOB NOT NULL,
    UNIQUE(doc_uuid, chunk_index)
);

CREATE TABLE IF NOT EXISTS knowledge_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Display-only article images (UC-003 Workstream B — DORMANT).  Stored
-- encrypted, keyed by doc_uuid, for inline preview/render ONLY.  These rows
-- are NEVER chunked / embedded / indexed / sent to any model (see the module
-- docstring and the no-VLM structural guard at the two _embed call sites).
-- ON DELETE CASCADE mirrors knowledge_chunks so deleting a doc reaps its
-- images (foreign_keys=ON is set at construction, same as the chunk table).
CREATE TABLE IF NOT EXISTS knowledge_images (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id       TEXT NOT NULL UNIQUE,
    doc_uuid       TEXT NOT NULL REFERENCES knowledge_docs(doc_uuid) ON DELETE CASCADE,
    image_hash     BLOB NOT NULL,   -- keyed-hash dedup index (HMAC over bytes)
    mime           TEXT NOT NULL,
    alt            BLOB NOT NULL,    -- encrypted (FieldCipher, AAD-bound)
    source_url     BLOB NOT NULL,   -- encrypted (FieldCipher, AAD-bound)
    data           BLOB NOT NULL,   -- encrypted image bytes (FieldCipher)
    approval_state TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_images_doc ON knowledge_images(doc_uuid);
CREATE INDEX IF NOT EXISTS idx_knowledge_images_hash ON knowledge_images(image_hash);

-- ── UC-010 Local Generative Imaging (ADR-033 — DORMANT) ──────────────────
-- Locally GENERATED images (text->image / image+text->image), born on-box from
-- an OPERATOR prompt.  A SIBLING of knowledge_images but with NO parent-doc FK:
-- a generated image belongs to a chat SESSION, not to an ingested article (no
-- cascade, no approval lifecycle).  Stored encrypted, display-only.  NEVER
-- chunked / embedded / indexed / sent to any model (the same no-VLM lock as
-- knowledge_images; _guard_embed_input enforces it at every embed call site).
-- Retention: DELETE-on-discard (ADR-032 parity) — delete_generated_image reaps
-- the row outright; there is no tombstone.  DISTINCT REGION from the Pass A
-- knowledge_images store (image-go-live) — the two limbs never share a column.
CREATE TABLE IF NOT EXISTS generated_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id    TEXT NOT NULL UNIQUE,            -- uuid4().hex display ref id
    session_id  TEXT NOT NULL,                   -- owning chat session (plaintext label)
    image_hash  BLOB NOT NULL,                   -- keyed-HMAC dedup index (over bytes)
    mime        TEXT NOT NULL,                   -- structural label (plaintext)
    prompt      BLOB NOT NULL,                   -- encrypted (FieldCipher, AAD-bound)
    data        BLOB NOT NULL,                   -- encrypted image bytes (FieldCipher)
    -- UC-010 Phase 1 (#667): the operator's own FORWARD-LOOKING record that this
    -- image has been exported to disk at least once via /save.  A small
    -- non-content structural flag (plaintext 0/1) — NOT a path, NOT a timestamp
    -- log (LA decision: a simple saved/locked boolean, not an export ledger).
    -- Default 0; flipped by mark_generated_image_saved.  A fresh DB gets the
    -- column here; a PRE-EXISTING table (created before this build) gets it via
    -- the idempotent ALTER-TABLE migration in __init__ (existing rows -> 0, i.e.
    -- not-saved: past /saves are deliberately NOT retroactively known).
    saved       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_generated_images_session ON generated_images(session_id);
CREATE INDEX IF NOT EXISTS idx_generated_images_hash ON generated_images(image_hash);

-- Operator preferences (Learning Loops Loop 1, #770 M1) — the OPERATOR_PREFERENCE
-- provenance tier's verbatim store.  P7: SAME substrate, same DEK, same
-- born-encrypted discipline — no new store.  P2: ``body`` is the operator's
-- utterance VERBATIM (never LLM-paraphrased); ``type_tag`` is a cosmetic label
-- (address-form|standing-rule|fact).  P5: last-writer-wins with audit history —
-- an edit UPDATEs the active row in place (stable pref_id + created => stable,
-- append-minimal render order, P9) and inserts a ``superseded`` audit row
-- carrying the prior verbatim body; a delete flips status to ``deleted``
-- (audit retained, excluded from rendering).  P6: NO decay column, NO expiry.
-- P8: the ONLY writer is the AO PREFERENCE_WRITE handler (the explicit operator
-- command path); no model-callable tool references this table — locked by
-- test_preference_write_authority.py.  NEVER chunked / embedded / indexed
-- (not a retrieval surface; the pinned block is rendered directly from rows).
CREATE TABLE IF NOT EXISTS operator_preferences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pref_id     TEXT NOT NULL UNIQUE,             -- uuid4().hex stable id
    status      TEXT NOT NULL DEFAULT 'active',   -- active|superseded|deleted
    type_tag    TEXT NOT NULL,                    -- cosmetic label (plaintext)
    supersedes  TEXT,                             -- audit chain: pref_id this row is history OF
    subject     BLOB,                             -- encrypted (FieldCipher, AAD-bound)
    body        BLOB NOT NULL,                    -- encrypted verbatim (FieldCipher, AAD-bound)
    source      TEXT NOT NULL,                    -- 'operator-explicit' (M1's only source)
    created     TEXT NOT NULL,
    updated     TEXT NOT NULL,
    expires     TEXT                              -- #770 M2 W2: operator-stated ISO date (YYYY-MM-DD); NULL = no expiry (P6: the SYSTEM never decides to forget)
);
CREATE INDEX IF NOT EXISTS idx_operator_preferences_status ON operator_preferences(status);
"""


class KnowledgeBankError(RuntimeError):
    """Raised on invalid knowledge-bank operations (Fail-Closed)."""


class KnowledgeSubmitResult(NamedTuple):
    """Outcome of :meth:`EncryptedKnowledgeBank.submit_pending`."""

    doc_uuid: str
    state: str               # 'pending' | 'already_ingested'
    replaced_prior: bool     # True when a prior pending/rejected row was replaced
    source_hash_hex: str     # hex of the keyed dedup index (labels-only audit ref)


class KnowledgeDoc(NamedTuple):
    """A decrypted knowledge-bank document record."""

    doc_uuid: str
    source_type: str
    source_ref: str
    provenance: str
    approval_state: str
    title: str
    byline: str
    published_date: str
    content: str
    content_sha256_keyed: str
    """Hex of the KEYED content-digest index (never the plaintext SHA-256)."""
    cleaner_version: str
    word_count: int
    created_at: str
    decided_at: str | None


class KnowledgeImage(NamedTuple):
    """A decrypted display-only image record (UC-003 Workstream B).

    Returned by :meth:`EncryptedKnowledgeBank.get_images_for_doc` for inline
    rendering ONLY — never chunked, embedded, or sent to any model.
    """

    image_id: str
    doc_uuid: str
    mime: str
    alt: str
    source_url: str
    data: bytes
    approval_state: str
    created_at: str


class GeneratedImage(NamedTuple):
    """A decrypted locally-generated image record (UC-010, ADR-033).

    Returned by :meth:`EncryptedKnowledgeBank.get_generated_image` for inline
    rendering ONLY — born on-box from an operator prompt, display-only, never
    chunked / embedded / indexed / fed to any model.
    """

    image_id: str
    session_id: str
    mime: str
    prompt: str
    data: bytes
    created_at: str


class GeneratedImageMeta(NamedTuple):
    """Cheap METADATA for one generated image (UC-010 Phase 1, #667).

    Returned by :meth:`EncryptedKnowledgeBank.list_generated_images` for the
    ``/images`` listing.  Carries ONLY the cheap, non-content columns — there is
    deliberately NO ``prompt`` and NO ``data`` field, and the list method reads
    NEITHER encrypted column (no decrypt happens to build a listing).  The
    encrypted prompt + image bytes still cross ONLY via the existing resolve
    corridor (display) or ``/save`` (explicit export), never via a list.
    """

    image_id: str
    session_id: str
    mime: str
    byte_size: int
    """Size in bytes of the stored (encrypted) ``data`` blob — a cheap
    ``length(data)`` SQL aggregate, NOT a decrypt (so the list stays
    metadata-only).  Includes the AES-GCM nonce+tag overhead, so it is the
    on-disk ciphertext length, a faithful ~plaintext-size proxy for a UI hint."""
    saved: bool
    created_at: str


class OperatorPreference(NamedTuple):
    """A decrypted operator-preference row (Learning Loops Loop 1, #770 M1).

    ``body`` is the operator's utterance VERBATIM (P2 — stored byte-identical,
    never paraphrased).  ``status`` is ``active`` (rendered into the pinned
    block), ``superseded`` (audit history of an edit — the prior verbatim body,
    never rendered), or ``deleted`` (audit tombstone, never rendered).
    """

    pref_id: str
    status: str
    type_tag: str
    subject: str
    body: str
    source: str
    supersedes: str
    """pref_id of the ACTIVE row this audit row is history of ('' for active rows)."""
    created: str
    updated: str
    expires: str = ""
    """#770 M2 W2 — operator-stated ISO expiry date (YYYY-MM-DD), or '' for none.
    The pinned block stops rendering the row on/after this date; /preferences
    still LISTS it, flagged expired.  P6-safe: the SYSTEM never decides to forget
    — only the operator's own stated bound applies, and nothing is auto-deleted."""


#: Cosmetic preference type labels (design §3.2 envelope).  A mis-tag is
#: cosmetic, never lossy — an unrecognized tag COERCES to the default rather
#: than refusing the write (the body, the load-bearing part, stays verbatim).
PREFERENCE_TYPE_TAGS: frozenset[str] = frozenset(
    {"address-form", "standing-rule", "fact"}
)
DEFAULT_PREFERENCE_TYPE_TAG: str = "standing-rule"

#: Deterministic near-duplicate/contradiction threshold (P5): Jaccard overlap
#: of normalized token sets at or above this flags a REQUIRES_CONFIRMATION.
#: Deliberately deterministic + offline (no embed dependency) for M1; the M2
#: propose-and-confirm flow may refine it.
PREFERENCE_SIMILARITY_THRESHOLD: float = 0.6


def _pref_similarity_tokens(text: str) -> frozenset[str]:
    """Normalized token set for the deterministic preference-similarity check."""
    return frozenset(t for t in re.split(r"[^a-z0-9]+", text.lower()) if t)


class KnowledgeHit(NamedTuple):
    """A single hybrid-retrieval hit."""

    doc_uuid: str
    chunk_index: int
    title: str
    source_type: str
    text: str
    score: float  # reciprocal-rank-fusion score (higher = better)


def _doc_aad_id(doc_uuid: str) -> str:
    """Natural row identity for knowledge_docs AAD binding."""
    return doc_uuid


def _chunk_aad_id(doc_uuid: str, chunk_index: int) -> str:
    """Natural row identity for knowledge_chunks AAD binding."""
    return f"{doc_uuid}|{chunk_index}"


def _image_aad_id(doc_uuid: str, image_id: str) -> str:
    """Natural row identity for knowledge_images AAD binding.

    Binds BOTH the parent ``doc_uuid`` and the row's own ``image_id`` (a
    ``uuid4().hex`` string) — mirroring :func:`_chunk_aad_id` and the image
    STAGING layer (``image_staging`` binds ``<doc_uuid>:<image_id>``).  So a
    ciphertext relocated to a different column, a different image, OR
    re-associated to a different document (a tampered plaintext ``doc_uuid``
    column) all fail authentication and fall into the decrypt-quarantine path —
    closing the cross-doc replay the image-only-AAD left open (review, 2026-06-14).
    """
    return f"{doc_uuid}|{image_id}"


def _generated_image_aad_id(session_id: str, image_id: str) -> str:
    """Natural row identity for generated_images AAD binding (UC-010, ADR-033).

    Binds BOTH the owning ``session_id`` and the row's own ``image_id`` (a
    ``uuid4().hex`` string), mirroring :func:`_image_aad_id`.  So a generated-
    image ciphertext relocated to a different column, a different image, OR
    re-associated to a different session all fail authentication and fall into
    the decrypt-quarantine path.
    """
    return f"{session_id}|{image_id}"


def _pref_aad_id(pref_id: str) -> str:
    """Natural row identity for operator_preferences AAD binding (#770 M1).

    The row's own ``pref_id`` (a ``uuid4().hex`` string).  Audit rows carry
    their OWN pref_id, so a superseded body's ciphertext re-encrypts under the
    audit row's identity — a ciphertext relocated between rows or columns
    fails authentication (the same discipline as every other encrypted table).
    """
    return pref_id


# The local image scheme the cleaner rewrites refs to (mirrors
# services.cleaner.src.image_refs.BLARAI_IMG_SCHEME — duplicated as a literal
# here to avoid a knowledge-bank -> cleaner cross-service import for one token).
# The id runs up to the markdown ref close ``)`` / whitespace / ``]``.
_BLARAI_IMG_REF_RE = re.compile(r"blarai-img://([^)\s\]]+)")


def _extract_local_image_ids(text: str) -> frozenset[str]:
    """The set of ``blarai-img://<id>`` image ids referenced in *text*.

    Used by :meth:`EncryptedKnowledgeBank.submit_pending` to decide which prior
    images SURVIVE an edited re-submit: an image whose local ref the operator
    KEPT in the edited body is migrated to the new doc; one they deleted is
    reaped by the dedup-replace CASCADE (the A×B survivorship rule, #663
    c.1087).  ``text`` is definitionally the edited body (the submit content),
    so the referenced-set IS the survivor-set — no separate signal is needed.
    """
    if not text:
        return frozenset()
    return frozenset(_BLARAI_IMG_REF_RE.findall(text))


def _normalize_source_ref(source_ref: str) -> bytes:
    """Canonical bytes of a source reference (URL/path/paste label) for hashing."""
    return source_ref.strip().encode("utf-8")


def _fts_match_expr(query: str) -> str:
    """Build a safe FTS5 MATCH expression from free-form query text.

    Every alphanumeric word is double-quoted (FTS5 string syntax — quoting
    neutralises operators like ``NEAR``/``*``/``-``) and OR-joined so any
    overlapping term contributes to BM25.  Returns ``""`` when the query
    carries no indexable words (caller skips the lexical limb).
    """
    words = re.findall(r"\w+", query, flags=re.UNICODE)
    return " OR ".join(f'"{w}"' for w in words)


def _guard_embed_input(texts: object) -> list[str]:
    """No-VLM structural lock: refuse anything but a list of plain ``str``.

    The embedder is a TEXT embedding model (bge-small-en-v1.5).  Image bytes
    are display-only and must NEVER reach it — there is no vision-language
    model in BlarAI's runtime and this store must not become the seam that
    smuggles one in.  This guard runs at EVERY ``self._embed(...)`` call site
    (approve + retrieve) so a future wiring mistake that routes ``bytes`` (or a
    bytes-bearing sequence) into the embed path fails LOUDLY at the boundary
    instead of silently producing a garbage vector or — worse — handing raw
    image bytes to an inference call.

    Returns the validated list unchanged (so call sites read naturally:
    ``self._embed(_guard_embed_input(chunks))``).

    Raises:
        TypeError: if *texts* is not a non-empty list of ``str`` only.
    """
    if not isinstance(texts, list) or not texts:
        raise TypeError(
            "embed() received non-string; image bytes must not reach the embedder"
        )
    for item in texts:
        if not isinstance(item, str):
            raise TypeError(
                "embed() received non-string; image bytes must not reach the embedder"
            )
    return texts


class EncryptedKnowledgeBank:
    """AES-GCM-encrypted, approval-gated knowledge store with hybrid retrieval.

    Lifecycle: ``submit_pending`` holds cleaned content only; ``approve``
    chunks (2048/256 chars, the substrate chunker) + embeds (512-token window)
    + indexes; ``reject`` flips the state and retains content (tombstone).
    ``retrieve`` reads APPROVED chunks only.

    Dedup (keyed ``source_hash`` over ciphertext): a re-submitted identical
    source REPLACES a prior *pending* row (the operator refreshed the fetch
    before deciding) and also a prior *rejected* row (an explicit re-submit is
    a fresh-decision request that supersedes the tombstone) — but NEVER an
    approved one: an approved dedup conflict returns a distinct
    ``already_ingested`` result and leaves the stored document untouched.

    Fail-Closed: constructor refuses without a real
    :class:`~shared.security.field_cipher.FieldCipher`; writes that cannot
    encrypt raise; bulk reads quarantine undecryptable rows (ADR-025 §2.7).

    ``has_encryption: bool = True`` — production-wiring regression lock.

    Args:
        db_path: Path to the knowledge SQLite file (``:memory:`` for tests).
        embed_fn: Callable mapping ``list[str]`` to an ``(N, 384)`` numpy array
            of L2-normalised float32 embeddings.  The AO binds this to
            ``LeakageDetector.embed_documents`` at the configured
            ``[knowledge].embed_max_tokens`` window — NOT the 128-token
            leakage path.
        cipher: :class:`FieldCipher` derived from the unsealed shared DEK.
        retrieve_k: Default top-k budget for :meth:`retrieve`.
        embed_max_tokens: The token window the supplied *embed_fn* is actually
            bound at.  Recorded in ``knowledge_meta`` at first creation; a
            reopen under a DIFFERENT configured window refuses retrieval and
            approve loudly (``KNOWLEDGE_EMBED_WINDOW_MISMATCH``) instead of
            silently mixing embedding depths (ADR-031 §3).
        embed_model / embed_model_revision: Identity of the model *embed_fn*
            actually runs (Vikunja #794).  Recorded in ``knowledge_meta`` at
            first creation; a reopen under a DIFFERENT identity loud-disables the
            VECTOR limb only — BM25/lexical retrieval keeps working — instead of
            fusing cosine scores from a different embedding space (ADR-031 §7
            loud-disable middle ground).
    """

    #: Regression-lock attribute (same contract as EncryptedSubstrateStore).
    has_encryption: bool = True

    def __init__(
        self,
        db_path: str,
        embed_fn: EmbedFn,
        cipher: "FieldCipher",  # type: ignore[name-defined]  # noqa: F821
        retrieve_k: int = DEFAULT_RETRIEVE_K,
        embed_max_tokens: int = KNOWLEDGE_EMBED_MAX_TOKENS,
        embed_model: str = EMBED_MODEL_NAME,
        embed_model_revision: str = EMBED_MODEL_REVISION,
    ) -> None:
        from shared.security.field_cipher import FieldCipher  # local import; no circular dep

        if not isinstance(cipher, FieldCipher):
            raise TypeError(
                "EncryptedKnowledgeBank requires a FieldCipher instance; "
                f"got {type(cipher).__name__!r}.  Pass a FieldCipher derived "
                "from the unsealed DEK."
            )
        self._embed = embed_fn
        self._cipher = cipher
        self._retrieve_k = int(retrieve_k)
        self._embed_max_tokens = int(embed_max_tokens)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        _harden_db_file_dacl(db_path)
        # WAL ON — deliberate divergence from substrate.db (see module docstring).
        # A no-op result on ':memory:' is fine (SQLite reports 'memory').
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # secure_delete=ON (FULL) — DELETEd rows (rejected article images,
        # discarded generated images, replaced docs) are overwritten with zeros
        # in the freed pages, not merely unlinked. Makes the ADR-032/ADR-033
        # "purges at rest" / "DELETE-on-discard" claims literally true. Covers
        # BOTH knowledge_images and generated_images (same connection). In WAL
        # the zeroing lands in the -wal frames and reaches the main file at
        # checkpoint (the SE-1 residual probe forces wal_checkpoint(TRUNCATE)
        # before reading raw bytes). UC-010 WS2.
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA)
        # In-place schema migrations for tables that predate a column add.
        # ``CREATE TABLE IF NOT EXISTS`` above is a no-op on an EXISTING table, so
        # a column added to a table's definition never reaches a store created by
        # an older build — an explicit, idempotent ALTER is required (#667).
        self._migrate_schema()
        # The recorded window is the CONFIGURED one actually bound into
        # embed_fn (not the module constant) — INSERT OR IGNORE keeps the
        # ORIGINAL value on reopen so a config drift is detectable below.
        for key, value in (
            ("embed_dim", str(EMBED_DIM)),
            ("embed_model", embed_model),
            ("embed_model_revision", embed_model_revision),
            ("embed_max_tokens", str(self._embed_max_tokens)),
            ("schema_version", "1"),
        ):
            self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_meta(key, value) VALUES(?, ?)",
                (key, value),
            )
        self._conn.commit()

        # Stored-vs-configured embed-window cross-check (#655 review fix —
        # detectability made real).  On mismatch the embedding-producing
        # operations (retrieve / approve) REFUSE loudly; review/reject reads
        # stay available so the operator can still triage pending documents.
        stored_row = self._conn.execute(
            "SELECT value FROM knowledge_meta WHERE key='embed_max_tokens'"
        ).fetchone()
        stored_window = (
            str(stored_row[0]) if stored_row is not None
            else str(self._embed_max_tokens)
        )
        self._embed_window_mismatch: tuple[str, int] | None = None
        if stored_window != str(self._embed_max_tokens):
            self._embed_window_mismatch = (stored_window, self._embed_max_tokens)
            logger.error(
                "KNOWLEDGE_EMBED_WINDOW_MISMATCH "
                "event=KNOWLEDGE_EMBED_WINDOW_MISMATCH stored=%s configured=%d "
                "-- this store's chunks were embedded at a different token "
                "window than the configured embed_fn; retrieve and approve "
                "REFUSE until the windows agree (run the re-embed ceremony or "
                "restore [knowledge].embed_max_tokens).  Review/reject reads "
                "remain available.",
                stored_window,
                self._embed_max_tokens,
            )

        # Stored-vs-configured embedding-MODEL identity cross-check (#794).  A
        # DIFFERENT model/revision than the one whose vectors are on disk means
        # cosine scores are being compared across two embedding spaces.  Posture:
        # loud-disable the VECTOR limb ONLY (ADR-031 §7 middle ground) — BM25 does
        # not depend on the embedder, so lexical retrieval keeps working while the
        # cosine limb is skipped in retrieve().  None ⇒ identity agrees.
        self._embed_model_mismatch: EmbedModelMismatch | None = detect_embed_model_mismatch(
            self._conn,
            "knowledge_meta",
            embed_model,
            embed_model_revision,
            "knowledge.db",
        )

        # In-RAM retrieval state, built once at DEK-unlock (construction) from
        # APPROVED chunks and extended incrementally on approve.  All access is
        # serialised by the lock (AO is connection-per-message today; the lock
        # makes the cache safe if that ever changes).
        self._lock = threading.RLock()
        self._chunk_vecs: dict[tuple[str, int], Any] = {}
        self._chunk_texts: dict[tuple[str, int], str] = {}
        self._doc_titles: dict[str, str] = {}
        self._doc_source_types: dict[str, str] = {}
        self._fts = sqlite3.connect(":memory:", check_same_thread=False)
        self._fts.execute(
            "CREATE VIRTUAL TABLE knowledge_fts USING fts5("
            "text, doc_uuid UNINDEXED, chunk_index UNINDEXED, "
            "tokenize='porter unicode61')"
        )
        self._load_approved_caches()

        logger.info(
            "EncryptedKnowledgeBank initialised: %s (%d approved chunks indexed)",
            db_path,
            len(self._chunk_vecs),
        )

    # ── Schema migration ──────────────────────────────────────────────────

    def _has_column(self, table: str, column: str) -> bool:
        """True if *table* already has *column* (PRAGMA table_info introspection)."""
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        # row[1] is the column name in PRAGMA table_info output.
        return any(str(r[1]) == column for r in rows)

    def _migrate_schema(self) -> None:
        """Idempotent in-place migrations for stores created by an older build.

        SQLite ``CREATE TABLE IF NOT EXISTS`` does NOT add a column to a table
        that already exists, so a column added to a table's definition only lands
        on a fresh DB.  Each migration below is guarded by a column-existence
        check (so it is a no-op on a current store) and adds the column with a
        safe default that preserves existing rows.

        UC-010 Phase 1 (#667): ``generated_images.saved`` — the operator's
        forward-looking "this image has been /save'd at least once" flag.
        Existing rows migrate to ``0`` (not-saved): past exports are deliberately
        NOT reconstructed (there is no on-disk record of them, and inventing one
        would be wrong).  ``ADD COLUMN ... DEFAULT 0`` is a metadata-only SQLite
        operation — it does NOT rewrite rows or touch the encrypted blobs.
        """
        if not self._has_column("generated_images", "saved"):
            self._conn.execute(
                "ALTER TABLE generated_images "
                "ADD COLUMN saved INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()
            logger.info(
                "Knowledge bank migration: added generated_images.saved "
                "(existing rows -> not-saved; UC-010 Phase 1 #667)"
            )

        # #770 M2 W2: operator-stated preference expiry. A nullable column so
        # existing rows migrate to NULL (no expiry — an M1 preference stays
        # unbounded, which is exactly its prior behaviour).  Plaintext ISO date
        # (not content-bearing — it is a bound the operator SAID, not a secret);
        # NULL never renders as expired.
        if not self._has_column("operator_preferences", "expires"):
            self._conn.execute(
                "ALTER TABLE operator_preferences ADD COLUMN expires TEXT"
            )
            self._conn.commit()
            logger.info(
                "Knowledge bank migration: added operator_preferences.expires "
                "(existing rows -> NULL/no-expiry; #770 M2 W2)"
            )

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close both connections; the in-memory FTS index simply vanishes."""
        with self._lock:
            self._chunk_vecs.clear()
            self._chunk_texts.clear()
            self._doc_titles.clear()
            self._doc_source_types.clear()
            try:
                self._fts.close()
            except Exception:  # noqa: BLE001 — close must not raise
                pass
        self._conn.close()

    # ── Encrypt/decrypt helpers ──────────────────────────────────────────

    def _enc_doc_field(self, column: str, doc_uuid: str, value: str) -> bytes:
        from shared.security.field_cipher import make_aad_for

        return self._cipher.encrypt(
            value.encode("utf-8"),
            aad=make_aad_for("knowledge_docs", column, _doc_aad_id(doc_uuid)),
        )

    def _dec_doc_field(self, column: str, doc_uuid: str, blob: bytes) -> str:
        from shared.security.field_cipher import make_aad_for

        return self._cipher.decrypt(
            bytes(blob),
            aad=make_aad_for("knowledge_docs", column, _doc_aad_id(doc_uuid)),
        ).decode("utf-8")

    # ── Submit (pending) ─────────────────────────────────────────────────

    def source_hash_for(self, source_ref: str) -> bytes:
        """Deterministic keyed dedup index for a source reference."""
        return self._cipher.keyed_index(_normalize_source_ref(source_ref))

    def content_digest_keyed(self, content_sha256: str) -> bytes:
        """Keyed at-rest/audit form of a plaintext content digest (#655).

        ``HMAC(k_idx, utf8(lowercase plaintext-sha256 hex))`` — the single
        derivation used for BOTH the ``content_sha256_keyed`` column and the
        ingest audit ``car_hash``, so the two surfaces can never drift.  The
        plaintext digest itself stays RAM-only (the AO's staging integrity
        cross-check); persisting it beside the ciphertext was a membership
        oracle (module docstring).
        """
        return self._cipher.keyed_index(
            content_sha256.strip().lower().encode("utf-8")
        )

    def content_digest_keyed_hex(self, content_sha256: str) -> str:
        """Hex of :meth:`content_digest_keyed` (audit-chain ``car_hash`` form)."""
        return self.content_digest_keyed(content_sha256).hex()

    def source_hash_hex_for(self, doc_uuid: str) -> str:
        """Hex of the stored source_hash for *doc_uuid* (labels-only audit ref)."""
        row = self._conn.execute(
            "SELECT source_hash FROM knowledge_docs WHERE doc_uuid=?", (doc_uuid,)
        ).fetchone()
        if row is None:
            raise KnowledgeBankError(f"Unknown doc_uuid: {doc_uuid!r}")
        return bytes(row[0]).hex()

    def _validate_submit(
        self,
        *,
        doc_uuid: str,
        source_type: str,
        source_ref: str,
        content: str,
    ) -> tuple[bytes, str | None, str | None]:
        """Deterministic, READ-ONLY submit validation (no DML — Fail-Closed).

        Every check that can refuse a submit runs here, BEFORE any DML, so a
        refusal can never leave statements stranded in an open transaction
        (the reproduced #655 corruption defect).

        Returns:
            ``(source_hash, prior_doc_uuid, prior_state)`` — the prior fields
            are ``None`` when no row with the same source exists.

        Raises:
            KnowledgeBankError: On any validation failure, including the
                doc_uuid-collision check (now ordered before the dedup DELETE).
        """
        if not doc_uuid.strip():
            raise KnowledgeBankError("submit_pending: doc_uuid must be non-empty")
        if source_type not in _SOURCE_TYPES:
            raise KnowledgeBankError(
                f"submit_pending: invalid source_type {source_type!r} "
                f"(expected one of {sorted(_SOURCE_TYPES)})"
            )
        if not source_ref.strip():
            raise KnowledgeBankError("submit_pending: source_ref must be non-empty")
        if not content.strip():
            raise KnowledgeBankError("submit_pending: content must be non-empty")

        source_hash = self.source_hash_for(source_ref)
        prior = self._conn.execute(
            "SELECT doc_uuid, approval_state FROM knowledge_docs WHERE source_hash=?",
            (source_hash,),
        ).fetchone()
        prior_uuid = str(prior[0]) if prior is not None else None
        prior_state = str(prior[1]) if prior is not None else None

        # doc_uuid-collision check BEFORE any DML: a row with this doc_uuid
        # that is NOT the same-source row about to be replaced is a caller
        # bug.  (Approved-dedup short-circuits before any DML too, so the
        # check is only meaningful on the pending/rejected/new paths.)
        if prior_state != "approved":
            existing = self._conn.execute(
                "SELECT 1 FROM knowledge_docs WHERE doc_uuid=?", (doc_uuid,)
            ).fetchone()
            if existing is not None and doc_uuid != prior_uuid:
                raise KnowledgeBankError(
                    f"submit_pending: doc_uuid {doc_uuid!r} already exists with a "
                    "different source — doc_uuid reuse is a caller bug (Fail-Closed)"
                )
        return source_hash, prior_uuid, prior_state

    def precheck_submit(
        self,
        *,
        doc_uuid: str,
        source_type: str,
        source_ref: str,
        content: str,
    ) -> str:
        """Read-only dry-run of :meth:`submit_pending`'s deterministic outcome.

        Returns the state ``submit_pending`` would report (``'pending'`` or
        ``'already_ingested'``) and raises :class:`KnowledgeBankError` exactly
        where it would refuse — without mutating anything.  Lets the AO order
        the ingest audit append BEFORE the mutation (audit-first) without
        writing audit records for deterministically-refused or no-op submits.
        """
        _hash, _uuid, prior_state = self._validate_submit(
            doc_uuid=doc_uuid,
            source_type=source_type,
            source_ref=source_ref,
            content=content,
        )
        return "already_ingested" if prior_state == "approved" else "pending"

    def submit_pending(
        self,
        *,
        doc_uuid: str,
        source_type: str,
        source_ref: str,
        content: str,
        title: str = "",
        byline: str = "",
        published_date: str = "",
        content_sha256: str = "",
        cleaner_version: str = "",
        word_count: int = 0,
        provenance: str = "untrusted_external",
    ) -> KnowledgeSubmitResult:
        """Persist a cleaned document as a PENDING row (content only, no chunks).

        Hard fail-closed: any validation or encryption failure raises — a
        pending row is either fully, correctly encrypted on disk or absent.
        All deterministic checks and ALL encryption run BEFORE any DML; the
        dedup-replace DELETE and the INSERT execute inside one explicit
        transaction (commit on success, rollback on ANY exception) so a
        failure can never strand a destructive statement in an open implicit
        transaction for a later commit to flush (#655 review fix).

        Returns:
            :class:`KnowledgeSubmitResult` with ``state='pending'`` on success,
            or ``state='already_ingested'`` when an APPROVED document with the
            same source already exists (that document is left untouched).
        """
        source_hash, prior_uuid, prior_state = self._validate_submit(
            doc_uuid=doc_uuid,
            source_type=source_type,
            source_ref=source_ref,
            content=content,
        )
        if not content_sha256:
            content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # At-rest form is KEYED (#655 LA verdict 2026-06-10): the plaintext
        # digest never touches disk — see the module docstring.
        content_sha256_keyed = self.content_digest_keyed(content_sha256)

        if prior_state == "approved":
            # Never replace an approved document via dedup — distinct result.
            logger.info(
                "Knowledge submit deduplicated: source already APPROVED as %s",
                prior_uuid,
            )
            return KnowledgeSubmitResult(
                doc_uuid=str(prior_uuid),
                state="already_ingested",
                replaced_prior=False,
                source_hash_hex=source_hash.hex(),
            )

        replaced_prior = prior_uuid is not None
        now = datetime.now(timezone.utc).isoformat()

        # Encrypt every field BEFORE opening the transaction — a cipher
        # failure must surface with zero DML executed.
        enc_source_ref = self._enc_doc_field("source_ref", doc_uuid, source_ref)
        enc_title = self._enc_doc_field("title", doc_uuid, title)
        enc_byline = self._enc_doc_field("byline", doc_uuid, byline)
        enc_content = self._enc_doc_field("content", doc_uuid, content)

        # Migrate SURVIVING display-only images (#2 / A×B, c.1087): on an edited
        # re-submit the dedup-replace DELETE reaps the prior doc's images via ON
        # DELETE CASCADE.  Images whose ``blarai-img://<id>`` ref the operator
        # KEPT in the edited body are re-keyed to the new doc here; the rest are
        # intentionally dropped.  ALL crypto runs BEFORE the transaction (the
        # AAD binds doc_uuid, so each surviving row is decrypted under the prior
        # doc's AAD and re-encrypted under the new doc's — a bare relabel would
        # fail authentication).  Dormant by construction: with images disabled
        # knowledge_images is empty and this is a no-op.
        migrated_images: list[tuple[Any, ...]] = []
        if prior_uuid is not None:
            migrated_images = self._migrate_surviving_images(
                str(prior_uuid), doc_uuid, _extract_local_image_ids(content)
            )

        # Atomic dedup-replace + insert: commit on success, rollback on ANY
        # exception ('with self._conn:' is sqlite3's transaction context).
        with self._conn:
            if prior_uuid is not None:
                # pending or rejected: the re-submit supersedes the prior row.
                self._conn.execute(
                    "DELETE FROM knowledge_docs WHERE doc_uuid=?", (prior_uuid,)
                )
            self._conn.execute(
                "INSERT INTO knowledge_docs("
                "doc_uuid, source_type, source_ref, source_hash, provenance, "
                "approval_state, title, byline, published_date, content, "
                "content_sha256_keyed, cleaner_version, word_count, created_at, "
                "decided_at) "
                "VALUES(?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    doc_uuid,
                    source_type,
                    enc_source_ref,
                    source_hash,
                    provenance,
                    enc_title,
                    enc_byline,
                    published_date,
                    enc_content,
                    content_sha256_keyed,
                    cleaner_version,
                    int(word_count),
                    now,
                ),
            )
            # Re-INSERT surviving images under the new doc_uuid — AFTER the new
            # doc row exists (the FK no-orphan invariant) and inside the SAME
            # transaction, so the CASCADE-reap and the re-key commit/rollback
            # together.  Empty (no-op) in the dormant default.
            if migrated_images:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO knowledge_images("
                    "image_id, doc_uuid, image_hash, mime, alt, source_url, "
                    "data, approval_state, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    migrated_images,
                )
        logger.info(
            "Knowledge submit: doc %s pending (source_type=%s, %d words%s)",
            doc_uuid,
            source_type,
            word_count,
            ", replaced prior row" if replaced_prior else "",
        )
        return KnowledgeSubmitResult(
            doc_uuid=doc_uuid,
            state="pending",
            replaced_prior=replaced_prior,
            source_hash_hex=source_hash.hex(),
        )

    # ── Decide (approve / reject) ────────────────────────────────────────

    def approval_state_for(self, doc_uuid: str) -> str:
        """Read-only approval_state of *doc_uuid* (raises on unknown)."""
        row = self._conn.execute(
            "SELECT approval_state FROM knowledge_docs WHERE doc_uuid=?",
            (doc_uuid,),
        ).fetchone()
        if row is None:
            raise KnowledgeBankError(f"Unknown doc_uuid: {doc_uuid!r}")
        return str(row[0])

    def check_decision(self, doc_uuid: str, decision: str) -> str:
        """Read-only validation that *decision* may be attempted on *doc_uuid*.

        Raises :class:`KnowledgeBankError` exactly where :meth:`approve` /
        :meth:`reject` would refuse deterministically (unknown doc,
        approve-a-rejected, reject-an-approved) WITHOUT mutating anything —
        the single source of truth for those refusals.  Lets the AO order its
        audit append BEFORE the mutation (audit-first) without ever writing a
        record for a deterministically-refused decision.

        Returns:
            The current approval_state.
        """
        if decision not in ("approve", "reject"):
            raise KnowledgeBankError(
                f"check_decision: unknown decision {decision!r} (approve|reject)"
            )
        state = self.approval_state_for(doc_uuid)
        if decision == "approve" and state == "rejected":
            raise KnowledgeBankError(
                f"approve: doc {doc_uuid!r} is rejected — re-submit the source "
                "for a fresh decision cycle (Fail-Closed)"
            )
        if decision == "reject" and state == "approved":
            raise KnowledgeBankError(
                f"reject: doc {doc_uuid!r} is already approved — removing "
                "approved knowledge is a separate lifecycle action (Fail-Closed)"
            )
        return state

    def approve(self, doc_uuid: str) -> int:
        """Approve a pending document: chunk + embed + index + flip state.

        Idempotent for an already-approved document (returns its existing
        chunk count without re-embedding).  Approving a REJECTED document
        raises — the tombstoned decision stands until the source is
        re-submitted (a fresh decision cycle).

        Transaction discipline (#655 review fix): every deterministic check,
        the decrypt, the chunking/embedding, and ALL chunk encryption happen
        BEFORE any DML; the chunk INSERTs + the state UPDATE then run inside
        one explicit transaction that commits on success and rolls back on
        ANY exception — a mid-insert failure leaves the document pending with
        zero chunks, never half-indexed and never stranded in an open
        transaction.

        Returns:
            The number of chunks indexed for this document.
        """
        from shared.security.field_cipher import make_aad_for

        state = self.check_decision(doc_uuid, "approve")
        # Refuse to extend a window-mismatched store BEFORE the idempotent
        # short-circuit: an approve on a mismatched store is a request to
        # create exactly the mixed-depth corpus ADR-031 §3 rejects.
        self._check_embed_window("approve")
        if state == "approved":
            existing = self._conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_uuid=?",
                (doc_uuid,),
            ).fetchone()
            return int(existing[0])

        row = self._conn.execute(
            "SELECT content, title, source_type FROM knowledge_docs "
            "WHERE doc_uuid=?",
            (doc_uuid,),
        ).fetchone()
        if row is None:  # pragma: no cover — check_decision just saw the row
            raise KnowledgeBankError(f"approve: unknown doc_uuid {doc_uuid!r}")

        # Hard fail-closed single-record read: a pending row whose content
        # cannot decrypt must surface, not silently approve an empty document.
        content = self._dec_doc_field("content", doc_uuid, row[0])
        title = self._dec_doc_field("title", doc_uuid, row[1])
        source_type = str(row[2])

        chunks = chunk_text(content)
        if not chunks:
            raise KnowledgeBankError(
                f"approve: doc {doc_uuid!r} produced no chunks (empty content)"
            )
        import numpy as np

        # No-VLM structural lock: the embedder is text-only; image bytes must
        # never reach it (see _guard_embed_input + the module docstring).
        embeddings = np.asarray(
            self._embed(_guard_embed_input(chunks)), dtype=np.float32
        )
        now = datetime.now(timezone.utc).isoformat()

        chunk_rows: list[tuple[Any, ...]] = []
        for i, chunk in enumerate(chunks):
            nat_id = _chunk_aad_id(doc_uuid, i)
            enc_text = self._cipher.encrypt(
                chunk.encode("utf-8"),
                aad=make_aad_for("knowledge_chunks", "text", nat_id),
            )
            enc_emb = self._cipher.encrypt(
                embeddings[i].tobytes(),
                aad=make_aad_for("knowledge_chunks", "embedding", nat_id),
            )
            chunk_rows.append((doc_uuid, i, enc_text, enc_emb))

        # Atomic chunk-index + state-flip: commit on success, rollback on ANY
        # exception (a mid-insert failure must leave zero chunks, state
        # pending, and NOTHING stranded in an open transaction).
        with self._conn:
            self._conn.executemany(
                "INSERT INTO knowledge_chunks(doc_uuid, chunk_index, text, embedding) "
                "VALUES(?, ?, ?, ?)",
                chunk_rows,
            )
            self._conn.execute(
                "UPDATE knowledge_docs SET approval_state='approved', decided_at=? "
                "WHERE doc_uuid=?",
                (now, doc_uuid),
            )
            # Promote this doc's display-only images pending -> approved in the
            # SAME transaction (UC-003 Workstream B #3).  Plaintext label flip
            # only (no re-encrypt; the AAD is untouched).  No-op when the doc
            # has no images (the dormant default).  Idempotent: the
            # already-approved short-circuit above returns BEFORE this block, so
            # a second approve never re-runs it.
            self._conn.execute(
                "UPDATE knowledge_images SET approval_state='approved' "
                "WHERE doc_uuid=? AND approval_state='pending'",
                (doc_uuid,),
            )

        # Incremental in-RAM index extension (vector cache + FTS5).
        with self._lock:
            self._doc_titles[doc_uuid] = title
            self._doc_source_types[doc_uuid] = source_type
            for i, chunk in enumerate(chunks):
                self._chunk_vecs[(doc_uuid, i)] = embeddings[i].copy()
                self._chunk_texts[(doc_uuid, i)] = chunk
                self._fts.execute(
                    "INSERT INTO knowledge_fts(text, doc_uuid, chunk_index) "
                    "VALUES(?, ?, ?)",
                    (chunk, doc_uuid, i),
                )
            self._fts.commit()

        logger.info(
            "Knowledge approve: doc %s approved (%d chunks indexed)",
            doc_uuid,
            len(chunks),
        )
        return len(chunks)

    def reject(self, doc_uuid: str) -> None:
        """Reject a pending document: flip the state; TEXT content is RETAINED.

        The rejected row is a tombstone — text content retention/scrubbing is a
        later lifecycle decision, deliberately not taken in Stage A.  Display-only
        IMAGE rows for the doc, however, are DELETEd here (purged at rest) —
        data-minimization on rejected untrusted web bytes (UC-003 Workstream B,
        LA decision 2026-06-15); only the doc text tombstone + the INGEST_REJECT
        audit record remain.  Idempotent for an already-rejected document.
        Rejecting an APPROVED document raises — un-approving is a forget-this
        lifecycle action, not an ingest decision.
        """
        state = self.check_decision(doc_uuid, "reject")
        if state == "rejected":
            return
        now = datetime.now(timezone.utc).isoformat()
        # Explicit transaction (commit / rollback-on-exception) — uniform
        # mutating-method discipline (#655 review fix).
        with self._conn:
            self._conn.execute(
                "UPDATE knowledge_docs SET approval_state='rejected', decided_at=? "
                "WHERE doc_uuid=?",
                (now, doc_uuid),
            )
            # DELETE this doc's display-only image rows in the SAME transaction
            # (UC-003 Workstream B #3; LA decision 2026-06-15 — DELETE-on-reject).
            # Data-minimization under the privacy-absolute mandate: the encrypted
            # image bytes are PURGED at rest on reject; only the doc TEXT
            # tombstone (retained) + the INGEST_REJECT audit record remain.  This
            # DELIBERATELY DIVERGES from the doc-content tombstone — images are
            # content-bearing UNTRUSTED web bytes the operator explicitly
            # rejected, so they are not kept.  No-op when the doc has no images.
            self._conn.execute(
                "DELETE FROM knowledge_images WHERE doc_uuid=?",
                (doc_uuid,),
            )
        logger.info("Knowledge reject: doc %s rejected (content retained)", doc_uuid)

    # ── Display-only images (UC-003 Workstream B — DORMANT) ──────────────

    def _enc_image_field(
        self, column: str, doc_uuid: str, image_id: str, value: bytes
    ) -> bytes:
        """Encrypt a content-bearing image column, AAD-bound to its row.

        Mirrors :meth:`_enc_doc_field` but for ``knowledge_images``: the AAD is
        ``knowledge_images|<column>|<doc_uuid>|<image_id>`` so a ciphertext
        relocated to a different column, a different image, OR re-associated to a
        different document fails authentication (ADR-025 §2.4).
        """
        from shared.security.field_cipher import make_aad_for

        return self._cipher.encrypt(
            value,
            aad=make_aad_for(
                "knowledge_images", column, _image_aad_id(doc_uuid, image_id)
            ),
        )

    def _dec_image_field(
        self, column: str, doc_uuid: str, image_id: str, blob: bytes
    ) -> bytes:
        """Decrypt a content-bearing image column (hard fail-closed)."""
        from shared.security.field_cipher import make_aad_for

        return self._cipher.decrypt(
            bytes(blob),
            aad=make_aad_for(
                "knowledge_images", column, _image_aad_id(doc_uuid, image_id)
            ),
        )

    def image_hash_for(self, image_bytes: bytes) -> bytes:
        """Deterministic keyed dedup index for raw image bytes.

        Same construction as :meth:`source_hash_for` (HMAC under ``k_idx``):
        identical bytes hash identically (the ADR-025 §3 equality-leak residual
        is accepted, as elsewhere), letting dedup work over ciphertext without
        revealing the plaintext bytes.
        """
        return self._cipher.keyed_index(image_bytes)

    def _migrate_surviving_images(
        self,
        prior_uuid: str,
        new_doc_uuid: str,
        surviving_ids: frozenset[str],
    ) -> list[tuple[Any, ...]]:
        """Re-key surviving image rows from *prior_uuid* to *new_doc_uuid* (#2).

        On an edited re-submit the dedup-replace DELETE reaps the prior doc's
        images via ON DELETE CASCADE — including images whose
        ``blarai-img://<id>`` ref the operator KEPT.  This reads each surviving
        image, DECRYPTS it under the prior doc's AAD, and RE-ENCRYPTS it under
        the new doc's AAD (a bare ``UPDATE ... SET doc_uuid`` would fail
        authentication — :func:`_image_aad_id` binds the doc_uuid, so the
        ciphertext must be re-bound, not relabeled).  ALL crypto runs HERE,
        before any DML, so the returned rows can be re-INSERTed inside the
        caller's atomic transaction AFTER the new doc row exists.

        Fail-safe per row (mirrors :meth:`get_images_for_doc`): a row that fails
        to decrypt is SKIPPED + logged ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``,
        never re-encrypted as garbage.  ``image_hash`` (keyed over the raw
        bytes) and the plaintext ``mime`` / ``approval_state`` / ``created_at``
        are carried forward verbatim.  Returns the buffered re-INSERT tuples
        (empty when nothing survives — the dormant default).
        """
        if not surviving_ids or not prior_uuid:
            return []
        from shared.security.field_cipher import FieldCipherError

        placeholders = ",".join("?" for _ in surviving_ids)
        rows = self._conn.execute(
            "SELECT image_id, image_hash, mime, alt, source_url, data, "
            "approval_state, created_at FROM knowledge_images "
            "WHERE doc_uuid=? AND image_id IN (" + placeholders + ")",
            (prior_uuid, *sorted(surviving_ids)),
        ).fetchall()
        migrated: list[tuple[Any, ...]] = []
        for row in rows:
            image_id = str(row[0])
            try:
                alt = self._dec_image_field("alt", prior_uuid, image_id, row[3])
                source_url = self._dec_image_field(
                    "source_url", prior_uuid, image_id, row[4]
                )
                data = self._dec_image_field("data", prior_uuid, image_id, row[5])
                # Re-bind every content-bearing column to the NEW doc_uuid.
                enc_alt = self._enc_image_field("alt", new_doc_uuid, image_id, alt)
                enc_source_url = self._enc_image_field(
                    "source_url", new_doc_uuid, image_id, source_url
                )
                enc_data = self._enc_image_field(
                    "data", new_doc_uuid, image_id, data
                )
            except FieldCipherError as exc:
                logger.warning(
                    "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                    "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE image_id=%r "
                    "doc_uuid=%r reason=%r -- surviving image NOT migrated",
                    image_id,
                    prior_uuid,
                    str(exc),
                )
                continue
            migrated.append(
                (
                    image_id,
                    new_doc_uuid,
                    bytes(row[1]),       # image_hash carried forward (same bytes)
                    str(row[2]),         # mime (plaintext)
                    enc_alt,
                    enc_source_url,
                    enc_data,
                    # approval_state is RESET to 'pending' (not carried forward):
                    # the new doc is always pending at submit_pending time, so a
                    # migrated image starts a fresh decision cycle with it and is
                    # promotable by approve().  (With DELETE-on-reject the only
                    # prior state that can reach migration is 'pending' anyway —
                    # approved sources early-return, rejected images are purged —
                    # so this keeps the correct invariant robust, not a live
                    # divergence; adversarial review 2026-06-15.)
                    "pending",
                    str(row[7]),         # created_at preserved
                )
            )
        return migrated

    def store_image(
        self,
        image_id: str,
        doc_uuid: str,
        image_bytes: bytes,
        mime: str,
        alt: str,
        source_url: str,
        *,
        approval_state: str,
    ) -> None:
        """Persist one display-only image for *doc_uuid* (encrypted at rest).

        DORMANT in this build: nothing populates this live until the LA
        go-live ceremony (see the module docstring).  When wired, the host
        ingest-submit handler calls this for each staged image.

        Storage rules (fail-closed, mirroring the document-write discipline):
          * ``doc_uuid`` MUST already exist — an image with no parent document
            is refused (no orphan rows; the FK + CASCADE only protects against
            *later* doc deletion, not against an orphaned INSERT).
          * Every content-bearing column (``alt``, ``source_url``, ``data``) is
            AES-GCM encrypted under :class:`FieldCipher`, AAD-bound to
            ``knowledge_images|<column>|<image_id>``.  ``mime`` is a small
            structural label kept plaintext (no privacy value; needed to pick
            the decoder at render time without a decrypt).
          * ``image_hash`` is the keyed-hash column + index over the raw bytes.
            The only ACTIVE dedup today is the ``image_id`` UNIQUE constraint
            (a re-store for the SAME image_id is a no-op UPSERT-style refresh; a
            duplicate ``image_id`` is a caller bug it refuses).  The hash index is
            BUILT for a future cross-image dedup consumer (collapse byte-identical
            images across docs) but **nothing queries it yet** — written, not yet
            consumed (SL-2, #663 c.1106; a named go-live successor).
          * All encryption runs BEFORE the single INSERT, inside one explicit
            transaction (commit on success / rollback on any exception) — same
            no-stranded-DML discipline as :meth:`submit_pending`.

        Image bytes are stored ONLY for display; they are never chunked,
        embedded, indexed, or sent to any model (the no-VLM lock).
        """
        if not image_id.strip():
            raise KnowledgeBankError("store_image: image_id must be non-empty")
        if not doc_uuid.strip():
            raise KnowledgeBankError("store_image: doc_uuid must be non-empty")
        if not mime.strip():
            raise KnowledgeBankError("store_image: mime must be non-empty")
        if not image_bytes:
            raise KnowledgeBankError("store_image: image_bytes must be non-empty")

        # Store-time content RE-VALIDATION (#6 / defense-in-depth): re-sniff the
        # bytes against the claimed MIME at the at-rest boundary.  The egress
        # door validated them at FETCH time, but they arrive here off an on-disk
        # staging blob + a host-supplied frame label, so the label is NOT
        # trusted — we re-run the door's single validator (no forked magic
        # table).  A header/body mismatch, SVG, or non-allowlisted type is
        # REFUSED (Fail-Closed); the STORED mime is the SNIFFED one, never the
        # raw label.  The caller (_store_ingest_images) drops a single refused
        # image without failing the document.
        from shared.security.guarded_fetch import (
            dimension_above_max,
            validate_image_content,
        )

        ok, validated_mime, reason = validate_image_content(mime, image_bytes)
        if not ok:
            raise KnowledgeBankError(
                f"store_image: image failed content re-validation ({reason}) — "
                "refusing to store a mislabeled image (Fail-Closed)"
            )
        mime = validated_mime

        # Decompression-bomb CEILING re-check at the at-rest boundary (W1 / BED-3,
        # defense-in-depth).  The coordinator already drops an over-ceiling image
        # at fetch time, but these bytes arrive off an on-disk staging blob, so we
        # re-apply the SAME header-only check (no decode) the door exposes.  An
        # image whose header declares dimensions over the max edge/area is REFUSED
        # (Fail-Closed); the caller drops the single image without failing the doc.
        if dimension_above_max(validated_mime, image_bytes):
            raise KnowledgeBankError(
                "store_image: image dimensions exceed the decompression-bomb "
                "ceiling (max edge/area) — refusing to store (Fail-Closed)"
            )

        # No-orphan check BEFORE any DML: the parent document must exist.
        parent = self._conn.execute(
            "SELECT 1 FROM knowledge_docs WHERE doc_uuid=?", (doc_uuid,)
        ).fetchone()
        if parent is None:
            raise KnowledgeBankError(
                f"store_image: unknown doc_uuid {doc_uuid!r} — refusing to "
                "store an orphan image (Fail-Closed)"
            )

        image_hash = self.image_hash_for(image_bytes)
        # Encrypt every content-bearing column BEFORE opening the transaction —
        # a cipher failure must surface with zero DML executed.
        enc_alt = self._enc_image_field("alt", doc_uuid, image_id, alt.encode("utf-8"))
        enc_source_url = self._enc_image_field(
            "source_url", doc_uuid, image_id, source_url.encode("utf-8")
        )
        enc_data = self._enc_image_field("data", doc_uuid, image_id, image_bytes)
        now = datetime.now(timezone.utc).isoformat()

        # INSERT OR REPLACE keyed on the UNIQUE image_id makes a re-store of the
        # same image_id (e.g. an ingest retry) idempotent rather than raising;
        # a genuinely new image_id inserts a fresh row.  Wrapped in an explicit
        # transaction (commit / rollback-on-exception).
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO knowledge_images("
                "image_id, doc_uuid, image_hash, mime, alt, source_url, data, "
                "approval_state, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    image_id,
                    doc_uuid,
                    image_hash,
                    mime,
                    enc_alt,
                    enc_source_url,
                    enc_data,
                    approval_state,
                    now,
                ),
            )
        logger.info(
            "Knowledge image stored: image %s for doc %s (mime=%s, %d bytes, "
            "state=%s) -- display-only, never embedded",
            image_id,
            doc_uuid,
            mime,
            len(image_bytes),
            approval_state,
        )

    def get_images_for_doc(self, doc_uuid: str) -> list[KnowledgeImage]:
        """Return all display-only images for *doc_uuid*, decrypted.

        Bulk read — decrypt-quarantine (ADR-025 §2.7): an image row whose
        encrypted columns cannot decrypt is SKIPPED, logged at WARNING with the
        stable event code ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``, and never
        returned as partial plaintext — the same posture as :meth:`list_pending`.
        Ordered by ``created_at`` then ``id`` for a stable render sequence.

        The returned bytes are for INLINE DISPLAY ONLY (the WinUI render
        surface) — they are never chunked, embedded, indexed, or sent to any
        model.
        """
        from shared.security.field_cipher import FieldCipherError

        rows = self._conn.execute(
            "SELECT image_id, doc_uuid, mime, alt, source_url, data, "
            "approval_state, created_at FROM knowledge_images "
            "WHERE doc_uuid=? ORDER BY created_at, id",
            (doc_uuid,),
        ).fetchall()
        images: list[KnowledgeImage] = []
        for row in rows:
            image_id = str(row[0])
            try:
                # Bind decrypt to the QUERIED doc_uuid (not row[1]): a tampered
                # plaintext doc_uuid that re-pointed this image to another doc
                # now fails authentication -> decrypt-quarantine, never returned.
                alt = self._dec_image_field(
                    "alt", doc_uuid, image_id, row[3]
                ).decode("utf-8")
                source_url = self._dec_image_field(
                    "source_url", doc_uuid, image_id, row[4]
                ).decode("utf-8")
                data = self._dec_image_field("data", doc_uuid, image_id, row[5])
            except FieldCipherError as exc:
                logger.warning(
                    "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                    "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE image_id=%r "
                    "doc_uuid=%r reason=%r -- image excluded from "
                    "get_images_for_doc",
                    image_id,
                    doc_uuid,
                    str(exc),
                )
                continue
            images.append(
                KnowledgeImage(
                    image_id=image_id,
                    doc_uuid=str(row[1]),
                    mime=str(row[2]),
                    alt=alt,
                    source_url=source_url,
                    data=data,
                    approval_state=str(row[6]),
                    created_at=str(row[7]),
                )
            )
        return images

    def get_knowledge_image(
        self, doc_uuid: str, image_id: str
    ) -> KnowledgeImage | None:
        """Return ONE decrypted display-only image by ``(doc_uuid, image_id)``, or None.

        The PER-DOCUMENT-grain sibling of :meth:`get_generated_image`: a
        single-record decrypt-quarantine read keyed by BOTH the owning document
        AND the image identity.  Built-ahead for the UC-010/UC-003 WS3 display
        corridor — it is the strictest set-membership check (an image stored
        under a DIFFERENT document, or a well-formed-but-unstored id, both
        resolve to None → the caller renders the inert alt placeholder).  NOT yet
        on the render path: the renderer resolves by ``image_id`` alone today (it
        does not carry the ``doc_uuid``), so this is the ceremony successor for
        per-document grain — see the UC-010 WS3 corridor report.

        Fail-Closed parity with :meth:`get_generated_image`:
          * Unknown ``(doc_uuid, image_id)`` pair → None (no row).
          * An ``image_id`` stored under a DIFFERENT ``doc_uuid`` → None (the
            WHERE clause excludes it — per-document membership).
          * A row that fails to decrypt — tampered / wrong-key / a plaintext
            ``doc_uuid`` re-pointed to another document (the decrypt is bound to
            the QUERIED ``doc_uuid``, not the stored column) → None, logged
            ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``, NEVER partial plaintext.

        The returned bytes are for INLINE DISPLAY ONLY — never chunked, embedded,
        indexed, or sent to any model (the no-VLM lock holds at the store).
        """
        from shared.security.field_cipher import FieldCipherError

        row = self._conn.execute(
            "SELECT image_id, doc_uuid, mime, alt, source_url, data, "
            "approval_state, created_at FROM knowledge_images "
            "WHERE doc_uuid=? AND image_id=?",
            (doc_uuid, image_id),
        ).fetchone()
        if row is None:
            return None
        try:
            # Bind decrypt to the QUERIED doc_uuid (not row[1]): a tampered
            # plaintext doc_uuid that re-pointed this image to another doc now
            # fails authentication -> decrypt-quarantine, never returned.
            alt = self._dec_image_field("alt", doc_uuid, image_id, row[3]).decode("utf-8")
            source_url = self._dec_image_field(
                "source_url", doc_uuid, image_id, row[4]
            ).decode("utf-8")
            data = self._dec_image_field("data", doc_uuid, image_id, row[5])
        except FieldCipherError as exc:
            logger.warning(
                "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE image_id=%r "
                "doc_uuid=%r reason=%r -- image excluded from get_knowledge_image",
                image_id, doc_uuid, str(exc),
            )
            return None
        return KnowledgeImage(
            image_id=str(row[0]),
            doc_uuid=str(row[1]),
            mime=str(row[2]),
            alt=alt,
            source_url=source_url,
            data=data,
            approval_state=str(row[6]),
            created_at=str(row[7]),
        )

    def image_count(self, doc_uuid: str | None = None) -> int:
        """Count stored display-only images, optionally for one ``doc_uuid``."""
        if doc_uuid is not None:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM knowledge_images WHERE doc_uuid=?",
                (doc_uuid,),
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM knowledge_images")
        return int(cur.fetchone()[0])

    # ══ UC-010 Local Generative Imaging (ADR-033 — DORMANT) ═══════════════
    # A locally-generated image belongs to a chat SESSION (no parent doc, no
    # approval lifecycle).  Born-encrypted under the SAME shared DEK; the prompt
    # + bytes are AAD-bound to ``generated_images|<column>|<session_id>|<image_id>``.
    # display-only — never chunked / embedded / indexed / fed to a model.
    # DISTINCT REGION from the knowledge_images (Pass A) store above.

    def _enc_generated_field(
        self, column: str, session_id: str, image_id: str, value: bytes
    ) -> bytes:
        """Encrypt a content-bearing generated-image column, AAD-bound to its row.

        Mirrors :meth:`_enc_image_field`: AAD is
        ``generated_images|<column>|<session_id>|<image_id>`` so a ciphertext
        relocated to a different column, image, or session fails authentication.
        """
        from shared.security.field_cipher import make_aad_for

        return self._cipher.encrypt(
            value,
            aad=make_aad_for(
                "generated_images", column,
                _generated_image_aad_id(session_id, image_id),
            ),
        )

    def _dec_generated_field(
        self, column: str, session_id: str, image_id: str, blob: bytes
    ) -> bytes:
        """Decrypt a content-bearing generated-image column (hard fail-closed)."""
        from shared.security.field_cipher import make_aad_for

        return self._cipher.decrypt(
            bytes(blob),
            aad=make_aad_for(
                "generated_images", column,
                _generated_image_aad_id(session_id, image_id),
            ),
        )

    def store_generated_image(
        self,
        image_id: str,
        session_id: str,
        image_bytes: bytes,
        mime: str,
        prompt: str,
    ) -> None:
        """Persist one locally-generated image for *session_id* (encrypted at rest).

        UC-010 (ADR-033).  Born on-box from an OPERATOR prompt; display-only.
        Storage rules (fail-closed, mirroring :meth:`store_image`):

          * Every content-bearing column (``prompt``, ``data``) is AES-256-GCM
            encrypted under the SAME shared DEK (ADR-025 §2.1 one-DEK rule),
            AAD-bound to ``generated_images|<column>|<session_id>|<image_id>``.
            ``mime`` is a small structural label kept plaintext (needed to pick
            the decoder at render time without a decrypt).
          * ``image_hash`` is the keyed-hash dedup index over the raw bytes
            (HMAC under ``k_idx`` — same construction as :meth:`image_hash_for`).
            Built for a future cross-image dedup consumer; not queried yet.
          * NO parent-document check (a generated image has no parent doc — it
            belongs to a session).  ``session_id`` is a free-form label; an
            empty one is refused (a row must be reapable by session).
          * All encryption runs BEFORE the single ``INSERT OR REPLACE`` inside
            one explicit transaction — same no-stranded-DML discipline.

        The bytes are stored ONLY for display; they are NEVER chunked, embedded,
        indexed, or sent to any model (the no-VLM lock — _guard_embed_input).
        """
        if not image_id.strip():
            raise KnowledgeBankError("store_generated_image: image_id must be non-empty")
        if not session_id.strip():
            raise KnowledgeBankError(
                "store_generated_image: session_id must be non-empty"
            )
        if not mime.strip():
            raise KnowledgeBankError("store_generated_image: mime must be non-empty")
        if not image_bytes:
            raise KnowledgeBankError(
                "store_generated_image: image_bytes must be non-empty"
            )

        image_hash = self.image_hash_for(image_bytes)
        # Encrypt every content-bearing column BEFORE opening the transaction —
        # a cipher failure must surface with zero DML executed.
        enc_prompt = self._enc_generated_field(
            "prompt", session_id, image_id, prompt.encode("utf-8")
        )
        enc_data = self._enc_generated_field(
            "data", session_id, image_id, image_bytes
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO generated_images("
                "image_id, session_id, image_hash, mime, prompt, data, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (image_id, session_id, image_hash, mime, enc_prompt, enc_data, now),
            )
        logger.info(
            "Generated image stored: image %s for session %s (mime=%s, %d bytes) "
            "-- display-only, never embedded (UC-010)",
            image_id, session_id, mime, len(image_bytes),
        )

    def get_generated_image(self, image_id: str) -> GeneratedImage | None:
        """Return one decrypted generated image by ``image_id``, or None.

        The host display resolver calls this to decrypt a ``blarai-img://<id>``
        ref to bitmap bytes.  Single-record read — returns None when the id is
        unknown OR the row fails to decrypt (tampered / wrong-key /
        wrong-identity: logged ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``, never
        returned as partial plaintext).  Bytes are for INLINE DISPLAY ONLY.
        """
        from shared.security.field_cipher import FieldCipherError

        row = self._conn.execute(
            "SELECT image_id, session_id, mime, prompt, data, created_at "
            "FROM generated_images WHERE image_id=?",
            (image_id,),
        ).fetchone()
        if row is None:
            return None
        session_id = str(row[1])
        try:
            prompt = self._dec_generated_field(
                "prompt", session_id, image_id, row[3]
            ).decode("utf-8")
            data = self._dec_generated_field("data", session_id, image_id, row[4])
        except FieldCipherError as exc:
            logger.warning(
                "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE image_id=%r "
                "session_id=%r reason=%r -- generated image excluded from "
                "get_generated_image",
                image_id, session_id, str(exc),
            )
            return None
        return GeneratedImage(
            image_id=str(row[0]),
            session_id=session_id,
            mime=str(row[2]),
            prompt=prompt,
            data=data,
            created_at=str(row[5]),
        )

    def delete_generated_image(self, image_id: str) -> bool:
        """Delete one generated image by ``image_id``; True if a row was removed.

        DELETE-on-discard (ADR-032 parity): a discarded generated image is reaped
        outright — there is no tombstone (an un-kept generation is not a curation
        decision worth retaining).  Idempotent: deleting an absent id returns
        False without error.
        """
        if not image_id.strip():
            return False
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM generated_images WHERE image_id=?", (image_id,)
            )
        removed = cur.rowcount > 0
        if removed:
            logger.info("Generated image deleted: %s (UC-010 DELETE-on-discard)", image_id)
        return removed

    def generated_image_count(self, session_id: str | None = None) -> int:
        """Count stored generated images, optionally for one ``session_id``."""
        if session_id is not None:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM generated_images WHERE session_id=?",
                (session_id,),
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM generated_images")
        return int(cur.fetchone()[0])

    def list_generated_images(
        self, session_id: str | None = None
    ) -> list[GeneratedImageMeta]:
        """List generated-image METADATA — newest first (UC-010 Phase 1, #667).

        Returns one :class:`GeneratedImageMeta` per stored image carrying ONLY
        the cheap, non-content columns: ``image_id``, ``session_id``, ``mime``,
        ``byte_size`` (a ``length(data)`` SQL aggregate — the on-disk ciphertext
        length, NOT a decrypt), ``saved`` (the operator's forward-looking
        exported-once flag), and ``created_at``.

        SECURITY (Fail-Closed, metadata-only): this method reads NEITHER
        encrypted column (``prompt``/``data``) — no :class:`FieldCipher` decrypt
        happens to build a listing, so a listing can NEVER surface plaintext
        prompts or image bytes (those cross ONLY via the resolve corridor for
        display or ``/save`` for export).  There is consequently NO
        decrypt-quarantine path here: nothing is decrypted, so nothing can fail
        to decrypt.  A row with an undecryptable blob still appears in the
        listing (its metadata is intact and useful — the operator can still
        DELETE it); it simply cannot be displayed, which the resolve corridor
        already handles by returning a placeholder.

        Args:
            session_id: When given, list only that session's images; otherwise
                list across all sessions (the default ``/images`` view).
        """
        if session_id is not None:
            rows = self._conn.execute(
                "SELECT image_id, session_id, mime, length(data), saved, created_at "
                "FROM generated_images WHERE session_id=? "
                "ORDER BY created_at DESC, id DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT image_id, session_id, mime, length(data), saved, created_at "
                "FROM generated_images ORDER BY created_at DESC, id DESC",
            ).fetchall()
        return [
            GeneratedImageMeta(
                image_id=str(r[0]),
                session_id=str(r[1]),
                mime=str(r[2]),
                byte_size=int(r[3] or 0),
                saved=bool(r[4]),
                created_at=str(r[5]),
            )
            for r in rows
        ]

    def mark_generated_image_saved(self, image_id: str) -> bool:
        """Mark a generated image as exported-to-disk; True if a row was updated.

        UC-010 Phase 1 (#667).  Sets the forward-looking ``saved`` flag after the
        operator successfully exports the image via ``/save`` (the gateway calls
        this fail-soft AFTER the PNG is on disk — a mark failure must never undo a
        completed save).  Idempotent: marking an already-saved image is a no-op
        success (the row exists), and marking an absent id returns False without
        error.  Touches ONLY the plaintext ``saved`` flag — no decrypt, no
        re-encrypt, the AAD-bound blobs are untouched.
        """
        if not image_id.strip():
            return False
        with self._conn:
            cur = self._conn.execute(
                "UPDATE generated_images SET saved=1 WHERE image_id=?", (image_id,)
            )
        updated = cur.rowcount > 0
        if updated:
            logger.info(
                "Generated image marked saved: %s (UC-010 Phase 1 #667)", image_id
            )
        return updated

    # ── Read (single record: hard fail-closed; bulk: quarantine) ────────

    # ── Operator preferences (Learning Loops Loop 1, #770 M1) ───────────

    def _enc_pref_field(self, column: str, pref_id: str, value: str) -> bytes:
        """Encrypt a content-bearing preference column, AAD-bound to its row."""
        from shared.security.field_cipher import make_aad_for

        return self._cipher.encrypt(
            value.encode("utf-8"),
            aad=make_aad_for("operator_preferences", column, _pref_aad_id(pref_id)),
        )

    def _dec_pref_field(self, column: str, pref_id: str, blob: bytes) -> str:
        """Decrypt a content-bearing preference column (hard fail-closed)."""
        from shared.security.field_cipher import make_aad_for

        return self._cipher.decrypt(
            bytes(blob),
            aad=make_aad_for("operator_preferences", column, _pref_aad_id(pref_id)),
        ).decode("utf-8")

    @staticmethod
    def _coerce_pref_type_tag(type_tag: str) -> str:
        """Coerce an unrecognized type tag to the default (cosmetic, never lossy)."""
        tag = type_tag.strip()
        return tag if tag in PREFERENCE_TYPE_TAGS else DEFAULT_PREFERENCE_TYPE_TAG

    def store_preference(
        self,
        body: str,
        type_tag: str = DEFAULT_PREFERENCE_TYPE_TAG,
        subject: str = "",
        source: str = "operator-explicit",
        expires: str = "",
    ) -> OperatorPreference:
        """Persist one operator preference VERBATIM (P2), born-encrypted.

        Validation (Fail-Closed — raises :class:`KnowledgeBankError` with a
        stable ``PREFERENCE_*`` code prefix):

          * ``PREFERENCE_EMPTY`` — an empty/whitespace-only body.
          * ``PREFERENCE_BODY_TOO_LONG`` — body over
            ``shared.preference_budgets.PREFERENCE_BODY_MAX_CHARS`` (P4).
          * ``PREFERENCE_COUNT_CAP`` — the active tier is at
            ``PREFERENCE_MAX_COUNT`` (P4).

        The body is stored byte-verbatim — this method never trims, rewrites,
        or paraphrases it (P2: small models cannot recover from summarization
        loss; the store must not either).  ``type_tag``/``subject`` are the
        thin cosmetic envelope; an unrecognized tag coerces to the default.

        NOTE (P4 — the third cap): the pinned-block TOKEN cap is enforced at
        the single operator write door (the AO PREFERENCE_WRITE handler checks
        the candidate render BEFORE calling this method) and backstopped by
        deterministic truncation in the renderer; it is deliberately NOT
        re-checked here to keep the renderer dependency out of the store.
        """
        if not body or not body.strip():
            raise KnowledgeBankError(
                "PREFERENCE_EMPTY: preference body must be non-empty"
            )
        from shared.preference_budgets import (
            PREFERENCE_BODY_MAX_CHARS,
            PREFERENCE_MAX_COUNT,
        )

        if len(body) > PREFERENCE_BODY_MAX_CHARS:
            raise KnowledgeBankError(
                f"PREFERENCE_BODY_TOO_LONG: {len(body)} chars exceeds the "
                f"{PREFERENCE_BODY_MAX_CHARS}-char cap (P4)"
            )
        if self.count_preferences() >= PREFERENCE_MAX_COUNT:
            raise KnowledgeBankError(
                f"PREFERENCE_COUNT_CAP: the active tier is at the "
                f"{PREFERENCE_MAX_COUNT}-preference cap (P4); delete or edit "
                f"an existing preference first"
            )

        pref_id = uuid.uuid4().hex
        resolved_tag = self._coerce_pref_type_tag(type_tag)
        # Encrypt BEFORE opening the transaction — a cipher failure must
        # surface with zero DML executed (the store-wide discipline).
        enc_subject = self._enc_pref_field("subject", pref_id, subject)
        enc_body = self._enc_pref_field("body", pref_id, body)
        expiry = expires.strip() or None  # '' -> NULL (no expiry)
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO operator_preferences("
                "pref_id, status, type_tag, supersedes, subject, body, "
                "source, created, updated, expires) "
                "VALUES(?, 'active', ?, NULL, ?, ?, ?, ?, ?, ?)",
                (pref_id, resolved_tag, enc_subject, enc_body, source, now, now,
                 expiry),
            )
        logger.info(
            "Operator preference stored: %s (tag=%s, %d chars, expires=%s) -- "
            "verbatim, born-encrypted (#770 M1/M2)",
            pref_id, resolved_tag, len(body), expiry or "never",
        )
        return OperatorPreference(
            pref_id=pref_id,
            status="active",
            type_tag=resolved_tag,
            subject=subject,
            body=body,
            source=source,
            supersedes="",
            created=now,
            updated=now,
            expires=expiry or "",
        )

    def list_preferences(
        self, include_history: bool = False
    ) -> list[OperatorPreference]:
        """Return operator preferences in the DETERMINISTIC render order.

        Order is INSERTION order (the monotonic ``id`` rowid) — stable across
        calls and processes and immune to same-timestamp collisions (two
        preferences stored in the same clock tick must still append in the
        order the operator issued them — P9: the pinned block renders
        byte-stable and a new preference appends at the END; ``created``
        timestamps are audit metadata, not the sort key).  An in-place edit
        keeps its rowid, so its line position is stable too.  Default returns
        ACTIVE rows only (the render feed); ``include_history=True`` adds
        superseded/deleted audit rows (the P5 audit trail), same ordering.

        Bulk read — decrypt-quarantine (ADR-025 §2.7): a row whose fields
        cannot decrypt is skipped and logged, never returned as plaintext.
        """
        from shared.security.field_cipher import FieldCipherError

        where = "" if include_history else "WHERE status='active'"
        rows = self._conn.execute(
            "SELECT pref_id, status, type_tag, supersedes, subject, body, "
            f"source, created, updated, expires FROM operator_preferences {where} "
            "ORDER BY id ASC"
        ).fetchall()
        out: list[OperatorPreference] = []
        for row in rows:
            pref_id = str(row[0])
            try:
                subject = (
                    self._dec_pref_field("subject", pref_id, row[4])
                    if row[4] is not None
                    else ""
                )
                body = self._dec_pref_field("body", pref_id, row[5])
            except FieldCipherError:
                logger.warning(
                    "PREFERENCE_ROW_DECRYPT_QUARANTINE pref_id=%s -- row "
                    "skipped (ADR-025 §2.7)",
                    pref_id,
                )
                continue
            out.append(
                OperatorPreference(
                    pref_id=pref_id,
                    status=str(row[1]),
                    type_tag=str(row[2]),
                    subject=subject,
                    body=body,
                    source=str(row[6]),
                    supersedes=str(row[3]) if row[3] is not None else "",
                    created=str(row[7]),
                    updated=str(row[8]),
                    expires=str(row[9]) if row[9] is not None else "",
                )
            )
        return out

    def count_preferences(self) -> int:
        """Count of ACTIVE preference rows (the P4 count-cap feed)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM operator_preferences WHERE status='active'"
        ).fetchone()
        return int(row[0]) if row else 0

    def get_preference(self, pref_id: str) -> OperatorPreference | None:
        """Return one ACTIVE preference by id, or None (unknown / not active)."""
        for pref in self.list_preferences():
            if pref.pref_id == pref_id:
                return pref
        return None

    def update_preference(
        self, pref_id: str, new_body: str
    ) -> OperatorPreference | None:
        """Last-writer-wins in-place edit with an audit trail (P5).

        The ACTIVE row keeps its ``pref_id`` and ``created`` (so the pinned
        block's deterministic order and line identity are stable — P9
        append-minimal edits: only the edited line's bytes change) and gets
        the new verbatim body; the PRIOR verbatim body is preserved as a new
        ``superseded`` audit row pointing back via ``supersedes``.  Audit rows
        are born-encrypted and excluded from rendering.

        Returns the updated preference, or ``None`` when *pref_id* is unknown
        or not active (Fail-Closed: editing history is not a thing).

        Raises:
            KnowledgeBankError: ``PREFERENCE_EMPTY`` / ``PREFERENCE_BODY_TOO_LONG``
                on an invalid new body (same P4 validation as a fresh store).
        """
        if not new_body or not new_body.strip():
            raise KnowledgeBankError(
                "PREFERENCE_EMPTY: preference body must be non-empty"
            )
        from shared.preference_budgets import PREFERENCE_BODY_MAX_CHARS

        if len(new_body) > PREFERENCE_BODY_MAX_CHARS:
            raise KnowledgeBankError(
                f"PREFERENCE_BODY_TOO_LONG: {len(new_body)} chars exceeds the "
                f"{PREFERENCE_BODY_MAX_CHARS}-char cap (P4)"
            )
        current = self.get_preference(pref_id)
        if current is None:
            return None

        audit_id = uuid.uuid4().hex
        # Re-encrypt the prior body under the AUDIT row's own identity (the
        # AAD binds ciphertext to its row — a moved blob fails authentication).
        enc_audit_subject = self._enc_pref_field("subject", audit_id, current.subject)
        enc_audit_body = self._enc_pref_field("body", audit_id, current.body)
        enc_new_body = self._enc_pref_field("body", pref_id, new_body)
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO operator_preferences("
                "pref_id, status, type_tag, supersedes, subject, body, "
                "source, created, updated) "
                "VALUES(?, 'superseded', ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_id, current.type_tag, pref_id,
                    enc_audit_subject, enc_audit_body,
                    current.source, current.created, now,
                ),
            )
            self._conn.execute(
                "UPDATE operator_preferences SET body=?, updated=? "
                "WHERE pref_id=? AND status='active'",
                (enc_new_body, now, pref_id),
            )
        logger.info(
            "Operator preference updated in place: %s (audit row %s retains "
            "the prior verbatim body -- P5 last-writer-wins)",
            pref_id, audit_id,
        )
        return OperatorPreference(
            pref_id=pref_id,
            status="active",
            type_tag=current.type_tag,
            subject=current.subject,
            body=new_body,
            source=current.source,
            supersedes="",
            created=current.created,
            updated=now,
            expires=current.expires,  # #770 M2 W2: an edit preserves the operator's stated bound
        )

    def delete_preference(self, pref_id: str) -> bool:
        """Soft-delete one ACTIVE preference (audit tombstone retained, P5).

        Flips ``status`` to ``deleted`` — the row leaves the pinned-block
        render feed and the count cap immediately, but its verbatim body
        stays as encrypted audit history.  Returns ``False`` when *pref_id*
        is unknown or not active (idempotent — deleting twice is a no-op).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE operator_preferences SET status='deleted', updated=? "
                "WHERE pref_id=? AND status='active'",
                (now, pref_id),
            )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Operator preference deleted (audit retained): %s", pref_id)
        return deleted

    def find_similar_preference(self, body: str) -> OperatorPreference | None:
        """Deterministic near-duplicate/contradiction probe (P5 confirm seam).

        Compares normalized token sets (Jaccard) of *body* against every
        ACTIVE preference; the highest-overlap row at or above
        ``PREFERENCE_SIMILARITY_THRESHOLD`` is returned (ties break to the
        deterministic list order).  Deliberately deterministic and offline —
        no embedding dependency — so the REQUIRES_CONFIRMATION path is
        reproducible in the standing gate.  M2's propose-and-confirm flow may
        refine the similarity signal; the CONFIRMATION requirement itself is
        the locked behaviour.
        """
        candidate_tokens = _pref_similarity_tokens(body)
        if not candidate_tokens:
            return None
        best: OperatorPreference | None = None
        best_score = 0.0
        for pref in self.list_preferences():
            existing_tokens = _pref_similarity_tokens(pref.body)
            if not existing_tokens:
                continue
            union = candidate_tokens | existing_tokens
            score = len(candidate_tokens & existing_tokens) / len(union)
            if score >= PREFERENCE_SIMILARITY_THRESHOLD and score > best_score:
                best = pref
                best_score = score
        return best

    def get_doc(self, doc_uuid: str) -> KnowledgeDoc:
        """Return one decrypted document record.

        Single-record read — HARD fail-closed: a decrypt failure raises
        (``FieldCipherError``), never returns partial plaintext.
        """
        row = self._conn.execute(
            "SELECT doc_uuid, source_type, source_ref, provenance, approval_state, "
            "title, byline, published_date, content, content_sha256_keyed, "
            "cleaner_version, word_count, created_at, decided_at "
            "FROM knowledge_docs WHERE doc_uuid=?",
            (doc_uuid,),
        ).fetchone()
        if row is None:
            raise KnowledgeBankError(f"get_doc: unknown doc_uuid {doc_uuid!r}")
        return self._decode_doc_row(row)

    def _decode_doc_row(self, row: tuple[Any, ...]) -> KnowledgeDoc:
        doc_uuid = str(row[0])
        return KnowledgeDoc(
            doc_uuid=doc_uuid,
            source_type=str(row[1]),
            source_ref=self._dec_doc_field("source_ref", doc_uuid, row[2]),
            provenance=str(row[3]),
            approval_state=str(row[4]),
            title=self._dec_doc_field("title", doc_uuid, row[5]),
            byline=self._dec_doc_field("byline", doc_uuid, row[6]),
            published_date=str(row[7]),
            content=self._dec_doc_field("content", doc_uuid, row[8]),
            content_sha256_keyed=bytes(row[9]).hex(),
            cleaner_version=str(row[10]),
            word_count=int(row[11]),
            created_at=str(row[12]),
            decided_at=(str(row[13]) if row[13] is not None else None),
        )

    def list_pending(self) -> list[KnowledgeDoc]:
        """Return all pending documents (bulk read — decrypt-quarantine).

        A row whose fields cannot decrypt is skipped, logged at WARNING with
        the stable event code ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``, and never
        returned as plaintext (ADR-025 §2.7).
        """
        from shared.security.field_cipher import FieldCipherError

        rows = self._conn.execute(
            "SELECT doc_uuid, source_type, source_ref, provenance, approval_state, "
            "title, byline, published_date, content, content_sha256_keyed, "
            "cleaner_version, word_count, created_at, decided_at "
            "FROM knowledge_docs WHERE approval_state='pending' ORDER BY created_at",
        ).fetchall()
        docs: list[KnowledgeDoc] = []
        for row in rows:
            try:
                docs.append(self._decode_doc_row(row))
            except FieldCipherError as exc:
                logger.warning(
                    "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                    "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE doc_uuid=%r reason=%r "
                    "-- pending doc excluded from list_pending",
                    str(row[0]),
                    str(exc),
                )
        return docs

    def count(self, state: str | None = None) -> int:
        """Count documents, optionally filtered by approval state."""
        if state is not None:
            if state not in _DECISION_STATES:
                raise KnowledgeBankError(f"count: invalid state {state!r}")
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM knowledge_docs WHERE approval_state=?",
                (state,),
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM knowledge_docs")
        return int(cur.fetchone()[0])

    def chunk_count(self) -> int:
        """Count stored (approved) chunks."""
        return int(
            self._conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        )

    # ── Hybrid retrieval (cosine + BM25 via reciprocal-rank fusion) ─────

    @property
    def embed_model_mismatch(self) -> EmbedModelMismatch | None:
        """The detected embedding-model identity mismatch, or ``None`` (#794).

        When non-``None`` the VECTOR limb is loud-disabled: :meth:`retrieve` skips
        the cosine limb and serves BM25/lexical results only (BM25 does not depend
        on the embedder).  A construction-time ``EMBED_MODEL_IDENTITY_MISMATCH``
        ERROR named the rebuild path.  Distinct from the embed-WINDOW mismatch,
        which hard-refuses retrieve/approve.
        """
        return self._embed_model_mismatch

    def _check_embed_window(self, operation: str) -> None:
        """Refuse embedding-dependent operations on a window-mismatched store.

        Raised LOUDLY (not silently empty) so a configured-vs-stored
        ``embed_max_tokens`` drift surfaces as an error the operator can act
        on instead of degraded retrieval quality nobody notices (ADR-031 §3).
        """
        if self._embed_window_mismatch is not None:
            stored, configured = self._embed_window_mismatch
            raise KnowledgeBankError(
                f"{operation}: knowledge store embed-window mismatch — stored "
                f"knowledge_meta.embed_max_tokens={stored} but the configured "
                f"embed_fn is bound at {configured} tokens.  Mixing windows "
                "would create the mixed-depth store ADR-031 §3 rejects.  Run "
                "the re-embed ceremony or restore [knowledge].embed_max_tokens "
                "(Fail-Closed)."
            )

    def retrieve(self, query: str, k: int | None = None) -> list[KnowledgeHit]:
        """Hybrid top-k retrieval over APPROVED chunks only.

        Vector limb: brute-force cosine over the in-RAM decrypted embedding
        cache.  Lexical limb: BM25 over the in-memory FTS5 index.  The two
        rankings are merged by reciprocal-rank fusion with the canonical
        constant ``k=60``: ``score(c) = sum(1 / (60 + rank_i(c)))``.

        Pending and rejected documents are never candidates — their chunks do
        not exist (pending/rejected rows hold content only).

        Raises:
            KnowledgeBankError: When the store's recorded embed window does
                not match the configured one (loud refusal, never a silently
                wrong-depth query — ADR-031 §3).

        Vector-limb identity guard (#794): when the store's recorded embedding
        MODEL identity does not match the configured one, the cosine limb is
        skipped entirely and only BM25/lexical results are returned (loud-disable,
        not a hard refusal — BM25 does not depend on the embedder).  The query is
        not embedded at all in that state.
        """
        self._check_embed_window("retrieve")
        if k is None:
            k = self._retrieve_k
        if k <= 0 or not query.strip():
            return []
        import numpy as np

        vector_disabled = self._embed_model_mismatch is not None
        q_vec = None
        if not vector_disabled:
            # Embed the query OUTSIDE the lock (model inference must not serialise
            # on the cache lock) — mirrors the substrate retrieve pattern.  The
            # no-VLM guard wraps the single-element query list too: retrieval is
            # text-only and never touches knowledge_images (display-only store).
            q = np.asarray(self._embed(_guard_embed_input([query])), dtype=np.float32)
            q_vec = q[0] if q.ndim == 2 else q

        with self._lock:
            # Vector limb — skipped when the embedding-model identity is
            # mismatched (#794); the lexical limb below still runs.
            vector_ranked: list[tuple[str, int]] = []
            if not vector_disabled and self._chunk_vecs:
                keys = list(self._chunk_vecs.keys())
                matrix = np.vstack([self._chunk_vecs[key] for key in keys])
                scores = matrix @ q_vec
                vector_ranked = [keys[int(i)] for i in np.argsort(scores)[::-1]]

            lexical_ranked: list[tuple[str, int]] = []
            match_expr = _fts_match_expr(query)
            if match_expr:
                rows = self._fts.execute(
                    "SELECT doc_uuid, chunk_index FROM knowledge_fts "
                    "WHERE knowledge_fts MATCH ? ORDER BY bm25(knowledge_fts)",
                    (match_expr,),
                ).fetchall()
                lexical_ranked = [(str(r[0]), int(r[1])) for r in rows]

            # Both limbs empty ⇒ nothing to return.  Covers a store with no
            # approved chunks AND a disabled vector limb whose lexical query
            # matched nothing (the loud-disable degradation, not an error).
            if not vector_ranked and not lexical_ranked:
                return []

            fused: dict[tuple[str, int], float] = {}
            for ranked in (vector_ranked, lexical_ranked):
                for rank, key in enumerate(ranked):
                    fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

            top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
            hits: list[KnowledgeHit] = []
            for (doc_uuid, chunk_index), score in top:
                text = self._chunk_texts.get((doc_uuid, chunk_index))
                if text is None:
                    continue  # quarantined at cache build — never scored from disk
                hits.append(
                    KnowledgeHit(
                        doc_uuid=doc_uuid,
                        chunk_index=chunk_index,
                        title=self._doc_titles.get(doc_uuid, ""),
                        source_type=self._doc_source_types.get(doc_uuid, ""),
                        text=text,
                        score=float(score),
                    )
                )
            return hits

    # ── In-RAM cache construction (DEK-unlock time) ──────────────────────

    def _load_approved_caches(self) -> None:
        """Decrypt approved chunks ONCE into the vector cache + FTS5 index.

        Bulk read — decrypt-quarantine (ADR-025 §2.7): an undecryptable chunk
        (or an undecryptable doc title) is skipped with the stable WARNING
        event code ``KNOWLEDGE_ROW_DECRYPT_QUARANTINE``; healthy rows still
        load.  Plaintext is never returned from a bad row.
        """
        import numpy as np
        from shared.security.field_cipher import FieldCipherError, make_aad_for

        doc_rows = self._conn.execute(
            "SELECT doc_uuid, title, source_type FROM knowledge_docs "
            "WHERE approval_state='approved'"
        ).fetchall()
        quarantined = 0
        for doc_uuid, enc_title, source_type in doc_rows:
            doc_uuid = str(doc_uuid)
            try:
                title = self._dec_doc_field("title", doc_uuid, enc_title)
            except FieldCipherError as exc:
                quarantined += 1
                logger.warning(
                    "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                    "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE doc_uuid=%r field=title "
                    "reason=%r -- title blanked in retrieval metadata",
                    doc_uuid,
                    str(exc),
                )
                title = ""
            self._doc_titles[doc_uuid] = title
            self._doc_source_types[doc_uuid] = str(source_type)

        chunk_rows = self._conn.execute(
            "SELECT c.doc_uuid, c.chunk_index, c.text, c.embedding "
            "FROM knowledge_chunks c "
            "JOIN knowledge_docs d ON d.doc_uuid = c.doc_uuid "
            "WHERE d.approval_state='approved'"
        ).fetchall()
        for doc_uuid, chunk_index, enc_text, enc_emb in chunk_rows:
            doc_uuid = str(doc_uuid)
            chunk_index = int(chunk_index)
            nat_id = _chunk_aad_id(doc_uuid, chunk_index)
            try:
                text = self._cipher.decrypt(
                    bytes(enc_text),
                    aad=make_aad_for("knowledge_chunks", "text", nat_id),
                ).decode("utf-8")
                emb = self._cipher.decrypt(
                    bytes(enc_emb),
                    aad=make_aad_for("knowledge_chunks", "embedding", nat_id),
                )
            except FieldCipherError as exc:
                quarantined += 1
                logger.warning(
                    "KNOWLEDGE_ROW_DECRYPT_QUARANTINE "
                    "event=KNOWLEDGE_ROW_DECRYPT_QUARANTINE doc_uuid=%r "
                    "chunk_index=%d reason=%r -- chunk excluded from retrieval",
                    doc_uuid,
                    chunk_index,
                    str(exc),
                )
                continue
            vec = np.frombuffer(emb, dtype=np.float32).copy()
            self._chunk_vecs[(doc_uuid, chunk_index)] = vec
            self._chunk_texts[(doc_uuid, chunk_index)] = text
            self._fts.execute(
                "INSERT INTO knowledge_fts(text, doc_uuid, chunk_index) "
                "VALUES(?, ?, ?)",
                (text, doc_uuid, chunk_index),
            )
        self._fts.commit()
        if quarantined:
            logger.warning(
                "KNOWLEDGE_ROW_DECRYPT_QUARANTINE summary: %d row(s) quarantined "
                "while building the knowledge retrieval caches -- check key "
                "rotation / dev->prod key transition",
                quarantined,
            )
