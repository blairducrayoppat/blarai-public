"""
Tests for the Personal Knowledge Substrate (USE-CASE-002 MVP).

Uses a deterministic bag-of-words fake embedder so retrieval is meaningful
(texts sharing words embed near each other) without loading the real ONNX
model. This exercises chunking, ingest, brute-force cosine retrieval, the
document/turn split, session exclusion, dedup-on-reingest, and persistence.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pytest

from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    SubstrateStore,
    chunk_text,
)


def fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words embedder: shared words → similar vectors."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


@pytest.fixture()
def store() -> SubstrateStore:
    return SubstrateStore(db_path=":memory:", embed_fn=fake_embed)


# ── Chunking ────────────────────────────────────────────────────────────


def test_chunk_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_short_single() -> None:
    assert chunk_text("a short doc") == ["a short doc"]


def test_chunk_long_overlaps() -> None:
    text = " ".join(f"word{i}" for i in range(2000))  # well over one window
    chunks = chunk_text(text, chunk_chars=200, overlap_chars=40)
    assert len(chunks) > 1
    # Overlap: the tail of one chunk reappears at the head of the next.
    assert chunks[0].split()[-1] in chunks[1] or chunks[1].startswith(chunks[0].split()[-1])


def test_chunk_reassembles_content() -> None:
    text = " ".join(f"token{i}" for i in range(500))
    chunks = chunk_text(text, chunk_chars=300, overlap_chars=50)
    joined = " ".join(chunks)
    for tok in ("token0", "token250", "token499"):
        assert tok in joined


# ── Document ingest + retrieval ──────────────────────────────────────────


def test_ingest_document_counts_chunks(store: SubstrateStore) -> None:
    n = store.ingest_document("recipe.txt", "mix flour water yeast salt and bake bread")
    assert n == 1
    assert store.count("doc") == 1


def test_retrieve_finds_relevant_document(store: SubstrateStore) -> None:
    store.ingest_document("cars.txt", "the engine pistons crankshaft and turbocharger")
    store.ingest_document("garden.txt", "tomatoes basil soil compost and watering")
    hits = store.retrieve("how does a turbocharger engine work", k_docs=1, k_turns=0)
    assert len(hits) == 1
    assert hits[0].source == "cars.txt"
    assert hits[0].kind == "doc"


def test_reingest_replaces_not_duplicates(store: SubstrateStore) -> None:
    store.ingest_document("notes.txt", "alpha beta gamma")
    store.ingest_document("notes.txt", "delta epsilon")  # same filename, new content
    assert store.count("doc") == 1
    hits = store.retrieve("delta epsilon", k_docs=1, k_turns=0)
    assert "delta" in hits[0].text


def test_long_document_multiple_chunks(store: SubstrateStore) -> None:
    text = " ".join(f"sentence{i} about widgets" for i in range(400))
    n = store.ingest_document("big.txt", text)
    assert n > 1
    assert store.count("doc") == n


# ── Turn ingest + cross-session recall ───────────────────────────────────


def test_ingest_turn(store: SubstrateStore) -> None:
    assert store.ingest_turn("sess-1", 0, "my sister is named Dana", "Noted, Dana.") == 1
    assert store.count("turn") == 1


def test_empty_turn_not_ingested(store: SubstrateStore) -> None:
    assert store.ingest_turn("sess-1", 0, "", "") == 0
    assert store.count("turn") == 0


def test_cross_session_turn_recall(store: SubstrateStore) -> None:
    # A past session mentioned the sister; an unrelated one did not.
    store.ingest_turn("old-sess", 0, "my sister Dana loves hiking trails", "Got it.")
    store.ingest_turn("old-sess", 1, "the weather today is rainy and cold", "Indeed.")
    hits = store.retrieve("what does my sister Dana enjoy", k_docs=0, k_turns=1)
    assert len(hits) == 1
    assert "sister" in hits[0].text and "Dana" in hits[0].text


def test_exclude_current_session(store: SubstrateStore) -> None:
    store.ingest_turn("current", 0, "apples oranges bananas", "fruit noted")
    store.ingest_turn("past", 0, "apples oranges bananas", "fruit noted")
    hits = store.retrieve("apples oranges", k_docs=0, k_turns=5, exclude_session="current")
    assert all(h.session_id != "current" for h in hits)
    assert any(h.session_id == "past" for h in hits)


def test_turn_reingest_idempotent(store: SubstrateStore) -> None:
    store.ingest_turn("s", 3, "hello", "hi")
    store.ingest_turn("s", 3, "hello again", "hi there")  # same (session, index)
    assert store.count("turn") == 1


# ── Retrieval budget + edge cases ────────────────────────────────────────


def test_docs_and_turns_combined(store: SubstrateStore) -> None:
    store.ingest_document("d.txt", "quantum entanglement physics")
    store.ingest_turn("s", 0, "quantum entanglement is spooky", "indeed spooky")
    hits = store.retrieve("quantum entanglement", k_docs=1, k_turns=1)
    kinds = {h.kind for h in hits}
    assert kinds == {"doc", "turn"}


def test_empty_query_returns_nothing(store: SubstrateStore) -> None:
    store.ingest_document("d.txt", "content here")
    assert store.retrieve("   ") == []


def test_k_zero_skips_kind(store: SubstrateStore) -> None:
    store.ingest_document("d.txt", "alpha")
    store.ingest_turn("s", 0, "alpha", "beta")
    assert all(h.kind == "turn" for h in store.retrieve("alpha", k_docs=0, k_turns=2))


def test_scores_descending(store: SubstrateStore) -> None:
    store.ingest_document("a.txt", "red green blue colors")
    store.ingest_document("b.txt", "red orange warm colors")
    store.ingest_document("c.txt", "calculus integrals derivatives")
    hits = store.retrieve("red colors", k_docs=3, k_turns=0)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


# ── Persistence across restart (FUT-07 shape) ────────────────────────────


def test_persistence_across_reopen(tmp_path: Path) -> None:
    db = str(tmp_path / "substrate.db")
    s1 = SubstrateStore(db, fake_embed)
    s1.ingest_document("kept.txt", "persistent memory survives restart")
    s1.ingest_turn("s", 0, "remember this fact", "remembered")
    s1.close()

    s2 = SubstrateStore(db, fake_embed)
    assert s2.count("doc") == 1
    assert s2.count("turn") == 1
    hits = s2.retrieve("persistent memory restart", k_docs=1, k_turns=0)
    assert hits[0].source == "kept.txt"
    s2.close()
