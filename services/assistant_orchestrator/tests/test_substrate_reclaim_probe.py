"""Wiring test: the #900 memory-reclaim probe fires on the substrate
embedding-cache idle-unload (Vikunja #611 path), driven through the REAL
``EncryptedSubstrateStore.unload_embed_cache()`` entry point.

GPU-free and model-free: synthetic bag-of-words embeddings (mirrored from
``test_substrate_idle_unload.py``) + a mocked memory source. Proves the probe is
reachable on this third evict path and stays silent when off (the shipped
default) — the embedding cache is CPU RAM, so this is the small-delta member of
the trio, instrumented for completeness of the reclaim picture.
"""

from __future__ import annotations

import logging
import zlib

import numpy as np
import pytest

import shared.diagnostics as diag
from services.assistant_orchestrator.src.substrate import (
    EMBED_DIM,
    EncryptedSubstrateStore,
)
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.tpm_sealer import SoftwareSealer


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(diag.RECLAIM_PROBE_ENV, raising=False)
    diag.set_reclaim_probe_enabled(None)
    yield
    diag.set_reclaim_probe_enabled(None)


def fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words embedder (no model / GPU)."""
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


def _snap(total: float, avail: float) -> dict:
    return {
        "sys_total_mb": total,
        "sys_available_mb": avail,
        "sys_used_pct": 0.0,
        "proc_rss_mb": 0.0,
    }


class ScriptedSnapshot:
    def __init__(self, snaps: list[dict]) -> None:
        self._snaps = snaps
        self.calls = 0

    def __call__(self) -> dict:
        snap = self._snaps[min(self.calls, len(self._snaps) - 1)]
        self.calls += 1
        return dict(snap)


# Small CPU-RAM reclaim (a few hundred MB, illustrative): avail 5000 → 5300.
_BEFORE = _snap(31323.0, 5000.0)
_AFTER = _snap(31323.0, 5300.0)


def _make_store(idle_unload_s: int = 0) -> EncryptedSubstrateStore:
    sealer = SoftwareSealer()
    rk = generate_recovery_key()
    env = DekEnvelope.create(sealer=sealer, recovery_key=rk)
    cipher = FieldCipher(derive_subkeys(env.unseal_dek()))
    return EncryptedSubstrateStore(
        db_path=":memory:",
        embed_fn=fake_embed,
        cipher=cipher,
        embed_cache_idle_unload_s=idle_unload_s,  # 0 ⇒ no monitor thread
    )


def _seed(store: EncryptedSubstrateStore) -> None:
    store.ingest_document("cars.txt", "engine pistons turbocharger crankshaft cylinder")
    store.ingest_turn("sess-A", 0, "my sister is named Dana", "Noted, Dana.")


class TestEmbedCacheUnloadWiring:
    def test_on_emits_reclaim_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        store = _make_store()
        _seed(store)
        with caplog.at_level(logging.INFO):
            did = store.unload_embed_cache()
        assert did is True
        assert len(store._embed_cache) == 0  # eviction still happened
        assert "MEM_RECLAIM op=substrate.embed_cache.unload" in caplog.text
        assert "reclaimed=+300MB" in caplog.text
        store.close()

    def test_off_still_unloads_silently(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        snap = ScriptedSnapshot([_BEFORE, _AFTER])
        monkeypatch.setattr(diag, "memory_snapshot", snap)
        store = _make_store()
        _seed(store)
        with caplog.at_level(logging.INFO):
            did = store.unload_embed_cache()
        assert did is True
        assert len(store._embed_cache) == 0
        assert "MEM_RECLAIM" not in caplog.text
        assert snap.calls == 0  # off ⇒ no snapshot taken
        store.close()

    def test_noop_unload_emits_no_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A second (already-unloaded) call returns False and records nothing even
        when armed."""
        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        store = _make_store()
        _seed(store)
        store.unload_embed_cache()  # first: real unload (records)
        caplog.clear()
        with caplog.at_level(logging.INFO):
            assert store.unload_embed_cache() is False  # second: no-op
        assert "MEM_RECLAIM" not in caplog.text
        store.close()
