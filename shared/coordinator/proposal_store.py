"""Born-encrypted coordinator proposal-staging store (#844 C2 / #845 C3, ADR-039).

The single, sanctioned home for coordinator PROPOSALS before an operator acts on
them — the shared C2↔C3 dependency named in the Coordinator program plan: C2's
PARKED-HONEST → redispatch proposal (#844) and C3's heartbeat proposals/digests
(#845) both stage into THIS store, so it is built once, cleanly, and consumed by
both.

Governed core (ADR-039 §2.1 item 10): "the proposal-staging store itself — appended
to only via the sanctioned staging API, never by direct write." This module IS that
sanctioned API. Every write travels through a method here; no raw-SQL write path is
exposed. A caller that reaches around this API to write the table directly violates
the self-governance boundary — the whole point of the store being governed core is
that its append path is the ONLY one.

Born-encrypted (ADR-039 §2.13 item 2): the content-bearing ``payload`` (proposal
goals, ticket text, target, evidence pointers, digest text) is AES-256-GCM encrypted
at rest under the SAME one-DEK envelope the session/knowledge stores use (ADR-025
§2.1 — one DEK, N consumers), via :mod:`shared.security.field_cipher` +
:mod:`shared.security.dek_envelope`. **No new crypto is introduced here** — this is
a third consumer of the existing sealed-store machinery. Each ciphertext is
AAD-bound to its (table, column, row-UUID) identity (ADR-025 §2.4), so a blob
relocated to a different row fails authentication.

Refuse-to-start (ADR-025 §2.8(a), mirrored from ``build_session_store``): the
production factory :func:`build_proposal_store` REFUSES to construct
(:class:`StoreProvisioningError`) when ``dev_mode=False`` and no
``BLARAI_DEK_KEYSTORE`` is provisioned — it never silently falls back to the public
``SoftwareSealer`` key. Fail-closed, no plaintext fallback, ever.

Crash-safe reconcile on boot (mirrors ``swap_state.reconcile_swap_state``):
:meth:`ProposalStore.reconcile_at_boot` is an idempotent boot-time convergence —
it applies any TTL expiry that accrued while the app was off (demoting un-actioned
STAGED proposals back to DRAFT, ADR-039 §2.12.5 "back to drafts with a note"). All
writes are single-row atomic SQLite commits (WAL), so there is no half-written
proposal to repair; the only time-dependent convergence is TTL.

DORMANCY: this module has NO live consumer. Nothing in a production boot path
constructs a :class:`ProposalStore` today (C2's redispatch limb and C3's heartbeat
wire it in later, dormant behind ``[coordinator]`` flags). Importing this module
arms nothing and changes no behavior — exactly like
:mod:`shared.fleet.coord_lifecycle` and :mod:`shared.coordinator.governed_core`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Mapping

if TYPE_CHECKING:  # import only for typing — no runtime crypto import at module load
    from shared.security.field_cipher import FieldCipher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default un-actioned-proposal TTL (ADR-039 §2.12.5 — "expire after a configured
#: TTL, default 7 days, back to drafts"). A STAGED proposal older than this (from
#: when it was surfaced) is demoted to DRAFT so an operator's absence never returns
#: to a wall of stale asks. Configurable per store; never a magic constant.
DEFAULT_PROPOSAL_TTL_DAYS: Final[int] = 7

#: The store's table name — ALSO the AAD ``table`` component, so every ciphertext is
#: bound to this store's identity (ADR-025 §2.4). Relocating a payload blob into any
#: other table/store fails authentication.
_TABLE: Final[str] = "coordinator_proposals"

#: The AAD ``column`` component for the encrypted payload.
_PAYLOAD_COLUMN: Final[str] = "payload"

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS coordinator_proposals (
    id              TEXT PRIMARY KEY,
    lane            TEXT NOT NULL,
    proposal_class  TEXT NOT NULL,
    status          TEXT NOT NULL,
    fingerprint_idx BLOB NOT NULL,
    payload         BLOB NOT NULL,
    created_at      TEXT NOT NULL,
    staged_at       TEXT NOT NULL DEFAULT '',
    expires_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    system_note     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_proposals_fingerprint
    ON coordinator_proposals(fingerprint_idx);
CREATE INDEX IF NOT EXISTS idx_proposals_status
    ON coordinator_proposals(status);
"""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StoreProvisioningError(RuntimeError):
    """Raised by :func:`build_proposal_store` when a required keystore is absent in
    production mode (``dev_mode=False``).

    The coordinator-layer counterpart to the session store's identically-named
    (and identically-purposed) exception (ADR-025 §2.8(a)). ``shared/`` must not
    depend on ``services/``, so the proposal store carries its own — same posture,
    same fail-closed semantics: a production boot without ``BLARAI_DEK_KEYSTORE``
    refuses to start rather than silently encrypting under the public
    ``SoftwareSealer`` key (which is not a security boundary).

    Also raised when the constructed store fails its ``has_encryption`` wiring
    invariant — an explicit tripwire (not an ``assert``) so it survives a future
    ``python -O`` invocation (#804, CWE-617).
    """


class ProposalStoreError(RuntimeError):
    """Raised for a proposal-store integrity fault (unknown id on a transition, a
    malformed persisted record). Fail-closed: the store never returns a partial or
    unauthenticated result."""


# ---------------------------------------------------------------------------
# Vocabulary — lane + status (structural metadata, never model free text)
# ---------------------------------------------------------------------------


class ProposalLane(Enum):
    """The two proposal lanes (ADR-039 §2.2 control 2).

    ``WORKSPACE`` proposals target project repos and are executable (post-approval)
    via BlarAI's own dispatch path. ``SELF_ADVISORY`` proposals are about BlarAI
    itself and are routed EXCLUSIVELY to the human-governed dev channel — BlarAI's
    dispatch path refuses them categorically, even post-approval. The lane is
    structural (set by deterministic code), never parsed from model output."""

    WORKSPACE = "workspace"
    SELF_ADVISORY = "self_advisory"


class ProposalStatus(Enum):
    """The proposal lifecycle (ADR-039 §2.12.5).

    ``DRAFT`` — staged into the store but not yet surfaced to the operator (the
    resting state; also where a TTL-expired STAGED proposal is demoted).
    ``STAGED`` — surfaced for approval (in a briefing/digest); the TTL clock runs
    from here.
    ``APPROVED`` / ``REJECTED`` — the operator's decision (terminal).

    A TTL-expired ``STAGED`` proposal returns to ``DRAFT`` (never a silent drop),
    so an operator's absence degrades to quiet safety, not a wall of stale asks."""

    DRAFT = "draft"
    STAGED = "staged"
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def is_active(self) -> bool:
        """True for the non-terminal states (DRAFT/STAGED) — the ones dedup and TTL
        reason over. APPROVED/REJECTED are terminal and never deduped against."""
        return self in (ProposalStatus.DRAFT, ProposalStatus.STAGED)


#: The active (non-terminal) status values — the dedup/TTL working set.
_ACTIVE_STATUS_VALUES: Final[tuple[str, ...]] = (
    ProposalStatus.DRAFT.value,
    ProposalStatus.STAGED.value,
)


# ---------------------------------------------------------------------------
# Canonical fingerprint (ADR-039 §2.12.5 — "class + target + evidence hash")
# ---------------------------------------------------------------------------


def proposal_fingerprint(
    *, proposal_class: str, target: str, evidence_hash: str
) -> str:
    """The canonical deterministic dedup fingerprint for a proposal.

    ADR-039 §2.12.5: "Proposals carry a deterministic fingerprint (class + target +
    evidence hash); a condition detected every cycle stages ONE proposal, not one
    per cycle." This is the SSOT builder so every consumer (C2 redispatch, C3
    heartbeat) fingerprints identically — a NUL-separated SHA-256 over the three
    structured fields (NUL cannot appear in any of them, so the boundaries are
    unambiguous and the hash is injection-safe). The raw fingerprint is never
    stored in plaintext; :meth:`ProposalStore.add_draft` stores only its
    keyed-index (HMAC), so even the target repo it encodes stays confidential at
    rest (ADR-025 §2.4)."""
    material = f"{proposal_class}\x00{target}\x00{evidence_hash}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    """A decrypted proposal view returned by the store's read methods.

    ``payload`` is the decrypted content dict (goals, ticket text, target, evidence
    pointers, digest text — whatever the consumer staged). All other fields are the
    plaintext lifecycle metadata the deterministic ruler reasons over."""

    id: str
    lane: ProposalLane
    proposal_class: str
    status: ProposalStatus
    payload: Mapping[str, Any]
    created_at: str
    staged_at: str
    expires_at: str
    updated_at: str
    system_note: str


@dataclass(frozen=True)
class ProposalReconcileResult:
    """The outcome of a boot-time reconcile — how many STAGED proposals were demoted
    to DRAFT by accrued TTL expiry. Idempotent: a second reconcile at the same
    ``now`` demotes nothing (``demoted == 0``)."""

    demoted: int


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """The current UTC instant (tz-aware). Factored out so tests inject ``now``
    explicitly and never depend on the wall clock."""
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """A tz-aware datetime as an ISO-8601 UTC string (the on-disk metadata form).

    Pinned to fixed-width microsecond precision (``timespec="microseconds"``) so the
    ``WHERE expires_at <= ?`` string comparison in :meth:`ProposalStore.expire_stale`
    is unambiguously chronological — every timestamp shares the same width and the
    ``+00:00`` offset, so lexicographic order == time order."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


class ProposalStore:
    """SQLite-backed, born-encrypted proposal-staging store — the sanctioned API.

    Construct via :func:`build_proposal_store` (the fail-closed production factory),
    never directly in production: the factory resolves the shared DEK envelope and
    enforces the refuse-to-start posture. The direct constructor takes an
    already-built :class:`~shared.security.field_cipher.FieldCipher`, matching
    :class:`~services.ui_gateway.src.session_store.EncryptedSessionStore`.

    Every mutation is a method here (``add_draft`` / ``mark_staged`` /
    ``mark_approved`` / ``mark_rejected`` / ``expire_stale`` / ``reconcile_at_boot``)
    — the sole sanctioned write path (ADR-039 §2.1 item 10). Reads return
    :class:`Proposal` value objects with the payload decrypted."""

    #: Production-wiring regression lock — a constructed store is always encrypted
    #: (there is no plaintext variant). ``build_proposal_store`` asserts this True.
    has_encryption: bool = True

    def __init__(
        self,
        *,
        db_path: str,
        cipher: "FieldCipher",
        ttl_days: int = DEFAULT_PROPOSAL_TTL_DAYS,
    ) -> None:
        from shared.security.field_cipher import FieldCipher  # local — no cycle

        if not isinstance(cipher, FieldCipher):
            raise TypeError(
                "ProposalStore requires a FieldCipher instance derived from the "
                f"unsealed DEK; got {type(cipher).__name__!r}."
            )
        if ttl_days <= 0:
            raise ValueError(f"ttl_days must be positive, got {ttl_days}")

        self._db_path = db_path
        self._cipher = cipher
        self._ttl = timedelta(days=ttl_days)

        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._harden_dacl(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # secure_delete=ON: a demoted/rejected proposal's freed pages are zeroed at
        # checkpoint, not merely marked free — the born-encrypted posture extends to
        # deletion (mirrors the session/knowledge stores).
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("ProposalStore initialized: %s", db_path)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _harden_dacl(db_path: str) -> None:
        """Apply the #637 owner-only DACL to the store file (defense-in-depth on top
        of the at-rest encryption; the store is governed core, ADR-039 §2.1 item 10).
        No-op for ``:memory:`` and on non-Windows hosts; never raises."""
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

    def _payload_aad(self, proposal_id: str) -> bytes:
        from shared.security.field_cipher import make_aad_for

        return make_aad_for(_TABLE, _PAYLOAD_COLUMN, proposal_id)

    def _encrypt_payload(self, proposal_id: str, payload: Mapping[str, Any]) -> bytes:
        """Serialize + encrypt a payload dict, bound to its row identity."""
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return self._cipher.encrypt(raw, aad=self._payload_aad(proposal_id))

    def _decrypt_payload(self, proposal_id: str, blob: Any) -> dict[str, Any]:
        """Decrypt + parse a payload blob. Fail-closed: an authentication failure or
        malformed JSON raises rather than returning unauthenticated/partial data."""
        from shared.security.field_cipher import FieldCipherError

        try:
            plaintext = self._cipher.decrypt(
                bytes(blob), aad=self._payload_aad(proposal_id)
            )
        except FieldCipherError as exc:
            raise ProposalStoreError(
                f"proposal {proposal_id}: payload authentication failed "
                "(tampered, wrong key, or relocated row)"
            ) from exc
        try:
            parsed = json.loads(plaintext)
        except (ValueError, TypeError) as exc:
            raise ProposalStoreError(
                f"proposal {proposal_id}: payload is not valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProposalStoreError(
                f"proposal {proposal_id}: payload did not decode to an object"
            )
        return parsed

    def _row_to_proposal(self, row: sqlite3.Row | tuple) -> Proposal:
        (
            pid,
            lane,
            proposal_class,
            status,
            _fingerprint_idx,
            payload_blob,
            created_at,
            staged_at,
            expires_at,
            updated_at,
            system_note,
        ) = row
        return Proposal(
            id=pid,
            lane=ProposalLane(lane),
            proposal_class=proposal_class,
            status=ProposalStatus(status),
            payload=self._decrypt_payload(pid, payload_blob),
            created_at=created_at,
            staged_at=staged_at,
            expires_at=expires_at,
            updated_at=updated_at,
            system_note=system_note,
        )

    # ------------------------------------------------------------------
    # Sanctioned writes (the SOLE append/transition path — §2.1 item 10)
    # ------------------------------------------------------------------

    def add_draft(
        self,
        *,
        lane: ProposalLane,
        proposal_class: str,
        fingerprint: str,
        payload: Mapping[str, Any],
        now: datetime | None = None,
    ) -> Proposal:
        """Stage a new proposal as a DRAFT — idempotent on ``fingerprint``.

        The anti-firehose invariant of ADR-039 §2.12.5 realized IN the store: if an
        ACTIVE (DRAFT or STAGED) proposal already carries this fingerprint, that
        existing proposal is returned unchanged and NO duplicate is inserted — a
        condition detected every cycle stages exactly one proposal, never one per
        cycle. (A terminal APPROVED/REJECTED proposal with the same fingerprint does
        NOT suppress a fresh draft — a recurrence after a decision is new work.)

        The fingerprint is stored only as its keyed-index (HMAC under the DEK's
        index subkey), so the target it encodes never sits in plaintext. The payload
        is encrypted, AAD-bound to the freshly-minted row UUID."""
        now = now or _utc_now()
        fingerprint_idx = self._cipher.keyed_index(fingerprint.encode("utf-8"))

        existing = self._find_active_row_by_fingerprint_idx(fingerprint_idx)
        if existing is not None:
            return self._row_to_proposal(existing)

        proposal_id = str(uuid.uuid4())
        created = _iso(now)
        expires = _iso(now + self._ttl)
        payload_blob = self._encrypt_payload(proposal_id, payload)
        self._conn.execute(
            "INSERT INTO coordinator_proposals "
            "(id, lane, proposal_class, status, fingerprint_idx, payload, "
            " created_at, staged_at, expires_at, updated_at, system_note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, '')",
            (
                proposal_id,
                lane.value,
                proposal_class,
                ProposalStatus.DRAFT.value,
                fingerprint_idx,
                payload_blob,
                created,
                expires,
                created,
            ),
        )
        self._conn.commit()
        loaded = self._get_row(proposal_id)
        assert loaded is not None  # just inserted
        return self._row_to_proposal(loaded)

    def mark_staged(self, proposal_id: str, *, now: datetime | None = None) -> Proposal:
        """Surface a DRAFT for operator approval (DRAFT → STAGED) and (re)start its
        TTL clock: ``expires_at`` is set to ``now + ttl``. The TTL runs from the
        moment a proposal is put in front of the operator, per §2.12.5's
        "un-actioned proposals expire after a configured TTL"."""
        now = now or _utc_now()
        staged = _iso(now)
        expires = _iso(now + self._ttl)
        return self._transition(
            proposal_id,
            to_status=ProposalStatus.STAGED,
            from_statuses=(ProposalStatus.DRAFT, ProposalStatus.STAGED),
            now=now,
            extra_sets={"staged_at": staged, "expires_at": expires},
        )

    def mark_approved(
        self, proposal_id: str, *, now: datetime | None = None
    ) -> Proposal:
        """Record the operator's approval (STAGED → APPROVED, terminal)."""
        return self._transition(
            proposal_id,
            to_status=ProposalStatus.APPROVED,
            from_statuses=(ProposalStatus.STAGED,),
            now=now or _utc_now(),
        )

    def mark_rejected(
        self, proposal_id: str, *, now: datetime | None = None
    ) -> Proposal:
        """Record the operator's rejection (STAGED → REJECTED, terminal)."""
        return self._transition(
            proposal_id,
            to_status=ProposalStatus.REJECTED,
            from_statuses=(ProposalStatus.STAGED,),
            now=now or _utc_now(),
        )

    def expire_stale(self, *, now: datetime | None = None) -> int:
        """Demote every STAGED proposal whose TTL has passed back to DRAFT.

        ADR-039 §2.12.5: "un-actioned proposals expire after a configured TTL back
        to drafts with a note." Only STAGED (surfaced-but-un-actioned) proposals are
        subject — a DRAFT is already un-surfaced, and APPROVED/REJECTED are terminal.
        Returns the count demoted. Deterministic (``now`` supplied) and idempotent
        (a second call at the same ``now`` demotes nothing)."""
        now = now or _utc_now()
        now_iso = _iso(now)
        note = f"TTL-expired to draft on {now_iso} (un-actioned)"
        cur = self._conn.execute(
            "UPDATE coordinator_proposals "
            "SET status = ?, updated_at = ?, system_note = ? "
            "WHERE status = ? AND expires_at <= ?",
            (
                ProposalStatus.DRAFT.value,
                now_iso,
                note,
                ProposalStatus.STAGED.value,
                now_iso,
            ),
        )
        self._conn.commit()
        return cur.rowcount

    def extend_ttl(self, *, delta: timedelta, now: datetime | None = None) -> int:
        """Extend every STAGED proposal's TTL deadline by *delta* — the ONE
        sanctioned operator-absence pause API (#845 C3, design §8.2; ADR-039
        §2.12.9).

        The absence TTL pause is real, not a sweep-skip: skipping
        :meth:`expire_stale` during an absence and sweeping on return would demote
        every surfaced ask at once. Instead the heartbeat cycle, on the first cycle
        after ``operator_absent`` flips back off, extends each STAGED proposal's
        ``expires_at`` by the recorded absence duration — the TTL clock simply did
        not run while the operator was away. Only STAGED proposals are subject (the
        TTL clock runs from staging, exactly as :meth:`expire_stale` sweeps only
        STAGED; DRAFTs are un-surfaced and APPROVED/REJECTED are terminal). Returns
        the count extended.

        A non-positive *delta* is a no-op returning 0 (a negative extension would
        SHORTEN deadlines — the wrong direction; clock skew at the caller must
        never accelerate expiry). A row whose ``expires_at`` does not parse is
        skipped WITH a warning (fail-loud: the store is this module's only writer,
        so an unparseable deadline is corruption worth hearing about, but one bad
        row must not strand the rest of the pause). Like every mutation here, this
        is a sanctioned-API method — never a raw write (§2.1 item 10)."""
        if delta <= timedelta(0):
            return 0
        now = now or _utc_now()
        now_iso = _iso(now)
        cur = self._conn.execute(
            "SELECT id, expires_at FROM coordinator_proposals WHERE status = ?",
            (ProposalStatus.STAGED.value,),
        )
        extended = 0
        note = (
            f"TTL paused for operator absence — deadline extended by "
            f"{delta.total_seconds():.0f}s on {now_iso}"
        )
        for proposal_id, expires_at in cur.fetchall():
            try:
                expires = datetime.fromisoformat(expires_at)
            except (ValueError, TypeError):
                logger.warning(
                    "ProposalStore.extend_ttl: proposal %s has an unparseable "
                    "expires_at %r — skipped (surfaced, not silently rewritten)",
                    proposal_id,
                    expires_at,
                )
                continue
            self._conn.execute(
                "UPDATE coordinator_proposals "
                "SET expires_at = ?, updated_at = ?, system_note = ? WHERE id = ?",
                (_iso(expires + delta), now_iso, note, proposal_id),
            )
            extended += 1
        self._conn.commit()
        return extended

    def reconcile_at_boot(
        self, *, now: datetime | None = None
    ) -> ProposalReconcileResult:
        """Idempotent boot-time convergence (mirrors
        ``swap_state.reconcile_swap_state``).

        Applies any TTL expiry that accrued while the app was off — the only
        time-dependent convergence this store needs, because every write is a
        single-row atomic SQLite commit (there is no half-written proposal to
        repair). A second reconcile at the same instant is a clean no-op."""
        now = now or _utc_now()
        demoted = self.expire_stale(now=now)
        if demoted:
            logger.info(
                "ProposalStore.reconcile_at_boot: demoted %d stale STAGED proposal(s) "
                "to DRAFT (TTL)",
                demoted,
            )
        return ProposalReconcileResult(demoted=demoted)

    def _transition(
        self,
        proposal_id: str,
        *,
        to_status: ProposalStatus,
        from_statuses: tuple[ProposalStatus, ...],
        now: datetime,
        extra_sets: Mapping[str, str] | None = None,
    ) -> Proposal:
        """Deterministic status transition with an explicit legal-from-state gate.

        Fail-closed: an unknown id, or a transition from an illegal current state
        (e.g. approving a DRAFT that was never staged, or a terminal proposal),
        raises :class:`ProposalStoreError` rather than silently mutating — the store
        never fabricates a lifecycle jump."""
        row = self._get_row(proposal_id)
        if row is None:
            raise ProposalStoreError(f"proposal {proposal_id}: not found")
        current = ProposalStatus(row[3])
        if current not in from_statuses:
            legal = ", ".join(s.value for s in from_statuses)
            raise ProposalStoreError(
                f"proposal {proposal_id}: illegal transition {current.value} -> "
                f"{to_status.value} (legal from: {legal})"
            )
        sets = {"status": to_status.value, "updated_at": _iso(now)}
        if extra_sets:
            sets.update(extra_sets)
        assignments = ", ".join(f"{col} = ?" for col in sets)
        params = list(sets.values()) + [proposal_id]
        self._conn.execute(
            f"UPDATE coordinator_proposals SET {assignments} WHERE id = ?", params
        )
        self._conn.commit()
        updated = self._get_row(proposal_id)
        assert updated is not None  # just updated
        return self._row_to_proposal(updated)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    _SELECT_COLS: Final[str] = (
        "id, lane, proposal_class, status, fingerprint_idx, payload, "
        "created_at, staged_at, expires_at, updated_at, system_note"
    )

    def _get_row(self, proposal_id: str) -> tuple | None:
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_proposals WHERE id = ?",
            (proposal_id,),
        )
        return cur.fetchone()

    def _find_active_row_by_fingerprint_idx(self, fingerprint_idx: bytes) -> tuple | None:
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUS_VALUES)
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_proposals "
            f"WHERE fingerprint_idx = ? AND status IN ({placeholders}) "
            "ORDER BY created_at ASC LIMIT 1",
            (fingerprint_idx, *_ACTIVE_STATUS_VALUES),
        )
        return cur.fetchone()

    def get(self, proposal_id: str) -> Proposal | None:
        """Fetch one proposal (payload decrypted), or ``None`` if unknown."""
        row = self._get_row(proposal_id)
        return self._row_to_proposal(row) if row is not None else None

    def find_active_by_fingerprint(self, fingerprint: str) -> Proposal | None:
        """The active (DRAFT/STAGED) proposal carrying ``fingerprint``, if any — the
        dedup query a consumer runs before deciding to stage a fresh proposal."""
        fingerprint_idx = self._cipher.keyed_index(fingerprint.encode("utf-8"))
        row = self._find_active_row_by_fingerprint_idx(fingerprint_idx)
        return self._row_to_proposal(row) if row is not None else None

    def find_by_fingerprint(self, fingerprint: str) -> list[Proposal]:
        """Every proposal carrying ``fingerprint`` in ANY status, oldest first — the
        full-history sibling of :meth:`find_active_by_fingerprint`.

        A consumer uses it to distinguish "never proposed" from "already proposed
        and DECIDED": the C2 redispatch limb (#844,
        :mod:`shared.fleet.coord_redispatch`) refuses to re-stage evidence the
        operator already APPROVED/REJECTED — re-asking about the SAME parked run
        after a decision would be the wall-of-stale-asks ADR-039 §2.12.5 exists to
        prevent; only genuinely NEW evidence mints a new fingerprint. READ-ONLY:
        this adds no write path (the sanctioned-API rule, §2.1 item 10, governs
        writes; reads were always method-mediated here too)."""
        fingerprint_idx = self._cipher.keyed_index(fingerprint.encode("utf-8"))
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_proposals "
            "WHERE fingerprint_idx = ? ORDER BY created_at ASC",
            (fingerprint_idx,),
        )
        return [self._row_to_proposal(r) for r in cur.fetchall()]

    def list_by_status(self, status: ProposalStatus) -> list[Proposal]:
        """Every proposal in ``status``, oldest first."""
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_proposals "
            "WHERE status = ? ORDER BY created_at ASC",
            (status.value,),
        )
        return [self._row_to_proposal(r) for r in cur.fetchall()]

    def list_active(self) -> list[Proposal]:
        """Every active (DRAFT + STAGED) proposal, oldest first — the working set the
        heartbeat/briefing reasons over."""
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUS_VALUES)
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM coordinator_proposals "
            f"WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            _ACTIVE_STATUS_VALUES,
        )
        return [self._row_to_proposal(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Fail-closed production factory (mirrors build_session_store, ADR-025 §2.8(a))
# ---------------------------------------------------------------------------


def build_proposal_store(
    db_path: str,
    *,
    dev_mode: bool = False,
    ttl_days: int = DEFAULT_PROPOSAL_TTL_DAYS,
) -> ProposalStore:
    """Build a born-encrypted :class:`ProposalStore` — the production factory.

    Follows ``build_session_store``'s DEK-envelope construction EXACTLY (ADR-025),
    reusing the SAME one-DEK envelope (same ``BLARAI_DEK_KEYSTORE`` keystore path,
    same ``TpmSealer("BlarAI-DEKSeal")`` key name) — the proposal store is a third
    consumer of the one DEK the session/knowledge stores already share (ADR-025
    §2.1). No new crypto, no new key, no new secret store.

    - Dev/test (``db_path == ':memory:'``, or ``dev_mode=True`` explicit):
      ``SoftwareSealer`` + ephemeral keystore. The dev path is a LOUD, explicit
      opt-in — never the silent default for a missing env var.
    - Production (``dev_mode=False``, ``BLARAI_DEK_KEYSTORE`` set):
      ``TpmSealer("BlarAI-DEKSeal")`` + the persisted keystore.
    - Misconfiguration (``dev_mode=False``, ``BLARAI_DEK_KEYSTORE`` MISSING,
      non-``:memory:``): REFUSE TO START — :class:`StoreProvisioningError`.

    Raises:
        StoreProvisioningError: production without a keystore, or a post-construction
            ``has_encryption`` wiring-invariant failure (#804 tripwire).
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
                "ProposalStore: created ephemeral DEK keystore at %s (dev mode — "
                "SoftwareSealer, no TPM). Run the ceremony to provision a real "
                "TPM-sealed DEK.",
                keystore_path,
            )
    elif not keystore_env:
        # Production with a missing keystore — REFUSE TO START (ADR-025 §2.8(a)).
        logger.error(
            "BLARAI_DEK_KEYSTORE is not set and dev_mode=False — refusing to start "
            "the proposal store. Production requires a TPM-sealed DEK keystore; a "
            "SoftwareSealer fallback is NOT permitted outside explicit dev_mode."
        )
        raise StoreProvisioningError(
            "BLARAI_DEK_KEYSTORE is not set in production mode (dev_mode=False). "
            "The coordinator proposal store requires the shared TPM-sealed DEK "
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

    store = ProposalStore(db_path=db_path, cipher=cipher, ttl_days=ttl_days)
    # Production-wiring regression lock: explicit raise (not assert) so it survives
    # `python -O` (#804, CWE-617).
    if store.has_encryption is not True:  # pragma: no cover - defensive tripwire
        raise StoreProvisioningError(
            "ProposalStore constructed without encryption wiring (has_encryption "
            "is not True) — refusing to return an unencrypted governed-core store."
        )
    return store
