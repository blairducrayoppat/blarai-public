"""
Tests for the Encrypted Knowledge Bank (UC-002 Substrate v2, Vikunja #655).

Uses deterministic stub embedders (no ONNX model required — worktree-safe):
  * ``fake_embed`` — bag-of-words (shared words → similar vectors) for
    vector-limb relevance tests.
  * ``constant_embed`` — identical vector for every text, making cosine
    non-informative, to prove the FTS5 lexical limb contributes on its own.

Covers: schema/meta/WAL, encryption-on-disk (no plaintext), submit/approve/
reject lifecycle, dedup-over-ciphertext semantics (pending-replace /
approved-already-ingested / rejected-replace), hybrid retrieval (cosine +
BM25 + reciprocal-rank fusion), incremental FTS add on approve, persistence
across reopen, and decrypt-quarantine on bulk reads.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import uuid
import zlib
from pathlib import Path

import numpy as np
import pytest

from services.assistant_orchestrator.src.knowledge_bank import (
    EncryptedKnowledgeBank,
    KnowledgeBankError,
    _fts_match_expr,
)
from services.assistant_orchestrator.src.substrate import EMBED_DIM
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words embedder: shared words → similar vectors."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


def constant_embed(texts: list[str]) -> np.ndarray:
    """Identical unit vector for every text — cosine is non-informative."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    out[:, 0] = 1.0
    return out


# Vector-limb lock fixtures (#655 review FIX 5): the query and target share
# ZERO indexable words (BM25-invisible) while their pinned vectors are
# identical — only the cosine limb can surface the target.
_VEC_QUERY = "ornithopter wing oscillation cadence"
_VEC_TARGET = "submarine ballast chambers regulate buoyancy depth underwater"
_VEC_DECOY = "sourdough fermentation schedule hydration ratio crumb texture"


def pinned_embed(texts: list[str]) -> np.ndarray:
    """Map specific texts to predetermined unit vectors.

    The query and the target doc share axis 0 (cosine 1.0); the decoy is
    orthogonal; anything else lands on a third axis.  The mirror of
    ``constant_embed``: that stub proves the lexical limb alone can rank,
    this one proves the VECTOR limb alone can rank.
    """
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        key = t.strip()
        if key in (_VEC_QUERY, _VEC_TARGET):
            out[i, 0] = 1.0
        elif key == _VEC_DECOY:
            out[i, 1] = 1.0
        else:
            out[i, 2] = 1.0
    return out


def _make_cipher() -> FieldCipher:
    sealer = SoftwareSealer()
    env = DekEnvelope.create(sealer=sealer, recovery_key=generate_recovery_key())
    return FieldCipher(derive_subkeys(env.unseal_dek()))


def _make_bank(
    db_path: str = ":memory:",
    cipher: FieldCipher | None = None,
    embed_fn=fake_embed,
) -> EncryptedKnowledgeBank:
    return EncryptedKnowledgeBank(
        db_path=db_path,
        embed_fn=embed_fn,
        cipher=cipher if cipher is not None else _make_cipher(),
    )


def _submit(bank: EncryptedKnowledgeBank, **overrides):
    """Submit a representative pending article, returning the result."""
    kwargs = dict(
        doc_uuid=str(uuid.uuid4()),
        source_type="url",
        source_ref="https://example.org/articles/turbo-engines",
        content=(
            "Turbochargers compress intake air so the engine burns more fuel "
            "per cycle, raising power output without enlarging displacement."
        ),
        title="How turbochargers work",
        byline="A. Writer",
        published_date="2026-06-01",
        cleaner_version="cleaner-v1",
        word_count=24,
    )
    kwargs.update(overrides)
    return bank.submit_pending(**kwargs)


@pytest.fixture()
def bank() -> EncryptedKnowledgeBank:
    b = _make_bank()
    yield b
    b.close()


# ---------------------------------------------------------------------------
# 1. Construction / schema / WAL / regression locks
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_has_encryption_class_level_lock(self) -> None:
        assert EncryptedKnowledgeBank.has_encryption is True

    def test_requires_field_cipher(self) -> None:
        with pytest.raises(TypeError):
            EncryptedKnowledgeBank(
                db_path=":memory:", embed_fn=fake_embed, cipher="not-a-cipher"  # type: ignore[arg-type]
            )

    def test_meta_rows_written(self, bank: EncryptedKnowledgeBank) -> None:
        meta = dict(
            bank._conn.execute("SELECT key, value FROM knowledge_meta").fetchall()
        )
        assert meta["embed_dim"] == str(EMBED_DIM)
        assert meta["embed_model"] == "bge-small-en-v1.5"
        assert meta["embed_max_tokens"] == "512"
        assert meta["schema_version"] == "1"

    def test_wal_mode_on_for_file_backed_store(self, tmp_path: Path) -> None:
        """WAL is the deliberate divergence from substrate.db — lock it."""
        b = _make_bank(db_path=str(tmp_path / "knowledge.db"))
        try:
            mode = b._conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"
        finally:
            b.close()

    def test_empty_bank_counts_zero(self, bank: EncryptedKnowledgeBank) -> None:
        assert bank.count() == 0
        assert bank.chunk_count() == 0
        assert bank.retrieve("anything") == []


# ---------------------------------------------------------------------------
# 2. Submit (pending) + encryption at rest
# ---------------------------------------------------------------------------


class TestSubmitPending:
    def test_submit_creates_pending_row(self, bank: EncryptedKnowledgeBank) -> None:
        result = _submit(bank)
        assert result.state == "pending"
        assert result.replaced_prior is False
        assert len(result.source_hash_hex) == 64  # 32-byte HMAC hex
        assert bank.count("pending") == 1
        assert bank.count("approved") == 0

    def test_pending_row_has_no_chunks(self, bank: EncryptedKnowledgeBank) -> None:
        _submit(bank)
        assert bank.chunk_count() == 0

    def test_pending_not_retrievable(self, bank: EncryptedKnowledgeBank) -> None:
        _submit(bank)
        assert bank.retrieve("turbochargers engine power") == []

    def test_get_doc_round_trips_fields(self, bank: EncryptedKnowledgeBank) -> None:
        result = _submit(bank)
        doc = bank.get_doc(result.doc_uuid)
        assert doc.source_type == "url"
        assert doc.source_ref == "https://example.org/articles/turbo-engines"
        assert doc.title == "How turbochargers work"
        assert doc.byline == "A. Writer"
        assert doc.published_date == "2026-06-01"
        assert "Turbochargers compress" in doc.content
        assert doc.approval_state == "pending"
        assert doc.word_count == 24
        assert doc.cleaner_version == "cleaner-v1"
        assert doc.decided_at is None
        # KEYED fingerprint (32-byte HMAC hex) — and provably NOT the
        # plaintext sha (membership-oracle close, #655 LA verdict 2026-06-10).
        assert len(doc.content_sha256_keyed) == 64
        plaintext_sha = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
        assert doc.content_sha256_keyed != plaintext_sha

    def test_invalid_source_type_raises(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError):
            _submit(bank, source_type="carrier-pigeon")

    def test_empty_content_raises(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError):
            _submit(bank, content="   ")

    def test_empty_source_ref_raises(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError):
            _submit(bank, source_ref="")

    def test_no_plaintext_on_disk(self, tmp_path: Path) -> None:
        """source_ref / title / byline / content are ciphertext in raw bytes."""
        db = str(tmp_path / "knowledge.db")
        b = _make_bank(db_path=db)
        result = _submit(b)
        b.approve(result.doc_uuid)
        b.close()  # closes WAL → checkpoint into the main file

        raw = Path(db).read_bytes()
        for sample in (
            b"Turbochargers compress intake air",
            b"https://example.org/articles/turbo-engines",
            b"How turbochargers work",
            b"A. Writer",
        ):
            assert sample not in raw, f"plaintext leaked to disk: {sample!r}"

    def test_published_date_plaintext_by_design(self, tmp_path: Path) -> None:
        """published_date is a deliberate plaintext metadata column (the full
        honest plaintext-column enumeration lives in DATA_MAP.md row 8)."""
        db = str(tmp_path / "knowledge.db")
        b = _make_bank(db_path=db)
        _submit(b, published_date="2026-06-01")
        b.close()
        assert b"2026-06-01" in Path(db).read_bytes()

    def test_content_fingerprint_keyed_on_disk_not_plaintext_sha(
        self, tmp_path: Path
    ) -> None:
        """Membership-oracle close (#655 LA verdict 2026-06-10): the raw DB
        bytes must NOT contain the plaintext SHA-256 of the ingested content
        (an attacker with the stolen file could hash any public article
        through the deterministic cleaner and test membership); the KEYED
        form must be what is actually stored."""
        db = str(tmp_path / "knowledge.db")
        b = _make_bank(db_path=db)
        content = (
            "Turbochargers compress intake air so the engine burns more fuel "
            "per cycle, raising power output without enlarging displacement."
        )
        _submit(b, content=content)
        plaintext_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        keyed = b.content_digest_keyed(plaintext_sha)
        b.close()  # checkpoint WAL into the main file

        raw = Path(db).read_bytes()
        # The plaintext digest must be absent in every storable spelling.
        assert plaintext_sha.encode("ascii") not in raw
        assert plaintext_sha.upper().encode("ascii") not in raw
        assert bytes.fromhex(plaintext_sha) not in raw
        # The keyed form IS the stored fingerprint.
        assert keyed in raw

    def test_keyed_content_digest_is_deterministic_and_key_bound(self) -> None:
        """Same digest + same key → same index; different key → different
        index (the property that denies offline membership testing)."""
        content = "an article body"
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        cipher_a = _make_cipher()
        bank_a = _make_bank(cipher=cipher_a)
        bank_b = _make_bank(cipher=_make_cipher())
        try:
            assert bank_a.content_digest_keyed(sha) == cipher_a.keyed_index(
                sha.encode("utf-8")
            )
            assert bank_a.content_digest_keyed(sha) == bank_a.content_digest_keyed(
                sha.upper()  # case-normalised input
            )
            assert bank_a.content_digest_keyed(sha) != bank_b.content_digest_keyed(
                sha
            )
        finally:
            bank_a.close()
            bank_b.close()


# ---------------------------------------------------------------------------
# 3. Dedup-over-ciphertext semantics
# ---------------------------------------------------------------------------


class TestDedup:
    def test_resubmit_replaces_pending(self, bank: EncryptedKnowledgeBank) -> None:
        first = _submit(bank, content="first fetch of the article body words")
        second = _submit(bank, content="refreshed fetch with corrected body words")
        assert second.state == "pending"
        assert second.replaced_prior is True
        assert bank.count() == 1  # replaced, not duplicated
        doc = bank.get_doc(second.doc_uuid)
        assert "refreshed fetch" in doc.content
        with pytest.raises(KnowledgeBankError):
            bank.get_doc(first.doc_uuid)  # prior row is gone

    def test_resubmit_approved_returns_already_ingested(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        first = _submit(bank)
        bank.approve(first.doc_uuid)
        second = _submit(bank, content="a totally different body of words")
        assert second.state == "already_ingested"
        assert second.doc_uuid == first.doc_uuid  # points at the approved doc
        assert second.replaced_prior is False
        assert bank.count() == 1
        # The approved document is untouched.
        assert "Turbochargers compress" in bank.get_doc(first.doc_uuid).content

    def test_resubmit_rejected_replaces_tombstone(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        first = _submit(bank)
        bank.reject(first.doc_uuid)
        second = _submit(bank, content="second attempt at the same source words")
        assert second.state == "pending"
        assert second.replaced_prior is True
        assert bank.count() == 1
        assert bank.count("rejected") == 0

    def test_different_sources_do_not_collide(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        _submit(bank, source_ref="https://example.org/a")
        _submit(bank, source_ref="https://example.org/b")
        assert bank.count("pending") == 2

    def test_doc_uuid_reuse_is_a_caller_bug(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        first = _submit(bank, source_ref="https://example.org/a")
        with pytest.raises(KnowledgeBankError):
            _submit(
                bank,
                doc_uuid=first.doc_uuid,
                source_ref="https://example.org/different",
            )


# ---------------------------------------------------------------------------
# 4. Approve / reject lifecycle
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_approve_chunks_and_flips_state(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        result = _submit(bank)
        n = bank.approve(result.doc_uuid)
        assert n >= 1
        assert bank.chunk_count() == n
        doc = bank.get_doc(result.doc_uuid)
        assert doc.approval_state == "approved"
        assert doc.decided_at is not None

    def test_approve_long_content_multiple_chunks(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        long_content = " ".join(f"sentence{i} about widgets" for i in range(400))
        result = _submit(bank, content=long_content)
        n = bank.approve(result.doc_uuid)
        assert n > 1
        assert bank.chunk_count() == n

    def test_approve_unknown_uuid_raises(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError):
            bank.approve(str(uuid.uuid4()))

    def test_approve_idempotent(self, bank: EncryptedKnowledgeBank) -> None:
        result = _submit(bank)
        n1 = bank.approve(result.doc_uuid)
        n2 = bank.approve(result.doc_uuid)
        assert n1 == n2
        assert bank.chunk_count() == n1  # no duplicate chunks

    def test_approve_rejected_doc_raises(self, bank: EncryptedKnowledgeBank) -> None:
        result = _submit(bank)
        bank.reject(result.doc_uuid)
        with pytest.raises(KnowledgeBankError):
            bank.approve(result.doc_uuid)

    def test_reject_retains_content_tombstone(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        result = _submit(bank)
        bank.reject(result.doc_uuid)
        doc = bank.get_doc(result.doc_uuid)
        assert doc.approval_state == "rejected"
        assert "Turbochargers compress" in doc.content  # retained, not scrubbed
        assert doc.decided_at is not None
        assert bank.chunk_count() == 0

    def test_reject_idempotent(self, bank: EncryptedKnowledgeBank) -> None:
        result = _submit(bank)
        bank.reject(result.doc_uuid)
        bank.reject(result.doc_uuid)  # no raise
        assert bank.count("rejected") == 1

    def test_reject_approved_doc_raises(self, bank: EncryptedKnowledgeBank) -> None:
        result = _submit(bank)
        bank.approve(result.doc_uuid)
        with pytest.raises(KnowledgeBankError):
            bank.reject(result.doc_uuid)

    def test_reject_unknown_uuid_raises(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError):
            bank.reject(str(uuid.uuid4()))

    def test_list_pending(self, bank: EncryptedKnowledgeBank) -> None:
        a = _submit(bank, source_ref="https://example.org/a")
        b = _submit(bank, source_ref="https://example.org/b")
        bank.approve(a.doc_uuid)
        pending = bank.list_pending()
        assert [d.doc_uuid for d in pending] == [b.doc_uuid]


# ---------------------------------------------------------------------------
# 5. Hybrid retrieval (cosine + BM25, reciprocal-rank fusion)
# ---------------------------------------------------------------------------


class TestHybridRetrieval:
    def test_vector_limb_finds_relevant_doc(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        a = _submit(
            bank,
            source_ref="https://example.org/cars",
            content="engine pistons crankshaft turbocharger combustion cylinder",
            title="Cars",
        )
        b = _submit(
            bank,
            source_ref="https://example.org/garden",
            content="tomatoes basil soil compost watering irrigation harvest",
            title="Garden",
        )
        bank.approve(a.doc_uuid)
        bank.approve(b.doc_uuid)
        hits = bank.retrieve("how does a turbocharger engine work", k=1)
        assert len(hits) == 1
        assert hits[0].doc_uuid == a.doc_uuid
        assert hits[0].title == "Cars"
        assert hits[0].source_type == "url"

    def test_vector_limb_surfaces_doc_with_zero_word_overlap(self) -> None:
        """The mirror of the constant_embed lexical lock (#655 review FIX 5):
        the target shares NO indexable words with the query, so BM25 cannot
        see it — only the cosine limb can rank it.  Verified during authoring
        that this test FAILS with the vector limb commented out of the fusion
        (the prior vector-only assertion was satisfiable by BM25 alone)."""
        import re as _re

        b = _make_bank(embed_fn=pinned_embed)
        try:
            target = _submit(
                b,
                source_ref="https://example.org/sub",
                content=_VEC_TARGET,
                title="Submarines",
            )
            decoy = _submit(
                b,
                source_ref="https://example.org/bread",
                content=_VEC_DECOY,
                title="Bread",
            )
            b.approve(target.doc_uuid)
            b.approve(decoy.doc_uuid)
            # Sanity: query and target genuinely share zero indexable words.
            q_words = set(_re.findall(r"\w+", _VEC_QUERY.lower()))
            t_words = set(_re.findall(r"\w+", _VEC_TARGET.lower()))
            assert not (q_words & t_words), "fixture drift: words overlap"
            hits = b.retrieve(_VEC_QUERY, k=1)
            assert len(hits) == 1
            assert hits[0].doc_uuid == target.doc_uuid
            assert hits[0].title == "Submarines"
        finally:
            b.close()

    def test_lexical_limb_works_when_vectors_are_uninformative(self) -> None:
        """With a constant embedder, only BM25 can rank — prove the FTS5 limb."""
        b = _make_bank(embed_fn=constant_embed)
        try:
            a = _submit(
                b,
                source_ref="https://example.org/zeph",
                content="the zephyrium alloy resists corrosion at high temperature",
                title="Zephyrium",
            )
            other = _submit(
                b,
                source_ref="https://example.org/bread",
                content="flour water yeast salt knead proof bake crust crumb",
                title="Bread",
            )
            b.approve(a.doc_uuid)
            b.approve(other.doc_uuid)
            hits = b.retrieve("zephyrium corrosion", k=1)
            assert len(hits) == 1
            assert hits[0].doc_uuid == a.doc_uuid
        finally:
            b.close()

    def test_rrf_fuses_both_limbs(self, bank: EncryptedKnowledgeBank) -> None:
        """Both a vector-similar and a lexically-matching doc surface in top-2."""
        vec_doc = _submit(
            bank,
            source_ref="https://example.org/vec",
            content="quantum entanglement physics spooky particles measurement",
            title="Quantum",
        )
        lex_doc = _submit(
            bank,
            source_ref="https://example.org/lex",
            content="the flibbertigibbet protocol entanglement clause section nine",
            title="Protocol",
        )
        bank.approve(vec_doc.doc_uuid)
        bank.approve(lex_doc.doc_uuid)
        hits = bank.retrieve("quantum entanglement", k=2)
        got = {h.doc_uuid for h in hits}
        assert got == {vec_doc.doc_uuid, lex_doc.doc_uuid}

    def test_scores_descending(self, bank: EncryptedKnowledgeBank) -> None:
        for i, words in enumerate(
            ("red green blue colors", "red orange warm colors", "calculus integrals")
        ):
            r = _submit(bank, source_ref=f"https://example.org/{i}", content=words)
            bank.approve(r.doc_uuid)
        hits = bank.retrieve("red colors", k=3)
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)

    def test_rejected_never_retrieved(self, bank: EncryptedKnowledgeBank) -> None:
        r = _submit(bank)
        bank.reject(r.doc_uuid)
        assert bank.retrieve("turbochargers engine") == []

    def test_empty_query_and_zero_k(self, bank: EncryptedKnowledgeBank) -> None:
        r = _submit(bank)
        bank.approve(r.doc_uuid)
        assert bank.retrieve("   ") == []
        assert bank.retrieve("turbochargers", k=0) == []

    def test_incremental_fts_add_on_approve(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        r = _submit(bank)
        assert bank.retrieve("turbochargers") == []  # pending: not indexed
        bank.approve(r.doc_uuid)
        hits = bank.retrieve("turbochargers")
        assert hits and hits[0].doc_uuid == r.doc_uuid

    def test_fts_match_expr_neutralises_operators(self) -> None:
        """Free-form query text cannot inject FTS5 syntax.  The bare ``OR``
        token now lowercases into the #795 stopword set and is filtered."""
        expr = _fts_match_expr('drop "table NEAR(x) OR *')
        assert expr == '"drop" OR "table" OR "NEAR" OR "x"'
        assert _fts_match_expr("!!! ???") == ""

    def test_fts_match_expr_filters_stopwords(self) -> None:
        """#795: function words are dropped (case-insensitively) so they
        cannot flood the keyword limb with noise matches."""
        expr = _fts_match_expr("What is the status of the certificate rotation")
        assert expr == '"status" OR "certificate" OR "rotation"'

    def test_fts_match_expr_all_stopwords_keeps_unfiltered(self) -> None:
        """#795 fail-safe: a query whose indexable words are ALL stopwords
        keeps its full unfiltered expression — never an empty MATCH."""
        assert _fts_match_expr("what is it") == '"what" OR "is" OR "it"'

    def test_fts_match_expr_without_stopwords_is_unchanged(self) -> None:
        """#795: a query with no stopwords builds an expression byte-identical
        to the pre-filter behaviour."""
        expr = _fts_match_expr("turbocharger boost pressure")
        assert expr == '"turbocharger" OR "boost" OR "pressure"'

    def test_stopword_flooded_query_still_retrieves(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """#795 seam: the filtered MATCH expression runs against real FTS5
        and the content tokens alone still find the document."""
        r = _submit(bank)
        bank.approve(r.doc_uuid)
        hits = bank.retrieve("what is the engine doing in the turbochargers", k=1)
        assert hits and hits[0].doc_uuid == r.doc_uuid

    def test_all_stopword_query_lexical_limb_runs_without_error(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """#795 fail-safe seam: an all-stopword query reaches real FTS5 with
        its unfiltered expression (no FTS5 error, no match-everything), and
        the vector limb still fuses the document in."""
        r = _submit(bank)
        bank.approve(r.doc_uuid)
        hits = bank.retrieve("what is it about", k=1)
        assert len(hits) == 1
        assert hits[0].doc_uuid == r.doc_uuid

    def test_query_with_only_punctuation_skips_lexical_limb(
        self, bank: EncryptedKnowledgeBank
    ) -> None:
        """No indexable words → the lexical limb is skipped (no FTS5 syntax
        error) and the VECTOR limb alone must still produce the hit.  This
        fails if the cosine limb is removed from the fusion (#655 review)."""
        r = _submit(bank)
        bank.approve(r.doc_uuid)
        hits = bank.retrieve("???", k=1)
        assert len(hits) == 1
        assert hits[0].doc_uuid == r.doc_uuid


# ---------------------------------------------------------------------------
# 6. Persistence + cache rebuild at construction (DEK-unlock)
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_reopen_rebuilds_retrieval_caches(self, tmp_path: Path) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = _make_bank(db_path=db, cipher=cipher)
        r = _submit(b1)
        b1.approve(r.doc_uuid)
        pending = _submit(b1, source_ref="https://example.org/pending")
        b1.close()

        b2 = _make_bank(db_path=db, cipher=cipher)
        try:
            assert b2.count("approved") == 1
            assert b2.count("pending") == 1
            hits = b2.retrieve("turbochargers engine", k=1)
            assert hits and hits[0].doc_uuid == r.doc_uuid
            assert [d.doc_uuid for d in b2.list_pending()] == [pending.doc_uuid]
        finally:
            b2.close()

    def test_wrong_cipher_quarantines_not_crashes(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Reopening under a different DEK quarantines rows, never plaintext."""
        db = str(tmp_path / "knowledge.db")
        b1 = _make_bank(db_path=db, cipher=_make_cipher())
        r = _submit(b1)
        b1.approve(r.doc_uuid)
        b1.close()

        with caplog.at_level(logging.WARNING):
            b2 = _make_bank(db_path=db, cipher=_make_cipher())  # different DEK
        try:
            assert b2.retrieve("turbochargers engine") == []
            assert "KNOWLEDGE_ROW_DECRYPT_QUARANTINE" in caplog.text
        finally:
            b2.close()


# ---------------------------------------------------------------------------
# 7. Decrypt-quarantine on bulk reads (ADR-025 §2.7 pattern)
# ---------------------------------------------------------------------------


class TestQuarantine:
    def test_corrupt_chunk_quarantined_others_survive(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = _make_bank(db_path=db, cipher=cipher)
        a = _submit(
            b1,
            source_ref="https://example.org/a",
            content="alpha beta gamma delta words about engines",
        )
        c = _submit(
            b1,
            source_ref="https://example.org/c",
            content="healthy second document about gardens and compost",
        )
        b1.approve(a.doc_uuid)
        b1.approve(c.doc_uuid)
        b1.close()

        # Corrupt ONE chunk's embedding blob directly in the DB.
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE knowledge_chunks SET embedding=? WHERE doc_uuid=?",
            (b"\x01" + b"garbage" * 8, a.doc_uuid),
        )
        conn.commit()
        conn.close()

        with caplog.at_level(logging.WARNING):
            b2 = _make_bank(db_path=db, cipher=cipher)
        try:
            assert "KNOWLEDGE_ROW_DECRYPT_QUARANTINE" in caplog.text
            hits = b2.retrieve("gardens compost", k=2)
            assert any(h.doc_uuid == c.doc_uuid for h in hits)
            assert all(h.doc_uuid != a.doc_uuid for h in hits)
        finally:
            b2.close()

    def test_corrupt_pending_content_skipped_in_list_pending(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = _make_bank(db_path=db, cipher=cipher)
        bad = _submit(b1, source_ref="https://example.org/bad")
        good = _submit(
            b1,
            source_ref="https://example.org/good",
            content="a healthy pending row that decrypts fine",
        )
        conn = b1._conn
        conn.execute(
            "UPDATE knowledge_docs SET content=? WHERE doc_uuid=?",
            (b"\x01" + b"tampered" * 6, bad.doc_uuid),
        )
        conn.commit()

        with caplog.at_level(logging.WARNING):
            pending = b1.list_pending()
        assert [d.doc_uuid for d in pending] == [good.doc_uuid]
        assert "KNOWLEDGE_ROW_DECRYPT_QUARANTINE" in caplog.text
        b1.close()

    def test_single_record_read_hard_fails_closed(self, tmp_path: Path) -> None:
        """get_doc on a tampered row raises — never partial plaintext."""
        from shared.security.field_cipher import FieldCipherError

        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b = _make_bank(db_path=db, cipher=cipher)
        r = _submit(b)
        b._conn.execute(
            "UPDATE knowledge_docs SET content=? WHERE doc_uuid=?",
            (b"\x01" + b"tampered" * 6, r.doc_uuid),
        )
        b._conn.commit()
        with pytest.raises(FieldCipherError):
            b.get_doc(r.doc_uuid)
        b.close()

    def test_count_invalid_state_raises(self, bank: EncryptedKnowledgeBank) -> None:
        with pytest.raises(KnowledgeBankError):
            bank.count("limbo")


# ---------------------------------------------------------------------------
# 8. Transaction discipline (#655 adversarial-review FIX 1 — CRITICAL)
# ---------------------------------------------------------------------------


class _FlakyCipher(FieldCipher):
    """FieldCipher whose encrypt fails after N successful calls once armed.

    Probe for the approve-path transaction discipline: the failure lands
    partway through the per-chunk encryption loop, mimicking the review's
    'inject a failing cipher partway' reproduction.
    """

    def __init__(self, subkeys: object, fail_after: int) -> None:
        super().__init__(subkeys)  # type: ignore[arg-type]
        self.armed: bool = False
        self._calls: int = 0
        self._fail_after: int = int(fail_after)

    def arm(self) -> None:
        self.armed = True
        self._calls = 0

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        from shared.security.field_cipher import FieldCipherError

        if self.armed:
            self._calls += 1
            if self._calls > self._fail_after:
                raise FieldCipherError("injected encrypt failure (flaky cipher)")
        return super().encrypt(plaintext, aad=aad)


class TestTransactionDiscipline:
    """The reproduced #655 corruption defect and its siblings, locked."""

    def test_doc_uuid_collision_leaves_unrelated_pending_intact(
        self, tmp_path: Path
    ) -> None:
        """EXACT review repro: submit u1/X, submit u2/Y, then
        submit(doc_uuid=u1, source=Y) raises.  Under the pre-fix code the
        dedup DELETE of u2's row sat in an open implicit transaction and the
        NEXT healthy operation's commit silently destroyed u2 (gone after
        reopen).  Locked: u2 survives the raise, a later healthy commit, AND
        a reopen."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b = _make_bank(db_path=db, cipher=cipher)
        u1 = _submit(
            b,
            source_ref="https://example.org/X",
            content="content for source X with several words",
        )
        u2 = _submit(
            b,
            source_ref="https://example.org/Y",
            content="content for source Y with several words",
        )
        with pytest.raises(KnowledgeBankError):
            _submit(
                b,
                doc_uuid=u1.doc_uuid,  # collides with u1 ...
                source_ref="https://example.org/Y",  # ... dedups onto u2
                content="content for source Y with several words",
            )
        # u2 intact immediately after the refusal ...
        assert b.count("pending") == 2
        # ... and after a later unrelated submit's commit (the old failure
        # mode: the orphan DELETE flushed exactly here) ...
        _submit(
            b,
            source_ref="https://example.org/Z",
            content="an unrelated healthy submit with words",
        )
        assert b.count("pending") == 3
        assert "source Y" in b.get_doc(u2.doc_uuid).content
        b.close()
        # ... and after a reopen (nothing pending in any journal).
        b2 = _make_bank(db_path=db, cipher=cipher)
        try:
            assert b2.count("pending") == 3
            assert "source Y" in b2.get_doc(u2.doc_uuid).content
        finally:
            b2.close()

    def test_approve_failing_cipher_partway_leaves_pending_zero_chunks(
        self, tmp_path: Path
    ) -> None:
        """An approve whose cipher fails partway through chunk encryption
        must leave the doc PENDING with ZERO chunks — and later healthy
        operations must not flush any stale state (review FIX 1 repro)."""
        from shared.security.field_cipher import FieldCipherError

        db = str(tmp_path / "knowledge.db")
        env = DekEnvelope.create(
            sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
        )
        cipher = _FlakyCipher(derive_subkeys(env.unseal_dek()), fail_after=3)
        b = _make_bank(db_path=db, cipher=cipher)
        long_content = " ".join(f"sentence{i} about widgets" for i in range(400))
        r = _submit(b, content=long_content)  # multi-chunk on approve
        cipher.arm()
        with pytest.raises(FieldCipherError):
            b.approve(r.doc_uuid)
        cipher.armed = False

        assert b.get_doc(r.doc_uuid).approval_state == "pending"
        assert b.chunk_count() == 0
        assert b.retrieve("widgets") == []
        # A later healthy submit + approve must not resurrect anything.
        other = _submit(
            b,
            source_ref="https://example.org/other",
            content="a healthy other document with words",
        )
        b.approve(other.doc_uuid)
        assert b.get_doc(r.doc_uuid).approval_state == "pending"
        per_doc = b._conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_uuid=?",
            (r.doc_uuid,),
        ).fetchone()[0]
        assert int(per_doc) == 0
        b.close()
        b2 = _make_bank(db_path=db, cipher=cipher)
        try:
            assert b2.get_doc(r.doc_uuid).approval_state == "pending"
        finally:
            b2.close()

    def test_approve_mid_insert_db_failure_rolls_back(
        self, tmp_path: Path
    ) -> None:
        """A DB-level failure PARTWAY through the chunk INSERTs (UNIQUE
        violation on a planted conflicting row) must roll the inserted chunks
        back — never leave them in an open transaction for the next healthy
        commit to flush."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b = _make_bank(db_path=db, cipher=cipher)
        long_content = " ".join(f"sentence{i} about widgets" for i in range(400))
        r = _submit(b, content=long_content)
        # Plant a conflicting chunk at index 1 so executemany fails AFTER
        # chunk 0 was inserted (genuinely mid-DML).
        with b._conn:
            b._conn.execute(
                "INSERT INTO knowledge_chunks(doc_uuid, chunk_index, text, embedding) "
                "VALUES(?, 1, ?, ?)",
                (r.doc_uuid, b"\x01junk", b"\x01junk"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            b.approve(r.doc_uuid)
        # Chunk 0 must NOT survive (rolled back); only the planted row remains.
        rows = b._conn.execute(
            "SELECT chunk_index FROM knowledge_chunks WHERE doc_uuid=? "
            "ORDER BY chunk_index",
            (r.doc_uuid,),
        ).fetchall()
        assert [int(x[0]) for x in rows] == [1]
        assert b.get_doc(r.doc_uuid).approval_state == "pending"
        # A later healthy operation's commit must not resurrect chunk 0.
        other = _submit(
            b,
            source_ref="https://example.org/other",
            content="a healthy other document with words",
        )
        b.approve(other.doc_uuid)
        rows = b._conn.execute(
            "SELECT chunk_index FROM knowledge_chunks WHERE doc_uuid=?",
            (r.doc_uuid,),
        ).fetchall()
        assert [int(x[0]) for x in rows] == [1]
        b.close()


# ---------------------------------------------------------------------------
# 9. Embed-window meta + mismatch refusal (#655 review FIX 4)
# ---------------------------------------------------------------------------


class TestEmbedWindowMeta:
    def test_meta_records_configured_window_not_constant(self) -> None:
        """knowledge_meta carries the CONFIGURED window bound into embed_fn."""
        b = EncryptedKnowledgeBank(
            db_path=":memory:",
            embed_fn=fake_embed,
            cipher=_make_cipher(),
            embed_max_tokens=256,
        )
        try:
            row = b._conn.execute(
                "SELECT value FROM knowledge_meta WHERE key='embed_max_tokens'"
            ).fetchone()
            assert row[0] == "256"
        finally:
            b.close()

    def test_reopen_with_different_window_refuses_loudly(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stored-vs-configured window mismatch on reopen: ERROR log at
        construction; retrieve AND approve refuse (KnowledgeBankError) so the
        mixed-depth store ADR-031 §3 rejects can be neither created nor
        queried; review/reject reads stay available."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = EncryptedKnowledgeBank(
            db_path=db, embed_fn=fake_embed, cipher=cipher, embed_max_tokens=512
        )
        r = _submit(b1)
        b1.approve(r.doc_uuid)
        pend = _submit(b1, source_ref="https://example.org/pending-doc")
        b1.close()

        with caplog.at_level(logging.ERROR):
            b2 = EncryptedKnowledgeBank(
                db_path=db, embed_fn=fake_embed, cipher=cipher, embed_max_tokens=128
            )
        try:
            assert "KNOWLEDGE_EMBED_WINDOW_MISMATCH" in caplog.text
            with pytest.raises(KnowledgeBankError, match="embed-window mismatch"):
                b2.retrieve("turbochargers engine")
            with pytest.raises(KnowledgeBankError, match="embed-window mismatch"):
                b2.approve(pend.doc_uuid)
            # Non-embedding lifecycle reads/decisions remain available.
            assert b2.count("approved") == 1
            assert [d.doc_uuid for d in b2.list_pending()] == [pend.doc_uuid]
            b2.reject(pend.doc_uuid)
            assert b2.count("rejected") == 1
        finally:
            b2.close()

    def test_matching_window_reopen_is_clean(self, tmp_path: Path) -> None:
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b1 = EncryptedKnowledgeBank(
            db_path=db, embed_fn=fake_embed, cipher=cipher, embed_max_tokens=512
        )
        r = _submit(b1)
        b1.approve(r.doc_uuid)
        b1.close()
        b2 = EncryptedKnowledgeBank(
            db_path=db, embed_fn=fake_embed, cipher=cipher, embed_max_tokens=512
        )
        try:
            hits = b2.retrieve("turbochargers engine", k=1)
            assert hits and hits[0].doc_uuid == r.doc_uuid
        finally:
            b2.close()


# ---------------------------------------------------------------------------
# 10. WAL-sidecar no-cleartext scan (#655 review FIX 7)
# ---------------------------------------------------------------------------


class TestWalSidecarNoCleartext:
    """The -wal journal file must never contain readable plaintext.

    Mirror of the session store's TestWalSidecarNoCleartext: WAL is ON for
    knowledge.db (deliberate divergence from the substrate), so the sidecar
    only ever carries already-ciphertext column values.  Methodology: write
    (submit + approve) WITHOUT close/checkpoint so the -wal stays populated,
    then scan its raw bytes for the content/title/source_ref samples.
    """

    def test_wal_sidecar_contains_no_plaintext(self, tmp_path: Path) -> None:
        db = str(tmp_path / "knowledge.db")
        b = _make_bank(db_path=db)
        r = _submit(b)
        b.approve(r.doc_uuid)
        # Deliberately NO close / checkpoint — the WAL must be populated.
        wal_path = Path(db + "-wal")
        assert wal_path.exists() and wal_path.stat().st_size > 0, (
            "-wal sidecar missing/empty — WAL mode regressed?"
        )
        wal_bytes = wal_path.read_bytes()
        content_sha_hex = hashlib.sha256(
            b.get_doc(r.doc_uuid).content.encode("utf-8")
        ).hexdigest().encode("ascii")
        for sample in (
            b"Turbochargers compress intake air",
            b"How turbochargers work",
            b"https://example.org/articles/turbo-engines",
            b"A. Writer",
            content_sha_hex,  # membership-oracle close (#655): keyed only
        ):
            assert sample not in wal_bytes, (
                f"plaintext leaked into the -wal sidecar: {sample!r}"
            )
        b.close()


# ---------------------------------------------------------------------------
# 11. FTS5 index stays in RAM — no index file on disk (#655 review FIX 8)
# ---------------------------------------------------------------------------


class TestFtsInMemoryLock:
    def test_no_files_beyond_db_and_sidecars_and_fts_is_memory(
        self, tmp_path: Path
    ) -> None:
        """The DB parent dir must hold exactly {knowledge.db, -wal, -shm}
        after submit+approve (no plaintext FTS index file can appear), and
        PRAGMA database_list on the FTS connection must show an empty file
        path (a genuinely in-memory database)."""
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        db = str(kb_dir / "knowledge.db")
        b = _make_bank(db_path=db)
        r = _submit(b)
        b.approve(r.doc_uuid)
        try:
            names = {p.name for p in kb_dir.iterdir()}
            assert names == {
                "knowledge.db",
                "knowledge.db-wal",
                "knowledge.db-shm",
            }, f"unexpected files beside knowledge.db: {sorted(names)}"
            rows = b._fts.execute("PRAGMA database_list").fetchall()
            assert rows, "PRAGMA database_list returned nothing"
            for _seq, _name, file_path in rows:
                assert (file_path or "") == "", (
                    f"FTS connection is file-backed: {file_path!r}"
                )
        finally:
            b.close()


# ---------------------------------------------------------------------------
# 12. AAD swap locks (#655 review FIX 9)
# ---------------------------------------------------------------------------


class TestAadSwapLock:
    def test_cross_doc_content_ciphertext_swap_fails_closed(
        self, bank: EncryptedKnowledgeBank, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Doc A's content ciphertext planted in doc B's content column must
        refuse to decrypt (AAD binds the doc identity): get_doc(B) raises,
        list_pending quarantines B per the bulk-read rule."""
        from shared.security.field_cipher import FieldCipherError

        a = _submit(
            bank,
            source_ref="https://example.org/a",
            content="alpha document body with words",
        )
        bdoc = _submit(
            bank,
            source_ref="https://example.org/b",
            content="beta document body with words",
        )
        blob_a = bank._conn.execute(
            "SELECT content FROM knowledge_docs WHERE doc_uuid=?", (a.doc_uuid,)
        ).fetchone()[0]
        with bank._conn:
            bank._conn.execute(
                "UPDATE knowledge_docs SET content=? WHERE doc_uuid=?",
                (blob_a, bdoc.doc_uuid),
            )
        with pytest.raises(FieldCipherError):
            bank.get_doc(bdoc.doc_uuid)
        with caplog.at_level(logging.WARNING):
            pending = bank.list_pending()
        assert [d.doc_uuid for d in pending] == [a.doc_uuid]
        assert "KNOWLEDGE_ROW_DECRYPT_QUARANTINE" in caplog.text

    def test_cross_column_title_blob_in_content_fails_closed(
        self, bank: EncryptedKnowledgeBank, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A title ciphertext planted in the SAME doc's content column must
        refuse to decrypt (AAD binds the column name too)."""
        from shared.security.field_cipher import FieldCipherError

        a = _submit(bank)
        title_blob = bank._conn.execute(
            "SELECT title FROM knowledge_docs WHERE doc_uuid=?", (a.doc_uuid,)
        ).fetchone()[0]
        with bank._conn:
            bank._conn.execute(
                "UPDATE knowledge_docs SET content=? WHERE doc_uuid=?",
                (title_blob, a.doc_uuid),
            )
        with pytest.raises(FieldCipherError):
            bank.get_doc(a.doc_uuid)
        with caplog.at_level(logging.WARNING):
            assert bank.list_pending() == []
        assert "KNOWLEDGE_ROW_DECRYPT_QUARANTINE" in caplog.text


# ---------------------------------------------------------------------------
# 13. secure_delete at rest — SE-1 free-page residual probes (UC-010 WS2)
# ---------------------------------------------------------------------------


def _multipage_png(marker: bytes, *, width: int = 64, height: int = 64) -> bytes:
    """A magic-valid PNG that carries *marker* across many freed pages.

    ``store_image`` re-runs the egress door's content gate at rest
    (:func:`validate_image_content` + :func:`dimension_above_max`), so the
    payload MUST be a genuine PNG: the 8-byte signature, then an IHDR chunk whose
    declared dimensions sit UNDER the decompression-bomb ceiling (header-only,
    never decoded).  The marker is appended AFTER the header so the body spans
    many SQLite pages — a single-page row could be page-reused on DELETE and
    false-pass even with ``secure_delete`` OFF, so the residual must be
    multi-page to make the probe genuinely sensitive.
    """
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        b"\x00\x00\x00\x0d"          # chunk length = 13
        + b"IHDR"
        + width.to_bytes(4, "big")    # body[16:20] — width (under ceiling)
        + height.to_bytes(4, "big")   # body[20:24] — height
        + b"\x08\x06\x00\x00\x00"     # bit depth / colour / compression / filter / interlace
    )
    return sig + ihdr + (marker * 4000)


class TestSecureDelete:
    """``PRAGMA secure_delete=ON`` zeroes freed pages — proven at rest.

    The store opens its connection with ``secure_delete=ON`` so DELETEd image
    rows (discarded generated images, rejected article images) are overwritten
    with zeros in the freed pages rather than merely unlinked.  In WAL mode the
    zeroing lands in the ``-wal`` frames and only reaches the main file at
    checkpoint — the probes force ``wal_checkpoint(TRUNCATE)`` before reading the
    raw bytes off disk.

    These tests assert the absence of BOTH the plaintext marker AND a captured
    CIPHERTEXT FRAGMENT of the row's ``data`` BLOB.  A plaintext-only assert
    would pass even with the PRAGMA OFF (the bytes are encrypted at rest anyway),
    so asserting the ciphertext is what makes the probe actually sensitive to
    ``secure_delete``.  But the BLOB is multi-page: SQLite splits it across 4 KiB
    overflow pages whose page headers interrupt the byte stream, so a WHOLE-blob
    ``in raw`` scan never matches even while the row is LIVE (useless as a probe).
    The probe therefore captures a 64-byte window from DEEP inside the ciphertext
    (:data:`_FRAG_LO`:`_FRAG_HI`), comfortably within a single overflow page and
    thus contiguous on disk.  Verified during authoring (PRAGMA toggled OFF in
    ``knowledge_bank.py``): that fragment SURVIVES the delete in the freed page
    with ``secure_delete`` OFF (both probes FAIL) and is zeroed with it ON (both
    pass) — and the pragma-on regression lock fails too.
    """

    # A 64-byte window from deep inside the ciphertext, comfortably within one
    # 4 KiB overflow page so it is stored contiguously on disk (a contiguous
    # match is impossible across the whole multi-page BLOB — page headers split
    # it).  This window is the load-bearing residual signal.
    _FRAG_LO: int = 2000
    _FRAG_HI: int = 2064

    def test_secure_delete_pragma_on(self, tmp_path: Path) -> None:
        """Regression lock: the connection's secure_delete PRAGMA is ON (=1).

        Fails loudly if the PRAGMA is ever dropped in a merge — the at-rest
        zeroing the ADR-032/ADR-033 'purges at rest' claim relies on.  Mirrors
        the WAL-mode regression lock (:meth:`test_wal_mode_on_for_file_backed_store`).
        """
        b = _make_bank(db_path=str(tmp_path / "knowledge.db"))
        try:
            val = b._conn.execute("PRAGMA secure_delete").fetchone()[0]
            assert int(val) == 1, f"secure_delete is not ON (got {val!r})"
        finally:
            b.close()

    def test_se1_generated_image_no_freepage_residual(self, tmp_path: Path) -> None:
        """A discarded generated image leaves NO free-page residual at rest.

        Store a multi-page generated image, capture the on-disk ciphertext of its
        ``data`` BLOB, round-trip it, delete it, checkpoint(TRUNCATE), close, then
        scan the raw file: neither the plaintext marker nor the captured
        ciphertext may survive (secure_delete zeroed the freed pages)."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b = _make_bank(db_path=db, cipher=cipher)
        marker = b"WS2-SE1-GENIMG-MARKER-"
        image_id = uuid.uuid4().hex
        session_id = "se1-session"
        image_bytes = marker * 4000  # multi-page payload (store_generated_image does not gate content)

        b.store_generated_image(
            image_id=image_id,
            session_id=session_id,
            image_bytes=image_bytes,
            mime="image/png",
            prompt="a unique generated-image prompt",
        )
        # Capture the at-rest ciphertext of the data BLOB BEFORE delete, and a
        # mid-blob fragment that is contiguous on disk (single overflow page).
        cipher_blob = bytes(
            b._conn.execute(
                "SELECT data FROM generated_images WHERE image_id=?", (image_id,)
            ).fetchone()[0]
        )
        assert len(cipher_blob) > self._FRAG_HI, "BLOB too small to fragment"
        cipher_frag = cipher_blob[self._FRAG_LO : self._FRAG_HI]
        # Sanity: the fragment IS contiguous on disk while the row is LIVE — if it
        # weren't, the post-delete absence assert below would be vacuously true.
        b._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert cipher_frag in Path(db).read_bytes(), (
            "ciphertext fragment not found on disk while LIVE — probe would be vacuous"
        )
        # Round-trip proves the row was genuinely stored + decryptable.
        got = b.get_generated_image(image_id)
        assert got is not None and got.data == image_bytes

        assert b.delete_generated_image(image_id) is True
        assert b.get_generated_image(image_id) is None
        # Force the WAL zeroing into the main file, then read raw bytes.
        b._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        b.close()

        raw = Path(db).read_bytes()
        assert marker not in raw, "plaintext marker survived in freed pages"
        assert cipher_frag not in raw, (
            "ciphertext fragment of the deleted data BLOB survived — secure_delete OFF?"
        )

    def test_se1_rejected_knowledge_image_no_freepage_residual(
        self, tmp_path: Path
    ) -> None:
        """A rejected article's display image is PURGED at rest (ADR-032).

        Submit a pending doc, store a multi-page display image under it, capture
        the on-disk ciphertext of the image ``data`` BLOB, reject the doc (which
        DELETEs knowledge_images), checkpoint(TRUNCATE), close, then scan the raw
        file: neither the plaintext marker nor the captured ciphertext survive."""
        db = str(tmp_path / "knowledge.db")
        cipher = _make_cipher()
        b = _make_bank(db_path=db, cipher=cipher)
        r = _submit(b)
        marker = b"WS2-SE1-KNOWIMG-MARKER-"
        image_id = uuid.uuid4().hex
        image_bytes = _multipage_png(marker)

        b.store_image(
            image_id=image_id,
            doc_uuid=r.doc_uuid,
            image_bytes=image_bytes,
            mime="image/png",
            alt="a unique alt label",
            source_url="https://example.org/img.png",
            approval_state="pending",
        )
        assert b.image_count(r.doc_uuid) == 1
        cipher_blob = bytes(
            b._conn.execute(
                "SELECT data FROM knowledge_images WHERE image_id=?", (image_id,)
            ).fetchone()[0]
        )
        assert len(cipher_blob) > self._FRAG_HI, "BLOB too small to fragment"
        cipher_frag = cipher_blob[self._FRAG_LO : self._FRAG_HI]
        # Sanity: the fragment IS contiguous on disk while the image is LIVE.
        b._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert cipher_frag in Path(db).read_bytes(), (
            "ciphertext fragment not found on disk while LIVE — probe would be vacuous"
        )
        # Round-trip proves the image was genuinely stored + decryptable.
        got = b.get_knowledge_image(r.doc_uuid, image_id)
        assert got is not None and got.data == image_bytes

        b.reject(r.doc_uuid)  # DELETEs knowledge_images for the doc
        assert b.image_count(r.doc_uuid) == 0
        b._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        b.close()

        raw = Path(db).read_bytes()
        assert marker not in raw, "plaintext marker survived in freed pages"
        assert cipher_frag not in raw, (
            "ciphertext fragment of the rejected image data BLOB survived — secure_delete OFF?"
        )
