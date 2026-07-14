"""Isolated tests for the born-encrypted coordinator proposal-staging store.

`shared/coordinator/proposal_store.py` (#844 C2 / #845 C3, ADR-039). The store has
NO live consumer yet — these tests exercise it in isolation, exactly as the unit was
scoped: encrypt/decrypt round-trip, born-encrypted-at-rest, AAD binding, dedup, TTL
expiry, crash-safe reconcile, fail-closed transitions, and the production
refuse-to-start posture.

All tests use the SoftwareSealer dev path (``:memory:`` or ``dev_mode=True``) — the
one-DEK envelope reuse and the TPM production path are exercised by the shared
crypto layer's own suites; here the focus is the STORE's behavior over that layer.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from shared.coordinator.proposal_store import (
    DEFAULT_PROPOSAL_TTL_DAYS,
    Proposal,
    ProposalLane,
    ProposalStatus,
    ProposalStore,
    ProposalStoreError,
    StoreProvisioningError,
    build_proposal_store,
    proposal_fingerprint,
)

T0 = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store():
    """An in-memory store (SoftwareSealer dev path); closed on teardown."""
    s = build_proposal_store(":memory:")
    try:
        yield s
    finally:
        s.close()


def _payload(**extra):
    base = {
        "goal": "redispatch run r-123 after PARKED-HONEST",
        "target": "coder-jobs/widget",
        "evidence": ["runs/r-123/SUMMARY.txt"],
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Round-trip + at-rest encryption + AAD binding
# ---------------------------------------------------------------------------


def test_add_draft_round_trip(store: ProposalStore) -> None:
    payload = _payload()
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint=proposal_fingerprint(
            proposal_class="redispatch", target="coder-jobs/widget", evidence_hash="h1"
        ),
        payload=payload,
        now=T0,
    )
    assert p.status is ProposalStatus.DRAFT
    assert p.lane is ProposalLane.WORKSPACE
    assert p.proposal_class == "redispatch"
    assert p.payload == payload  # decrypts identically
    assert p.created_at == "2026-07-12T12:00:00.000000+00:00"
    # expires_at defaults to created + TTL
    expected_exp = (T0 + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS)).isoformat(
        timespec="microseconds"
    )
    assert p.expires_at == expected_exp
    assert p.staged_at == ""

    fetched = store.get(p.id)
    assert fetched is not None
    assert fetched.payload == payload


def test_self_advisory_lane_preserved(store: ProposalStore) -> None:
    p = store.add_draft(
        lane=ProposalLane.SELF_ADVISORY,
        proposal_class="self_advisory",
        fingerprint="fp-self",
        payload={"note": "BlarAI's own backlog item"},
        now=T0,
    )
    assert store.get(p.id).lane is ProposalLane.SELF_ADVISORY  # type: ignore[union-attr]


def test_payload_is_encrypted_at_rest(store: ProposalStore) -> None:
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint="fp-1",
        payload=_payload(goal="SECRET-MARKER-goal-text"),
        now=T0,
    )
    raw = store._conn.execute(  # noqa: SLF001 - test reaches in to inspect at-rest bytes
        "SELECT payload FROM coordinator_proposals WHERE id = ?", (p.id,)
    ).fetchone()[0]
    assert isinstance(raw, (bytes, memoryview))
    raw_bytes = bytes(raw)
    # First byte is the field-cipher version, and the plaintext marker is absent.
    assert raw_bytes[0] == 0x01
    assert b"SECRET-MARKER-goal-text" not in raw_bytes


def test_fingerprint_not_stored_plaintext(store: ProposalStore) -> None:
    fp = proposal_fingerprint(
        proposal_class="redispatch",
        target="coder-jobs/confidential-repo",
        evidence_hash="h9",
    )
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint=fp,
        payload=_payload(),
        now=T0,
    )
    idx = store._conn.execute(  # noqa: SLF001
        "SELECT fingerprint_idx FROM coordinator_proposals WHERE id = ?", (p.id,)
    ).fetchone()[0]
    idx_bytes = bytes(idx)
    # The stored index is the 32-byte HMAC, not the raw fingerprint string.
    assert len(idx_bytes) == 32
    assert fp.encode("utf-8") not in idx_bytes
    assert b"confidential-repo" not in idx_bytes


def test_aad_binding_relocation_fails(store: ProposalStore) -> None:
    a = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint="fp-a",
        payload=_payload(goal="payload-A"),
        now=T0,
    )
    b = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint="fp-b",
        payload=_payload(goal="payload-B"),
        now=T0,
    )
    a_blob = store._conn.execute(  # noqa: SLF001
        "SELECT payload FROM coordinator_proposals WHERE id = ?", (a.id,)
    ).fetchone()[0]
    # Relocate A's ciphertext into B's row — AAD is bound to the row id, so B's
    # decrypt must fail (authentication), never silently return A's plaintext.
    store._conn.execute(  # noqa: SLF001
        "UPDATE coordinator_proposals SET payload = ? WHERE id = ?", (a_blob, b.id)
    )
    store._conn.commit()
    with pytest.raises(ProposalStoreError):
        store.get(b.id)


# ---------------------------------------------------------------------------
# Dedup (anti-firehose)
# ---------------------------------------------------------------------------


def test_dedup_same_fingerprint_returns_existing(store: ProposalStore) -> None:
    fp = proposal_fingerprint(
        proposal_class="stall", target="coder-jobs/widget", evidence_hash="h1"
    )
    first = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(),
        now=T0,
    )
    second = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(goal="different text, same condition"),
        now=T0 + timedelta(hours=1),
    )
    assert second.id == first.id  # same condition -> one proposal, not one per cycle
    assert len(store.list_active()) == 1


def test_dedup_active_across_staged(store: ProposalStore) -> None:
    fp = "fp-x"
    first = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(),
        now=T0,
    )
    store.mark_staged(first.id, now=T0)
    # Still active (STAGED) -> a re-detection dedups to the same proposal.
    again = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(),
        now=T0 + timedelta(hours=2),
    )
    assert again.id == first.id
    assert again.status is ProposalStatus.STAGED


def test_terminal_does_not_suppress_new_draft(store: ProposalStore) -> None:
    fp = "fp-recur"
    first = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(),
        now=T0,
    )
    store.mark_staged(first.id, now=T0)
    store.mark_rejected(first.id, now=T0)
    # A recurrence AFTER an operator decision is new work, not a dup.
    fresh = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(),
        now=T0 + timedelta(days=1),
    )
    assert fresh.id != first.id
    assert fresh.status is ProposalStatus.DRAFT


def test_find_active_by_fingerprint(store: ProposalStore) -> None:
    fp = "fp-find"
    assert store.find_active_by_fingerprint(fp) is None
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint=fp,
        payload=_payload(),
        now=T0,
    )
    found = store.find_active_by_fingerprint(fp)
    assert found is not None and found.id == p.id
    store.mark_staged(p.id, now=T0)
    store.mark_approved(p.id, now=T0)
    assert store.find_active_by_fingerprint(fp) is None  # terminal -> not active


def test_find_by_fingerprint_returns_full_history_oldest_first(
    store: ProposalStore,
) -> None:
    """The any-status sibling: terminal proposals stay visible (the C2 redispatch
    limb reads them to distinguish "never proposed" from "already decided")."""
    fp = "fp-history"
    assert store.find_by_fingerprint(fp) == []
    first = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch-parked",
        fingerprint=fp,
        payload=_payload(),
        now=T0,
    )
    store.mark_staged(first.id, now=T0)
    store.mark_rejected(first.id, now=T0)
    # Terminal-doesn't-suppress mints a second row under the same fingerprint.
    second = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch-parked",
        fingerprint=fp,
        payload=_payload(),
        now=T0 + timedelta(days=1),
    )
    history = store.find_by_fingerprint(fp)
    assert [p.id for p in history] == [first.id, second.id]  # oldest first
    assert history[0].status is ProposalStatus.REJECTED
    assert history[1].status is ProposalStatus.DRAFT


def test_find_by_fingerprint_isolates_fingerprints(store: ProposalStore) -> None:
    store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch-parked",
        fingerprint="fp-one",
        payload=_payload(),
        now=T0,
    )
    assert store.find_by_fingerprint("fp-other") == []


# ---------------------------------------------------------------------------
# TTL expiry + reconcile
# ---------------------------------------------------------------------------


def test_ttl_expiry_demotes_staged_to_draft(store: ProposalStore) -> None:
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-ttl",
        payload=_payload(),
        now=T0,
    )
    store.mark_staged(p.id, now=T0)
    # Not yet expired: a run just after staging demotes nothing.
    assert store.expire_stale(now=T0 + timedelta(seconds=1)) == 0
    assert store.get(p.id).status is ProposalStatus.STAGED  # type: ignore[union-attr]
    # Past TTL: demoted back to DRAFT with a note.
    past = T0 + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS, seconds=1)
    assert store.expire_stale(now=past) == 1
    demoted = store.get(p.id)
    assert demoted is not None
    assert demoted.status is ProposalStatus.DRAFT
    assert "TTL-expired" in demoted.system_note


def test_expire_stale_is_idempotent(store: ProposalStore) -> None:
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-idem",
        payload=_payload(),
        now=T0,
    )
    store.mark_staged(p.id, now=T0)
    past = T0 + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS, seconds=1)
    assert store.expire_stale(now=past) == 1
    assert store.expire_stale(now=past) == 0  # already demoted -> no-op


def test_expire_stale_ignores_drafts_and_terminals(store: ProposalStore) -> None:
    draft = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-draft",
        payload=_payload(),
        now=T0,
    )
    approved = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-appr",
        payload=_payload(),
        now=T0,
    )
    store.mark_staged(approved.id, now=T0)
    store.mark_approved(approved.id, now=T0)
    # Long past any TTL — but only STAGED items are demoted.
    assert store.expire_stale(now=T0 + timedelta(days=365)) == 0
    assert store.get(draft.id).status is ProposalStatus.DRAFT  # type: ignore[union-attr]
    assert store.get(approved.id).status is ProposalStatus.APPROVED  # type: ignore[union-attr]


def test_mark_staged_restarts_ttl(store: ProposalStore) -> None:
    # A proposal created at T0 but not staged until later gets its TTL from the
    # staging moment, not creation (un-actioned-since-surfaced semantics).
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-restart",
        payload=_payload(),
        now=T0,
    )
    stage_time = T0 + timedelta(days=5)
    staged = store.mark_staged(p.id, now=stage_time)
    assert staged.staged_at == stage_time.isoformat(timespec="microseconds")
    assert staged.expires_at == (
        stage_time + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS)
    ).isoformat(timespec="microseconds")
    # Original created+TTL would already be past, but the restarted TTL protects it.
    assert store.expire_stale(now=T0 + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS + 1)) == 0


def test_reconcile_at_boot_applies_ttl_across_reopen(tmp_path) -> None:
    db = str(tmp_path / "proposals.db")
    s1 = build_proposal_store(db, dev_mode=True)
    p = s1.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-boot",
        payload=_payload(),
        now=T0,
    )
    s1.mark_staged(p.id, now=T0)
    s1.close()

    # "Reboot": a fresh store over the same DB + keystore (same DEK) reconciles.
    s2 = build_proposal_store(db, dev_mode=True)
    try:
        past = T0 + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS, seconds=1)
        result = s2.reconcile_at_boot(now=past)
        assert result.demoted == 1
        assert s2.get(p.id).status is ProposalStatus.DRAFT  # type: ignore[union-attr]
        # Idempotent: a second reconcile at the same instant demotes nothing.
        assert s2.reconcile_at_boot(now=past).demoted == 0
        # And it can still decrypt the reopened payload (shared DEK via keystore).
        assert s2.get(p.id).payload["goal"] == _payload()["goal"]  # type: ignore[union-attr]
    finally:
        s2.close()


# ---------------------------------------------------------------------------
# Transitions — fail-closed
# ---------------------------------------------------------------------------


def test_illegal_transition_raises(store: ProposalStore) -> None:
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="stall",
        fingerprint="fp-trans",
        payload=_payload(),
        now=T0,
    )
    # Can't approve a DRAFT that was never staged.
    with pytest.raises(ProposalStoreError):
        store.mark_approved(p.id, now=T0)
    store.mark_staged(p.id, now=T0)
    store.mark_approved(p.id, now=T0)
    # Terminal -> any further transition refused.
    with pytest.raises(ProposalStoreError):
        store.mark_rejected(p.id, now=T0)


def test_unknown_id_transition_raises(store: ProposalStore) -> None:
    with pytest.raises(ProposalStoreError):
        store.mark_staged("does-not-exist", now=T0)


def test_get_unknown_returns_none(store: ProposalStore) -> None:
    assert store.get("nope") is None


# ---------------------------------------------------------------------------
# Reads / listing
# ---------------------------------------------------------------------------


def test_list_active_and_by_status(store: ProposalStore) -> None:
    d = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="c",
        fingerprint="fp-la-1",
        payload=_payload(),
        now=T0,
    )
    s = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="c",
        fingerprint="fp-la-2",
        payload=_payload(),
        now=T0 + timedelta(seconds=1),
    )
    store.mark_staged(s.id, now=T0)
    a = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="c",
        fingerprint="fp-la-3",
        payload=_payload(),
        now=T0 + timedelta(seconds=2),
    )
    store.mark_staged(a.id, now=T0)
    store.mark_approved(a.id, now=T0)

    active_ids = {p.id for p in store.list_active()}
    assert active_ids == {d.id, s.id}  # DRAFT + STAGED, not the APPROVED
    assert [p.id for p in store.list_by_status(ProposalStatus.APPROVED)] == [a.id]


# ---------------------------------------------------------------------------
# Fingerprint helper
# ---------------------------------------------------------------------------


def test_proposal_fingerprint_deterministic_and_distinct() -> None:
    a = proposal_fingerprint(proposal_class="stall", target="r1", evidence_hash="h1")
    b = proposal_fingerprint(proposal_class="stall", target="r1", evidence_hash="h1")
    c = proposal_fingerprint(proposal_class="stall", target="r2", evidence_hash="h1")
    assert a == b
    assert a != c
    assert len(a) == 64 and all(ch in "0123456789abcdef" for ch in a)


def test_fingerprint_field_boundaries_unambiguous() -> None:
    # NUL-separated hashing means "a" + "bc" and "ab" + "c" don't collide.
    left = proposal_fingerprint(proposal_class="a", target="bc", evidence_hash="x")
    right = proposal_fingerprint(proposal_class="ab", target="c", evidence_hash="x")
    assert left != right


# ---------------------------------------------------------------------------
# Production wiring — refuse-to-start + encryption invariant
# ---------------------------------------------------------------------------


def test_has_encryption_invariant() -> None:
    s = build_proposal_store(":memory:")
    try:
        assert s.has_encryption is True
    finally:
        s.close()


def test_refuse_to_start_in_production_without_keystore(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BLARAI_DEK_KEYSTORE", raising=False)
    db = str(tmp_path / "prod.db")
    with pytest.raises(StoreProvisioningError):
        build_proposal_store(db, dev_mode=False)


def test_ttl_days_must_be_positive() -> None:
    with pytest.raises(ValueError):
        build_proposal_store(":memory:", ttl_days=0)


def test_construct_requires_field_cipher() -> None:
    with pytest.raises(TypeError):
        ProposalStore(db_path=":memory:", cipher=object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extend_ttl — the sanctioned operator-absence TTL pause (#845 C3, design §8.2)
# ---------------------------------------------------------------------------


def _staged(store: ProposalStore, fingerprint: str, now: datetime):
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint=fingerprint,
        payload=_payload(),
        now=now,
    )
    return store.mark_staged(p.id, now=now)


def test_extend_ttl_extends_staged_only(store: ProposalStore) -> None:
    staged = _staged(store, "fp-staged", T0)
    draft = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint="fp-draft",
        payload=_payload(),
        now=T0,
    )
    approved = _staged(store, "fp-approved", T0)
    store.mark_approved(approved.id, now=T0)

    extended = store.extend_ttl(delta=timedelta(days=3), now=T0 + timedelta(days=1))
    assert extended == 1  # ONLY the STAGED proposal

    assert store.get(draft.id).expires_at == draft.expires_at  # DRAFT untouched
    assert store.get(approved.id).expires_at == approved.expires_at  # terminal untouched
    new_expires = store.get(staged.id).expires_at
    assert new_expires > staged.expires_at
    assert "TTL paused for operator absence" in store.get(staged.id).system_note


def test_extend_ttl_survives_the_old_deadline_but_not_the_new(store: ProposalStore) -> None:
    """The pause is real AND finite: the old deadline no longer demotes; the
    extended one still does."""
    _staged(store, "fp-pause", T0)
    old_deadline = T0 + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS, hours=1)
    store.extend_ttl(delta=timedelta(days=5), now=T0 + timedelta(days=2))
    assert store.expire_stale(now=old_deadline) == 0  # paused past the old deadline
    assert store.expire_stale(now=old_deadline + timedelta(days=5)) == 1  # finite


def test_extend_ttl_non_positive_delta_is_a_no_op(store: ProposalStore) -> None:
    staged = _staged(store, "fp-neg", T0)
    assert store.extend_ttl(delta=timedelta(0), now=T0) == 0
    assert store.extend_ttl(delta=timedelta(seconds=-30), now=T0) == 0
    assert store.get(staged.id).expires_at == staged.expires_at  # unchanged
