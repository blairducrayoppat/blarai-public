"""
Knowledge-bank operator-preference store (#770 M1) — P2/P4/P5/P6/P7 locks.
===========================================================================
Drives the REAL ``EncryptedKnowledgeBank`` (in-memory SQLite, real
``FieldCipher``) — no mocks on the store side, mirroring
``test_knowledge_bank.py``.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from services.assistant_orchestrator.src.knowledge_bank import (
    DEFAULT_PREFERENCE_TYPE_TAG,
    EMBED_DIM,
    EncryptedKnowledgeBank,
    KnowledgeBankError,
    PREFERENCE_TYPE_TAGS,
)
from shared.preference_budgets import (
    PREFERENCE_BODY_MAX_CHARS,
    PREFERENCE_MAX_COUNT,
)
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


def fake_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    out[:, 0] = 1.0
    return out


def _make_cipher() -> FieldCipher:
    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    return FieldCipher(derive_subkeys(env.unseal_dek()))


@pytest.fixture()
def bank() -> EncryptedKnowledgeBank:
    b = EncryptedKnowledgeBank(
        db_path=":memory:", embed_fn=fake_embed, cipher=_make_cipher()
    )
    yield b
    b.close()


# ---------------------------------------------------------------------------
# P2 — verbatim capture
# ---------------------------------------------------------------------------


class TestVerbatimCapture:
    def test_body_round_trips_byte_identical(self, bank) -> None:
        body = "Always call me Blair — never 'user', never 'sir'.  Metric units."
        stored = bank.store_preference(body)
        assert stored.body == body
        (listed,) = bank.list_preferences()
        assert listed.body == body  # decrypted round-trip, byte-identical

    def test_body_with_unicode_and_padding_survives_exactly(self, bank) -> None:
        body = "réponds-moi   en    français\t(toujours) — même à 3h du matin"
        stored = bank.store_preference(body)
        assert bank.list_preferences()[0].body == body
        assert stored.body == body

    def test_store_never_trims_interior_whitespace(self, bank) -> None:
        body = "spacing   is    meaningful"
        bank.store_preference(body)
        assert bank.list_preferences()[0].body == body

    def test_default_type_tag(self, bank) -> None:
        stored = bank.store_preference("always use metric")
        assert stored.type_tag == DEFAULT_PREFERENCE_TYPE_TAG

    def test_known_type_tags_kept(self, bank) -> None:
        for tag in sorted(PREFERENCE_TYPE_TAGS):
            stored = bank.store_preference(f"pref for {tag}", type_tag=tag)
            assert stored.type_tag == tag

    def test_unknown_type_tag_coerces_cosmetically_never_lossy(self, bank) -> None:
        stored = bank.store_preference("call me Blair", type_tag="banana")
        assert stored.type_tag == DEFAULT_PREFERENCE_TYPE_TAG
        assert stored.body == "call me Blair"  # the body is untouched


# ---------------------------------------------------------------------------
# Born-encrypted at rest (P7 — the same substrate discipline)
# ---------------------------------------------------------------------------


class TestBornEncrypted:
    def test_body_is_ciphertext_on_disk(self, tmp_path) -> None:
        db_path = str(tmp_path / "knowledge.db")
        secret = "my NAS password hint is the dog's birthday"
        bank = EncryptedKnowledgeBank(
            db_path=db_path, embed_fn=fake_embed, cipher=_make_cipher()
        )
        try:
            bank.store_preference(secret)
        finally:
            bank.close()
        raw = sqlite3.connect(db_path)
        try:
            (blob,) = raw.execute(
                "SELECT body FROM operator_preferences"
            ).fetchone()
        finally:
            raw.close()
        assert isinstance(blob, bytes)
        assert secret.encode("utf-8") not in blob

    def test_wrong_row_ciphertext_quarantined_not_returned(self, bank) -> None:
        # Relocating one row's body blob onto another row must fail AAD
        # authentication and quarantine the row (never plaintext, never crash).
        a = bank.store_preference("preference A")
        b = bank.store_preference("preference B")
        blob_a = bank._conn.execute(
            "SELECT body FROM operator_preferences WHERE pref_id=?", (a.pref_id,)
        ).fetchone()[0]
        with bank._conn:
            bank._conn.execute(
                "UPDATE operator_preferences SET body=? WHERE pref_id=?",
                (blob_a, b.pref_id),
            )
        listed = bank.list_preferences()
        assert [p.pref_id for p in listed] == [a.pref_id]  # B quarantined


# ---------------------------------------------------------------------------
# P4 — the store-side caps (char + count) refuse loudly
# ---------------------------------------------------------------------------


class TestCaps:
    def test_empty_body_refused(self, bank) -> None:
        with pytest.raises(KnowledgeBankError, match="PREFERENCE_EMPTY"):
            bank.store_preference("   ")

    def test_body_at_cap_accepted(self, bank) -> None:
        bank.store_preference("x" * PREFERENCE_BODY_MAX_CHARS)
        assert bank.count_preferences() == 1

    def test_body_over_cap_refused(self, bank) -> None:
        with pytest.raises(KnowledgeBankError, match="PREFERENCE_BODY_TOO_LONG"):
            bank.store_preference("x" * (PREFERENCE_BODY_MAX_CHARS + 1))

    def test_count_cap_refuses_the_65th(self, bank) -> None:
        for i in range(PREFERENCE_MAX_COUNT):
            bank.store_preference(f"preference number {i}")
        with pytest.raises(KnowledgeBankError, match="PREFERENCE_COUNT_CAP"):
            bank.store_preference("one too many")
        assert bank.count_preferences() == PREFERENCE_MAX_COUNT

    def test_delete_frees_count_capacity(self, bank) -> None:
        for i in range(PREFERENCE_MAX_COUNT):
            bank.store_preference(f"preference number {i}")
        victim = bank.list_preferences()[0]
        assert bank.delete_preference(victim.pref_id)
        bank.store_preference("fits again after a delete")
        assert bank.count_preferences() == PREFERENCE_MAX_COUNT

    def test_edit_over_char_cap_refused(self, bank) -> None:
        stored = bank.store_preference("short")
        with pytest.raises(KnowledgeBankError, match="PREFERENCE_BODY_TOO_LONG"):
            bank.update_preference(
                stored.pref_id, "x" * (PREFERENCE_BODY_MAX_CHARS + 1)
            )
        assert bank.list_preferences()[0].body == "short"  # unchanged


# ---------------------------------------------------------------------------
# P5 — update-in-place, last-writer-wins, audit trail
# ---------------------------------------------------------------------------


class TestUpdateAndAudit:
    def test_edit_wins_and_keeps_id_and_created(self, bank) -> None:
        stored = bank.store_preference("call me Bob")
        updated = bank.update_preference(stored.pref_id, "call me Blair")
        assert updated is not None
        assert updated.pref_id == stored.pref_id       # stable id (P9)
        assert updated.created == stored.created        # stable order key
        assert updated.body == "call me Blair"
        (active,) = bank.list_preferences()
        assert active.body == "call me Blair"           # last writer wins

    def test_prior_verbatim_body_kept_as_superseded_audit(self, bank) -> None:
        stored = bank.store_preference("call me Bob")
        bank.update_preference(stored.pref_id, "call me Blair")
        history = bank.list_preferences(include_history=True)
        superseded = [p for p in history if p.status == "superseded"]
        assert len(superseded) == 1
        assert superseded[0].body == "call me Bob"       # verbatim audit
        assert superseded[0].supersedes == stored.pref_id

    def test_audit_rows_never_render_or_count(self, bank) -> None:
        stored = bank.store_preference("call me Bob")
        bank.update_preference(stored.pref_id, "call me Blair")
        assert bank.count_preferences() == 1
        assert [p.body for p in bank.list_preferences()] == ["call me Blair"]

    def test_edit_unknown_id_returns_none(self, bank) -> None:
        assert bank.update_preference("f" * 32, "whatever") is None

    def test_delete_is_soft_and_idempotent(self, bank) -> None:
        stored = bank.store_preference("temporary rule")
        assert bank.delete_preference(stored.pref_id) is True
        assert bank.delete_preference(stored.pref_id) is False  # already gone
        assert bank.count_preferences() == 0
        history = bank.list_preferences(include_history=True)
        assert [p.status for p in history] == ["deleted"]
        assert history[0].body == "temporary rule"       # audit retained

    def test_editing_a_deleted_row_refused(self, bank) -> None:
        stored = bank.store_preference("temporary rule")
        bank.delete_preference(stored.pref_id)
        assert bank.update_preference(stored.pref_id, "resurrect") is None


# ---------------------------------------------------------------------------
# P5 — deterministic similarity probe (the confirm seam's signal)
# ---------------------------------------------------------------------------


class TestSimilarityProbe:
    def test_near_duplicate_found(self, bank) -> None:
        stored = bank.store_preference("always use metric units")
        hit = bank.find_similar_preference("always use metric units please")
        assert hit is not None and hit.pref_id == stored.pref_id

    def test_exact_duplicate_found(self, bank) -> None:
        stored = bank.store_preference("call me Blair")
        hit = bank.find_similar_preference("call me Blair")
        assert hit is not None and hit.pref_id == stored.pref_id

    def test_unrelated_body_not_flagged(self, bank) -> None:
        bank.store_preference("always use metric units")
        assert bank.find_similar_preference("respond in French") is None

    def test_deleted_rows_never_conflict(self, bank) -> None:
        stored = bank.store_preference("always use metric units")
        bank.delete_preference(stored.pref_id)
        assert bank.find_similar_preference("always use metric units") is None


# ---------------------------------------------------------------------------
# P6 (no decay) + P9 (deterministic order)
# ---------------------------------------------------------------------------


class TestOrderAndNonDecay:
    def test_list_order_is_insertion_order_and_stable(self, bank) -> None:
        # Same-clock-tick stores MUST keep operator issue order (the rowid,
        # not the created timestamp, is the sort key — timestamp collisions
        # under a fast writer were exactly the defect this test caught).
        bodies = [f"preference {i}" for i in range(5)]
        for body in bodies:
            bank.store_preference(body)
        first = [p.pref_id for p in bank.list_preferences()]
        second = [p.pref_id for p in bank.list_preferences()]
        assert first == second  # deterministic across calls
        assert [p.body for p in bank.list_preferences()] == bodies  # append order

    def test_same_tick_rows_keep_insertion_order_not_id_order(self, bank) -> None:
        """Regression lock for the same-tick ordering defect (builder-caught).

        The weak version of this lock stored rows whose ``created`` stamps
        happened to differ, so a regression back to the old
        ``(created, pref_id)`` sort key would still have passed (review N2,
        #770 c.1550).  This lock manufactures the exact collision: identical
        ``created`` on every row AND a pref_id set whose lexicographic order
        CONTRADICTS insertion order — so the old key produces a detectably
        wrong list, deterministically.  pref_id itself is never rewritten
        (it is the AAD row identity; rewriting would quarantine the row).
        """
        first = second = None
        for _ in range(20):  # uuid order contradicts insertion ~50% per draw
            a = bank.store_preference("first of the tick")
            b = bank.store_preference("second of the tick")
            if b.pref_id < a.pref_id:
                first, second = a, b
                break
            bank.delete_preference(a.pref_id)
            bank.delete_preference(b.pref_id)
        assert first is not None, (
            "could not draw pref_ids whose lexicographic order contradicts "
            "insertion order in 20 batches (P ~ 2**-20) — investigate the "
            "pref_id generator before weakening this lock"
        )
        same_tick = "2026-07-09T21:00:00+00:00"
        with bank._conn:
            bank._conn.execute(
                "UPDATE operator_preferences SET created=?, updated=?",
                (same_tick, same_tick),
            )
        listed = [p.body for p in bank.list_preferences()]
        assert listed == ["first of the tick", "second of the tick"], (
            "same-created rows came back in pref_id order, not insertion "
            "order — the (created, pref_id) sort key regressed (must be rowid)"
        )

    def test_ancient_preferences_still_active_no_decay(self, bank) -> None:
        stored = bank.store_preference("call me Blair")
        # Simulate a preference written years ago: no code path may read the
        # timestamp as a decay signal — backdate it and assert full presence.
        with bank._conn:
            bank._conn.execute(
                "UPDATE operator_preferences SET created=?, updated=? "
                "WHERE pref_id=?",
                ("2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00",
                 stored.pref_id),
            )
        listed = bank.list_preferences()
        assert [p.body for p in listed] == ["call me Blair"]
        assert bank.count_preferences() == 1

    def test_expiry_is_operator_stated_only_never_system_decay(self, bank) -> None:
        # #770 M2 W2 (D-4) refines P6: an `expires` column EXISTS, but it is
        # nullable and ONLY the operator ever sets it — the SYSTEM never imposes a
        # decay/TTL, and nothing is auto-deleted. So there is no decay/ttl column,
        # and a preference stored without a stated expiry carries NONE.
        cols = {
            str(r[1])
            for r in bank._conn.execute(
                "PRAGMA table_info(operator_preferences)"
            ).fetchall()
        }
        assert not (cols & {"decay", "ttl"}), (
            "P6: the SYSTEM never decays a preference — no decay/ttl column"
        )
        assert "expires" in cols  # the operator's OWN stated bound (D-4)
        stored = bank.store_preference("call me Blair")
        assert stored.expires == ""             # no expiry unless the operator states one
        assert bank.list_preferences()[0].expires == ""
