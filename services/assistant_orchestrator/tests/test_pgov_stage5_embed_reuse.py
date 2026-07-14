"""
PGOV Stage-5 embedding reuse + device threading — regression locks (#807).

AUDIT-8 (System Qualities Audit, Performance #5) found two defects on the
Stage-5 leakage path:

  1. ``LeakageDetector.check_leakage`` re-embedded the generated text PLUS
     every retrieved chunk on EVERY grounded response, although the chunk
     set (``context_manager.get_untrusted_chunk_texts``) is session-stable
     between turns.  Measured 2026-07-11 on CPU (see docs/performance/
     pgov_stage5_reembed_807_before_*.json): the chunks leg was ~54-95% of
     every call — e.g. 1231 ms of a 1368 ms Stage 5 at 16 chunks.
     Fix: a per-detector LRU chunk-embedding cache — each unique chunk text
     embeds ONCE per detector lifetime; only the generated text embeds
     fresh each turn.

  2. The module-level ``check_leakage() -> _get_detector()`` path defaulted
     ``device="CPU"``, silently bypassing the #720 NPU offload for any
     singleton it created.  Fix: the AO entrypoint stamps the resolved
     ``[embeddings].device`` via ``set_default_embedding_device`` at
     start(); ``_get_detector(None)`` honours the stamp.

SEMANTICS ARE THE CONTRACT: the leakage verdicts must be unchanged.  The
locks below drive the NEW code against a reference implementation of the
PRE-#807 composition (embed-everything-fresh) over a fixture corpus and
assert bit-identical scores — a cold cache reproduces the old batch
composition exactly, and cache hits return the very vectors that batch
produced.

TEETH CHECK (lesson 30): ``test_teeth_reference_detects_a_semantics_break``
proves the reference-comparison harness FAILS when the composition is
deliberately broken, so the equality locks are not vacuous.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from services.assistant_orchestrator.src import pgov
from services.assistant_orchestrator.src.pgov import (
    LeakageDetector,
    set_default_embedding_device,
    set_leakage_detector,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# Deterministic fake embedding (mirrors the established test_pgov.py pattern)
# ---------------------------------------------------------------------------


def _hash_embed(texts: list[str]) -> Any:
    """Deterministic per-text unit vectors — stable across calls/batches."""
    vecs = []
    for t in texts:
        rng = np.random.RandomState(abs(hash(t)) % (2**31))
        v = rng.randn(384).astype(np.float32)
        v /= np.linalg.norm(v)
        vecs.append(v)
    return np.stack(vecs)


class _CountingEmbed:
    """Wraps an embed fn; records every batch it is asked to embed."""

    def __init__(self, inner: Callable[[list[str]], Any]) -> None:
        self.inner = inner
        self.batches: list[list[str]] = []

    def __call__(self, texts: list[str]) -> Any:
        self.batches.append(list(texts))
        return self.inner(texts)


def _make_detector(embed: Callable[[list[str]], Any]) -> LeakageDetector:
    d = LeakageDetector()
    d._embed = embed  # type: ignore[assignment]
    d._loaded = True
    return d


def _reference_max_cosine(
    embed: Callable[[list[str]], Any], generated_text: str, chunks: list[str]
) -> float:
    """The PRE-#807 check_leakage composition, verbatim: embed the generated
    text and ALL chunks fresh, max of the pairwise cosines."""
    gen_emb = embed([generated_text])
    chunk_embs = embed(chunks)
    return float(np.max((chunk_embs @ gen_emb.T).flatten()))


# Fixture corpus: (generated_text, chunks) — varying N, duplicate chunks,
# an exact echo (verdict fires), and disjoint prose (verdict silent).
_CORPUS: list[tuple[str, list[str]]] = [
    ("the memory ceiling is 31.323 GB", ["the memory ceiling is 31.323 GB"]),
    ("a summary of the vendor release notes", ["vendor release notes text"]),
    (
        "the quarterly report discusses throughput",
        [
            "quarterly report body about latency",
            "an unrelated article about kernels",
            "the quarterly report discusses throughput",
        ],
    ),
    (
        "fresh prose with no overlap at all",
        ["chunk alpha", "chunk beta", "chunk gamma", "chunk delta"],
    ),
    (
        "duplicate chunks must not break the stack",
        ["same chunk text", "same chunk text", "other chunk"],
    ),
    (
        "a longer generated answer " * 20,
        [f"external article paragraph {i} " * 30 for i in range(6)],
    ),
]


# ---------------------------------------------------------------------------
# Semantics locks — new code vs the pre-#807 reference composition
# ---------------------------------------------------------------------------


class TestSemanticsUnchanged:
    def test_scores_bit_identical_to_reference_over_corpus(self) -> None:
        for gen_text, chunks in _CORPUS:
            d = _make_detector(_hash_embed)  # fresh detector = cold cache
            got = d.check_leakage(gen_text, chunks, _THRESHOLD)
            want = _reference_max_cosine(_hash_embed, gen_text, chunks)
            assert got == want, (gen_text[:40], chunks[:1])
            assert (got >= _THRESHOLD) == (want >= _THRESHOLD)

    def test_scores_bit_identical_across_turns_stable_chunks(self) -> None:
        """A simulated session: same chunk set, fresh text per turn — every
        turn's score must equal the reference (which re-embeds fresh)."""
        chunks = [f"session chunk {i} about the substrate" for i in range(5)]
        d = _make_detector(_hash_embed)
        for turn in range(8):
            gen_text = f"turn {turn} generated answer about the pipeline"
            got = d.check_leakage(gen_text, chunks, _THRESHOLD)
            want = _reference_max_cosine(_hash_embed, gen_text, chunks)
            assert got == want

    def test_scores_bit_identical_when_chunk_set_grows(self) -> None:
        """Mid-session /external paste: new chunks join, old are cached —
        scores must still equal the fresh-embed reference (the fake embeds
        per-text deterministically, so batch composition is score-neutral
        here; real-model batch neutrality is covered by the slow test)."""
        d = _make_detector(_hash_embed)
        chunks = ["first article chunk", "second article chunk"]
        d.check_leakage("turn one text", chunks, _THRESHOLD)
        grown = [*chunks, "a later pasted chunk", "and one more"]
        got = d.check_leakage("turn two text", grown, _THRESHOLD)
        want = _reference_max_cosine(_hash_embed, "turn two text", grown)
        assert got == want

    def test_verdict_boundary_locked_at_threshold(self) -> None:
        """Engineered cosines just below / at the 0.85 threshold: the new
        path must yield the same score AND the same verdict as the
        reference."""
        base = np.zeros(384, dtype=np.float32)
        base[0] = 1.0
        for target_cos in (0.8499, 0.85, 0.8501):
            gen_vec = np.zeros(384, dtype=np.float32)
            gen_vec[0] = target_cos
            gen_vec[1] = np.sqrt(1.0 - target_cos * target_cos)

            def fixed_embed(
                texts: list[str],
                _gen: Any = gen_vec,
                _chunk: Any = base,
            ) -> Any:
                return np.stack(
                    [_gen if t.startswith("GEN") else _chunk for t in texts]
                )

            d = _make_detector(fixed_embed)
            got = d.check_leakage("GEN text", ["chunk text"], _THRESHOLD)
            want = _reference_max_cosine(fixed_embed, "GEN text", ["chunk text"])
            assert got == want
            assert (got >= _THRESHOLD) == (want >= _THRESHOLD)

    def test_teeth_reference_detects_a_semantics_break(self) -> None:
        """TEETH: if the composition ever drifted (e.g. mean instead of max),
        the reference comparison above would FAIL — prove it can."""
        gen_text = "the quarterly report discusses throughput"
        chunks = [
            "quarterly report body about latency",
            "an unrelated article about kernels",
            "the quarterly report discusses throughput",
        ]
        gen_emb = _hash_embed([gen_text])
        chunk_embs = _hash_embed(chunks)
        broken = float(np.mean((chunk_embs @ gen_emb.T).flatten()))
        want = _reference_max_cosine(_hash_embed, gen_text, chunks)
        assert broken != want

    def test_empty_inputs_and_fail_closed_unchanged(self) -> None:
        d = _make_detector(_hash_embed)
        assert d.check_leakage("", ["chunk"], _THRESHOLD) == 0.0
        assert d.check_leakage("text", [], _THRESHOLD) == 0.0

        unloaded = LeakageDetector(model_path="nonexistent/model.onnx")
        assert unloaded.check_leakage("text", ["chunk"], _THRESHOLD) == 1.0

    def test_embed_failure_on_chunks_leg_fails_closed(self) -> None:
        """The gen embed succeeding must not open a fail-soft window if the
        chunks leg then crashes — still 1.0."""
        calls: list[int] = []

        def embed_then_fail(texts: list[str]) -> Any:
            calls.append(len(texts))
            if len(calls) > 1:
                raise RuntimeError("chunks-leg crash")
            return _hash_embed(texts)

        d = _make_detector(embed_then_fail)
        assert d.check_leakage("text", ["chunk"], _THRESHOLD) == 1.0


# ---------------------------------------------------------------------------
# Reuse behaviour — the perf property itself
# ---------------------------------------------------------------------------


class TestChunkEmbeddingReuse:
    def test_stable_chunks_embed_once_across_turns(self) -> None:
        counting = _CountingEmbed(_hash_embed)
        d = _make_detector(counting)
        chunks = [f"chunk {i}" for i in range(4)]

        for turn in range(5):
            d.check_leakage(f"turn {turn}", chunks, _THRESHOLD)

        chunk_batches = [b for b in counting.batches if b and b[0].startswith("chunk")]
        gen_batches = [b for b in counting.batches if b and b[0].startswith("turn")]
        assert chunk_batches == [chunks]  # the full set embedded exactly once
        assert len(gen_batches) == 5  # generated text embeds fresh every turn
        assert all(len(b) == 1 for b in gen_batches)

    def test_cold_cache_first_turn_preserves_batch_composition(self) -> None:
        """Turn 1 must embed ALL chunks in ONE batch, exactly as the
        pre-#807 code did — the numerics-preservation property."""
        counting = _CountingEmbed(_hash_embed)
        d = _make_detector(counting)
        chunks = ["alpha", "beta", "gamma"]
        d.check_leakage("gen text", chunks, _THRESHOLD)
        assert ["alpha", "beta", "gamma"] in counting.batches

    def test_growing_chunk_set_embeds_only_the_new_chunks(self) -> None:
        counting = _CountingEmbed(_hash_embed)
        d = _make_detector(counting)
        d.check_leakage("turn one", ["old A", "old B"], _THRESHOLD)
        counting.batches.clear()

        d.check_leakage("turn two", ["old A", "old B", "new C"], _THRESHOLD)
        assert ["new C"] in counting.batches
        flat = [t for b in counting.batches for t in b]
        assert "old A" not in flat and "old B" not in flat

    def test_duplicate_chunk_texts_share_one_vector(self) -> None:
        d = _make_detector(_hash_embed)
        embs = d._chunk_embeddings(["same text", "same text", "other"])
        assert embs.shape == (3, 384)
        assert np.array_equal(embs[0], embs[1])

    def test_lru_eviction_bounds_the_cache(self) -> None:
        d = _make_detector(_hash_embed)
        # Instance override of the class bound — keeps the probe small.
        d._CHUNK_CACHE_MAX = 3  # type: ignore[misc]
        d.check_leakage("gen", ["c1", "c2", "c3"], _THRESHOLD)
        assert len(d._chunk_embed_cache) == 3

        # c4 arrives; the least recently used (c1) must make room.
        counting = _CountingEmbed(_hash_embed)
        d._embed = counting  # type: ignore[assignment]
        d.check_leakage("gen", ["c2", "c3", "c4"], _THRESHOLD)
        assert len(d._chunk_embed_cache) == 3
        assert ["c4"] in counting.batches

        # c1 was evicted -> a re-encounter re-embeds it.
        counting.batches.clear()
        d.check_leakage("gen", ["c1"], _THRESHOLD)
        assert ["c1"] in counting.batches

    def test_lru_hit_refreshes_recency(self) -> None:
        d = _make_detector(_hash_embed)
        d._CHUNK_CACHE_MAX = 2  # type: ignore[misc]
        d.check_leakage("gen", ["c1"], _THRESHOLD)
        d.check_leakage("gen", ["c2"], _THRESHOLD)
        d.check_leakage("gen", ["c1"], _THRESHOLD)  # touch c1 -> c2 is now LRU

        counting = _CountingEmbed(_hash_embed)
        d._embed = counting  # type: ignore[assignment]
        d.check_leakage("gen", ["c3"], _THRESHOLD)  # evicts c2, not c1
        counting.batches.clear()
        d.check_leakage("gen", ["c1"], _THRESHOLD)
        assert counting.batches == [["gen"]]  # c1 still cached — no re-embed

    def test_unload_zeroes_and_clears_the_cache(self) -> None:
        d = _make_detector(_hash_embed)
        d.check_leakage("gen", ["c1", "c2"], _THRESHOLD)
        held = list(d._chunk_embed_cache.values())
        assert held and any(np.any(v != 0) for v in held)

        d.unload()
        assert len(d._chunk_embed_cache) == 0
        assert all(np.all(v == 0) for v in held)  # buffers zeroed, not just dropped


# ---------------------------------------------------------------------------
# Device threading — the module-creation path honours [embeddings].device
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_pgov_module_state():
    """Save/restore the pgov module singleton + device stamp around a test."""
    prior_detector = pgov._detector
    prior_default = pgov._default_device
    pgov._detector = None
    pgov._default_device = None
    try:
        yield
    finally:
        pgov._detector = prior_detector
        pgov._default_device = prior_default


@pytest.mark.usefixtures("_clean_pgov_module_state")
class TestDefaultDeviceStamp:
    def test_no_stamp_defaults_cpu(self) -> None:
        d = pgov._get_detector()
        assert d._device == "CPU"

    def test_stamped_device_used_at_singleton_creation(self) -> None:
        set_default_embedding_device("NPU")
        d = pgov._get_detector()
        assert d._device == "NPU"

    def test_explicit_device_wins_over_stamp(self) -> None:
        set_default_embedding_device("NPU")
        d = pgov._get_detector(device="GPU")
        assert d._device == "GPU"

    def test_stamp_normalises_case_and_whitespace(self) -> None:
        set_default_embedding_device("  npu ")
        d = pgov._get_detector()
        assert d._device == "NPU"

    def test_none_and_empty_clear_the_stamp(self) -> None:
        set_default_embedding_device("NPU")
        set_default_embedding_device(None)
        assert pgov._default_device is None
        set_default_embedding_device("NPU")
        set_default_embedding_device("")
        assert pgov._default_device is None
        d = pgov._get_detector()
        assert d._device == "CPU"

    def test_existing_singleton_unaffected_by_later_stamp(self) -> None:
        d1 = pgov._get_detector()
        set_default_embedding_device("NPU")
        d2 = pgov._get_detector()
        assert d2 is d1
        assert d2._device == "CPU"

    def test_module_check_leakage_creates_stamped_singleton(self) -> None:
        """The load-bearing #807 path: Stage 5's module-level check_leakage
        creating the singleton must honour the stamp (fail-closed 1.0 here —
        nothing loads a model)."""
        set_default_embedding_device("NPU")
        score = pgov.check_leakage("text", ["chunk"], _THRESHOLD)
        assert score == 1.0  # unloaded -> fail-closed, unchanged
        assert pgov._detector is not None
        assert pgov._detector._device == "NPU"


class TestEntrypointStampsDevice:
    @patch("services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference")
    @patch("services.assistant_orchestrator.src.entrypoint.VsockListener")
    def test_start_stamps_resolved_embeddings_device(
        self,
        mock_listener_cls: MagicMock,
        mock_inference_cls: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """start() must stamp [embeddings].device into pgov BEFORE the
        substrate/knowledge build sites run (mirrors the
        test_start_calls_model_load harness; detector creation is faked so
        no real model — and no real NPU — is ever touched)."""
        from services.assistant_orchestrator.src.entrypoint import (
            AssistantOrchestratorService,
        )

        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            """
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "models/qwen3-14b/openvino-int4-gpu"
weight_manifest = "models/qwen3-14b/openvino-int4-gpu/manifest.json"
draft_model_dir = "models/qwen3-0.6b/openvino-int4-gpu"
speculative_decoding_enabled = true

[generation]
max_new_tokens = 512
temperature = 0.0
top_k = 50
top_p = 0.9
repetition_penalty = 1.1
do_sample = false
response_depth_mode = "standard"

[security]
dev_mode = true

[ipc]
vsock_cid = 2
vsock_port = 5001
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85

[embeddings]
device = "NPU"
""".strip(),
            encoding="utf-8",
        )

        mock_inference = MagicMock()
        mock_inference.load_model.return_value = True
        mock_inference_cls.return_value = mock_inference
        mock_listener = MagicMock()
        mock_listener.start.return_value = True
        mock_listener.running = False
        mock_listener_cls.return_value = mock_listener

        stamped_at_build: list[str | None] = []

        class _UnloadedFake:
            loaded = False

            def load_model(self) -> bool:
                return False

        def _fake_get_detector(device: str | None = None) -> Any:
            # Record what the module default was when the build sites ran —
            # proves the stamp landed BEFORE them.
            stamped_at_build.append(pgov._default_device)
            return _UnloadedFake()

        monkeypatch.setattr(pgov, "_get_detector", _fake_get_detector)

        prior_default = pgov._default_device
        service = AssistantOrchestratorService(config_path)
        try:
            assert service.start() is True
            assert pgov._default_device == "NPU"
            assert stamped_at_build and all(
                seen == "NPU" for seen in stamped_at_build
            )
        finally:
            service.stop()
            pgov._default_device = prior_default


# ---------------------------------------------------------------------------
# Real-model numerics probe (deliberate runs only — @slow; skips when the
# gitignored bge model is absent, e.g. on isolated worktrees)
# ---------------------------------------------------------------------------


def _real_model() -> Path:
    override = os.environ.get("BLARAI_BGE_ONNX", "")
    if override:
        return Path(override)
    return _REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"


@pytest.mark.slow
@pytest.mark.skipif(
    not _real_model().exists(),
    reason="bge-small-en-v1.5 ONNX model not present (gitignored)",
)
class TestRealModelNumerics:
    """CPU-only (ONNX Runtime) — never compiles NPU/GPU."""

    def _loaded_detector(self) -> LeakageDetector:
        d = LeakageDetector(model_path=str(_real_model()), device="CPU")
        assert d.load_model() is True
        return d

    def test_cache_hit_scores_bit_identical_to_first_turn(self) -> None:
        d = self._loaded_detector()
        chunks = [
            "the quarterly report says the memory ceiling is 31.323 GB",
            "an unrelated paragraph about kernel drivers and compilers",
            "the substrate stores embeddings encrypted at rest",
        ]
        gen = "the memory ceiling stated by the quarterly report is 31.323 GB"
        first = d.check_leakage(gen, chunks, _THRESHOLD)
        second = d.check_leakage(gen, chunks, _THRESHOLD)  # cache-served
        assert second == first

    def test_growing_set_scores_match_fresh_detector_closely(self) -> None:
        """Cached-old + fresh-new batch vs one full fresh batch: same
        verdicts, scores equal to within float32 batch-composition noise."""
        chunks = [
            "external article paragraph about inference throughput",
            "a second paragraph describing latency and windows",
        ]
        grown = [*chunks, "a later pasted paragraph about token budgets"]
        gen = "an answer discussing throughput, latency and token budgets"

        d_incremental = self._loaded_detector()
        d_incremental.check_leakage("warm turn", chunks, _THRESHOLD)
        incremental = d_incremental.check_leakage(gen, grown, _THRESHOLD)

        d_fresh = self._loaded_detector()
        fresh = d_fresh.check_leakage(gen, grown, _THRESHOLD)

        assert (incremental >= _THRESHOLD) == (fresh >= _THRESHOLD)
        assert abs(incremental - fresh) < 1e-5


# ---------------------------------------------------------------------------
# Module-path composition still routed through the singleton (unchanged API)
# ---------------------------------------------------------------------------


class TestModulePathStillDelegates:
    def test_injected_detector_still_used(self) -> None:
        mock_detector = MagicMock(spec=LeakageDetector)
        mock_detector.check_leakage.return_value = 0.42
        set_leakage_detector(mock_detector)
        try:
            assert pgov.check_leakage("text", ["chunk"], _THRESHOLD) == 0.42
        finally:
            set_leakage_detector(None)  # type: ignore[arg-type]
