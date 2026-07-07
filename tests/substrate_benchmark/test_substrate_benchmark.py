"""Tests for the Substrate perf benchmark harness (Vikunja #542).

Fast unit tests (default suite) use a fake embedder — they validate corpus
seeding, retrieval summary shape, the temp-store safety guard, and that a
produced record passes the community-grade perf_contrib schema.

The real-model end-to-end benchmark is marked ``slow`` + ``hardware`` and
skipped when the bge-small model is absent; run it with
``pytest -m hardware tests/substrate_benchmark``.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from tests.substrate_benchmark import harness
from tools.perf_contrib.schema import validate

# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------

requires_model = pytest.mark.skipif(
    not harness.MODEL_AVAILABLE,
    reason="bge-small-en-v1.5 ONNX FP16 model not available",
)


def fake_embed(texts: list[str]) -> np.ndarray:
    """Deterministic-shape fake embedder: (N, 384) L2-normalised float32."""
    out = np.zeros((len(texts), 384), dtype=np.float32)
    for i, text in enumerate(texts):
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        vec = rng.standard_normal(384).astype(np.float32)
        out[i] = vec / (np.linalg.norm(vec) + 1e-8)
    return out


@pytest.fixture()
def fake_store() -> Any:
    from services.assistant_orchestrator.src.substrate import SubstrateStore

    store = SubstrateStore(db_path=":memory:", embed_fn=fake_embed)
    yield store
    store.close()


# ---------------------------------------------------------------------------
# A. Corpus seeding + retrieval shape (fast, no model)
# ---------------------------------------------------------------------------


def test_seed_corpus_counts(fake_store: Any) -> None:
    total = harness.seed_corpus(fake_store, n_doc_chunks=10, n_turns=15)
    assert total == 25
    assert fake_store.count("doc") == 10
    assert fake_store.count("turn") == 15


def test_measure_retrieval_returns_summary(fake_store: Any) -> None:
    harness.seed_corpus(fake_store, n_doc_chunks=20, n_turns=20)
    stats = harness.measure_retrieval(fake_store, repeats=2)
    for key in ("count", "min_ms", "mean_ms", "p50_ms", "p95_ms", "max_ms", "total_chunks"):
        assert key in stats
    assert stats["count"] == len(harness.REPRESENTATIVE_PROMPTS) * 2
    assert stats["total_chunks"] == 40
    assert stats["p95_ms"] >= stats["p50_ms"] >= 0.0


def test_warm_embed_summary() -> None:
    stats = harness.measure_warm_embed_ms(fake_embed, samples=5)
    assert stats["count"] == 5
    assert stats["mean_ms"] >= 0.0


# ---------------------------------------------------------------------------
# B. Temp-store safety guard (critical: never touch the real substrate.db)
# ---------------------------------------------------------------------------


def test_open_temp_store_lives_under_tempdir() -> None:
    import tempfile
    from pathlib import Path

    store, db_path = harness.open_temp_store(fake_embed)
    try:
        resolved = Path(db_path).resolve()
        assert Path(tempfile.gettempdir()).resolve() in resolved.parents
    finally:
        store.close()


def test_guard_rejects_real_substrate_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    real_db = tmp_path / "BlarAI" / "substrate.db"
    with pytest.raises(RuntimeError, match="refused to open the real substrate.db"):
        harness._assert_not_real_substrate(str(real_db))


def test_guard_rejects_non_temp_path() -> None:
    # A path outside the system temp root must be rejected even if not the real db.
    # The repo root is not under tempfile.gettempdir(), so it must be refused.
    stray = harness._REPO_ROOT / "stray_should_be_rejected.db"
    with pytest.raises(RuntimeError, match="must live under"):
        harness._assert_not_real_substrate(str(stray))


def test_guard_rejects_blarai_db_with_localappdata_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Hardened guard: even with LOCALAPPDATA unset (non-Windows CI) and the path
    # under the temp root, any .../BlarAI/substrate.db must still be refused.
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    sneaky = tmp_path / "BlarAI" / "substrate.db"
    with pytest.raises(RuntimeError, match="BlarAI/substrate.db path"):
        harness._assert_not_real_substrate(str(sneaky))


# ---------------------------------------------------------------------------
# C. Record passes the community-grade perf_contrib schema
# ---------------------------------------------------------------------------


def test_record_validates_against_perf_contrib_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Redirect the perf-record output dir so the unit test never litters docs/.
    monkeypatch.setattr("tests.harness.latency.PERF_DIR", tmp_path)
    measurements = {
        "embedder_load": {"isolated_total_ms": 6251.0, "marginal_total_ms": 325.0},
        "retrieval_by_scale": {"small_100": {"p50_ms": 5.1, "p95_ms": 7.0, "total_chunks": 100}},
    }
    out = harness.record(measurements, when_iso="2026-06-04T12:00:00+00:00")
    record = json.loads(out.read_text(encoding="utf-8"))
    result = validate(record)
    assert result.valid, str(result)


# ---------------------------------------------------------------------------
# D. Real-model end-to-end benchmark (slow + hardware; skipped without model)
# ---------------------------------------------------------------------------


@requires_model
@pytest.mark.slow
@pytest.mark.hardware
def test_real_embedder_load_and_retrieval(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr("tests.harness.latency.PERF_DIR", tmp_path)

    measurements = harness.run_full_benchmark(scales=(("small_100", 50, 50),))

    load = measurements["embedder_load"]
    # The crux: marginal load (transformers cached) << isolated load.
    assert load["marginal_total_ms"] < load["isolated_total_ms"]
    assert load["import_transformers_ms"] > load["ort_session_construct_ms"]
    # Magnitude, not just direction: the marginal load is sub-1.5s (the #553
    # finding is ~0.3s), categorically not the 5-8s isolated cost.
    assert load["marginal_total_ms"] < 1500, load

    retr = measurements["retrieval_by_scale"]["small_100"]
    assert retr["total_chunks"] == 100
    assert retr["p95_ms"] > 0.0

    out = harness.record(measurements, when_iso="2026-06-04T12:00:00+00:00")
    assert validate(json.loads(out.read_text(encoding="utf-8"))).valid
