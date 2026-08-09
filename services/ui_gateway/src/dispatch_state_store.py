"""Born-encrypted store for the ``/dispatch`` pending-state slots (#1116).

WHY THIS EXISTS
---------------
The dispatch corridor is an INTERACTIVE, multi-turn conversation: BlarAI asks the
operator a question (#819 requirements / increment-4 platform) or shows a plan card
awaiting approval (#820 revise / approve), and then WAITS for a reply. Until this
module, the half-finished dispatch that gives that reply its meaning lived only in
:class:`~services.ui_gateway.src.dispatch_coordinator.DispatchCoordinator`'s
in-process :class:`~shared.ttl_dict.TtlDict` slots — while the chat transcript that
displays the question is durably stored in the encrypted ``sessions.db``.

So a restart split the two apart: the transcript kept rendering the question and
kept instructing the operator to answer it, and the engine no longer held it. The
operator's answer then arrived with nothing to attach it to. **The instruction on
screen became a lie.** Hit live by the operator on 2026-07-27, costing a long
free-text answer that the no-state path then discarded.

This store closes that gap: the parked dispatch survives a restart, so the answer
the screen asks for is the answer the engine can still consume.

DESIGN
------
ONE ROW PER SESSION, with a ``slot`` discriminator. The coordinator's own invariant
is that at most one of ``_requirements`` / ``_clarifying`` / ``_pending`` is populated
for a session at a time (a question precedes a plan; resolving one clears it and
populates the next). A single-row-per-session primary key makes that invariant
STRUCTURAL here rather than a property the caller must remember — two slots for one
session cannot be represented.

Born-encrypted (security_by_design principle 6): the payload carries the operator's
goal text, their typed answers, and the plan — the same class of content as the
session transcript, and it is encrypted from creation, never written plainly and
sealed later. This is a further consumer of the EXISTING one-DEK envelope the
session / knowledge / proposal stores already share (ADR-025 §2.1 — one DEK, N
consumers), via :mod:`shared.security.field_cipher` +
:mod:`shared.security.dek_envelope`. **No new crypto, no new key, no new secret
store.** Each ciphertext is AAD-bound to its ``(table, column, session-id + slot)``
identity (ADR-025 §2.4), so a payload blob relocated to another session's row — or
reinterpreted as a different slot — fails authentication rather than restoring one
operator's plan into another's chat. The ``slot`` component is load-bearing and was
missing until #1125: it is the discriminator that selects which dataclass a payload
rebuilds into, and the three payload shapes are mutually substitutable, so leaving it
unauthenticated let a one-column edit produce the half-restored plan the paragraph
below promises is impossible.

FAIL-CLOSED ON READ (the load-bearing safety property). A row that cannot be
decrypted, authenticated, or parsed is DROPPED and reported — never partially
restored. A half-understood plan is far more dangerous than an absent one: the
operator's next ``/dispatch approve`` would fire work they never actually saw. The
honest outcome of a corrupt row is "the parked job is gone, here is why", which the
coordinator's no-state path already handles by keeping the operator's text.

FAIL-LOUD BUT NON-BLOCKING ON WRITE. Persistence is a DURABILITY aid, not a security
control, so a write failure is logged at ERROR and the turn proceeds on the in-memory
slot — degrading to exactly the pre-#1116 behaviour. Failing the operator's live turn
because a durability write failed would trade a rare inconvenience for a certain one.

REACHABILITY: a store is constructed ONLY through the fail-closed factory
:func:`build_dispatch_state_store`. Importing this module arms nothing and changes no
behaviour; the coordinator treats a ``None`` store as "no persistence" and behaves
exactly as it did before this module existed.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Mapping

if TYPE_CHECKING:  # import only for typing — no runtime crypto import at module load
    from shared.security.field_cipher import FieldCipher

logger = logging.getLogger(__name__)

#: The store's table name — ALSO the AAD ``table`` component, so every ciphertext is
#: bound to this store's identity (ADR-025 §2.4).
_TABLE: Final[str] = "dispatch_pending_state"

#: The AAD ``column`` component for the encrypted payload.
_PAYLOAD_COLUMN: Final[str] = "payload"

#: The three slot discriminators — they mirror the coordinator's three pending
#: sub-states EXACTLY. A row's slot decides which dataclass the payload rebuilds
#: into on restore; an unrecognised slot is refused (fail-closed), never guessed.
SLOT_REQUIREMENTS: Final[str] = "requirements"
SLOT_CLARIFYING: Final[str] = "clarifying"
SLOT_PENDING: Final[str] = "pending"

#: Every slot this store will restore. A row whose slot is outside this set was
#: written by a future/foreign version and is dropped rather than interpreted.
KNOWN_SLOTS: Final[frozenset[str]] = frozenset(
    {SLOT_REQUIREMENTS, SLOT_CLARIFYING, SLOT_PENDING}
)

#: The PROJECT-MEMORY table (#1120) — what the operator has already told BlarAI about a
#: project, keyed by repo. Distinct from the pending-state table above in KEY (repo, not
#: session) and in LIFETIME: a pending slot is transient and clears the moment the operator
#: answers, whereas project memory OUTLIVES the plan it was gathered for. That is the whole
#: point — rejecting a plan means "not this plan", not "forget everything I told you".
_MEMORY_TABLE: Final[str] = "dispatch_project_memory"

#: The AAD ``column`` component for the project-memory payload.
_MEMORY_COLUMN: Final[str] = "answers"

_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS dispatch_pending_state (
    session_id  TEXT PRIMARY KEY,
    slot        TEXT NOT NULL,
    run_id      TEXT NOT NULL DEFAULT '',
    payload     BLOB NOT NULL,
    written_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispatch_project_memory (
    repo        TEXT PRIMARY KEY,
    answers     BLOB NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class DispatchStateProvisioningError(RuntimeError):
    """The store refused to construct (missing keystore / broken encryption wiring).

    Raised instead of silently returning an unencrypted store — there is no plaintext
    variant of this store, because the payload carries operator goal text.
    """


@dataclass(frozen=True)
class RestoredSlot:
    """One successfully decrypted, authenticated, parsed row (a restore candidate)."""

    session_id: str
    slot: str
    payload: dict[str, Any]
    written_at: str


class DispatchStateStore:
    """The sanctioned read/write API for parked ``/dispatch`` state.

    Every write travels through a method here; no raw-SQL write path is exposed. The
    coordinator holds at most one row per session and clears it the moment the
    sub-state resolves, so this table's steady-state size is "sessions with an
    unanswered question", not "sessions".
    """

    #: Production-wiring regression lock — a constructed store is always encrypted
    #: (there is no plaintext variant). The factory asserts this is True.
    has_encryption: bool = True

    def __init__(self, *, db_path: str, cipher: "FieldCipher") -> None:
        from shared.security.field_cipher import FieldCipher  # local — no cycle

        if not isinstance(cipher, FieldCipher):
            raise TypeError(
                "DispatchStateStore requires a FieldCipher instance derived from the "
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
        # secure_delete=ON: a resolved dispatch's freed pages are zeroed at checkpoint,
        # not merely marked free — the born-encrypted posture extends to deletion
        # (mirrors the session / knowledge / proposal stores).
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("DispatchStateStore initialized: %s", db_path)

    # ── lifecycle ─────────────────────────────────────────────────────────

    @staticmethod
    def _harden_dacl(db_path: str) -> None:
        """Apply the #637 owner-only DACL (defense-in-depth over the at-rest
        encryption). No-op for ``:memory:`` and on non-Windows hosts; never raises."""
        if db_path == ":memory:":
            return
        from shared.security.file_dacl import ensure_owner_only_dacl

        ensure_owner_only_dacl(db_path)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ── crypto helpers (the ONE-DEK envelope; AAD bound to the session row) ─

    def _payload_aad(self, session_id: str, slot: str) -> bytes:
        """AAD for a pending payload, binding it to its row AND its slot (#1125).

        ``slot`` is in here because it is the DISCRIMINATOR — ``restore_at_boot``
        dispatches on it to choose which dataclass to rebuild. Leaving it out bound the
        ciphertext to a row while leaving the field that decides HOW to interpret that
        ciphertext unauthenticated, and the three payload shapes turn out to be mutually
        substitutable: all three ``from_payload`` functions require only
        ``run_id``/``repo``/``goal`` and read every differing field with ``.get(default)``.
        Independent review demonstrated the consequence by execution — flipping a
        ``pending`` row to ``requirements`` (and back) SUCCEEDS, and the reverse yields a
        ``PendingDispatch`` with zero tasks and zero criteria sitting in the approve slot.
        This module's own docstring promised that could not happen; the promise was
        asserted, not implemented. Now it is implemented.
        """
        from shared.security.field_cipher import make_aad_for

        return make_aad_for(_TABLE, _PAYLOAD_COLUMN, f"{session_id}|{slot}")

    def _encrypt_payload(
        self, session_id: str, slot: str, payload: Mapping[str, Any]
    ) -> bytes:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self._cipher.encrypt(raw, aad=self._payload_aad(session_id, slot))

    def _decrypt_payload(self, session_id: str, slot: str, blob: Any) -> dict[str, Any]:
        """Decrypt + parse a payload blob, bound to its row identity.

        Fail-closed: an authentication failure or malformed JSON RAISES rather than
        returning unauthenticated or partial state. :meth:`load_all` converts that
        raise into "drop the row, report it" — a corrupt parked dispatch is never
        half-restored into a plan the operator did not approve.
        """
        from shared.security.field_cipher import FieldCipherError

        try:
            plaintext = self._cipher.decrypt(
                bytes(blob), aad=self._payload_aad(session_id, slot)
            )
        except FieldCipherError as exc:
            raise ValueError(f"payload failed authentication: {exc}") from exc
        parsed = json.loads(plaintext.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError(f"payload is {type(parsed).__name__}, expected an object")
        return parsed

    # ── the sanctioned write API ──────────────────────────────────────────

    def save(
        self, session_id: str, *, slot: str, payload: Mapping[str, Any], run_id: str = ""
    ) -> None:
        """Park (or re-park) *session_id*'s dispatch state in *slot*.

        REPLACE semantics: writing any slot for a session evicts whatever that session
        had parked, which is precisely the coordinator's own transition rule (answering
        a question replaces it with a plan). Raises on an unknown slot — a slot this
        store cannot restore must never be written in the first place.
        """
        if slot not in KNOWN_SLOTS:
            raise ValueError(f"unknown dispatch slot {slot!r}; expected one of {sorted(KNOWN_SLOTS)}")
        if not session_id:
            raise ValueError("session_id must be non-empty")
        blob = self._encrypt_payload(session_id, slot, payload)
        self._conn.execute(
            "INSERT OR REPLACE INTO dispatch_pending_state "
            "(session_id, slot, run_id, payload, written_at) VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                slot,
                str(run_id or ""),
                blob,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def clear(self, session_id: str) -> bool:
        """Forget *session_id*'s parked dispatch. Returns True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM dispatch_pending_state WHERE session_id = ?", (session_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── the sanctioned read API ───────────────────────────────────────────

    def load_all(self) -> list[RestoredSlot]:
        """Every restorable parked dispatch, newest write first.

        Fail-closed per row: a row that fails decryption, authentication, JSON parsing,
        or slot recognition is DELETED and logged at ERROR — it can never be silently
        skipped (which would leave an un-restorable row to fail again every boot) and
        can never be partially restored. Session ids only are logged; goal text and
        plan content never are.
        """
        try:
            rows = self._conn.execute(
                "SELECT session_id, slot, payload, written_at FROM dispatch_pending_state "
                "ORDER BY written_at DESC"
            ).fetchall()
        except sqlite3.Error as exc:
            logger.error("DispatchStateStore: cannot read parked state (%s) — restoring nothing.", exc)
            return []

        restored: list[RestoredSlot] = []
        poisoned: list[str] = []
        for session_id, slot, payload_blob, written_at in rows:
            if slot not in KNOWN_SLOTS:
                poisoned.append(str(session_id))
                logger.error(
                    "DispatchStateStore: session=%s parked in unknown slot %r — dropping "
                    "the row (fail-closed; nothing restored for that chat).",
                    session_id, slot,
                )
                continue
            try:
                payload = self._decrypt_payload(str(session_id), str(slot), payload_blob)
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                poisoned.append(str(session_id))
                logger.error(
                    "DispatchStateStore: session=%s parked state is unreadable (%s) — "
                    "dropping the row (fail-closed; a corrupt plan is never half-restored).",
                    session_id, exc,
                )
                continue
            restored.append(
                RestoredSlot(
                    session_id=str(session_id),
                    slot=str(slot),
                    payload=payload,
                    written_at=str(written_at or ""),
                )
            )

        for session_id in poisoned:
            self.clear(session_id)
        return restored


    # ── project memory: what the operator has already told us (#1120) ─────

    def _memory_aad(self, repo: str) -> bytes:
        from shared.security.field_cipher import make_aad_for

        return make_aad_for(_MEMORY_TABLE, _MEMORY_COLUMN, repo)

    def remember_answers(self, repo: str, answers: "list[Mapping[str, Any]]") -> None:
        """Record what the operator has told us about *repo* (REPLACE semantics).

        The caller passes the FULL merged set, not a delta — the coordinator owns the merge
        (a fresh answer supersedes a remembered one for the same question), so this stays a
        dumb, total write with no policy of its own. An empty list CLEARS the row: "you have
        told me nothing" and "the row is absent" must not be two distinguishable states.
        """
        if not repo:
            raise ValueError("repo must be non-empty")
        kept = [dict(a) for a in answers if str(a.get("answer", "")).strip()]
        if not kept:
            self.forget_answers(repo)
            return
        blob = self._cipher.encrypt(
            json.dumps({"answers": kept}, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            aad=self._memory_aad(repo),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO dispatch_project_memory (repo, answers, updated_at) "
            "VALUES (?, ?, ?)",
            (repo, blob, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def recall_answers(self, repo: str) -> list[dict[str, Any]]:
        """What the operator has told us about *repo*, or ``[]``.

        Fail-closed and SILENT-SAFE: an unreadable row is dropped, logged, and reported as
        "nothing remembered". Degrading to amnesia is the correct failure here — the operator
        sees the questions again, which is annoying; restoring a half-decrypted answer would
        put words in their mouth on a plan card, which is worse.
        """
        from shared.security.field_cipher import FieldCipherError

        if not repo:
            return []
        row = self._conn.execute(
            "SELECT answers FROM dispatch_project_memory WHERE repo = ?", (repo,)
        ).fetchone()
        if row is None:
            return []
        try:
            plaintext = self._cipher.decrypt(bytes(row[0]), aad=self._memory_aad(repo))
            parsed = json.loads(plaintext.decode("utf-8"))
            answers = parsed["answers"] if isinstance(parsed, dict) else None
            if not isinstance(answers, list):
                raise ValueError("payload has no 'answers' list")
        except (FieldCipherError, ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
            logger.error(
                "DispatchStateStore: project memory for repo=%s is unreadable (%s) — dropping "
                "it (fail-closed; the operator will simply be asked again).",
                repo, exc,
            )
            self.forget_answers(repo)
            return []
        return [dict(a) for a in answers if isinstance(a, dict)]

    def forget_answers(self, repo: str) -> bool:
        """Clear *repo*'s remembered answers. Returns True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM dispatch_project_memory WHERE repo = ?", (repo,)
        )
        self._conn.commit()
        return cur.rowcount > 0


def build_dispatch_state_store(
    db_path: str, *, dev_mode: bool = False
) -> DispatchStateStore:
    """Build a born-encrypted :class:`DispatchStateStore` — the production factory.

    Follows ``build_session_store`` / ``build_proposal_store`` construction EXACTLY
    (ADR-025), reusing the SAME one-DEK envelope (same ``BLARAI_DEK_KEYSTORE`` keystore
    path, same ``TpmSealer("BlarAI-DEKSeal")`` key name) — this is a further consumer of
    the one DEK the other sealed stores already share (ADR-025 §2.1).

    - Dev/test (``db_path == ':memory:'``, or explicit ``dev_mode=True``):
      ``SoftwareSealer`` + ephemeral keystore. A LOUD, explicit opt-in — never the
      silent default for a missing env var.
    - Production (``dev_mode=False``, ``BLARAI_DEK_KEYSTORE`` set):
      ``TpmSealer("BlarAI-DEKSeal")`` + the persisted keystore.
    - Misconfiguration (``dev_mode=False``, keystore MISSING, non-``:memory:``):
      REFUSE TO START — :class:`DispatchStateProvisioningError`.

    Raises:
        DispatchStateProvisioningError: production without a keystore, or a
            post-construction ``has_encryption`` wiring-invariant failure.
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
        sealer: Sealer = SoftwareSealer()
        envelope = DekEnvelope.create(sealer=sealer, recovery_key=generate_recovery_key())
    elif dev_mode:
        sealer = SoftwareSealer()
        keystore_path = Path(db_path).with_suffix(".keystore.json")
        if keystore_path.exists():
            envelope = DekEnvelope.load(sealer=sealer, keystore_path=keystore_path)
        else:
            envelope = build_envelope(
                sealer=sealer,
                recovery_key=generate_recovery_key(),
                keystore_path=keystore_path,
                dev_mode=True,
            )
            logger.warning(
                "DispatchStateStore: created ephemeral DEK keystore at %s (dev mode — "
                "SoftwareSealer, no TPM). Run the ceremony to provision a real "
                "TPM-sealed DEK.",
                keystore_path,
            )
    elif not keystore_env:
        logger.error(
            "BLARAI_DEK_KEYSTORE is not set and dev_mode=False — refusing to start the "
            "dispatch state store. It holds operator goal text and must be born "
            "encrypted; a SoftwareSealer fallback is NOT permitted outside an explicit "
            "dev_mode=True context (ADR-025 §2.8(a))."
        )
        raise DispatchStateProvisioningError(
            "BLARAI_DEK_KEYSTORE is not set in production mode (dev_mode=False). The "
            "dispatch state store requires the shared TPM-sealed DEK keystore."
        )
    else:
        from shared.security.tpm_sealer import TpmSealer

        sealer = TpmSealer(key_name="BlarAI-DEKSeal")
        envelope = DekEnvelope.load(sealer=sealer, keystore_path=Path(keystore_env))

    cipher = FieldCipher(derive_subkeys(envelope.unseal_dek()))
    store = DispatchStateStore(db_path=db_path, cipher=cipher)
    # Production-wiring regression lock: explicit raise (not assert) so it survives
    # `python -O` (#804, CWE-617).
    if store.has_encryption is not True:  # pragma: no cover - defensive tripwire
        raise DispatchStateProvisioningError(
            "DispatchStateStore constructed without encryption wiring (has_encryption "
            "is not True) — refusing to return an unencrypted store."
        )
    return store
