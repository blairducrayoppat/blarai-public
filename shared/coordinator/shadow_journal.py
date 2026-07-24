"""Born-encrypted, append-only coordinator shadow journal (#845 C3 limb 4, design §7.3).

The shadow seam's evidence store: while ``[coordinator].shadow_mode`` is true
(the default, flipped only at the #855 graduation ceremony), every
operator-visible and board-visible heartbeat effect — stall comments, board
moves, proposal payload copies, digests, tripwire alarms — is diverted HERE by
the :mod:`shared.coordinator.output_router` instead of reaching Vikunja or the
operator. #855's grading harness reads this journal to measure the
coordinator's precision before anything goes live.

Governed core (ADR-039 §2.1 item 10): the shadow journal lives under
``coordinator_store_root`` — ``GovernedCoreRoots`` already enumerates it for
exactly this store — appended to only via the sanctioned API here, never by
direct write. APPEND-ONLY by construction: this module exposes ``append`` and
reads; there is no mutation or removal path at all, so a journaled effect can
never be silently rewritten after the fact (the grading evidence is
tamper-evident at the API level, and the AAD binding below makes it
tamper-evident at the byte level).

Born-encrypted (ADR-039 §2.13 item 2 names the shadow journal explicitly): the
content-bearing ``payload`` (comment markdown, digest text, proposal copies) is
AES-256-GCM encrypted at rest under the SAME one-DEK envelope the
session/knowledge/proposal stores use (ADR-025 §2.1 — one DEK, N consumers),
via :mod:`shared.security.field_cipher` + :mod:`shared.security.dek_envelope`.
**No new crypto is introduced here** — this is the FOURTH consumer of the
existing sealed-store machinery. Each ciphertext is AAD-bound to its
(table, column, row-UUID) identity (ADR-025 §2.4), so a blob relocated to a
different row fails authentication.

Refuse-to-start (ADR-025 §2.8(a), mirrored from ``build_proposal_store``): the
production factory :func:`build_shadow_journal` REFUSES to construct
(:class:`~shared.coordinator.proposal_store.StoreProvisioningError`) when
``dev_mode=False`` and no ``BLARAI_DEK_KEYSTORE`` is provisioned — it never
silently falls back to the public ``SoftwareSealer`` key. Fail-closed, no
plaintext fallback, ever.

Deterministic timestamps: ``append`` REQUIRES the caller to inject ``now``
(tz-aware) — this store never reads the wall clock, matching the cycle
engine's clock-free discipline so #855's fixture-board grading is
reproducible to the microsecond.

REACHABILITY: importing this module arms nothing — it defines a store and
constructs none. A :class:`ShadowJournal` is built by the heartbeat cycle
(:func:`shared.coordinator.heartbeat.build_shadow_journal`) only when
``[coordinator].enabled`` AND ``[coordinator].heartbeat_enabled`` are both set;
with either false nothing constructs it. Read those flags from
``services/assistant_orchestrator/config/default.toml`` — never from here.
Provisioning is fail-closed: a journal that cannot be created REFUSES to start
the cycle rather than running unjournalled.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Mapping

from shared.coordinator.proposal_store import StoreProvisioningError

if TYPE_CHECKING:  # import only for typing — no runtime crypto import at module load
    from shared.security.field_cipher import FieldCipher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entry-kind vocabulary (design §7.2 — one kind per routed side-effect class).
# An allowlist, not a convention: append/list validate against it fail-closed,
# so a typo'd kind can neither pollute the journal nor silently read as empty.
# ---------------------------------------------------------------------------

#: A stall comment diverted from Vikunja (§7.2 row 1 shadow column).
KIND_STALL_COMMENT: Final[str] = "stall_comment"

#: A board move diverted from the kanban board (§7.2 row 2 shadow column).
KIND_BOARD_MOVE: Final[str] = "board_move"

#: The full-context copy of a redispatch proposal staged as DRAFT during shadow
#: (§7.2 row 3 shadow column — the real store keeps the DRAFT; the journal keeps
#: the gradable context).
KIND_PROPOSAL_COPY: Final[str] = "proposal_copy"

#: A cycle digest (§7.2 row 4 — journaled in shadow; ALSO the live default until
#: the post-graduation renderer exists, §7.4 "not built live in C3").
KIND_DIGEST: Final[str] = "digest"

#: A quiet-queue tripwire alarm (§7.2 row 5 shadow column — its false-alarm rate
#: is precisely what shadow measures).
KIND_TRIPWIRE_ALARM: Final[str] = "tripwire_alarm"

#: The sanctioned entry kinds. Machinery-health alarms are deliberately ABSENT:
#: §7.2's most load-bearing row routes them to the operator surface in BOTH
#: modes — a health alarm in an unread journal would re-create the vigilance
#: dependence §2.14.1 exists to kill.
JOURNAL_KINDS: Final[frozenset[str]] = frozenset(
    {
        KIND_STALL_COMMENT,
        KIND_BOARD_MOVE,
        KIND_PROPOSAL_COPY,
        KIND_DIGEST,
        KIND_TRIPWIRE_ALARM,
    }
)

#: The store's table name — ALSO the AAD ``table`` component (ADR-025 §2.4), so
#: every ciphertext is bound to this store's identity: relocating a payload blob
#: into any other table/store (including the proposal store) fails authentication.
_TABLE: Final[str] = "coordinator_shadow_journal"

#: The AAD ``column`` component for the encrypted payload.
_PAYLOAD_COLUMN: Final[str] = "payload"

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS coordinator_shadow_journal (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    id         TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL,
    payload    BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shadow_journal_kind
    ON coordinator_shadow_journal(kind);
CREATE INDEX IF NOT EXISTS idx_shadow_journal_created
    ON coordinator_shadow_journal(created_at);
"""


class ShadowJournalError(RuntimeError):
    """Raised for a shadow-journal integrity fault (unknown kind, payload
    authentication failure, malformed persisted record). Fail-closed: the
    journal never returns a partial or unauthenticated result, and never
    accepts an entry it could not later account for."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JournalEntry:
    """A decrypted journal entry returned by the reads.

    ``seq`` is the monotonic append order (the grading-stable sort key even when
    two entries share an injected timestamp); ``id`` is the row UUID the payload
    ciphertext is AAD-bound to; ``payload`` is the decrypted content dict the
    router journaled; ``created_at`` is the caller-injected instant, ISO-8601."""

    seq: int
    id: str
    kind: str
    payload: Mapping[str, Any]
    created_at: str


def _iso(dt: datetime) -> str:
    """A tz-aware datetime as an ISO-8601 UTC string (the on-disk metadata form).

    Pinned to fixed-width microsecond precision (``timespec="microseconds"``) so
    the ``WHERE created_at >= ?`` string comparison in
    :meth:`ShadowJournal.list_entries` is unambiguously chronological — every
    timestamp shares the same width and the ``+00:00`` offset, so lexicographic
    order == time order (mirrors the proposal store's ``_iso``)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class ShadowJournal:
    """SQLite-backed, born-encrypted, append-only shadow journal — the sanctioned API.

    Construct via :func:`build_shadow_journal` (the fail-closed production
    factory), never directly in production: the factory resolves the shared DEK
    envelope and enforces the refuse-to-start posture. The direct constructor
    takes an already-built :class:`~shared.security.field_cipher.FieldCipher`,
    matching :class:`~shared.coordinator.proposal_store.ProposalStore`.

    The ONLY mutation is :meth:`append` (ADR-039 §2.1 item 10 — sanctioned-API
    writes only); there is no update, transition, or removal method, and no raw
    write path is exposed. Reads (:meth:`list_entries`, :meth:`count`) return
    :class:`JournalEntry` value objects with the payload decrypted."""

    #: Production-wiring regression lock — a constructed journal is always
    #: encrypted (there is no plaintext variant). ``build_shadow_journal``
    #: asserts this True.
    has_encryption: bool = True

    def __init__(self, *, db_path: str, cipher: "FieldCipher") -> None:
        from shared.security.field_cipher import FieldCipher  # local — no cycle

        if not isinstance(cipher, FieldCipher):
            raise TypeError(
                "ShadowJournal requires a FieldCipher instance derived from the "
                f"unsealed DEK; got {type(cipher).__name__!r}."
            )

        self._db_path = db_path
        self._cipher = cipher

        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._harden_dacl(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # secure_delete=ON: the journal itself never deletes, but a future
        # operator-run retention ceremony (outside this API) inherits zeroed
        # pages, not merely freed ones — the born-encrypted posture extends to
        # deletion (mirrors the session/knowledge/proposal stores).
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("ShadowJournal initialized: %s", db_path)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _harden_dacl(db_path: str) -> None:
        """Apply the #637 owner-only DACL to the journal file (defense-in-depth on
        top of the at-rest encryption; the journal is governed core, ADR-039 §2.1
        item 10). No-op for ``:memory:`` and on non-Windows hosts; never raises."""
        if db_path == ":memory:":
            return
        from shared.security.file_dacl import ensure_owner_only_dacl

        ensure_owner_only_dacl(db_path)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Crypto helpers (the ONE-DEK envelope; AAD bound to this store's row)
    # ------------------------------------------------------------------

    def _payload_aad(self, entry_id: str) -> bytes:
        from shared.security.field_cipher import make_aad_for

        return make_aad_for(_TABLE, _PAYLOAD_COLUMN, entry_id)

    def _encrypt_payload(self, entry_id: str, payload: Mapping[str, Any]) -> bytes:
        """Serialize + encrypt a payload dict, bound to its row identity."""
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return self._cipher.encrypt(raw, aad=self._payload_aad(entry_id))

    def _decrypt_payload(self, entry_id: str, blob: Any) -> dict[str, Any]:
        """Decrypt + parse a payload blob. Fail-closed: an authentication failure
        or malformed JSON raises rather than returning unauthenticated/partial
        data."""
        from shared.security.field_cipher import FieldCipherError

        try:
            plaintext = self._cipher.decrypt(
                bytes(blob), aad=self._payload_aad(entry_id)
            )
        except FieldCipherError as exc:
            raise ShadowJournalError(
                f"journal entry {entry_id}: payload authentication failed "
                "(tampered, wrong key, or relocated row)"
            ) from exc
        try:
            parsed = json.loads(plaintext)
        except (ValueError, TypeError) as exc:
            raise ShadowJournalError(
                f"journal entry {entry_id}: payload is not valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise ShadowJournalError(
                f"journal entry {entry_id}: payload did not decode to an object"
            )
        return parsed

    def _row_to_entry(self, row: tuple) -> JournalEntry:
        seq, entry_id, kind, payload_blob, created_at = row
        return JournalEntry(
            seq=seq,
            id=entry_id,
            kind=kind,
            payload=self._decrypt_payload(entry_id, payload_blob),
            created_at=created_at,
        )

    @staticmethod
    def _require_known_kind(kind: str) -> None:
        """The kind allowlist gate (deny-by-default): an unknown kind raises on
        BOTH write and read — a typo can neither pollute the journal nor read as
        a silently-empty result (#855's grading must never mistake a misspelled
        query for a clean shadow run)."""
        if kind not in JOURNAL_KINDS:
            known = ", ".join(sorted(JOURNAL_KINDS))
            raise ShadowJournalError(
                f"unknown journal entry kind {kind!r} (sanctioned kinds: {known})"
            )

    # ------------------------------------------------------------------
    # The sanctioned write (the SOLE append path — §2.1 item 10; append-only)
    # ------------------------------------------------------------------

    def append(
        self, kind: str, payload: Mapping[str, Any], *, now: datetime
    ) -> JournalEntry:
        """Append one journal entry — the store's ONLY mutation.

        *kind* must be a sanctioned :data:`JOURNAL_KINDS` member (fail-closed).
        *now* is REQUIRED and must be tz-aware — the caller (the output router's
        injected ``now_fn``, or a test) owns the clock; this store never reads
        it, so shadow evidence is deterministic. The payload is encrypted,
        AAD-bound to the freshly-minted row UUID; the write is one atomic
        single-row SQLite commit (WAL), so a crash never leaves a torn entry."""
        self._require_known_kind(kind)
        if now.tzinfo is None:
            raise ValueError(
                "ShadowJournal.append: 'now' must be timezone-aware (UTC) — "
                "timestamps are injected by the caller, never read from a naive "
                "local clock"
            )
        entry_id = str(uuid.uuid4())
        created = _iso(now)
        payload_blob = self._encrypt_payload(entry_id, payload)
        self._conn.execute(
            "INSERT INTO coordinator_shadow_journal (id, kind, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (entry_id, kind, payload_blob, created),
        )
        self._conn.commit()
        row = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_shadow_journal "
            "WHERE id = ?",
            (entry_id,),
        ).fetchone()
        assert row is not None  # just inserted
        return self._row_to_entry(row)

    # ------------------------------------------------------------------
    # Reads (for #855's grading harness + the C3 locks)
    # ------------------------------------------------------------------

    _SELECT_COLS: Final[str] = "seq, id, kind, payload, created_at"

    def list_entries(
        self,
        *,
        kind: str | None = None,
        since: datetime | str | None = None,
    ) -> list[JournalEntry]:
        """Every entry (payloads decrypted), append order, oldest first.

        *kind* filters to one sanctioned kind (an unknown kind RAISES — see
        :meth:`_require_known_kind`). *since* keeps entries with
        ``created_at >= since`` — a tz-aware datetime, or an already-formatted
        ISO string as previously returned in :attr:`JournalEntry.created_at`
        (the fixed-width form makes the string comparison chronological)."""
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            self._require_known_kind(kind)
            clauses.append("kind = ?")
            params.append(kind)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(_iso(since) if isinstance(since, datetime) else since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_shadow_journal"
            f"{where} ORDER BY seq ASC",
            params,
        )
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def count(self, *, kind: str | None = None) -> int:
        """Entry count, optionally for one sanctioned kind (unknown kind raises)."""
        if kind is not None:
            self._require_known_kind(kind)
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM coordinator_shadow_journal WHERE kind = ?",
                (kind,),
            )
        else:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM coordinator_shadow_journal"
            )
        return int(cur.fetchone()[0])


# ---------------------------------------------------------------------------
# Fail-closed production factory (mirrors build_proposal_store, ADR-025 §2.8(a))
# ---------------------------------------------------------------------------


def build_shadow_journal(db_path: str, *, dev_mode: bool = False) -> ShadowJournal:
    """Build a born-encrypted :class:`ShadowJournal` — the production factory.

    Follows ``build_proposal_store``'s DEK-envelope construction EXACTLY
    (ADR-025), reusing the SAME one-DEK envelope (same ``BLARAI_DEK_KEYSTORE``
    keystore path, same ``TpmSealer("BlarAI-DEKSeal")`` key name) — the shadow
    journal is the FOURTH consumer of the one DEK the session/knowledge/proposal
    stores already share (ADR-025 §2.1). No new crypto, no new key, no new
    secret store.

    - Dev/test (``db_path == ':memory:'``, or ``dev_mode=True`` explicit):
      ``SoftwareSealer`` + ephemeral keystore. The dev path is a LOUD, explicit
      opt-in — never the silent default for a missing env var.
    - Production (``dev_mode=False``, ``BLARAI_DEK_KEYSTORE`` set):
      ``TpmSealer("BlarAI-DEKSeal")`` + the persisted keystore.
    - Misconfiguration (``dev_mode=False``, ``BLARAI_DEK_KEYSTORE`` MISSING,
      non-``:memory:``): REFUSE TO START —
      :class:`~shared.coordinator.proposal_store.StoreProvisioningError` (the
      coordinator layer's one provisioning exception, shared with the proposal
      store — same posture, same fail-closed semantics).

    Raises:
        StoreProvisioningError: production without a keystore, or a
            post-construction ``has_encryption`` wiring-invariant failure
            (#804 tripwire).
        DekEnvelopeError:   if the DEK cannot be unsealed (fail-closed).
        DevModeSealerError: if a SoftwareSealer is used without ``dev_mode=True``.
    """
    from shared.security.dek_envelope import (
        DekEnvelope,
        build_envelope,
        generate_recovery_key,
    )
    from shared.security.field_cipher import FieldCipher, derive_subkeys
    from shared.security.tpm_sealer import Sealer, SoftwareSealer

    keystore_env = os.environ.get("BLARAI_DEK_KEYSTORE", "")

    if db_path == ":memory:":
        # Pure in-memory — always dev/test; ephemeral envelope, never saved.
        sealer: Sealer = SoftwareSealer()
        recovery_key = generate_recovery_key()
        envelope = DekEnvelope.create(sealer=sealer, recovery_key=recovery_key)
    elif dev_mode:
        # Explicit dev/test — SoftwareSealer + ephemeral keystore alongside the DB.
        sealer = SoftwareSealer()
        recovery_key = generate_recovery_key()
        keystore_path = Path(db_path).with_suffix(".keystore.json")
        if keystore_path.exists():
            envelope = DekEnvelope.load(sealer=sealer, keystore_path=keystore_path)
        else:
            envelope = build_envelope(
                sealer=sealer,
                recovery_key=recovery_key,
                keystore_path=keystore_path,
                dev_mode=True,
            )
            logger.warning(
                "ShadowJournal: created ephemeral DEK keystore at %s (dev mode — "
                "SoftwareSealer, no TPM). Run the ceremony to provision a real "
                "TPM-sealed DEK.",
                keystore_path,
            )
    elif not keystore_env:
        # Production with a missing keystore — REFUSE TO START (ADR-025 §2.8(a)).
        logger.error(
            "BLARAI_DEK_KEYSTORE is not set and dev_mode=False — refusing to start "
            "the shadow journal. Production requires a TPM-sealed DEK keystore; a "
            "SoftwareSealer fallback is NOT permitted outside explicit dev_mode."
        )
        raise StoreProvisioningError(
            "BLARAI_DEK_KEYSTORE is not set in production mode (dev_mode=False). "
            "The coordinator shadow journal requires the shared TPM-sealed DEK "
            "keystore; constructing it with the SoftwareSealer is NOT permitted "
            "outside an explicit dev_mode=True context (ADR-025 §2.8(a))."
        )
    else:
        # Production — TpmSealer, shared keystore (same DEK as the session store).
        from shared.security.tpm_sealer import TpmSealer

        sealer = TpmSealer(key_name="BlarAI-DEKSeal")
        envelope = DekEnvelope.load(sealer=sealer, keystore_path=Path(keystore_env))

    dek = envelope.unseal_dek()
    subkeys = derive_subkeys(dek)
    cipher = FieldCipher(subkeys)

    journal = ShadowJournal(db_path=db_path, cipher=cipher)
    # Production-wiring regression lock: explicit raise (not assert) so it survives
    # `python -O` (#804, CWE-617).
    if journal.has_encryption is not True:  # pragma: no cover - defensive tripwire
        raise StoreProvisioningError(
            "ShadowJournal constructed without encryption wiring (has_encryption "
            "is not True) — refusing to return an unencrypted governed-core store."
        )
    return journal
