"""Substrate perf benchmark harness (USE-CASE-002, Vikunja #542).

Pure measurement logic. No pytest, no assertions — the test module and any
community-run CLI drive this. Reuses the embedder load path from
``pgov.LeakageDetector`` and the store from ``substrate.SubstrateStore`` so the
numbers reflect the real production code, not a re-implementation.

Safety: every store this harness opens lives under ``tempfile`` and the path is
asserted to be outside ``%LOCALAPPDATA%`` — the real substrate.db is never
touched (Vikunja #542 acceptance: benchmarks use a fresh/temp substrate).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from tests.harness.latency import Stopwatch, build_environment, summarize, write_perf_record

# Repo root: tests/substrate_benchmark/harness.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = _REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"
MODEL_AVAILABLE = MODEL_PATH.exists()

# Representative single-user retrieval prompts (memory-style questions).
REPRESENTATIVE_PROMPTS: tuple[str, ...] = (
    "what did I tell you about my sister",
    "remind me of the budget plan",
    "when is Maria's birthday",
    "what is the car service interval",
    "summarize project alpha",
    "what meetings did I mention last week",
    "what did we discuss about the garden",
    "what are my upcoming deadlines",
)

# Corpus scales: (label, doc_chunks, turns). small/medium bracket realistic
# single-user scale; large is a deliberate stress point beyond typical use.
DEFAULT_SCALES: tuple[tuple[str, int, int], ...] = (
    ("small_100", 50, 50),
    ("medium_1k", 500, 500),
    ("large_5k", 2500, 2500),
)


def _assert_not_real_substrate(db_path: str) -> None:
    """Fail-closed guard: never let a benchmark open the real substrate.db.

    Three independent conditions, any of which rejects: (1) the path equals the
    real ``%LOCALAPPDATA%\\BlarAI\\substrate.db`` when LOCALAPPDATA is set; (2) the
    path is *any* ``.../BlarAI/substrate.db`` regardless of env — covers
    LOCALAPPDATA unset (e.g. non-Windows CI) or a TEMP that nests inside it; (3)
    the path is not under the system temp root.
    """
    resolved = Path(db_path).resolve()
    local = os.environ.get("LOCALAPPDATA", "")
    if local and resolved == (Path(local) / "BlarAI" / "substrate.db").resolve():
        msg = f"benchmark refused to open the real substrate.db: {resolved}"
        raise RuntimeError(msg)
    if resolved.name == "substrate.db" and "BlarAI" in resolved.parts:
        msg = f"benchmark refused a BlarAI/substrate.db path: {resolved}"
        raise RuntimeError(msg)
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if tmp_root not in resolved.parents and resolved != tmp_root:
        msg = f"benchmark store must live under {tmp_root}, got {resolved}"
        raise RuntimeError(msg)


# ── Embedder load decomposition ─────────────────────────────────────────────


def decompose_embedder_load(model_path: str = str(MODEL_PATH)) -> tuple[Any, dict[str, float]]:
    """Load the embedder once, faithfully mirroring ``LeakageDetector.load_model``,
    timing each phase.

    Mirrors the *work* of ``services/assistant_orchestrator/src/pgov.py``
    ``LeakageDetector.load_model`` (imports, tokenizer, ONNX session, warmup) so
    the breakdown (the #553 decomposition) is observable; it does not reproduce
    that method's ``_loaded``/exception bookkeeping — :func:`marginal_reload_ms`
    calls the real ``load_model`` for a faithful end-to-end cross-check.
    Returns the loaded detector (for reuse in retrieval) and the phase timings.
    The dominant phase in a fresh process is the one-time ``transformers`` import.
    """
    from services.assistant_orchestrator.src import pgov

    phases: dict[str, float] = {}
    model_dir = str(Path(model_path).parent)

    with Stopwatch() as sw:
        import onnxruntime as ort
    phases["import_onnxruntime_ms"] = round(sw.ms, 2)

    with Stopwatch() as sw:
        from transformers import AutoTokenizer
    phases["import_transformers_ms"] = round(sw.ms, 2)

    det = pgov.LeakageDetector(model_path=model_path)

    with Stopwatch() as sw:
        det._tokenizer = AutoTokenizer.from_pretrained(model_dir)
    phases["tokenizer_from_pretrained_ms"] = round(sw.ms, 2)

    with Stopwatch() as sw:
        sess_options = ort.SessionOptions()
        sess_options.inter_op_num_threads = 1
        sess_options.intra_op_num_threads = 2
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        det._session = ort.InferenceSession(
            model_path, sess_options=sess_options, providers=["CPUExecutionProvider"]
        )
        det._input_names = [inp.name for inp in det._session.get_inputs()]
    phases["ort_session_construct_ms"] = round(sw.ms, 2)

    with Stopwatch() as sw:
        probe = det._embed(["probe"])
    phases["first_embed_warmup_ms"] = round(sw.ms, 2)
    det._loaded = True
    if probe.shape[1] != 384:  # pragma: no cover — defensive
        msg = f"unexpected embedding dim {probe.shape}"
        raise RuntimeError(msg)

    phases["isolated_total_ms"] = round(
        phases["import_onnxruntime_ms"]
        + phases["import_transformers_ms"]
        + phases["tokenizer_from_pretrained_ms"]
        + phases["ort_session_construct_ms"]
        + phases["first_embed_warmup_ms"],
        2,
    )
    return det, phases


def marginal_reload_ms(model_path: str = str(MODEL_PATH)) -> float:
    """Total ``LeakageDetector.load_model()`` time on a fresh instance *after*
    ``transformers`` is already imported — i.e. the embedder's real marginal cost
    in the running AO (where ``gpu_inference`` imported ``transformers`` at boot).

    Call only after :func:`decompose_embedder_load` (or any prior transformers
    import) so the import is warm. Uses the real ``load_model`` for fidelity.
    """
    from services.assistant_orchestrator.src import pgov

    det = pgov.LeakageDetector(model_path=model_path)
    with Stopwatch() as sw:
        det.load_model()
    return round(sw.ms, 2)


def measure_warm_embed_ms(embed_fn: Callable[[list[str]], Any], samples: int = 20) -> dict[str, float]:
    """Steady-state single-text embed latency once the model is warm."""
    vals: list[float] = []
    for _ in range(samples):
        with Stopwatch() as sw:
            embed_fn(["what did I tell you last week about the budget"])
        vals.append(sw.ms)
    return summarize(vals)


# ── Retrieval ───────────────────────────────────────────────────────────────


def seed_corpus(store: Any, n_doc_chunks: int, n_turns: int) -> int:
    """Populate *store* with a representative doc + turn corpus. Returns chunk count.

    Uses the real ``ingest_document`` / ``ingest_turn`` paths so vectors and
    layout match production. Each ~1.8 KB document yields a single chunk.
    """
    filler = (
        "Notes about project alpha, the quarterly budget, the garden, my sister "
        "Maria's birthday in June, the car service interval, and assorted meetings. "
    )
    for d in range(n_doc_chunks):
        store.ingest_document(f"doc_{d}.txt", f"Document {d}. " + filler * 12, session_id="seed")
    for ti in range(n_turns):
        store.ingest_turn(
            session_id=f"sess_{ti % 7}",
            turn_index=ti,
            user_text=f"Tell me about topic {ti}, my sister, and budget plan {ti}.",
            assistant_text=f"Here is what I recall about topic {ti}: details and figures.",
        )
    return store.count()


def measure_retrieval(
    store: Any,
    prompts: tuple[str, ...] = REPRESENTATIVE_PROMPTS,
    repeats: int = 5,
    exclude_session: str = "live_session",
) -> dict[str, Any]:
    """Time ``store.retrieve`` across *prompts* (repeated). Returns summary stats."""
    vals: list[float] = []
    for _ in range(repeats):
        for prompt in prompts:
            with Stopwatch() as sw:
                store.retrieve(prompt, exclude_session=exclude_session)
            vals.append(sw.ms)
    stats = summarize(vals)
    stats["total_chunks"] = store.count()
    return stats


def open_temp_store(embed_fn: Callable[[list[str]], Any]) -> tuple[Any, str]:
    """Open a SubstrateStore on a fresh temp db (never the real substrate.db)."""
    from services.assistant_orchestrator.src.substrate import SubstrateStore

    tmp_dir = tempfile.mkdtemp(prefix="substrate_bench_")
    db_path = str(Path(tmp_dir) / "bench_substrate.db")
    _assert_not_real_substrate(db_path)
    return SubstrateStore(db_path=db_path, embed_fn=embed_fn), db_path


# ── Full run + record ───────────────────────────────────────────────────────


def run_full_benchmark(
    scales: tuple[tuple[str, int, int], ...] = DEFAULT_SCALES,
) -> dict[str, Any]:
    """Load the real embedder, then measure load decomposition + retrieval scaling.

    Returns a measurements dict suitable for :func:`write_perf_record`.
    """
    if not MODEL_AVAILABLE:  # pragma: no cover — guarded by caller
        msg = f"embedder model not available at {MODEL_PATH}"
        raise RuntimeError(msg)

    det, load_phases = decompose_embedder_load()
    load_phases["marginal_total_ms"] = marginal_reload_ms()
    warm_embed = measure_warm_embed_ms(det._embed)

    retrieval: dict[str, Any] = {}
    for label, n_docs, n_turns in scales:
        store, _ = open_temp_store(det._embed)
        try:
            seed_corpus(store, n_docs, n_turns)
            retrieval[label] = measure_retrieval(store)
        finally:
            store.close()

    return {
        "embedder_load": load_phases,
        "warm_embed_ms": warm_embed,
        "retrieval_by_scale": retrieval,
    }


def record(measurements: dict[str, Any], when_iso: str) -> Path:
    """Write *measurements* as a community-grade perf record. Caller supplies time."""
    return write_perf_record(
        "substrate_use_case_002",
        measurements,
        when_iso=when_iso,
        model="bge-small-en-v1.5 (substrate embedder; CPU)",
        precision="ONNX FP16",
        methodology=(
            "Fresh temp substrate (never the real substrate.db); offline/air-gapped "
            "(HF_HUB_OFFLINE). Embedder load decomposed by mirroring "
            "LeakageDetector.load_model: isolated (transformers not pre-imported) vs "
            "marginal (transformers already imported, as in the real AO where "
            "gpu_inference imports it at module load for the 14B). Retrieval = "
            "store.retrieve (1 query embed + brute-force cosine over doc+turn matrices), "
            f"{len(REPRESENTATIVE_PROMPTS)} representative prompts x5 repeats per scale. "
            "CPU only; the 14B GPU path is NOT exercised here."
        ),
        notes=(
            "The '5-8s embedder load' is ~92% the one-time `transformers` import, which "
            "the 14B path (gpu_inference, module-level import) already pays at AO boot; "
            "the embedder's marginal load is ~0.3s. Retrieval is immaterial to TTFT "
            "(~1-2% at realistic single-user scale). See PERFORMANCE_LOG.md (#542)."
        ),
        extra_env={
            "embedder": "bge-small-en-v1.5 ONNX FP16 (CPU, ONNX Runtime)",
            "not_measured": [
                "GPU driver version (read from dxdiag / Device Manager; not introspectable here)",
                "co-resident memory cost when the 14B is loaded alongside",
                "real-AO end-to-end boot trace with the 14B on the GPU (avoided to not "
                "contend with the parallel security session)",
                "true cold-disk (post-reboot) transformers import; measured warm-disk",
            ],
        },
    )
