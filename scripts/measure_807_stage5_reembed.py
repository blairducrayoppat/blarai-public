"""
PGOV Stage-5 re-embed cost — measure-first harness for Vikunja #807
===================================================================
AUDIT-8 (System Qualities Audit, Performance #5): ``LeakageDetector.
check_leakage`` re-embeds the generated text PLUS every retrieved
(UNTRUSTED_EXTERNAL) chunk on EVERY grounded response, although the chunk
set is session-stable between turns.  The ticket's own verdict is MEASURE
FIRST: this harness times the production Stage-5 surface on CPU so the
before/after delta of the embedding-reuse fix is a recorded number, not a
guess.

What it drives (the PRODUCTION surface, not a synthetic pipeline)
  - ``LeakageDetector(device="CPU")`` → ``load_model()`` → the ONNX Runtime
    CPUExecutionProvider path with the production session options
    (intra_op=2 / inter_op=1) — exactly the executor a CPU-configured (or
    CPU-defaulted, the #807 device-threading limb) Stage 5 runs.
  - Per simulated grounded turn: ``check_leakage(generated_text_t, chunks)``
    with a session-stable chunk set — the shape
    ``entrypoint._handle_generate`` feeds from
    ``context_manager.get_untrusted_chunk_texts``.

Scenarios: N chunks in {1, 2, 4, 8, 16, 32} (a pasted external article
grounds as a handful of chunks; 32 is the heavy tail), T turns per session
(default 12: 2 warmup + 10 timed).  The corpus is seeded-deterministic so a
``--label before`` run and a ``--label after`` run see byte-identical
inputs — the per-turn scores recorded in the JSON double as the semantics
regression evidence (same verdicts, score deltas reportable to the bit).

What IS measured
  - Warm per-turn ``check_leakage`` wall time per N (mean/median/stdev over
    the timed turns; turn-1 cold time reported separately — after the fix
    turn 1 still embeds the full chunk set, so cold vs warm is the honest
    split).
  - One-shot attribution: ``_embed([generated_text])`` alone vs
    ``_embed(chunks)`` alone (which component the reuse removes).
  - Per-turn leakage scores + >=0.85 verdicts (semantics evidence).
  - ``load_model()`` wall time (context; not the ticket's subject).

What is NOT measured (named, per the testing-data-capture rule)
  - The NPU / GPU offload path (#720): this harness is CPU-only by design —
    a live battery pass owns the GPU, and the NPU-path live verify is a
    separate coordinator-run hardware slot.  The 13.6x figure cited in #807
    is the 2026-07-02 measurement (docs/performance/
    embedding_device_2026-07-02_00-10-26.json), not re-measured here.
  - Co-resident contention (embedding while the 14B generates) — isolation
    run only.
  - The full ``validate_output`` pipeline (Stages 1-4/6 are regex/string
    passes, micro vs the embed cost); this times Stage 5 proper.
  - Real end-to-end grounded-turn latency on the Arc 140V (model generation
    dominates; this harness isolates the Stage-5 fraction's absolute cost).

Usage (from a repo root with the BlarAI venv; the bge model is gitignored —
point --model at a checkout that has it when running from a worktree):
  python scripts/measure_807_stage5_reembed.py --label before \
      --model C:/Users/mrbla/blarai/models/bge-small-en-v1.5/onnx-fp16/model.onnx

Output: community-grade JSON under docs/performance/
  pgov_stage5_reembed_807_<label>_<timestamp>.json
plus a human summary table on stdout.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

_CHUNK_COUNTS: tuple[int, ...] = (1, 2, 4, 8, 16, 32)
_WARMUP_TURNS: int = 2

# Seeded word bank for deterministic pseudo-prose (realistic tokenizer load,
# byte-identical across runs — the before/after score diff depends on it).
_WORDS: tuple[str, ...] = (
    "the", "quarterly", "report", "memory", "ceiling", "firmware", "device",
    "measured", "throughput", "latency", "pipeline", "governance", "chunk",
    "embedding", "hardware", "local", "model", "inference", "session",
    "budget", "decode", "draft", "window", "cache", "substrate", "knowledge",
    "external", "article", "vendor", "release", "notes", "kernel", "driver",
    "compile", "static", "dynamic", "batch", "token", "cosine", "threshold",
    "verdict", "grounded", "response", "operator", "archive", "paragraph",
)


def _prose(rng: np.random.RandomState, n_words: int) -> str:
    """Deterministic pseudo-prose: seeded draws from the word bank."""
    words = [str(_WORDS[int(i)]) for i in rng.randint(0, len(_WORDS), n_words)]
    out: list[str] = []
    for i, w in enumerate(words):
        if i % 12 == 0:
            w = w.capitalize()
            if i:
                out[-1] = out[-1] + "."
        out.append(w)
    return " ".join(out) + "."


def _build_corpus(
    n_chunks: int, n_turns: int, seed: int
) -> tuple[list[str], list[str]]:
    """Build (chunks, per-turn generated texts) — all seeded-deterministic.

    Chunks: ~300 words (~1800 chars) each — a pasted-article paragraph scale
    (Stage-5 truncates at its 128-token calibrated window; raw length still
    exercises realistic tokenizer cost).  Generated texts: ~110 words each,
    distinct per turn.  Turn 2 (index 1) deliberately echoes a verbatim
    chunk prefix so the >=0.85 verdict fires on at least one turn (both
    verdict polarities appear in the semantics evidence).
    """
    rng = np.random.RandomState(seed)
    chunks = [_prose(rng, 300) for _ in range(n_chunks)]
    gens: list[str] = []
    for turn in range(n_turns):
        text = _prose(rng, 110)
        if turn == 1:
            # Verbatim leak shape: echo the first ~90 words of chunk 0.
            text = " ".join(chunks[0].split()[:90])
        gens.append(text)
    return chunks, gens


def _measure_scenario(
    detector: Any, n_chunks: int, n_turns: int, seed: int
) -> dict[str, Any]:
    """Simulate one grounded session: stable chunk set, fresh text per turn."""
    chunks, gens = _build_corpus(n_chunks, n_turns, seed)

    turn_ms: list[float] = []
    scores: list[float] = []
    for gen_text in gens:
        t0 = time.perf_counter()
        score = detector.check_leakage(gen_text, chunks, 0.85)
        turn_ms.append((time.perf_counter() - t0) * 1000.0)
        scores.append(float(score))

    timed = turn_ms[_WARMUP_TURNS:]

    # One-shot component attribution (post-run; model warm): what the reuse
    # fix removes is the chunks leg.
    t0 = time.perf_counter()
    detector._embed([gens[-1]])  # noqa: SLF001 — deliberate production-path probe
    gen_embed_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    detector._embed(chunks)  # noqa: SLF001 — deliberate production-path probe
    chunks_embed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "n_chunks": n_chunks,
        "n_turns": n_turns,
        "turn1_cold_ms": round(turn_ms[0], 3),
        "timed_turns": len(timed),
        "per_turn_ms_mean": round(statistics.mean(timed), 3),
        "per_turn_ms_median": round(statistics.median(timed), 3),
        "per_turn_ms_stdev": round(statistics.stdev(timed), 3)
        if len(timed) > 1
        else 0.0,
        "per_turn_ms_min": round(min(timed), 3),
        "per_turn_ms_max": round(max(timed), 3),
        "attribution_gen_only_embed_ms": round(gen_embed_ms, 3),
        "attribution_chunks_only_embed_ms": round(chunks_embed_ms, 3),
        "scores_by_turn": [round(s, 8) for s in scores],
        "verdicts_by_turn": [bool(s >= 0.85) for s in scores],
    }


def _environment() -> dict[str, Any]:
    import onnxruntime
    import transformers

    return {
        "cpu": platform.processor(),
        "machine": platform.machine(),
        "os": f"{platform.system()} {platform.version()}",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "onnxruntime": onnxruntime.__version__,
        "transformers": transformers.__version__,
        "note": (
            "CPU-only run (ONNX Runtime CPUExecutionProvider, production "
            "session options intra_op=2/inter_op=1). GPU/NPU deliberately "
            "untouched — battery campaign owns the GPU; NPU live verify is "
            "a separate hardware slot."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(
            _REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"
        ),
        help="Path to the bge-small-en-v1.5 ONNX fp16 model file.",
    )
    parser.add_argument(
        "--label",
        required=True,
        help="Run label stamped into the artifact, e.g. 'before' / 'after'.",
    )
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--seed", type=int, default=807)
    parser.add_argument(
        "--out-dir",
        default=str(_REPO_ROOT / "docs" / "performance"),
        help="Directory for the JSON artifact.",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: model not found: {model_path}", file=sys.stderr)
        return 2

    from services.assistant_orchestrator.src.pgov import LeakageDetector

    detector = LeakageDetector(model_path=str(model_path), device="CPU")
    t0 = time.perf_counter()
    if not detector.load_model():
        print("ERROR: load_model() failed.", file=sys.stderr)
        return 2
    load_ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"Loaded {model_path.name} on {detector.active_device} "
        f"(backend={detector.backend}) in {load_ms:.0f} ms"
    )

    scenarios: list[dict[str, Any]] = []
    for n_chunks in _CHUNK_COUNTS:
        # Fresh detector state per scenario so a chunk-embedding cache (the
        # #807 fix) starts cold for every N — turn 1 is the honest cold cost.
        # Model stays loaded; only per-instance caches would reset, so use a
        # new instance per scenario to keep before/after runs symmetric.
        scenario_detector = LeakageDetector(model_path=str(model_path), device="CPU")
        if not scenario_detector.load_model():
            print("ERROR: scenario load_model() failed.", file=sys.stderr)
            return 2
        result = _measure_scenario(scenario_detector, n_chunks, args.turns, args.seed)
        scenarios.append(result)
        print(
            f"N={n_chunks:>2} chunks: turn1(cold)={result['turn1_cold_ms']:>8.1f} ms  "
            f"warm/turn mean={result['per_turn_ms_mean']:>8.1f} ms  "
            f"median={result['per_turn_ms_median']:>8.1f} ms  "
            f"[gen-only {result['attribution_gen_only_embed_ms']:.1f} ms, "
            f"chunks-only {result['attribution_chunks_only_embed_ms']:.1f} ms]"
        )
        scenario_detector.unload()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    artifact = {
        "benchmark": "pgov_stage5_reembed_807",
        "label": args.label,
        "timestamp": timestamp,
        "model": "BAAI/bge-small-en-v1.5 ONNX fp16 (384-dim)",
        "surface": (
            "services.assistant_orchestrator.src.pgov.LeakageDetector"
            ".check_leakage — the PGOV Stage-5 leakage control"
        ),
        "methodology": {
            "shape": (
                "Simulated grounded session per N: session-stable chunk set "
                "(the get_untrusted_chunk_texts shape), fresh ~110-word "
                "generated text per turn, check_leakage(gen, chunks) timed "
                "per turn with time.perf_counter."
            ),
            "chunk_counts": list(_CHUNK_COUNTS),
            "turns_per_session": args.turns,
            "warmup_turns_excluded": _WARMUP_TURNS,
            "chunk_words": 300,
            "corpus": f"seeded-deterministic (seed={args.seed}); byte-identical across labels",
            "device": "CPU (ONNX Runtime CPUExecutionProvider)",
            "fresh_detector_per_scenario": True,
            "model_load_ms": round(load_ms, 1),
        },
        "environment": _environment(),
        "results": scenarios,
        "not_measured": [
            "NPU/GPU offload path (#720) — CPU-only run; NPU live verify is a "
            "separate coordinator-run hardware slot",
            "co-resident 14B contention (isolation run)",
            "Stages 1-4/6 of validate_output (regex/string passes)",
            "end-to-end grounded-turn latency on the Arc 140V",
        ],
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"pgov_stage5_reembed_807_{args.label}_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    print(f"\nArtifact: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
