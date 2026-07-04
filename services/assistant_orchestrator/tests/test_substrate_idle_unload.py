"""
Tests for Vikunja #611 — substrate embedding-cache idle-unload (ADR-025 §3).

The decrypted embedding matrix is the largest and longest-lived plaintext-derived
secret in RAM (feasibility study §2.2/§3-mitigation-2).  ``unload_embed_cache()``
drops it when idle and ZEROES the numpy buffers in place (numpy arrays are mutable,
unlike the immutable-bytes DEK, so this is a genuine overwrite, not just a
dereference), reloading lazily on the next retrieval to shrink both the live-memory
exposure window and the 32 GB footprint.

All tests use SYNTHETIC embeddings (the bag-of-words ``fake_embed`` mirrored from
``test_substrate_encryption.py``) — no real model or GPU is required.  All stores
use ``:memory:`` or ``tmp_path``; NEVER write to ``%LOCALAPPDATA%``.

Test structure:
  1. unload_embed_cache() zeroes the buffers IN PLACE and clears the dict; idempotent.
  2. Lazy reload: a retrieve() after unload returns identical top-k + scores.
  3. Thread-safety: concurrent retrieve() + unload_embed_cache() never crash/corrupt.
  4. Idle timer: a short test-injected window unloads after idle and reloads on access;
     a window <= 0 never idle-unloads (and starts no monitor thread).
  5. The existing write-invalidation path still works unchanged with idle-unload present.
  6. close() stops the monitor thread cleanly (no leaked thread) and scrubs the cache.
"""

from __future__ import annotations

import threading
import time
import zlib
from pathlib import Path

import numpy as np
import pytest

import services.assistant_orchestrator.src.substrate as substrate_mod
from services.assistant_orchestrator.src.substrate import (
    DEFAULT_EMBED_CACHE_IDLE_UNLOAD_S,
    EMBED_DIM,
    EncryptedSubstrateStore,
)
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_substrate_encryption.py)
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


def _make_cipher() -> FieldCipher:
    """Build a FieldCipher from a freshly-generated DEK (SoftwareSealer path)."""
    sealer = SoftwareSealer()
    rk = generate_recovery_key()
    env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
    dek = env.unseal_dek()
    return FieldCipher(derive_subkeys(dek))


def _make_store(
    db_path: str = ":memory:",
    cipher: FieldCipher | None = None,
    *,
    idle_unload_s: int = 0,
) -> EncryptedSubstrateStore:
    """Construct a store.

    Defaults to ``idle_unload_s=0`` (no monitor thread) so a test that drives the
    cache lifecycle explicitly does not also race a background timer; tests that
    exercise the timer pass an explicit positive window.
    """
    if cipher is None:
        cipher = _make_cipher()
    return EncryptedSubstrateStore(
        db_path=db_path,
        embed_fn=fake_embed,
        cipher=cipher,
        embed_cache_idle_unload_s=idle_unload_s,
    )


def _seed_store(store: EncryptedSubstrateStore) -> None:
    """Seed with representative documents + turns (distinguishable bag-of-words)."""
    store.ingest_document(
        "cars.txt",
        "engine engine pistons pistons turbocharger crankshaft combustion cylinder",
    )
    store.ingest_document(
        "garden.txt",
        "tomatoes tomatoes basil basil compost watering irrigation harvest",
    )
    store.ingest_turn("sess-A", 0, "my sister is named Dana hiking trails", "Noted, Dana.")
    store.ingest_turn("sess-A", 1, "the weather today is rainy and cold outside", "Indeed.")


# ---------------------------------------------------------------------------
# 1. unload_embed_cache() zeroes the buffers IN PLACE and clears the dict
# ---------------------------------------------------------------------------


class TestUnloadZeroesBuffers:
    def test_unload_zeroes_buffers_in_place_and_clears_dict(self) -> None:
        """Captured ndarray refs must be all-zero after unload (in-place overwrite),
        and the cache dict must be empty."""
        store = _make_store()
        _seed_store(store)

        # Capture references to the actual cached ndarrays BEFORE unload.
        cached_refs = list(store._embed_cache.values())
        assert cached_refs, "precondition: cache should be populated after seeding"
        # Sanity: at least one buffer is non-zero pre-unload (real embeddings).
        assert any(not (arr == 0).all() for arr in cached_refs)

        did_unload = store.unload_embed_cache()

        assert did_unload is True
        # The dict is cleared...
        assert len(store._embed_cache) == 0
        # ...AND the previously-cached buffers were overwritten in place with zeros.
        # (This is the load-bearing assertion: dereferencing alone would leave the
        # plaintext vectors in the captured refs; zeroing proves the genuine scrub.)
        for arr in cached_refs:
            assert (arr == 0).all(), (
                "embedding buffer was not zeroed in place — unload dereferenced "
                "without overwriting the plaintext vector"
            )
        store.close()

    def test_unload_is_idempotent(self) -> None:
        """A second unload is a no-op and returns False."""
        store = _make_store()
        _seed_store(store)

        assert store.unload_embed_cache() is True
        assert store.unload_embed_cache() is False
        assert store.unload_embed_cache() is False
        assert len(store._embed_cache) == 0
        store.close()

    def test_unload_on_empty_store(self) -> None:
        """Unloading an empty store is safe (zeroes nothing, marks unloaded)."""
        store = _make_store()
        assert store.unload_embed_cache() is True  # first transition still happens
        assert store.unload_embed_cache() is False
        store.close()


# ---------------------------------------------------------------------------
# 2. Lazy reload: retrieve() after unload returns identical results
# ---------------------------------------------------------------------------


class TestLazyReloadEquivalence:
    def test_retrieve_after_unload_is_identical(self) -> None:
        """Same top-k, same scores, same text — before vs. after an idle-unload."""
        store = _make_store()
        _seed_store(store)

        pre = store.retrieve("engine pistons turbocharger", k_docs=2, k_turns=2)
        assert pre, "precondition: query should retrieve something"

        store.unload_embed_cache()
        assert len(store._embed_cache) == 0  # genuinely unloaded

        post = store.retrieve("engine pistons turbocharger", k_docs=2, k_turns=2)

        # Cache was transparently reloaded.
        assert len(store._embed_cache) > 0
        assert store._cache_unloaded is False

        pre_key = [(h.kind, h.source, h.session_id, h.text, round(h.score, 6)) for h in pre]
        post_key = [(h.kind, h.source, h.session_id, h.text, round(h.score, 6)) for h in post]
        assert pre_key == post_key, "retrieval after idle-unload diverged from before"
        store.close()

    def test_multiple_unload_reload_cycles_stable(self) -> None:
        """Repeated unload→reload cycles keep returning identical results."""
        store = _make_store()
        _seed_store(store)
        baseline = store.retrieve("tomatoes basil compost", k_docs=2, k_turns=2)
        baseline_key = [(h.kind, h.text, round(h.score, 6)) for h in baseline]

        for _ in range(3):
            store.unload_embed_cache()
            again = store.retrieve("tomatoes basil compost", k_docs=2, k_turns=2)
            assert [(h.kind, h.text, round(h.score, 6)) for h in again] == baseline_key
        store.close()

    def test_reload_uses_same_rows_not_a_rewrite(self) -> None:
        """Reload re-decrypts the SAME rows: chunk count is unchanged across unload."""
        store = _make_store()
        _seed_store(store)
        n_before = store.count()
        store.unload_embed_cache()
        store.retrieve("engine")  # triggers reload
        assert store.count() == n_before
        store.close()


# ---------------------------------------------------------------------------
# 3. Thread-safety: concurrent retrieve() + unload() must not crash or corrupt
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_retrieve_and_unload(self) -> None:
        """Drive retrieve() and unload_embed_cache() from many threads at once.

        The lock must serialise the unload-vs-reload race: no exception, and every
        non-empty result is internally consistent (the query always matches the
        'cars' doc as the top doc hit)."""
        store = _make_store()
        _seed_store(store)

        errors: list[BaseException] = []
        stop = threading.Event()
        barrier = threading.Barrier(9)

        def retriever() -> None:
            barrier.wait()
            try:
                while not stop.is_set():
                    hits = store.retrieve("engine pistons turbocharger", k_docs=1, k_turns=1)
                    # When docs are present in the (possibly just-reloaded) cache,
                    # the top doc hit must be the cars doc — never corrupted data.
                    docs = [h for h in hits if h.kind == "doc"]
                    if docs:
                        assert docs[0].source == "cars.txt"
            except BaseException as exc:  # noqa: BLE001 — capture for the assert below
                errors.append(exc)

        def unloader() -> None:
            barrier.wait()
            try:
                while not stop.is_set():
                    store.unload_embed_cache()
                    time.sleep(0.001)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=retriever) for _ in range(6)]
        threads += [threading.Thread(target=unloader) for _ in range(3)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"concurrent access raised: {errors[:3]}"
        # Store still usable + consistent after the storm.
        final = store.retrieve("engine pistons turbocharger", k_docs=1, k_turns=1)
        assert any(h.kind == "doc" and h.source == "cars.txt" for h in final)
        store.close()


# ---------------------------------------------------------------------------
# 4. Idle timer: short injected window unloads after idle; <= 0 never does
# ---------------------------------------------------------------------------


class TestIdleTimer:
    def test_idle_unload_fires_after_window_then_reloads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With a 1 s window and a fast poll tick, the monitor unloads after idle;
        the next retrieve reloads lazily."""
        # Shrink the monitor's poll tick so a 1 s window is checked promptly.
        monkeypatch.setattr(substrate_mod, "_IDLE_MONITOR_MAX_TICK_S", 0.02)

        store = _make_store(idle_unload_s=1)
        _seed_store(store)
        assert len(store._embed_cache) > 0
        assert store._cache_unloaded is False

        # Wait past the idle window for the monitor to fire (bounded busy-wait).
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and not store._cache_unloaded:
            time.sleep(0.02)

        assert store._cache_unloaded is True, "idle monitor did not unload within window"
        assert len(store._embed_cache) == 0

        # Access reloads lazily and returns hits.
        hits = store.retrieve("engine pistons turbocharger")
        assert any(h.kind == "doc" for h in hits)
        assert store._cache_unloaded is False
        store.close()

    def test_active_use_defers_unload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Repeated retrievals keep bumping last-access, so the cache stays resident
        while in active use (the unload does not fire mid-activity)."""
        monkeypatch.setattr(substrate_mod, "_IDLE_MONITOR_MAX_TICK_S", 0.02)
        store = _make_store(idle_unload_s=1)
        _seed_store(store)

        # Hammer retrieve for ~1.5 s (longer than the 1 s window). Because each call
        # bumps last_access, the cache must never be observed unloaded.
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:
            store.retrieve("engine")
            assert store._cache_unloaded is False
            time.sleep(0.05)
        store.close()

    def test_disabled_window_starts_no_thread_and_never_unloads(self) -> None:
        """idle_unload_s <= 0 → no monitor thread, cache resident forever."""
        store = _make_store(idle_unload_s=0)
        _seed_store(store)
        assert store._idle_thread is None
        # Even after a wait, nothing unloads on its own.
        time.sleep(0.3)
        assert store._cache_unloaded is False
        assert len(store._embed_cache) > 0
        store.close()

    def test_negative_window_also_disables(self) -> None:
        store = _make_store(idle_unload_s=-5)
        _seed_store(store)
        assert store._idle_thread is None
        assert store._cache_unloaded is False
        store.close()

    def test_default_window_is_900(self) -> None:
        """The module default matches the documented 15-minute placeholder."""
        assert DEFAULT_EMBED_CACHE_IDLE_UNLOAD_S == 900


# ---------------------------------------------------------------------------
# 5. The existing write-invalidation path still works with idle-unload present
# ---------------------------------------------------------------------------


class TestWriteInvalidationUnchanged:
    def test_ingest_after_unload_reloads_and_includes_new_row(self) -> None:
        """A write (ingest) after an idle-unload rebuilds the cache eagerly and the
        new content is retrievable — the write path is not broken by idle-unload."""
        store = _make_store()
        _seed_store(store)
        store.unload_embed_cache()
        assert store._cache_unloaded is True

        # A write invalidates → reloads eagerly; the store leaves the unloaded state.
        store.ingest_document(
            "rockets.txt", "rocket rocket propellant nozzle thrust telemetry"
        )
        assert store._cache_unloaded is False
        assert len(store._embed_cache) > 0

        hits = store.retrieve("rocket propellant nozzle thrust", k_docs=1, k_turns=0)
        assert any(h.kind == "doc" and h.source == "rockets.txt" for h in hits)
        store.close()

    def test_invalidate_refreshes_changed_document(self) -> None:
        """Re-ingesting a filename replaces its chunks; retrieval reflects the new
        content — unchanged behaviour with idle-unload in place."""
        store = _make_store()
        store.ingest_document("notes.txt", "alpha alpha beta gamma")
        first = store.retrieve("alpha beta", k_docs=1, k_turns=0)
        assert first

        store.ingest_document("notes.txt", "delta delta epsilon zeta")
        # Old terms no longer dominate; new doc is retrievable by its new terms.
        hits = store.retrieve("delta epsilon zeta", k_docs=1, k_turns=0)
        assert any(h.source == "notes.txt" for h in hits)
        assert store.count(kind="doc") == 1  # replaced, not duplicated
        store.close()


# ---------------------------------------------------------------------------
# 6. close() stops the monitor thread cleanly and scrubs the cache
# ---------------------------------------------------------------------------


class TestCloseLifecycle:
    def test_close_stops_idle_thread(self) -> None:
        """The monitor thread is joined on close — no leaked thread."""
        store = _make_store(idle_unload_s=900)
        assert store._idle_thread is not None
        assert store._idle_thread.is_alive()
        store.close()
        assert store._idle_thread is None

    def test_close_zeroes_resident_buffers(self) -> None:
        """Any plaintext vectors still resident at close are zeroed in place."""
        store = _make_store()
        _seed_store(store)
        refs = list(store._embed_cache.values())
        assert any(not (arr == 0).all() for arr in refs)
        store.close()
        for arr in refs:
            assert (arr == 0).all(), "close() did not scrub the resident embedding buffers"

    def test_close_is_idempotent(self) -> None:
        store = _make_store(idle_unload_s=900)
        store.close()
        store.close()  # second close must not raise


# ---------------------------------------------------------------------------
# 7. Persistence: idle-unload + reopen still decrypts correctly (tmp_path)
# ---------------------------------------------------------------------------


class TestPersistenceWithUnload:
    def test_unload_reload_then_reopen_on_disk(self, tmp_path: Path) -> None:
        """A disk-backed store survives unload/reload AND a close+reopen cycle."""
        db = str(tmp_path / "enc_idle.db")
        cipher = _make_cipher()
        s1 = _make_store(db, cipher)
        _seed_store(s1)
        pre = s1.retrieve("engine pistons", k_docs=1, k_turns=0)
        s1.unload_embed_cache()
        mid = s1.retrieve("engine pistons", k_docs=1, k_turns=0)
        assert [(h.text, round(h.score, 6)) for h in pre] == [
            (h.text, round(h.score, 6)) for h in mid
        ]
        s1.close()

        s2 = _make_store(db, cipher)
        post = s2.retrieve("engine pistons", k_docs=1, k_turns=0)
        assert [(h.text, round(h.score, 6)) for h in pre] == [
            (h.text, round(h.score, 6)) for h in post
        ]
        s2.close()
