"""Isolated locks for the born-encrypted, append-only shadow journal.

`shared/coordinator/shadow_journal.py` (#845 C3 limb 4, design §7.3). The journal
has NO live consumer yet — these tests exercise it in isolation, mirroring the
proposal-store suite (the SAME one-DEK sealed-store machinery, fourth consumer):
round-trip, encrypted-at-rest (blob-level AND file-byte-level), AAD binding, the
kind allowlist, deterministic caller-injected timestamps, ordered reads, the
append-only public surface, and the production refuse-to-start posture.

All tests use the SoftwareSealer dev path (``:memory:`` or ``dev_mode=True``) —
the one-DEK envelope reuse and the TPM production path are exercised by the
shared crypto layer's own suites; here the focus is the JOURNAL's behavior over
that layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.coordinator.proposal_store import StoreProvisioningError
from shared.coordinator.shadow_journal import (
    JOURNAL_KINDS,
    KIND_BOARD_MOVE,
    KIND_DIGEST,
    KIND_PROPOSAL_COPY,
    KIND_STALL_COMMENT,
    KIND_TRIPWIRE_ALARM,
    JournalEntry,
    ShadowJournal,
    ShadowJournalError,
    build_shadow_journal,
)

T0 = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def journal():
    """An in-memory journal (SoftwareSealer dev path); closed on teardown."""
    j = build_shadow_journal(":memory:")
    try:
        yield j
    finally:
        j.close()


# ---------------------------------------------------------------------------
# Round-trip + deterministic timestamps
# ---------------------------------------------------------------------------


def test_append_round_trip(journal: ShadowJournal) -> None:
    payload = {"task_id": 42, "markdown": "**Coordinator — stall detected.**"}
    entry = journal.append(KIND_STALL_COMMENT, payload, now=T0)
    assert entry.kind == KIND_STALL_COMMENT
    assert entry.payload == payload  # decrypts identically
    assert entry.created_at == "2026-07-14T12:00:00.000000+00:00"
    assert entry.seq == 1

    listed = journal.list_entries()
    assert len(listed) == 1
    assert listed[0] == entry


def test_all_sanctioned_kinds_accepted(journal: ShadowJournal) -> None:
    for i, kind in enumerate(sorted(JOURNAL_KINDS)):
        entry = journal.append(kind, {"i": i}, now=T0 + timedelta(seconds=i))
        assert entry.kind == kind
    assert journal.count() == len(JOURNAL_KINDS)


def test_unknown_kind_refused_on_append(journal: ShadowJournal) -> None:
    with pytest.raises(ShadowJournalError):
        journal.append("machinery_health", {"x": 1}, now=T0)
    assert journal.count() == 0


def test_unknown_kind_refused_on_read(journal: ShadowJournal) -> None:
    """A typo'd read kind RAISES rather than returning [] — #855's grading must
    never mistake a misspelled query for a clean shadow run (fail-loud)."""
    with pytest.raises(ShadowJournalError):
        journal.list_entries(kind="stall_comments")  # plural typo
    with pytest.raises(ShadowJournalError):
        journal.count(kind="digests")


def test_naive_now_refused(journal: ShadowJournal) -> None:
    """Timestamps are caller-injected and tz-aware — a naive clock is a caller
    bug, refused before any side effect (mirrors run_wake_cycle's clock gate)."""
    with pytest.raises(ValueError):
        journal.append(KIND_DIGEST, {"d": 1}, now=datetime(2026, 7, 14, 12, 0, 0))
    assert journal.count() == 0


# ---------------------------------------------------------------------------
# Encrypted-at-rest + AAD binding (the born-encrypted lock, ADR-039 §2.13.2)
# ---------------------------------------------------------------------------


def test_payload_is_encrypted_at_rest_blob(journal: ShadowJournal) -> None:
    entry = journal.append(
        KIND_DIGEST, {"prose": "SECRET-MARKER-digest-text"}, now=T0
    )
    raw = journal._conn.execute(  # noqa: SLF001 - test reaches in to inspect at-rest bytes
        "SELECT payload FROM coordinator_shadow_journal WHERE id = ?", (entry.id,)
    ).fetchone()[0]
    raw_bytes = bytes(raw)
    # First byte is the field-cipher version, and the plaintext marker is absent.
    assert raw_bytes[0] == 0x01
    assert b"SECRET-MARKER-digest-text" not in raw_bytes


def test_payload_is_encrypted_at_rest_file_bytes(tmp_path) -> None:
    """The whole on-disk footprint (db + WAL sidecars) carries no plaintext
    payload marker — the at-rest posture holds at the byte level, not just
    through the API."""
    db = tmp_path / "journal.db"
    j = build_shadow_journal(str(db), dev_mode=True)
    try:
        j.append(
            KIND_STALL_COMMENT,
            {"task_id": 7, "markdown": "SECRET-MARKER-comment-body"},
            now=T0,
        )
    finally:
        j.close()
    on_disk = b""
    for candidate in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        if candidate.exists():
            on_disk += candidate.read_bytes()
    assert b"SECRET-MARKER-comment-body" not in on_disk


def test_aad_binding_relocation_fails(journal: ShadowJournal) -> None:
    a = journal.append(KIND_DIGEST, {"prose": "payload-A"}, now=T0)
    b = journal.append(KIND_DIGEST, {"prose": "payload-B"}, now=T0)
    a_blob = journal._conn.execute(  # noqa: SLF001
        "SELECT payload FROM coordinator_shadow_journal WHERE id = ?", (a.id,)
    ).fetchone()[0]
    # Relocate A's ciphertext into B's row — AAD is bound to the row id, so B's
    # decrypt must fail (authentication), never silently return A's plaintext.
    journal._conn.execute(  # noqa: SLF001
        "UPDATE coordinator_shadow_journal SET payload = ? WHERE id = ?",
        (a_blob, b.id),
    )
    journal._conn.commit()  # noqa: SLF001
    with pytest.raises(ShadowJournalError):
        journal.list_entries(kind=KIND_DIGEST)


# ---------------------------------------------------------------------------
# Reads — ordering + filters
# ---------------------------------------------------------------------------


def test_list_entries_ordered_and_filtered(journal: ShadowJournal) -> None:
    journal.append(KIND_BOARD_MOVE, {"run_id": "r1"}, now=T0)
    journal.append(KIND_STALL_COMMENT, {"task_id": 1}, now=T0 + timedelta(minutes=1))
    journal.append(KIND_BOARD_MOVE, {"run_id": "r2"}, now=T0 + timedelta(minutes=2))

    moves = journal.list_entries(kind=KIND_BOARD_MOVE)
    assert [e.payload["run_id"] for e in moves] == ["r1", "r2"]  # oldest first
    assert journal.count(kind=KIND_BOARD_MOVE) == 2
    assert journal.count(kind=KIND_TRIPWIRE_ALARM) == 0


def test_list_entries_since_filter(journal: ShadowJournal) -> None:
    journal.append(KIND_DIGEST, {"cycle": "a"}, now=T0)
    journal.append(KIND_DIGEST, {"cycle": "b"}, now=T0 + timedelta(minutes=15))
    since = T0 + timedelta(minutes=1)
    got = journal.list_entries(kind=KIND_DIGEST, since=since)
    assert [e.payload["cycle"] for e in got] == ["b"]
    # An ISO string boundary (as previously returned) is inclusive.
    got_iso = journal.list_entries(since=journal.list_entries()[0].created_at)
    assert len(got_iso) == 2


def test_same_timestamp_entries_keep_append_order(journal: ShadowJournal) -> None:
    """Two entries with the SAME injected instant (one cycle journals several
    effects through one now_fn read) stay in append order via ``seq`` — the
    grading-stable sort key."""
    journal.append(KIND_PROPOSAL_COPY, {"n": 1}, now=T0)
    journal.append(KIND_PROPOSAL_COPY, {"n": 2}, now=T0)
    got = journal.list_entries(kind=KIND_PROPOSAL_COPY)
    assert [e.payload["n"] for e in got] == [1, 2]
    assert got[0].seq < got[1].seq


# ---------------------------------------------------------------------------
# Append-only surface (sanctioned-API writes, ADR-039 §2.1 item 10)
# ---------------------------------------------------------------------------


def test_public_surface_is_append_plus_reads_only() -> None:
    """The journal's public API is append + reads + close — no update, no
    transition, no removal method exists to call (append-only structurally,
    not by convention)."""
    public = {
        name
        for name in dir(ShadowJournal)
        if not name.startswith("_") and callable(getattr(ShadowJournal, name))
    }
    assert public == {"append", "list_entries", "count", "close"}


# ---------------------------------------------------------------------------
# Production wiring — refuse-to-start + encryption invariant + reopen
# ---------------------------------------------------------------------------


def test_refuse_to_start_in_production_without_keystore(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BLARAI_DEK_KEYSTORE", raising=False)
    db = str(tmp_path / "prod.db")
    with pytest.raises(StoreProvisioningError):
        build_shadow_journal(db, dev_mode=False)


def test_has_encryption_invariant() -> None:
    j = build_shadow_journal(":memory:")
    try:
        assert j.has_encryption is True
    finally:
        j.close()


def test_construct_requires_field_cipher() -> None:
    with pytest.raises(TypeError):
        ShadowJournal(db_path=":memory:", cipher=object())  # type: ignore[arg-type]


def test_reopen_across_dev_keystore_decrypts(tmp_path) -> None:
    """A fresh journal over the same DB + keystore (same DEK) still decrypts —
    the envelope is persisted, not per-process (mirrors the proposal store's
    reopen lock)."""
    db = str(tmp_path / "journal.db")
    j1 = build_shadow_journal(db, dev_mode=True)
    j1.append(KIND_TRIPWIRE_ALARM, {"detail": "3 Ready, nothing pulling"}, now=T0)
    j1.close()

    j2 = build_shadow_journal(db, dev_mode=True)
    try:
        got = j2.list_entries(kind=KIND_TRIPWIRE_ALARM)
        assert len(got) == 1
        assert got[0].payload["detail"] == "3 Ready, nothing pulling"
        assert isinstance(got[0], JournalEntry)
    finally:
        j2.close()
